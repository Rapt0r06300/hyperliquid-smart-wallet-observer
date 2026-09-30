"""PROVENANCE ET FRAÎCHEUR DE LA SOURCE DE DÉCISIONS — le mensonge le plus dur à voir.

CE QUI S'EST PASSÉ LE 19/07
---------------------------
Le panneau Hyperliquid affichait `virtual_refusals_logged = 3773`, figé pendant toute la
session, et `readiness = SIMULATION_INPUT_INCOMPLETE` en permanence. Les 3 773 refus étaient
un **vrai** chiffre, lu dans un **vrai** fichier. Deux problèmes quand même :

1. **PROVENANCE.** Le fichier était `logs/structured/decisions.jsonl`, écrit par le moteur
   **dYdX legacy** — une autre venue, un autre moteur. CLAUDE.md le dit noir sur blanc :
   « Ce n'est PAS la simulation Hyperliquid. » Les fichiers Hyperliquid sont remis à vide au
   démarrage de session, le sélecteur les sautait tous et retombait sur dYdX.

2. **FRAÎCHEUR.** Ce fichier n'avait pas bougé depuis 13:14, alors que la session avait
   redémarré à 14:28. Le panneau montrait donc l'état d'un moteur qui ne tournait plus.

Ce n'était pas une erreur de grandeur — une erreur de PROVENANCE. Un chiffre faux se repère ;
un chiffre vrai mais venu d'ailleurs se contemple pendant des heures. C'est exactement la
maladie du projet : « un nombre qu'on ne peut pas remonter à un rapport finira par mentir ».
"""
from __future__ import annotations

import os
import time

import pytest

from hl_observer.simulation import log_metrics as LM


def _ecrire(chemin, *, age_s: float = 0.0, contenu: str = '{"status": "REFUSED"}\n'):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8")
    if age_s:
        vieux = time.time() - age_s
        os.utime(chemin, (vieux, vieux))
    return chemin


# ------------------------------------------------------------------ 1. provenance

def test_le_log_dYdX_legacy_n_est_JAMAIS_choisi_par_defaut(tmp_path):
    """LE BUG DU 19/07. Aucun fichier Hyperliquid vivant -> on retourne le VIDE, jamais dYdX."""
    log_dir = tmp_path / "logs" / "logs à envoyer"
    log_dir.mkdir(parents=True)
    _ecrire(tmp_path / "logs" / "structured" / "decisions.jsonl")   # moteur dYdX, bien vivant

    assert LM._existing_decision_files(log_dir) == [], (
        "le panneau Hyperliquid vient d'aller lire le moteur dYdX legacy"
    )


def test_le_log_dYdX_reste_accessible_SUR_DEMANDE_EXPLICITE(tmp_path):
    """On n'a rien cassé pour dYdX : sa source reste lisible, mais il faut la DEMANDER."""
    log_dir = tmp_path / "logs" / "logs à envoyer"
    log_dir.mkdir(parents=True)
    dydx = _ecrire(tmp_path / "logs" / "structured" / "decisions.jsonl")

    trouve = LM._existing_decision_files(log_dir, autoriser_dydx_legacy=True)
    assert trouve == [dydx]


def test_une_source_HYPERLIQUID_vivante_est_bien_choisie(tmp_path):
    """CONTRE-ÉPREUVE : le garde ne doit pas tout refuser, sinon il serait « affamé »."""
    log_dir = tmp_path / "logs" / "logs à envoyer"
    attendu = _ecrire(log_dir / "simulation_pnl_ledger_latest.jsonl")
    _ecrire(tmp_path / "logs" / "structured" / "decisions.jsonl")

    assert LM._existing_decision_files(log_dir) == [attendu]


# ------------------------------------------------------------------ 2. fraîcheur

def test_une_source_PERIMEE_est_ecartee(tmp_path):
    """Un compteur d'une session morte est pire qu'un zéro : il a l'air d'être le présent."""
    log_dir = tmp_path / "logs" / "logs à envoyer"
    _ecrire(log_dir / "simulation_decisions_latest.jsonl",
            age_s=LM.MAX_AGE_SOURCE_S + 60.0)

    assert LM._existing_decision_files(log_dir) == []


def test_une_source_RECENTE_passe(tmp_path):
    log_dir = tmp_path / "logs" / "logs à envoyer"
    frais = _ecrire(log_dir / "simulation_decisions_latest.jsonl",
                    age_s=LM.MAX_AGE_SOURCE_S / 2.0)

    assert LM._existing_decision_files(log_dir) == [frais]


def test_source_perimee_juge_bien_l_age(tmp_path):
    chemin = _ecrire(tmp_path / "d.jsonl")
    maintenant = time.time()
    assert LM._source_perimee(chemin, maintenant=maintenant) is False
    assert LM._source_perimee(chemin, maintenant=maintenant + LM.MAX_AGE_SOURCE_S + 1.0) is True


def test_un_fichier_absent_est_perime_pas_une_exception(tmp_path):
    """Un garde qui explose sur un fichier manquant fait tomber le panneau entier."""
    assert LM._source_perimee(tmp_path / "jamais_ecrit.jsonl") is True


# ------------------------------------------------------------------ 3. cliquet

def test_les_CONSTANTES_ne_bougent_pas_en_douce():
    """Si quelqu'un remet dYdX par défaut « pour avoir des chiffres », ce test rougit."""
    assert LM.AUTORISER_DYDX_LEGACY is False, (
        "réautoriser dYdX par défaut fait mentir le panneau Hyperliquid sur sa provenance"
    )
    assert LM.MAX_AGE_SOURCE_S == 1800.0


@pytest.mark.parametrize("prefer_append_only", [False, True])
def test_les_DEUX_ordres_de_priorite_excluent_dYdX(tmp_path, prefer_append_only):
    """Il y a deux listes de candidats dans le code — le trou ne doit pas rester dans l'une."""
    log_dir = tmp_path / "logs" / "logs à envoyer"
    log_dir.mkdir(parents=True)
    _ecrire(tmp_path / "logs" / "structured" / "decisions.jsonl")

    assert LM._existing_decision_files(
        log_dir, prefer_append_only=prefer_append_only) == []
