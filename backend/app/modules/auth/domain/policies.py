from datetime import datetime


def session_valid(
    status: str, revoked_at: datetime | None, expires_at: datetime, now: datetime
) -> bool:
    return status == "active" and revoked_at is None and expires_at > now


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def validate_password(password: str) -> None:
    if not 6 <= len(password) <= 128:
        raise ValueError("Password must contain 6–128 characters")
