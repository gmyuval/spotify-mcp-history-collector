"""Tests for TokenEncryptor."""

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.auth.crypto import TokenEncryptor


@pytest.fixture
def fernet_key() -> str:
    """Generate a fresh Fernet key for testing."""
    return Fernet.generate_key().decode()


@pytest.fixture
def encryptor(fernet_key: str) -> TokenEncryptor:
    return TokenEncryptor(fernet_key)


def test_encrypt_decrypt_roundtrip(encryptor: TokenEncryptor) -> None:
    """Encrypting then decrypting returns the original plaintext."""
    plaintext = "my-secret-refresh-token-abc123"
    ciphertext = encryptor.encrypt(plaintext)
    assert encryptor.decrypt(ciphertext) == plaintext


def test_decrypt_with_wrong_key_fails(encryptor: TokenEncryptor) -> None:
    """Decrypting with a different key raises an error."""
    ciphertext = encryptor.encrypt("secret")
    wrong_encryptor = TokenEncryptor(Fernet.generate_key().decode())
    with pytest.raises(InvalidToken):
        wrong_encryptor.decrypt(ciphertext)


def test_encrypt_produces_different_ciphertext(encryptor: TokenEncryptor) -> None:
    """Same plaintext encrypted twice produces different ciphertexts (random IV)."""
    plaintext = "same-token"
    ct1 = encryptor.encrypt(plaintext)
    ct2 = encryptor.encrypt(plaintext)
    assert ct1 != ct2
    # Both still decrypt to the same value
    assert encryptor.decrypt(ct1) == plaintext
    assert encryptor.decrypt(ct2) == plaintext


def test_empty_string(encryptor: TokenEncryptor) -> None:
    """Empty string can be encrypted and decrypted."""
    ciphertext = encryptor.encrypt("")
    assert encryptor.decrypt(ciphertext) == ""
