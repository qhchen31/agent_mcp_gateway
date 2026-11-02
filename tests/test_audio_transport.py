import asyncio
import json
import ssl

import httpx
import pytest

from agent_mcp.providers import Providers
from agent_mcp.security import AgentError
from agent_mcp.tasks import TaskRequest
from tests.test_providers import adapter


@pytest.mark.parametrize("wrapped,certificate", [(False, False), (True, False), (False, True), (True, True)])
async def test_raw_and_wrapped_tls_errors_are_sanitized_without_retry(settings, files, wrapped, certificate):
    calls = []
    async def handler(request):
        calls.append(1)
        exc = (ssl.SSLCertVerificationError if certificate else ssl.SSLError)(1, "PRIVATE PROMPT TEST_SECRET")
        if wrapped:
            raise httpx.ReadError("TEST_SECRET", request=request) from exc
        raise exc
    provider, client = adapter(settings, files, handler)
    async with client:
        with pytest.raises(AgentError) as error:
            await provider.post("gemini", "/models/example:generateContent", json={})
    assert error.value.code == ("tls_certificate" if certificate else "tls_error")
    assert "TEST_SECRET" not in str(error.value) and "PRIVATE" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("url", ["https://evil.example/upload/v1beta/files", "http://generativelanguage.googleapis.com/upload/v1beta/files",
    "https://generativelanguage.googleapis.com@evil.example/v1beta/files/abc", "https://generativelanguage.googleapis.com:444/v1beta/files/abc"])
def test_upload_endpoint_cannot_redirect_credentials(url):
    with pytest.raises(AgentError):
        Providers.official_file_url(url)


@pytest.mark.parametrize("fail_generation", [False, True])
@pytest.mark.parametrize("granularity", [262144, 8388608])
async def test_large_audio_chunk_upload_reference_and_cleanup(settings, files, fail_generation, granularity):
    settings.gemini_audio_upload_threshold_bytes = 1
    path = settings.allowed_input_dirs[0] / "large.mp3"
    data = b"audio" * 120000
    path.write_bytes(data)
    uploaded = bytearray()
    events = []
    url = "https://generativelanguage.googleapis.com/upload/v1beta/files?upload_id=private-session"
    metadata = {"name": "files/testaudio", "uri": "https://generativelanguage.googleapis.com/v1beta/files/testaudio", "mimeType": "audio/mpeg", "state": "ACTIVE"}
    def handler(request):
        events.append(request.method + " " + request.url.path)
        assert request.headers["x-goog-api-key"] == "TEST_SECRET"
        if request.url.path == "/upload/v1beta/files":
            command = request.headers["x-goog-upload-command"]
            if command == "start":
                assert request.headers["x-goog-upload-header-content-length"] == str(len(data))
                return httpx.Response(200, headers={"x-goog-upload-url": url, "x-goog-upload-chunk-granularity": str(granularity)})
            assert int(request.headers["x-goog-upload-offset"]) == len(uploaded)
            assert len(request.content) <= granularity
            assert request.headers["content-length"] == str(len(request.content))
            uploaded.extend(request.content)
            return httpx.Response(200, json={"file": metadata}) if "finalize" in command else httpx.Response(200)
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        body = json.loads(request.content)
        assert body["contents"][0]["parts"][1] == {"fileData": {"mimeType": "audio/mpeg", "fileUri": metadata["uri"]}}
        assert len(request.content) < 2048
        if fail_generation:
            raise ssl.SSLError(1, "TEST_SECRET")
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "transcript"}]}}]})
    provider, client = adapter(settings, files, handler)
    async with client:
        if fail_generation:
            with pytest.raises(AgentError) as error:
                await provider.execute(TaskRequest(kind="audio", file_path=str(path), prompt="Transcribe"), settings.models["ga"])
            assert error.value.code == "tls_error"
        else:
            result = await provider.execute(TaskRequest(kind="audio", file_path=str(path), prompt="Transcribe"), settings.models["ga"])
            assert result["text"] == "transcript" and result["remote_file_deleted"]
            assert result["audio_transport"] == "files_api"
    assert uploaded == data
    assert events[-1] == "DELETE /v1beta/files/testaudio"
    assert sum("generateContent" in event for event in events) == 1


async def test_upload_failure_cancels_without_generation(settings, files):
    events = []
    def handler(request):
        command = request.headers.get("x-goog-upload-command")
        events.append(command)
        if command == "start":
            return httpx.Response(200, headers={"x-goog-upload-url": "https://generativelanguage.googleapis.com/upload/v1beta/files?upload_id=private"})
        if command == "cancel":
            return httpx.Response(200)
        raise ssl.SSLError(1, "TEST_SECRET")
    provider, client = adapter(settings, files, handler)
    async with client:
        with pytest.raises(AgentError):
            await provider.upload_audio(b"audio", "audio/mpeg")
    assert events == ["start", "upload, finalize", "cancel"]


async def test_cancelled_audio_generation_deletes_uploaded_file(settings, files, monkeypatch):
    settings.gemini_audio_upload_threshold_bytes = 0
    path = settings.allowed_input_dirs[0] / "test.mp3"
    path.write_bytes(b"audio")
    provider, client = adapter(settings, files, lambda r: httpx.Response(200))
    started, deleted = asyncio.Event(), []
    async def upload(*args):
        return {"name": "files/test", "uri": "https://generativelanguage.googleapis.com/v1beta/files/test", "state": "ACTIVE", "mimeType": "audio/mpeg"}
    async def generate(*args):
        started.set()
        await asyncio.Event().wait()
    async def delete(name):
        deleted.append(name)
        return True
    monkeypatch.setattr(provider, "upload_audio", upload)
    monkeypatch.setattr(provider, "gemini_content", generate)
    monkeypatch.setattr(provider, "delete_remote_file", delete)
    async with client:
        task = asyncio.create_task(provider.execute(TaskRequest(kind="audio", file_path=str(path), prompt="x"), settings.models["ga"]))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert deleted == ["files/test"]
