"""Real-time layer (ARCHITECTURE.md §4.1) — kernel infrastructure.

Like the event bus, this is platform plumbing rather than a feature module:
``main.py`` mounts the one WebSocket endpoint, and feature modules register
the room types they own (scoreboard now; announcements, tickets, presence
later) via :func:`register_room_type`.
"""

from realtime.manager import ConnectionManager, manager
from realtime.router import register_room_type, router


async def start_realtime() -> None:
    """Wire the cross-worker realtime layer when running multi-worker (#189,
    ADR-0025/0026): the broadcast relay and the shared presence store + its
    heartbeat. Single-worker is a no-op. Raises if ``web_concurrency > 1``
    without a ``redis_url`` — a multi-worker deployment that can't relay would
    silently drop broadcasts to most clients and fragment presence, so it must
    fail loudly at startup instead.
    """
    from config import settings

    if settings.web_concurrency <= 1:
        return
    if not settings.redis_url:
        raise RuntimeError(
            "web_concurrency > 1 requires REDIS_URL: multi-worker needs the "
            "Redis broadcast relay + presence store (#189), or broadcasts reach "
            "only the clients on the emitting worker and presence fragments."
        )
    from realtime.presence_store import RedisPresenceStore
    from realtime.relay import RedisRelay

    relay = RedisRelay(
        settings.redis_url,
        max_connections=settings.redis_max_connections,
        acquire_timeout_seconds=settings.redis_acquire_timeout_seconds,
    )
    manager.attach_relay(relay)
    await manager.start_relay()

    store = RedisPresenceStore(
        settings.redis_url,
        manager.worker_id,
        ttl_seconds=settings.ws_presence_ttl_seconds,
        max_connections=settings.redis_max_connections,
        acquire_timeout_seconds=settings.redis_acquire_timeout_seconds,
    )
    manager.attach_presence_store(store)
    await manager.start_presence(settings.ws_presence_heartbeat_seconds)


async def stop_realtime() -> None:
    """Tear down the relay subscriber and presence heartbeat. No-op single-worker."""
    await manager.stop_presence()
    await manager.stop_relay()


__all__ = [
    "ConnectionManager",
    "manager",
    "register_room_type",
    "router",
    "start_realtime",
    "stop_realtime",
]
