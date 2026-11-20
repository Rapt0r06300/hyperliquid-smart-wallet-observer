"""Le collecteur L2 doit VOIR un flux qui se tait sans se fermer.

CE QUI MANQUAIT (20/11/2026). `src/hl_observer/feed_integrity/` contient 19 primitives
d'integrite de flux ; **16 n'avaient aucun appelant en production** -- ecrites, testees
unitairement, jamais branchees. `idle_socket_watchdog` est la plus directe : un socket OUVERT
mais SILENCIEUX gele la collecte sans rien signaler.

POURQUOI LE KEEPALIVE NE SUFFIT PAS. La boucle borne deja la lecture a 30 s et passe
`ping_interval=20`, donc la bibliotheque ferme d'elle-meme un socket qui ne repond plus aux
pings. Le trou qui reste est AUTRE : un socket qui repond parfaitement aux pings mais dont la
SOUSCRIPTION ne livre plus de donnees. Ni le keepalive ni le `wait_for` ne peuvent le voir.

CE QUE CE CABLAGE FAIT, ET CE QU'IL NE FAIT PAS. Il IMPRIME, il ne coupe rien : le silence
normal d'une lane L2 n'a pas ete mesure, et une garde se calibre sur le pire cas MESURE. Agir
sur le verdict (forcer une reconnexion) reste a decider une fois la mesure faite.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for _chemin in (RACINE / "tools", RACINE / "src"):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

import collecter_l2_lane as C  # noqa: E402


def test_un_flux_silencieux_est_signale() -> None:
    maintenant = 1_700_000_000_000
    ligne = C.diagnostic_silence(maintenant - 300_000, maintenant)
    assert ligne is not None, "un silence de 300 s n'est pas signale"
    assert "FLUX SILENCIEUX" in ligne and "SOCKET_SILENCIEUX" in ligne, ligne


def test_un_flux_vivant_ne_dit_rien() -> None:
    """La moitie qui compte : crier sur un flux normal rendrait le signal inutile."""
    maintenant = 1_700_000_000_000
    assert C.diagnostic_silence(maintenant - 1_000, maintenant) is None
    assert C.diagnostic_silence(maintenant, maintenant) is None


def test_un_horodatage_inconnu_est_traite_comme_MORT() -> None:
    """Fail-closed : « je ne sais pas » ne doit jamais se lire « tout va bien »."""
    ligne = C.diagnostic_silence(None, 1_700_000_000_000)
    assert ligne is not None and "ACTIVITE_INCONNUE" in ligne, ligne


def test_le_seuil_est_franchissable_dans_les_deux_sens() -> None:
    """Sans ceci, un seuil absurde (0 ou l'infini) passerait les tests ci-dessus."""
    maintenant = 1_000_000
    seuil = C.SILENCE_DIAGNOSTIC_MS
    assert seuil > 0, "un seuil nul signalerait tout"
    assert C.diagnostic_silence(maintenant - (seuil - 1), maintenant) is None
    assert C.diagnostic_silence(maintenant - (seuil + 1), maintenant) is not None


def test_la_primitive_du_projet_est_bien_celle_utilisee() -> None:
    """Le cablage doit passer par `feed_integrity`, pas par une copie locale du calcul."""
    from hl_observer.feed_integrity import idle_socket_watchdog as W
    assert C.etat_socket is W.etat_socket, (
        "le collecteur n'appelle plus la primitive du projet : un doublon aurait ete cree")
