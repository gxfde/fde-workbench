import pytest

from fde_api.auth.limits import PASSWORD_MAX_LENGTH, USERNAME_MAX_LENGTH
from fde_api.auth.service import (
    AuthServiceError,
    validate_password_strength,
    validate_username,
)


def test_username_accepts_maximum_and_rejects_one_more_character():
    assert validate_username("u" * USERNAME_MAX_LENGTH) == "u" * USERNAME_MAX_LENGTH

    with pytest.raises(AuthServiceError) as rejected:
        validate_username("u" * (USERNAME_MAX_LENGTH + 1))
    assert rejected.value.code == "invalid_request"


def test_password_accepts_maximum_and_rejects_one_more_character():
    validate_password_strength("Aa1!" + "x" * (PASSWORD_MAX_LENGTH - 4))

    with pytest.raises(AuthServiceError) as rejected:
        validate_password_strength("Aa1!" + "x" * (PASSWORD_MAX_LENGTH - 3))
    assert rejected.value.code == "invalid_request"


def test_password_accepts_any_six_characters_and_rejects_five():
    validate_password_strength("123456")

    with pytest.raises(AuthServiceError) as rejected:
        validate_password_strength("12345")
    assert rejected.value.code == "password_too_weak"
