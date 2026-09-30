"""LE REGISTRE DES ÉCHECS AVALÉS — rendre visible ce que `except: pass` faisait disparaître.

LE CONSTAT (revue du 2026-07-19)
--------------------------------
105 `except: pass` dans `src/hl_observer`, dont 14 dans `ui/routes.py`. Chacun est une panne
qui ne remonte NULLE PART : pas de log, pas de compteur, pas de trace. C'est exactement la même
maladie que le `catch` vide du dashboard, qui laissait un panneau figé sur « … » sans un mot —
et qui, vu de l'extérieur, s'appelait « l'UI est énormément buguée ».

POURQUOI ON NE LES SUPPRIME PAS
-------------------------------
Un `except: pass` est souvent DÉLIBÉRÉ et JUSTE : un panneau secondaire ne doit pas faire tomber
la page, un journal qui échoue ne doit pas casser une décision. Le problème n'est pas d'avaler
l'erreur — c'est de l'avaler **sans laisser de trace**. On garde donc le comportement (rien ne
remonte, rien ne casse) et on ajoute la seule chose qui manquait : **un compteur**.

CE QUE ÇA CHANGE CONCRÈTEMENT
-----------------------------
Au lieu de « ce panneau est vide, va savoir pourquoi », on lit :
    ui/routes.py:1832  ×47   (dernier : KeyError)
et on sait où chercher. Un chiffre qui monte est une piste ; le silence n'en est jamais une.

CONTRAINTES DURES
-----------------
  * `noter()` ne lève JAMAIS — un enregistreur d'échecs qui plante serait une farce ;
  * mémoire BORNÉE (le bot tourne des jours) : nombre de sites plafonné, pas d'historique ;
  * aucune I/O, aucun verrou coûteux : appelé sur des chemins chauds.

PAPER only : compter des exceptions n'émet aucun ordre.
"""
from __future__ import annotations

import threading
from typing import Any

#: plafond de sites distincts suivis. Au-delà, on cesse d'en AJOUTER (on continue de compter
#: ceux déjà connus) : un registre qui grossit sans fin finirait par être le bug.
MAX_SITES = 500

_verrou = threading.Lock()
_compteurs: dict[str, int] = {}
_derniers: dict[str, str] = {}


def noter(site: str, exc: BaseException | None = None) -> None:
    """Enregistre un échec AVALÉ. Ne lève jamais, ne casse jamais l'appelant."""
    try:
        cle = str(site)[:200]
        detail = type(exc).__name__ if isinstance(exc, BaseException) else ""
        with _verrou:
            if cle in _compteurs:
                _compteurs[cle] += 1
            elif len(_compteurs) < MAX_SITES:
                _compteurs[cle] = 1
            else:
                return
            if detail:
                _derniers[cle] = detail
    except Exception:  # noqa: BLE001 — un compteur d'echecs ne doit JAMAIS faire tomber le code
        return


def resume(limite: int = 20) -> dict[str, Any]:
    """Les sites qui avalent le plus, du pire au moins pire. Lecture seule."""
    with _verrou:
        items = sorted(_compteurs.items(), key=lambda kv: -kv[1])[: max(1, int(limite))]
        return {
            "n_sites": len(_compteurs),
            "total_echecs": sum(_compteurs.values()),
            "sites": [{"site": s, "n": n, "dernier": _derniers.get(s, "")} for s, n in items],
        }


def reinitialiser() -> None:
    """Remet les compteurs à zéro (tests, ou nouvelle session)."""
    with _verrou:
        _compteurs.clear()
        _derniers.clear()


__all__ = ["noter", "resume", "reinitialiser", "MAX_SITES"]
