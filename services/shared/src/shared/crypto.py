"""Token encryption and decryption using Fernet symmetric encryption."""

from cryptography.fernet import Fernet


class TokenEncryptor:
    """Encrypts and decrypts tokens using Fernet symmetric encryption.

    Fernet guarantees that data encrypted with it cannot be read or tampered
    with without the key. Each call to encrypt produces different ciphertext
    (Fernet uses a random IV), so the same plaintext never produces the same output.
    """

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode())

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string, returning base64-encoded ciphertext."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a base64-encoded ciphertext string, returning the original plaintext."""
        return self._fernet.decrypt(ciphertext.encode()).decode()
