"""Audit summaries include only structured, approved business facts."""

# No request bodies, free-text notes, customer details, passwords or tokens.
SAFE_FIELDS = frozenset(
    {
        "role",
        "status",
        "restaurant_ids",
        "price",
        "is_available",
        "payment_status",
        "quantity",
        "total",
        "fields",
        "outcome",
    }
)


def safe_changes(changes: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in changes.items() if key in SAFE_FIELDS}
