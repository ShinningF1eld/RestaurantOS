"""Pure event retry policy; infrastructure probes have a separate allowance."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 8

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 100:
            raise ValueError("Attempt limit must be between 1 and 100")

    def delay_seconds(self, attempt_count: int, jitter: float) -> float:
        if attempt_count < 1 or not 0 <= jitter <= 1:
            raise ValueError("Invalid retry policy input")
        base = min(60, 2 ** min(attempt_count - 1, 6))
        return min(60.0, base * (1 + 0.1 * jitter))
