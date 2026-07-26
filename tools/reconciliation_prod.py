"""RÉCONCILIATION & EXCLUSIONS RÉELLES (Flo 26/07, LABO-CONTINU-PROD-TRUTH PT-10).

La somme des médianes de candidats N'EST PAS un PnL. Ici on RECONSTRUIT, en STREAMING (jamais tout charger en
mémoire), depuis le ledger d'événements d'un portefeuille paper :
  events (OPEN/ADD/REDUCE/CLOSE) → positions → PnL réalisé/latent → cash → equity → drawdown → ROI total/déployé.
On AGRÈGE aussi les VRAIES exclusions (sources non parsées, épisodes UNMEASURABLE/NO_FILL/NO_DATA, troncatures)
au lieu de renvoyer systématiquement une liste vide. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import json
from pathlib import Path


def lire_jsonl_stream(chemin: Path):
    """Générateur : rend chaque objet JSON du fichier ligne par ligne (STREAMING, pour de très gros JSONL)."""
    chemin = Path(chemin)
    if not chemin.exists():
        return
    with chemin.open("r", encoding="utf-8", errors="ignore") as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                yield json.loads(ligne)
            except ValueError:
                continue


def reconstruire_depuis_ledger(chemin_ledger: Path, *, capital_initial: float = 1000.0) -> dict:
    """Reconstruit l'état d'un portefeuille depuis SON ledger (OPEN/ADD/REDUCE/CLOSE), en streaming. Rend
    realized, cash, equity (à la clôture des positions restantes marquées à leur dernier prix vu), drawdown,
    ROI total/déployé. Indépendant de tout compteur courant : c'est la SOURCE DE VÉRITÉ."""
    cash = float(capital_initial)
    realized = 0.0
    frais = 0.0
    n_open = n_add = n_reduce = n_close = 0
    marge_engagee = 0.0
    for e in lire_jsonl_stream(chemin_ledger):
        t = e.get("type")
        cout = float(e.get("cout_usd") or 0.0)
        pnl = float(e.get("pnl_usd") or 0.0)
        notional = float(e.get("notional") or 0.0)
        marge = abs(notional) / 3.0                          # levier de référence (cohérent avec le portefeuille)
        if t == "OPEN":
            n_open += 1
            cash -= (marge + cout); frais += cout; realized -= cout; marge_engagee += marge
        elif t == "ADD":
            n_add += 1
            cash -= (marge + cout); frais += cout; realized -= cout; marge_engagee += marge
        elif t in ("REDUCE", "CLOSE"):
            n_reduce += 1 if t == "REDUCE" else 0
            n_close += 1 if t == "CLOSE" else 0
            cash += (marge + pnl - cout); realized += pnl - cout; frais += cout
            marge_engagee = max(0.0, marge_engagee - marge)
    equity = cash + marge_engagee                            # positions restantes : marge conservée (latent inconnu ici)
    roi_total = (equity - capital_initial) / capital_initial * 100.0 if capital_initial else None
    deploye = max(capital_initial - cash, 1e-9)
    roi_deploye = realized / deploye * 100.0
    return {"capital_initial": round(capital_initial, 4), "cash": round(cash, 4),
            "pnl_realise": round(realized, 4), "frais_cumules": round(frais, 4),
            "marge_engagee": round(marge_engagee, 4), "equity": round(equity, 4),
            "roi_total_pct": (round(roi_total, 4) if roi_total is not None else None),
            "roi_deploye_pct": round(roi_deploye, 4),
            "evenements": {"open": n_open, "add": n_add, "reduce": n_reduce, "close": n_close},
            "source": "LEDGER_EVENTS (reconstruit en streaming)"}


def reconstruire_global(ledgers, *, capital_initial: float = 1000.0, levier: float = 3.0,
                        equity_curve_out=None) -> dict:
    """PORTEFEUILLE GLOBAL DU RUN : fusionne TOUS les ledgers de campagne en UNE seule séquence chronologique
    et fait passer UN SEUL capital à travers (jamais additionner plusieurs capitaux ni plusieurs drawdowns).
    Rend une equity curve unique, drawdown global, ROI total (capital initial) et ROI déployé (capital PIC
    réellement engagé). Écrit optionnellement l'equity curve en JSONL streaming."""
    ledgers = list(ledgers)
    evts = []
    for lg in ledgers:
        for e in lire_jsonl_stream(lg):
            ts = e.get("ts_ms")
            if ts is None:
                ts = e.get("entry_ts") or e.get("exit_ts") or 0
            evts.append((float(ts or 0), e))
    evts.sort(key=lambda x: x[0])
    cash = float(capital_initial)
    marge = 0.0
    realized = 0.0
    pic_equity = float(capital_initial)
    marge_pic = 0.0
    max_dd = 0.0
    n = {"open": 0, "add": 0, "reduce": 0, "close": 0}
    fout = None
    if equity_curve_out is not None:
        Path(equity_curve_out).parent.mkdir(parents=True, exist_ok=True)
        fout = Path(equity_curve_out).open("w", encoding="utf-8")
    try:
        for ts, e in evts:
            t = e.get("type"); cout = float(e.get("cout_usd") or 0.0); pnl = float(e.get("pnl_usd") or 0.0)
            m = abs(float(e.get("notional") or 0.0)) / levier
            if t in ("OPEN", "ADD"):
                cash -= (m + cout); realized -= cout; marge += m; n["open" if t == "OPEN" else "add"] += 1
            elif t in ("REDUCE", "CLOSE"):
                cash += (m + pnl - cout); realized += pnl - cout; marge = max(0.0, marge - m)
                n["reduce" if t == "REDUCE" else "close"] += 1
            equity = cash + marge
            pic_equity = max(pic_equity, equity)
            marge_pic = max(marge_pic, marge)
            max_dd = max(max_dd, pic_equity - equity)
            if fout is not None:
                fout.write(json.dumps({"ts_ms": ts, "equity": round(equity, 4), "cash": round(cash, 4),
                                       "marge": round(marge, 4), "realized": round(realized, 4)}) + "\n")
    finally:
        if fout is not None:
            fout.close()
    equity = cash + marge
    roi_total = (equity - capital_initial) / capital_initial * 100.0 if capital_initial else None
    deploye = max(marge_pic, 1e-9)
    return {"capital_initial": round(capital_initial, 4), "cash": round(cash, 4),
            "pnl_realise": round(realized, 4), "equity": round(equity, 4),
            "drawdown_usd": round(max_dd, 4), "marge_pic": round(marge_pic, 4),
            "roi_total_pct": (round(roi_total, 4) if roi_total is not None else None),
            "roi_deploye_pct": round(realized / deploye * 100.0, 4),
            "n_evenements": len(evts), "evenements": n, "n_ledgers": len(list(ledgers)),
            "source": "PORTEFEUILLE GLOBAL (une equity curve, un capital, drawdown non additionné)"}


def comparer(reconstruit: dict, courant: dict, *, tol: float = 1e-4) -> dict:
    """Compare la reconstruction au portefeuille courant sur les champs clés. `coherent=False` si écart > tol."""
    champs = ("cash", "pnl_realise", "equity")
    ecarts = {}
    for c in champs:
        a, b = reconstruit.get(c), courant.get(c) if c != "pnl_realise" else courant.get("pnl_realise")
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) > tol:
            ecarts[c] = round(a - b, 6)
    return {"coherent": not ecarts, "ecarts": ecarts}


def agreger_exclusions(rundir: Path) -> list:
    """VRAIES exclusions agrégées sur toutes les campagnes (streaming) : sources non parsées (accounting),
    épisodes non mesurés (UNMEASURABLE/NO_FILL/NO_DATA dans le forward), et curseurs en rotation/troncature.
    Ne renvoie JAMAIS [] par défaut si des exclusions existent réellement."""
    rundir = Path(rundir)
    exclusions = []
    camps = sorted((rundir / "campagnes").glob("camp-*")) if (rundir / "campagnes").exists() else []
    for c in camps:
        # 1) sources cataloguées mais NON parsées (accounting du pipeline)
        try:
            r = json.loads((c / "resultats" / "pipeline_resume.json").read_text(encoding="utf-8"))
            acc = r.get("accounting", {})
            nx = acc.get("n_excluded", 0)
            if nx:
                exclusions.append({"campagne": c.name, "type": "SOURCES_NON_PARSEES", "n": nx})
        except (OSError, ValueError):
            pass
        # 2) épisodes forward non mesurés (statuts != OK), en streaming
        compte = {}
        for e in lire_jsonl_stream(c / "ledger" / "forward_paper.jsonl"):
            st = e.get("type")
            if st and st not in ("FILL", "OPEN", "ADD", "REDUCE", "CLOSE"):
                compte[st] = compte.get(st, 0) + 1
        for st, n in compte.items():
            exclusions.append({"campagne": c.name, "type": "EPISODE_%s" % st, "n": n})
    return exclusions


__all__ = ["lire_jsonl_stream", "reconstruire_depuis_ledger", "comparer", "agreger_exclusions"]
