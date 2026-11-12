"""Le relais qui a supprime la fenetre noire du lanceur (12/11/2026).

Au lancement de la campagne de 6 jours, l'ecran est reste COMPLETEMENT NOIR pendant plusieurs
minutes : le scellement du coffre (113 fichiers, dont des rubans de 77 Mo) etait redirige vers
`runtime/logs/coffre_session.log`. Impossible de distinguer « ca travaille » de « c'est plante »,
juste apres avoir lance six jours de collecte.

Ce qui est verrouille ici, c'est surtout le piege qui aurait rendu le remede PIRE que le mal :
derriere un TUYAU, `%ERRORLEVEL%` de Windows renvoie le code du dernier maillon (le relais,
toujours 0). Le lanceur aurait consigne « certification reussie » meme apres un echec du
certificateur. D'ou le mode LANCEUR, qui ressort avec le code du programme execute.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
OUTIL = RACINE / "tools" / "tee_console.py"


def _lancer(args, entree=None):
    return subprocess.run([sys.executable, "-B", str(OUTIL), *args], input=entree,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def _script(tmp_path: Path, corps: str) -> list[str]:
    f = tmp_path / "programme.py"
    f.write_text(corps, encoding="utf-8")
    return [sys.executable, "-B", str(f)]


# ------------------------------------------------------------------ mode TUYAU

def test_le_tuyau_affiche_ET_journalise_a_l_identique(tmp_path):
    journal = tmp_path / "sous" / "dossier" / "j.log"       # cree aussi les dossiers manquants
    r = _lancer([str(journal)], entree="une\ndeux\n")
    assert r.stdout == "une\ndeux\n"
    assert journal.read_text(encoding="utf-8") == r.stdout


def test_les_accents_survivent(tmp_path):
    """Une console cp1252 ne doit JAMAIS faire echouer une certification sur un caractere."""
    journal = tmp_path / "j.log"
    r = _lancer([str(journal)], entree="éàü — flèche →\n")
    assert "flèche" in journal.read_text(encoding="utf-8")
    assert r.returncode == 0


def test_le_journal_est_AJOUTE_jamais_ecrase(tmp_path):
    journal = tmp_path / "j.log"
    journal.write_text("deja la\n", encoding="utf-8")
    _lancer([str(journal)], entree="nouveau\n")
    assert journal.read_text(encoding="utf-8") == "deja la\nnouveau\n"


def test_sans_journal_on_affiche_quand_meme(tmp_path):
    assert _lancer([], entree="visible\n").stdout == "visible\n"


# ------------------------------------------------------------------ mode LANCEUR : LE point clé

def test_le_code_de_sortie_est_celui_du_PROGRAMME_pas_du_relais(tmp_path):
    """LE test qui compte : sinon le lanceur consignerait « certification reussie » apres un echec."""
    journal = tmp_path / "j.log"
    r = _lancer([str(journal), "--", *_script(tmp_path, "import sys; sys.exit(7)")])
    assert r.returncode == 7


def test_un_programme_qui_reussit_ressort_a_zero(tmp_path):
    journal = tmp_path / "j.log"
    r = _lancer([str(journal), "--", *_script(tmp_path, "print('ok')")])
    assert r.returncode == 0
    assert "ok" in journal.read_text(encoding="utf-8")


def test_la_sortie_d_erreur_est_relayee_elle_aussi(tmp_path):
    """Un message d'erreur qui n'apparait nulle part est exactement ce qu'on vient de corriger."""
    journal = tmp_path / "j.log"
    corps = "import sys; print('souci', file=sys.stderr); sys.exit(3)"
    r = _lancer([str(journal), "--", *_script(tmp_path, corps)])
    assert r.returncode == 3
    assert "souci" in journal.read_text(encoding="utf-8")
    assert "souci" in r.stdout


def test_un_journal_impossible_n_empeche_PAS_l_affichage(tmp_path):
    """Perdre la trace est ennuyeux ; perdre la visibilite au milieu d'une campagne l'est plus."""
    dossier = tmp_path / "occupe"
    dossier.mkdir()
    r = _lancer([str(dossier)], entree="toujours visible\n")      # un dossier n'est pas un fichier
    assert "toujours visible" in r.stdout
    assert r.returncode == 0


# ------------------------------------------------------------------ le lanceur l'utilise vraiment

def test_le_lanceur_n_a_plus_AUCUNE_etape_muette():
    """Non-regression du defaut signale : plus une seule redirection silencieuse du coffre."""
    bs = chr(92)
    texte = (RACINE / "LANCER_COLLECTEURS_COPY_VAULT.cmd").read_bytes().decode("utf-8",
                                                                               errors="replace")
    muet = ">> " + '"%CV_ROOT%runtime' + bs + "logs" + bs + 'coffre_session.log" 2>&1'
    assert muet not in texte, "une etape du coffre redirige encore tout vers un fichier"
    assert texte.count("tee_console.py") == 4, "les 4 etapes du coffre doivent passer par le relais"


def test_le_lanceur_utilise_le_mode_LANCEUR_et_pas_un_tuyau():
    """Avec un tuyau, SEAL_RC vaudrait toujours 0 : le lanceur mentirait sur la certification."""
    texte = (RACINE / "LANCER_COLLECTEURS_COPY_VAULT.cmd").read_bytes().decode("utf-8",
                                                                               errors="replace")
    for ligne in texte.replace("\r\n", "\n").split("\n"):
        if "tee_console.py" in ligne:
            assert " -- " in ligne, f"mode tuyau detecte (code de sortie perdu) : {ligne.strip()}"
            assert "|" not in ligne
