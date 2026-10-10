import base64
import pytest
from pydantic import ValidationError
from agent_mcp.config import Settings
from agent_mcp.security import AgentError, Credentials

def test_paths_extension_and_size(settings, files, tmp_path):
    outside = tmp_path / "private.wav"
    outside.write_bytes(b"audio")
    for path in [outside, settings.allowed_input_dirs[0] / ".." / "private.wav"]:
        with pytest.raises(AgentError, match="outside"):
            files.read(str(path), "audio")
    with pytest.raises(AgentError, match="absolute"):
        files.read("relative.wav", "audio")
    inside = settings.allowed_input_dirs[0] / "sample.wav"
    inside.write_bytes(b"audio")
    assert files.read(str(inside), "audio")[:2] == (b"audio", "audio/wav")
    settings.max_input_file_bytes = 4
    with pytest.raises(AgentError, match="exceeds"):
        files.read(str(inside), "audio")
    wrong = settings.allowed_input_dirs[0] / "sample.exe"
    wrong.write_bytes(b"x")
    with pytest.raises(AgentError, match="extension"):
        files.read(str(wrong), "audio")

def test_output_no_overwrite_and_base64_validation(files):
    one = files.save_image(base64.b64encode(b"image").decode(), "image/png")
    two = files.save_image(base64.b64encode(b"image").decode(), "image/png")
    assert one["path"] != two["path"]
    with pytest.raises(AgentError):
        files.save_image("not base64!", "image/png")

def test_secrets_and_custom_endpoints_forbidden(settings):
    data = settings.model_dump()
    data["api_key"] = "SECRET"
    with pytest.raises(ValidationError):
        Settings.model_validate(data)
    data.pop("api_key")
    data["models"]["ds"]["base_url"] = "https://example.com"
    with pytest.raises(ValidationError):
        Settings.model_validate(data)

def test_removed_provider_and_bad_default_rejected(settings):
    data = settings.model_dump()
    data["models"]["ds"]["provider"] = "openai"
    with pytest.raises(ValidationError):
        Settings.model_validate(data)
    data = settings.model_dump()
    data["default_models"]["audio"] = "ds"
    with pytest.raises(ValidationError):
        Settings.model_validate(data)

def test_keyring_fails_closed(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "platform", "unsupported")
    with pytest.raises(AgentError, match="Supported credential stores"):
        Credentials("test").get("deepseek")
