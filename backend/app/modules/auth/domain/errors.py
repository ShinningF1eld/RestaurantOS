class AuthenticationError(Exception):
    """Invalid credentials or an unusable session; no sensitive context."""


class RateLimitError(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after


class AuthStorageError(Exception):
    """Authentication persistence is unavailable."""
