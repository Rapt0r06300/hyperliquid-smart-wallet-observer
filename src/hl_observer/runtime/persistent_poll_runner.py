"""T44 — Runner de poll PERSISTANT : un seul process Python chaud pour tout le cycle.

Vérité mesurée (mini-T43, session 2026-07-08 ~01h30) : le poll .ps1 historique coûtait
~60-63 s alors que le travail utile en vaut ~30 : chaque étape payait un démarrage
Python À FROID (~2-4 s × ~8-14 étapes/poll) et les deux écoutes WebSocket (8 s + 10 s)
étaient purement séquentielles.

Ce runner :
- invoque les MÊMES commandes CLI (mêmes argv, mêmes gardes, mêmes sorties) mais
  in-process via typer/click CliRunner → imports chauds, zéro taxe de spawn ;
- lance les deux écoutes WS en sous-processus EN PARALLÈLE du bloc local qui n'en
  dépend pas (plans/discover/scan-markets), et les joint AVANT copy-run qui, lui,
  consomme leurs fills — l'ordre des dépendances est préservé ;
- écrit le même engine status JSON que le .ps1 (schéma identique, heartbeat pour le
  watchdog externe) et le même log live ;
- absorbe l'échec d'une étape (log + metrics) sans jamais tuer la boucle ;
- s'arrête proprement sur le stop-file, et peut se relancer tout seul tous les N polls
  (garde-fou mémoire d'un process qui vit des heures).

Read-only / paper-only : ce module n'introduit AUCUN appel nouveau — il orchestre les
commandes read-only existantes. Aucun ordre, aucune clé, aucune signature.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from hl_observer.ops.echec_silencieux import noter as _noter_echec

EXIT_STOP = 0
EXIT_SELF_RESTART = 3

_METRIC_LINE_RE = re.compile(r"^([A-Za-z0-9_]+)=(.*)$")
_METRIC_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_]{1,48})=([^ \t,;]+)")

_BASE_ENV_METRICS = {
    "sltp_enabled": "HYPERSMART_SLTP_ENABLED",
    "sltp_take_profit_bps": "HYPERSMART_SLTP_TAKE_PROFIT_BPS",
    "sltp_stop_loss_bps": "HYPERSMART_SLTP_STOP_LOSS_BPS",
    "sltp_trailing_bps": "HYPERSMART_SLTP_TRAILING_BPS",
    "sltp_trailing_activation_bps": "HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS",
    "sltp_breakeven_buffer_bps": "HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS",
    "sltp_stop_min_hold_ms": "HYPERSMART_SLTP_STOP_MIN_HOLD_MS",
    "sltp_catastrophic_stop_bps": "HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS",
    "adaptive_paper_sizing": "HYPERSMART_ADAPTIVE_PAPER_SIZING",
    "min_reduce_notional_usdt": "HYPERSMART_MIN_REDUCE_NOTIONAL_USDT",
    "v12_sqlite_path": "HYPERSMART_V12_SQLITE_PATH",
}

_FUSION_PRESERVED_TOP_KEYS = (
    "fusion_runtime_input",
    "fusion_runtime_input_status",
    "fusion_runtime_input_message",
)
_FUSION_PRESERVED_METRICS = (
    "fusion_runtime_input_status", "fusion_runtime_votes", "fusion_runtime_price_events",
    "fusion_runtime_coins", "fusion_runtime_reasons", "fusion_runtime_recent_deltas",
    "fusion_runtime_recent_entry_deltas", "fusion_runtime_latest_delta_age_ms",
    "fusion_runtime_state_source", "fusion_runtime_current_equity_usdt",
    "fusion_runtime_starting_equity_usdt", "fusion_runtime_peak_equity_usdt",
    "fusion_runtime_open_exposure_usdt",
)


def now_ms() -> int:
    return int(time.time() * 1000)


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, "")).strip())
    except (TypeError, ValueError):
        return default


@dataclass
class RunnerConfig:
    root: Path
    interval_seconds: int = 15
    max_leaders: int = 50
    leaders_per_poll: int = 10
    backfill_days: int = 1
    fresh_window_minutes: int = 1
    max_pages: int = 1
    public_trade_coins: str = "AUTO"
    public_trade_max_coins: int = 60
    public_trade_scan_seconds: int = 8
    public_trade_max_wallets: int = 10000
    public_trade_scan_every_polls: int = 1
    user_fills_max_live_age_ms: int = 20000
    max_runs: int = 5760
    plans_every_polls: int = 5
    diagnostics_every_polls: int = 5
    restart_every_polls: int = 400
    overlap_ws_scans: bool = True
    start_poll_index: int = 1
    fills_multiplex: bool = False
    fills_multiplex_connections: int = 4

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def logs_to_send_dir(self) -> Path:
        return self.logs_dir / ("logs à envoyer")

    @property
    def runtime_data_dir(self) -> Path:
        return self.root / "runtime" / "data"

    @property
    def live_log_path(self) -> Path:
        return self.logs_dir / "hypersmart_simulation_live.log"

    @property
    def engine_status_path(self) -> Path:
        return self.runtime_data_dir / "hypersmart_engine_status.json"

    @property
    def stop_file(self) -> Path:
        env = os.environ.get("HYPERSMART_RUNTIME_STOP_FILE", "").strip()
        if env:
            return Path(env)
        return self.runtime_data_dir / "hypersmart_runtime.stop"


@dataclass
class StepResult:
    label: str
    exit_code: int
    output: str
    duration_ms: int
    failed: bool = False


class PersistentPollRunner:
    """Boucle de poll chaude. Injectable pour les tests (invoke/popen/sleep/now)."""

    def __init__(
        self,
        config: RunnerConfig,
        *,
        invoke: Callable[[list[str]], tuple[int, str]] | None = None,
        popen: Callable[[list[str], Any], Any] | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_ms_fn: Callable[[], int] = now_ms,
    ) -> None:
        self.config = config
        self._invoke = invoke or self._default_invoke
        self._popen = popen or self._default_popen
        self._sleep = sleep_fn
        self._now_ms = now_ms_fn
        self.metrics: dict[str, str] = {
            "runtime_venue": "Hyperliquid",
            "paper_engine": "local_only",
            "loop_mode": "persistent_t44",
        }
        self.step_durations: dict[str, int] = {}
        self.current_poll = 0
        self._cli_runner = None
        self._session_id = ""

    # ------------------------------------------------------------------ infra

    def _default_invoke(self, argv: list[str]) -> tuple[int, str]:
        """Invoque une commande CLI in-process (imports chauds). Jamais d'exception."""
        if self._cli_runner is None:
            from typer.testing import CliRunner  # import tardif: peu coûteux, testable

            self._cli_runner = CliRunner()
        from hl_observer.cli import app  # chaud après le 1er appel

        result = self._cli_runner.invoke(app, argv, catch_exceptions=True)
        output = ""
        try:
            output = result.output or ""
        except Exception:  # noqa: BLE001 - la sortie ne doit jamais tuer la boucle
            output = ""
        if result.exception is not None and result.exit_code == 0:
            return 1, output + f"\n[runner] exception absorbee: {result.exception!r}"
        if result.exception is not None:
            output += f"\n[runner] exception absorbee: {result.exception!r}"
        return int(result.exit_code or 0), output

    def _default_popen(self, argv: list[str], stdout_file: Any) -> Any:
        return subprocess.Popen(  # noqa: S603 - argv construit localement, read-only
            argv, stdout=stdout_file, stderr=subprocess.STDOUT, cwd=str(self.config.root)
        )

    def log(self, message: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{stamp}] {message}"
        print(line, flush=True)
        try:
            with self.config.live_log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:  # noqa: BLE001 - un log qui echoue n'arrete pas le scan
            _noter_echec("hl_observer/runtime/persistent_poll_runner.py:207")

    def stop_requested(self) -> bool:
        try:
            return self.config.stop_file.exists()
        except Exception:  # noqa: BLE001
            return False

    # -------------------------------------------------------------- status/UI

    def write_engine_status(self, phase: str, message: str) -> None:
        """Même schéma que le .ps1 historique (l'UI et le watchdog externe le lisent)."""
        try:
            preserved_top: dict[str, Any] = {}
            try:
                existing = json.loads(
                    self.config.engine_status_path.read_text(encoding="utf-8-sig")
                )
                for key in _FUSION_PRESERVED_TOP_KEYS:
                    if existing.get(key) is not None:
                        preserved_top[key] = existing[key]
                old_metrics = existing.get("metrics") or {}
                for key in _FUSION_PRESERVED_METRICS:
                    if key in old_metrics:
                        self.metrics[key] = str(old_metrics[key])
            except Exception:  # noqa: BLE001 - best-effort, comme le .ps1
                _noter_echec("hl_observer/runtime/persistent_poll_runner.py:233")
            for metric_key, env_key in _BASE_ENV_METRICS.items():
                value = os.environ.get(env_key)
                if value:
                    self.metrics[metric_key] = value
            payload: dict[str, Any] = {
                "updated_at_ms": self._now_ms(),
                "session_id": self._session_id,
                "phase": phase,
                "message": message,
                "poll_index": self.current_poll,
                "max_runs": self.config.max_runs,
                "pool": self.config.max_leaders,
                "leaders_per_poll": self.config.leaders_per_poll,
                "read_only": True,
                "simulation_only": True,
                "external_action": False,
                "metrics": self.metrics,
            }
            payload.update(preserved_top)
            self.config.runtime_data_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.config.engine_status_path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.config.engine_status_path)
            if phase == "sleeping":
                # Historique d'equity persiste par le MOTEUR (survit a Chrome ferme).
                try:
                    from hl_observer.runtime.equity_history_store import append_equity_point
                    from hl_observer.simulation.accounting_truth import finite_number

                    _eq = finite_number(self.metrics.get("fusion_runtime_current_equity_usdt"))
                    _starting = finite_number(
                        self.metrics.get("fusion_runtime_starting_equity_usdt")
                    )
                    _pnl = (
                        _eq - _starting
                        if _eq is not None
                        and _starting is not None
                        and _eq > 0
                        and _starting > 0
                        else None
                    )
                    if _eq is not None and _eq > 0:
                        append_equity_point(
                            timestamp_ms=self._now_ms(),
                            equity_usdt=_eq,
                            pnl_usdc=_pnl,
                            starting_equity_usdt=_starting,
                            session_id=self._session_id,
                            accounting_status=(
                                "MEASURABLE"
                                if _pnl is not None
                                else "BASELINE_UNMEASURABLE"
                            ),
                            runtime_data_dir=self.config.runtime_data_dir,
                        )
                    # LOGS-MAX: une ligne SYSTEM par poll (equity/pnl/positions) pour tout revoir.
                    from hl_observer.runtime import detailed_logger as _dl
                    _dl.log("SYSTEM", f"poll {self.current_poll} done", sev="INFO",
                            poll_index=self.current_poll,
                            equity_usdt=(round(_eq, 4) if _eq is not None else None),
                            starting_equity_usdt=(
                                round(_starting, 4) if _starting is not None else None
                            ),
                            pnl_usdc=(round(_pnl, 4) if _pnl is not None else None),
                            pnl_accounting_status=(
                                "MEASURABLE"
                                if _pnl is not None
                                else "BASELINE_UNMEASURABLE"
                            ),
                            open_positions=self.metrics.get("fusion_runtime_open_positions"),
                            runtime_data_dir=str(self.config.runtime_data_dir))
                except Exception:
                    _noter_echec("hl_observer/runtime/persistent_poll_runner.py:274")
        except Exception as exc:  # noqa: BLE001
            self.log(f"engine status write failed: {exc}")

    def _record_output(self, label: str, output: str) -> None:
        suppressed = 0
        for raw_line in (output or "").splitlines():
            text = raw_line.rstrip()
            if '"logger": "httpx"' in text and "HTTP/1.1 200 OK" in text:
                suppressed += 1
                continue
            if not text.strip():
                continue
            match = _METRIC_LINE_RE.match(text)
            if match:
                self.metrics[match.group(1)] = match.group(2)
            safe_label = re.sub(r"[^A-Za-z0-9_]", "_", label).strip("_")
            for token in _METRIC_TOKEN_RE.finditer(text):
                if safe_label:
                    self.metrics[f"{safe_label}_{token.group(1)}"] = token.group(2)
            self.log(text)
        if suppressed:
            self.log(f"{label}: suppressed {suppressed} successful /info HTTP 200 log lines")

    def _add_step_duration(self, step: str, start_ms: int) -> None:
        elapsed = max(0, self._now_ms() - start_ms)
        key = re.sub(r"[^A-Za-z0-9_]", "_", step)
        self.step_durations[key] = elapsed
        self.metrics[f"step_ms_{key}"] = str(elapsed)

    # ------------------------------------------------------------------ steps

    def run_step(self, *, phase: str, message: str, label: str, argv: list[str]) -> StepResult:
        self.write_engine_status(phase, message)
        start = self._now_ms()
        try:
            exit_code, output = self._invoke(argv)
        except Exception as exc:  # noqa: BLE001 - ceinture: _invoke ne doit pas lever
            exit_code, output = 1, f"[runner] invoke crash absorbe: {exc!r}"
        duration = max(0, self._now_ms() - start)
        self._record_output(label, output)
        self._add_step_duration(label, start)
        failed = exit_code != 0
        if failed:
            self.log(f"step {label} exit_code={exit_code} (absorbe, la boucle continue)")
            self.metrics[f"step_failed_{re.sub(r'[^A-Za-z0-9_]', '_', label)}"] = str(exit_code)
        # LOGS-MAX: trace détaillée bornée de CHAQUE étape (erreur même minuscule visible).
        try:
            from hl_observer.runtime import detailed_logger as _dl
            _rt = str(self.config.runtime_data_dir)
            if failed:
                _tail = "\n".join(str(output or "").splitlines()[-6:])[-700:]
                _dl.log_error(f"step:{label}", f"exit_code={exit_code}", sev="WARN",
                              phase=phase, exit_code=exit_code, duration_ms=duration,
                              output_tail=_tail, poll_index=self.current_poll, runtime_data_dir=_rt)
            _dl.log("SCAN", f"{label} exit={exit_code} {duration}ms", sev="DEBUG",
                    label=label, phase=phase, exit_code=exit_code, duration_ms=duration,
                    poll_index=self.current_poll, runtime_data_dir=_rt)
        except Exception:
            _noter_echec("hl_observer/runtime/persistent_poll_runner.py:333")
        return StepResult(label=label, exit_code=exit_code, output=output, duration_ms=duration, failed=failed)

    def _spawn_ws_scan(self, label: str, argv: list[str]) -> dict[str, Any] | None:
        """Lance une écoute WS en sous-processus (parallèle au bloc local)."""
        try:
            tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115 - fermé au join
                mode="w+", encoding="utf-8", errors="replace",
                prefix=f"hs_{label}_", suffix=".out", delete=False,
                dir=str(self.config.runtime_data_dir),
            )
            proc = self._popen([sys.executable, "-u", "-m", "hl_observer", *argv], tmp)
            return {"label": label, "proc": proc, "file": tmp, "started_ms": self._now_ms()}
        except Exception as exc:  # noqa: BLE001
            self.log(f"spawn {label} failed (absorbe): {exc}")
            return None

    def _join_ws_scan(self, handle: dict[str, Any] | None, *, timeout_s: float) -> None:
        if not handle:
            return
        label = handle["label"]
        proc = handle["proc"]
        try:
            try:
                proc.wait(timeout=max(1.0, timeout_s))
            except Exception:  # noqa: BLE001 - timeout => on tue, pas de gel
                self.log(f"WATCHDOG: {label} depasse son budget -> kill (absorbe)")
                try:
                    proc.kill()
                    proc.wait(timeout=10)
                except Exception:  # noqa: BLE001
                    _noter_echec("hl_observer/runtime/persistent_poll_runner.py:364")
            output = ""
            try:
                handle["file"].flush()
                handle["file"].seek(0)
                output = handle["file"].read()
            finally:
                try:
                    handle["file"].close()
                    os.unlink(handle["file"].name)
                except Exception:  # noqa: BLE001
                    _noter_echec("hl_observer/runtime/persistent_poll_runner.py:375")
            self._record_output(label, output)
        finally:
            self._add_step_duration(label, handle["started_ms"])

    # ------------------------------------------------------------------- poll

    def run_poll(self, i: int) -> None:
        cfg = self.config
        self.current_poll = i
        safe_leaders = max(1, min(cfg.leaders_per_poll, min(cfg.max_leaders, 10)))
        leader_offset = ((i - 1) * safe_leaders) % max(1, cfg.max_leaders)
        self.log(f"poll {i}/{cfg.max_runs} starting offset={leader_offset} batch={safe_leaders} pool={cfg.max_leaders} (persistent)")
        self.write_engine_status("poll_start", f"Poll {i}/{cfg.max_runs}: offset={leader_offset} batch={safe_leaders} pool={cfg.max_leaders}.")
        poll_start = self._now_ms()

        # --- Écoutes WS en parallèle du bloc local (dépendances préservées: jointes avant copy-run)
        public_scan_due = i == 1 or (i % max(1, cfg.public_trade_scan_every_polls)) == 0
        public_handle = None
        fills_handle = None
        if cfg.overlap_ws_scans:
            if public_scan_due:
                public_handle = self._spawn_ws_scan("live-public-scan", [
                    "live-public-scan", "--network-read", "--store",
                    "--duration-seconds", str(cfg.public_trade_scan_seconds),
                    "--coins", cfg.public_trade_coins, "--max-coins", str(cfg.public_trade_max_coins),
                    "--max-wallets", str(cfg.public_trade_max_wallets),
                    "--promote-top", str(cfg.max_leaders), "--no-report",
                ])
            fills_handle = self._spawn_ws_scan("live-user-fills-scan", [
                "live-user-fills-scan", "--network-read", "--store", "--duration-seconds", "10",
                "--max-users", str(safe_leaders), "--leader-offset", str(leader_offset),
                "--max-live-fill-age-ms", str(cfg.user_fills_max_live_age_ms),
            ])

        # --- Plans (1 poll sur N, gap-recovery conservé)
        if i == 1 or (i % max(1, cfg.plans_every_polls)) == 0:
            t0 = self._now_ms()
            self.run_step(phase="throughput_plan", message="Verification des budgets de scan read-only.",
                          label="throughput-plan", argv=[
                              "throughput-plan", "--network-read", "--ws",
                              "--requested-wallets", str(cfg.max_leaders),
                              "--max-leaders-per-run", str(safe_leaders),
                              "--public-trade-wallets", str(cfg.public_trade_max_wallets)])
            self.run_step(phase="fresh_scan_plan", message="Planification de la rotation des wallets frais.",
                          label="fresh-scan-plan", argv=[
                              "fresh-scan-plan", "--network-read", "--requested-wallets", "50000",
                              "--cycle-seconds", str(cfg.interval_seconds),
                              "--leaders-per-stream", str(safe_leaders),
                              "--public-trade-wallets", str(cfg.public_trade_max_wallets)])
            self.run_step(phase="fresh_data_plan", message="Selection des coins et sources temps reel (gap-recovery inclus).",
                          label="fresh-data-plan", argv=[
                              "fresh-data-plan", "--network-read", "--requested-wallets", "50000",
                              "--coins", cfg.public_trade_coins, "--max-coins", str(cfg.public_trade_max_coins),
                              "--max-hot-wallets", str(safe_leaders), "--gap-recovery"])
            self._add_step_duration("plans", t0)
        else:
            self.log(f"Plans sautes ce poll (1 poll sur {max(1, cfg.plans_every_polls)}) pour la cadence.")

        # --- Marks + marchés (chemin PnL latent)
        self.run_step(phase="market_marks_refresh", message="Rafraichissement allMids Hyperliquid read-only pour le PnL latent paper.",
                      label="discover-markets", argv=["discover-markets", "--store", "--max-coins", str(cfg.public_trade_max_coins)])
        self.run_step(phase="market_scan", message="Scan marches read-only (l2book + candles).",
                      label="scan-markets", argv=["scan-markets", "--all", "--store", "--max-coins", str(cfg.public_trade_max_coins), "--l2book", "--candles"])

        # --- Refresh périodique lourd (1/20): collect-all + explorer, en sous-processus isolés
        if i == 1 or (i % 20) == 0:
            self.write_engine_status("periodic_collect_all", "Refresh collect-all borne: marches, wallets, shortlist, queue.")
            t0 = self._now_ms()
            try:
                proc = subprocess.run(  # noqa: S603
                    [sys.executable, "-u", "-m", "hl_observer.collection.run_collect_all",
                     "--max-coins", str(cfg.public_trade_max_coins),
                     "--target", str(max(500, cfg.max_leaders * 10))],
                    capture_output=True, text=True, cwd=str(cfg.root), timeout=600,
                )
                self._record_output("collect-all", (proc.stdout or "") + (proc.stderr or ""))
            except Exception as exc:  # noqa: BLE001
                self.log(f"collect-all failed (absorbe): {exc}")
            self._add_step_duration("collect_all", t0)
            self.run_step(phase="periodic_explorer_scrape", message="Lecture Explorer Hyperliquid read-only bornee.",
                          label="scrape-explorer", argv=["scrape-explorer", "--store", "--max-events", "250"])
            self.run_step(phase="explorer_candidates", message="Promotion des candidats Explorer.",
                          label="explorer-candidates", argv=["explorer-candidates", "--store"])

        # --- Mode séquentiel (fallback sans overlap) : écoutes WS in-process, ordre historique
        if not cfg.overlap_ws_scans:
            if public_scan_due:
                self.run_step(phase="live_public_scan", message="Lecture WebSocket publique Hyperliquid pour decouvrir des wallets.",
                              label="live-public-scan", argv=[
                                  "live-public-scan", "--network-read", "--store",
                                  "--duration-seconds", str(cfg.public_trade_scan_seconds),
                                  "--coins", cfg.public_trade_coins, "--max-coins", str(cfg.public_trade_max_coins),
                                  "--max-wallets", str(cfg.public_trade_max_wallets),
                                  "--promote-top", str(cfg.max_leaders), "--no-report"])
            self.run_step(phase="live_user_fills_scan", message="Lecture WebSocket userFills read-only sur shortlist bornee.",
                          label="live-user-fills-scan", argv=[
                              "live-user-fills-scan", "--network-read", "--store", "--duration-seconds", "10",
                              "--max-users", str(safe_leaders), "--leader-offset", str(leader_offset),
                              "--max-live-fill-age-ms", str(cfg.user_fills_max_live_age_ms)])
        else:
            # Joindre les écoutes AVANT copy-run (qui consomme leurs fills).
            self.write_engine_status("ws_scans_join", "Attente des ecoutes WebSocket paralleles (fills frais).")
            budget = cfg.public_trade_scan_seconds + 60
            self._join_ws_scan(public_handle, timeout_s=budget)
            self._join_ws_scan(fills_handle, timeout_s=10 + 60)

        # --- Décision copy paper (réconciliation réseau 1/20 comme l'historique)
        force_network = i == 1 or (i % 20) == 0
        copy_argv = ["copy-run", "--interval", str(cfg.interval_seconds), "--dry-run"]
        if force_network:
            copy_argv.append("--network-read")
        copy_argv += ["--copy-max-leaders", str(safe_leaders), "--leader-offset", str(leader_offset),
                      "--backfill-days", str(cfg.backfill_days),
                      "--fresh-window-minutes", str(cfg.fresh_window_minutes),
                      "--max-pages", str(cfg.max_pages), "--no-report"]
        self.run_step(
            phase="copy_run_network_read" if force_network else "copy_run_local",
            message="Reconciliation REST /info read-only et simulation paper locale." if force_network
            else "Decision paper depuis la base locale et les evenements WS recents.",
            label="copy-run", argv=copy_argv)

        # --- Analyse
        self.run_step(phase="opportunity_report", message="Analyse des opportunites et consensus recents.",
                      label="opportunity-report", argv=[
                          "opportunity-report", "--active-window-seconds", "120",
                          "--consensus-window-seconds", "4", "--min-wallets", "2",
                          "--max-deltas", "5000", "--max-opportunities", "10"])
        self.run_step(phase="fusion_runtime_input", message="Construction input fusion paper depuis deltas locaux et prix Hyperliquid locaux.",
                      label="fusion-heartbeat-input", argv=[
                          "fusion-heartbeat-input", "--fresh-window-seconds", "120",
                          "--max-votes", "24", "--write-engine-status", "--no-report"])

        # --- Carry HYPE paper (decision Flo 2026-07-14): journalise, gated, jamais bloquant
        try:
            from hl_observer.funding import carry_paper_runtime as _carry
            if _carry.enabled():
                _msg = ("Carry paper : decision + ETAPE 2 (ouverture/tenue de position paper, ledger)."
                        if _carry.etape2_active()
                        else "Evaluation carry HYPE paper (journalisee, sans position).")
                self.write_engine_status("carry_hype_paper", _msg)
                t0 = self._now_ms()
                ligne = _carry.evaluer_et_journaliser(cfg.root)
                d = ligne.get("decision") or {}
                self.metrics["carry_hype_viable"] = str(d.get("viable"))
                self.metrics["carry_hype_motif"] = str(d.get("motif") or "")
                e2 = ligne.get("etape2") or {}
                if isinstance(e2, dict) and "positions_ouvertes" in e2:
                    self.metrics["carry_positions_ouvertes"] = str(e2.get("positions_ouvertes"))
                    self.metrics["carry_coins_ouverts"] = ",".join(e2.get("coins_ouverts") or [])
                    self.metrics["carry_realise_total_usdt"] = str(e2.get("realise_total_usdt"))
                    _fermes = [x.get("ferme") for x in (e2.get("evts") or []) if x.get("ferme")]
                    if _fermes:
                        self.metrics["carry_derniere_sortie"] = str(_fermes[-1])
                self._add_step_duration("carry_hype_paper", t0)
        except Exception as exc:  # noqa: BLE001
            self.log(f"carry paper step failed (absorbe): {exc!r}")

        # --- Diagnostics (1 poll sur N)
        if i == 1 or (i % max(1, cfg.diagnostics_every_polls)) == 0:
            self.run_step(phase="simulation_readiness", message="Diagnostic de fraicheur et raisons de refus.",
                          label="simulation-readiness", argv=[
                              "simulation-readiness", "--from-logs", str(cfg.logs_to_send_dir),
                              "--fresh-window-seconds", "120"])
            self.run_step(phase="warehouse_report", message="Synthese warehouse local: wallets, deltas, decisions paper.",
                          label="warehouse-report", argv=["warehouse-report", "--fresh-window-seconds", "120"])
            try:
                # #286 LE LECTEUR: un identifiant sans verificateur serait la maladie du projet.
                from hl_observer.runtime.session_identity import verifier_coherence
                ok, motifs = verifier_coherence(cfg.root)
                self.metrics["session_check"] = "OK" if ok else "FAIL"
                if not ok:
                    self.log("SESSION_CHECK FAIL: " + " | ".join(motifs))
            except Exception:  # noqa: BLE001
                _noter_echec("hl_observer/runtime/persistent_poll_runner.py:549")
        else:
            self.log(f"Diagnostics sautes ce poll (1 poll sur {max(1, cfg.diagnostics_every_polls)}) pour la cadence.")

        # --- Bilan durees (mini-T43)
        total = max(0, self._now_ms() - poll_start)
        self.metrics["poll_total_ms"] = str(total)
        slowest = " ".join(
            f"{k}={v}ms" for k, v in sorted(self.step_durations.items(), key=lambda kv: kv[1], reverse=True)[:8]
        )
        self.log(f"poll {i} durations: total={total}ms {slowest}")
        self.step_durations = {}
        self.write_engine_status("sleeping", "Cycle termine, attente avant prochain scan.")

    # ------------------------------------------------------------ fills firehose

    def _spawn_fills_multiplex(self) -> Any | None:
        """Firehose userFills MULTIPLEXE always-on (V27) : plusieurs connexions WS
        persistantes (<=10 leaders chacune) pour couvrir N*10 leaders en sub-seconde
        -> un MAXIMUM de signaux frais, pas seulement le top-10. Sous-processus long,
        read-only. Tue par le shutdown large *hl_observer* du launcher + proprement ici.
        No-op si HYPERSMART_FILLS_MULTIPLEX n'est pas explicitement actif."""
        if not self.config.fills_multiplex:
            return None
        conns = max(1, int(self.config.fills_multiplex_connections))
        try:
            argv = [
                sys.executable, "-u", "-m", "hl_observer.wallets.user_fills_multiplex",
                "--network-read", "--max-connections", str(conns),
                "--max-live-fill-age-ms", str(self.config.user_fills_max_live_age_ms),
            ]
            proc = subprocess.Popen(  # noqa: S603 - argv local, read-only, jamais d'ordre
                argv, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, cwd=str(self.config.root)
            )
            self.log(f"fills-multiplex firehose demarre (always-on) connections={conns} pid={proc.pid} read_only=true")
            self.metrics["fills_multiplex_connections"] = str(conns)
            return proc
        except Exception as exc:  # noqa: BLE001 - un firehose qui ne demarre pas n'arrete pas la boucle
            self.log(f"fills-multiplex spawn failed (absorbe): {exc}")
            return None

    def _terminate_fills_multiplex(self, proc: Any | None) -> None:
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.kill()
        except Exception:  # noqa: BLE001
            _noter_echec("hl_observer/runtime/persistent_poll_runner.py:600")

    # -------------------------------------------------------------------- run

    def run(self) -> int:
        cfg = self.config
        try:
            cfg.logs_dir.mkdir(parents=True, exist_ok=True)
            cfg.runtime_data_dir.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            _noter_echec("hl_observer/runtime/persistent_poll_runner.py:610")
        try:
            # #286: LA session. Le lanceur la pose (env); le filet runner la cree sinon.
            from hl_observer.runtime.session_identity import demarrer_session, session_courante
            sid = session_courante(cfg.root)
            if not sid:
                sid = demarrer_session(cfg.root)
                self.log(f"session demarree (filet runner): {sid}")
            self._session_id = sid
            self.metrics["session_id"] = sid
        except Exception:  # noqa: BLE001
            self._session_id = ""
        self.log(
            f"Persistent poll runner started (T44). root={cfg.root} interval={cfg.interval_seconds} "
            f"pool={cfg.max_leaders} leadersPerPoll={cfg.leaders_per_poll} maxRuns={cfg.max_runs} "
            f"overlap={cfg.overlap_ws_scans} restartEvery={cfg.restart_every_polls} read_only=true execution=forbidden"
        )
        self.write_engine_status("starting", "Poller simulation Hyperliquid en demarrage (runner persistant T44).")
        fills_mux = self._spawn_fills_multiplex()
        for i in range(max(1, cfg.start_poll_index), cfg.max_runs + 1):
            if self.stop_requested():
                self.log("Stop demande (stop-file): arret propre du runner persistant.")
                self.write_engine_status("finished", "Poller simulation termine (stop demande).")
                self._terminate_fills_multiplex(fills_mux)
                return EXIT_STOP
            try:
                self.run_poll(i)
            except Exception as exc:  # noqa: BLE001 - un poll casse n'arrete pas la boucle
                self.log(f"poll failed: {exc!r}")
                self.write_engine_status("poll_failed", f"Erreur poller: {exc!r}")
            if cfg.restart_every_polls > 0 and i % cfg.restart_every_polls == 0 and i < cfg.max_runs:
                self.log(f"Self-restart apres {i} polls (garde-fou memoire du process chaud); le lanceur relance.")
                self.write_engine_status("self_restart", "Runner persistant: rotation planifiee du process.")
                self._terminate_fills_multiplex(fills_mux)
                return EXIT_SELF_RESTART
            if i < cfg.max_runs:
                cooldown = max(2, min(5, int(cfg.interval_seconds / 3)))
                self._sleep(cooldown)
        self.log("Persistent poll runner finished (max runs).")
        self.write_engine_status("finished", "Poller simulation termine.")
        self._terminate_fills_multiplex(fills_mux)
        return EXIT_STOP


def build_config(argv: list[str] | None = None) -> RunnerConfig:
    parser = argparse.ArgumentParser(description="HyperSmart T44 persistent poll runner (read-only, paper-only)")
    parser.add_argument("--root", default=".")
    parser.add_argument("--interval-seconds", type=int, default=15)
    parser.add_argument("--max-leaders", type=int, default=50)
    parser.add_argument("--leaders-per-poll", type=int, default=10)
    parser.add_argument("--backfill-days", type=int, default=1)
    parser.add_argument("--fresh-window-minutes", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--public-trade-coins", default="AUTO")
    parser.add_argument("--public-trade-max-coins", type=int, default=60)
    parser.add_argument("--public-trade-scan-seconds", type=int, default=8)
    parser.add_argument("--public-trade-max-wallets", type=int, default=10000)
    parser.add_argument("--public-trade-scan-every-polls", type=int, default=1)
    parser.add_argument("--user-fills-max-live-age-ms", type=int, default=20000)
    parser.add_argument("--max-runs", type=int, default=5760)
    parser.add_argument("--plans-every-polls", type=int, default=5)
    parser.add_argument("--diagnostics-every-polls", type=int, default=5)
    parser.add_argument("--restart-every-polls", type=int, default=400)
    parser.add_argument("--start-poll-index", type=int, default=1)
    parser.add_argument("--no-overlap-ws-scans", dest="overlap_ws_scans", action="store_false")
    args = parser.parse_args(argv)
    return RunnerConfig(
        root=Path(args.root).resolve(),
        interval_seconds=args.interval_seconds, max_leaders=args.max_leaders,
        leaders_per_poll=args.leaders_per_poll, backfill_days=args.backfill_days,
        fresh_window_minutes=args.fresh_window_minutes, max_pages=args.max_pages,
        public_trade_coins=args.public_trade_coins, public_trade_max_coins=args.public_trade_max_coins,
        public_trade_scan_seconds=args.public_trade_scan_seconds,
        public_trade_max_wallets=args.public_trade_max_wallets,
        public_trade_scan_every_polls=args.public_trade_scan_every_polls,
        user_fills_max_live_age_ms=args.user_fills_max_live_age_ms, max_runs=args.max_runs,
        plans_every_polls=args.plans_every_polls, diagnostics_every_polls=args.diagnostics_every_polls,
        restart_every_polls=args.restart_every_polls, overlap_ws_scans=args.overlap_ws_scans,
        start_poll_index=args.start_poll_index,
        fills_multiplex=str(os.environ.get("HYPERSMART_FILLS_MULTIPLEX", "")).strip().lower()
        in {"1", "true", "yes", "on"},
        fills_multiplex_connections=max(1, min(8, _env_int("HYPERSMART_FILLS_MULTIPLEX_CONNECTIONS", 4))),
    )


def main(argv: list[str] | None = None) -> int:
    config = build_config(argv)
    runner = PersistentPollRunner(config)
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
