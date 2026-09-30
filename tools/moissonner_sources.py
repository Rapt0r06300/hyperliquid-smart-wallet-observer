r"""LES SOURCES — *arXiv, Hacker News, quant.stackexchange, et X (si jeton).*

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUE CET OUTIL EST, ET CE QU'IL REFUSE D'ETRE
═══════════════════════════════════════════════════════════════════════════════════════════════

Flo veut chercher **des posts X** sur *« les meilleures methodes de grinder et sniper »*.

    🔴 **Ce corpus est exactement celui que ce projet a PROUVE sans valeur.**
        le **grinder** : **0/29** meme a **100 %% de fill**. Et **HLP -- le MM *paye* par le
                         protocole -- rend -0,01 %% APR.**
        le **sniper**  : **-7,97 bps a cout ZERO**, 24 133 signaux OOS.

Alors cet outil ne cherche pas « les meilleures methodes ». **Il cherche des PREUVES.**

    Un post qui promet **+300 %%**                        -> **score NEGATIF**, ecarte.
    Un post qui dit « on a perdu, voici la formule       -> **garde**.
      et le chiffre »

    ***Le filtre ne demande pas D'OU ca vient. Il demande CE QUE CA PROUVE.***

Et il ajoute les sources qui, elles, contiennent vraiment quelque chose :
**arXiv** (la source des formules, gratuite), **HN**, **quant.stackexchange**.

🔒 100 %% LECTURE SEULE. Aucun ordre reel. Rien de payant.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research.scan_resilience import (  # noqa: E402
    ABANDONNER,
    ATTENDRE,
    REESSAYER,
    Blessures,
    decider,
)
from hl_observer.research.sources import (  # noqa: E402
    catalogue,
    juger,
    rapport_sources,
)

SORTIE = RACINE / "data" / "reports" / "moisson_sources.json"
ETAT = RACINE / "data" / "reports" / "sources_etat.json"

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LES REQUETES — **derivees de nos trous mesures**, pas de mots a la mode.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
REQUETES_ARXIV = [
    ('cat:q-fin.TR AND abs:"limit order book"', "le carnet -- on lit des snapshots, on ne REJOUE rien"),
    ('cat:q-fin.TR AND abs:"market making"', "le MM est mort chez nous (0/29) -- POURQUOI, exactement ?"),
    ('abs:"queue position" AND abs:"fill probability"', "notre fill maker est un CHIFFRE INVENTE"),
    ('abs:"adverse selection" AND abs:"market maker"', "le maker est rempli QUAND IL A TORT"),
    ('abs:"market impact" AND abs:"square root"', "l'hypothese qui expliquerait nos -7,97 bps"),
    ('abs:"funding rate" AND abs:"perpetual"', "le carry -- NOTRE SEULE piste positive"),
    ('abs:"basis trade" OR abs:"cash and carry"', "idem"),
    ('abs:"liquidation" AND abs:"cascade"', "LA DERNIERE PISTE NON MESUREE"),
    ('abs:"backtest overfitting" OR abs:"deflated Sharpe"', "nos 1 425 000 scenarios : combien d'overfit ?"),
    ('abs:"purged cross-validation" OR abs:"embargo"', "notre coupe train/test FUYAIT (68 %)"),
    ('abs:"order flow imbalance" OR abs:"VPIN"', "branche hier, AUCUNE validation externe"),
    ('abs:"optimal execution" AND abs:"transaction cost"', "l'edge net apres couts -- notre seul juge"),
]

REQUETES_HN = [
    ("hyperliquid", "notre venue"),
    ("market making crypto lost money", "🔑 ceux qui AVOUENT -- le seul signal fiable"),
    ("hft backtest overfitting", "nos garde-fous anti-overfit avaient ZERO appelant"),
    ("funding rate arbitrage", "le carry"),
    ("perpetual futures basis trade", "idem"),
    ("order book queue position", "le fill invente"),
    ("why my trading bot failed", "🔑 les post-mortem valent 100 promesses"),
    ("market maker adverse selection", "rempli quand on a tort"),
]

REQUETES_SE = [
    ("queue position fill probability", "le fill invente"),
    ("avellaneda stoikov inventory", "le terme d'inventaire -- ce qui manquait au grinder"),
    ("funding rate arbitrage perpetual", "le carry"),
    ("market impact model", "les -7,97 bps"),
    ("backtest overfitting deflated sharpe", "1 425 000 scenarios"),
    ("adverse selection market making", "rempli quand on a tort"),
]

# 🚨 X — *on ne cherche PAS « les meilleures methodes ». On cherche des AVEUX et des CHIFFRES.*
REQUETES_X = [
    ("hyperliquid funding rate bps -is:retweet", "le carry, avec un CHIFFRE"),
    ('"post mortem" trading bot -is:retweet', "🔑 ceux qui AVOUENT"),
    ('"didn\'t work" market making -is:retweet', "🔑 idem"),
    ("adverse selection maker fill -is:retweet", "rempli quand on a tort"),
    ("liquidation cascade perp -is:retweet", "la derniere piste"),
    ('"after fees" pnl backtest -is:retweet', "🔑 l'edge NET, pas le brut"),
]


def _appel(url: str, entetes: dict[str, str], bless: Blessures, cle: str) -> str | None:
    """🔒 **NE MEURT JAMAIS. NE MENT JAMAIS.** Toute blessure est comptee et publiee."""
    essai = 0
    while True:
        statut: int | None = None
        after = None
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=entetes), timeout=30.0
            ) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            statut = exc.code
            try:
                after = float(exc.headers.get("Retry-After") or 0) or None
            except (TypeError, ValueError):
                after = None
        except Exception:  # noqa: BLE001
            statut = None

        d = decider(statut, essai=essai, retry_after=after)
        bless.note(cle, d)
        if d.action == ABANDONNER:
            return None
        if d.action in (ATTENDRE, REESSAYER):
            print("     ⏳ %s" % d.raison)
            time.sleep(min(d.attente_s, 900.0))
            essai += 1


def _texte_arxiv(xml: str) -> list[tuple[str, str, str]]:
    """(titre, resume, lien). *Parsing minimal : on ne depend d'aucune lib externe.*"""
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        t = re.search(r"<title>(.*?)</title>", e, re.S)
        s = re.search(r"<summary>(.*?)</summary>", e, re.S)
        u = re.search(r"<id>(.*?)</id>", e, re.S)
        if t and s:
            out.append((" ".join(t.group(1).split()),
                        " ".join(s.group(1).split()),
                        (u.group(1).strip() if u else "")))
    return out


def main() -> int:  # noqa: C901, PLR0912, PLR0915
    ap = argparse.ArgumentParser(description="Moissonner arXiv / HN / StackExchange / X")
    ap.add_argument("--minutes", type=float, default=20.0)
    args = ap.parse_args()

    jg = os.environ.get("GITHUB_TOKEN", "").strip()
    jx = os.environ.get("X_BEARER_TOKEN", "").strip()
    srcs = {s.nom: s for s in catalogue(jeton_github=jg, jeton_x=jx)}

    print("=" * 100)
    print("  LES SOURCES — *le meme filtre partout. Il ne demande pas D'OU ca vient.*")
    print("=" * 100)

    r = rapport_sources(list(srcs.values()))
    print("\n  disponibles : %s" % ", ".join(r["disponibles"]))
    for nom, pq in r["indisponibles"].items():
        print("\n  🔴 **%s : INDISPONIBLE**" % nom)
        print("     %s" % pq)
    print("\n  %s" % r["note_x"])

    bless = Blessures()
    gardes: list[dict[str, Any]] = []
    ecartes = 0
    debut = time.time()
    limite = args.minutes * 60.0

    def _fini() -> bool:
        if time.time() - debut > limite:
            print("\n  ⏹️ budget atteint. *On ecrit ce qu'on a. Rien n'est perdu.*")
            return True
        return False

    # ── arXiv — 🔑 la source des FORMULES. Gratuite, ouverte. ─────────────────────────────────
    print("\n" + "-" * 100)
    print("  arXiv — 🔑 **la source des FORMULES** (gratuite, ouverte, relue par des pairs)")
    print("-" * 100)
    for q, pourquoi in REQUETES_ARXIV:
        if _fini():
            break
        url = ("http://export.arxiv.org/api/query?search_query=%s&max_results=40"
               "&sortBy=submittedDate&sortOrder=descending" % urllib.parse.quote(q))
        xml = _appel(url, {"User-Agent": "hypersmart-research"}, bless, "arxiv|%s" % q)
        time.sleep(3.5)                        # arXiv demande 3 s entre deux appels. On respecte.
        if not xml:
            continue
        n = 0
        for titre, resume, lien in _texte_arxiv(xml):
            v = juger(titre + " " + resume, source=srcs["arxiv"])
            if v.garde:
                gardes.append({"source": "arxiv", "titre": titre, "lien": lien,
                               "pourquoi_cherche": pourquoi, **v.as_dict()})
                n += 1
            else:
                ecartes += 1
        print("  %-56s +%d" % (q[:56], n))

    # ── Hacker News — les COMMENTAIRES y sont souvent plus honnetes que les posts ─────────────
    print("\n" + "-" * 100)
    print("  Hacker News — *quelqu'un vient TOUJOURS dire pourquoi ca ne marche pas*")
    print("-" * 100)
    for q, pourquoi in REQUETES_HN:
        if _fini():
            break
        url = ("https://hn.algolia.com/api/v1/search?query=%s&hitsPerPage=50"
               % urllib.parse.quote(q))
        t = _appel(url, {"User-Agent": "hypersmart-research"}, bless, "hn|%s" % q)
        time.sleep(1.2)
        if not t:
            continue
        try:
            hits = json.loads(t).get("hits") or []
        except Exception:  # noqa: BLE001
            continue
        n = 0
        for h in hits:
            txt = " ".join(str(h.get(k) or "") for k in ("title", "story_text", "comment_text"))
            v = juger(txt, source=srcs["hackernews"])
            if v.garde:
                gardes.append({
                    "source": "hackernews", "titre": (h.get("title") or txt[:90]),
                    "lien": "https://news.ycombinator.com/item?id=%s" % h.get("objectID"),
                    "pourquoi_cherche": pourquoi, **v.as_dict()})
                n += 1
            else:
                ecartes += 1
        print("  %-56s +%d" % (q[:56], n))

    # ── quant.stackexchange — *un corpus qui se contredit lui-meme est un corpus qui se corrige* ─
    print("\n" + "-" * 100)
    print("  quant.stackexchange — *les reponses y sont NOTEES et CONTESTEES*")
    print("-" * 100)
    for q, pourquoi in REQUETES_SE:
        if _fini():
            break
        url = ("https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=votes"
               "&q=%s&site=quant&filter=withbody&pagesize=30" % urllib.parse.quote(q))
        t = _appel(url, {"User-Agent": "hypersmart-research",
                         "Accept-Encoding": "identity"}, bless, "se|%s" % q)
        time.sleep(1.5)
        if not t:
            continue
        try:
            items = json.loads(t).get("items") or []
        except Exception:  # noqa: BLE001
            continue
        n = 0
        for it in items:
            txt = "%s %s" % (it.get("title") or "", it.get("body") or "")
            v = juger(txt, source=srcs["stackexchange_quant"])
            if v.garde:
                gardes.append({"source": "stackexchange", "titre": it.get("title"),
                               "lien": it.get("link"), "pourquoi_cherche": pourquoi,
                               **v.as_dict()})
                n += 1
            else:
                ecartes += 1
        print("  %-56s +%d" % (q[:56], n))

    # ── X — 🚨 seulement si Flo fournit un jeton. **Sinon on le DIT.** ────────────────────────
    print("\n" + "-" * 100)
    print("  X / Twitter")
    print("-" * 100)
    if not srcs["x_twitter"].disponible:
        print("  🔴 **INDISPONIBLE** — %s" % srcs["x_twitter"].pourquoi_indisponible)
        print("\n  🚩 **Et honnetement : ce n'est pas une grande perte.**")
        print("     *Le grinder est mort (0/29 a 100 %% de fill). Le sniper est mort (-7,97 bps")
        print("      a cout ZERO). X est la source la plus dense au monde en promesses sur ces")
        print("      deux-la — et une capture de PnL est du **biais du survivant** : tu vois")
        print("      celui qui a gagne, jamais les mille qui ont perdu avec la meme methode.*")
    else:
        ent = {"Authorization": "Bearer %s" % jx, "User-Agent": "hypersmart-research"}
        for q, pourquoi in REQUETES_X:
            if _fini():
                break
            url = ("https://api.x.com/2/tweets/search/recent?query=%s&max_results=100"
                   "&tweet.fields=public_metrics,created_at" % urllib.parse.quote(q))
            t = _appel(url, ent, bless, "x|%s" % q)
            time.sleep(2.0)
            if not t:
                continue
            try:
                data = json.loads(t).get("data") or []
            except Exception:  # noqa: BLE001
                continue
            n = 0
            for tw in data:
                v = juger(str(tw.get("text") or ""), source=srcs["x_twitter"])
                if v.garde:
                    gardes.append({"source": "x", "titre": str(tw.get("text"))[:110],
                                   "lien": "https://x.com/i/status/%s" % tw.get("id"),
                                   "pourquoi_cherche": pourquoi, **v.as_dict()})
                    n += 1
                else:
                    ecartes += 1
            print("  %-56s +%d  (%d ecartes)" % (q[:56], n, len(data) - n))

    # ── LE RESULTAT ───────────────────────────────────────────────────────────────────────────
    gardes.sort(key=lambda x: -float(x.get("score") or 0))
    par_source: dict[str, int] = {}
    for g in gardes:
        par_source[g["source"]] = par_source.get(g["source"], 0) + 1

    print("\n" + "=" * 100)
    print("  RESULTAT")
    print("=" * 100)
    print("\n  gardes : **%d**  ·  ecartes : %d" % (len(gardes), ecartes))
    for s, n in sorted(par_source.items(), key=lambda x: -x[1]):
        print("     %-16s %d" % (s, n))

    if not gardes:
        print("\n  ⚪ **Rien de gardable.** *Ce n'est pas une panne : le corpus n'a rien prouve.*")

    print("\n  " + bless.rapport().replace("\n", "\n  "))

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps({
        "gardes": gardes, "n_ecartes": ecartes,
        "par_source": par_source,
        "sources": rapport_sources(list(srcs.values())),
        "blessures": bless.as_dict(),
        "lecture_seule": True, "real_execution": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n  -> %s" % SORTIE)
    print("\n  🔒 Lecture seule. Rien de payant. Aucun ordre reel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
