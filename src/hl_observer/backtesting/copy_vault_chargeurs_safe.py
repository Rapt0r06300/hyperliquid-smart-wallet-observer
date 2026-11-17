"""Chargeurs SAFE du labo Copy-Vault : ce que le workspace matérialisé donne aux signaux.

POURQUOI CE MODULE EST À PART (17/11/2026). Ces deux chargeurs vivaient dans
``copy_vault_local_lab.py``, un fichier de plus de 5 000 lignes sous plafond historique.
L'invariant ``test_pas_de_nouveau_fichier_geant`` interdit de l'agrandir ; or les gardes ajoutées
au chargeur de fills (ligne SAFE, manifeste vérifié, heure de réception, source causale) l'avaient
fait dépasser. Plutôt que de relever le plafond, les deux chargeurs — autonomes, voisins, et de
même nature — sont extraits ici. Le labo les réimporte sous leurs noms d'origine.

Les deux sont « fail-soft » : un fichier absent ou illisible rend une liste vide, parce que
l'exploration doit tourner sans planter. Aucun des deux n'invente de valeur : une ligne incomplète
est écartée, jamais complétée.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.collection.forward_poll_fills import is_causal_live_source


def charger_asset_ctx_safe(workspace: Path) -> list[dict[str, Any]]:
    """Charge l'asset_ctx SAFE matérialisé et l'adapte en ``{coin, ts_ms, mark, oracle}``
    pour le signal overshoot. Robuste aux deux shapes (``context.markPx/oraclePx`` ou
    direct). Fail-soft : ``[]`` si absent/illisible (l'exploration tourne sans planter)."""
    chemin = workspace / "runtime" / "data" / "copy_vault_active_asset_ctx_tape.jsonl"
    if chemin.is_symlink() or not chemin.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        with chemin.open("r", encoding="utf-8") as fh:
            for ligne in fh:
                ligne = ligne.strip()
                if not ligne:
                    continue
                try:
                    row = json.loads(ligne)
                except (ValueError, TypeError):
                    continue
                if not isinstance(row, dict):
                    continue
                ctx = row.get("context") if isinstance(row.get("context"), Mapping) else row
                coin = row.get("coin") or ctx.get("coin")
                ts = row.get("ts_ms") or row.get("received_at_ms") or row.get("exchange_ts_ms")
                mark = ctx.get("markPx", ctx.get("mark", row.get("mark")))
                oracle = ctx.get("oraclePx", ctx.get("oracle", row.get("oracle")))
                if coin is None or ts is None or mark is None or oracle is None:
                    continue
                try:
                    out.append({
                        "coin": str(coin), "ts_ms": int(ts),
                        "mark": float(mark), "oracle": float(oracle),
                    })
                except (TypeError, ValueError):
                    continue
    except OSError:
        return []
    return out


def charger_leader_fills_safe(workspace: Path) -> list[dict[str, Any]]:
    """Charge les fills leaders SAFE matérialisés (``vault_fills.jsonl`` + live) réduits
    à ``{vault, ts_ms=heure de réception, closed_pnl}`` pour le signal de qualité leader (#10). Fail-soft :
    ignore les fichiers absents/illisibles et les lignes invalides (l'exploration tourne
    sans planter)."""
    out: list[dict[str, Any]] = []
    for nom in ("vault_fills.jsonl", "vault_fills_live.jsonl"):
        chemin = workspace / "runtime" / "data" / nom
        if chemin.is_symlink() or not chemin.is_file():
            continue
        try:
            with chemin.open("r", encoding="utf-8") as fh:
                for ligne in fh:
                    ligne = ligne.strip()
                    if not ligne:
                        continue
                    try:
                        row = json.loads(ligne)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(row, dict):
                        continue
                    if (row.get("source_quality_status") != "SAFE"
                            or row.get("source_manifest_verified") is not True
                            or row.get("provenance_tier") == "LOCAL"):
                        continue
                    vault = row.get("vault")
                    event_ts = row.get("ts_ms")
                    received = row.get("received_at_ms")
                    cp = row.get("closed_pnl")
                    if (vault is None or type(event_ts) is not int or type(received) is not int
                            or received < event_ts or row.get("isSnapshot") is not False
                            or not is_causal_live_source(row.get("source")) or cp is None):
                        continue
                    try:
                        out.append({
                            "vault": str(vault), "ts_ms": received, "closed_pnl": float(cp),
                        })
                    except (TypeError, ValueError):
                        continue
        except OSError:
            continue
    return out


__all__ = ["charger_asset_ctx_safe", "charger_leader_fills_safe"]
