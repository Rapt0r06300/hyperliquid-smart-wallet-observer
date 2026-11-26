"""Fusionne les fills des lanes GitHub (artefacts poll-fills-shard-N) dans le
fichier local runtime/data/vault_fills_poll.jsonl.

Garanties QUALITÉ (identiques à la collecte, appliquées une 2e fois ici) :
- ne garde que des sources causales live (LIVE_WS / LIVE_POLL) ;
- ne garde que des fills FRAIS : retard d'observation (observed_at_ms - time)
  <= seuil (défaut 10 min), calculé sur les champs STOCKÉS (pas sur l'heure de
  fusion) -> aucun backlog/ancien ne se glisse ;
- déduplique par identité source-indépendante (vault,coin,time,tid/hash,oid,
  px,sz,side), en préférant la vue non-snapshot (causale) — exactement la même
  logique que le labo, donc zéro double.

Lecture seule / PAPER. Non destructif : sauvegarde .bak avant de réécrire.

Usage :
  python tools/fusionner_fills_lanes.py --artefacts <dossier_telechargements>
  # <dossier> = là où tu as extrait les artefacts GitHub (poll-fills-shard-*/).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection.forward_poll_fills import (  # noqa: E402
    DEFAULT_MAX_OBSERVATION_LAG_MS,
    is_causal_live_source,
    merge_dedup_fills,
)
from hl_observer.collection.collecte_fiable import ajouter_atomique  # noqa: E402
from hl_observer.collection.copy_vault_checkpoint_socle import (  # noqa: E402
    CheckpointSourceBusy,
    CHECKPOINT_SOURCE_RELPATH,
    FillSourceChanged,
    FillWriterBusy,
    copy_vault_checkpoint_source_lock,
    copy_vault_fill_writer_lock,
)

CIBLE = Path("runtime") / "data" / "vault_fills_poll.jsonl"


def _lire_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
    except OSError:
        return []
    return rows


def _frais_et_causal(row: dict, max_lag_ms: int) -> bool:
    """Garde un fill seulement s'il est d'une source causale ET observé à temps."""
    if not is_causal_live_source(row.get("source")):
        return False
    t = row.get("time")
    o = row.get("observed_at_ms")
    if not isinstance(t, int) or isinstance(t, bool) or t <= 0:
        return False
    if not isinstance(o, int) or isinstance(o, bool) or o <= 0:
        return False
    lag = o - t
    return 0 <= lag <= max_lag_ms


def _reserver_backup(cible: Path) -> Path:
    """Reserve an unused backup name without deleting an earlier recovery copy."""
    for index in range(1_000_000):
        candidate = (
            cible.with_suffix(".jsonl.avant-fusion.bak")
            if index == 0
            else cible.with_suffix(f".jsonl.avant-fusion-{index:04d}.bak")
        )
        try:
            descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue
        os.close(descriptor)
        return candidate
    raise FileExistsError(f"aucun nom de backup libre pour {cible}")


def _version_fichier(path: Path) -> tuple[int, int, int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return int(stat.st_dev), int(stat.st_ino), int(stat.st_size), int(stat.st_mtime_ns)


def fusionner(root: Path, artefacts: Path, max_lag_ms: int, *,
              cible_rel: Path = CIBLE, motif: str = "vault_fills_poll.jsonl") -> dict:
    """Fusionne les lanes; protège la source LIVE_WS du tailer forward-only."""
    cible = root / cible_rel
    checkpoint_source = root / CHECKPOINT_SOURCE_RELPATH
    if cible.resolve() == checkpoint_source.resolve():
        with copy_vault_checkpoint_source_lock(root, wait_s=0):
            return _ajouter_au_ruban_live(root, artefacts, max_lag_ms, cible_rel, motif)
    return _fusionner_sous_verrou(root, artefacts, max_lag_ms, cible_rel, motif)


def _identite_fill(row: dict) -> tuple:
    """Identite d'un fill, que la ligne soit au format du collecteur WS (``ts_ms``, ``received_at_ms``) ou des lanes
    (``time``, ``observed_at_ms``) : un meme trade d'un meme compte n'est ajoute qu'une fois."""
    compte = str(row.get("vault") or row.get("user") or "").lower()
    if row.get("tid") is not None:
        return (compte, row.get("coin"), "tid", row.get("tid"))
    instant = row.get("time") if row.get("time") is not None else row.get("ts_ms")
    return (compte, row.get("coin"), instant, row.get("hash"), row.get("oid"), row.get("px"), row.get("sz"),
            row.get("side") if row.get("side") is not None else row.get("signe"))


def _ajouter_au_ruban_live(
    root: Path, artefacts: Path, max_lag_ms: int, cible_rel: Path, motif: str
) -> dict:
    """26/11/2026 -- LE RUBAN LIVE N'EST PLUS REECRIT : on y AJOUTE les fills des lanes absents.

    Mesure : la fusion reecrivait ``vault_fills_live.jsonl`` en ne gardant que les lignes passant ``_frais_et_causal``,
    qui exige ``time`` et ``observed_at_ms`` -- le format des lanes. Le collecteur WS ecrit ``ts_ms`` et
    ``received_at_ms`` : TOUTES ses lignes etaient retirees a chaque AlinaSync (777 sur 777 le 26/11 a 04:11, dont 11
    pas encore scellees au coffre, retrouvees dans la copie ``.avant-fusion.bak``). Les lignes locales ne sont plus
    jamais retirees ni reecrites ; le filtre ne s'applique qu'aux lignes des lanes, comme avant.
    """
    cible = root / cible_rel
    locales_lignes = _lire_jsonl(cible) if cible.exists() else []
    connues = {_identite_fill(r) for r in locales_lignes}
    taille_initiale = cible.stat().st_size if cible.exists() else 0
    lanes = sorted(p for p in artefacts.rglob(motif) if p.resolve() != cible.resolve())
    par_source: list[list[dict]] = []
    rejets_qualite = 0
    lus_par_fichier: dict[str, int] = {}
    for src in lanes:
        brut = _lire_jsonl(src)
        gardes = [r for r in brut if _frais_et_causal(r, max_lag_ms)]
        rejets_qualite += len(brut) - len(gardes)
        lus_par_fichier[str(src)] = len(gardes)
        par_source.append(gardes)
    candidats = merge_dedup_fills(*par_source)
    candidats.sort(key=lambda r: (int(r.get("observed_at_ms") or 0), int(r.get("time") or 0)))
    with copy_vault_fill_writer_lock(root, wait_s=1.0):
        # ce que le collecteur a ecrit PENDANT la preparation compte aussi comme deja present
        if cible.exists() and cible.stat().st_size > taille_initiale:
            with cible.open("rb") as fh:
                fh.seek(taille_initiale)
                for brut in fh:
                    try:
                        obj = json.loads(brut)
                    except ValueError:
                        continue
                    if isinstance(obj, dict):
                        connues.add(_identite_fill(obj))
        nouvelles = [r for r in candidats if _identite_fill(r) not in connues]
        if nouvelles:
            ajouter_atomique(cible, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in nouvelles), fsync=True)
    total_entree = sum(len(s) for s in par_source)
    return {
        "mode": "AJOUT_SEUL",
        "lanes_trouvees": [str(p) for p in lanes],
        "lus_par_fichier": lus_par_fichier,
        "rejets_qualite": rejets_qualite,
        "locales": len(locales_lignes),
        "ajoutees": len(nouvelles),
        "doublons_retires": total_entree - len(nouvelles),
        "total_final": len(locales_lignes) + len(nouvelles),
        "backup_path": None,
    }


def _fusionner_sous_verrou(
    root: Path, artefacts: Path, max_lag_ms: int, cible_rel: Path, motif: str
) -> dict:
    """Corps commun de fusion; l'appelant protège la cible LIVE_WS si nécessaire."""
    cible = root / cible_rel
    version_initiale = _version_fichier(cible)
    # 1) Rassemble le fichier local + tous les <motif> des lanes.
    sources: list[Path] = []
    if cible.exists():
        sources.append(cible)
    lanes = sorted(
        p for p in artefacts.rglob(motif)
        if p.resolve() != cible.resolve()
    )
    sources.extend(lanes)

    par_source: list[list[dict]] = []
    rejets_qualite = 0
    lus_par_fichier: dict[str, int] = {}
    for src in sources:
        brut = _lire_jsonl(src)
        gardes = [r for r in brut if _frais_et_causal(r, max_lag_ms)]
        rejets_qualite += len(brut) - len(gardes)
        lus_par_fichier[str(src)] = len(gardes)
        par_source.append(gardes)

    # 2) Dédup par identité (préfère non-snapshot) via le helper prouvé du labo.
    fusionnes = merge_dedup_fills(*par_source)
    # Ordre déterministe : par instant d'observation puis heure de trade.
    fusionnes.sort(key=lambda r: (int(r.get("observed_at_ms") or 0), int(r.get("time") or 0)))

    total_entree = sum(len(s) for s in par_source)
    doublons = total_entree - len(fusionnes)

    # 3) Écriture atomique, backup non destructif.
    cible.parent.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_suffix(".jsonl.fusion.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in fusionnes:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    backup_path = None
    try:
        with copy_vault_fill_writer_lock(root, wait_s=1.0):
            if _version_fichier(cible) != version_initiale:
                raise FillSourceChanged(
                    f"{cible.name} a reçu une écriture pendant la préparation; fusion différée"
                )
            if cible.exists():
                backup_path = _reserver_backup(cible)
                try:
                    os.replace(cible, backup_path)
                except BaseException:
                    if backup_path.exists() and not cible.exists():
                        os.replace(backup_path, cible)
                    elif backup_path.exists() and backup_path.stat().st_size == 0:
                        backup_path.unlink(missing_ok=True)
                    raise
            try:
                os.replace(tmp, cible)
            except BaseException:
                if backup_path is not None and not cible.exists():
                    os.replace(backup_path, cible)
                raise
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    return {
        "lanes_trouvees": [str(p) for p in lanes],
        "lus_par_fichier": lus_par_fichier,
        "rejets_qualite": rejets_qualite,
        "doublons_retires": doublons,
        "total_final": len(fusionnes),
        "backup_path": str(backup_path) if backup_path is not None else None,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fusionne les fills des lanes GitHub (dédup + fraîcheur).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--artefacts", required=True,
                   help="dossier où les artefacts GitHub ont été extraits (poll-fills-shard-*/)")
    p.add_argument("--max-lag-ms", type=int, default=DEFAULT_MAX_OBSERVATION_LAG_MS,
                   help="retard d'observation max toléré (ms) — défaut 10 min")
    args = p.parse_args(argv)
    artefacts = Path(args.artefacts)
    if not artefacts.exists():
        print(f"[fusion] dossier introuvable : {artefacts}", flush=True)
        return 2
    try:
        rapport = fusionner(Path(args.root), artefacts, max(0, int(args.max_lag_ms)))
    except CheckpointSourceBusy:
        print("[fusion] differee : le checkpoint lit le ruban LIVE; aucun fichier remplace.", flush=True)
        return 0
    except (FillSourceChanged, FillWriterBusy):
        print("[fusion] differee : une ecriture collecte est survenue; aucun fill n'a ete ecrase.", flush=True)
        return 0
    print("[fusion] lanes fusionnees :")
    for f, n in rapport["lus_par_fichier"].items():
        print(f"   {n:>8} fills frais  <- {f}")
    print(f"[fusion] doublons retires : {rapport['doublons_retires']}")
    print(f"[fusion] rejets qualite (non causal / trop vieux) : {rapport['rejets_qualite']}")
    backup = rapport.get("backup_path") or "aucun (cible initialement absente)"
    print(f"[fusion] TOTAL final dans {CIBLE} : {rapport['total_final']} fills ; backup={backup}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
