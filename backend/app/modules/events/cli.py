"""Trusted operator status, safe inspection and single-delivery replay."""

import argparse
import asyncio
import json
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError


async def run(arguments: argparse.Namespace) -> dict[str, object]:
    # Lazy configuration keeps --help independent of database/auth secrets.
    from app.core.config import get_settings
    from app.core.logging import configure_json_logging
    from app.db.database import AsyncSessionLocal, engine
    from app.modules.events.operator import EventOperatorService
    from app.modules.events.worker.redis import WorkerRedisFailure, WorkerRedisTransport
    from app.modules.events.worker.streams import EventStreams

    settings = get_settings()
    configure_json_logging(level=settings.log_level)
    service = EventOperatorService(AsyncSessionLocal)
    try:
        if arguments.command == "inspect":
            return await service.inspect(arguments.delivery_id)
        if arguments.command == "replay":
            replay_id = await service.replay(
                arguments.delivery_id, reason=arguments.reason
            )
            return {
                "delivery_id": str(arguments.delivery_id),
                "replay_id": str(replay_id),
                "status": "pending",
            }
        if arguments.command in {"analytics-inspect", "analytics-reconcile"}:
            from app.modules.analytics.service import AnalyticsProjectionService

            analytics = AnalyticsProjectionService(AsyncSessionLocal)
            method = (
                analytics.inspect
                if arguments.command == "analytics-inspect"
                else analytics.reconcile
            )
            return await method(arguments.organization_id, arguments.restaurant_id)
        if arguments.command in {"initialize", "analytics-rebuild"}:
            from app.modules.events.maintenance import EventMaintenanceService

            return await EventMaintenanceService(AsyncSessionLocal).run(
                arguments.organization_id,
                arguments.restaurant_id,
                kind="initialize"
                if arguments.command == "initialize"
                else "analytics_rebuild",
                reason=arguments.reason,
                maintenance_confirmed=arguments.maintenance_confirmed,
            )
        result = await service.status()
        transport = WorkerRedisTransport(settings)
        try:
            await transport.open()
            result["stream_size"] = await EventStreams(transport).length()
            result["redis_status"] = "available"
        except WorkerRedisFailure:
            result["stream_size"] = None
            result["redis_status"] = "unavailable"
        finally:
            try:
                await transport.close()
            except WorkerRedisFailure:
                pass
        return result
    finally:
        await engine.dispose()


def delivery_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Delivery ID must be a UUID") from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("inspect").add_argument("delivery_id", type=delivery_uuid)
    replay = commands.add_parser("replay")
    replay.add_argument("delivery_id", type=delivery_uuid)
    replay.add_argument("--reason", required=True)
    for name in ("analytics-inspect", "analytics-reconcile"):
        command = commands.add_parser(name)
        command.add_argument("--organization-id", required=True, type=UUID)
        command.add_argument("--restaurant-id", required=True, type=int)
    for name in ("initialize", "analytics-rebuild"):
        command = commands.add_parser(name)
        command.add_argument("--organization-id", required=True, type=UUID)
        command.add_argument("--restaurant-id", required=True, type=int)
        command.add_argument("--reason", required=True)
        command.add_argument(
            "--maintenance-confirmed",
            required=True,
            action="store_true",
            help="Confirm workers are stopped and business writes quiesced",
        )
    arguments = parser.parse_args()
    try:
        result = asyncio.run(run(arguments))
    except ValidationError:
        parser.exit(1, "Invalid operator configuration\n")
    except SQLAlchemyError:
        parser.exit(1, "Event storage operation failed\n")
    except (OSError, TimeoutError):
        parser.exit(1, "Event storage unavailable\n")
    except ValueError:
        parser.exit(1, "Invalid event operator input or target\n")
    except Exception:
        # Connection establishment can expose driver exceptions outside the
        # SQLAlchemy hierarchy. Never print their messages or traceback.
        parser.exit(1, "Event operator command failed\n")
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
