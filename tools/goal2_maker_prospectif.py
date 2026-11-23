r"""H22-P — confrontation prospective de la copie MAKER à 60 s (règle H22 figée) aux données de NOS collecteurs.

Seules les données enregistrées APRÈS le gel de H22 sont lues : carnet `copy_vault_l2_tape.jsonl` (5 niveaux avec
tailles), trades `copy_vault_trades_lane.jsonl` (côté agresseur), ouvertures de leaders du journal du moteur. Règle de
remplissage identique à H22 (`goal2_maker_tardis.simuler`). Garde de causalité : un fill reçu plus de 60 s après son
exécution ne pouvait pas être copié à t + 60 s -> NO-TRADE (0). Verdict seulement avec >= 100 signaux mesurables sur
>= 5 jours ; sinon MORE_DATA. LECTURE SEULE, PAPER ; inscrit au registre seulement avec un verdict et `--enregistrer`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
for p in (RACINE / "src", RACINE / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import goal2_maker_tardis as M  # noqa: E402

GEL = RACINE / "runtime" / "reports" / "copy_vault_quant_lab" / "goal2" / "FREEZE_H22.json"
CARNET = Path("runtime") / "data" / "copy_vault_l2_tape.jsonl"
TRADES = Path("runtime") / "data" / "copy_vault_trades_lane.jsonl"
SIGNAUX_MIN, JOURS_MIN = 100, 5


def gel_ms() -> int:
    texte = json.loads(GEL.read_text(encoding="utf-8"))["gele_le_utc"]
    return int(dt.datetime.strptime(texte, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def _lignes(chemin: Path, depuis_ms: int, champ: str):
    if not chemin.exists():
        return
    with chemin.open(encoding="utf-8", errors="replace") as f:
        for ligne in f:
            try:
                x = json.loads(ligne)
            except ValueError:
                continue
            t = x.get(champ)
            if isinstance(t, (int, float)) and t >= depuis_ms and x.get("causal_observation", True) is not False:
                yield x


def carnets(root: Path, depuis_ms: int) -> dict[str, dict[str, np.ndarray]]:
    par: dict[str, list] = {}
    for x in _lignes(root / CARNET, depuis_ms, "exchange_ts_ms"):
        b, a = x.get("bids5") or [], x.get("asks5") or []
        if b and a and float(a[0][0]) > float(b[0][0]) > 0:
            par.setdefault(x["coin"], []).append((int(x["exchange_ts_ms"]), float(b[0][0]), float(b[0][1]), float(a[0][0]), float(a[0][1])))
    out = {}
    for coin, v in par.items():
        v.sort()
        m = np.asarray(v, dtype=float)
        out[coin] = {"t": m[:, 0].astype(np.int64), "bid": m[:, 1], "bid_sz": m[:, 2], "ask": m[:, 3], "ask_sz": m[:, 4]}
    return out


def trades(root: Path, depuis_ms: int) -> dict[str, dict[str, np.ndarray]]:
    par: dict[str, list] = {}
    for x in _lignes(root / TRADES, depuis_ms, "exchange_ts_ms"):
        cote = {"BUY": 1, "SELL": -1}.get(str(x.get("aggressor_side")).upper())
        if cote is not None:
            par.setdefault(x["coin"], []).append((int(x["exchange_ts_ms"]), cote, float(x["price"]), float(x["size"])))
    out = {}
    for coin, v in par.items():
        v.sort()
        m = np.asarray(v, dtype=float)
        out[coin] = {"t": m[:, 0].astype(np.int64), "cote": m[:, 1].astype(np.int8), "px": m[:, 2], "amt": m[:, 3]}
    return out


def ouvertures(lignes, depuis_ms: int) -> list[dict]:
    out = []
    for x in lignes:
        d = str(x.get("dir") or "")
        t = x.get("fill_ts_ms") or x.get("time") or x.get("ts_ms")
        recu = x.get("recu_ms") or x.get("received_at_ms")
        if d.startswith("Open") and isinstance(t, (int, float)) and t >= depuis_ms and isinstance(recu, (int, float)):
            out.append({"coin": x.get("coin"), "vault": str(x.get("vault") or ""), "signe": 1 if d == "Open Long" else -1,
                        "t": int(t), "recu": int(recu)})
    return out


def evaluer(signaux: list[dict], c: dict, tr: dict) -> dict:
    lignes = []
    for s in signaux:
        if s["recu"] - s["t"] > 1000 * M.LATENCE_S:
            lignes.append({**s, "etat": "TROP_TARD", "pnl": 0.0})            # pas vu à temps : NO-TRADE
            continue
        if s["coin"] not in c or s["coin"] not in tr:
            lignes.append({**s, "etat": "NON_MESURABLE"})
            continue
        r = M.simuler(s["signe"], s["t"], c[s["coin"]], tr[s["coin"]])
        lignes.append({**s, **r, "pnl": (r.get("net") if r["etat"] == "REMPLI" else 0.0) if r["etat"] != "NON_MESURABLE" else None})
    df = pd.DataFrame(lignes)
    if df.empty:
        return {"statut": "MORE_DATA", "signaux": 0, "mesurables": 0, "jours": 0}
    ok = df[df["etat"] != "NON_MESURABLE"].copy()
    ok["jour"] = (ok["t"] // 86_400_000).astype(np.int64)
    sortie = {"signaux": int(len(df)), "mesurables": int(len(ok)), "jours": int(ok["jour"].nunique()),
              "etats": {k: int(v) for k, v in df["etat"].value_counts().items()}}
    if len(ok) < SIGNAUX_MIN or sortie["jours"] < JOURS_MIN:
        return {**sortie, "statut": "MORE_DATA"}
    blocs = ok["jour"].astype(str) + ":" + ok["vault"]
    import goal2_decroissance_tardis as D
    pnl = D.ic(ok["pnl"].astype(float), blocs)
    return {**sortie, "pnl_total_par_signal": [round(float(x), 3) for x in pnl[:3]],
            "statut": "PROMISING" if pnl[1] > 0 else "REJECTED"}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--enregistrer", action="store_true")
    a = p.parse_args(argv)
    root = Path(a.racine)
    depuis = gel_ms()
    from hl_observer.experimental import cycles_fantomes as CF
    sig = ouvertures(CF.lire_journal(root), depuis)
    r = evaluer(sig, carnets(root, depuis), trades(root, depuis))
    print(f"  H22-P | depuis le gel ({dt.datetime.fromtimestamp(depuis / 1000, dt.timezone.utc):%Y-%m-%d %H:%M} UTC) : {r}")
    if a.enregistrer and r["statut"] != "MORE_DATA":
        import goal2_commun as G
        G.enregistrer({"hypothese": "H22P_maker_60s_prospectif", "segment": "prospectif_apres_gel_H22", "statut": r["statut"], "resultats": r})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
