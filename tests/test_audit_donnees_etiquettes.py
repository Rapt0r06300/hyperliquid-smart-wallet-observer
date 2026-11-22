"""« JAMAIS COLLECTÉ » ne doit pas se dire d'une famille qui a 333 shards au coffre.

MESURE DU 22/11/2026. `tools/auditer_donnees_collectees.py` est le rapport que l'opérateur lit
pour décider quoi rallumer. Il affichait, sur deux lignes consécutives :

    allmids          [JAMAIS COLLECTÉ]
                0 lignes · dernière écriture — · 333 shard(s) au coffre

Dix-sept familles dans ce cas, dont `vault_ledger` (39 shards), `position` et `vault_portfolio`
(311 chacune). L'étiquette ne regardait que le fichier VIVANT de `runtime/data`, en ignorant le
nombre de shards qu'elle imprimait elle-même juste en dessous. Or un zéro de fichier vivant
signifie seulement « le collecteur ne tourne pas en ce moment » — ce qui est l'état NORMAL
quand les collecteurs sont éteints sur consigne.

Lu tel quel, ce rapport fait conclure que ces types de données n'existent pas, alors que le
coffre en est plein. C'est un faux négatif dans le document même qui sert à décider : la pire
place pour une étiquette fausse. Même famille que le détecteur qui lisait des étiquettes au lieu
de diagnostics.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _chemin in (ROOT / "src", ROOT / "tools"):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

import auditer_donnees_collectees as A  # noqa: E402


def _etat(lignes: int, shards: int, *, utilise: bool = False) -> str:
    """L'étiquette seule, sans toucher au disque."""
    return A.etat_de_la_famille(
        presente=lignes > 0, lignes=lignes, shards=shards,
        utilise_par_le_labo=utilise, fraicheur_min=None, frais_seuil_min=30.0,
    )


def test_zero_ligne_AVEC_des_shards_nest_pas_jamais_collecte() -> None:
    """Le cœur du défaut : 0 ligne vivante + 333 shards = collecté, mais pas en vol."""
    etat = _etat(0, 333)
    assert etat != "JAMAIS COLLECTÉ"
    assert "COFFRE" in etat.upper(), etat


def test_zero_ligne_et_zero_shard_reste_JAMAIS_COLLECTE() -> None:
    """La nuance inverse doit survivre : rien nulle part, c'est vraiment rien."""
    assert _etat(0, 0) == "JAMAIS COLLECTÉ"


def test_une_famille_vivante_garde_son_etat_dusage() -> None:
    """Aucune régression sur les familles qui coulent."""
    assert _etat(1_000, 12, utilise=True).startswith("UTILIS")
    assert _etat(1_000, 0) == "COLLECTÉ · NON CERTIFIÉ"
    assert _etat(1_000, 12, utilise=False).startswith("CERTIFIÉ · NON")


def test_le_recapitulatif_SEPARE_les_deux_cas() -> None:
    """Un opérateur doit voir « au coffre, pas en vol » à part de « jamais collecté »."""
    rapport = [
        {"famille": "allmids", "etat": _etat(0, 333), "lignes_collectees": 0,
         "fraicheur_min": None, "shards_coffre": 333, "charge_par_labo": False,
         "usage_labo": "prix de reference", "fichiers": ()},
        {"famille": "neuve", "etat": _etat(0, 0), "lignes_collectees": 0,
         "fraicheur_min": None, "shards_coffre": 0, "charge_par_labo": False,
         "usage_labo": "rien encore", "fichiers": ()},
    ]
    texte = "\n".join(A.rendre(rapport))
    assert "allmids" in texte and "neuve" in texte
    ligne_jamais = next(l for l in texte.splitlines() if "jamais collect" in l.casefold())
    assert "neuve" in ligne_jamais, ligne_jamais
    assert "allmids" not in ligne_jamais, "une famille au coffre n'est pas 'jamais collectee'"
    # ⚠️ DEUX versions aveugles avant celle-ci, deux causes :
    #   1. on vérifiait que la ligne « pas en vol » EXISTE — or une liste vide la laisse
    #      exister (« : aucun »), donc l'injection qui vidait le récapitulatif restait verte ;
    #   2. `next(... if "pas en vol" in l)` attrapait la LIGNE DE FAMILLE
    #      (« allmids [AU COFFRE · PAS EN VOL] »), pas celle du récapitulatif : l'assertion
    #      « allmids est dedans » devenait tautologique.
    # On ancre donc sur le libellé propre au récapitulatif, et on exige qu'il NOMME la famille.
    ligne_en_vol = next(l for l in texte.splitlines() if "collecteur arrêté" in l.casefold())
    assert "allmids" in ligne_en_vol, ligne_en_vol
    assert "neuve" not in ligne_en_vol, "une famille jamais vue n'est pas 'au coffre'"
