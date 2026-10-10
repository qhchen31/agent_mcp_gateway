import json
from types import SimpleNamespace

import pytest

from agent_mcp import plugin
from agent_mcp.security import AgentError


def test_plugin_bundles_only_launch_metadata(tmp_path):
    config = tmp_path / "workspace with spaces" / "config.json"
    config.parent.mkdir()
    config.write_text('{"sentinel": "do-not-copy-this"}', encoding="utf-8")
    python = str(tmp_path / "venv with spaces" / "bin" / "python")
    root = plugin.build_plugin(config, python)
    server = json.loads((root / "plugins" / plugin.NAME / ".mcp.json").read_text())["mcpServers"][plugin.NAME]
    assert server["command"] == python
    assert server["args"] == ["-m", "agent_mcp", "--config", str(config), "serve"]
    assert server["cwd"] == str(config.parent)
    files = list(root.rglob("*.json"))
    assert len(files) == 3
    assert all("do-not-copy-this" not in path.read_text() for path in files)


def test_install_stops_when_marketplace_registration_fails(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text("{}")
    monkeypatch.setattr(plugin.shutil, "which", lambda _: "codex")
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(plugin.subprocess, "run", run)
    with pytest.raises(AgentError, match="installation failed"):
        plugin.install_plugin(config)
    assert len(calls) == 1


def test_linux_plugin_forwards_session_names_only(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text("{}")
    monkeypatch.setattr(plugin.sys, "platform", "linux")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "session-address-must-not-be-copied")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-must-not-be-copied")
    root = plugin.build_plugin(config, "python")
    manifest = root / "plugins" / plugin.NAME / ".mcp.json"
    server = json.loads(manifest.read_text())["mcpServers"][plugin.NAME]
    assert server["env_vars"] == ["DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR"]
    assert "session-address-must-not-be-copied" not in manifest.read_text()
    assert "fake-key-must-not-be-copied" not in manifest.read_text()
