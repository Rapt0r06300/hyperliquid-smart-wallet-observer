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
    """Apply every invariant with explicit missing-evidence semantics.

    An empty or incomplete state is never a vacuous success. Each advertised
    invariant must either receive its complete input tuple or emit
    MISSING_REQUIRED_EVIDENCE.
    """
    if not isinstance(etat, dict) or not etat:
        return {
            "ok": False,
            "violations": [{
                "invariant": "suite",
                "raison": "MISSING_REQUIRED_EVIDENCE",
            }],
            "n_violations": 1,
        }

    violations: list[dict[str, Any]] = []

    def require(name: str, fields: tuple[str, ...], fn):
        missing = [field for field in fields if field not in etat]
        if missing:
            violations.append({
                "invariant": name,
                "raison": "MISSING_REQUIRED_EVIDENCE",
                "missing_fields": missing,
            })
            return
        result = fn()
        if not result.get("ok", False):
            violations.append({
                "invariant": name,
                "raison": result.get("raison", "VIOLATION"),
            })

    require(
        "hedge_qty",
        ("hedge_qty", "actual_fill_qty"),
        lambda: inv_hedge_qty(etat["hedge_qty"], etat["actual_fill_qty"]),
    )
    require(
        "reduce_only",
        ("exposition_avant", "exposition_apres"),
        lambda: inv_reduce_only(etat["exposition_avant"], etat["exposition_apres"]),
    )
    require(
        "fill_unique",
        ("fill_ids",),
        lambda: inv_fill_unique(etat["fill_ids"]),
    )
    require(
        "position_fermee",
        ("position_disparue", "avait_fermeture"),
        lambda: inv_position_fermee(
            etat["position_disparue"], etat["avait_fermeture"]
        ),
    )
    require(
        "pnl_sans_fill",
        ("realized_pnl", "n_fills"),
        lambda: inv_pnl_sans_fill(etat["realized_pnl"], etat["n_fills"]),
    )
    require(
        "liquidite_unique",
        ("consommations",),
        lambda: inv_liquidite_unique(etat["consommations"]),
    )
    require(
        "completed_residu",
        ("statut", "residu"),
        lambda: inv_completed_sans_residu(etat["statut"], etat["residu"]),
    )
    return {
        "ok": not violations,
        "violations": violations,
        "n_violations": len(violations),
    }



__all__ = ["inv_hedge_qty", "inv_reduce_only", "inv_fill_unique", "inv_position_fermee", "inv_pnl_sans_fill",
           "inv_liquidite_unique", "inv_completed_sans_residu", "verifier_tous"]
