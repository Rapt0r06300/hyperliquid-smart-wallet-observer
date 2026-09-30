from hl_observer.ops.launcher_robustness import (
    code_sortie, chemin_windows_sur, commande_kill_arbre, forcer_locale_utc,
    ecrire_atomique_tolerant_verrou, sequence_double_clic,
    EXIT_GO, EXIT_NO_GO, EXIT_ERREUR, EXIT_VERROU)


def test_codes_sortie_normalises():
    assert code_sortie("GO") == EXIT_GO == 0
    assert code_sortie("NO_GO") == EXIT_NO_GO == 2
    assert code_sortie("VERROU") == EXIT_VERROU == 3
    assert code_sortie("truc_inconnu") == EXIT_ERREUR


def test_chemin_windows_avec_espace_est_quote():
    assert chemin_windows_sur(r"C:\Users\flo\Projet invest") == '"C:\\Users\\flo\\Projet invest"'
    assert chemin_windows_sur("simple") == "simple"


def test_kill_arbre_inclut_enfants():
    cmd = commande_kill_arbre(1234)
    assert "/T" in cmd and "1234" in cmd


def test_locale_forcee_utc():
    e = forcer_locale_utc({"EXISTANT": "1"})
    assert e["TZ"] == "UTC" and e["LC_ALL"] == "C" and e["PYTHONUTF8"] == "1" and e["EXISTANT"] == "1"


def test_ecriture_atomique(tmp_path):
    p = tmp_path / "sub" / "f.bin"
    r = ecrire_atomique_tolerant_verrou(p, b"hello")
    assert r["ok"] is True and p.read_bytes() == b"hello"


def test_sequence_double_clic_ordre():
    s = sequence_double_clic()
    assert s.index("restaurer_portable_env") < s.index("poser_porte_analyser_session") < s.index("lancer_lab_alpha")
