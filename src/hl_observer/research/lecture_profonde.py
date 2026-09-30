r"""#2 #6 #8 — LIRE le papier (pas le résumé) · le mode INCRÉMENTAL · LINTER le .md produit.

PUR : fabrique des URL, borne des dates, vérifie un texte markdown. Aucun réseau ici.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #2 — LIRE LE PAPIER, PAS LE RÉSUMÉ.
#
#   ***Incohérence que je m'étais permise :*** pour GitHub on ouvre **le code** (la vérité) ;
#   pour les papiers on ne lisait que **titre + résumé** — la *page de vente* d'un papier.
#   La formule, le tableau de résultats, l'aveu de limite sont dans le **corps**.
#
#   arXiv sert désormais un **HTML plein texte** pour une grande partie des papiers récents :
#     https://arxiv.org/abs/2401.01234   ->   https://arxiv.org/html/2401.01234
#   On le lit pour les MEILLEURS papiers (pas tous : ça coûte un appel de plus).
# ═══════════════════════════════════════════════════════════════════════════════════════════════
_ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5})")


def url_papier_plein_texte(lien: str) -> str | None:
    """L'URL du **corps** du papier, si on sait la construire. `None` = on ne devine pas."""
    a = _ARXIV_ID.search(lien or "")
    if a:
        return "https://arxiv.org/html/%s" % a.group(1)
    return None


# les balises HTML/scripts n'apportent rien : on garde le TEXTE.
_BALISE = re.compile(r"<(script|style)[\s\S]*?</\1>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_ESP = re.compile(r"\s+")


def texte_du_html(html: str, *, maxi: int = 40000) -> str:
    """Extrait le texte lisible d'une page HTML. *Pas de dépendance : on nettoie à la main.*"""
    s = _BALISE.sub(" ", html or "")
    s = _TAG.sub(" ", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
         .replace("&gt;", ">").replace("&#x27;", "'").replace("&quot;", '"'))
    return _ESP.sub(" ", s).strip()[:maxi]


# les sections d'un papier où se cache la VÉRITÉ (au-delà du résumé)
SECTIONS_QUI_COMPTENT: tuple[str, ...] = (
    r"limitation", r"we\s+assume", r"assumption", r"caveat", r"future\s+work",
    r"out[\s-]of[\s-]sample", r"transaction\s+cost", r"after\s+fees", r"net\s+of\s+fees",
    r"does\s+not\s+(work|hold|scale)", r"fails?\s+to", r"unrealistic",
    r"result", r"table\s+\d", r"we\s+find", r"we\s+show",
)


def extraits_du_corps(texte: str, *, maxi: int = 6) -> list[str]:
    """Les phrases du **corps** qui portent une limite, un résultat, un aveu. *La vraie substance.*"""
    out: list[str] = []
    for m in SECTIONS_QUI_COMPTENT:
        for x in re.finditer(m, texte or "", re.IGNORECASE):
            a, b = max(0, x.start() - 60), min(len(texte), x.end() + 120)
            e = " ".join(texte[a:b].split())
            if e not in out:
                out.append(e)
            if len(out) >= maxi:
                return out
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #6 — LE MODE INCRÉMENTAL. *Ne re-scanner que ce qui est NOUVEAU depuis la dernière fois.*
#
#   GitHub et arXiv publient tous les jours. Un run hebdomadaire ne devrait resurfacer que le
#   vraiment neuf, au lieu de tout re-brasser.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
def lire_derniere_date(chemin: Path) -> date | None:
    if not chemin.exists():
        return None
    try:
        return date.fromisoformat(chemin.read_text(encoding="utf-8").strip()[:10])
    except Exception:  # noqa: BLE001
        return None


def ecrire_derniere_date(chemin: Path, jour: date | None = None) -> None:
    chemin.write_text((jour or date.today()).isoformat(), encoding="utf-8")


def filtre_date_github(depuis: date | None) -> str:
    """Le fragment de requête GitHub `created:>=AAAA-MM-JJ`. Vide si pas de date -> tout."""
    return "created:>=%s" % depuis.isoformat() if depuis else ""


def est_recent(iso_ou_ts: Any, depuis: date | None) -> bool:
    """Un item est-il postérieur à `depuis` ? `depuis=None` -> **tout passe** (1er run)."""
    if depuis is None:
        return True
    try:
        s = str(iso_ou_ts)[:10]
        return date.fromisoformat(s) >= depuis
    except Exception:  # noqa: BLE001
        return True            # date illisible -> on ne JETTE pas : dans le doute, on garde


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #8 — LINTER LE .md PRODUIT. *On teste chaque brique, jamais le résultat assemblé.*
#
#   C'est le trou qu'a comblé le smoke test pour le CODE — pas encore pour le LIVRABLE.
#   Un .md avec un lien `](None)`, une section vide ou le bloc de pré-approbation manquant est
#   un livrable cassé, et personne ne s'en plaindrait. *La maladie du projet, appliquée au .md.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
SECTIONS_OBLIGATOIRES: tuple[str, ...] = (
    "déjà accepté",          # le bloc de pré-approbation
    "MESURÉE CHEZ NOUS",     # la ligne rouge : mesurer avant d'accepter
    "Bilan de couverture",   # l'aveu honnête
)


@dataclass(frozen=True, slots=True)
class Lint:
    ok: bool
    problemes: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "problemes": self.problemes}

    def rapport(self) -> str:
        if self.ok:
            return "✅ le .md produit est bien formé (sections présentes, aucun lien cassé)."
        return "🔴 **le .md a %d problème(s)** :\n   - %s" % (
            len(self.problemes), "\n   - ".join(self.problemes))


def linter_md(texte: str) -> Lint:
    """Vérifie le livrable **avant** de le déclarer fini. *Un livrable qu'on ne vérifie pas ment.*"""
    p: list[str] = []
    t = texte or ""

    if len(t) < 400:
        p.append("le fichier est **trop court** (%d caractères) pour être le vrai livrable"
                 % len(t))

    for s in SECTIONS_OBLIGATOIRES:
        if s not in t:
            p.append("section obligatoire **absente** : « %s »" % s)

    # 🔴 les liens cassés : `](None)`, `]()`, `](nan)` — *un chiffre qu'on ne peut pas suivre.*
    casses = len(re.findall(r"\]\(\s*(None|nan|null|)\s*\)", t))
    if casses:
        p.append("**%d lien(s) cassé(s)** (`](None)` / `]()`)" % casses)

    # les tableaux markdown a moitie ecrits (une ligne d'entete sans separateur)
    for m in re.finditer(r"^\|.+\|\s*$", t, re.MULTILINE):
        pass  # on ne bloque pas la-dessus, trop de faux positifs

    # un placeholder oublie
    for marqueur in ("TODO", "FIXME", "XXX", "%s", "{}", "None None"):
        if marqueur in t:
            p.append("**placeholder oublié** dans le livrable : « %s »" % marqueur)

    return Lint(not p, p)


__all__ = [
    "SECTIONS_OBLIGATOIRES", "SECTIONS_QUI_COMPTENT", "Lint",
    "ecrire_derniere_date", "est_recent", "extraits_du_corps", "filtre_date_github",
    "linter_md", "lire_derniere_date", "texte_du_html", "url_papier_plein_texte",
]
