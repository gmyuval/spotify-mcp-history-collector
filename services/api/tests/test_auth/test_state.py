"""Tests for OAuthStateManager."""

from unittest.mock import patch

from app.auth.state import OAuthStateManager

KEY = "test-secret-key-for-hmac"


def test_generate_and_verify() -> None:
    """A freshly generated state should verify successfully."""
    mgr = OAuthStateManager(key=KEY, ttl_seconds=300)
    state = mgr.generate()
    assert mgr.verify(state) is True


def test_verify_invalid_signature() -> None:
    """A state with a tampered signature should fail verification."""
    mgr = OAuthStateManager(key=KEY, ttl_seconds=300)
    state = mgr.generate()
    # Tamper with the signature
    ts, _sig = state.split(".", 1)
    tampered = f"{ts}.{'a' * 64}"
    assert mgr.verify(tampered) is False


def test_verify_wrong_key() -> None:
    """A state verified with a different key should fail."""
    mgr = OAuthStateManager(key=KEY, ttl_seconds=300)
    state = mgr.generate()
    other_mgr = OAuthStateManager(key="different-key", ttl_seconds=300)
    assert other_mgr.verify(state) is False


def test_verify_expired_state() -> None:
    """A state whose timestamp is older than the TTL should fail."""
    mgr = OAuthStateManager(key=KEY, ttl_seconds=300)
    with patch("app.auth.state.time") as mock_time:
        mock_time.time.return_value = 1000000.0
        state = mgr.generate()
    # Now time.time() returns real time, so the state is far in the past
    assert mgr.verify(state) is False


def test_verify_malformed_state() -> None:
    """Malformed state strings should fail gracefully."""
    mgr = OAuthStateManager(key=KEY, ttl_seconds=300)
    assert mgr.verify("no-dot-separator") is False
    assert mgr.verify("") is False
    assert mgr.verify("not-a-number.abcdef") is False
