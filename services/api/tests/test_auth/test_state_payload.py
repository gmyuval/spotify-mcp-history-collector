"""Tests for OAuthStateManager payload support."""

from app.auth.state import OAuthStateManager

KEY = "test-secret-key-for-hmac"
TTL = 300


def test_generate_without_payload_verifies() -> None:
    """generate() with no payload still works and verifies."""
    mgr = OAuthStateManager(key=KEY, ttl_seconds=TTL)
    state = mgr.generate()
    assert mgr.verify(state) is True


def test_generate_with_payload_verifies() -> None:
    """generate(payload='42') produces a state that verifies correctly."""
    mgr = OAuthStateManager(key=KEY, ttl_seconds=TTL)
    state = mgr.generate(payload="42")
    assert mgr.verify(state) is True


def test_extract_payload_returns_payload() -> None:
    """extract_payload on a state with payload '42' returns '42'."""
    mgr = OAuthStateManager(key=KEY, ttl_seconds=TTL)
    state = mgr.generate(payload="42")
    assert mgr.extract_payload(state) == "42"


def test_extract_payload_returns_none_without_payload() -> None:
    """extract_payload on a state without payload returns None."""
    mgr = OAuthStateManager(key=KEY, ttl_seconds=TTL)
    state = mgr.generate()
    assert mgr.extract_payload(state) is None


def test_tampered_payload_fails_verification() -> None:
    """Modifying the payload portion of a state breaks HMAC verification."""
    mgr = OAuthStateManager(key=KEY, ttl_seconds=TTL)
    state = mgr.generate(payload="42")

    # State format is "{timestamp}:{payload}.{signature}"
    data, sig = state.split(".", 1)
    ts, _payload = data.split(":", 1)
    tampered = f"{ts}:99.{sig}"
    assert mgr.verify(tampered) is False


def test_backward_compatible_with_old_format() -> None:
    """Old-format states (no colon, just timestamp.signature) still verify."""
    mgr = OAuthStateManager(key=KEY, ttl_seconds=TTL)
    # Generate without payload — produces old-format "{timestamp}.{signature}"
    state = mgr.generate()
    # Verify that there is no colon in the data portion
    data, _sig = state.split(".", 1)
    assert ":" not in data
    # Should still verify
    assert mgr.verify(state) is True
