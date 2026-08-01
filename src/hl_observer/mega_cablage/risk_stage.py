"""[CABLAGE étage E] RISK STAGE : dernier filtre AVANT le PaperEngine. Un candidat canonique ne devient un fill
que s'il passe les VRAIS garde-fous pretrade :
  - risk_gates.quote_quantity_pretrade : le VRAI notional (USD) ≤ plafond (jamais confondre base/quote) ;
  - risk_gates.account_equity_max_drawdown : compte HALTED si l'equity a chuté au-delà du seuil (cooldown) ;
  - risk_gates.low_profit_module_lock : coin/module en cooldown faible-profit → refusé.
Toute garde qui bloque → autorise=False + raison (aucun ordre). Fail-closed : gate optionnelle absente = ignorée,
mais présente et bloquante = refus. 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

from hl_observer.risk_gates.quote_quantity_pretrade import valider as valider_notional


def filtrer_risque(candidat: dict[str, Any] | None, *, notional_max: float, coin: Any, now_ms: Any,
                   drawdown_gate: Any = None, verrou: Any = None, equity: Any = None) -> dict[str, Any]:
    """candidat = sortie de creer_candidat. Ordre des gardes : candidat valide → drawdown → verrou module →
    plafond notional. Retourne {autorise, raison, notional?, detail?}."""
    if not candidat or not candidat.get("valide"):
        return {"autorise": False, "raison": "CANDIDAT_INVALIDE"}
    if drawdown_gate is not None and equity is not None:
        dd = drawdown_gate.evaluer(equity, now_ms=now_ms)
        if dd.get("etat") == "HALTED":
            return {"autorise": False, "raison": "MAX_DRAWDOWN_HALTED", "detail": dd}
    if verrou is not None:
        vv = verrou.est_verrouille(coin, now_ms)
        if vv.get("verrouille"):
            return {"autorise": False, "raison": "MODULE_VERROUILLE", "detail": vv}
    notional = candidat.get("notional")
    vn = valider_notional(notional, unite="QUOTE", notional_max=notional_max)
    if not vn.get("ok"):
        return {"autorise": False, "raison": vn.get("raison"), "notional": notional}
    return {"autorise": True, "raison": "OK", "notional": notional}


__all__ = ["filtrer_risque"]
