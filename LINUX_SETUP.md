# Linux setup and Codex plugin

The gateway supports Windows Credential Manager and Linux Secret Service.
Platform selection is automatic; Windows keeps its native vault. Linux uses
`keyring.backends.SecretService.Keyring` explicitly, so an environment setting
or an installed plaintext keyring cannot silently replace the secure backend.
Unsupported platforms and unavailable vaults fail closed.

## Install

Use Python 3.11 or newer (`python3 --version`). On a Linux desktop, install your
distribution's GNOME Keyring / Secret Service and D-Bus packages if absent.
For Ubuntu/Debian these are `gnome-keyring` and `dbus-user-session`. The Python
SecretStorage dependency is installed automatically by keyring on Linux.

```bash
git clone https://github.com/qhchen31/agent_mcp_gateway.git AgentMcpGateway
cd AgentMcpGateway
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m agent_mcp init
.venv/bin/python -m agent_mcp doctor
```

Substitute your Python 3.11+ executable in the venv command. `init` uses the
configuration directory to create absolute `inputs` and `outputs` paths on
either OS. It never overwrites an existing configuration. For a separate
configuration location use `--config /absolute/path/config.json` **before** the
subcommand, including for later credential/server/plugin commands. The default
configuration is `config.json` in the current working directory. The packaged
template also supports installations from a wheel.

## Save and load API keys

Run these in your own interactive terminal, with your desktop login keyring
unlocked. Input is hidden; a terminal that cannot hide input is rejected.

```bash
.venv/bin/python -m agent_mcp set-key deepseek
.venv/bin/python -m agent_mcp set-key gemini
```

Save only keys for the providers you plan to use. The keys are stored in your
OS-managed keyring under service `local-agent-mcp` and provider name `deepseek`
or `gemini`, outside the repository. They are never written to Python code,
`config.json`, plugin manifests, command arguments, or shell history.
Do not paste keys into a chat or commit them to GitHub.

No `export`, shell `source`, or key-bearing environment file is needed. The
gateway fetches the corresponding key from Secret Service when a task calls
its provider. Keep Codex and the gateway in the same desktop D-Bus session.
Restart the MCP client after configuration changes. Use the same `set-key`
command to replace a key; remove it with `delete-key deepseek` or
`delete-key gemini`.

`doctor` checks configuration and vault availability without reading keys or
making API requests. It does not prove that a key exists, the keyring is
unlocked, or an account has model access. A missing key fails only the affected
provider's task with `missing_credential`; locked/unavailable vaults return a
sanitized `credential_backend` error.

For SSH/headless Linux, Secret Service still requires D-Bus and an unlocked
keyring. Start the daemon, gateway, and client within the same D-Bus session;
see the [keyring headless guide](https://keyring.readthedocs.io/en/latest/#using-keyring-on-headless-linux-systems).
There is deliberately no plaintext fallback. Desktop login normally unlocks
GNOME's login keyring. Same-user processes with keyring access may also read
these credentials; the vault does not isolate mutually untrusted processes
running as your user.

## Install as a local Codex plugin

With a current Codex CLI on `PATH`, run:

```bash
.venv/bin/python -m agent_mcp install-plugin
```

This builds a local marketplace in `.local-plugin/`, registers it using
`codex plugin marketplace add`, then installs
`agent-mcp-gateway@agent-mcp-gateway-local` using `codex plugin add`.
The manifest points at a stdio MCP server launched by the **same Python
interpreter** and the explicit configuration path used for installation.
On Linux it requests inheritance of `DBUS_SESSION_BUS_ADDRESS` and
`XDG_RUNTIME_DIR` so the server can reach the client's desktop keyring.
Only launch metadata is packaged; it does not copy your configuration, input,
output, virtual environment, or keys. `.local-plugin/` and `config.json` are
Git-ignored. The plugin therefore depends on the original environment and
configuration remaining at those paths. After moving them, rerun
`install-plugin`. Windows uses the same command with `.venv\Scripts\python.exe`.

Start a new Codex chat in this workspace (restart the app if needed). Check
`codex plugin list --json` for `installed: true` and `enabled: true`, then call
`list_capabilities` to verify the nine MCP tools. Credentials can be saved
before or after installation; tool discovery does not read keys or call APIs.
Do not also register the same gateway as a standalone MCP server, which would
create a second task process.

The packaging follows [OpenAI's local plugin documentation](https://developers.openai.com/plugins/build/plugins).
This is a machine-local installation, not publication to the public plugin
directory. To remove it:

```bash
codex plugin remove agent-mcp-gateway@agent-mcp-gateway-local
codex plugin marketplace remove agent-mcp-gateway-local
```

Other MCP clients can launch the same server directly:

```bash
/absolute/path/AgentMcpGateway/.venv/bin/python -m agent_mcp \
  --config /absolute/path/AgentMcpGateway/config.json serve
```

## Verification

```bash
.venv/bin/python -m pytest -q
```

Offline tests use synthetic credentials and mocked providers, including a real
stdio handshake and task lifecycle. CI covers Linux and Windows on Python
3.11/3.12. The existing paid harness self-test now uses `sys.executable` on
either OS; its PowerShell speech fixture remains Windows-specific. On Linux,
provide your own `inputs/codex-test.wav` if you choose to run that paid test.
No real API request is needed for installation or offline verification.
