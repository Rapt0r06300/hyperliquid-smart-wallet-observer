r"""#3 #4 #7 #10 — nos MORTS · la DÉDUP entre sources · le MÉTA-classement · le RETOUR.

Quatre briques qui rendent le tri **plus honnête** et **plus utile**, sans réseau.

PUR : aucun réseau. Aucun ordre réel.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #3 — NOS MORTS. *Ne jamais faire relire ce qu'on a déjà mesuré MORT.*
#
#   Le moissonneur ne connaissait pas notre propre cimetière. S'il trouve un beau papier de
#   market making, il doit **automatiquement** afficher le certificat de décès.
#   ***Le contradicteur (#14) est une chose ; relire une idée qu'on a déjà réfutée en est une
#      autre — et c'est du temps perdu.***
# ═══════════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class Mort:
    idee: str
    verdict: str          # le chiffre qui l'a tuée
    motifs: tuple[str, ...]


CIMETIERE: tuple[Mort, ...] = (
    Mort("market making retail",
         "T1b : **0/29 même à 100 % de fill** (la borne la plus généreuse). Et **HLP — le MM "
         "*payé* par le protocole — rend −0,01 % APR.**",
         (r"market\s*mak", r"avellaneda", r"stoikov", r"\bglft\b", r"optimal\s*spread",
          r"inventory\s*skew")),
    Mort("copy-trading / smart money",
         "**−7,97 bps à coût ZÉRO** sur 24 133 signaux OOS. *Le leader est **contrarien**, pas "
         "informé.*",
         (r"copy[\s-]?trad", r"smart\s*money", r"mirror\s*trad", r"whale\s*(track|watch|copy)",
          r"leader\s*follow")),
    Mort("funding perp↔perp",
         "**0/120** (X-04). *Couvrir avec un AUTRE actif ne change RIEN.*",
         (r"funding.{0,20}between.{0,20}(exchange|venue|perp)",
          r"cross[\s-]?exchange.{0,15}funding", r"perp.{0,10}perp.{0,15}arb")),
    Mort("lead-lag BTC→alts",
         "**0/66.** *Les alts bougent AVEC BTC (corr(0)=+0,83), ils ne le SUIVENT pas. Une "
         "corrélation contemporaine ne se trade pas.*",
         (r"lead[\s-]?lag", r"bitcoin.{0,15}(lead|predict).{0,15}alt",
          r"altcoin.{0,15}follow.{0,15}bitcoin")),
    Mort("le mempool pour copier",
         "Le prix court **CONTRE** le leader **AVANT** son fill (−7,75 bps). *Voir son ordre plus "
         "tôt nous met plus PROFONDÉMENT dans le mouvement adverse.*",
         (r"mempool.{0,20}copy", r"front[\s-]?run.{0,15}(leader|whale|copy)",
          r"see.{0,15}order.{0,15}before.{0,15}(execut|fill)")),
    Mort("MM sur HIP-3 (frais ÷10)",
         "Le growth mode franchit la porte des COÛTS mais **la porte de l'INVENTAIRE reste "
         "fermée : ratio 0,20 (il faut ≥ 1,0)**. *Diviser les frais par 10 ne touche pas le "
         "terme qui tue.*",
         (r"hip-?3.{0,20}market\s*mak", r"growth\s*mode.{0,20}fee",
          r"reduced\s*fee.{0,20}market\s*mak")),
)


@dataclass(frozen=True, slots=True)
class Certificat:
    idee_morte: str
    verdict: str
    extrait: str

    def as_dict(self) -> dict[str, Any]:
        return {"idee_deja_morte_chez_nous": self.idee_morte, "notre_verdict": self.verdict,
                "extrait_qui_a_declenche": self.extrait}


def deja_mort(texte: str) -> list[Certificat]:
    """Ce texte ressuscite-t-il une idée qu'on a **déjà mesurée morte** ? Renvoie les certificats."""
    t = texte or ""
    out: list[Certificat] = []
    for m in CIMETIERE:
        for mot in m.motifs:
            x = re.search(mot, t, re.IGNORECASE)
            if x:
                a, b = max(0, x.start() - 40), min(len(t), x.end() + 40)
                out.append(Certificat(m.idee, m.verdict, " ".join(t[a:b].split())))
                break
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #4 — LA DÉDUP ENTRE SOURCES. *Le même papier sur 4 sources = UNE idée, pas quatre.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
_PONCT = re.compile(r"[^a-z0-9 ]+")
_ESP = re.compile(r"\s+")
_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", re.IGNORECASE)
_ARXIV = re.compile(r"(\d{4}\.\d{4,5})")
_STOP_TITRE = frozenset("""
a an the of and or for to in on with from that this is are be as at by we our via using toward
towards new novel approach method model framework study paper analysis
""".split())


def _norm_titre(t: str) -> str:
    s = _PONCT.sub(" ", (t or "").lower())
    mots = [w for w in _ESP.sub(" ", s).split() if w not in _STOP_TITRE and len(w) > 2]
    return " ".join(sorted(mots))          # trié -> insensible a l'ordre des mots


def _empreinte(item: Mapping[str, Any]) -> str:
    """L'identité **stable** d'un papier : DOI > titre normalisé.

    🔴 **BUG ATTRAPÉ PAR LE TEST** : au début, j'utilisais aussi l'**arXiv id**. Mais seul le
    lien *arXiv* contient cet id — le même papier sur OpenAlex/S2/PapersWithCode ne l'a pas.
    Résultat : l'entrée arXiv était clé par `arxiv:...` et les autres par `titre:...` → **elles
    ne fusionnaient PAS**. ***Un identifiant qui ne se trouve que sur UNE source FRAGMENTE au
    lieu de dédupliquer.*** Le **titre normalisé** est la vraie clé commune ; le DOI (global)
    l'emporte quand il est là.
    """
    blob = "%s %s" % (item.get("lien") or "", item.get("titre") or "")
    d = _DOI.search(blob)
    if d:
        return "doi:" + d.group(0).lower()
    nt = _norm_titre(str(item.get("titre") or ""))
    return "titre:" + nt if nt else "vide:%d" % id(item)


@dataclass(slots=True)
class Fusion:
    representant: dict[str, Any]
    sources: list[str] = field(default_factory=list)
    doublons: int = 0


def dedupliquer_idees(items: Sequence[Mapping[str, Any]]) -> list[Fusion]:
    """Regroupe **le même travail** trouvé sur plusieurs sources. On n'en garde **qu'un**.

    *Sinon le .md liste le même papier 4× (arXiv + OpenAlex + S2 + PapersWithCode).*
    """
    par: dict[str, Fusion] = {}
    for it in items:
        e = _empreinte(it)
        src = str(it.get("source") or "?")
        if e not in par:
            f = Fusion(dict(it), [src], 0)
            par[e] = f
        else:
            f = par[e]
            f.doublons += 1
            if src not in f.sources:
                f.sources.append(src)
            # on garde le mieux score / le plus cité comme representant
            if float(it.get("score") or 0) > float(f.representant.get("score") or 0):
                gardees = f.sources
                f.representant = dict(it)
                f.sources = gardees
    for f in par.values():
        f.representant["_trouve_sur"] = f.sources
        f.representant["_doublons_fusionnes"] = f.doublons
    return sorted(par.values(), key=lambda f: -float(f.representant.get("score") or 0))


def lier_repo_et_papier(repos: Sequence[str],
                        papiers: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """🔑 Un repo qui **implémente** un papier trouvé -> *« la théorie ET le code »*.

    Heuristique : le nom du repo apparaît dans le titre/lien du papier, ou l'inverse.
    """
    liens: list[dict[str, str]] = []
    for r in repos:
        court = r.split("/")[-1].lower().replace("-", "").replace("_", "")
        if len(court) < 5:
            continue
        for p in papiers:
            blob = ("%s %s" % (p.get("titre") or "", p.get("lien") or "")).lower()
            if court in blob.replace("-", "").replace("_", ""):
                liens.append({"repo": r, "papier": str(p.get("titre") or ""),
                              "lien": str(p.get("lien") or "")})
                break
    return liens


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #7 — LE MÉTA-CLASSEMENT. *« Si tu ne fais qu'UNE chose, fais celle-ci. »*
#
#   Le score classe par NOUVEAUTÉ. Il ne dit pas quoi faire EN PREMIER. On croise :
#     gravité de NOTRE trou  ×  nouveauté  ×  faible effort
# ═══════════════════════════════════════════════════════════════════════════════════════════════
# gravité : à quel point ce trou nous fait mal (mesuré, pas supposé)
GRAVITE: dict[str, float] = {
    "kappa_fill": 1.0,        # notre fill est un chiffre INVENTÉ -> tout le MM en dépend
    "queue_position": 0.9,
    "lookahead": 1.0,         # notre coupe train/test FUYAIT (68 %)
    "parite": 0.95,           # le meta-test qui juge tous les autres
    "impact": 0.8,            # l'hypothèse des −7,97 bps
    "carry": 0.85,            # notre SEULE piste positive -> l'améliorer vaut de l'or
    "liquidation": 0.7,       # dernière piste non mesurée
    "adverse": 0.6,
    "execution": 0.4,
    "inventaire": 0.2,        # le MM est mort -> INSPIRE_ONLY
}
# effort : 1 = facile, 0 = lourd (dérivé du "coût" des fiches)
FACILITE: dict[str, float] = {
    "kappa_fill": 0.7, "queue_position": 0.4, "lookahead": 0.6, "parite": 0.7,
    "impact": 0.7, "carry": 0.5, "liquidation": 0.3, "adverse": 0.7,
    "execution": 0.7, "inventaire": 1.0,
}


@dataclass(frozen=True, slots=True)
class Priorite:
    cle: str
    priorite: float
    gravite: float
    nouveaute: float
    facilite: float
    pourquoi: str

    def as_dict(self) -> dict[str, Any]:
        return {"cle": self.cle, "priorite": round(self.priorite, 3),
                "gravite": self.gravite, "nouveaute_etayage": self.nouveaute,
                "facilite": self.facilite, "pourquoi": self.pourquoi}


def prioriser(idees: Sequence[Mapping[str, Any]]) -> list[Priorite]:
    """`idees` = fiches (`cle`, `sources`...). Classe par **impact actionnable**, pas nouveauté."""
    out: list[Priorite] = []
    n_max = max((len(i.get("sources") or []) for i in idees), default=1) or 1
    for i in idees:
        cle = str(i.get("cle"))
        g = GRAVITE.get(cle, 0.3)
        f = FACILITE.get(cle, 0.5)
        nouv = len(i.get("sources") or []) / n_max      # bien étayée = mesure plus fiable
        pr = g * (0.5 + 0.5 * nouv) * (0.4 + 0.6 * f)
        pq = ("gravité de notre trou **%.2f** × étayage %.2f × facilité %.2f" % (g, nouv, f))
        if cle == "inventaire":
            pq = "🔒 **NE PAS FAIRE** — le MM est mort (T1b 0/29). *Priorité basse VOULUE.*"
        out.append(Priorite(cle, pr, g, round(nouv, 2), f, pq))
    return sorted(out, key=lambda p: -p.priorite)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #10 — LE RETOUR. *Un canari qui APPREND, au lieu d'un canari figé.*
#
#   Après avoir lu une idée, Flo (ou moi) la marque « utile » / « du vent ». On stocke ça et on
#   ajuste les poids au prochain run. *La mesure, encore : on ne devine pas ce qui marche.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
def charger_retours(chemin: Path) -> dict[str, float]:
    """concept -> ajustement de poids (∈ [-1, +1]). Absent -> **rien**, jamais une devinette."""
    if not chemin.exists():
        return {}
    try:
        d = json.loads(chemin.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, float] = {}
    for r in d.get("retours", []) if isinstance(d, dict) else []:
        c = str(r.get("concept") or "")
        v = r.get("verdict")
        if not c:
            continue
        delta = 0.15 if v in ("utile", "good", "ok", True) else \
                (-0.20 if v in ("vent", "junk", "bad", False) else 0.0)
        out[c] = max(-1.0, min(1.0, out.get(c, 0.0) + delta))
    return out


def enregistrer_retour(chemin: Path, concept: str, verdict: str) -> None:
    """*On ACCUMULE les jugements humains — ils valent mieux que mes poids devinés.*"""
    d: dict[str, Any] = {"retours": []}
    if chemin.exists():
        try:
            d = json.loads(chemin.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            d = {"retours": []}
    d.setdefault("retours", []).append({"concept": concept, "verdict": verdict})
    chemin.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def appliquer_retours(score: float, concept: str, retours: Mapping[str, float]) -> float:
    """*Le score s'ajuste de ce que l'humain a constaté — mais reste borné.*"""
    return score * (1.0 + retours.get(concept, 0.0))


__all__ = [
    "CIMETIERE", "FACILITE", "GRAVITE",
    "Certificat", "Fusion", "Mort", "Priorite",
    "appliquer_retours", "charger_retours", "deja_mort", "dedupliquer_idees",
    "enregistrer_retour", "lier_repo_et_papier", "prioriser",
]
