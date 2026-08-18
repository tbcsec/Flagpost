"""Real-time layer (ARCHITECTURE.md §4.1) — kernel infrastructure.

Like the event bus, this is platform plumbing rather than a feature module:
``main.py`` mounts the one WebSocket endpoint, and feature modules register
the room types they own (scoreboard now; announcements, tickets, presence
later) via :func:`register_room_type`.
"""

from realtime.manager import ConnectionManager, manager
from realtime.router import register_room_type, router


async def start_realtime() -> None:
    """Wire the cross-process realtime layer (#189, ADR-0025/0026/0031): the
    broadcast relay and the shared presence store + its heartbeat.

    Needed whenever more than one app process serves WS clients — multiple
    workers in one container (``web_concurrency > 1``) *or* multiple
    containers/hosts behind a load balancer (``MULTI_INSTANCE=1``, ADR-0031).
    The relay is plain Redis pub/sub, so it spans hosts exactly as it spans
    workers. A lone single-worker process is a no-op. Raises without a
    ``redis_url`` when either signal says other processes exist — a deployment
    that can't relay would silently drop broadcasts to the other processes'
    clients and fragment presence, so it must fail loudly at startup instead.
    """
    from config import settings

    if settings.web_concurrency <= 1 and not settings.multi_instance:
        return
    if not settings.redis_url:
        raise RuntimeError(
            "Cross-process realtime needs REDIS_URL: WEB_CONCURRENCY > 1 "
            "and/or MULTI_INSTANCE=1 mean other processes serve WS clients "
            "too, and without the Redis broadcast relay + presence store "
            "(#189, ADR-0031) broadcasts reach only the emitting process's "
            "clients and presence fragments."
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
