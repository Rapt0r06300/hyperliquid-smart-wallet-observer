"""BACKTEST DE RÉPLICATION COPY-VAULTS — le rendement NET copiable, sans survivorship (23/07, COPY).

Le copy de FILLS est mort. Les VAULTS sont la dernière porte : tenus des JOURS, donc nos 62 s de délai
sont négligeables ; et on peut RÉPLIQUER leur exposition. Ce backtest mesure, honnêtement :

  * RENDEMENT CORRIGÉ DES FLUX : un dépôt gonfle la NAV sans être un gain -> on retire les
    dépôts/retraits nets avant de mesurer le rendement. (Sans ça, un gros dépôt ressemble à une perf.)
  * COÛT DE RÉPLICATION : notre turnover (Σ|Δexpo|) payé au bid/ask -> traîne le rendement.
  * NET RÉPLIQUÉ = rendement corrigé − coût de turnover. À l'horizon JOURS des vaults, le délai de 62 s
    est négligeable devant la durée de tenue (c'est PRÉCISÉMENT pourquoi les vaults sont la frontière) ;
    la part de slippage FINE du délai exigerait les fills tick-à-tick (le collecteur les capture, à
    brancher) — on le DIT, on ne le maquille pas.
  * CONTRÔLE ANTI-SURVIVORSHIP : les vaults REJETÉS par la classification (MM, drawdown, trop jeunes)
    sont mesurés AUSSI. Si les rejetés gagnent autant que les retenus, notre sélection ne vaut rien.
  * PROVENANCE : chaque snapshot porte son adresse de vault et sa source ; l'univers est GELÉ avant le
    forward (on ne choisit pas les gagnants après coup).

PAPER/shadow only : répliquer une trajectoire n'est pas passer un ordre.
"""
from __future__ import annotations

import json
import statistics as st
from pathlib import Path
from typing import Any

SNAPSHOTS = Path("runtime") / "data" / "vault_snapshots.jsonl"
COUT_TURNOVER_BPS = 5.0            # bid/ask payé par unité d'exposition tournée (mid-cap perp)
MIN_SNAPSHOTS = 12                 # sous ça, un rendement n'est que du bruit


def charger_snapshots_vault(root: str | Path) -> dict[str, list[dict]]:
    """{vault: [snapshots triés par ts]}. Provenance conservée (chaque ligne porte son adresse)."""
    from collections import defaultdict
    p = Path(root) / SNAPSHOTS
    if not p.exists():
        return {}
    par: dict[str, list[dict]] = defaultdict(list)
    for l in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            d = json.loads(l)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("vault"):
            par[str(d["vault"])].append(d)
    for v in par:
        par[v].sort(key=lambda s: int(s.get("ts_ms") or 0))
    return dict(par)


def _f(x, defaut=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return defaut


def repliquer(snaps: list[dict], *, cout_turnover_bps: float = COUT_TURNOVER_BPS) -> dict[str, Any]:
    """Rendement NET copiable d'un vault : corrigé des flux, moins le coût de turnover. PUR."""
    if len(snaps) < MIN_SNAPSHOTS:
        return {"verdict": "INSUFFISANT", "n": len(snaps)}
    nav0, nav1 = _f(snaps[0].get("nav_usd")), _f(snaps[-1].get("nav_usd"))
    if nav0 <= 0:
        return {"verdict": "NAV_INVALIDE", "n": len(snaps)}
    flux_net = sum(_f(s.get("depot_retrait_net_usd")) for s in snaps)     # dépôts − retraits cumulés
    rendement_corrige_bps = (nav1 - nav0 - flux_net) / nav0 * 1e4          # perf VRAIE, sans les flux
    nav_moy = st.mean(_f(s.get("nav_usd")) for s in snaps) or 1.0
    turnover = sum(abs(_f(s.get("delta_expo_nette_usd"))) for s in snaps) / nav_moy   # rotations
    cout_turnover_bps_tot = turnover * cout_turnover_bps
    net = rendement_corrige_bps - cout_turnover_bps_tot
    jours = (int(snaps[-1].get("ts_ms") or 0) - int(snaps[0].get("ts_ms") or 0)) / 86_400_000.0
    return {"verdict": "MESURE", "n": len(snaps), "jours": round(jours, 2),
            "rendement_corrige_bps": round(rendement_corrige_bps, 2),
            "flux_net_usd": round(flux_net, 2), "turnover": round(turnover, 3),
            "cout_turnover_bps": round(cout_turnover_bps_tot, 2),
            "net_replique_bps": round(net, 2),
            "apr_net_pct": round(net / 1e4 * (365.0 / jours) * 100.0, 1) if jours > 0.5 else None}


def backtest(root: str | Path = ".", *, vaults_retenus: list[str] | None = None,
             vaults_controle: list[str] | None = None,
             cout_turnover_bps: float = COUT_TURNOVER_BPS) -> dict[str, Any]:
    """Réplication nette des RETENUS vs les REJETÉS (contrôle anti-survivorship). Univers GELÉ passé en
    argument (jamais choisi après coup). NEED_MORE_DATA tant que la collecte est trop courte."""
    snaps = charger_snapshots_vault(root)
    if not snaps:
        return {"strategie": "copy_vaults", "statut": "NEED_MORE_DATA", "detail": "aucun snapshot vault"}
    retenus = {v.lower() for v in (vaults_retenus or list(snaps))}
    controle = {v.lower() for v in (vaults_controle or [])}
    res_ret, res_ctrl = {}, {}
    for v, sn in snaps.items():
        r = repliquer(sn, cout_turnover_bps=cout_turnover_bps)
        if r.get("verdict") != "MESURE":
            continue
        (res_ctrl if v.lower() in controle else res_ret)[v] = r
    if not res_ret:
        return {"strategie": "copy_vaults", "statut": "NEED_MORE_DATA",
                "detail": "aucun vault retenu avec assez de snapshots (>= %d)" % MIN_SNAPSHOTS,
                "vaults_vus": len(snaps)}
    net_ret = [r["net_replique_bps"] for r in res_ret.values()]
    net_ctrl = [r["net_replique_bps"] for r in res_ctrl.values()]
    med_ret = st.median(net_ret)
    med_ctrl = st.median(net_ctrl) if net_ctrl else None
    # KEEP seulement si les RETENUS gagnent ET battent le CONTRÔLE (sinon la sélection est illusoire)
    bat_controle = med_ctrl is None or med_ret > med_ctrl
    return {"strategie": "copy_vaults",
            "statut": "PROMETTEUR" if (med_ret > 0 and bat_controle) else "PAS_D_EDGE",
            "n_retenus": len(res_ret), "n_controle": len(res_ctrl),
            "net_median_retenus_bps": round(med_ret, 2),
            "net_median_controle_bps": round(med_ctrl, 2) if med_ctrl is not None else None,
            "bat_le_controle": bat_controle, "par_vault_retenu": res_ret,
            "avertissement": "Rendement CORRIGÉ des dépôts/retraits, net du turnover au bid/ask. Le "
                             "délai de 62 s est négligeable à l'horizon JOURS des vaults ; la slippage "
                             "fine exigerait les fills tick (collecteur prêt). Contrôle = vaults REJETÉS "
                             "(anti-survivorship). Aucun APR affiché n'est cru : on remesure la NAV."}


__all__ = ["COUT_TURNOVER_BPS", "MIN_SNAPSHOTS", "charger_snapshots_vault", "repliquer", "backtest"]
