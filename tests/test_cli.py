import getpass
import sys
import warnings

from agent_mcp import cli

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
