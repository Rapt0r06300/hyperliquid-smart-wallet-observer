from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from hl_observer.config.loader import load_settings
from hl_observer.config.settings import Settings
from hl_observer.storage.database import init_db
from hl_observer.ui.event_bus import UiEventBus
from hl_observer.ui.persistent_state import load_or_create_ui_state
from hl_observer.ui.routes import create_router
from hl_observer.ui.state import UiState
from hl_observer.ui.status_routes import create_status_router


SMOOTH_METAGRAPH_SCRIPT = '<script src="/static/metagraph_smooth_v2.js?v=simulation-ui-20260615-smooth-metagraph-v3"></script>'


def _inject_smooth_metagraph_script(html: str) -> str:
    if "metagraph_smooth" in html:
        return html
    marker = '<script src="/static/app.js?v=simulation-ui-20260612-antijump-v5"></script>'
    replacement = marker + "\n    " + SMOOTH_METAGRAPH_SCRIPT
    if marker in html:
        return html.replace(marker, replacement, 1)
    return html.replace("</body>", f"    {SMOOTH_METAGRAPH_SCRIPT}\n  </body>", 1)


def create_ui_app(settings: Settings | None = None, state: UiState | None = None) -> FastAPI:
    settings = settings or load_settings()
    # The dashboard must be able to start from a fresh runtime DB. The launcher
    # also runs init-db, but keeping this here prevents a half-started UI from
    # returning 500s when the session database is new or was rotated.
    init_db(settings.database_url)
    state = state or load_or_create_ui_state(settings)
    bus = UiEventBus()
    app = FastAPI(title="HyperSmart Observer - Hyperliquid Command Center")
    static_dir = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(create_router(settings, state, bus))
    # Fast read-only tick endpoint kept out of the huge routes.py (see status_routes).
    app.include_router(create_status_router(state, settings=settings))

    @app.middleware("http")
    async def inject_smooth_metagraph(request: Request, call_next):
        if request.url.path == "/":
            template_path = Path(__file__).with_name("templates") / "index.html"
            try:
                html = template_path.read_text(encoding="utf-8")
                return HTMLResponse(_inject_smooth_metagraph_script(html))
            except OSError:
                pass
        return await call_next(request)

    app.state.ui_settings = settings
    app.state.ui_state = state
    app.state.ui_bus = bus
    return app
