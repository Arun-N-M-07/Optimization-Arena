"""Tiny TTL cache for the unauthenticated endpoints, cleared whenever an admin action can change what they show."""
import contextvars
import time

TTL = 3.0   # seconds
_cache: dict = {}


_generation = 0


def cached(key, fn):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < TTL:
        return hit[1]
    started_in = _generation
    val = fn()
    if started_in == _generation:       # computed across an invalidation => its snapshot may predate the write: never cache it
        _cache[key] = (time.monotonic(), val)
    return val


def clear() -> None:
    global _generation
    _generation += 1
    _cache.clear()


# Clearing must happen AFTER the writer's transaction commits: clearing earlier lets a concurrent poller re-cache the old
# data in the commit window. Writers call changed(); db.admin_tx() calls flush_if_changed() once the commit succeeded.
_dirty: contextvars.ContextVar[bool] = contextvars.ContextVar("public_dirty", default=False)


def changed() -> None:
    _dirty.set(True)


def reset() -> None:
    _dirty.set(False)


def flush_if_changed() -> None:
    if _dirty.get():
        _dirty.set(False)
        clear()
