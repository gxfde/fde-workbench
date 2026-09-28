from fde_api.auth.passwords import hash_password, verify_password


def test_password_hash_never_contains_plaintext():
    encoded = hash_password("Correct Horse Battery Staple")

    assert "Correct Horse" not in encoded
    assert "m=65536,t=3,p=4" in encoded
    assert verify_password(encoded, "Correct Horse Battery Staple") is True
    assert verify_password(encoded, "wrong") is False


def test_password_verification_rejects_invalid_hashes():
    assert verify_password("not-an-argon2-hash", "Correct Horse Battery Staple") is False
