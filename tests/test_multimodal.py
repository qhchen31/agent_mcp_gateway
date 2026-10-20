import base64
import io
import json
import wave
from pathlib import Path

import httpx
import pytest
from pypdf import PdfReader, PdfWriter

from agent_mcp.security import AgentError
from agent_mcp.tasks import TaskManager, TaskRequest
from tests.test_providers import adapter


def make_pdf(path):
    writer = PdfWriter()
    for width in (100, 200, 300):
        writer.add_blank_page(width=width, height=400)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 2400)
    return output.getvalue()


def test_pdf_selection_and_limits(settings, files):
    path = make_pdf(settings.allowed_input_dirs[0] / "test.pdf")
    data, selected, count = files.prepare_pdf(str(path), [3, 1])
    pdf = PdfReader(io.BytesIO(data))
    assert [float(page.mediabox.width) for page in pdf.pages] == [300, 100]
    assert selected == [3, 1] and count == 3
    for pages in ([], [0], [4], [1, 1]):
        with pytest.raises(AgentError):
            files.prepare_pdf(str(path), pages)
    settings.max_pdf_pages = 2
    with pytest.raises(AgentError) as exc:
        files.prepare_pdf(str(path))
    assert exc.value.code == "pdf_page_limit"
    path.write_bytes(b"not a pdf")
    with pytest.raises(AgentError) as exc:
        files.prepare_pdf(str(path))
    assert exc.value.code == "invalid_pdf"


def test_encrypted_pdf_rejected(settings, files):
    path = settings.allowed_input_dirs[0] / "secret.pdf"
    writer = PdfWriter(); writer.add_blank_page(100, 100); writer.encrypt("secret")
    with path.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(AgentError) as exc:
        files.prepare_pdf(str(path))
    assert exc.value.code == "invalid_pdf"


@pytest.mark.parametrize("finish", ["STOP", "MAX_TOKENS"])
async def test_document_upload_selected_pages_and_save_preview(settings, files, finish):
    path = make_pdf(settings.allowed_input_dirs[0] / "test.pdf")
    settings.document_preview_characters = 5
    def handler(request):
        body = json.loads(request.content)
        assert body["generationConfig"]["responseModalities"] == ["TEXT"]
        assert "[3, 1]" in body["contents"][0]["parts"][0]["text"]
        assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "LOW"}
        uploaded = base64.b64decode(body["contents"][0]["parts"][1]["inlineData"]["data"])
        assert [float(p.mediabox.width) for p in PdfReader(io.BytesIO(uploaded)).pages] == [300, 100]
        return httpx.Response(200, json={"candidates": [{"finishReason": finish, "content": {"parts": [{"text": "# Page 3\nResult"}]}}]})
    provider, client = adapter(settings, files, handler)
    async with client:
        result = await provider.execute(TaskRequest(kind="document", prompt="Extract", file_path=str(path), pages=[3, 1]), settings.models["gd"])
    assert result["pages"] == [3, 1] and result["source_page_count"] == 3
    assert result["text"] == "# Pag" and result["preview_truncated"]
    assert result["complete"] is (finish == "STOP")
    assert result["truncated"] is (finish == "MAX_TOKENS")
    assert Path(result["artifacts"][0]["path"]).read_text(encoding="utf-8") == "# Page 3\nResult"


async def test_vision_multiple_images_text_only(settings, files):
    paths = []
    for i in range(2):
        path = settings.allowed_input_dirs[0] / f"{i}.png"; path.write_bytes(bytes([i+1])); paths.append(str(path))
    def handler(request):
        body = json.loads(request.content)
        assert body["generationConfig"]["responseModalities"] == ["TEXT"]
        assert len(body["contents"][0]["parts"]) == 3
        assert "tools" not in body
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "two images"}]}}]})
    provider, client = adapter(settings, files, handler)
    async with client:
        result = await provider.execute(TaskRequest(kind="vision", prompt="Compare", file_paths=paths), settings.models["gv"])
    assert result["text"] == "two images" and not result["artifacts"]


@pytest.mark.parametrize("finish", ["STOP", "MAX_TOKENS"])
async def test_speech_separates_style_and_validates_wav(settings, files, finish):
    data = wav_bytes()
    def handler(request):
        body = json.loads(request.content)
        assert "systemInstruction" not in body
        assert body["contents"][0]["parts"] == [{"text": "Hello.", "speech_metadata": {"style": "warm"}}]
        assert body["generationConfig"] == {"responseModalities": ["AUDIO"], "maxOutputTokens": 16384,
            "speechConfig": {"voiceConfig": {"voice": "Kore"}}}
        return httpx.Response(200, json={"candidates": [{"finishReason": finish, "content": {"parts": [
            {"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(data).decode()}}]}}]})
    provider, client = adapter(settings, files, handler)
    async with client:
        if finish == "MAX_TOKENS":
            with pytest.raises(AgentError):
                await provider.execute(TaskRequest(kind="speech", prompt="Hello.", style="warm"), settings.models["gs"])
            assert not list(settings.output_dir.glob("*.wav"))
            return
        result = await provider.execute(TaskRequest(kind="speech", prompt="Hello.", style="warm"), settings.models["gs"])
    artifact = result["artifacts"][0]
    assert artifact["duration_seconds"] == 0.1 and artifact["sample_rate"] == 24000
    assert Path(artifact["path"]).read_bytes() == data  # no double WAV header


@pytest.mark.parametrize("mime,data", [("audio/pcm", b"raw"), ("audio/wav", b"RIFFbroken"), ("audio/wav", wav_bytes()[:-10])])
def test_invalid_audio_not_saved(files, mime, data):
    with pytest.raises(AgentError):
        files.save_audio(base64.b64encode(data).decode(), mime)


@pytest.mark.parametrize("task_request", [
    TaskRequest(kind="vision", prompt="x"),
    TaskRequest(kind="vision", prompt="x", file_paths=["irrelevant.png"]*9),
    TaskRequest(kind="speech", prompt="x"*2001),
    TaskRequest(kind="speech", prompt="x", voice="voice_custom"),
    TaskRequest(kind="speech", prompt="x", context="rewrite"),
    TaskRequest(kind="speech", prompt="x", max_output_tokens=10),
    TaskRequest(kind="speech", prompt="你"*2000, style="好"*1000),
    TaskRequest(kind="text", prompt="x", pages=[1]),
    TaskRequest(kind="audio", prompt="x", voice="Kore"),
    TaskRequest(kind="document", prompt="x"),
])
def test_invalid_new_tasks_not_enqueued(settings, files, task_request):
    manager = TaskManager(settings, None, files)
    with pytest.raises(AgentError):
        manager.submit([task_request])
    assert not manager.jobs
