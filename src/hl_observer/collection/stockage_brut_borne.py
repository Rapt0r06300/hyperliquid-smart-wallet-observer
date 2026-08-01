"""[LANCEUR item 11] Stockage brut BORNÉ — remplace le stockage brut illimité (qui avait gonflé la DB à
29 Go) par un stockage durable et **borné sur disque**, sans jamais rien supprimer en silence.

Chemin : payload brut -> JSONL fsync + **shards gzip immuables** + manifeste + sha256 (TickDatasetWriter),
le tout **gardé par un quota** (GardeStockage) :
  - avant chaque écriture, si le quota SERAIT dépassé -> on ARCHIVE les shards les plus vieux (déplacement
    vers un dossier archive **frère**, jamais unlink silencieux) pour repasser sous la ligne basse ;
  - si même après rétention il n'y a pas de place -> l'écriture est ABANDONNÉE avec une raison LOGGÉE
    (jamais un drop muet) ;
  - alarme **avant** saturation (≥ 80 %).

Opt-in : `HYPERSMART_RAW_STORAGE_QUOTA_GO` (Go). Absent/0 => DÉSACTIVÉ (défaut sûr). Le SQL brut reste
coupé (`HYPERSMART_DISABLE_RAW_STORAGE=1`) — ce stockage-ci écrit des SHARDS FICHIERS, pas la DB.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

from hl_observer.collection.tick_dataset import TickDatasetWriter, TickEnvelope
from hl_observer.ops.quota_stockage import (
    GardeStockage,
    Shard,
    executer_retention,
    mesurer_usage,
    plan_retention,
)

ENV_QUOTA_GO = "HYPERSMART_RAW_STORAGE_QUOTA_GO"
ROTATE_DEFAUT = 32 * 1024 * 1024          # shards de 32 Mo -> rotation fréquente -> rétention possible


class EcrivainBrutBorne:
    """Sink brut durable et borné. `ecrire()` ne dépasse JAMAIS le quota (backpressure + rétention)."""

    def __init__(self, racine: str | Path, *, quota_octets: int, stream: str = "raw_events",
                 ligne_basse: float = 0.70, seuil_alerte: float = 0.80,
                 rotate_bytes: int = ROTATE_DEFAUT) -> None:
        base = Path(racine) / "runtime" / "data"
        self.dossier = base / "raw_bounded"                       # zone HOT mesurée par le quota
        self.archive = base / "raw_bounded_archive"               # zone COLD (frère, hors quota)
        self.writer = TickDatasetWriter(self.dossier, stream_name=stream, rotate_bytes=rotate_bytes)
        self.garde = GardeStockage(quota_octets, seuil_alerte=seuil_alerte)
        self.ligne_basse = ligne_basse
        self.abandons = 0
        self._maj_usage()

    def _maj_usage(self) -> int:
        octets = mesurer_usage([self.dossier]).octets
        self.garde.mettre_a_jour(octets)
        return octets

    def _shards(self) -> list[Shard]:
        out: list[Shard] = []
        for p in sorted(self.writer.shards_directory.glob("*.jsonl.gz")):
            try:
                st = p.stat()
                out.append(Shard(str(p), int(st.st_size), int(st.st_mtime * 1000)))
            except OSError:
                continue
        return out

    def ecrire(self, event: Mapping[str, Any], *, source_id: str = "raw", channel: str = "raw",
               instrument: str = "", exchange_ts_ms: int | None = None,
               now_ms: int | None = None) -> dict[str, Any]:
        maintenant = int(now_ms if now_ms is not None else time.time() * 1000)
        taille = len(json.dumps(event, ensure_ascii=False, default=str).encode("utf-8"))
        usage = self._maj_usage()
        ok, verdict = self.garde.autoriser_ecriture(taille)
        alarme = verdict.alerte_operateur()
        if not ok:
            # RÉTENTION EXPLICITE : archiver les shards les plus vieux (jamais de suppression muette).
            plan = plan_retention(self._shards(), quota_octets=self.garde.quota_octets,
                                  usage_octets=usage, ligne_basse=self.ligne_basse, motif="quota_raw")
            executer_retention(plan, dossier_archive=self.archive)
            usage = self._maj_usage()
            ok, verdict = self.garde.autoriser_ecriture(taille)
            if not ok:
                self.abandons += 1
                return {"ecrit": False, "raison": "QUOTA_PLEIN_APRES_RETENTION",
                        "usage": usage, "quota": self.garde.quota_octets, "alarme": alarme}
        env = TickEnvelope(source_id=source_id, channel=channel, instrument=instrument,
                           event_kind="raw", raw_payload=dict(event), received_ts_ms=maintenant,
                           exchange_ts_ms=exchange_ts_ms)
        self.writer.append(env)
        return {"ecrit": True, "etat": verdict.etat, "usage": self._maj_usage(), "alarme": alarme}

    def etat(self) -> dict[str, Any]:
        v = self.garde.verdict()
        return {"etat": v.etat, "usage": v.usage_octets, "quota": v.quota_octets,
                "pct": round(v.pct * 100.0, 1), "abandons": self.abandons, "alarme": v.alerte_operateur()}


def depuis_env(racine: str | Path, *, env: Mapping[str, str] | None = None) -> EcrivainBrutBorne | None:
    """Construit l'écrivain SI `HYPERSMART_RAW_STORAGE_QUOTA_GO` > 0, sinon None (désactivé — défaut sûr)."""
    e = env if env is not None else os.environ
    try:
        go = float(str(e.get(ENV_QUOTA_GO, "")).strip() or 0.0)
    except ValueError:
        go = 0.0
    if go <= 0:
        return None
    return EcrivainBrutBorne(racine, quota_octets=int(go * 1024**3))


# ── Hook global (utilisé par le sink SQL quand le brut SQL est coupé) ────────────────────────────────
_ECRIVAIN: EcrivainBrutBorne | None = None
_INITIALISE = False


def reinitialiser() -> None:
    global _ECRIVAIN, _INITIALISE
    _ECRIVAIN, _INITIALISE = None, False


def capturer_si_active(*, source: str, endpoint: str, request_type: str, request: Any, response: Any,
                       racine: str | Path | None = None) -> bool:
    """Capture un event brut vers le stockage BORNÉ si activé par l'ENV (sinon no-op). Ne lève jamais —
    la capture est best-effort et ne doit jamais casser la collecte."""
    global _ECRIVAIN, _INITIALISE
    try:
        if not _INITIALISE:
            _ECRIVAIN = depuis_env(racine or Path.cwd())
            _INITIALISE = True
        if _ECRIVAIN is None:
            return False
        _ECRIVAIN.ecrire({"source": source, "endpoint": endpoint, "request_type": request_type,
                          "request": request, "response": response},
                         source_id=str(source), channel=str(request_type), instrument=str(endpoint))
        return True
    except Exception:  # noqa: BLE001 — capture best-effort, jamais bloquante
        return False


__all__ = ["ENV_QUOTA_GO", "EcrivainBrutBorne", "depuis_env", "capturer_si_active", "reinitialiser"]
