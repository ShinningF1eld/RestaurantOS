"""Verify clean and representative legacy migrations on disposable PostgreSQL databases."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory
from test_support.disposable_postgres import TestDatabase, disposable_database

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
LEGACY_BASELINE = "c48b7e02f315"  # pragma: allowlist secret
RECIPE_REVISION = "d57c8f13a426"  # pragma: allowlist secret
ORDER_INVENTORY_REVISION = "e68d9a24b537"  # pragma: allowlist secret
RESTAURANT_ID = 101
MENU_ID = 101
MENU_ITEM_ID = 101
ACCEPTED_ORDER_ID = 101
COMPLETED_ORDER_ID = 102
INGREDIENT_ID = 101


def migration_script() -> ScriptDirectory:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return ScriptDirectory.from_config(config)


def unique_head(script: ScriptDirectory) -> str:
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Expected one Alembic head; found {len(heads)}")
    return heads[0]


def ancestors(script: ScriptDirectory, revision: str) -> set[str]:
    visited: set[str] = set()
    pending = [revision]
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        migration = script.get_revision(current)
        if migration is None:
            raise RuntimeError(
                f"Unknown Alembic revision in migration graph: {current}"
            )
        down_revisions = migration.down_revision
        if isinstance(down_revisions, tuple):
            pending.extend(down_revisions)
        elif down_revisions:
            pending.append(down_revisions)
    return visited


def run_alembic(*arguments: str, env: Mapping[str, str]) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND,
        env=dict(env),
        check=True,
    )


def current_revision(database: TestDatabase) -> str:
    with psycopg.connect(database.sync_url) as connection:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    if row is None:
        raise AssertionError("The disposable database has no Alembic revision")
    return row[0]


def seed_legacy_data(database: TestDatabase) -> None:
    """Create business rows at c48b7e02f315 to exercise later additive migrations."""

    with psycopg.connect(database.sync_url) as connection:
        organization_id = uuid4()
        connection.execute(
            "INSERT INTO organizations(id,name,slug) "
            "VALUES(%s,'Migration verification tenant',%s)",
            (
                organization_id,
                f"m6-migration-{database.name[-16:]}",
            ),
        )
        connection.execute(
            "INSERT INTO restaurants(id,organization_id,name,created_at,updated_at) "
            "VALUES(%s,%s,'Migration verification restaurant',now(),now())",
            (RESTAURANT_ID, organization_id),
        )
        connection.execute(
            "INSERT INTO menus(menu_id,restaurant_id,name) VALUES(%s,%s,'Legacy menu')",
            (MENU_ID, RESTAURANT_ID),
        )
        connection.execute(
            "INSERT INTO menu_items(menu_item_id,menu_id,name,price,is_available) "
            "VALUES(%s,%s,'Historical chicken',25,true)",
            (MENU_ITEM_ID, MENU_ID),
        )
        for order_id, status in (
            (ACCEPTED_ORDER_ID, "ACCEPTED"),
            (COMPLETED_ORDER_ID, "COMPLETED"),
        ):
            connection.execute(
                "INSERT INTO orders(order_id,restaurant_id,status,subtotal,total,created_at,updated_at) "
                "VALUES(%s,%s,%s,50,50,now(),now())",
                (order_id, RESTAURANT_ID, status),
            )
            connection.execute(
                "INSERT INTO order_items(order_item_id,order_id,menu_item_id,item_name,quantity,unit_price,line_total) "
                "VALUES(%s,%s,%s,'Historical chicken',2,25,50)",
                (order_id, order_id, MENU_ITEM_ID),
            )
        connection.execute(
            "INSERT INTO inventory_ingredients(id,restaurant_id,name,normalized_name,unit,reorder_threshold,is_active,created_at,updated_at) "
            "VALUES(%s,%s,'Chicken','chicken','g',100,true,now(),now())",
            (INGREDIENT_ID, RESTAURANT_ID),
        )
        connection.execute(
            "INSERT INTO inventory_balances(ingredient_id,quantity,version) VALUES(%s,1000,1)",
            (INGREDIENT_ID,),
        )
        connection.execute(
            "INSERT INTO inventory_movements(ingredient_id,kind,quantity_delta,balance_after,version_after,reason,idempotency_key,request_fingerprint,occurred_at) "
            "VALUES(%s,'opening',1000,1000,1,'Legacy opening','legacy-opening',%s,now())",
            (INGREDIENT_ID, "0" * 64),
        )


def legacy_data_snapshot(connection: psycopg.Connection) -> dict[str, list[tuple]]:
    queries = {
        "tenant_restaurant": (
            (
                "SELECT o.id,o.name,o.slug,r.id,r.organization_id,r.name "
                "FROM organizations o JOIN restaurants r ON r.organization_id=o.id "
                "WHERE r.id=%s"
            ),
            (RESTAURANT_ID,),
        ),
        "menus": (
            "SELECT menu_id,restaurant_id,name FROM menus WHERE menu_id=%s",
            (MENU_ID,),
        ),
        "menu_items": (
            (
                "SELECT menu_item_id,menu_id,name,price,is_available "
                "FROM menu_items WHERE menu_item_id=%s"
            ),
            (MENU_ITEM_ID,),
        ),
        "orders": (
            (
                "SELECT order_id,restaurant_id,status,subtotal,total,payment_status "
                "FROM orders WHERE order_id IN (%s,%s) ORDER BY order_id"
            ),
            (ACCEPTED_ORDER_ID, COMPLETED_ORDER_ID),
        ),
        "order_snapshots": (
            (
                "SELECT order_id,menu_item_id,item_name,quantity,unit_price,line_total "
                "FROM order_items WHERE order_id IN (%s,%s) ORDER BY order_id,order_item_id"
            ),
            (ACCEPTED_ORDER_ID, COMPLETED_ORDER_ID),
        ),
        "inventory_ingredients": (
            (
                "SELECT id,restaurant_id,name,normalized_name,unit,reorder_threshold,is_active "
                "FROM inventory_ingredients WHERE id=%s"
            ),
            (INGREDIENT_ID,),
        ),
        "inventory_balances": (
            "SELECT ingredient_id,quantity,version FROM inventory_balances WHERE ingredient_id=%s",
            (INGREDIENT_ID,),
        ),
        "inventory_movements": (
            (
                "SELECT id,ingredient_id,kind,quantity_delta,balance_after,version_after,reason,occurred_at "
                "FROM inventory_movements WHERE ingredient_id=%s ORDER BY id"
            ),
            (INGREDIENT_ID,),
        ),
    }
    return {
        name: connection.execute(query, parameters).fetchall()
        for name, (query, parameters) in queries.items()
    }


def schema_snapshot(connection: psycopg.Connection) -> tuple[list[tuple], ...]:
    columns = connection.execute(
        "SELECT table_name,column_name,ordinal_position,is_nullable,data_type,column_default "
        "FROM information_schema.columns WHERE table_schema='public' "
        "ORDER BY table_name,ordinal_position"
    ).fetchall()
    constraints = connection.execute(
        "SELECT relation.relname,con.conname,con.contype,pg_get_constraintdef(con.oid,true) "
        "FROM pg_constraint AS con "
        "JOIN pg_class AS relation ON relation.oid=con.conrelid "
        "JOIN pg_namespace AS namespace ON namespace.oid=relation.relnamespace "
        "WHERE namespace.nspname='public' ORDER BY relation.relname,con.conname"
    ).fetchall()
    indexes = connection.execute(
        "SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' "
        "ORDER BY tablename,indexname"
    ).fetchall()
    sequences = connection.execute(
        "SELECT sequence_name,data_type,start_value,minimum_value,maximum_value,increment,cycle_option "
        "FROM information_schema.sequences WHERE sequence_schema='public' "
        "ORDER BY sequence_name"
    ).fetchall()
    return columns, constraints, indexes, sequences


def guarded_history_snapshot(connection: psycopg.Connection) -> tuple[list[tuple], ...]:
    movements = connection.execute(
        "SELECT id,ingredient_id,kind,quantity_delta,balance_after,version_after,reason,order_id "
        "FROM inventory_movements ORDER BY id"
    ).fetchall()
    submissions = connection.execute(
        "SELECT restaurant_id,idempotency_key,order_id,request_fingerprint,response_snapshot "
        "FROM order_submissions ORDER BY id"
    ).fetchall()
    processed = connection.execute(
        "SELECT order_id,inventory_processed FROM orders ORDER BY order_id"
    ).fetchall()
    return movements, submissions, processed


def verify_untracked_legacy_rows(database: TestDatabase) -> None:
    with psycopg.connect(database.sync_url) as connection:
        tracking = connection.execute(
            "SELECT inventory_tracking FROM menu_items WHERE menu_item_id=%s",
            (MENU_ITEM_ID,),
        ).fetchone()
        processed = connection.execute(
            "SELECT order_id,inventory_processed FROM orders "
            "WHERE order_id IN (%s,%s) ORDER BY order_id",
            (ACCEPTED_ORDER_ID, COMPLETED_ORDER_ID),
        ).fetchall()
        assert tracking == (False,), (
            f"Legacy menu item became inventory tracked: {tracking}"
        )
        assert processed == [(ACCEPTED_ORDER_ID, False), (COMPLETED_ORDER_ID, False)], (
            f"Legacy orders became inventory processed: {processed}"
        )


def verify_history_downgrade_guard(
    database: TestDatabase, env: Mapping[str, str], head: str
) -> None:
    """Prove a prohibited downgrade rolls back both schema and business history."""

    with psycopg.connect(database.sync_url) as connection:
        connection.execute(
            "UPDATE orders SET inventory_processed=true WHERE order_id=%s",
            (ACCEPTED_ORDER_ID,),
        )
        connection.execute(
            "UPDATE inventory_balances SET quantity=990,version=2 WHERE ingredient_id=%s",
            (INGREDIENT_ID,),
        )
        connection.execute(
            "INSERT INTO inventory_movements(ingredient_id,kind,quantity_delta,balance_after,version_after,reason,order_id,occurred_at) "
            "VALUES(%s,'consumption',-10,990,2,'Migration verification accepted order',%s,now())",
            (INGREDIENT_ID, ACCEPTED_ORDER_ID),
        )
        connection.execute(
            "INSERT INTO order_submissions(restaurant_id,idempotency_key,order_id,request_fingerprint,response_snapshot,created_at) "
            "VALUES(%s,'m6-migration-order',%s,%s,'{}'::jsonb,now())",
            (RESTAURANT_ID, ACCEPTED_ORDER_ID, "0" * 64),
        )
        before_schema = schema_snapshot(connection)
        before_history = guarded_history_snapshot(connection)

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", RECIPE_REVISION],
        cwd=BACKEND,
        env=dict(env),
        capture_output=True,
        text=True,
        check=False,
    )
    diagnostics = result.stdout + result.stderr
    if result.returncode == 0 or "Cannot downgrade" not in diagnostics:
        raise AssertionError(
            "The order-inventory downgrade guard did not reject the seeded history"
        )

    with psycopg.connect(database.sync_url) as connection:
        after_schema = schema_snapshot(connection)
        after_history = guarded_history_snapshot(connection)
    if current_revision(database) != head:
        raise AssertionError("Rejected downgrade changed the Alembic revision")
    if after_schema != before_schema:
        raise AssertionError("Rejected downgrade left partial schema changes")
    if after_history != before_history:
        raise AssertionError("Rejected downgrade changed inventory or replay history")
    run_alembic("check", env=env)
    print(
        "PASS: prohibited order-history downgrade left schema and data unchanged",
        flush=True,
    )


def inject_failure(
    stage: str, requested_stage: str | None, database: TestDatabase
) -> None:
    if requested_stage == stage:
        raise RuntimeError(
            f"Injected failure after {stage}; disposable database was {database.name}"
        )


def verify_clean(head: str, fail_after: str | None) -> None:
    with disposable_database(prefix="restaurantos_m6_clean") as database:
        print(f"Created clean migration database {database.name}", flush=True)
        inject_failure("clean-created", fail_after, database)
        env = database.environment()
        run_alembic("upgrade", head, env=env)
        run_alembic("check", env=env)
        if current_revision(database) != head:
            raise AssertionError("Clean database did not reach the unique Alembic head")
        inject_failure("clean-upgrade", fail_after, database)
        print(
            f"PASS: clean database upgraded to unique Alembic head {head}", flush=True
        )


def verify_legacy(head: str, script: ScriptDirectory, fail_after: str | None) -> None:
    graph = ancestors(script, head)
    if LEGACY_BASELINE not in graph:
        raise RuntimeError(
            f"Legacy baseline {LEGACY_BASELINE} is not an ancestor of current head {head}; "
            "advance the documented baseline and fixture before relying on this check"
        )

    with disposable_database(prefix="restaurantos_m6_legacy") as database:
        print(f"Created legacy migration database {database.name}", flush=True)
        inject_failure("legacy-created", fail_after, database)
        env = database.environment()
        run_alembic("upgrade", LEGACY_BASELINE, env=env)
        seed_legacy_data(database)
        with psycopg.connect(database.sync_url) as connection:
            before = legacy_data_snapshot(connection)

        run_alembic("upgrade", head, env=env)
        run_alembic("check", env=env)
        if current_revision(database) != head:
            raise AssertionError(
                "Legacy database did not reach the unique Alembic head"
            )
        with psycopg.connect(database.sync_url) as connection:
            after = legacy_data_snapshot(connection)
        if after != before:
            changed = [name for name in before if before[name] != after[name]]
            raise AssertionError(
                f"Legacy business data changed during upgrade: {changed}"
            )
        verify_untracked_legacy_rows(database)
        inject_failure("legacy-upgrade", fail_after, database)
        print(
            "PASS: legacy tenant, order snapshots, and inventory history survived upgrade",
            flush=True,
        )

        if ORDER_INVENTORY_REVISION in graph:
            if RECIPE_REVISION not in graph:
                raise RuntimeError(
                    "Order-inventory revision is present without its recipe predecessor"
                )
            verify_history_downgrade_guard(database, env, head)
        else:
            print(
                "SKIP: current migration graph has no order-inventory downgrade guard",
                flush=True,
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Requires an explicit TEST_DATABASE_URL ending in _test on a local or "
            "documented test-service host. The configured database is never migrated."
        ),
    )
    parser.add_argument(
        "--scenario",
        choices=("both", "clean", "legacy"),
        default="both",
        help="Choose clean-head verification, seeded legacy verification, or both (default)",
    )
    parser.add_argument(
        "--inject-failure-after",
        choices=("clean-created", "clean-upgrade", "legacy-created", "legacy-upgrade"),
        help="Intentionally fail at a named stage to verify nonzero exit and database cleanup",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.inject_failure_after and args.scenario not in {
        "both",
        args.inject_failure_after.split("-", maxsplit=1)[0],
    }:
        print(
            "FAIL: injected stage is not included in the selected scenario",
            file=sys.stderr,
        )
        return 2

    try:
        script = migration_script()
        head = unique_head(script)
        if args.scenario in {"both", "clean"}:
            verify_clean(head, args.inject_failure_after)
        if args.scenario in {"both", "legacy"}:
            verify_legacy(head, script, args.inject_failure_after)
    except Exception as exc:  # noqa: BLE001 - report every verifier failure at the CLI boundary
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
