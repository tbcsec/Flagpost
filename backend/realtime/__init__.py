"""Real-time layer (ARCHITECTURE.md §4.1) — kernel infrastructure.

Like the event bus, this is platform plumbing rather than a feature module:
``main.py`` mounts the one WebSocket endpoint, and feature modules register
the room types they own (scoreboard now; announcements, tickets, presence
later) via :func:`register_room_type`.
"""

from realtime.manager import ConnectionManager, manager
from realtime.router import register_room_type, router


async def start_broadcast_relay() -> None:
    """Attach + start the cross-worker broadcast relay when running multi-worker
    (#189, ADR-0025). Single-worker is a no-op. Raises if ``web_concurrency > 1``
    without a ``redis_url`` — a multi-worker deployment that can't relay would
    silently drop broadcasts to most clients, so it must fail loudly at startup
    instead.
    """
    from config import settings

    if settings.web_concurrency <= 1:
        return
    if not settings.redis_url:
        raise RuntimeError(
            "web_concurrency > 1 requires REDIS_URL: multi-worker needs the "
            "Redis broadcast relay (#189), or broadcasts reach only the clients "
            "on the emitting worker."
        )
    from realtime.relay import RedisRelay

    relay = RedisRelay(
        settings.redis_url,
        max_connections=settings.redis_max_connections,
        acquire_timeout_seconds=settings.redis_acquire_timeout_seconds,
    )
    manager.attach_relay(relay)
    await manager.start_relay()


__all__ = [
    "ConnectionManager",
    "manager",
    "register_room_type",
    "router",
    "start_broadcast_relay",
]
