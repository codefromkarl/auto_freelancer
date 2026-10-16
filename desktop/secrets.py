"""Use the OS vault, never a plaintext fallback or a publisher-owned relay."""

import hashlib
from desktop.redaction import remember


class VaultUnavailable(RuntimeError):
    pass


class SecretStore:
    def __init__(self, directory, backend=None):
        self.service = (
            "BidMaster/" + hashlib.sha256(str(directory).encode()).hexdigest()[:24]
        )
        if backend is None:
            try:
                import sys

                if sys.platform == "win32":
                    from keyring.backends.Windows import WinVaultKeyring

                    backend = WinVaultKeyring()
                elif sys.platform == "darwin":
                    from keyring.backends.macOS import Keyring

                    backend = Keyring()
                else:
                    from keyring.backends.SecretService import Keyring

                    backend = Keyring()
            except Exception:
                backend = None
        self.backend = backend

    def require(self):
        if self.backend is None:
            raise VaultUnavailable(
                "OS credential storage is unavailable. Unlock your keychain and restart."
            )
        name = type(self.backend).__module__
        trusted = (
            "keyring.backends.Windows",
            "keyring.backends.macOS",
            "keyring.backends.SecretService",
            "keyring.backends.kwallet",
        )
        if not any(name.startswith(prefix) for prefix in trusted):
            raise VaultUnavailable(
                "A supported OS credential vault is required; plaintext storage is not supported."
            )
        return self.backend

    def get(self, name):
        try:
            return remember(self.require().get_password(self.service, name) or "")
        except VaultUnavailable:
            raise
        except Exception:
            raise VaultUnavailable(
                "OS credential storage could not be read. Unlock your keychain."
            ) from None

    def set(self, name, value):
        remember(value)
        try:
            backend = self.require()
            if value:
                backend.set_password(self.service, name, value)
            elif backend.get_password(self.service, name):
                backend.delete_password(self.service, name)
        except VaultUnavailable:
            raise
        except Exception:
            raise VaultUnavailable(
                "OS credential storage could not be updated."
            ) from None

    def status(self):
        try:
            self.require()
            return {
                "available": True,
                "provider_key_saved": bool(self.get("model_api_key")),
                "platform_token_saved": bool(self.get("freelancer_token")),
            }
        except VaultUnavailable as exc:
            return {
                "available": False,
                "provider_key_saved": False,
                "platform_token_saved": False,
                "message": str(exc),
            }
