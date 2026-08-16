from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from hl_observer.config.loader import load_settings
from hl_observer.config.settings import Settings
from hl_observer.storage.database import init_db
from hl_observer.ui import dashboard_v2 as dashboard_v2_module
from hl_observer.ui.economic_writer import EconomicWriter
from hl_observer.ui.event_bus import UiEventBus
from hl_observer.ui.persistent_state import load_or_create_ui_state
from hl_observer.ui.read_only_status_router import create_read_only_status_router
from hl_observer.ui.routes import create_router
from hl_observer.ui.state import UiState
from hl_observer.ui.status_routes import create_status_router
from hl_observer.ops.echec_silencieux import noter as _noter_echec


BRAND_NAME = "Alina SmartFlow"
SMOOTH_METAGRAPH_SCRIPT = '<script src="/static/metagraph_smooth_v2.js?v=simulation-ui-20260615-smooth-metagraph-v3"></script>'


def _apply_branding(html: str) -> str:
    replacements = (
        ("HyperSmart Observer - Hyperliquid Command Center", f"{BRAND_NAME} - Hyperliquid Command Center"),
        ("HyperSmart Observer - Hyperliquid", f"{BRAND_NAME} - Hyperliquid"),
        ("Hyperliquid Smart-Wallet Observer - Simulation Paper", f"{BRAND_NAME} - Hyperliquid Smart-Wallet Observer"),
        ("HYPERSMART // OBSERVER", "ALINA SMARTFLOW // OBSERVER"),
    )
    for old, new in replacements:
        html = html.replace(old, new)
    return html


def _inject_smooth_metagraph_script(html: str) -> str:
    html = _apply_branding(html)
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
    app = FastAPI(title=f"{BRAND_NAME} - Hyperliquid Command Center")
    static_dir = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # One lock, one paper-economic writer. HTTP GETs only project state. Prime one
    # tick as part of SERVER construction so economic correctness never depends on
    # a browser request or FastAPI lifespan semantics.
    economic_lock = threading.RLock()
    economic_writer = EconomicWriter(state, settings, lock=economic_lock)
    try:
        economic_writer.tick()
    except Exception as exc:  # startup remains available for diagnostics; writer retries later.
        economic_writer.last_error = f"{exc.__class__.__name__}: {exc}"
        _noter_echec("hl_observer/ui/app.py:economic_writer_prime", exc)

    app.include_router(create_router(settings, state, bus))
    # IMPORTANT: first matching route wins in Starlette/FastAPI. Register the pure
    # projection before the legacy compatibility router so browser polling cannot
    # mutate positions, ledger, PnL, disk state or network traffic.
    app.include_router(
        create_read_only_status_router(
            state,
            settings=settings,
            economic_writer=economic_writer,
            lock=economic_lock,
        )
    )
    # Keep other legacy status endpoints (notably /fusion-status) compatible.
    # Its duplicate /api/simulation/status declaration is intentionally shadowed.
    app.include_router(create_status_router(state, settings=settings))
    if hasattr(dashboard_v2_module, "_PAGE"):
        dashboard_v2_module._PAGE = _apply_branding(dashboard_v2_module._PAGE)
    app.include_router(dashboard_v2_module.create_dashboard_v2_router())

    @app.on_event("startup")
    def _start_economic_writer() -> None:
        economic_writer.start()

    @app.on_event("shutdown")
    def _stop_economic_writer() -> None:
        economic_writer.stop()

    @app.middleware("http")
    async def inject_smooth_metagraph(request: Request, call_next):
        if request.url.path == "/":
            template_path = Path(__file__).with_name("templates") / "index.html"
            try:
                html = template_path.read_text(encoding="utf-8")
                return HTMLResponse(_inject_smooth_metagraph_script(html))
            except OSError as exc:
                _noter_echec("hl_observer/ui/app.py:index_template", exc)
        return await call_next(request)

    app.state.ui_settings = settings
    app.state.ui_state = state
    app.state.ui_bus = bus
    app.state.economic_lock = economic_lock
    app.state.economic_writer = economic_writer
    return app
