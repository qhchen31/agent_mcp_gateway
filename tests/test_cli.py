import getpass
import sys
import warnings

from agent_mcp import cli

def test_init_resolves_paths_and_never_overwrites(tmp_path, monkeypatch):
    from agent_mcp.config import load_settings
    config = tmp_path / "new workspace" / "config.json"
    monkeypatch.setattr(sys, "argv", ["agent-mcp", "--config", str(config), "init"])
    assert cli.main() == 0
    settings = load_settings(config)
    assert settings.allowed_input_dirs == [config.parent / "inputs", config.parent / "outputs"]
    assert settings.output_dir.is_dir()
    before = config.read_bytes()
    assert cli.main() == 1
    assert config.read_bytes() == before

def test_doctor_never_reads_keys(settings, tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.json"
    config.write_text(settings.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["agent-mcp", "--config", str(config), "doctor"])
    monkeypatch.setattr(cli.Credentials, "backend", staticmethod(lambda: object()))
    monkeypatch.setattr(cli.Credentials, "get", lambda *args: (_ for _ in ()).throw(AssertionError("Must not read keys")))
    assert cli.main() == 0
    assert '"keys_read": false' in capsys.readouterr().out

def test_set_key_aborts_if_hidden_input_unavailable(settings, tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.json"
    config.write_text(settings.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["agent-mcp", "--config", str(config), "set-key", "deepseek"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    def fallback(*args):
        warnings.warn("Cannot hide input", getpass.GetPassWarning)
        raise AssertionError("Must never reach echoing fallback")
    monkeypatch.setattr(getpass, "getpass", fallback)
    monkeypatch.setattr(cli.Credentials, "set", lambda *args: (_ for _ in ()).throw(AssertionError("Must not store anything")))
    assert cli.main() == 1
    assert "Cannot hide input" not in capsys.readouterr().err

def test_set_key_requires_interactive_terminal(settings, tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(settings.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["agent-mcp", "--config", str(config), "set-key", "deepseek"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(getpass, "getpass", lambda *args: (_ for _ in ()).throw(AssertionError("Must not prompt")))
    assert cli.main() == 1
