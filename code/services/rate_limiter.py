import time
import random
from typing import List
from services.exceptions import RateLimitExceededError


class RateLimiter:
    def __init__(self, min_wait: float = 10.0, max_wait: float = 30.0, hourly_cap: int = 8):
        self.min_wait = min_wait
        self.max_wait = max_wait
        self.hourly_cap = hourly_cap
        self._timestamps: List[float] = []

    def _count_recent(self) -> int:
        now = time.time()
        self._timestamps = [t for t in self._timestamps if now - t < 3600]
        return len(self._timestamps)

    def wait(self) -> None:
        count = self._count_recent()
        if count >= self.hourly_cap:
            raise RateLimitExceededError(
                f"Hourly rate limit reached: {count}/{self.hourly_cap} calls in the last hour."
            )
        sleep_time = random.uniform(self.min_wait, self.max_wait)
        time.sleep(sleep_time)
        self._timestamps.append(time.time())

    def reset(self) -> None:
        self._timestamps = []
