ROLE_RANK: dict[str, int] = {
    "viewer": 0,
    "fde_engineer": 1,
    "project_lead": 2,
    "admin": 3,
}


def role_at_least(actual: str, required: str) -> bool:
    return (
        actual in ROLE_RANK
        and required in ROLE_RANK
        and ROLE_RANK[actual] >= ROLE_RANK[required]
    )
