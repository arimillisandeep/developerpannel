import anyio
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.connections: dict[int, set[WebSocket]] = {}

    async def connect(self, user_id: int, ws: WebSocket):
        await ws.accept()
        self.connections.setdefault(user_id, set()).add(ws)

    def disconnect(self, user_id: int, ws: WebSocket):
        self.connections.get(user_id, set()).discard(ws)

    async def send(self, user_id: int, message: dict):
        for ws in list(self.connections.get(user_id, ())):
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(user_id, ws)

    def send_from_thread(self, user_id: int, message: dict):
        """Called from sync endpoints (which run in a worker thread)."""
        if not self.connections.get(user_id):
            return
        try:
            anyio.from_thread.run(self.send, user_id, message)
        except Exception:
            pass  # the notification is already stored; live push is best-effort


manager = ConnectionManager()
