"""Local operator commands. Passwords are read only from a hidden prompt."""

import argparse
import asyncio
import getpass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from pydantic import ValidationError

from app.db.database import AsyncSessionLocal, engine
from app.modules.auth.domain.policies import normalize_email
from app.modules.auth.repo.models import AuthSession, RateLimitBucket, User
from app.modules.auth.repo.users import find_by_email
from app.modules.auth.schemas import LoginRequest
from app.modules.auth.security import hash_password


async def create_user(email: str, password: str) -> None:
    email = LoginRequest(email=email, password=password).email
    encoded = await hash_password(password)
    async with AsyncSessionLocal() as db, db.begin():
        db.add(User(email=email, password_hash=encoded))


async def disable_user(email: str) -> None:
    async with AsyncSessionLocal() as db, db.begin():
        user = await find_by_email(db, normalize_email(email), lock=True)
        if user is None:
            raise ValueError("User not found")
        user.status = "disabled"
        families = (
            await db.scalars(
                select(AuthSession)
                .where(AuthSession.user_id == user.id)
                .order_by(AuthSession.id)
                .with_for_update()
            )
        ).all()
        for family in families:
            if family.revoked_at is None:
                family.revoked_at = datetime.now(timezone.utc)
                family.revoked_reason = "user_disabled"


async def cleanup(batch_size: int = 500) -> int:
    if not 1 <= batch_size <= 10000:
        raise ValueError("Batch size must be between 1 and 10000")
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db, db.begin():
        sessions = list(
            await db.scalars(
                select(AuthSession.id)
                .where(AuthSession.expires_at <= now)
                .order_by(AuthSession.id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        if sessions:
            await db.execute(delete(AuthSession).where(AuthSession.id.in_(sessions)))
        buckets = (
            await db.execute(
                select(RateLimitBucket.key_digest, RateLimitBucket.window_start)
                .where(RateLimitBucket.expires_at <= now)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for key, start in buckets:
            await db.execute(
                delete(RateLimitBucket).where(
                    RateLimitBucket.key_digest == key,
                    RateLimitBucket.window_start == start,
                )
            )
        return len(sessions) + len(buckets)


async def run(command: str, email: str | None, batch_size: int) -> None:
    try:
        if command == "create-user" and email:
            password = getpass.getpass("Password (15–128 characters): ")
            if password != getpass.getpass("Confirm password: "):
                raise ValueError("Passwords do not match")
            await create_user(email, password)
            print("User created")
        elif command == "disable-user" and email:
            await disable_user(email)
            print("User disabled and sessions revoked")
        else:
            print(f"Removed {await cleanup(batch_size)} expired records")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("create-user", "disable-user"):
        sub = commands.add_parser(command)
        sub.add_argument("email")
    commands.add_parser("cleanup").add_argument("--batch-size", type=int, default=500)
    arguments = parser.parse_args()
    try:
        asyncio.run(
            run(
                arguments.command,
                getattr(arguments, "email", None),
                getattr(arguments, "batch_size", 500),
            )
        )
    except IntegrityError:
        parser.exit(1, "Account already exists or violates account constraints\n")
    except ValidationError:
        parser.exit(1, "Invalid account input\n")
    except SQLAlchemyError:
        parser.exit(1, "Authentication storage unavailable\n")
    except ValueError as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
