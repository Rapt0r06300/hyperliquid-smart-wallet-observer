"""Isolation du laboratoire : chemins dédiés, identité (run_id/config_hash/heartbeat/PID), ledger
append-only, archiveur compressé. AUCUN chemin ne pointe vers runtime/data (main) : cloisonnement total.

Vérité des données : provenance + timestamps wall+monotonic sur chaque ligne ; rien n'est supprimé
(archives .gz immuables). 0 réseau ici (pur IO local, testable sans HL).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

#: RACINE ISOLÉE du labo — séparée de runtime/data (main). Rien du labo n'écrit ailleurs.
LAB_REL = Path("runtime") / "research_lab"
SOUS_DOSSIERS = ("data", "ledgers", "positions", "rapports", "logs", "archives")


def lab_root(root: Path) -> Path:
    return Path(root) / LAB_REL


def preparer(root: Path) -> Path:
    """Crée l'arborescence isolée du labo (idempotent). Rend la racine du labo."""
    base = lab_root(root)
    for d in SOUS_DOSSIERS:
        (base / d).mkdir(parents=True, exist_ok=True)
    return base


def config_hash(plugins, params: dict | None = None) -> str:
    """Empreinte STABLE du jeu de plugins + params : un changement de config se voit dans le hash."""
    payload = {"plugins": sorted(str(p) for p in plugins), "params": params or {}}
    brut = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(brut).hexdigest()[:16]


def nouvelle_identite(root: Path, plugins, params: dict | None = None) -> dict:
    """run_id + config_hash + pid, écrits dans le labo. CONTINUITÉ : si une identité existe déjà avec le
    MÊME config_hash (même jeu de plugins/params), on RÉUTILISE son run_id — les passes one-shot successives
    (relancées toutes les N s par boucle_collecteur) partagent donc un run_id stable. Un changement de config
    -> nouveau run_id (traçable). Le pid et l'heure de passe sont rafraîchis à chaque fois."""
    base = preparer(root)
    ch = config_hash(plugins, params)
    run_id = "lab-" + uuid.uuid4().hex[:12]
    try:
        prec = json.loads((base / "run_identity.json").read_text(encoding="utf-8"))
        if prec.get("config_hash") == ch and prec.get("run_id"):
            run_id = prec["run_id"]                      # continuité intra-session (même config)
    except (OSError, ValueError):
        import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
        _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
    ident = {"run_id": run_id, "config_hash": ch, "pid": os.getpid(),
             "demarre_wall_ms": int(time.time() * 1000), "demarre_mono_ns": time.monotonic_ns(),
             "plugins": sorted(str(p) for p in plugins)}
    (base / "run_identity.json").write_text(json.dumps(ident, ensure_ascii=False, indent=1), encoding="utf-8")
    return ident


def battre_coeur(root: Path, ident: dict, *, extra: dict | None = None) -> None:
    """Heartbeat propre du labo (diagnostic de vie, séparé du main)."""
    base = lab_root(root)
    base.mkdir(parents=True, exist_ok=True)
    hb = {"run_id": ident.get("run_id"), "config_hash": ident.get("config_hash"), "pid": os.getpid(),
          "ts_wall_ms": int(time.time() * 1000), "ts_mono_ns": time.monotonic_ns()}
    if extra:
        hb.update(extra)
    (base / "heartbeat.json").write_text(json.dumps(hb, ensure_ascii=False), encoding="utf-8")


def _provenance(ident: dict) -> dict:
    return {"run_id": ident.get("run_id"), "config_hash": ident.get("config_hash"),
            "recu_wall_ms": int(time.time() * 1000), "recu_mono_ns": time.monotonic_ns(),
            "read_only": True, "real_execution": False}


def ajouter_ledger(root: Path, plugin: str, lignes: list[dict], ident: dict) -> int:
    """Append-only dans ledgers/<plugin>.jsonl, chaque ligne tamponnée provenance + wall/mono + checksum.
    Rend le nb de lignes écrites. Best-effort (le labo ne casse jamais le main sur une écriture)."""
    if not lignes:
        return 0
    base = lab_root(root) / "ledgers"
    base.mkdir(parents=True, exist_ok=True)
    prov = _provenance(ident)
    p = base / ("%s.jsonl" % plugin)
    n = 0
    try:
        with p.open("a", encoding="utf-8") as f:
            for l in lignes:
                corps = {**l, **prov, "plugin": plugin}
                corps["checksum"] = hashlib.sha256(
                    json.dumps({k: corps[k] for k in sorted(corps) if k != "checksum"},
                               ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
                f.write(json.dumps(corps, ensure_ascii=False) + "\n")
                n += 1
    except OSError:
        return n
    return n


def archiver_si_gros(root: Path, nom: str, *, seuil_octets: int = 50 * 1024 * 1024,
                     max_travail: int = 40) -> str | None:
    """Scelle data/<nom>.jsonl en archive .gz IMMUABLE quand elle dépasse le seuil, borne le SET DE
    TRAVAIL, mais DÉPLACE les plus vieux vers archives/ (jamais supprimés). Rend le nom du shard ou None."""
    base = lab_root(root)
    src = base / "data" / ("%s.jsonl" % nom)
    if not src.exists() or src.stat().st_size < seuil_octets:
        return None
    dossier = base / "data"
    arch = base / "archives"
    arch.mkdir(parents=True, exist_ok=True)
    shard = "%s_%d.jsonl.gz" % (nom, time.time_ns())
    tmp = dossier / (shard + ".tmp")
    with src.open("rb") as fi, gzip.open(tmp, "wb") as fo:
        while True:
            buf = fi.read(1 << 20)
            if not buf:
                break
            fo.write(buf)
    os.replace(tmp, dossier / shard)
    src.write_text("", encoding="utf-8")
    shards = sorted(dossier.glob("%s_*.jsonl.gz" % nom))
    for vieux in shards[:-max_travail]:
        try:
            os.replace(vieux, arch / vieux.name)      # ARCHIVE (déplace), jamais supprime
        except OSError:
            import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
            _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
    return shard


__all__ = ["LAB_REL", "lab_root", "preparer", "config_hash", "nouvelle_identite", "battre_coeur",
           "ajouter_ledger", "archiver_si_gros"]
