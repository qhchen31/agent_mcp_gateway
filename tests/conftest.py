import pytest
from agent_mcp.config import ModelSpec, Settings
from agent_mcp.security import FilePolicy

@pytest.fixture
def settings(tmp_path):
    inputs, outputs = tmp_path / "inputs", tmp_path / "outputs"
    inputs.mkdir()
    outputs.mkdir()
    return Settings(allowed_input_dirs=[inputs, outputs], output_dir=outputs,
        retry_base_seconds=0.001, max_retry_delay_seconds=0.001,
        models={alias: ModelSpec(provider=provider, model="test-model", capabilities=[kind])
            for alias, provider, kind in [("ds", "deepseek", "text"), ("gt", "gemini", "text"),
                ("gk", "gemini", "knowledge"), ("gi", "gemini", "image"), ("ga", "gemini", "audio"), ("gv", "gemini", "vision"), ("gd", "gemini", "document"), ("gs", "gemini", "speech") ]},
        default_models={"text": "ds", "knowledge": "gk", "image": "gi", "audio": "ga", "vision": "gv", "document": "gd", "speech": "gs"})

@pytest.fixture
def files(settings):
    return FilePolicy(settings)
