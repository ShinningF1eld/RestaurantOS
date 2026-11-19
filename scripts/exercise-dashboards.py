"""Exercise RestaurantOS dashboards against a dedicated loopback test restaurant."""

from __future__ import annotations

import argparse
import re
import sys
import warnings
from datetime import UTC, datetime
from decimal import Decimal
from getpass import GetPassWarning, getpass
from time import monotonic, sleep
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

RESTAURANT_NAME = "Dashboard Exercise (TEST)"
MENU_NAME = "Dashboard Test Menu"
ITEM_NAME = "Dashboard Test Order"
INGREDIENT_NAME = "Dashboard Test Stock"
STATES = ("DRAFT", "SUBMITTED", "ACCEPTED", "PREPARING", "READY", "COMPLETED")
LOCAL_ORIGIN = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?"
)


class ExerciseError(Exception):
    """A safe diagnostic that contains no credentials or response bodies."""


def request(client, method, path, payload=None, *, status=200):
    try:
        response = client.request(method, path, json=payload)
    except httpx.RequestError as error:
        raise ExerciseError(
            f"{method} {path} failed ({type(error).__name__})."
        ) from None
    if response.status_code != status:
        hint = {
            401: " Check the test credentials or sign in again with the same run ID.",
            403: " Check the trusted Origin and the test account's branch permissions.",
            429: " Wait for the login throttle to clear before retrying.",
        }.get(response.status_code, "")
        raise ExerciseError(
            f"{method} {path} returned HTTP {response.status_code}.{hint}"
        )
    if status != 204:
        return response.json()


def fixture(client, restaurant_id):
    restaurant = f"/api/restaurants/{restaurant_id}"
    inventory = f"{restaurant}/inventory"
    if request(client, "GET", restaurant)["name"] != RESTAURANT_NAME:
        raise ExerciseError(
            f"The selected restaurant must be named {RESTAURANT_NAME!r}."
        )

    menu = only_fixture(
        request(client, "GET", f"/restaurants/{restaurant_id}/menus"), MENU_NAME
    )
    items_path = f"/menus/{menu['menu_id']}/items"
    item = only_fixture(request(client, "GET", items_path), ITEM_NAME)
    ingredient = only_fixture(
        request(client, "GET", f"{inventory}/ingredients"), INGREDIENT_NAME
    )
    item_id = item["menu_item_id"]
    ingredient_id = ingredient["id"]
    recipe = request(client, "GET", f"/menu-items/{item_id}/recipe")
    components = [
        (part["ingredient_id"], Decimal(part["quantity"]))
        for part in recipe["components"]
    ]
    if (
        item["restaurant_id"] != restaurant_id
        or ingredient["restaurant_id"] != restaurant_id
        or not item["is_available"]
        or Decimal(item["price"]) <= 0
        or not recipe["inventory_tracking"]
        or components != [(ingredient_id, Decimal(1))]
        or not ingredient["is_active"]
        or ingredient["unit"] != "piece"
        or Decimal(ingredient["reorder_threshold"]) != 1
    ):
        raise ExerciseError(
            "The menu item, tracked recipe or ingredient does not match the test fixture."
        )
    return item_id, ingredient_id, items_path


def only_fixture(rows, name):
    if len(rows) != 1 or rows[0]["name"] != name:
        raise ExerciseError(
            f"The test restaurant must contain exactly one {name!r} in its fixture."
        )
    return rows[0]


def balance(client, inventory):
    ingredient = only_fixture(
        request(client, "GET", f"{inventory}/ingredients"), INGREDIENT_NAME
    )
    return Decimal(ingredient["quantity"])


def check_stock(client, inventory, movements, receipt_reasons):
    quantity = balance(client, inventory)
    if quantity == 2:
        latest = request(client, "GET", f"{movements}?limit=1")
        if (
            not latest
            or latest[0]["kind"] != "receipt"
            or latest[0]["reason"] not in receipt_reasons
        ):
            raise ExerciseError(
                "Stock is already 2 from another operation. Resume the original run first."
            )
    elif quantity != 1:
        raise ExerciseError("Expected 1 piece before receiving test stock.")


def receive_one(client, inventory, movements, key):
    reason = f"Dashboard exercise {key}"
    check_stock(client, inventory, movements, {reason})
    receipt = request(
        client,
        "POST",
        movements,
        {"kind": "receipt", "quantity": "1", "reason": reason, "idempotency_key": key},
        status=201,
    )
    if Decimal(receipt["balance_after"]) != 2:
        raise ExerciseError("The receipt did not bring stock to 2 pieces.")


def complete_order(client, restaurant, inventory, movements, item_id, key):
    created = request(
        client,
        "POST",
        f"{restaurant}/orders",
        {
            "idempotency_key": f"{key}-order",
            "notes": key,
            "items": [{"menu_item_id": item_id, "quantity": 1}],
        },
        status=201,
    )
    order_path = f"/api/orders/{created['order_id']}"
    # Create replays return the original DRAFT snapshot. Read the live state.
    order = request(client, "GET", order_path)
    current = order["status"]
    if (
        order["restaurant_id"] != int(restaurant.rsplit("/", 1)[1])
        or current not in STATES
    ):
        raise ExerciseError(
            "The saved order is outside the expected scope or lifecycle."
        )
    for state in STATES[STATES.index(current) + 1 :]:
        if state == "ACCEPTED":
            receive_one(client, inventory, movements, f"{key}-receipt")
        order = request(client, "PUT", order_path, {"status": state})
        if order["status"] != state:
            raise ExerciseError(f"The order did not reach {state}.")
        if state == "ACCEPTED" and balance(client, inventory) != 1:
            raise ExerciseError("Acceptance did not return test stock to 1 piece.")
    return order, current == "COMPLETED"


def utc(value):
    timestamp = datetime.fromisoformat(value)
    return (
        timestamp.replace(tzinfo=UTC)
        if timestamp.tzinfo is None
        else timestamp.astimezone(UTC)
    )


def verify_projection(client, inventory, ingredient_id, orders, wait_seconds):
    # Each workflow's low-stock opening is between its draft and completion.
    windows = [(utc(order["created_at"]), utc(order["updated_at"])) for order in orders]
    deadline = monotonic() + wait_seconds
    while True:
        rows = request(client, "GET", f"{inventory}/alerts/history?limit=100")["items"]
        openings = [
            utc(row["opened_at"])
            for row in rows
            if row["ingredient_id"] == ingredient_id
            and row["opening_source"] == "order_acceptance"
        ]
        projected = sum(
            any(start <= opened <= end for opened in openings) for start, end in windows
        )
        if projected == len(orders):
            print(
                f"Worker projected {projected}/{len(orders)} low-stock episodes.",
                flush=True,
            )
            return
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ExerciseError(
                f"Orders are complete. Worker projected {projected}/{len(orders)} "
                "episodes in the latest 100 history rows. Check worker progress."
            )
        sleep(min(3, remaining))


def exercise(client, args, run_id):
    restaurant = f"/api/restaurants/{args.restaurant_id}"
    inventory = f"{restaurant}/inventory"
    item_id, ingredient_id, items_path = fixture(client, args.restaurant_id)
    movements = f"{inventory}/ingredients/{ingredient_id}/movements"
    menus_path = f"/restaurants/{args.restaurant_id}/menus"
    keys = [
        f"dashboard-{run_id}-{iteration:02d}" for iteration in range(1, args.count + 1)
    ]
    check_stock(
        client,
        inventory,
        movements,
        {f"Dashboard exercise {key}-receipt" for key in keys},
    )

    orders = []
    for iteration, key in enumerate(keys, start=1):
        for _ in range(2):
            request(client, "GET", menus_path)
            request(client, "GET", items_path)
        order, replay = complete_order(
            client, restaurant, inventory, movements, item_id, key
        )
        orders.append(order)
        request(client, "GET", f"{restaurant}/analytics/dashboard")
        print(
            f"{iteration}/{args.count}  Order {order['order_id']} "
            f"{'already complete' if replay else 'completed'}",
            flush=True,
        )
        if iteration < args.count:
            sleep(args.pause_seconds)

    if balance(client, inventory) != 1:
        raise ExerciseError("The test ingredient did not finish at 1 piece.")
    verify_projection(
        client, inventory, ingredient_id, orders, args.worker_wait_seconds
    )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restaurant-id", type=int, required=True)
    parser.add_argument(
        "--confirm-test-data",
        action="store_true",
        help="Confirm the API and restaurant are reserved for local test data.",
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--origin", default="http://localhost:3000")
    parser.add_argument("--email", help="Test account email. The password is prompted.")
    parser.add_argument("--count", type=int, default=20, metavar="1-30")
    parser.add_argument("--pause-seconds", type=int, default=3, metavar="1-10")
    parser.add_argument("--worker-wait-seconds", type=int, default=60, metavar="0-120")
    parser.add_argument(
        "--run-id", help="Reuse the printed ID and original count to resume."
    )
    args = parser.parse_args()
    if not args.confirm_test_data or args.restaurant_id <= 0:
        parser.error("A positive --restaurant-id and --confirm-test-data are required.")
    for url in (args.base_url, args.origin):
        try:
            if LOCAL_ORIGIN.fullmatch(url) and urlsplit(url).port != 0:
                continue
        except ValueError:
            pass
        parser.error("--base-url and --origin must be loopback origins without a path.")
    if not (
        1 <= args.count <= 30
        and 1 <= args.pause_seconds <= 10
        and 0 <= args.worker_wait_seconds <= 120
    ):
        parser.error(
            "Use a count of 1–30, a pause of 1–10s and a worker wait of 0–120s."
        )
    if args.run_id is not None and not re.fullmatch(r"[0-9a-f]{32}", args.run_id):
        parser.error(
            "--run-id must be the 32-character lowercase hex ID printed at startup."
        )
    return args


def main():
    args = parse_args()
    run_id = args.run_id or uuid4().hex
    print(
        f"Run ID {run_id} | restaurant {args.restaurant_id} | {args.count} workflows",
        flush=True,
    )
    try:
        email = args.email or input("Test account email: ").strip()
        # Fail closed if the console cannot suppress password echo.
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            password = getpass("Test account password: ")
        with httpx.Client(
            base_url=args.base_url,
            headers={"Origin": args.origin, "X-CSRF-Protection": "1"},
            timeout=10,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            request(
                client, "POST", "/auth/login", {"email": email, "password": password}
            )
            del password
            try:
                exercise(client, args, run_id)
            finally:
                try:
                    request(client, "POST", "/auth/logout", status=204)
                except ExerciseError:
                    print(
                        "Test session logout could not be confirmed.", file=sys.stderr
                    )
    except (
        KeyboardInterrupt,
        EOFError,
        GetPassWarning,
        ExerciseError,
        ValueError,
        KeyError,
        TypeError,
        ArithmeticError,
    ) as error:
        message = (
            str(error)
            if isinstance(error, ExerciseError)
            else (
                "Interrupted or no secure input available."
                if isinstance(error, (KeyboardInterrupt, EOFError, GetPassWarning))
                else "Unexpected API response. Check the local API version and fixture."
            )
        )
        print(
            f"{message} Resume with --run-id {run_id} and the original count.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
