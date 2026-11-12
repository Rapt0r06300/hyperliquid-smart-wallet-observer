#!/usr/bin/env python3
"""Audit EXHAUSTIF des données collectées : chaque type est-il récolté, certifié, ET utilisé par le labo ?

« On collecte beaucoup de types de données, mais on ne les utilise pas tous. » Cet outil le vérifie,
type par type, sans en oublier un seul. Pour chaque famille de données il croise trois choses :

1. COLLECTÉ : le fichier brut de ``runtime/data`` ou ``runtime/history`` existe-t-il, avec des lignes,
   et a-t-il été écrit récemment (fraîcheur) ?
2. CERTIFIÉ : la famille est-elle présente au coffre (``runtime/coffre_certifie/LOCAL_INDEX.json``) ?
3. UTILISÉ PAR LE LABO : le pont LOCAL du labo (``copy_vault_tier_local``) la charge-t-il (fills,
   carnets, BBO, ou signaux de contexte) ?

Il signale les écarts : collecté mais pas certifié, certifié mais pas utilisé, jamais collecté. Et pour
chaque type il rappelle à quoi il sert (ou pourrait servir) au labo. Lecture seule ; aucun calcul réseau.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "src"))

#: Inventaire canonique : (famille, [fichiers sources], usage pour le labo). Les fichiers sont ceux
#: que les collecteurs écrivent (``coffre_certifie._FICHIERS_CONNUS``). L'ordre = par thème.
INVENTAIRE: list[tuple[str, list[str], str]] = [
    # ---- Exécution : ce qui rend un signal rejouable (référence/entrée/sortie) ----
    ("book_l2", ["copy_vault_l2_tape.jsonl", "copy_vault_l2_lane.jsonl"],
     "carnet L2 complet : EXÉCUTION (référence/entrée/sortie), profondeur, OFI, capacité"),
    ("bbo", ["copy_vault_bbo_tape.jsonl", "copy_vault_bbo_lane.jsonl", "bbo_tape.jsonl"],
     "top-of-book : repli d'exécution quand le L2 manque, lead-lag"),
    # ---- Fills des leaders : le signal de copie lui-même ----
    ("fills_forward", ["vault_fills_poll.jsonl", "vault_fills_live.jsonl", "copy_vault_twap_lane.jsonl"],
     "fills causaux en direct des leaders : le SIGNAL de copie (OPEN/ADD/REDUCE/CLOSE)"),
    ("fills_backfill", ["vault_fills.jsonl", "leader_fills_backfill.jsonl"],
     "historique des fills (TRAIN only) : profondeur de données des leaders"),
    ("snapshot", ["vault_snapshots.jsonl", "copy_vault_snapshots_lane.jsonl"],
     "snapshots clearinghouse : état de position, NAV, scoring des vaults"),
    # ---- Contexte de marché : où se cachent les avantages à chercher ----
    ("asset_ctx", ["asset_ctx_tape.jsonl"],
     "OI / funding / mark / oracle : filtre OVERSHOOT (fade de liquidation), régime"),
    ("overshoot", ["overshoots_liquidation.jsonl"], "débordement mark/oracle mesuré : fade de liquidation"),
    ("liquidation", ["liquidations_confirmees.jsonl"], "liquidations confirmées : fade, anti-signal (ne pas copier un liquidé)"),
    ("candle", ["candles_1h.jsonl", "candles_5m.jsonl", "copy_vault_candle_lane.jsonl"],
     "bougies : momentum, volatilité réalisée (sizing ciblé-vol), rétrospectif 208 j"),
    ("funding_history", ["funding_1h.jsonl"], "funding horaire : coût de PORTAGE sur toute position qui chevauche une frontière"),
    ("allmids", ["hl_allmids_tape.jsonl"], "prix de référence de tous les coins : edge forward de copie"),
    ("trades_marche", ["copy_vault_trades_lane.jsonl"], "trades publics : IMPACT de marché réel, intensité"),
    # ---- Cross-venue : dislocation réelle ----
    ("venue_book", ["carnet_venues.jsonl"], "carnet HL vs Binance : DISLOCATION, coût d'exécution cross-venue"),
    ("venue_dispersion", ["dispersion_venues.jsonl"], "dispersion des prix entre venues : signal de dislocation"),
    # ---- Intention & comptabilité des leaders ----
    ("leader_orders", ["copy_vault_orders_lane.jsonl"], "ordres EN ATTENTE : INTENTION, anticipation (ordre jumeau prudent)"),
    ("position", ["copy_vault_positions_lane.jsonl"], "positions complètes : réplication par position (pas par fill)"),
    ("vault_portfolio", ["vault_portfolio_history.jsonl"], "portefeuille complet (dex réunis) : réplication lente d'inventaire"),
    ("vault_ledger", ["vault_ledger.jsonl"], "dépôts/retraits : NAV as-of, détection de retrait (vs vente)"),
    # ---- Microstructure fine ----
    ("micro_l2", ["micro_l2book.jsonl"], "L2 microstructure : OFI fin (variations successives), horloges séparées"),
    ("micro_bbo", ["micro_bbo.jsonl"], "BBO microstructure : lead-lag fin, latence réelle"),
    ("micro_trades", ["micro_trades.jsonl"], "trades microstructure : flux signé, agressivité"),
    # ---- Découverte (métadonnée, pas un signal de marché) ----
    ("explorer_tx", ["explorer_tx_tape.jsonl"], "découverte de leaders actifs (métadonnée, pas un signal de marché)"),
]

#: Familles chargées par le pont LOCAL du labo (``copy_vault_tier_local``).
_FILLS = {"fills_forward", "fills_backfill", "snapshot"}
_BOOKS = {"book_l2", "bbo"}


def _charge_labo() -> set[str]:
    try:
        from hl_observer.backtesting import copy_vault_tier_local as T
        return _FILLS | _BOOKS | set(T._COFFRE_FAMILLES_SIGNAUX)
    except Exception:  # noqa: BLE001 - l'audit marche même si l'import échoue
        return _FILLS | _BOOKS


def _familles_au_coffre(root: Path) -> dict[str, int]:
    """{famille: nombre de shards} depuis l'index LOCAL du coffre."""
    index = root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    compte: dict[str, int] = {}
    for shard in data.get("shards", []) if isinstance(data, dict) else []:
        fam = str(shard.get("famille") or "")
        if fam:
            compte[fam] = compte.get(fam, 0) + 1
    return compte


def _collecte(root: Path, fichiers: list[str], *, maintenant: float) -> dict[str, Any]:
    """Pour une famille : total de lignes et fraîcheur (minutes depuis la dernière écriture)."""
    lignes = 0
    frais_min: float | None = None
    present = False
    for nom in fichiers:
        for base in (root / "runtime" / "data", root / "runtime" / "history",
                     root / "runtime" / "research_lab" / "data"):
            chemin = base / nom
            if not chemin.is_file():
                continue
            present = True
            try:
                with chemin.open("rb") as fh:
                    lignes += sum(1 for ligne in fh if ligne.strip())
                age = (maintenant - chemin.stat().st_mtime) / 60.0
                frais_min = age if frais_min is None else min(frais_min, age)
            except OSError:
                continue
    return {"present": present, "lignes": lignes, "fraicheur_min": frais_min}


def auditer(root: Path, *, maintenant: float | None = None, frais_seuil_min: float = 30.0) -> list[dict[str, Any]]:
    maintenant = time.time() if maintenant is None else float(maintenant)
    charge = _charge_labo()
    coffre = _familles_au_coffre(root)
    rapport: list[dict[str, Any]] = []
    for famille, fichiers, usage in INVENTAIRE:
        col = _collecte(root, fichiers, maintenant=maintenant)
        shards = coffre.get(famille, 0)
        utilise = famille in charge
        frais = col["fraicheur_min"]
        etat = (
            "JAMAIS COLLECTÉ" if not col["present"] or col["lignes"] == 0
            else "COLLECTÉ · NON CERTIFIÉ" if shards == 0
            else "CERTIFIÉ · NON UTILISÉ PAR LE LABO" if not utilise
            else "FRAIS · UTILISÉ" if (frais is not None and frais <= frais_seuil_min)
            else "UTILISÉ (données plus anciennes)"
        )
        rapport.append({
            "famille": famille, "etat": etat, "lignes_collectees": col["lignes"],
            "fraicheur_min": None if frais is None else round(frais, 1),
            "shards_coffre": shards, "charge_par_labo": utilise, "usage_labo": usage,
            "fichiers": fichiers,
        })
    return rapport


def rendre(rapport: list[dict[str, Any]]) -> list[str]:
    out = ["AUDIT DES DONNÉES COLLECTÉES  —  collecté → certifié → utilisé par le labo",
           "=" * 78]
    for r in rapport:
        frais = "—" if r["fraicheur_min"] is None else f"{r['fraicheur_min']:.0f} min"
        out.append(f"{r['famille']:16} [{r['etat']}]")
        out.append(f"   {int(r['lignes_collectees']):>10,} lignes · dernière écriture {frais} · {r['shards_coffre']} shard(s) au coffre".replace(",", " "))
        out.append(f"   usage labo : {r['usage_labo']}")
    # récapitulatif des écarts
    gaspilles = [r["famille"] for r in rapport if r["etat"].startswith("CERTIFIÉ · NON")]
    non_certifies = [r["famille"] for r in rapport if r["etat"].startswith("COLLECTÉ · NON")]
    manquants = [r["famille"] for r in rapport if r["etat"] == "JAMAIS COLLECTÉ"]
    out.append("")
    out.append("RÉCAPITULATIF DES ÉCARTS :")
    out.append(f"  · certifiés mais NON utilisés par le labo (gâchés) : {', '.join(gaspilles) or 'aucun ✅'}")
    out.append(f"  · collectés mais NON certifiés : {', '.join(non_certifies) or 'aucun ✅'}")
    out.append(f"  · jamais collectés sur cette session : {', '.join(manquants) or 'aucun ✅'}")
    return out


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    rapport = auditer(Path(args.root))
    if args.json:
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
    else:
        for ligne in rendre(rapport):
            print(ligne)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
