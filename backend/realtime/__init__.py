"""Real-time layer (ARCHITECTURE.md §4.1) — kernel infrastructure.

Like the event bus, this is platform plumbing rather than a feature module:
``main.py`` mounts the one WebSocket endpoint, and feature modules register
the room types they own (scoreboard now; announcements, tickets, presence
later) via :func:`register_room_type`.
"""

from realtime.manager import ConnectionManager, manager
from realtime.router import register_room_type, router

__all__ = ["ConnectionManager", "manager", "register_room_type", "router"]
