r"""#7 #8 #9 #10 #11 #13 #14 — LE MOTEUR : cache, dédup, budget, graphe social, contradiction.

═══════════════════════════════════════════════════════════════════════════════════════════════
#7 — SÉPARER LA **COLLECTE** DU **JUGEMENT**.  *La plus rentable des sept.*
═══════════════════════════════════════════════════════════════════════════════════════════════

Aujourd'hui, améliorer le filtre = **tout re-télécharger**. C'est absurde : le texte n'a pas
changé, **c'est notre jugement qui change.**

    -> **CACHE BRUT** sur disque (le texte intégral, jamais le verdict).
    -> on peut **re-juger les 5 617 repos en 10 secondes, hors ligne**, chaque fois qu'on
       améliore le filtre.

    ***C'est ce qui rend les quatorze autres idées presque gratuites.***

═══════════════════════════════════════════════════════════════════════════════════════════════
#8 — DÉDUPLIQUER PAR **SIMILARITÉ DE CODE**, pas par nom.
═══════════════════════════════════════════════════════════════════════════════════════════════

Le corpus crypto est plein de forks déguisés et de copier-coller. Sans ça, **on lit trente fois
le même bot en croyant lire trente idées.**

MinHash sur des **shingles de code normalisé** (variables renommées, espaces écrasés) : deux
repos qui partagent 80 % de leurs empreintes sont **le même code**.

═══════════════════════════════════════════════════════════════════════════════════════════════
#9 — LE BUDGET **ADAPTATIF**.  *Le quota est notre ressource rare.*
═══════════════════════════════════════════════════════════════════════════════════════════════

Distribuer le quota également entre toutes les requêtes, c'est **saupoudrer**. Un scan de trois
heures doit **apprendre en cours de route** où creuser (UCB1).

    ***Une ressource rare se pilote, elle ne se saupoudre pas.***

═══════════════════════════════════════════════════════════════════════════════════════════════
#10 / #11 — LE GRAPHE SOCIAL. Qui **CITE** ce repo · suivre les **AUTEURS**.
#13        — LA CHRONOLOGIE : les repos nés **juste après** un changement de protocole.
#14        — 🔴 CHERCHER CE QUI NOUS DONNE **TORT**.
═══════════════════════════════════════════════════════════════════════════════════════════════

    ***Un corpus qui ne contient que ce qui nous conforte est un corpus qu'on a CHOISI.***

Et on est **armés** pour juger les contradicteurs : T1b (0/29 à 100 % de fill) et HLP (le MM
**payé** rend −0,01 % APR) sont des massues. **S'ils y survivent, on a raté quelque chose
d'énorme — et il faut le savoir.**

PUR : aucun réseau. Lecture seule.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #7 — LE CACHE BRUT. *On garde le TEXTE, jamais le verdict.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
class CacheBrut:
    """Le texte **intégral**, sur disque. **Jamais le jugement.**

    ***La distinction est tout le point :*** le texte est un **fait** (il ne change pas), le
    verdict est une **opinion** (elle change à chaque fois qu'on améliore le filtre).
    *Cacher un verdict, c'est figer une opinion. Cacher un texte, c'est garder un fait.*
    """

    def __init__(self, racine: Path) -> None:
        self.racine = racine
        self.racine.mkdir(parents=True, exist_ok=True)

    def _chemin(self, cle: str) -> Path:
        h = hashlib.sha256(cle.encode("utf-8")).hexdigest()[:20]
        return self.racine / ("%s.json" % h)

    def lire(self, cle: str, *, max_age_s: float | None = None) -> str | None:
        p = self._chemin(cle)
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        if d.get("cle") != cle:
            return None                      # collision -> **on ne devine pas**
        if max_age_s is not None and (time.time() - float(d.get("t", 0))) > max_age_s:
            return None
        return str(d.get("texte") or "")

    def ecrire(self, cle: str, texte: str) -> None:
        self._chemin(cle).write_text(
            json.dumps({"cle": cle, "t": time.time(), "texte": texte}, ensure_ascii=False),
            encoding="utf-8",
        )

    def tout(self) -> dict[str, str]:
        """🔑 **Re-juger le corpus entier, hors ligne, en 10 secondes.**"""
        out: dict[str, str] = {}
        for p in self.racine.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if d.get("cle"):
                    out[str(d["cle"])] = str(d.get("texte") or "")
            except Exception:  # noqa: BLE001
                continue
        return out

    def taille(self) -> int:
        return sum(1 for _ in self.racine.glob("*.json"))


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #8 — LA DÉDUPLICATION PAR SIMILARITÉ DE CODE (MinHash).
# ═══════════════════════════════════════════════════════════════════════════════════════════════
N_EMPREINTES = 64
TAILLE_SHINGLE = 5
SEUIL_JUMEAU = 0.72          # au-delà : **c'est le même code**

_NORM = (
    (re.compile(r"#.*$|//.*$", re.M), " "),          # les commentaires ne sont pas du code
    (re.compile(r'"""[\s\S]*?"""'), " "),
    (re.compile(r'"[^"\n]*"|\'[^\'\n]*\''), " S "),  # les chaînes -> un jeton
    (re.compile(r"\b\d+(\.\d+)?\b"), " N "),         # les nombres -> un jeton
)

# 🔴 LES MOTS QU'ON GARDE — ceux qui portent la **STRUCTURE**, pas le nom.
#    *Un fork renomme ses variables ; il ne réécrit pas sa grammaire.*
_STRUCTURE = frozenset("""
def class return if elif else for while in not and or is none true false lambda yield
import from as with try except finally raise assert pass break continue global nonlocal
fn let mut pub impl struct enum match use const static async await self this new
function var const let of typeof instanceof switch case do throw catch
min max sum abs len range sorted enumerate zip int float str bool list dict set tuple
print append s n
""".split())

_MOT = re.compile(r"[A-Za-z_]\w*")


def normaliser(code: str) -> str:
    r"""🔑 ***Renommer ses variables ne rend pas un fork original.***

    🔴 **BUG QUE MON PROPRE TEST A ATTRAPÉ.** La 1ʳᵉ version normalisait les **nombres** et les
    **chaînes**… **mais pas les IDENTIFIANTS**. Or renommer `compute_fill` en `calc_fill` et
    `total` en `acc` est *exactement* ce que fait un fork déguisé — et ma dédup ne voyait rien.

    -> on garde ce qui porte la **STRUCTURE** (mots-clés, opérateurs, appels standards) et on
       écrase **tout identifiant** en `V`. Deux codes de même **grammaire** deviennent identiques.

    🚩 **Le risque, dit franchement :** deux algorithmes *différents* de même structure peuvent se
       ressembler. C'est pourquoi le shingle fait **5 jetons** et le seuil est à **0,72** — et
       pourquoi un « jumeau » n'est pas supprimé, seulement **regroupé** : on lit le
       représentant, les autres restent accessibles.
    """
    t = code or ""
    for rx, rep in _NORM:
        t = rx.sub(rep, t)

    def _remplacer(m: re.Match) -> str:
        mot = m.group(0).lower()
        return mot if mot in _STRUCTURE else "V"

    t = _MOT.sub(_remplacer, t)
    return " ".join(t.split()).lower()


def empreintes(code: str, *, n: int = N_EMPREINTES, k: int = TAILLE_SHINGLE) -> set[int]:
    """MinHash : `n` plus petits hachages de shingles de `k` jetons."""
    jetons = normaliser(code).split()
    if len(jetons) < k:
        return set()
    hs = sorted(
        int(hashlib.blake2b(" ".join(jetons[i:i + k]).encode(), digest_size=8).hexdigest(), 16)
        for i in range(len(jetons) - k + 1)
    )
    return set(hs[:n])


def similarite(a: set[int], b: set[int]) -> float:
    """Jaccard. **0 si l'un des deux est vide** — *on ne déclare pas jumeaux deux inconnus.*"""
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


@dataclass(slots=True)
class Jumeaux:
    groupes: list[list[str]] = field(default_factory=list)
    representants: dict[str, str] = field(default_factory=dict)   # repo -> le repo à LIRE

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_groupes": len(self.groupes),
            "groupes": self.groupes,
            "representants": self.representants,
            "pourquoi": ("🔑 **Sans ça, on lit trente fois le même bot** en croyant lire trente "
                         "idées. *Renommer ses variables ne rend pas un fork original.*"),
        }


def dedupliquer(codes: Mapping[str, str], *, seuil: float = SEUIL_JUMEAU) -> Jumeaux:
    """Regroupe les repos **qui sont le même code**. On n'en lira **qu'un**."""
    emp = {k: empreintes(v) for k, v in codes.items()}
    noms = [k for k in codes if emp[k]]
    vus: set[str] = set()
    j = Jumeaux()

    for i, a in enumerate(noms):
        if a in vus:
            continue
        groupe = [a]
        for b in noms[i + 1:]:
            if b not in vus and similarite(emp[a], emp[b]) >= seuil:
                groupe.append(b)
                vus.add(b)
        vus.add(a)
        if len(groupe) > 1:
            j.groupes.append(groupe)
            for g in groupe:
                j.representants[g] = groupe[0]
    return j


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #9 — LE BUDGET ADAPTATIF (UCB1). *Une ressource rare se pilote.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
@dataclass
class Bandit:
    """Alloue le quota **aux requêtes qui RENDENT**. *Un scan doit apprendre en cours de route.*

    UCB1 : `moyenne + sqrt(2·ln(N) / n)`. Le second terme est **la curiosité** — il force à
    réessayer ce qu'on a peu tenté. *Sans lui, on se fige sur le premier filon et on rate le reste.*
    """
    tires: dict[str, int] = field(default_factory=dict)
    gains: dict[str, float] = field(default_factory=dict)
    total: int = 0

    def choisir(self, bras: Sequence[str]) -> str:
        """🔒 **Tout bras jamais tiré passe en premier.** *On n'écarte pas ce qu'on n'a pas essayé.*"""
        for b in bras:
            if self.tires.get(b, 0) == 0:
                return b
        return max(bras, key=lambda b: self._ucb(b))

    def _ucb(self, b: str) -> float:
        n = self.tires.get(b, 0)
        if n == 0:
            return float("inf")
        moyenne = self.gains.get(b, 0.0) / n
        curiosite = math.sqrt(2.0 * math.log(max(self.total, 1)) / n)
        return moyenne + curiosite

    def noter(self, bras: str, gain: float) -> None:
        """`gain` = nb de repos **retenus** (pas trouvés). *On récompense la qualité, pas le volume.*"""
        self.tires[bras] = self.tires.get(bras, 0) + 1
        self.gains[bras] = self.gains.get(bras, 0.0) + float(gain)
        self.total += 1

    def classement(self) -> list[tuple[str, float, int]]:
        return sorted(
            ((b, (self.gains[b] / self.tires[b]) if self.tires[b] else 0.0, self.tires[b])
             for b in self.tires),
            key=lambda x: -x[1],
        )

    def as_dict(self) -> dict[str, Any]:
        c = self.classement()
        return {
            "n_tirages": self.total,
            "meilleures_requetes": [{"requete": b, "rendement": round(r, 2), "essais": n}
                                    for b, r, n in c[:10]],
            # 🚩 « sans rendement », **pas « stérile »**. La nuance compte :
            #    *une requête essayée une fois sans résultat n'est pas PROUVÉE stérile.*
            #    Le bandit l'a simplement dépriorisée — il ne l'a pas condamnée.
            "sans_rendement": [{"requete": b, "essais": n}
                               for b, r, n in c if n >= 1 and r == 0.0][:10],
            "pourquoi": ("🔑 **Le quota est notre ressource rare.** *Une ressource rare se pilote, "
                         "elle ne se saupoudre pas.* Les requêtes sans rendement ci-dessus sont "
                         "**dépriorisées, pas condamnées** — le terme de curiosité (UCB) les "
                         "réessaiera si tout le reste s'épuise."),
        }


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #10 / #11 — LE GRAPHE SOCIAL : qui CITE ce repo · suivre les AUTEURS.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
def citations_inverses(qui_cite_qui: Mapping[str, Sequence[str]]) -> dict[str, list[str]]:
    """**Qui cite CE repo** — et pas l'inverse.

    ***Être cité par vingt constructeurs sérieux est un signal bien plus fort que vingt mille
    étoiles.*** Une étoile est un clic ; une citation est un **choix d'ingénieur**.
    """
    inv: dict[str, list[str]] = {}
    for citeur, cites in qui_cite_qui.items():
        for c in cites:
            inv.setdefault(c, [])
            if citeur not in inv[c]:
                inv[c].append(citeur)
    return inv


AUTORITE_MAX = 60.0


def autorite(inv: Mapping[str, Sequence[str]], repo: str) -> float:
    """Le poids d'être cité. **Plafonné pour de vrai.**

    *Vingt citations ne valent pas vingt fois une* — et **cent** ne valent pas cinq fois vingt.
    Le plafond dur évite qu'une awesome-list très citée écrase tout le reste du classement.
    """
    return round(min(12.0 * math.sqrt(len(inv.get(repo, ()))), AUTORITE_MAX), 1)


def autres_repos_de_l_auteur(bons: Sequence[str], tous: Sequence[str]) -> dict[str, list[str]]:
    """#11 — *Les gens sont plus constants que les projets.*

    Si quelqu'un a **un** bon repo, ses **autres** repos méritent un coup d'œil.
    """
    auteurs = {r.split("/")[0].lower() for r in bons if "/" in r}
    out: dict[str, list[str]] = {}
    for r in tous:
        if "/" not in r:
            continue
        a = r.split("/")[0].lower()
        if a in auteurs and r not in bons:
            out.setdefault(a, []).append(r)
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #13 — LA CHRONOLOGIE DU PROTOCOLE.
# *Un repo né la semaine d'un changement sait quelque chose qu'on ne sait pas encore.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
EVENEMENTS_HL: tuple[tuple[str, str, str], ...] = (
    ("2023-06-01", "lancement du mainnet Hyperliquid",
     "les premiers bots — souvent les plus proches du métal"),
    ("2024-11-01", "l'airdrop HYPE",
     "⚠️ **vague de bots-farmeurs** : beaucoup de bruit, peu de substance. *Ratio forks/étoiles "
     "anormal = signature d'un repo fermé à l'airdrop.*"),
    ("2025-03-01", "HIP-3 (perps déployés par des builders)",
     "🔑 frais ÷10 en growth mode — **la seule réouverture arithmétique du MM**"),
    ("2025-06-01", "l'API `predictedFundings` / cross-venue",
     "le funding comparé entre venues"),
)


def requetes_chronologiques(mois_apres: int = 4) -> list[dict[str, str]]:
    """Les repos nés **juste après** un changement de protocole."""
    from datetime import date

    out: list[dict[str, str]] = []
    for iso, quoi, pourquoi in EVENEMENTS_HL:
        d = date.fromisoformat(iso)
        m = d.month + mois_apres
        fin = date(d.year + (m - 1) // 12, ((m - 1) % 12) + 1, 1)
        out.append({
            "requete": "hyperliquid created:%s..%s" % (d.isoformat(), fin.isoformat()),
            "evenement": quoi,
            "pourquoi": pourquoi,
        })
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #14 — 🔴 CHERCHER CE QUI NOUS DONNE **TORT**.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
NOS_CONCLUSIONS: tuple[tuple[str, str, str], ...] = (
    (
        "le market making retail est MORT",
        '"market making" profitable retail crypto pnl',
        "T1b : **0/29 même à 100 % de fill** (la borne la plus généreuse). Et **HLP — le MM "
        "*payé* par le protocole et liquidateur — rend −0,01 % APR.** "
        "***S'il existe un MM retail rentable et documenté, on a raté quelque chose d'énorme.***",
    ),
    (
        "le copy-trading n'a AUCUN edge",
        '"copy trading" alpha profitable smart money wallet',
        "**−7,97 bps à coût ZÉRO** sur 24 133 signaux OOS. Le leader est **contrarien**. "
        "*Si quelqu'un publie un edge OOS positif après coûts, il faut le lire.*",
    ),
    (
        "le mempool ne sert à rien pour copier",
        "mempool front-run copy trade perp dex",
        "Le prix court **CONTRE** le leader **AVANT** son fill (−7,75 bps). "
        "*Voir son ordre plus tôt nous met plus PROFONDÉMENT dans le mouvement adverse.*",
    ),
    (
        "le funding perp↔perp est mort",
        "funding arbitrage between perpetual exchanges profitable",
        "**0/120** (X-04). *Couvrir avec un AUTRE actif ne change RIEN* — et la loi vaut au-delà : "
        "**une couverture ne vaut que si c'est le MÊME actif** (trouvée 2× indépendamment).",
    ),
    (
        "le lead-lag BTC→alts n'existe pas",
        "bitcoin altcoin lead lag predictive crypto",
        "**0/66.** BNB corr(0) = **+0,83** vs corr(2 h) = −0,03 : *les alts bougent AVEC BTC, "
        "ils ne le SUIVENT pas.* **Une corrélation contemporaine ne se trade pas.**",
    ),
)


def requetes_de_contradiction() -> list[dict[str, str]]:
    """🔴 **Cherche activement ce qui nous donne TORT.**

    ***Un corpus qui ne contient que ce qui nous conforte est un corpus qu'on a CHOISI.***

    Et on est **armés** : T1b et HLP sont des massues. *S'ils y survivent, on a raté quelque
    chose d'énorme — et il vaut mille fois mieux le savoir.*
    """
    return [{"notre_conclusion": c, "requete": q, "notre_arme": a} for c, q, a in NOS_CONCLUSIONS]


__all__ = [
    "EVENEMENTS_HL", "NOS_CONCLUSIONS", "N_EMPREINTES", "SEUIL_JUMEAU", "TAILLE_SHINGLE",
    "Bandit", "CacheBrut", "Jumeaux",
    "autorite", "autres_repos_de_l_auteur", "citations_inverses", "dedupliquer",
    "empreintes", "normaliser", "requetes_chronologiques", "requetes_de_contradiction",
    "similarite",
]
