from accordance.auth.passwords import hash_password, verify_password


def test_hash_verify_roundtrip():
    h = hash_password("s3cret")
    assert verify_password("s3cret", h) is True


def test_wrong_password_fails():
    assert verify_password("nope", hash_password("s3cret")) is False


def test_same_password_hashes_differ_random_salt():
    assert hash_password("s3cret") != hash_password("s3cret")


def test_malformed_stored_hash_is_false_not_error():
    assert verify_password("x", "not-a-valid-hash") is False
    assert verify_password("x", "") is False
