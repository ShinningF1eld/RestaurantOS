"""Order aggregate revision helpers shared by future event producers."""


def next_order_revision(current_revision: int) -> int:
    """Return the next persisted revision, rejecting invalid legacy state."""
    if (
        not isinstance(current_revision, int)
        or isinstance(current_revision, bool)
        or current_revision < 1
    ):
        raise ValueError("order revision must be a positive integer")
    return current_revision + 1
