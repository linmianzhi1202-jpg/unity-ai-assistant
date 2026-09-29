"""
Encryption Module for the Unified MCP for Unity system.
Provides AES-256-GCM encryption for sensitive data in transit and at rest.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# AES-256-GCM constants
_KEY_SIZE = 32  # 256 bits
_NONCE_SIZE = 12  # 96 bits (recommended for GCM)
_TAG_SIZE = 16  # 128 bits


def _get_cipher():
    """Lazily import cryptography to avoid hard dependency."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM
    except ImportError:
        raise ImportError(
            "Encryption requires the 'cryptography' package. "
            "Install with: pip install cryptography"
        )


class EncryptionManager:
    """Manages encryption/decryption of sensitive data using AES-256-GCM.

    Usage:
        # Generate a new key
        key_b64 = EncryptionManager.generate_key()

        # Initialize with key
        enc = EncryptionManager(key_b64)

        # Encrypt
        ciphertext = enc.encrypt("sensitive data")

        # Decrypt
        plaintext = enc.decrypt(ciphertext)
    """

    def __init__(self, key_base64: str | None = None, key_path: str | None = None) -> None:
        """Initialize the encryption manager.

        Args:
            key_base64: Base64-encoded 256-bit key.
            key_path: Path to a file containing the base64-encoded key.
                      If both are provided, key_base64 takes precedence.
        """
        AESGCM = _get_cipher()

        if key_base64:
            raw_key = base64.b64decode(key_base64)
        elif key_path:
            raw_key = self._load_key_from_file(key_path)
        else:
            # Generate a new key for this session (not persistent)
            raw_key = os.urandom(_KEY_SIZE)
            logger.warning(
                "No encryption key provided; using ephemeral key. "
                "Data encrypted with this key cannot be decrypted after restart."
            )

        if len(raw_key) != _KEY_SIZE:
            raise ValueError(
                f"Encryption key must be {_KEY_SIZE} bytes, got {len(raw_key)}"
            )

        self._aesgcm = AESGCM(raw_key)

    @staticmethod
    def generate_key() -> str:
        """Generate a new random AES-256 key and return as base64 string."""
        key = os.urandom(_KEY_SIZE)
        return base64.b64encode(key).decode("ascii")

    @staticmethod
    def save_key(key_base64: str, path: str | Path) -> None:
        """Save a base64-encoded key to a file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key_base64, encoding="ascii")
        # Restrict file permissions (Unix only; Windows uses ACL)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _load_key_from_file(self, path: str) -> bytes:
        """Load a base64-encoded key from a file."""
        try:
            content = Path(path).read_text(encoding="ascii").strip()
            return base64.b64decode(content)
        except Exception as e:
            raise ValueError(f"Failed to load encryption key from {path}: {e}")

    def encrypt(self, plaintext: str | bytes, associated_data: bytes | None = None) -> str:
        """Encrypt a string or bytes using AES-256-GCM.

        Args:
            plaintext: The string or bytes to encrypt.
            associated_data: Optional AAD for additional authentication.

        Returns:
            Base64-encoded string: nonce + ciphertext + tag.
        """
        nonce = os.urandom(_NONCE_SIZE)
        if isinstance(plaintext, bytes):
            plaintext_bytes = plaintext
        else:
            plaintext_bytes = plaintext.encode("utf-8")
        ciphertext = self._aesgcm.encrypt(nonce, plaintext_bytes, associated_data)
        # Combine nonce + ciphertext (ciphertext already includes the tag)
        combined = nonce + ciphertext
        return base64.b64encode(combined).decode("ascii")

    def decrypt(self, encrypted: str, associated_data: bytes | None = None) -> str:
        """Decrypt a base64-encoded AES-256-GCM ciphertext.

        Args:
            encrypted: Base64-encoded nonce + ciphertext + tag.
            associated_data: Optional AAD (must match what was used for encryption).

        Returns:
            The decrypted plaintext string.
        """
        try:
            combined = base64.b64decode(encrypted)
        except Exception as e:
            raise ValueError(f"Invalid base64 in encrypted data: {e}")

        if len(combined) < _NONCE_SIZE + _TAG_SIZE + 1:
            raise ValueError("Encrypted data is too short")

        nonce = combined[:_NONCE_SIZE]
        ciphertext = combined[_NONCE_SIZE:]

        try:
            plaintext_bytes = self._aesgcm.decrypt(nonce, ciphertext, associated_data)
        except Exception as e:
            raise ValueError(f"Decryption failed (wrong key or tampered data): {e}")

        return plaintext_bytes.decode("utf-8")

    def encrypt_dict_values(
        self,
        data: dict,
        sensitive_keys: set[str] | None = None,
    ) -> dict:
        """Encrypt sensitive values in a dictionary.

        Args:
            data: Dictionary with potentially sensitive values.
            sensitive_keys: Set of keys whose values should be encrypted.
                           Default: {"api_key", "password", "secret", "token"}.

        Returns:
            New dict with sensitive values encrypted and prefixed with "enc:".
        """
        if sensitive_keys is None:
            sensitive_keys = {"api_key", "password", "secret", "token"}

        result = {}
        for key, value in data.items():
            if key in sensitive_keys and isinstance(value, str):
                result[key] = f"enc:{self.encrypt(value)}"
            elif isinstance(value, dict):
                result[key] = self.encrypt_dict_values(value, sensitive_keys)
            else:
                result[key] = value
        return result

    def decrypt_dict_values(self, data: dict) -> dict:
        """Decrypt values in a dictionary that were encrypted with encrypt_dict_values.

        Args:
            data: Dictionary with "enc:"-prefixed encrypted values.

        Returns:
            New dict with encrypted values decrypted.
        """
        result = {}
        for key, value in data.items():
            if isinstance(value, str) and value.startswith("enc:"):
                result[key] = self.decrypt(value[4:])
            elif isinstance(value, dict):
                result[key] = self.decrypt_dict_values(value)
            else:
                result[key] = value
        return result
