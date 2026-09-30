import base64
import json
import httpx
import pytest
from agent_mcp.providers import Providers, BASE_URLS
from agent_mcp.security import AgentError
from agent_mcp.tasks import TaskRequest

PNG = base64.b64encode(b"fake image bytes").decode()

class FakeCredentials:
    def get(self, provider):
        assert provider in {"deepseek", "gemini"}
        return "TEST_SECRET"

def adapter(settings, files, handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Providers(settings, files, FakeCredentials(), client), client

@pytest.mark.parametrize("finish,text,code", [("length", "partial", None), ("content_filter", None, "upstream_incomplete"), ("stop", None, "empty_result")])
async def test_deepseek_nullable_and_finish(settings, files, finish, text, code):
    async def handler(request):
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert request.headers["authorization"] == "Bearer TEST_SECRET"
        assert "TEST_SECRET" not in str(request.url)
        body = json.loads(request.content)
        assert body["thinking"] == {"type": "disabled"}
        assert body["max_tokens"] == 4096
        return httpx.Response(200, json={"choices": [{"finish_reason": finish, "message": {"content": text}}]})
    provider, client = adapter(settings, files, handler)
    async with client:
        if code:
            with pytest.raises(AgentError) as exc:
                await provider.execute(TaskRequest(kind="text", model="ds", prompt="x"), settings.models["ds"])
            assert exc.value.code == code
        else:
            result = await provider.execute(TaskRequest(kind="text", model="ds", prompt="x"), settings.models["ds"])
            assert result["truncated"] and result["text"] == "partial"

async def test_rate_limit_only_retries(settings, files):
    calls = []
    async def handler(request):
        calls.append(request)
        return httpx.Response(429 if len(calls) < 3 else 200, headers={"retry-after": "0"}, json={"done": True})
    provider, client = adapter(settings, files, handler)
    async with client:
        assert await provider.post("deepseek", "/chat/completions", json={}) == {"done": True}
    assert len(calls) == 3

@pytest.mark.parametrize("failure", ["timeout", "network", "http500", "http401"])
async def test_uncertain_failure_no_retry_or_secret_leak(settings, files, failure):
    calls = []
    async def handler(request):
        calls.append(1)
        if failure == "timeout":
            raise httpx.ReadTimeout("TEST_SECRET PRIVATE PROMPT", request=request)
        if failure == "network":
            raise httpx.ConnectError("TEST_SECRET", request=request)
        return httpx.Response(500 if failure == "http500" else 401, json={"error": "TEST_SECRET"})
    provider, client = adapter(settings, files, handler)
    async with client:
        with pytest.raises(AgentError) as exc:
            await provider.post("deepseek", "/chat/completions", json={})
    assert len(calls) == 1 and "TEST_SECRET" not in str(exc.value)

async def test_gemini_audio_and_edit_inline(settings, files):
    audio = settings.allowed_input_dirs[0] / "audio.wav"
    audio.write_bytes(b"audio bytes")
    image = settings.allowed_input_dirs[0] / "reference.png"
    image.write_bytes(b"ref bytes")
    async def handler(request):
        assert request.headers["x-goog-api-key"] == "TEST_SECRET"
        assert "TEST_SECRET" not in str(request.url)
        body = json.loads(request.content)
        if "responseModalities" in body["generationConfig"]:
            assert body["generationConfig"]["imageConfig"] == {"imageSize": "1K", "aspectRatio": "1:1"}
            assert base64.b64decode(body["contents"][0]["parts"][1]["inlineData"]["data"]) == b"ref bytes"
            parts = [{"text": "caption"}, {"inlineData": {"mimeType": "image/png", "data": PNG}}, {"inlineData": {"mimeType": "image/png", "data": PNG}}]
        else:
            assert base64.b64decode(body["contents"][0]["parts"][1]["inlineData"]["data"]) == b"audio bytes"
            parts = [{"thought": True, "text": "private reasoning"}, {"text": "audio summary"}]
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": parts}}], "usageMetadata": {"totalTokenCount": 12}})
    provider, client = adapter(settings, files, handler)
    async with client:
        result = await provider.execute(TaskRequest(kind="audio", model="ga", prompt="summarize", file_path=str(audio)), settings.models["ga"])
        assert result["text"] == "audio summary"
        result = await provider.execute(TaskRequest(kind="image", model="gi", prompt="edit", reference_paths=[str(image)]), settings.models["gi"])
        assert result["text"] == "caption" and len(result["artifacts"]) == 2
    assert result["artifacts"][0]["path"] != result["artifacts"][1]["path"]

async def test_gemini_encoded_size_before_network(settings, files):
    audio = settings.allowed_input_dirs[0] / "audio.wav"
    audio.write_bytes(b"x" * 500)
    settings.gemini_max_request_bytes = 600
    async def handler(request):
        pytest.fail("Oversized request must not reach network")
    provider, client = adapter(settings, files, handler)
    async with client:
        with pytest.raises(AgentError) as exc:
            await provider.execute(TaskRequest(kind="audio", model="ga", prompt="summarize", file_path=str(audio)), settings.models["ga"])
        assert exc.value.code == "request_too_large"

@pytest.mark.parametrize("response", [{"promptFeedback": {"blockReason": "SAFETY"}}, {"candidates": [{"finishReason": "SAFETY"}]}])
async def test_gemini_filter_not_success(settings, files, response):
    provider, client = adapter(settings, files, lambda request: httpx.Response(200, json=response))
    async with client:
        with pytest.raises(AgentError):
            await provider.execute(TaskRequest(kind="text", model="gt", prompt="x"), settings.models["gt"])

async def test_response_size_bound(settings, files):
    settings.max_response_bytes = 10
    provider, client = adapter(settings, files, lambda request: httpx.Response(200, content=b"x" * 100))
    async with client:
        with pytest.raises(AgentError) as exc:
            await provider.post("deepseek", "/chat/completions", json={})
    assert exc.value.code == "response_too_large"

def test_only_supported_endpoints():
    assert set(BASE_URLS) == {"deepseek", "gemini"}

@pytest.mark.parametrize("kind,enabled,grounded", [
    ("knowledge", True, True), ("knowledge", True, False),
    ("knowledge", False, False), ("text", True, False)])
async def test_search_only_for_knowledge_and_preserves_evidence(settings, files, kind, enabled, grounded):
    settings.knowledge_search_enabled = enabled
    metadata = {"webSearchQueries": ["France capital"],
        "groundingChunks": [{"web": {"uri": "https://example.com/fact", "title": "Source"}}],
        "groundingSupports": [{"segment": {"text": "Paris"}, "groundingChunkIndices": [0]}],
        "searchEntryPoint": {"renderedContent": "<div>Search suggestions</div>"}}
    def handler(request):
        body = json.loads(request.content)
        if kind == "knowledge" and enabled:
            assert body["tools"] == [{"google_search": {}}]
        else:
            assert "tools" not in body
        candidate = {"finishReason": "STOP", "content": {"parts": [{"text": "Paris"}]}}
        if grounded:
            candidate["groundingMetadata"] = metadata
        return httpx.Response(200, json={"candidates": [candidate]})
    provider, client = adapter(settings, files, handler)
    async with client:
        result = await provider.execute(TaskRequest(kind=kind, prompt="France capital"), settings.models["gk" if kind == "knowledge" else "gt"])
    if kind == "knowledge":
        assert result["search_enabled"] is enabled
        assert result["live_search"] is grounded
        assert result["knowledge_source"] == ("web" if grounded else "model")
        assert result["grounding_metadata"] == (metadata if grounded else {})
        assert result["sources"] == ([metadata["groundingChunks"][0]["web"]] if grounded else [])
    else:
        assert "live_search" not in result
