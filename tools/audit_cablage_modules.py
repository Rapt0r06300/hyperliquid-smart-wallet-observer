"""S7 — AUDIT « CABLE vs ORPHELIN vs TESTE-SEULEMENT » de TOUS les modules src/hl_observer.

Pour chaque module on regarde QUI l'importe, en distinguant les PORTES DE PRODUCTION
(src/ hors self, tools/ lances par les .cmd, et les .py racine) des TESTS :
  * CABLE            : importe par >= 1 porte de production -> atteignable a l'execution.
  * TESTE_SEULEMENT  : importe UNIQUEMENT par des tests -> LA MALADIE (capacite testee, jamais
                       appelee en prod). Piege exact de delta_neutral_carry.
  * ORPHELIN         : importe par personne -> code mort, franc.
Borne HAUTE : "cable" par import != forcement appele sur le chemin de decision, mais deja bien
plus que rien. 100% lecture, aucun ordre. La verite complete tourne sous Windows
(TEST-AUDIT-complet.cmd) : le sandbox n'a ni reseau ni UTF-8 fiable.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "hl_observer"
TESTS = ROOT / "tests"
TOOLS = ROOT / "tools"

NEUFS = {"funding_persistence", "funding_zscore", "base_convergence", "spot_yield", "carry_rotation",
    "carry_position_lifecycle", "carry_positions_store", "carry_paper_runtime",
    "post_liquidation_direction", "leader_markout", "wallet_consensus", "maker_rebate_decision",
    "execution_passive_agressive", "kelly_sizing", "budget_turnover", "promotion_gate",
    "session_conditioning", "tick_quality_guard", "structural_wallet_filter", "survival_gate",
    "residual_alpha", "microstructure_signals", "cross_sectional_momentum", "funding_reversal",
    "vol_regime_signal", "feature_store", "feature_normalize", "feature_multitimeframe", "feature_drift",
    "linear_baseline", "ridge_regression", "probability_calibration", "model_refit", "maker_taker",
    "anti_gaming", "freshness_cut", "portfolio_risk_limits", "carry_risk_gates", "safety_gates_mm",
    "perf_metrics", "allocator", "monte_carlo", "pnl_attribution", "strategy_monitoring",
    "clock_integrity", "universe_guard", "orthogonalize", "crowding", "drawdown_scaling", "margin_reserve"}


def _lire(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def classer() -> dict:
    modules = [p for p in SRC.rglob("*.py") if "__pycache__" not in str(p) and p.name != "__init__.py"]
    prod = {p: _lire(p) for p in SRC.rglob("*.py") if "__pycache__" not in str(p)}
    prod.update({p: _lire(p) for p in TOOLS.rglob("*.py") if "__pycache__" not in str(p)})
    prod.update({p: _lire(p) for p in ROOT.glob("*.py")})
    test_blob = "\n".join(_lire(t) for t in TESTS.rglob("test_*.py"))

    cat: dict[str, list[str]] = {"CABLE": [], "TESTE_SEULEMENT": [], "ORPHELIN": []}
    detail: dict[str, str] = {}
    for m in modules:
        dotted = ".".join(m.relative_to(ROOT / "src").with_suffix("").parts)
        en_prod = any(dotted in txt for p, txt in prod.items() if p != m)
        en_test = dotted in test_blob
        nom = str(m.relative_to(SRC))
        k = "CABLE" if en_prod else ("TESTE_SEULEMENT" if en_test else "ORPHELIN")
        cat[k].append(nom)
        detail[nom] = k
    return {"cat": cat, "detail": detail, "total": len(modules)}


def main() -> int:
    r = classer()
    cat, tot = r["cat"], r["total"]
    print("=== AUDIT CABLAGE (%d modules ; portes = src+tools+racine) ===" % tot)
    for k in ("CABLE", "TESTE_SEULEMENT", "ORPHELIN"):
        print("  %-16s %4d  (%4.1f%%)" % (k, len(cat[k]), 100.0 * len(cat[k]) / tot))
    sn = {k: sorted(nom for nom in lst if Path(nom).stem in NEUFS) for k, lst in cat.items()}
    print("\n  --- Modules NEUFS de la session (%d) ---" % sum(len(v) for v in sn.values()))
    for k in ("CABLE", "TESTE_SEULEMENT", "ORPHELIN"):
        print("  %-16s %4d" % (k, len(sn[k])))
    print("\n  NEUFS encore TESTE_SEULEMENT (backlog de cablage) :")
    for nom in sn["TESTE_SEULEMENT"]:
        print("    -", nom)
    print("\n  NEUFS deja CABLES :")
    for nom in sn["CABLE"]:
        print("    -", nom)
    (ROOT / "tools" / "audit_cablage_manifest.json").write_text(
        json.dumps({"total": tot, "compte": {k: len(v) for k, v in cat.items()},
                    "neufs": {k: sn[k] for k in sn}}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
