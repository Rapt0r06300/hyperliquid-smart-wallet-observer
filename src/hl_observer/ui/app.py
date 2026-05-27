from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from hl_observer.config.loader import load_settings
from hl_observer.config.settings import Settings
from hl_observer.ui.event_bus import UiEventBus
from hl_observer.ui.persistent_state import load_or_create_ui_state
from hl_observer.ui.routes import create_router
from hl_observer.ui.state import UiState


def create_ui_app(settings: Settings | None = None, state: UiState | None = None) -> FastAPI:
    settings = settings or load_settings()
    state = state or load_or_create_ui_state(settings)
    bus = UiEventBus()
    app = FastAPI(title="Hyperliquid Smart-Wallet Observer Command Center")
    static_dir = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(create_router(settings, state, bus))
    app.state.ui_settings = settings
    app.state.ui_state = state
    app.state.ui_bus = bus
    return app
