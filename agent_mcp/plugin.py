"""Build a credential-free, machine-local Codex plugin and install through its CLI."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from .security import AgentError


NAME = "agent-mcp-gateway"
MARKETPLACE = "agent-mcp-gateway-local"


def build_plugin(config: Path, python: str) -> Path:
    config = config.resolve(strict=True)
    root = config.parent / ".local-plugin"
    plugin = root / "plugins" / NAME
    manifest_dir = plugin / ".codex-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"name": NAME, "version": "0.3.0", "description": "Delegate independent tasks to DeepSeek and Gemini through a local MCP gateway",
                "mcpServers": "./.mcp.json"}
    # Write only known public metadata and launch paths. Never copy config or credentials.
    (manifest_dir / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    mcp = {"mcpServers": {NAME: {"command": python,
        "args": ["-m", "agent_mcp", "--config", str(config), "serve"],
        "cwd": str(config.parent)}}}
    if sys.platform.startswith("linux"):
        # Pass session routing, never provider credentials or environment values.
        mcp["mcpServers"][NAME]["env_vars"] = ["DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR"]
    (plugin / ".mcp.json").write_text(json.dumps(mcp, indent=2) + "\n", encoding="utf-8")
    catalog_dir = root / ".agents" / "plugins"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    catalog = {"name": MARKETPLACE, "interface": {"displayName": "Agent MCP Gateway (Local)"},
        "plugins": [{"name": NAME, "source": {"source": "local", "path": "./plugins/" + NAME},
                     "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"}, "category": "Developer Tools"}]}
    (catalog_dir / "marketplace.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    return root


def install_plugin(config: Path):
    codex = shutil.which("codex")
    if not codex:
        raise AgentError("plugin_install", "Install the Codex CLI and make codex available in PATH")
    root = build_plugin(config, sys.executable)
    for args in (["marketplace", "add", str(root)], ["add", NAME + "@" + MARKETPLACE]):
        result = subprocess.run([codex, "plugin", *args], check=False)
        if result.returncode:
            raise AgentError("plugin_install", "Codex plugin installation failed; check the CLI output and retry install-plugin")
    print("Installed agent-mcp-gateway. Start a new Codex chat to load its MCP tools.")
