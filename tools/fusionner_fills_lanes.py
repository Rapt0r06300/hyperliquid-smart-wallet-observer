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
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection.forward_poll_fills import (  # noqa: E402
    DEFAULT_MAX_OBSERVATION_LAG_MS,
    is_causal_live_source,
    merge_dedup_fills,
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


def fusionner(root: Path, artefacts: Path, max_lag_ms: int, *,
              cible_rel: Path = CIBLE, motif: str = "vault_fills_poll.jsonl") -> dict:
    """Fusionne les fills de lanes dans ``root/cible_rel`` (défaut : le tape poll).

    ``motif`` = nom des fichiers d'artefact à rassembler (poll : vault_fills_poll.jsonl ;
    WS : vault_fills_ws_lane.jsonl). La dédup/fraîcheur/écriture sont identiques.
    """
    cible = root / cible_rel
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
    if cible.exists():
        bak = cible.with_suffix(".jsonl.avant-fusion.bak")
        if bak.exists():
            bak.unlink()
        cible.rename(bak)
    tmp.rename(cible)

    return {
        "lanes_trouvees": [str(p) for p in lanes],
        "lus_par_fichier": lus_par_fichier,
        "rejets_qualite": rejets_qualite,
        "doublons_retires": doublons,
        "total_final": len(fusionnes),
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
    rapport = fusionner(Path(args.root), artefacts, max(0, int(args.max_lag_ms)))
    print("[fusion] lanes fusionnees :")
    for f, n in rapport["lus_par_fichier"].items():
        print(f"   {n:>8} fills frais  <- {f}")
    print(f"[fusion] doublons retires : {rapport['doublons_retires']}")
    print(f"[fusion] rejets qualite (non causal / trop vieux) : {rapport['rejets_qualite']}")
    print(f"[fusion] TOTAL final dans {CIBLE} : {rapport['total_final']} fills (backup .avant-fusion.bak)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
