#!/usr/bin/env python3
"""LA PAGE DE PROGRESSION DE KAITO (T1) -- 2026-07-12.

Elle repond a UNE question : **quand saura-t-on, et que sait-on deja ?**

CE QU'ELLE MONTRE, ET POURQUOI
------------------------------
Un verdict de market making n'existe pas tant que TROIS verrous ne sont pas franchis :

  1. >= 30 trades LIVE          -> en dessous, on ne mesure meme pas une mediane.
  2. >= 30 min de fenetre       -> une RAFALE n'est pas un DEBIT (CASHCAT : 86 trades en 14 s,
                                   extrapoles a 9,5 M$/h -- une fiction).
  3. >= 300 fills a la borne DERRIERE -> 31 trades, c'est un pile ou face. Le verrou qui compte
                                   vraiment, parce qu'un retail n'est rempli QUE par le quart
                                   superieur du flux (les gros trades balayent la file).

La page affiche l'avancement de chacun, et surtout **l'ETA calcule sur le debit REELLEMENT
observe** -- pas sur un espoir. Si les 4 h ne suffisent pas, elle le DIT.

Elle n'affiche jamais un verdict que la donnee ne porte pas. Deny-by-default, jusque dans l'UI.

LECTURE SEULE. Serveur local (127.0.0.1). Aucun ordre, aucune cle, aucune signature. JAMAIS.

    python tools/page_kaito.py            # sert la page sur http://127.0.0.1:8799
    python tools/page_kaito.py --once     # ecrit un HTML statique et sort
"""
from __future__ import annotations

import argparse
import html
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting.market_making_flow import (  # noqa: E402
    FENETRE_MIN_OBSERVATION_S,
    MIN_TRADES,
    MIN_TRADES_POUR_CONCLURE,
    encadrer_le_market_making,
    fenetre_continue_s,
)

PORT = 8799
PIECE = "KAITO"
DUREE_ECOUTE_S = 240 * 60.0


# ===================================================================== la partie PURE (testable)

def progression(
    trades_live: list[dict],
    *,
    fenetre_s: float,
    fills_derriere: int,
    duree_ecoute_s: float = DUREE_ECOUTE_S,
    ecoule_s: float = 0.0,
) -> dict[str, Any]:
    """L'etat d'avancement des 3 verrous, + l'ETA calcule sur le DEBIT OBSERVE.

    REGLE : on n'extrapole que depuis ce qu'on a VU. Si le debit est nul, l'ETA est `None` --
    on ne dit pas "bientot", on dit "on ne sait pas".
    """
    n = len(trades_live)
    minutes = fenetre_s / 60.0 if fenetre_s > 0 else 0.0

    debit_trades_min = (n / minutes) if minutes > 0 else 0.0
    debit_fills_min = (fills_derriere / minutes) if minutes > 0 else 0.0

    restant_s = max(0.0, duree_ecoute_s - ecoule_s)

    # ETA du verrou qui decide : 300 fills a la borne DERRIERE.
    manque = max(0, MIN_TRADES_POUR_CONCLURE - fills_derriere)
    if manque == 0:
        eta_fills_s: float | None = 0.0
    elif debit_fills_min > 0:
        eta_fills_s = manque / debit_fills_min * 60.0
    else:
        eta_fills_s = None            # aucun fill observe -> aucune extrapolation honnete

    # la fenetre de 30 min : elle avance a la vitesse du temps, pas du flux
    manque_fenetre_s = max(0.0, FENETRE_MIN_OBSERVATION_S - fenetre_s)

    atteignable = None
    if eta_fills_s is not None:
        atteignable = eta_fills_s <= restant_s

    return {
        "n_trades_live": n,
        "fenetre_s": round(fenetre_s, 1),
        "fills_derriere": fills_derriere,
        "debit_trades_par_min": round(debit_trades_min, 2),
        "debit_fills_par_min": round(debit_fills_min, 2),
        "verrous": [
            {"nom": "trades LIVE (mesurable ?)", "actuel": n, "cible": MIN_TRADES,
             "pct": min(100.0, 100.0 * n / MIN_TRADES)},
            {"nom": "fenetre d'observation (un debit, pas une rafale)",
             "actuel": round(fenetre_s), "cible": int(FENETRE_MIN_OBSERVATION_S),
             "pct": min(100.0, 100.0 * fenetre_s / FENETRE_MIN_OBSERVATION_S)},
            {"nom": "fills a la borne DERRIERE (concluant ?)",
             "actuel": fills_derriere, "cible": MIN_TRADES_POUR_CONCLURE,
             "pct": min(100.0, 100.0 * fills_derriere / MIN_TRADES_POUR_CONCLURE)},
        ],
        "manque_fenetre_s": round(manque_fenetre_s),
        "eta_verdict_s": None if eta_fills_s is None else round(eta_fills_s),
        "restant_ecoute_s": round(restant_s),
        "verdict_atteignable_dans_la_fenetre": atteignable,
        "conclusif": (n >= MIN_TRADES and fenetre_s >= FENETRE_MIN_OBSERVATION_S
                      and fills_derriere >= MIN_TRADES_POUR_CONCLURE),
    }


def _duree(s: float | None) -> str:
    if s is None:
        return "inconnu"
    s = int(s)
    if s <= 0:
        return "atteint"
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    if h:
        return "%dh %02dmin" % (h, m)
    if m:
        return "%dmin %02ds" % (m, sec)
    return "%ds" % sec


# ===================================================================== lecture des donnees

def fichier_de_la_session_courante() -> Path | None:
    """LE fichier de l'ecoute EN COURS -- pas les archives des sessions precedentes.

    LE BUG QUE CETTE FONCTION CORRIGE (2026-07-12, vu directement dans l'UI)
    ----------------------------------------------------------------------
    La page lisait TOUS les `trades*.jsonl` du dossier. Or il y en a un par session d'ecoute.
    Elle annonçait donc "ecoute demarree a 13h48" et "fenetre de 29 506 s" -- en melangeant
    trois sessions separees par des HEURES de trou.

    Consequences, et elles n'etaient pas cosmetiques :
      * le debit affiche etait divise par ~8 (les trous comptaient comme du temps d'ecoute) ;
      * le verrou des 30 min etait franchi par une ILLUSION ;
      * pire : a l'horizon de 30 s, un trade juste avant un trou voyait son "prix apres" pris
        8 H PLUS TARD -- la selection adverse devenait du bruit de nuit.

    On ne regarde donc qu'un fichier : celui qu'on est en train d'ecrire.
    """
    fichiers = list(ROOT.glob("runtime/replay/trades*.jsonl"))
    if not fichiers:
        return None
    return max(fichiers, key=lambda f: f.stat().st_mtime)


def _charger(piece: str) -> tuple[list[dict], list[dict], float, list[float]]:
    """(trades LIVE du coin, tous ses trades, debut REEL de l'ecoute, ts de TOUS les coins).

    Tout est lu dans le fichier de la SESSION COURANTE uniquement.
    """
    f = fichier_de_la_session_courante()
    if f is None:
        return [], [], time.time(), []

    tous: list[dict] = []
    ts_session: list[float] = []
    with open(f, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                t = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not t.get("snapshot") and t.get("ts"):
                ts_session.append(float(t["ts"]))     # tous coins : sert a dater l'ecoute
            if t.get("coin") == piece:
                tous.append(t)

    # Le debut de l'ecoute = le 1er trade LIVE reellement reçu, pas la date d'un fichier.
    debut = min(ts_session) if ts_session else f.stat().st_mtime
    live = [t for t in tous if not t.get("snapshot")]
    return live, tous, debut, ts_session


def _carnet(piece: str) -> dict:
    rows = []
    for f in sorted(ROOT.glob("runtime/replay/l2_book*.jsonl")):
        with open(f, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("coin") == piece and r.get("spread_bps") is not None:
                    rows.append(r)
    if not rows:
        return {}
    return {
        "spread_bps": statistics.median(float(r["spread_bps"]) for r in rows),
        "bid_depth_usd": statistics.median(float(r.get("bid_depth_usd") or 0.0) for r in rows),
        "ask_depth_usd": statistics.median(float(r.get("ask_depth_usd") or 0.0) for r in rows),
        "n": len(rows),
    }


def _autres_marches(limite: int = 6) -> list[tuple[str, int]]:
    from collections import Counter
    c: Counter = Counter()
    for f in sorted(ROOT.glob("runtime/replay/trades*.jsonl")):
        with open(f, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    t = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if t.get("coin") and not t.get("snapshot"):
                    c[t["coin"]] += 1
    return c.most_common(limite)


# ===================================================================== la page

CSS = """
:root{--bg:#0e1116;--card:#161b22;--bd:#2a313a;--tx:#e6edf3;--mu:#8b949e;
      --ok:#3fb950;--warn:#d29922;--bad:#f85149;--acc:#58a6ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
     font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;padding:28px}
.wrap{max-width:1100px;margin:0 auto}
h1{margin:0 0 4px;font-size:26px;letter-spacing:-.3px}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.9px;color:var(--mu);
   margin:34px 0 12px;font-weight:600}
.sub{color:var(--mu);margin-bottom:26px;font-size:13px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:18px 20px;
      margin-bottom:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.kpi{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px 16px}
.kpi .l{color:var(--mu);font-size:11px;text-transform:uppercase;letter-spacing:.7px}
.kpi .v{font-size:24px;font-weight:600;margin-top:5px;font-variant-numeric:tabular-nums}
.kpi .n{color:var(--mu);font-size:12px;margin-top:3px}
.bar{height:9px;background:#21262d;border-radius:5px;overflow:hidden;margin-top:8px}
.bar > i{display:block;height:100%;background:var(--acc);border-radius:5px}
.bar.done > i{background:var(--ok)}
.row{display:flex;justify-content:space-between;align-items:baseline;gap:14px}
.row .n{font-variant-numeric:tabular-nums;color:var(--mu);font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;color:var(--mu);font-weight:600;font-size:11px;text-transform:uppercase;
   letter-spacing:.6px;padding:8px 10px;border-bottom:1px solid var(--bd)}
td{padding:9px 10px;border-bottom:1px solid #1c2229;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:0}
.tag{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:600}
.t-ok{background:rgba(63,185,80,.15);color:var(--ok)}
.t-warn{background:rgba(210,153,34,.15);color:var(--warn)}
.t-bad{background:rgba(248,81,73,.15);color:var(--bad)}
.eq{background:#0b0f14;border:1px solid var(--bd);border-radius:8px;padding:14px 16px;
    font-family:ui-monospace,Consolas,monospace;font-size:13px;color:#c9d1d9;white-space:pre}
.note{color:var(--mu);font-size:13px;margin-top:10px}
b.hl{color:var(--tx)}
.foot{color:var(--mu);font-size:12px;margin-top:30px;border-top:1px solid var(--bd);padding-top:14px}
"""


def _bar(pct: float, done: bool) -> str:
    return '<div class="bar%s"><i style="width:%.1f%%"></i></div>' % (
        " done" if done else "", max(0.0, min(100.0, pct)))


def rendre_html() -> str:
    live, tous, debut, _ts_session = _charger(PIECE)
    carnet = _carnet(PIECE)
    maintenant = time.time()
    ecoule = max(0.0, maintenant - debut)

    # La duree REELLEMENT observee (trous exclus), pas l'ecart entre le 1er et le dernier trade.
    fenetre = fenetre_continue_s([float(t["ts"]) for t in live if t.get("ts")])

    verdict = None
    fills_derriere = 0
    if carnet and live:
        verdict = encadrer_le_market_making(PIECE, live, spread_bps=carnet["spread_bps"])
        d = next((b for b in verdict.bornes if b.nom == "DERRIERE"), None)
        if d:
            fills_derriere = d.n_fills

    p = progression(live, fenetre_s=fenetre, fills_derriere=fills_derriere,
                    ecoule_s=ecoule)

    fin_prevue = time.strftime("%Hh%M", time.localtime(debut + DUREE_ECOUTE_S))
    debut_txt = time.strftime("%Hh%M", time.localtime(debut))
    pct_ecoute = min(100.0, 100.0 * ecoule / DUREE_ECOUTE_S)
    finie = p["restant_ecoute_s"] <= 0

    o = []
    a = o.append
    a('<!doctype html><html lang="fr"><head><meta charset="utf-8">')
    a('<meta http-equiv="refresh" content="15">')
    a("<title>KAITO — progression T1</title><style>%s</style></head><body><div class='wrap'>" % CSS)

    a("<h1>KAITO — le flux paie-t-il le risque ?</h1>")
    a("<div class='sub'>Ecoute du canal <b>public</b> <code>trades</code> · lecture seule · "
      "aucun ordre, aucune cle, aucune signature. "
      "Page rafraichie toutes les 15 s — il est %s</div>"
      % html.escape(time.strftime("%Hh%M:%S")))

    # ---------------------------------------------------------------- l'ecoute
    a("<h2>1 · L'ecoute en cours</h2><div class='card'>")
    a("<div class='row'><b>Demarree a %s &nbsp;→&nbsp; fin prevue a %s</b>"
      "<span class='n'>%s ecoulees sur 4h00 · <b class='hl'>%s</b></span></div>"
      % (debut_txt, fin_prevue, _duree(ecoule),
         "TERMINEE" if finie else ("il reste %s" % _duree(p["restant_ecoute_s"]))))
    a(_bar(pct_ecoute, finie))
    a("<div class='note'>Seule la session <b class='hl'>en cours</b> est comptee. "
      "Les fichiers des ecoutes precedentes sont ignores : les melanger donnait une fenetre "
      "d'observation fantome (et une selection adverse mesuree a travers 8 h de trou).</div>")
    a("</div>")

    # ---------------------------------------------------------------- les KPI
    a("<h2>2 · KAITO en ce moment</h2><div class='grid'>")
    kpis = [
        ("Trades LIVE captes", "%d" % p["n_trades_live"],
         "%d snapshot ignores (c'est de l'historique, pas du flux)" % (len(tous) - len(live))),
        ("Quelqu'un traverse le spread", "%.2f /min" % p["debit_trades_par_min"],
         "c'est ce flux, et lui seul, qui peut nous remplir"),
        ("Spread du carnet", ("%.1f bps" % carnet["spread_bps"]) if carnet else "—",
         ("mediane sur %d releves — on en capture la moitie" % carnet["n"])
         if carnet else "aucun carnet"),
        ("Profondeur bid / ask", ("%.0f / %.0f $" % (carnet["bid_depth_usd"], carnet["ask_depth_usd"]))
         if carnet else "—", "mon seuil de 2 500 $ l'excluait quand je n'avais que 8 releves"),
    ]
    for label, val, note in kpis:
        a("<div class='kpi'><div class='l'>%s</div><div class='v'>%s</div>"
          "<div class='n'>%s</div></div>" % (html.escape(label), html.escape(val),
                                             html.escape(note)))
    a("</div>")

    # ---------------------------------------------------------------- les 3 verrous
    a("<h2>3 · Les trois verrous d'un verdict honnete</h2>")
    a("<div class='sub' style='margin-bottom:14px'>Tant que les trois ne sont pas franchis, "
      "il n'y a <b>pas de verdict</b> — et la page n'en inventera pas un.</div>")
    explications = [
        "Sous 30 trades, on ne peut meme pas calculer une mediane de selection adverse. "
        "On ne mesure rien.",
        "Une RAFALE n'est pas un DEBIT. CASHCAT : 86 trades en 14 secondes, extrapoles a "
        "9,5 M$/h — une pure fiction. Il faut 30 min d'observation CONTINUE.",
        "C'est LE verrou qui decide. Un retail est au fond de la file : il n'est rempli que par "
        "le quart superieur du flux (les gros trades, ceux qui balayent la file). Sous 300 de "
        "ces fills-la, le signe du resultat est un pile ou face.",
    ]
    for v, pourquoi in zip(p["verrous"], explications):
        fait = v["pct"] >= 100
        a("<div class='card'><div class='row'><b>%s</b>"
          "<span class='n'>%s / %s &nbsp;%s</span></div>%s"
          "<div class='note'>%s</div></div>"
          % (html.escape(v["nom"]), "{:,}".format(v["actuel"]).replace(",", " "),
             "{:,}".format(v["cible"]).replace(",", " "),
             "<span class='tag t-ok'>FRANCHI</span>" if fait
             else "<span class='tag t-warn'>%.0f %%</span>" % v["pct"],
             _bar(v["pct"], fait), html.escape(pourquoi)))

    # ---------------------------------------------------------------- ETA
    a("<h2>4 · Quand saura-t-on ?</h2><div class='card'>")
    if p["conclusif"]:
        a("<div class='row'><b>Les trois verrous sont franchis.</b>"
          "<span class='tag t-ok'>VERDICT DISPONIBLE</span></div>"
          "<div class='note'>Le tableau ci-dessous n'est plus une attente : c'est une mesure.</div>")
    elif p["eta_verdict_s"] is None:
        a("<div class='row'><b>ETA : inconnu</b><span class='tag t-warn'>AUCUN DEBIT OBSERVE</span></div>"
          "<div class='note'>Aucun fill a la borne DERRIERE pour l'instant. On n'extrapole pas "
          "depuis rien — ce serait exactement le genre de chiffre invente qu'on vient de retirer "
          "du moteur.</div>")
    else:
        ok = p["verdict_atteignable_dans_la_fenetre"]
        a("<div class='row'><b>ETA du verdict : %s</b><span class='tag %s'>%s</span></div>"
          % (_duree(p["eta_verdict_s"]),
             "t-ok" if ok else "t-bad",
             "TIENT DANS LA FENETRE" if ok else "LES 4 H NE SUFFIRONT PAS"))
        a("<div class='note'>Calcule sur le debit <b class='hl'>reellement observe</b> "
          "(%.2f fill/min a la borne DERRIERE), pas sur un espoir. Il manque %d fills sur les %d "
          "requis pour conclure.</div>"
          % (p["debit_fills_par_min"],
             max(0, MIN_TRADES_POUR_CONCLURE - p["fills_derriere"]), MIN_TRADES_POUR_CONCLURE))
        if not ok:
            a("<div class='note'>👉 A ce debit, il faudrait <b class='hl'>%s d'ecoute au total</b>. "
              "Ce n'est pas une panne : c'est KAITO qui nous dit qu'il est trop peu echange pour "
              "qu'un market maker y trouve du volume.</div>"
              % _duree(ecoule + p["eta_verdict_s"]))
    a("</div>")

    # ---------------------------------------------------------------- les bornes
    a("<h2>5 · Les trois bornes de file (on n'en choisit AUCUNE)</h2>")
    if verdict is None or not verdict.bornes:
        a("<div class='card'><span class='tag t-warn'>PAS ENCORE MESURABLE</span>"
          "<div class='note'>%s</div></div>"
          % html.escape(verdict.verdict if verdict else "aucune donnee"))
    else:
        a("<div class='card'><table><tr><th>Place dans la file</th><th>Seuil</th><th>Fills</th>"
          "<th>Selection adverse</th><th>Net bps [IC 90%]</th><th>Plafond $/h</th>"
          "<th>Verdict</th></tr>")
        for b in verdict.bornes:
            adv = "—" if b.adverse_bps is None else (
                "%+.1f bps <span class='n'>[%+.1f ; %+.1f]</span>"
                % (b.adverse_bps, b.adverse_ic_bas, b.adverse_ic_haut))
            net = "—" if b.net_bps is None else (
                "<b>%+.1f</b> <span class='n'>[%+.1f ; %+.1f]</span>"
                % (b.net_bps, b.net_ic_bas, b.net_ic_haut))
            pnl = "—" if b.pnl_max_par_h_usd is None else "%.3f" % b.pnl_max_par_h_usd
            cls = ("t-ok" if b.verdict.startswith("CANDIDAT")
                   else "t-bad" if "PERDANT" in b.verdict else "t-warn")
            court = b.verdict.split(" (")[0].split(" --")[0][:34]
            a("<tr><td><b>%s</b></td><td class='n'>%.0f $</td><td>%d</td><td>%s</td><td>%s</td>"
              "<td>%s</td><td><span class='tag %s'>%s</span></td></tr>"
              % (b.nom, b.seuil_notionnel_usd, b.n_fills, adv, net, pnl, cls,
                 html.escape(court)))
        a("</table>")
        a("<div class='note'><b class='hl'>DERRIERE</b> est notre place : un retail sans "
          "colocation n'est rempli que par les gros trades — ceux qui balayent la file. "
          "Et les gros trades sont les plus informes. C'est la borne qui tranche.</div></div>")

        if verdict.adverse_cote_buy_bps is not None or verdict.adverse_cote_sell_bps is not None:
            a("<div class='card'><b>Toxicite par cote</b> — le bid et l'ask ne se valent pas."
              "<table style='margin-top:10px'><tr><th>Cote du maker</th><th>Selection adverse</th></tr>")
            for nom, val in (("On est SHORT (l'agresseur achete a notre ask)",
                              verdict.adverse_cote_buy_bps),
                             ("On est LONG (l'agresseur vend a notre bid)",
                              verdict.adverse_cote_sell_bps)):
                a("<tr><td>%s</td><td>%s</td></tr>"
                  % (nom, "—" if val is None else "%+.2f bps" % val))
            a("</table></div>")

    # ---------------------------------------------------------------- l'equation
    a("<h2>6 · Pourquoi ce verdict ne depend d'aucun nombre invente</h2><div class='card'>")
    a("<div class='eq'>net_bps = capture − frais − selection_adverse     "
      "← <b>ne contient PAS</b> d'hypothese de file\n"
      "pnl_h   = volume × part_du_flux × net_bps / 10 000   ← elle, si</div>")
    a("<div class='note'>Le <b class='hl'>signe</b> du verdict — « le market making a-t-il un "
      "edge ? » — ne depend donc <b class='hl'>pas</b> du « 10 % du flux » qu'on avait invente. "
      "Pour les dollars, on ne devine plus : on affiche le <b class='hl'>plafond physique</b> "
      "(100 % du flux qui nous atteint — impossible en pratique, donc le reel sera plus bas).</div>")
    a("</div>")

    # ---------------------------------------------------------------- contexte
    autres = _autres_marches()
    if autres:
        a("<h2>7 · KAITO face aux autres marches ecoutes</h2><div class='card'><table>"
          "<tr><th>Marche</th><th>Trades LIVE</th><th>Avancement vers 300 fills</th></tr>")
        for coin, n in autres:
            pct = min(100.0, 100.0 * n / MIN_TRADES_POUR_CONCLURE)
            fort = " style='color:var(--acc)'" if coin == PIECE else ""
            a("<tr><td%s><b>%s</b></td><td>%d</td><td>%s</td></tr>"
              % (fort, html.escape(coin), n, _bar(pct, pct >= 100)))
        a("</table><div class='note'>Rappel : ces trades LIVE sont le flux TOTAL. La borne "
          "DERRIERE n'en retient que le quart superieur — le seul qui nous remplirait.</div></div>")

    a("<div class='foot'>Aucun ordre reel · aucun argent reel · aucune cle privee · "
      "aucune signature · aucun depot/retrait. Les seuls messages sortants sont des "
      "<code>subscribe</code> au canal public <code>trades</code>.</div>")
    a("</div></body></html>")
    return "".join(o)


# ===================================================================== le serveur

def servir(port: int = PORT) -> int:  # pragma: no cover  (I/O reseau local)
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                page = rendre_html().encode("utf-8")
            except Exception as exc:
                page = ("<pre>erreur : %s</pre>" % html.escape(str(exc))).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", port), H)
    print("\n  Page KAITO : http://127.0.0.1:%d/" % port)
    print("  (lecture seule -- elle ne fait que LIRE les fichiers deja enregistres)")
    print("  Ferme cette fenetre pour arreter la page.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main() -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="ecrit un HTML statique et sort")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()
    if args.once:
        p = ROOT / "PROGRESSION-KAITO.html"
        p.write_text(rendre_html(), encoding="utf-8")
        print("ecrit : %s" % p)
        return 0
    return servir(args.port)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
