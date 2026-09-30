"""CARRY CROSS-VENUE — paper (23/07, Flo : « gagner de l'argent avec le cross-venue », puis « go »).

MÉCANISME (le carry delta-neutre le plus connu des desks). Sur le MÊME coin, le funding diffère
entre venues. On se met :
  * SHORT le perp sur la venue qui PAIE le plus (HL) — on ENCAISSE son funding ;
  * LONG le perp sur la venue qui paie le moins (Binance) — on paie le sien.
Net encaissé par heure = `hl_bps_h − bin_bps_h` (la dispersion), **delta-neutre** (les deux jambes
sont le même actif : les mouvements de prix se compensent). C'est le carry que la recon du 23/07 a
trouvé le plus fort ET persistant sur les mid-caps (DASH/NEO/INJ/VIRTUAL : ~17-25 %/an mesuré).

POURQUOI C'EST LÉGITIME EN PAPER. `funding_cross_venue` dit, à raison, « on ne peut pas EXÉCUTER sur
Binance » : vrai pour du RÉEL. Ici tout est PAPER, sur DONNÉES RÉELLES (funding des deux venues via
`dispersion_venues.jsonl`, spreads réels des deux carnets via `carnet_venues.jsonl`). On SIMULE les
deux jambes ; aucun ordre, aucune clé, aucune monnaie. La jambe Binance reste conceptuelle → la
BASE (prix HL − prix Binance) porte un risque résiduel, NON caché : cf. §RISQUE.

PORTES PRÉ-DÉCLARÉES (les déplacer se voit dans un diff) :
  * COÛT RÉEL, PAS UN FORFAIT : `cout_ar = 2 × (demi_spread_HL + demi_spread_Binance)` lu au CARNET
    (aller ET retour, sur CHAQUE jambe). C'est la leçon du 21/07 (« un forfait de coût est une
    décision déguisée en constante ») appliquée dès le départ.
  * OUVERTURE seulement si le funding AMORTIT le coût avec marge : `premium × HOLD_MAX ≥ k × cout_ar`
    (k=1,5). Un premium qui ne rembourse pas la sortie AVANT la fin n'ouvre pas (leçon break-even).
  * ANTI-ARTEFACT : jambe Binance absente/figée (pas de carnet, ou `bin_bps_h` manquant) → REFUS
    (deny-by-default : on ne simule pas une jambe qu'on n'observe pas). Spread total > plafond →
    REFUS (illiquide = le spread mange le carry).
  * SORTIE : premium ≤ 0 (le funding ne paie plus → on ne tient pas un carry mort) OU âge ≥ HOLD_MAX
    OU donnée périmée (>15 min). Realized = funding ACCRU − cout_ar, jamais maquillé.
  * TAILLE : 50 $ fixe, MAX_POSITIONS plafonné (période d'essai). PAPER-only, read-only.

§RISQUE (assumé, pas caché) : la base HL↔Binance peut dériver ; sur le MÊME coin elle est de 2ᵈ
ordre mais réelle. Le realized ci-dessous NE la modélise pas encore (carnet trop épars pour une base
par tick) — il modélise les termes DOMINANTS (funding réel − spread réel). Un `basis_risque=True` est
écrit au ledger pour que l'audit le sache. La prochaine brique la price quand un flux prix dense
existera. On ne PROMET donc pas les 17-25 %/an : on les MESURE en paper, coûts réels déduits.

PnL réalisé écrit dans LE MÊME ledger que le carry/arb (kind=CLOSE, mode=LIVE, strategie=
'cross_venue_carry', session_id) → le PnL unifié du dashboard le somme sans une ligne de plus.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

NOTIONAL_USD = 50.0
MAX_POSITIONS = 4
HOLD_MAX_H = 168.0                 # 7 j : au-delà, on ne parie pas sur la persistance du premium
SEUIL_SORTIE_PREMIUM_BPS_H = 0.0   # premium ≤ 0 : le funding ne paie plus -> sortie
MARGE_BREAK_EVEN = 1.5             # le funding doit couvrir 1,5× le coût sur la vie de la position
SPREAD_TOTAL_MAX_BPS = 30.0        # demi_spread_HL + demi_spread_Binance : au-delà = illiquide, REFUS
FRAICHEUR_MAX_S = 900.0            # 15 min : au-delà, deny-by-default

STORE_RELPATH = Path("runtime") / "data" / "cross_venue_carry_positions.json"
LEDGER_RELPATH = Path("runtime") / "data" / "carry_paper_ledger.jsonl"
VENUES_RELPATH = Path("runtime") / "data" / "dispersion_venues.jsonl"
CARNET_RELPATH = Path("runtime") / "data" / "carnet_venues.jsonl"


def _charger_store(root: Path) -> dict:
    try:
        d = json.loads((root / STORE_RELPATH).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"ouvertes": {}}
    except (OSError, ValueError):
        return {"ouvertes": {}}


def _sauver_store(root: Path, store: dict) -> None:
    p = root / STORE_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    import os
    os.replace(tmp, p)


def _ledger(root: Path, row: dict) -> None:
    p = root / LEDGER_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def dernier_funding(root: Path, *, now: float | None = None) -> dict[str, dict]:
    """{coin: {hl_bps_h, bin_bps_h, premium, ts}} — dernière ligne venues FRAÎCHE par coin.
    `bin_bps_h` absent -> coin écarté (on ne simule pas une jambe Binance qu'on n'observe pas)."""
    t = now if now is not None else time.time()
    out: dict[str, dict] = {}
    p = root / VENUES_RELPATH
    if not p.exists():
        return out
    try:
        lignes = p.read_text(encoding="utf-8", errors="ignore").splitlines()[-1500:]
    except OSError:
        return {}
    for l in lignes:
        try:
            r = json.loads(l)
            hl = float(r["hl_bps_h"]); bn = float(r["bin_bps_h"]); ts = float(r["ts"])
        except (ValueError, KeyError, TypeError):
            continue
        if t - ts > FRAICHEUR_MAX_S:
            continue
        c = str(r.get("coin") or "").upper()
        if c:
            out[c] = {"hl_bps_h": hl, "bin_bps_h": bn, "premium": hl - bn, "ts": ts}
    return out


def couts_carnet(root: Path) -> dict[str, float]:
    """{coin: cout_aller_retour_bps} = 2 × (demi_spread_HL + demi_spread_Binance), lu au CARNET RÉEL.
    Coin sans carnet -> absent (donc REFUSÉ à l'ouverture : pas de coût observé = pas de simulation)."""
    out: dict[str, float] = {}
    p = root / CARNET_RELPATH
    if not p.exists():
        return out
    try:
        lignes = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return {}
    for l in lignes:                                   # dernière valeur par coin gagne (plus récente)
        try:
            r = json.loads(l)
            hl_s = float(r["hl_demi_spread_bps"]); bn_s = float(r["bin_demi_spread_bps"])
        except (ValueError, KeyError, TypeError):
            continue
        c = str(r.get("coin") or "").upper()
        if c and hl_s >= 0 and bn_s >= 0:
            out[c] = 2.0 * (hl_s + bn_s)               # aller-retour, deux jambes
    return out


def tick(root: str | Path = ".", *, now: float | None = None,
         session_id: str | None = None) -> list[dict[str, Any]]:
    """Une passe paper : accrue le funding des positions ouvertes, ferme selon les portes, ouvre
    les coins éligibles. Retourne les événements. 100 % simulation, aucun ordre réel."""
    racine = Path(root)
    t = now if now is not None else time.time()
    fund = dernier_funding(racine, now=t)
    couts = couts_carnet(racine)
    store = _charger_store(racine)
    ouvertes: dict[str, dict] = store.setdefault("ouvertes", {})
    evts: list[dict[str, Any]] = []

    # ── ACCRUE + SORTIES d'abord ──
    for coin in list(ouvertes):
        pos = ouvertes[coin]
        m = fund.get(coin)
        # accrue le funding réellement observé entre le dernier tick et maintenant (aucune
        # extrapolation : sans mesure fraîche, on n'accrue rien — on ne fabrique pas de funding).
        if m is not None:
            dt_h = max(0.0, (t - float(pos.get("last_ts") or t)) / 3600.0)
            pos["accrued_bps"] = float(pos.get("accrued_bps") or 0.0) + m["premium"] * dt_h
            pos["last_ts"] = t
            pos["premium_courant"] = m["premium"]
        age_h = (t - float(pos.get("entry_ts") or t)) / 3600.0
        premium_mort = m is not None and m["premium"] <= SEUIL_SORTIE_PREMIUM_BPS_H
        trop_vieux = age_h >= HOLD_MAX_H
        perime = m is None                             # donnée disparue -> deny-by-default : on ferme
        if not (premium_mort or trop_vieux or perime):
            continue
        accrue = float(pos.get("accrued_bps") or 0.0)
        cout_ar = float(pos.get("cout_ar_bps") or 0.0)
        realized = round((accrue - cout_ar) / 1e4 * NOTIONAL_USD, 6)
        _ledger(racine, {"kind": "CLOSE", "mode": "LIVE", "strategie": "cross_venue_carry",
                         "coin": coin, "ts_ms": int(t * 1000), "session_id": session_id,
                         "reason": ("CV_PREMIUM_MORT" if premium_mort else
                                    ("CV_HOLD_MAX_ATTEINT" if trop_vieux else "CV_DONNEE_PERIMEE")),
                         "funding_accru_bps": round(accrue, 4), "cout_ar_bps": round(cout_ar, 4),
                         "age_h": round(age_h, 2), "realized_net_pnl_usdc": realized,
                         "basis_risque": True, "real_execution": False, "not_an_order": True})
        evts.append({"type": "CLOSE", "coin": coin, "realized": realized,
                     "funding_accru_bps": round(accrue, 4)})
        del ouvertes[coin]

    # ── OUVERTURES (portes dures, deny-by-default) ──
    for coin, m in sorted(fund.items(), key=lambda kv: -kv[1]["premium"]):
        if coin in ouvertes or len(ouvertes) >= MAX_POSITIONS:
            continue
        premium = m["premium"]
        cout_ar = couts.get(coin)
        if cout_ar is None:                            # pas de carnet réel -> pas de coût -> REFUS
            continue
        if cout_ar / 2.0 > SPREAD_TOTAL_MAX_BPS:       # (cout_ar = 2×spread) -> spread total > plafond
            continue
        # BREAK-EVEN DÉRIVÉ : le funding doit couvrir k× le coût sur la vie MAX de la position.
        if premium <= 0.0 or premium * HOLD_MAX_H < MARGE_BREAK_EVEN * cout_ar:
            continue
        ouvertes[coin] = {"coin": coin, "entry_ts": t, "last_ts": t, "accrued_bps": 0.0,
                          "premium_entree": premium, "premium_courant": premium,
                          "cout_ar_bps": cout_ar, "notional_usd": NOTIONAL_USD,
                          "direction": "SHORT_HL_LONG_BIN", "real_execution": False}
        _ledger(racine, {"kind": "OPEN", "mode": "LIVE", "strategie": "cross_venue_carry",
                         "coin": coin, "ts_ms": int(t * 1000), "session_id": session_id,
                         "premium_bps_h": round(premium, 5), "cout_ar_bps": round(cout_ar, 4),
                         "notional_usd": NOTIONAL_USD, "basis_risque": True,
                         "real_execution": False, "not_an_order": True})
        evts.append({"type": "OPEN", "coin": coin, "premium_bps_h": round(premium, 5)})

    _sauver_store(racine, store)
    return evts


def _series_premium(root: Path) -> dict[str, list[tuple[float, float]]]:
    """{coin: [(ts, premium=hl_bps_h−bin_bps_h)]} chronologique, depuis TOUTE la dispersion.
    Jambe figée (bin à une seule valeur, ou hl mort à 0) EXCLUE : artefact, pas un signal."""
    from collections import defaultdict
    p = root / VENUES_RELPATH
    if not p.exists():
        return {}
    hl_par: dict[str, set] = defaultdict(set)
    par: dict[str, list[tuple[float, float]]] = defaultdict(list)
    bn_par: dict[str, set] = defaultdict(set)
    with p.open(encoding="utf-8", errors="ignore") as f:
        for l in f:
            try:
                r = json.loads(l)
                hl = float(r["hl_bps_h"]); bn = float(r["bin_bps_h"]); ts = float(r["ts"])
            except (ValueError, KeyError, TypeError):
                continue
            c = str(r.get("coin") or "").upper()
            if not c:
                continue
            par[c].append((ts, hl - bn)); hl_par[c].add(round(hl, 6)); bn_par[c].add(round(bn, 6))
    out = {}
    for c, serie in par.items():
        if len(bn_par[c]) <= 1 or max((abs(h) for h in hl_par[c]), default=0.0) < 1e-9:
            continue                                   # jambe Binance figée / HL mort -> artefact
        serie.sort()
        out[c] = serie
    return out


def backtest(root: str | Path = ".") -> dict[str, Any]:
    """MESURE (pas une promesse) le PnL paper du carry cross-venue sur l'historique OBSERVÉ, coûts
    RÉELS du carnet déduits. Positions NON chevauchantes par coin, funding intégré sur la fenêtre
    réelle (aucune extrapolation). Retour trié par net — le juge d'« est-ce que ça gagne ? »."""
    racine = Path(root)
    series = _series_premium(racine)
    couts = couts_carnet(racine)
    hold_ms_h = HOLD_MAX_H
    par_coin: list[dict] = []
    total = 0.0
    for coin, serie in series.items():
        cout = couts.get(coin)
        if cout is None or cout / 2.0 > SPREAD_TOTAL_MAX_BPS:
            continue                                   # pas de carnet réel, ou illiquide -> hors jeu
        nets: list[float] = []
        i = 0
        while i < len(serie):
            ts0, prem0 = serie[i]
            if prem0 <= 0.0 or prem0 * HOLD_MAX_H < MARGE_BREAK_EVEN * cout:
                i += 1
                continue                               # porte d'ouverture (break-even dérivé)
            accrue, j = 0.0, i
            t_fin = ts0 + hold_ms_h * 3600.0
            while j + 1 < len(serie) and serie[j + 1][0] <= t_fin and serie[j][1] > 0.0:
                accrue += serie[j][1] * (serie[j + 1][0] - serie[j][0]) / 3600.0   # ∫ premium dt
                j += 1
            nets.append(accrue - cout)                 # funding encaissé − coût aller-retour RÉEL
            i = j + 1 if j + 1 > i else i + 1          # non chevauchant
        if nets:
            net_usd = sum(n / 1e4 * NOTIONAL_USD for n in nets)
            total += net_usd
            heures = (serie[-1][0] - serie[0][0]) / 3600.0 or 1.0
            apr = (sum(nets) / len(nets)) / 1e4 * (8760.0 / min(HOLD_MAX_H, heures)) * 100.0
            par_coin.append({"coin": coin, "n_positions": len(nets),
                             "net_moyen_bps": round(sum(nets) / len(nets), 3),
                             "net_usd": round(net_usd, 4), "apr_pct_approx": round(apr, 1),
                             "cout_ar_bps": round(cout, 2)})
    par_coin.sort(key=lambda d: -d["net_usd"])
    positifs = [d for d in par_coin if d["net_usd"] > 0]
    return {"strategie": "cross_venue_carry", "total_net_usd": round(total, 4),
            "n_coins_joues": len(par_coin), "n_coins_positifs": len(positifs),
            "par_coin": par_coin,
            "avertissement": "MESURE paper sur données réelles, coûts carnet déduits ; base HL↔Binance "
                             "NON modélisée (risque résiduel) ; pas une promesse de PnL."}


__all__ = ["tick", "dernier_funding", "couts_carnet", "backtest", "NOTIONAL_USD", "MAX_POSITIONS",
           "HOLD_MAX_H", "SEUIL_SORTIE_PREMIUM_BPS_H", "MARGE_BREAK_EVEN", "SPREAD_TOTAL_MAX_BPS"]
