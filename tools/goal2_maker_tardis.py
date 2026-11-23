r"""H22 — copier une ouverture de leader en MAKER à 60 s, avec un remplissage honnête (pré-enregistrée au journal).

Ordre limite au meilleur prix de notre côté à t + 60 s ; rempli SEULEMENT si, dans les 60 s suivantes, le volume des
trades agresseurs du côté opposé, à notre prix ou à travers, dépasse la taille affichée à ce niveau au moment de poster
(la file devant nous). Toucher le prix ne suffit pas. Non rempli = NO-TRADE (0). Sortie taker au mid 1 h après
l'entrée. Carnet et trades : Tardis (horloge de la bourse). LECTURE SEULE, PAPER. Une ligne au registre chaîné.
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
import goal2_decroissance_tardis as D

TARDIS = G.RACINE / "runtime" / "history" / "tardis"
LATENCE_S, FENETRE_S, TENUE_S = 60, 60, 3600
FRAIS_MAKER, FRAIS_TAKER = 1.5, 4.5
NOTRE_TAILLE_USD = 20.0


def carnet(chemin: Path) -> dict[str, np.ndarray]:
    """Par instantané : t_ms, meilleur bid/ask et la TAILLE affichée à chacun (lu en flux)."""
    out = {k: [] for k in ("t", "bid", "bid_sz", "ask", "ask_sz")}
    courant, niveaux = None, {"bid": {}, "ask": {}}

    def vider() -> None:
        if courant is not None and niveaux["bid"] and niveaux["ask"]:
            b, a = max(niveaux["bid"]), min(niveaux["ask"])
            if a > b > 0:
                out["t"].append(courant // 1000); out["bid"].append(b); out["bid_sz"].append(niveaux["bid"][b])
                out["ask"].append(a); out["ask_sz"].append(niveaux["ask"][a])

    with gzip.open(chemin, "rt", encoding="utf-8", newline="") as f:
        lecteur = csv.reader(f)
        e = next(lecteur)
        i_ts, i_side, i_px, i_amt = e.index("timestamp"), e.index("side"), e.index("price"), e.index("amount")
        for ligne in lecteur:
            ts = int(ligne[i_ts])
            if ts != courant:
                vider()
                courant, niveaux = ts, {"bid": {}, "ask": {}}
            amt = float(ligne[i_amt])
            if amt > 0:
                niveaux["bid" if ligne[i_side] == "bid" else "ask"][float(ligne[i_px])] = amt
        vider()
    return {k: np.asarray(v, dtype=np.int64 if k == "t" else float) for k, v in out.items()}


def trades(chemin: Path) -> dict[str, np.ndarray]:
    t, cote, px, amt = [], [], [], []
    with gzip.open(chemin, "rt", encoding="utf-8", newline="") as f:
        lecteur = csv.reader(f)
        e = next(lecteur)
        i_ts, i_side, i_px, i_amt = e.index("timestamp"), e.index("side"), e.index("price"), e.index("amount")
        for ligne in lecteur:
            t.append(int(ligne[i_ts]) // 1000); cote.append(1 if ligne[i_side] == "buy" else -1)
            px.append(float(ligne[i_px])); amt.append(float(ligne[i_amt]))
    return {"t": np.asarray(t, np.int64), "cote": np.asarray(cote, np.int8), "px": np.asarray(px), "amt": np.asarray(amt)}


def simuler(signe: int, t_fill: int, c: dict, tr: dict) -> dict:
    """Un signal : rempli ? à quel prix ? net si rempli. Carnet absent ou périmé -> NON_MESURABLE."""
    poste = t_fill + 1000 * LATENCE_S
    k = int(np.searchsorted(c["t"], poste, side="right")) - 1
    if k < 0 or poste - c["t"][k] > 5_000:
        return {"etat": "NON_MESURABLE"}
    prix = c["bid"][k] if signe > 0 else c["ask"][k]
    file = c["bid_sz"][k] if signe > 0 else c["ask_sz"][k]
    notre = NOTRE_TAILLE_USD / prix
    a, b = int(np.searchsorted(tr["t"], poste, side="right")), int(np.searchsorted(tr["t"], poste + 1000 * FENETRE_S, side="right"))
    cote_oppose = -signe                                   # un achat passif est rempli par des VENDEURS agresseurs
    sel = slice(a, b)
    vol = tr["amt"][sel][(tr["cote"][sel] == cote_oppose) &
                         ((tr["px"][sel] <= prix) if signe > 0 else (tr["px"][sel] >= prix))]
    cumule = np.cumsum(vol)
    rempli = bool(len(cumule) and cumule[-1] > file + notre)
    sortie = poste + 1000 * TENUE_S
    j = int(np.searchsorted(c["t"], sortie, side="right")) - 1
    if j < 0 or sortie - c["t"][j] > 5_000:
        return {"etat": "NON_MESURABLE"}
    mid_sortie = (c["bid"][j] + c["ask"][j]) / 2
    demi_ecart = 1e4 * (c["ask"][j] - c["bid"][j]) / 2 / mid_sortie
    brut = 1e4 * signe * (mid_sortie / prix - 1.0)
    return {"etat": "REMPLI" if rempli else "NON_REMPLI", "brut": brut,
            "net": brut - FRAIS_MAKER - FRAIS_TAKER - demi_ecart}


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
    fills = fills[fills["coin"].isin(D.COINS) & fills["jour"].isin(D.JOURS) & fills["dir"].str.startswith("Open")]
    lignes = []
    for jour in D.JOURS:
        for coin in D.COINS:
            cl, ct = TARDIS / "incremental_book_L2" / jour / f"{coin}.csv.gz", TARDIS / "trades" / jour / f"{coin}.csv.gz"
            sel = fills[(fills["jour"] == jour) & (fills["coin"] == coin)]
            if sel.empty or not cl.exists() or not ct.exists():
                continue
            c, tr = carnet(cl), trades(ct)
            for _, f in sel.iterrows():
                r = simuler(int(f["signe"]), int(f["ts_ms"]), c, tr)
                lignes.append({"jour": jour, "vault": f["vault"], "coin": coin, **r})
    df = pd.DataFrame(lignes)
    ok = df[df["etat"] != "NON_MESURABLE"].copy()
    blocs = ok["jour"] + ":" + ok["vault"].astype(str)
    ok["pnl_signal"] = np.where(ok["etat"] == "REMPLI", ok["net"], 0.0)
    remplis, non = ok[ok["etat"] == "REMPLI"], ok[ok["etat"] == "NON_REMPLI"]
    f = lambda t: f"{t[0]:7.2f} [{t[1]:6.2f};{t[2]:6.2f}] n={t[3]}"   # noqa: E731
    r = {"signaux": int(len(df)), "mesurables": int(len(ok)), "taux_remplissage": round(float((ok["etat"] == "REMPLI").mean()), 3),
         "net_remplis": D.ic(remplis["net"], blocs[remplis.index]), "brut_remplis": D.ic(remplis["brut"], blocs[remplis.index]),
         "brut_non_remplis": D.ic(non["brut"], blocs[non.index]), "pnl_total_par_signal": D.ic(ok["pnl_signal"], blocs)}
    print(f"  H22 | {r['signaux']} ouvertures, {r['mesurables']} mesurables | remplissage {100 * r['taux_remplissage']:.1f} %")
    print(f"  brut des REMPLIS      : {f(r['brut_remplis'])}")
    print(f"  brut des NON remplis  : {f(r['brut_non_remplis'])}   (écart = sélection adverse)")
    print(f"  net des REMPLIS       : {f(r['net_remplis'])}")
    print(f"  PnL TOTAL par signal  : {f(r['pnl_total_par_signal'])}   (taker à 120 s, H20 : -9,43)")
    statut = "CANDIDAT_PROSPECTIF" if r["pnl_total_par_signal"][1] > 0 else "REJECTED"
    print(f"  -> {statut}")
    if not a.sans_registre:
        G.enregistrer({"hypothese": "H22_copie_maker_60s_remplissage_honnete", "segment": "exploration", "statut": statut,
                       "parametres": {"latence_s": LATENCE_S, "fenetre_s": FENETRE_S, "tenue_s": TENUE_S, "frais_maker": FRAIS_MAKER,
                                      "frais_taker": FRAIS_TAKER, "regle": "volume agresseur oppose >= file affichee + notre taille"},
                       "resultats": {k: (list(map(lambda x: round(float(x), 3), v)) if isinstance(v, tuple) else v) for k, v in r.items()}})
        print(f"  essai enregistre (total : {G.nombre_d_essais()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
