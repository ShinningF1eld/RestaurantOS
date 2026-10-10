"""Read only a browser-owned cache key; never accept a Redis/database target."""

import json
import os
import re
import sys
from pathlib import Path

from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def main():
    url = make_url(os.environ["TEST_DATABASE_URL"])
    namespace = os.environ["REDIS_TEST_NAMESPACE"]
    container = os.environ["PLAYWRIGHT_REDIS_CONTAINER"]
    if (
        not (url.database or "").startswith("restaurantos_browser_")
        or not (url.database or "").endswith("_test")
        or not re.fullmatch(r"restaurantos-auth-outage-[a-f0-9]{12}", container)
        or not re.fullmatch(r"run-[a-f0-9]{32}", namespace)
    ):
        raise RuntimeError("Explicit browser-owned resources required")
    if sys.argv[1] == "limiter":
        log = Path(os.environ["PLAYWRIGHT_API_LOG"])
        if (
            not log.parent.name.startswith(".m6-browser-")
            or log.name != "browser-api.log"
        ):
            raise RuntimeError("Browser-owned API log required")
        events = []
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line).get("event", "")
            except ValueError:
                continue
            if event.startswith("auth_limiter_"):
                events.append(event)
        print(json.dumps(events))
        return
    restaurant_id, menu_id = map(int, sys.argv[1:3])
    engine = create_engine(
        url.set(drivername="postgresql+psycopg"), hide_parameters=True
    )
    try:
        with engine.connect() as connection:
            organization = connection.scalar(
                text("SELECT organization_id FROM restaurants WHERE id=:id"),
                {"id": restaurant_id},
            )
        prefix = f"restaurantos:test:{namespace}:catalog:v1:org:{organization}:"
        keys = [
            prefix + f"restaurant:{restaurant_id}:menus",
            prefix + f"menu:{menu_id}:items",
        ]
        with Redis.from_url(os.environ["REDIS_URL"], socket_timeout=2) as redis:
            result = []
            for key in keys:
                raw = redis.get(key)
                result.append(json.loads(raw) if raw else None)
        print(json.dumps(result))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
