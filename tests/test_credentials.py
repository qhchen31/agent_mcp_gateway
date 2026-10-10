import sys
from types import SimpleNamespace

import pytest

from agent_mcp.security import AgentError, Credentials


class Vault:
    priority = 1

    def __init__(self):
        self.entries = {}

    def get_password(self, service, provider):
        return self.entries.get((service, provider))

    def set_password(self, service, provider, value):
        self.entries[service, provider] = value

    def delete_password(self, service, provider):
        del self.entries[service, provider]


@pytest.mark.parametrize("platform,module,attribute", [
    ("linux", "keyring.backends.SecretService", "Keyring"),
    ("win32", "keyring.backends.Windows", "WinVaultKeyring"),
])
def test_secure_platform_store(platform, module, attribute, monkeypatch):
    vault = Vault()
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setitem(sys.modules, module, SimpleNamespace(**{attribute: lambda: vault}))
    # The general keyring selector must not permit plaintext or third-party fallbacks.
    import keyring
    monkeypatch.setattr(keyring, "get_keyring", lambda: pytest.fail("Must select the OS vault explicitly"))
    credentials = Credentials("test-service")
    assert credentials.backend() is vault
    with pytest.raises(AgentError) as missing:
        credentials.get("deepseek")
    assert missing.value.code == "missing_credential"
    credentials.set("deepseek", " fake-test-value ")
    assert credentials.get("deepseek") == "fake-test-value"
    credentials.delete("deepseek")
    assert not vault.entries


def test_unavailable_linux_store_sanitizes_errors(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    def unavailable():
        raise RuntimeError("sensitive-backend-details")
    monkeypatch.setitem(sys.modules, "keyring.backends.SecretService", SimpleNamespace(Keyring=unavailable))
    with pytest.raises(AgentError) as error:
        Credentials("test").backend()
    assert error.value.code == "credential_backend"
    assert "D-Bus" in error.value.message
    assert "sensitive-backend-details" not in error.value.message


def test_backend_operation_errors_do_not_leak(monkeypatch):
    class BrokenVault(Vault):
        def get_password(self, *args):
            raise RuntimeError("fake-secret")
        set_password = get_password
        delete_password = get_password
    monkeypatch.setattr(Credentials, "backend", staticmethod(BrokenVault))
    credentials = Credentials("test")
    for operation in (lambda: credentials.get("deepseek"), lambda: credentials.set("deepseek", "fake-secret"), lambda: credentials.delete("deepseek")):
        with pytest.raises(AgentError) as error:
            operation()
        assert "fake-secret" not in error.value.message
