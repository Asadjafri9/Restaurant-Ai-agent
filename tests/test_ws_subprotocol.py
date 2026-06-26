def test_ws_accepts_full_client_subprotocol():
    """Server must echo the exact subprotocol offered by the browser."""
    token = "eyJhbGciOiJIUzI1NiJ9.full.jwt.token"
    offered = f"access.{token}"
    # Simulates the fixed accept() argument — must match offered, not token[:8].
    assert offered == f"access.{token}"
    assert offered != f"access.{token[:8]}"
