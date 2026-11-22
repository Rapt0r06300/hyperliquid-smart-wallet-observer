"""LE LANCEUR NE DOIT PLUS POUVOIR TUER UN INNOCENT — garde dans la suite.

MESURES DU 22/11/2026 sur `LANCER_COLLECTEURS_COPY_VAULT.cmd`, quatre defauts :

| # | ce qu'il faisait | pourquoi c'est dangereux |
|---|------------------|--------------------------|
| 1 | `taskkill /PID %%P /T /F`, `%%P` lu dans un `.pid` | Windows RECYCLE les PID : un `.pid` perime designe un jour un processus etranger, et `/T` emporte tout son arbre. Douze `python.exe` tournaient sur ce PC pendant la mission |
| 2 | `taskkill /FI "WINDOWTITLE eq ALINA-*"` | un titre de fenetre n'appartient a personne |
| 3 | `echo %RANDOM%%RANDOM%> lock` sous un commentaire disant << PID du cmd courant >> | le code contredisait son commentaire ; personne ne pouvait savoir qui tenait le verrou. Verifie sur la machine : `FORMAT_ANCIEN_OU_ILLISIBLE` |
| 4 | detection d'instance = << ce PID est UN python >> | faux positif (un python etranger fait refuser le demarrage) ET faux negatif (un collecteur sans `.pid` reste invisible). Defaut DUPLIQUE : aussi dans l'ecran `:status`, qui pouvait donc mentir dans les deux sens |

Ces tests vivent DANS la suite parce qu'une regle qui ne vit que dans un script d'audit ne
garde rien : le 21/11/2026, quatre violations injectees avaient passe 49 tests verts.

Ils ne LANCENT jamais le lanceur : ils lisent son texte. Lancer une campagne depuis un test
serait exactement la seconde instance que la mission interdit.
"""
from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
LANCEUR = RACINE / "LANCER_COLLECTEURS_COPY_VAULT.cmd"


def _lignes() -> list[str]:
    return LANCEUR.read_bytes().decode("cp1252", errors="replace").splitlines()


def _actives() -> list[str]:
    """Les lignes EXECUTEES : les `rem` ne font rien, donc ne peuvent rien casser."""
    return [l for l in _lignes() if not l.strip().lower().startswith("rem")]


def test_le_lanceur_existe_et_reste_en_CRLF_sans_double_retour():
    octets = LANCEUR.read_bytes()
    assert octets, "lanceur vide"
    assert octets.count(b"\r\n") > 100
    assert b"\r\r\n" not in octets, "double CR : piege connu du depot"
    assert octets.count(b"\n") == octets.count(b"\r\n"), "LF orphelin"


def test_AUCUN_taskkill_par_PID_n_est_actif():
    """Defaut 1. Un PID seul n'est pas une identite."""
    coupables = [l for l in _actives() if "taskkill /pid" in l.lower()]
    assert not coupables, "taskkill /PID actif(s) : " + " | ".join(coupables[:3])


def test_AUCUN_taskkill_par_TITRE_DE_FENETRE_n_est_actif():
    """Defaut 2. Un titre de fenetre n'appartient a personne."""
    coupables = [l for l in _actives()
                 if 'taskkill /fi "windowtitle' in l.lower()]
    assert not coupables, "taskkill par titre actif(s) : " + " | ".join(coupables[:3])


def test_l_arret_passe_par_le_selecteur_a_IDENTITE_VERIFIEE():
    """La capacite d'arret ne doit pas avoir disparu avec les taskkill : elle doit avoir
    ete REMPLACEE. Sans ce test, neutraliser les kills passerait pour une correction."""
    actives = "\n".join(_actives())
    assert "collecteurs_balayage.py" in actives
    assert "--arreter" in actives
    # Les PID des `.pid` sont encore utilises, mais VERIFIES au lieu d'etre crus.
    assert "--pid-de" in actives


def test_un_arret_qui_ECHOUE_empeche_de_demarrer_une_seconde_campagne():
    """Croire avoir arrete un collecteur encore vivant, c'est lancer une campagne
    par-dessus la premiere -- ce que la mission interdit explicitement."""
    actives = "\n".join(_actives())
    assert "errorlevel 3" in actives, "le code 3 (arret echoue) n'est pas teste"
    position = actives.index("errorlevel 3")
    assert "fail_lock" in actives[position:position + 400], \
        "un arret incomplet doit mener au refus de demarrer"


def test_le_verrou_n_est_plus_un_NOMBRE_ALEATOIRE():
    """Defaut 3. `%RANDOM%%RANDOM%` ne survit qu'en REPLI explicite, jamais en chemin
    principal : le chemin normal ecrit PID + commande + instant."""
    actives = _actives()
    aleatoires = [l for l in actives if "%RANDOM%%RANDOM%" in l]
    # Un seul usage tolere : le repli quand Python manque, et il doit etre garde par un
    # `if not exist` -- sinon il ECRASERAIT le vrai verrou juste ecrit.
    assert len(aleatoires) <= 1, aleatoires
    for ligne in aleatoires:
        assert ligne.strip().lower().startswith("if not exist"), ligne
    assert any("ecrire_verrou_collecteurs.py" in l for l in actives), \
        "le verrou identifiant n'est pas ecrit"


def test_la_detection_d_instance_n_est_plus_un_simple_FINDSTR_PYTHON():
    """Defaut 4, les DEUX copies : avant le lancement et dans l'ecran `:status`."""
    coupables = [l for l in _actives()
                 if "tasklist /fi" in l.lower() and "findstr" in l.lower()]
    assert not coupables, ("detection par 'c est UN python' encore active : "
                           + " | ".join(coupables[:2]))


def test_l_ecran_STATUS_lit_le_meme_selecteur_que_le_demarrage():
    """Deux verites sur << la collecte tourne-t-elle >> divergeraient un jour."""
    texte = "\n".join(_actives())
    # Le demarrage COMPTE (--compter, lu par `set /p` : une backquote coupait le chemin de
    # python.exe au premier espace) et le statut LISTE (--lister). Les deux doivent passer
    # par le MEME selecteur : deux verites sur "la collecte tourne-t-elle" divergeraient.
    occurrences = len(re.findall(
        r"collecteurs_balayage\.py[^\r\n]*--(?:lister|compter)", texte))
    assert occurrences >= 2, (
        f"le selecteur n'est utilise que {occurrences} fois : le demarrage et le statut"
        " doivent lire la MEME chose")


def test_l_ecran_STATUS_montre_l_ETAT_REEL_a_quatre_niveaux():
    """Defaut mesure le 22/11/2026 : l'ecran lisait `d.get("lease_valid")`, une clef ABSENTE
    de ce schema (elle appartient a `bounded_collection`). Il affichait donc
    `Lease valide: ?` POUR TOUJOURS, alors que le bail etait expire depuis 10,2 h et que le
    fichier listait 20 workers dont AUCUN n'etait vivant.
    """
    actives = "\n".join(_actives())
    assert "etat_collecte_reel.py" in actives, (
        "l'ecran ne montre pas l'etat reel (processus vivant != collecte fonctionnelle"
        " != donnees fraiches)")
    coupables = [l for l in _actives() if "lease_valid" in l]
    assert not coupables, "la clef inexistante `lease_valid` est encore lue : " + str(coupables)


def test_rien_n_a_ete_SUPPRIME_les_anciens_blocs_restent_tracables():
    """Le contrat du depot interdit d'effacer : les lignes perimees restent, motivees."""
    texte = "\n".join(_lignes())
    assert texte.count("PERIME 22/11/2026") >= 10, (
        "les anciennes lignes doivent etre conservees en `rem`, avec leur motif")
    # Et les anciens gestes restent lisibles pour qui veut comprendre l'historique.
    assert "taskkill /PID" in texte
    assert "WINDOWTITLE eq ALINA-POLL-LEADERS" in texte
