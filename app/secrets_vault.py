"""Encrypts secret values (API keys, tokens, passwords) at rest in .env, so a
leaked/shared/committed .env file doesn't expose them in plaintext.

Security model, stated plainly: this protects an .env file viewed in
isolation from the rest of the filesystem. It does NOT protect against
someone with full filesystem access to the Pi itself, since the decryption
key (get_or_create_key()) must live on that same disk for the running app to
use it. That's the honest scope.

Values are stored with an "enc:" prefix once encrypted. decrypt_value() on a
value WITHOUT that prefix returns it unchanged (plaintext passthrough) so
existing deployments with plaintext .env values keep working untouched —
only new saves through the web UI get encrypted.
"""
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

ENC_PREFIX = "enc:"


def get_or_create_key(path):
    """Read the Fernet key at `path`, generating and persisting a new one
    (chmod 0o600) if it doesn't exist yet. Losing this file means every
    encrypted secret becomes unrecoverable and must be re-entered."""
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read().strip()

    key = Fernet.generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    logging.warning(
        f"Generated a new secrets encryption key at {path}. Back this file up — "
        f"losing it makes every previously-encrypted secret unrecoverable."
    )
    return key


def encrypt_value(plaintext, key):
    """Returns "enc:<token>". `plaintext` must be a non-empty string."""
    fernet = Fernet(key)
    token = fernet.encrypt(plaintext.encode()).decode()
    return ENC_PREFIX + token


def decrypt_value(stored, key):
    """Decrypts an "enc:"-prefixed value; returns non-prefixed input
    unchanged (plaintext passthrough). Raises InvalidToken if the value is
    prefixed but doesn't decrypt with the given key (wrong/corrupt key)."""
    if not stored or not stored.startswith(ENC_PREFIX):
        return stored
    fernet = Fernet(key)
    token = stored[len(ENC_PREFIX):]
    return fernet.decrypt(token.encode()).decode()


def is_encrypted(value):
    return bool(value) and value.startswith(ENC_PREFIX)


__all__ = ["get_or_create_key", "encrypt_value", "decrypt_value", "is_encrypted", "InvalidToken", "ENC_PREFIX"]
