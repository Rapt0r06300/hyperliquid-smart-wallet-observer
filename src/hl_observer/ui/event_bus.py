from __future__ import annotations

from fastapi import WebSocket

from hl_observer.ui.schemas import UiEvent


class UiEventBus:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def broadcast(self, event: UiEvent) -> None:
        disconnected: list[WebSocket] = []
        for websocket in self._clients:
            try:
                await websocket.send_json(event.model_dump())
            except RuntimeError:
                disconnected.append(websocket)
        for websocket in disconnected:
            self.disconnect(websocket)
