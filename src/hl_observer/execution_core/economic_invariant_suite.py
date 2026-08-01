"""[ALL #100] ECONOMIC INVARIANT SUITE : une batterie d'invariants économiques IMPOSSIBLES à contourner, vérifiables
sur n'importe quel état de simulation —
  1. hedge_qty ≤ actual_fill_qty          (on ne hedge jamais plus qu'on n'a rempli)
  2. reduceOnly n'augmente pas l'exposition
  3. un fill ne compte pas deux fois       (identités uniques)
  4. aucune position ne disparaît sans fermeture
  5. aucun PnL réalisé sans fill
  6. aucune liquidité consommée deux fois
  7. aucun arbitrage COMPLETED avec résidu non nul
Chaque invariant renvoie (ok, raison) ; `verifier_tous` agrège les violations. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_TOL = 1e-9


def inv_hedge_qty(hedge_qty: Any, actual_fill_qty: Any) -> dict[str, Any]:
    if not all(isinstance(x, (int, float)) for x in (hedge_qty, actual_fill_qty)):
        return {"ok": False, "raison": "DONNEE_MANQUANTE"}
    ok = abs(float(hedge_qty)) <= abs(float(actual_fill_qty)) + _TOL
    return {"ok": bool(ok), "raison": ("OK" if ok else "HEDGE_SUPERIEUR_AU_FILL")}


def inv_reduce_only(exposition_avant: Any, exposition_apres: Any) -> dict[str, Any]:
    if not all(isinstance(x, (int, float)) for x in (exposition_avant, exposition_apres)):
        return {"ok": False, "raison": "DONNEE_MANQUANTE"}
    ok = abs(float(exposition_apres)) <= abs(float(exposition_avant)) + _TOL
    return {"ok": bool(ok), "raison": ("OK" if ok else "REDUCE_ONLY_A_AUGMENTE_EXPO")}


def inv_fill_unique(fill_ids: Iterable[Any]) -> dict[str, Any]:
    ids = list(fill_ids)
    ok = len(ids) == len(set(ids))
    return {"ok": bool(ok), "raison": ("OK" if ok else "FILL_COMPTE_DEUX_FOIS")}


def inv_position_fermee(position_disparue: Any, avait_fermeture: Any) -> dict[str, Any]:
    """Une position qui disparaît doit avoir une fermeture associée."""
    disparue = bool(position_disparue)
    ok = (not disparue) or bool(avait_fermeture)
    return {"ok": bool(ok), "raison": ("OK" if ok else "POSITION_DISPARUE_SANS_FERMETURE")}


def inv_pnl_sans_fill(realized_pnl: Any, n_fills: Any) -> dict[str, Any]:
    if not isinstance(realized_pnl, (int, float)) or not isinstance(n_fills, (int, float)):
        return {"ok": False, "raison": "DONNEE_MANQUANTE"}
    ok = abs(float(realized_pnl)) <= _TOL or int(n_fills) > 0
    return {"ok": bool(ok), "raison": ("OK" if ok else "PNL_REALISE_SANS_FILL")}


def inv_liquidite_unique(consommations: Iterable[Any]) -> dict[str, Any]:
    """Aucune (venue, coin, niveau) consommée deux fois."""
    xs = list(consommations)
    ok = len(xs) == len(set(xs))
    return {"ok": bool(ok), "raison": ("OK" if ok else "LIQUIDITE_CONSOMMEE_DEUX_FOIS")}


def inv_completed_sans_residu(statut: Any, residu: Any) -> dict[str, Any]:
    if not isinstance(residu, (int, float)):
        return {"ok": False, "raison": "RESIDU_INCONNU"}
    if str(statut).upper() == "COMPLETED":
        ok = abs(float(residu)) <= _TOL
        return {"ok": bool(ok), "raison": ("OK" if ok else "COMPLETED_AVEC_RESIDU")}
    return {"ok": True, "raison": "NON_COMPLETED"}


def verifier_tous(etat: dict[str, Any]) -> dict[str, Any]:
    """Applique tous les invariants présents dans `etat` et agrège les violations. Un champ absent est ignoré
    (l'invariant n'est pas applicable), mais une valeur présente et fausse est TOUJOURS signalée."""
    violations = []
    checks = {
        "hedge_qty": lambda: inv_hedge_qty(etat.get("hedge_qty"), etat.get("actual_fill_qty"))
        if "hedge_qty" in etat else {"ok": True},
        "reduce_only": lambda: inv_reduce_only(etat.get("exposition_avant"), etat.get("exposition_apres"))
        if "exposition_apres" in etat else {"ok": True},
        "fill_unique": lambda: inv_fill_unique(etat.get("fill_ids", [])),
        "position_fermee": lambda: inv_position_fermee(etat.get("position_disparue"), etat.get("avait_fermeture"))
        if "position_disparue" in etat else {"ok": True},
        "pnl_sans_fill": lambda: inv_pnl_sans_fill(etat.get("realized_pnl"), etat.get("n_fills"))
        if "realized_pnl" in etat else {"ok": True},
        "liquidite_unique": lambda: inv_liquidite_unique(etat.get("consommations", [])),
        "completed_residu": lambda: inv_completed_sans_residu(etat.get("statut"), etat.get("residu"))
        if "statut" in etat else {"ok": True},
    }
    for nom, fn in checks.items():
        r = fn()
        if not r.get("ok", False):
            violations.append({"invariant": nom, "raison": r.get("raison", "VIOLATION")})
    return {"ok": (not violations), "violations": violations, "n_violations": len(violations)}


__all__ = ["inv_hedge_qty", "inv_reduce_only", "inv_fill_unique", "inv_position_fermee", "inv_pnl_sans_fill",
           "inv_liquidite_unique", "inv_completed_sans_residu", "verifier_tous"]
