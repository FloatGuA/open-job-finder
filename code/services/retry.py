import time
import logging
from typing import Callable, Any
from functools import wraps

logger = logging.getLogger(__name__)


def with_retry(
    func: Callable,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    exceptions: tuple = (Exception,),
    no_retry_on: tuple = (),
) -> Any:
    """
    Call func(). On exception, wait base_delay * (2 ** attempt) seconds and retry.
    Raise the last exception if all attempts fail.
    Log each retry attempt at WARNING level.

    no_retry_on: exception types that should propagate immediately without retrying.
    """
    last_exc = None
    for attempt in range(max_attempts):
        try:
            return func()
        except no_retry_on:
            raise
        except exceptions as e:
            last_exc = e
            if attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Attempt {attempt + 1}/{max_attempts} failed: {e}. Retrying in {delay:.1f}s...")
                time.sleep(delay)
            else:
                logger.warning(f"Attempt {attempt + 1}/{max_attempts} failed: {e}. No more retries.")
    raise last_exc


def retry(max_attempts: int = 3, base_delay: float = 1.0, exceptions: tuple = (Exception,)):
    """Decorator wrapping with_retry."""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return with_retry(
                lambda: func(*args, **kwargs),
                max_attempts=max_attempts,
                base_delay=base_delay,
                exceptions=exceptions
            )
        return wrapper
    return decorator
