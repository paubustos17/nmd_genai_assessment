"""Retry logic with exponential backoff for transient errors."""

import logging
import time
from functools import wraps
from typing import Any, Callable, TypeVar

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    backoff_multiplier: float = 2.0,
    exception_types: tuple = (ClientError,),
) -> Callable[[F], F]:
    """Decorator for exponential backoff retry logic.

    Args:
        max_attempts: Maximum number of attempts (default 3).
        base_delay: Initial delay in seconds (default 1.0).
        backoff_multiplier: Multiplier for delay between retries (default 2.0).
        exception_types: Tuple of exception types to catch and retry on.

    Returns:
        Decorated function with retry logic.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            delay = base_delay

            while attempt < max_attempts:
                try:
                    return func(*args, **kwargs)
                except exception_types as e:
                    attempt += 1
                    if attempt >= max_attempts:
                        logger.error(
                            "Function %s failed after %d attempts: %s",
                            func.__name__,
                            max_attempts,
                            str(e),
                        )
                        raise
                    logger.warning(
                        "Function %s failed (attempt %d/%d), retrying in %.1fs: %s",
                        func.__name__,
                        attempt,
                        max_attempts,
                        delay,
                        str(e),
                    )
                    time.sleep(delay)
                    delay *= backoff_multiplier

            return func(*args, **kwargs)

        return wrapper  # type: ignore

    return decorator
