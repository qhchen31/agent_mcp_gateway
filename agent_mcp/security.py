import base64
from pathlib import Path
from uuid import uuid4

from .config import Settings


class AgentError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self):
        return {"code": self.code, "message": self.message}


class Credentials:
    """Fail closed unless the active backend is the Windows credential vault."""
    def __init__(self, service: str):
        self.service = service

    @staticmethod
    def backend():
        import keyring
        from keyring.backends.Windows import WinVaultKeyring
        backend = keyring.get_keyring()
        if not isinstance(backend, WinVaultKeyring):
            raise AgentError("credential_backend", "Windows Credential Manager backend is required")
        return backend

    def get(self, provider: str) -> str:
        try:
            value = self.backend().get_password(self.service, provider)
        except AgentError:
            raise
        except Exception:
            raise AgentError("credential_backend", "Cannot access Windows Credential Manager") from None
        if not value:
            raise AgentError("missing_credential", f"Set the {provider} credential using the local CLI")
        return value

    def set(self, provider: str, value: str):
        if not value.strip():
            raise AgentError("invalid_credential", "Credential cannot be empty")
        try:
            self.backend().set_password(self.service, provider, value.strip())
        except AgentError:
            raise
        except Exception:
            raise AgentError("credential_backend", "Cannot store credential") from None

    def delete(self, provider: str):
        try:
            self.backend().delete_password(self.service, provider)
        except AgentError:
            raise
        except Exception:
            raise AgentError("credential_backend", "Cannot delete credential; it may not exist") from None


IMAGE_MIMES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
AUDIO_MIMES = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg", ".flac": "audio/flac", ".webm": "audio/webm"}


class FilePolicy:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.roots = [p.resolve() for p in settings.allowed_input_dirs]
        self.output = settings.output_dir.resolve()

    def validate(self, filename: str, media: str) -> tuple[Path, str]:
        path = Path(filename)
        if not path.is_absolute():
            raise AgentError("invalid_path", "Input file path must be absolute")
        try:
            path = path.resolve(strict=True)
            if not any(path.is_relative_to(root) for root in self.roots):
                raise AgentError("path_denied", "Input file is outside the configured directories")
            if not path.is_file():
                raise AgentError("invalid_file", "Input must be a regular file")
            if path.stat().st_size > self.settings.max_input_file_bytes:
                raise AgentError("file_too_large", "Input exceeds max_input_file_bytes")
        except OSError:
            raise AgentError("invalid_file", "Input file cannot be accessed") from None
        mime = (IMAGE_MIMES if media == "image" else AUDIO_MIMES).get(path.suffix.lower())
        if not mime:
            raise AgentError("unsupported_file", "File extension is not supported for this capability")
        return path, mime

    def read(self, filename: str, media: str) -> tuple[bytes, str, str]:
        path, mime = self.validate(filename, media)
        try:
            with path.open("rb") as handle:
                data = handle.read(self.settings.max_input_file_bytes + 1)
        except OSError:
            raise AgentError("invalid_file", "Input file cannot be read") from None
        if not data or len(data) > self.settings.max_input_file_bytes:
            raise AgentError("invalid_file", "Input is empty or exceeds the configured size limit")
        return data, mime, path.name

    def save_image(self, encoded: str, mime: str) -> dict:
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime)
        if not suffix:
            raise AgentError("upstream_format", "Unsupported generated image format")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise AgentError("upstream_format", "Invalid generated image data") from None
        if not data or len(data) > self.settings.max_response_bytes:
            raise AgentError("upstream_format", "Generated image is empty or exceeds the size limit")
        self.output.mkdir(parents=True, exist_ok=True)
        path = self.output / (uuid4().hex + suffix)
        with path.open("xb") as handle:
            handle.write(data)
        return {"path": str(path), "mime_type": mime, "bytes": len(data)}
