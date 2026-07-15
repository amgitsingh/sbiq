from __future__ import annotations

import functools
import logging
from typing import Any, Callable, ParamSpec, TypeVar

from app.core.config import settings

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def toggleable(setting_name: str, empty_value: Any) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Gate an enrichment source function behind a boolean config flag.

    When settings.<setting_name> is False, the wrapped function is never
    called — it immediately returns empty_value and logs at INFO. Lets any
    source be "plugged out" (e.g. no paid API key yet) purely via config,
    with no change to the source's own logic or its call sites.

    empty_value is intentionally untyped (Any) rather than bound to the
    decorated function's return type R: R is solved from fn's own signature
    when the decorator is applied, and typing empty_value as R would create
    a second, earlier call site for the type checker to solve R from
    (toggleable(...) itself, before fn is even known) — which breaks for any
    R containing None, since a bare `None` argument narrows to the literal
    None type rather than the wider R. Correctness of empty_value's shape is
    covered by this module's tests, not by static typing.

    Callers must treat the returned empty_value as read-only — it is the
    same object on every disabled call, not a fresh one per call.
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            if not getattr(settings, setting_name):
                logger.info(f"{fn.__name__} disabled via {setting_name}=False - skipping")
                return empty_value
            return fn(*args, **kwargs)

        return wrapper

    return decorator
