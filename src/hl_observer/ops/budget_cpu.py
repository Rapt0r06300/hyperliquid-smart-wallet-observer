"""Budget CPU de la cohorte de collecte : part de coeurs et plafond d intensite.

EXTRAIT de `bounded_collection.py` le 21/11/2026, code inchange. L ajout du plafond
d intensite (consigne de l operateur : << non, les 16 coeurs a 50 % >>) portait ce
fichier a 826 lignes, au-dessus du plafond de 800 du depot, et il n est pas exempte.
Relever le plafond aurait echange une regle contre du confort.

DEUX NOTIONS DIFFERENTES, qu il ne faut pas confondre :

* la PART DE COEURS (`fraction_coeurs`, `coeurs_autorises`) epingle les collecteurs
  sur une partie des coeurs. Elle vaut 1.0 par defaut depuis le 21/11, donc elle
  n epingle rien : les 16 coeurs restent disponibles. Le mecanisme est conserve et
  teste, parce qu une machine differente peut avoir besoin de l epinglage ;
* le PLAFOND D INTENSITE (`plafond_charge_cpu`, `coeurs_equivalents_autorises`)
  borne le TRAVAIL : 16 x 50 % = 8 coeurs equivalents, etales sur les 16 par
  l ordonnanceur, chacun a mi-regime. Ce n est pas 8 coeurs satures et 8 au repos.

PAPER / lecture seule : aucune requete reseau, aucun ordre.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

#: Part des coeurs logiques EPINGLEE aux collecteurs. Historique : 60 % le 19/11/2026
#: (9 coeurs sur 16). **CHANGE LE 21/11/2026, sur demande explicite de l operateur** :
#: << non, les 16 coeurs a 50 % >>. Ce n est donc plus une part de coeurs reservee mais
#: un plafond d INTENSITE : tous les coeurs restent disponibles (aucune affinite), et la
#: charge est bornee par `PLAFOND_CHARGE_CPU` ci-dessous.
#:
#: POURQUOI CE N EST PAS LA MEME CHOSE. Epingler 8 coeurs sur 16 laisse 8 coeurs AU
#: REPOS pendant que les 8 autres saturent : la machine chauffe sur une moitie et le
#: debit plafonne a ce que 8 coeurs savent faire. Ne rien epingler et borner la charge
#: laisse l ordonnanceur etaler le travail sur les 16, chacun a mi-regime.
#:
#: Mettre 0 (ou une valeur hors ]0, 1]) desactive l affinite ; 1.0 aussi, puisqu il n y
#: a alors rien a reserver. Priorite IDLE conservee dans les deux cas : les collecteurs
#: cedent le processeur des qu une application normale le demande.
FRACTION_COEURS_DEFAUT = 1.0
VAR_FRACTION_COEURS = "HL_COLLECTEURS_FRACTION_COEURS"

#: Plafond de CHARGE processeur de la cohorte de collecte, en fraction de la machine.
#: 50 % demandes le 21/11/2026. Exprime en coeurs equivalents : 0,5 x 16 = 8 coeurs de
#: travail etales sur les 16, et non 8 coeurs satures.
PLAFOND_CHARGE_CPU_DEFAUT = 0.5
VAR_PLAFOND_CHARGE_CPU = "HL_COLLECTEURS_PLAFOND_CPU"


def fraction_coeurs(environnement: Mapping[str, str] | None = None) -> float:
    """Fraction des coeurs reservee aux collecteurs, bornee a ]0, 1]."""
    brut = (environnement or os.environ).get(VAR_FRACTION_COEURS, "")
    try:
        valeur = float(str(brut).strip().replace(",", ".")) if str(brut).strip() else FRACTION_COEURS_DEFAUT
    except ValueError:
        return FRACTION_COEURS_DEFAUT
    return valeur if 0.0 < valeur <= 1.0 else 0.0


def plafond_charge_cpu(environnement: Mapping[str, str] | None = None) -> float:
    """Plafond de charge CPU de la cohorte, en fraction de la machine, borne a ]0, 1].

    Une valeur hors bornes ou illisible rend le defaut : un plafond qu on ne sait pas
    lire ne doit jamais devenir << pas de plafond >>.
    """
    brut = (environnement or os.environ).get(VAR_PLAFOND_CHARGE_CPU, "")
    texte = str(brut).strip().replace(",", ".")
    if not texte:
        return PLAFOND_CHARGE_CPU_DEFAUT
    try:
        valeur = float(texte)
    except ValueError:
        return PLAFOND_CHARGE_CPU_DEFAUT
    return valeur if 0.0 < valeur <= 1.0 else PLAFOND_CHARGE_CPU_DEFAUT


def coeurs_equivalents_autorises(*, total: int | None = None,
                                 environnement: Mapping[str, str] | None = None) -> float:
    """Travail CPU autorise a la cohorte, en coeurs equivalents (non entier).

    16 coeurs x 50 % = 8,0 : huit coeurs de TRAVAIL, repartis sur les seize par
    l ordonnanceur, chacun a mi-regime. A ne pas confondre avec huit coeurs epingles.
    """
    n_total = int(total if total is not None else (os.cpu_count() or 1))
    n_total = max(1, n_total)
    return round(n_total * plafond_charge_cpu(environnement), 3)


def charge_cpu_depassee(charge_mesuree_pourcent: float, *, total: int | None = None,
                        environnement: Mapping[str, str] | None = None) -> bool:
    """Vrai si la charge mesuree de la cohorte depasse le plafond.

    `charge_mesuree_pourcent` est la somme des `cpu_percent()` des processus de la
    cohorte, comme psutil les rend : 100 % = un coeur plein. Une mesure negative ou
    absurde est traitee comme un depassement (fail-closed : on respire plutot que de
    pousser sur une mesure qu on ne comprend pas).
    """
    if charge_mesuree_pourcent < 0.0:
        return True
    autorise = coeurs_equivalents_autorises(total=total, environnement=environnement)
    return charge_mesuree_pourcent > autorise * 100.0


def coeurs_autorises(*, total: int | None = None,
                     environnement: Mapping[str, str] | None = None) -> tuple[int, ...]:
    """Les coeurs logiques reserves aux collecteurs, ou () si aucune affinite.

    POURQUOI UNE AFFINITE ET PAS SEULEMENT UNE PRIORITE. La priorite IDLE laisse les
    collecteurs prendre TOUS les coeurs quand la machine est libre, mais les affame des
    que l operateur travaille : leur debit s ecroule au pire moment. Reserver une PART
    des coeurs donne les deux garanties a la fois -- ils travaillent vraiment sur leur
    part, et ne touchent JAMAIS le reste, donc la machine reste reactive.

    On prend les coeurs du HAUT : les premiers portent par convention les threads
    systeme et l interface, ceux que l operateur sent en premier.
    """
    fraction = fraction_coeurs(environnement)
    if fraction <= 0.0:
        return ()
    n_total = int(total if total is not None else (os.cpu_count() or 1))
    if n_total <= 1:
        return ()
    n = max(1, min(n_total, int(n_total * fraction)))
    if n >= n_total:
        return ()   # rien a reserver : tout est deja autorise
    return tuple(range(n_total - n, n_total))


def appliquer_budget_cpu(processus: Any, *, psutil_mod: Any = None,
                         environnement: Mapping[str, str] | None = None,
                         total_coeurs: int | None = None) -> dict[str, Any]:
    """Reserve la part de coeurs au processus, et ne releve sa priorite QUE si ca a marche.

    FAIL-SAFE : sans affinite (psutil absent, plateforme sans affinite, droits refuses),
    on GARDE la priorite IDLE. Relever la priorite sans avoir borne les coeurs rendrait
    la machine moins reactive -- exactement ce que l operateur ne demande pas.
    """
    audit: dict[str, Any] = {"coeurs": [], "priorite": "IDLE", "raison": ""}
    coeurs = coeurs_autorises(total=total_coeurs, environnement=environnement)
    if not coeurs:
        audit["raison"] = "aucune affinite demandee"
        return audit
    if psutil_mod is None:
        try:
            import psutil as psutil_mod   # type: ignore[no-redef]
        except ImportError:
            audit["raison"] = "psutil absent"
            return audit
    pid = getattr(processus, "pid", None)
    if not pid:
        audit["raison"] = "processus sans pid"
        return audit
    try:
        poignee = psutil_mod.Process(int(pid))
        poignee.cpu_affinity(list(coeurs))
    except Exception as exc:                      # noqa: BLE001 - jamais fatal au lancement
        audit["raison"] = "affinite refusee: %s" % type(exc).__name__
        return audit
    audit["coeurs"] = list(coeurs)
    try:
        poignee.nice(getattr(psutil_mod, "BELOW_NORMAL_PRIORITY_CLASS", 0))
        audit["priorite"] = "BELOW_NORMAL"
    except Exception as exc:                      # noqa: BLE001
        audit["raison"] = "priorite inchangee: %s" % type(exc).__name__
    return audit
