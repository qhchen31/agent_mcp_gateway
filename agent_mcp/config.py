from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Provider = Literal["deepseek", "gemini"]
Kind = Literal["text", "knowledge", "image", "audio"]
SUPPORTED = {"deepseek": {"text", "knowledge"}, "gemini": {"text", "knowledge", "image", "audio"}}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelSpec(StrictModel):
    provider: Provider
    model: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    capabilities: list[Kind] = Field(min_length=1)
    image_size: Literal["512", "1K", "2K", "4K"] = "1K"
    image_aspect_ratio: str = Field(default="1:1", pattern=r"^[0-9]+:[0-9]+$")
    thinking_mode: Literal["enabled", "disabled"] = "disabled"

    @model_validator(mode="after")
    def supported(self):
        if not set(self.capabilities) <= SUPPORTED[self.provider]:
            raise ValueError("Provider/capability combination is not implemented")
        return self


class Settings(StrictModel):
    knowledge_search_enabled: bool = True
    global_concurrency: int = Field(default=4, ge=1, le=128)
    provider_concurrency: dict[Provider, int] = Field(default_factory=lambda: {"deepseek": 2, "gemini": 2})
    queue_limit: int = Field(default=32, ge=1, le=10000)
    text_timeout_seconds: float = Field(default=180, gt=0)
    media_timeout_seconds: float = Field(default=600, gt=0)
    max_output_tokens: int = Field(default=4096, ge=1, le=1000000)
    rate_limit_retries: int = Field(default=2, ge=0, le=10)
    retry_base_seconds: float = Field(default=1, gt=0)
    max_retry_delay_seconds: float = Field(default=30, gt=0)
    result_ttl_seconds: float = Field(default=3600, gt=0)
    max_completed_tasks: int = Field(default=256, ge=1)
    max_prompt_characters: int = Field(default=100000, ge=1)
    max_input_file_bytes: int = Field(default=12582912, ge=1)
    max_response_bytes: int = Field(default=67108864, ge=1)
    gemini_max_request_bytes: int = Field(default=20000000, ge=1, le=20000000)
    allowed_input_dirs: list[Path] = Field(min_length=1)
    output_dir: Path
    credential_service: str = Field(default="local-agent-mcp", min_length=1)
    models: dict[str, ModelSpec] = Field(min_length=1)
    default_models: dict[Kind, str] = Field(min_length=1)

    @model_validator(mode="after")
    def paths_and_limits(self):
        if any(not p.is_absolute() for p in [*self.allowed_input_dirs, self.output_dir]):
            raise ValueError("File directories must be absolute paths")
        if set(self.provider_concurrency) != set(SUPPORTED) or any(not 1 <= n <= 128 for n in self.provider_concurrency.values()):
            raise ValueError("Configure both provider concurrency limits between 1 and 128")
        for kind, alias in self.default_models.items():
            if alias not in self.models or kind not in self.models[alias].capabilities:
                raise ValueError("Default model must be a configured alias supporting its task kind")
        return self


def load_settings(path: Path) -> Settings:
    return Settings.model_validate_json(path.read_text(encoding="utf-8-sig"))
