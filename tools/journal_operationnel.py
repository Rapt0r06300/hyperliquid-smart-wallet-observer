"""OPERATIONAL REALITY JOURNAL (IDEA-10) — la réalité opérationnelle, journalisée puis REJOUÉE.

Un backtest qui ignore les déconnexions, les ticks périmés, les fills partiels et les rate limits ment par
omission. Ce journal enregistre chaque incident réellement rencontré, de façon append-only et bornée, puis
sait le RÉINJECTER dans les replays futurs (`scenarios_pour_replay`) pour que toute stratégie soit stressée
par ce qui s'est vraiment produit, et pas seulement par un monde parfait.

Types couverts (exactement ceux de l'idée) : WS_DISCONNECT, WS_GAP, STALE_TICK, OUTLIER, MISSING_BOOK,
NO_FILL, PARTIAL_FILL, DELAY_SPIKE, RATE_LIMIT, SNAPSHOT_CONFLICT, DUPLICATE, DATA_MISSING, RECONNECT,
LEDGER_MISMATCH, PNL_UNTRUSTED.

0 réseau, 0 ordre, paper-only.
"""
from __future__ import annotations

import json
import hashlib
import os
import time
import uuid
from pathlib import Path

TYPES = (
    "WS_DISCONNECT", "WS_GAP", "STALE_TICK", "OUTLIER", "MISSING_BOOK", "NO_FILL", "PARTIAL_FILL",
    "DELAY_SPIKE", "RATE_LIMIT", "SNAPSHOT_CONFLICT", "DUPLICATE", "DATA_MISSING", "RECONNECT",
    "LEDGER_MISMATCH", "PNL_UNTRUSTED",
)

#: incidents qui INTERDISENT toute promotion tant qu'ils ne sont pas expliqués (vérité du PnL).
BLOQUANTS = ("LEDGER_MISMATCH", "PNL_UNTRUSTED", "DATA_MISSING")

#: traduction incident -> stress rejouable (IDEA-10 « réinjecter ces erreurs dans les futurs replays »).
STRESS_REPLAY = {
    "WS_DISCONNECT": "coupure_flux", "RECONNECT": "coupure_flux", "WS_GAP": "trou_donnees",
    "DATA_MISSING": "trou_donnees", "STALE_TICK": "donnee_perimee", "DELAY_SPIKE": "latence_extreme",
    "RATE_LIMIT": "latence_extreme", "OUTLIER": "prix_aberrant", "MISSING_BOOK": "carnet_absent",
    "SNAPSHOT_CONFLICT": "carnet_absent", "NO_FILL": "non_execute", "PARTIAL_FILL": "execution_partielle",
    "DUPLICATE": "doublon", "LEDGER_MISMATCH": "incoherence_ledger", "PNL_UNTRUSTED": "pnl_non_fiable",
}

MAX_LIGNES_LUES = 20_000          # lecture TAIL bornée (fichier croissant, run 24/7)


class JournalOperationnel:
    """Journal append-only des incidents réels. Ne supprime jamais : rotation par archivage."""

    def __init__(self, dossier: Path, *, max_octets: int = 8_000_000):
        self.dir = Path(dossier)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.chemin = self.dir / "operational_reality.jsonl"
        self.archive = self.dir / "operational_archive"
        self.max_octets = int(max_octets)

    def _rotation_si_besoin(self):
        try:
            if self.chemin.exists() and self.chemin.stat().st_size > self.max_octets:
                self.archive.mkdir(parents=True, exist_ok=True)
                os.replace(
                    self.chemin,
                    self.archive / (
                        "operational_%d_%s.jsonl"
                        % (time.time_ns(), uuid.uuid4().hex[:12])
                    ),
                )
        except OSError:
            pass

    def enregistrer(self, type_: str, *, source=None, coin=None, detail=None, ts_ms=None, **extra) -> dict:
        """Journalise UN incident. Un type inconnu est refusé (on ne fabrique pas de taxonomie floue)."""
        t = str(type_).upper()
        if t not in TYPES:
            raise ValueError("type d'incident inconnu: %s" % type_)
        evt = {"event_id": uuid.uuid4().hex,
               "ts_ms": float(ts_ms if ts_ms is not None else time.time() * 1000.0), "type": t,
               "source": source, "coin": coin, "detail": (str(detail)[:300] if detail is not None else None),
               "bloquant": t in BLOQUANTS, "stress": STRESS_REPLAY.get(t), **extra}
        self._rotation_si_besoin()
        with self.chemin.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return evt

    def _lire(self, max_lignes: int = MAX_LIGNES_LUES) -> list:
        if not self.chemin.exists():
            return []
        out = []
        with self.chemin.open("r", encoding="utf-8", errors="ignore") as f:
            for ligne in f:                              # streaming (jamais tout le fichier en mémoire d'un coup)
                ligne = ligne.strip()
                if not ligne:
                    continue
                try:
                    out.append(json.loads(ligne))
                except ValueError:
                    continue
                if len(out) > max_lignes:
                    del out[0]
        return out

    def _lire_tous(self, max_lignes: int = MAX_LIGNES_LUES) -> list:
        """Read active and archived journals with stable deduplication."""
        chemins = []
        if self.archive.exists():
            chemins.extend(sorted(self.archive.glob("operational_*.jsonl")))
        if self.chemin.exists():
            chemins.append(self.chemin)
        out, seen = [], set()
        corruptions = 0
        for chemin in chemins:
            with chemin.open("r", encoding="utf-8", errors="strict") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        corruptions += 1
                        continue
                    event_id = str(
                        event.get("event_id")
                        or hashlib.sha256(raw_line.encode("utf-8")).hexdigest()
                    )
                    if event_id in seen:
                        continue
                    seen.add(event_id)
                    event["event_id"] = event_id
                    out.append(event)
        out.sort(
            key=lambda event: (
                float(event.get("ts_ms") or 0),
                str(event["event_id"]),
            )
        )
        if len(out) > max_lignes:
            out = out[-max_lignes:]
        if corruptions:
            out.append({
                "event_id": f"journal-corruption-{corruptions}",
                "ts_ms": time.time() * 1000.0,
                "type": "PNL_UNTRUSTED",
                "source": "operational_journal",
                "detail": f"{corruptions} corrupted JSONL line(s)",
                "bloquant": True,
                "stress": "pnl_non_fiable",
            })
        return out

    def resume(self, *, depuis_ms: float | None = None) -> dict:
        """Compte par type + drapeau bloquant. Sert au dashboard et au rapport final."""
        par_type, n_bloquants = {}, 0
        for e in self._lire_tous():
            if depuis_ms is not None and float(e.get("ts_ms") or 0) < float(depuis_ms):
                continue
            t = e.get("type", "?")
            par_type[t] = par_type.get(t, 0) + 1
            if e.get("bloquant"):
                n_bloquants += 1
        return {"n_incidents": sum(par_type.values()), "par_type": par_type,
                "n_bloquants": n_bloquants, "promotion_interdite": n_bloquants > 0}

    def scenarios_pour_replay(self, *, depuis_ms: float | None = None, max_scenarios: int = 50) -> list:
        """IDEA-10 — convertit les incidents RÉELS en scénarios de stress rejouables, avec leur fréquence
        observée. Une stratégie devra survivre à CE qui est déjà arrivé, pas à un monde idéal."""
        compte = {}
        total = 0
        for e in self._lire_tous():
            if depuis_ms is not None and float(e.get("ts_ms") or 0) < float(depuis_ms):
                continue
            s = e.get("stress") or STRESS_REPLAY.get(e.get("type", ""), None)
            if not s:
                continue
            compte[s] = compte.get(s, 0) + 1
            total += 1
        scenarios = [{"scenario": s, "occurrences": n,
                      "frequence": (round(n / total, 6) if total else None)}
                     for s, n in sorted(compte.items(), key=lambda kv: -kv[1])]
        return scenarios[:max_scenarios]


__all__ = ["JournalOperationnel", "TYPES", "BLOQUANTS", "STRESS_REPLAY"]
