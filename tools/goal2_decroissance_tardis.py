r"""H20 — décroissance de l'avantage des fills de nos leaders, mesurée sur le carnet TARDIS (source indépendante).

Pré-enregistrée au journal (GOAL2_CHASSE_ALPHA.md). Le mid vient des instantanés de carnet Tardis (horloge de la
bourse) ; les fills viennent du cache de recherche (exploration). Markouts avant/après le fill, prix obtenu par le
leader, et copie à t + 120 s sortie 1 h plus tard au coût de 12 bps. Bootstrap par blocs (jour, leader).
LECTURE SEULE, PAPER. Une ligne au registre chaîné.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import goal2_commun as G

TARDIS = G.RACINE / "runtime" / "history" / "tardis" / "incremental_book_L2"
JOURS = ("2026-05-01", "2026-06-01", "2026-07-01", "2026-08-01")
COINS = ("BTC", "ETH", "HYPE")
HORIZONS_S = (-300, -60, -10, 10, 60, 120, 300, 900, 3600)
LATENCE_S, TENUE_S, COUT_BPS = 120, 3600, 12.0


def mids(chemin: Path) -> tuple[np.ndarray, np.ndarray]:
    """(t_ms, mid) : un point par instantané (lignes de même horodatage de bourse), lu en flux."""
    t_out, m_out = [], []
    courant, bid, ask = None, -np.inf, np.inf

    def vider() -> None:
        if courant is not None and np.isfinite(bid) and np.isfinite(ask) and ask > bid > 0:
            t_out.append(courant // 1000)
            m_out.append((bid + ask) / 2.0)

    with gzip.open(chemin, "rt", encoding="utf-8", newline="") as f:
        lecteur = csv.reader(f)
        e = next(lecteur)
        i_ts, i_side, i_px, i_amt = e.index("timestamp"), e.index("side"), e.index("price"), e.index("amount")
        for ligne in lecteur:
            ts = int(ligne[i_ts])
            if ts != courant:
                vider()
                courant, bid, ask = ts, -np.inf, np.inf
            if float(ligne[i_amt]) <= 0:
                continue
            px = float(ligne[i_px])
            if ligne[i_side] == "bid":
                bid = max(bid, px)
            else:
                ask = min(ask, px)
        vider()
    return np.asarray(t_out, dtype=np.int64), np.asarray(m_out, dtype=float)


def mid_a(t: np.ndarray, m: np.ndarray, instants: np.ndarray, *, tolerance_ms: int = 5_000) -> np.ndarray:
    """Dernier mid connu à chaque instant (as-of), NaN s'il est plus vieux que `tolerance_ms` (trou de capture)."""
    k = np.searchsorted(t, instants, side="right") - 1
    ok = (k >= 0) & (instants - t[np.clip(k, 0, len(t) - 1)] <= tolerance_ms)
    return np.where(ok, m[np.clip(k, 0, len(m) - 1)], np.nan)


def mesurer(fills: pd.DataFrame, series: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]]) -> pd.DataFrame:
    lignes = []
    for (jour, coin), (t, m) in series.items():
        sel = fills[(fills["jour"] == jour) & (fills["coin"] == coin)]
        if sel.empty or not len(t):
            continue
        ts = sel["ts_ms"].to_numpy(np.int64)
        s = sel["signe"].to_numpy(float)
        m0 = mid_a(t, m, ts)
        d = {"jour": jour, "coin": coin, "vault": sel["vault"].to_numpy(), "ouverture": sel["dir"].str.startswith("Open").to_numpy(),
             "prix_obtenu": 1e4 * s * (m0 / sel["px"].to_numpy(float) - 1.0)}
        for h in HORIZONS_S:
            mh = mid_a(t, m, ts + 1000 * h)
            d[f"mk_{h}"] = 1e4 * s * (mh / m0 - 1.0) if h > 0 else 1e4 * s * (m0 / mh - 1.0)
        e = mid_a(t, m, ts + 1000 * LATENCE_S)
        x = mid_a(t, m, ts + 1000 * (LATENCE_S + TENUE_S))
        d["copie_net"] = 1e4 * s * (x / e - 1.0) - COUT_BPS
        lignes.append(pd.DataFrame(d))
    return pd.concat(lignes, ignore_index=True) if lignes else pd.DataFrame()


def ic(valeurs: pd.Series, blocs: pd.Series) -> tuple[float, float, float, int]:
    ok = valeurs.notna()
    v, b = valeurs[ok].to_numpy(float), blocs[ok].to_numpy()
    if len(v) < 2:
        return float("nan"), float("nan"), float("nan"), int(len(v))
    codes = pd.factorize(b)[0]
    moy, bas, haut = G.ic_bootstrap_par_blocs(v, codes)
    return moy, bas, haut, int(len(v))


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sans-registre", action="store_true")
    a = p.parse_args(argv)
    fills = G.charger("fills", "exploration")
    fills["jour"] = pd.to_datetime(fills["ts_ms"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    fills = fills[fills["coin"].isin(COINS) & fills["jour"].isin(JOURS)]
    series = {}
    for jour in JOURS:
        for coin in COINS:
            chemin = TARDIS / jour / f"{coin}.csv.gz"
            if chemin.exists():
                series[(jour, coin)] = mids(chemin)
    df = mesurer(fills, series)
    blocs = df["jour"] + ":" + df["vault"].astype(str)
    print(f"  H20 | {len(df)} fills mesurés ({df['vault'].nunique()} leaders) sur {len(series)} séries Tardis | coût copie {COUT_BPS} bps")
    f = lambda t: f"{t[0]:7.2f} [{t[1]:6.2f};{t[2]:6.2f}] n={t[3]}"   # noqa: E731
    resultats = {}
    for nom, masque in (("tous", df["vault"].notna()), ("ouvertures", df["ouverture"])):
        sous = df[masque]
        b = blocs[masque]
        r = {"prix_obtenu": ic(sous["prix_obtenu"], b), "copie_net_1h": ic(sous["copie_net"], b)}
        for h in HORIZONS_S:
            r[f"markout_{h}s"] = ic(sous[f"mk_{h}"], b)
        resultats[nom] = {k: [round(x, 3) if isinstance(x, float) else x for x in v] for k, v in r.items()}
        print(f"  --- {nom}")
        print(f"      prix obtenu vs mid : {f(r['prix_obtenu'])}")
        for h in HORIZONS_S:
            print(f"      {'avant' if h < 0 else 'apres'} {abs(h):>5} s : {f(r[f'markout_{h}s'])}")
        print(f"      COPIE (t+120 s -> +1 h, -12 bps) : {f(r['copie_net_1h'])}")
    net = resultats["ouvertures"]["copie_net_1h"]
    statut = "CANDIDAT_PROSPECTIF" if net[1] > 0 else "REJECTED"
    print(f"  -> {statut}")
    if not a.sans_registre:
        G.enregistrer({"hypothese": "H20_decroissance_avantage_leader_tardis", "segment": "exploration", "statut": statut,
                       "parametres": {"jours": list(JOURS), "coins": list(COINS), "latence_s": LATENCE_S, "tenue_s": TENUE_S,
                                      "cout_bps": COUT_BPS, "source_mid": "Tardis incremental_book_L2 (instantanes)"},
                       "resultats": resultats})
        print(f"  essai enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
