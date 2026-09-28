from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError


password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    type=Type.ID,
)


def hash_password(raw: str) -> str:
    return password_hasher.hash(raw)


def verify_password(hash_value: str, raw: str) -> bool:
    try:
        return password_hasher.verify(hash_value, raw)
    except (InvalidHashError, VerificationError):
        return False
