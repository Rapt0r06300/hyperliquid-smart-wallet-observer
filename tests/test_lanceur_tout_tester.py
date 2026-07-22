"""LE LANCEUR — en Python, parce que le batch n'était pas testable (21/07).

Les 40 améliorations avaient été écrites directement dans `TOUT-TESTER.cmd`, depuis un
environnement où elles ne pouvaient PAS être exécutées. Plantage au premier lancement, et
deux fichiers parasites créés à la racine :

    3.10   <-  REM ... ^>= 3.10 ...
    (3     <-  python -c "... sys.version_info>=(3,10) ..."

Dans cmd, `=` est un **délimiteur de token** : un `>=` est lu comme une redirection vers le
token suivant. Le script est mort avant d'avoir créé `logs-audit/` — les garde-fous de
traçabilité étaient en aval du plantage, donc inutiles.

Ces tests portent sur la version Python, qui, elle, s'exécute.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from tools import lanceur_tout_tester as L

CMD = Path(__file__).resolve().parents[1] / "TOUT-TESTER.cmd"


# ═══════════════ le .cmd ne doit plus JAMAIS porter de logique ═══════════════

def test_le_cmd_ne_contient_aucune_redirection_dans_un_commentaire():
    """LA CAUSE DU PLANTAGE. Un `>` ou `<` dans une ligne REM est interprété par cmd comme
    une redirection — le `^` ne protège pas de façon fiable. Aucun n'a le droit d'y être."""
    for i, ligne in enumerate(CMD.read_text(encoding="utf-8").splitlines(), 1):
        s = ligne.strip()
        if s.upper().startswith("REM"):
            assert ">" not in s and "<" not in s, (
                "ligne %d : un chevron dans un REM devient une REDIRECTION -> %s" % (i, s))


def test_le_cmd_n_a_NI_goto_NI_label_NI_chcp_NI_endlocal():
    """🔴 LA CAUSE DE LA 2e PANNE : la fenêtre se fermait instantanément, sans rien afficher.

    `LANCER_HYPERSMART.cmd`, qui tourne chez Flo depuis des semaines, n'a **aucune** de ces
    quatre constructions ; ma version en avait les quatre. Avec des fins de ligne LF, la
    recherche de label d'un `goto` échoue et cmd sort en silence. Un `chcp` au milieu d'un
    fichier contenant du non-ASCII décale le parseur. On imite ce qui MARCHE, on n'invente pas.
    """
    corps = "\n".join(l for l in CMD.read_text(encoding="utf-8").splitlines()
                      if not l.strip().upper().startswith("REM"))
    for interdit in ("goto", "chcp", "endlocal"):
        assert interdit not in corps.lower(), "%s a fait mourir le lanceur en silence" % interdit
    assert not [l for l in corps.splitlines() if l.strip().startswith(":")], "aucun label"


def test_le_cmd_est_en_PUR_ASCII():
    """Un caractère non-ASCII dans un batch dépend de la page de code active — et le tiret
    cadratin de mon en-tête était sur la même ligne qu'un `title`. On ne prend plus le risque."""
    octets = CMD.read_bytes()
    mauvais = [(i, b) for i, b in enumerate(octets) if b > 127]
    assert not mauvais, "octets non-ASCII a l'offset %s" % [i for i, _ in mauvais[:5]]


def test_le_cmd_est_en_CRLF():
    """Écrit depuis Linux, un `.cmd` part en LF. cmd.exe le tolère pour des commandes simples
    mais pas pour tout. Le fichier est donc écrit explicitement en CRLF."""
    octets = CMD.read_bytes()
    lf = octets.count(b"\n")
    crlf = octets.count(b"\r\n")
    assert lf > 0 and crlf == lf, "%d LF dont seulement %d en CRLF" % (lf, crlf)


def test_le_cmd_ne_contient_plus_de_for_f_ni_de_bloc_parenthese():
    """Un `for /f` avec backticks à l'intérieur d'un bloc `if ( )` casse le parseur de cmd.
    Ces constructions ne sont pas testables d'ici : elles n'ont plus le droit d'exister."""
    txt = CMD.read_text(encoding="utf-8")
    corps = "\n".join(l for l in txt.splitlines() if not l.strip().upper().startswith("REM"))
    assert "for /f" not in corps.lower()
    assert "set /p" not in corps.lower()
    assert "powershell" not in corps.lower(), "aucun sous-processus fragile dans le batch"


def test_le_cmd_reste_court():
    """Un lanceur qu'on ne peut pas exécuter doit rester assez petit pour être relu à l'œil."""
    corps = [l for l in CMD.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.strip().upper().startswith("REM")]
    assert len(corps) <= 30, "%d lignes de logique batch : trop pour du code non testable" % len(corps)


def test_le_cmd_appelle_bien_le_lanceur_python():
    txt = CMD.read_text(encoding="utf-8")
    assert "tools\\lanceur_tout_tester.py" in txt
    assert "exit /b %ERRORLEVEL%" in txt, "le code de sortie doit etre PROPAGE"


# ═══════════════ PRÉ-VOL (01-10) ═══════════════

def test_le_prevol_refuse_une_arborescence_incomplete(tmp_path):
    with pytest.raises(L.Echec) as e:
        L.prevol(tmp_path)
    assert e.value.code == L.CODE_PREVOL
    assert "tools/tout_tester.py" in str(e.value)


def test_le_prevol_passe_sur_le_vrai_projet():
    lignes = L.prevol()
    assert any("python" in l for l in lignes)


def test_le_verrou_empeche_deux_audits_simultanes(tmp_path):
    L.prendre_verrou(tmp_path)
    with pytest.raises(L.Echec) as e:
        L.prendre_verrou(tmp_path)
    assert e.value.code == L.CODE_VERROU
    assert "--forcer" in str(e.value), "le message doit dire COMMENT s'en sortir"


def test_un_verrou_PERIME_ne_bloque_pas_pour_toujours(tmp_path):
    """Un crash laisse un verrou. Sans expiration, plus aucun audit ne serait possible —
    le remède serait pire que le mal."""
    import os
    L.prendre_verrou(tmp_path)
    v = tmp_path / L.VERROU.name
    vieux = time.time() - (L.VERROU_PERIME_S + 60)
    os.utime(v, (vieux, vieux))
    L.prendre_verrou(tmp_path)          # ne doit pas lever


def test_forcer_passe_outre_un_verrou_vivant(tmp_path):
    L.prendre_verrou(tmp_path)
    L.prendre_verrou(tmp_path, forcer=True)
    L.liberer_verrou(tmp_path)
    assert not (tmp_path / L.VERROU.name).exists()


# ═══════════════ SÉCURITÉ (11-15) ═══════════════

@pytest.mark.parametrize("var", L.INTERRUPTEURS_REELS)
def test_un_interrupteur_d_execution_reelle_ARRETE_le_lanceur(var):
    with pytest.raises(L.Echec) as e:
        L.controle_securite({var: "true"})
    assert e.value.code == L.CODE_SECURITE
    assert "lecture seule" in str(e.value)


@pytest.mark.parametrize("var", L.SECRETS)
def test_une_cle_dans_l_environnement_ARRETE_le_lanceur(var):
    with pytest.raises(L.Echec) as e:
        L.controle_securite({var: "0xdeadbeef"})
    assert e.value.code == L.CODE_SECURITE
    assert "JAMAIS de cle" in str(e.value)


def test_une_variable_vide_ou_a_zero_n_est_pas_un_danger():
    """Un faux positif qui empêche l'audit de tourner est un dégât, pas une protection."""
    assert L.controle_securite({"REAL_MAINNET_TRADING": "false", "PRIVATE_KEY": ""})
    assert L.controle_securite({"REAL_MAINNET_TRADING": "0"})


def test_l_environnement_du_fils_impose_la_lecture_seule():
    e = L.environnement_fils()
    assert e["HYPERSMART_READ_ONLY"] == "1" and e["HYPERSMART_PAPER_ONLY"] == "1"
    assert e["PYTHONDONTWRITEBYTECODE"] == "1", "les .pyc periment a travers le mount"
    assert e["PYTHONUNBUFFERED"] == "1"
    assert "src" in e["PYTHONPATH"]


# ═══════════════ TRAÇABILITÉ (16-25) ═══════════════

def test_un_recap_perime_est_DETECTE(tmp_path):
    """LE PIRE ÉCHEC SILENCIEUX : le run plante, le RECAP d'hier reste, et on le lit en
    croyant lire celui d'aujourd'hui."""
    (tmp_path / "RECAP-COMPLET.md").write_text("vieux", encoding="utf-8")
    v = L.verdict_recap(tmp_path, debut_ts=time.time() + 10)
    assert v["perime"] is True and "PRECEDENT" in v["message"]


def test_un_recap_frais_est_accepte(tmp_path):
    (tmp_path / "RECAP-COMPLET.md").write_text("frais", encoding="utf-8")
    v = L.verdict_recap(tmp_path, debut_ts=time.time() - 10)
    assert v["perime"] is False and v["vide"] is False


def test_un_recap_VIDE_est_un_echec_pas_un_succes(tmp_path):
    (tmp_path / "RECAP-COMPLET.md").write_text("", encoding="utf-8")
    v = L.verdict_recap(tmp_path, debut_ts=time.time() - 10)
    assert v["vide"] is True and "VIDE" in v["message"]


def test_un_recap_absent_est_dit(tmp_path):
    v = L.verdict_recap(tmp_path, debut_ts=time.time())
    assert v["present"] is False and "ABSENT" in v["message"]


def test_le_recap_precedent_est_ARCHIVE_jamais_ecrase(tmp_path):
    (tmp_path / "RECAP-COMPLET.md").write_text("run precedent", encoding="utf-8")
    rel = L.archiver_recap(tmp_path, session="20260721-235959")
    assert rel and (tmp_path / rel).read_text(encoding="utf-8") == "run precedent"


def test_archiver_sans_recap_ne_leve_pas(tmp_path):
    assert L.archiver_recap(tmp_path, session="x") == ""


def test_les_logs_sont_conserves_mais_bornes(tmp_path):
    d = tmp_path / "logs-audit"
    d.mkdir()
    for i in range(40):
        p = d / ("tout-tester-2026072%02d.log" % (i % 10))
        p.write_text(str(i), encoding="utf-8")
        import os
        os.utime(p, (1000 + i, 1000 + i))
    assert L.purger_logs(tmp_path, garder=5) >= 1
    assert len(list(d.glob("tout-tester-*.log"))) <= 5


def test_l_etat_git_est_capture():
    s = L.etat_git()
    assert s and ("non commite" in s or "indisponible" in s)


def test_le_log_de_session_porte_l_empreinte_de_securite(tmp_path):
    log = tmp_path / "s.log"
    L._ecrire_log(log, "SID", tmp_path, ["une ligne"], time.time() - 5, 0)
    t = log.read_text(encoding="utf-8")
    assert "READ_ONLY=1" in t and "0 ordre reel" in t
    assert "code     : 0" in t and "une ligne" in t


# ═══════════════ ERGONOMIE / ROBUSTESSE ═══════════════

def test_les_options_du_lanceur_ne_partent_pas_au_driver():
    """`--sans-pause`, `--ouvrir` et `--forcer` n'existent pas côté driver : les transmettre
    ferait échouer le run avec « option inconnue »."""
    from tools.tout_tester import OPTIONS
    for o in L.OPTIONS_LANCEUR:
        assert o not in OPTIONS, "%s doit etre consommee par le lanceur" % o


def test_le_verdict_nomme_chaque_code_de_sortie():
    assert "VERT" in L._verdict(0)
    assert "OPTION INCONNUE" in L._verdict(2)
    assert "INTERROMPU" in L._verdict(130)
    assert "code 7" in L._verdict(7)


def test_la_duree_est_lisible():
    assert L._hms(0) == "00:00:00"
    assert L._hms(3661) == "01:01:01"
    assert L._hms(-5) == "00:00:00"


def test_une_exception_IMPREVUE_affiche_et_attend_au_lieu_de_disparaitre(monkeypatch, capsys):
    """🔴 LE PIRE MODE D'ÉCHEC : la fenêtre se ferme sans rien dire, et Flo n'a AUCUNE
    information à me transmettre. Le `.cmd` ne peut plus rien garantir (il n'a plus ni `goto`
    ni bloc, précisément parce que ça le tuait) : la garantie est ici."""
    def explose(_a=None):
        raise RuntimeError("panne jamais prevue")

    monkeypatch.setattr(L, "lancer", explose)
    monkeypatch.setattr(L, "_pause", lambda: None)
    code = L.point_d_entree([])
    sortie = capsys.readouterr().out
    assert code == 1
    assert "LE LANCEUR A PLANTE" in sortie
    assert "panne jamais prevue" in sortie, "la traceback doit etre VISIBLE, pas avalee"
    assert "envoie-le a Claude" in sortie, "l'utilisateur doit savoir quoi faire"


def test_un_refus_de_demarrer_reste_lisible_et_garde_son_code(monkeypatch, capsys):
    monkeypatch.setattr(L, "lancer", lambda _a=None: (_ for _ in ()).throw(
        L.Echec("verrou pose", L.CODE_VERROU)))
    monkeypatch.setattr(L, "_pause", lambda: None)
    assert L.point_d_entree([]) == L.CODE_VERROU
    assert "verrou pose" in capsys.readouterr().out


def test_ctrl_c_ne_passe_pas_pour_un_plantage(monkeypatch, capsys):
    monkeypatch.setattr(L, "lancer", lambda _a=None: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(L, "_pause", lambda: None)
    assert L.point_d_entree([]) == 130
    assert "INTERROMPU" in capsys.readouterr().out


def test_aucune_execution_reelle():
    import json
    assert json.loads(L.etat_json())["real_execution"] is False


# ═══════════════ DURCISSEMENTS CRASH-SAFETY (22/07) ═══════════════

def test_cflags_ne_leve_JAMAIS_et_rend_un_int():
    """🔴 tools/ n'a pas d'__init__.py : l'ancien `from tools.sous_processus_isole import` levait
    ModuleNotFoundError dans l'invocation reelle. Le helper robuste tente les deux formes puis 0 —
    il ne doit JAMAIS lever, et toujours rendre un entier (0 = aucune isolation, mais un run vivant)."""
    v = L._cflags()
    assert isinstance(v, int) and v >= 0


def test_le_budget_total_est_genereux_mais_fini():
    """Un plafond fini garantit que l'audit TERMINE toujours ; assez large pour ne jamais amputer
    un run legitime (~1 h 15)."""
    assert L.BUDGET_TOTAL_S >= 2 * 3600.0


def test_le_verdict_nomme_le_TIMEOUT():
    assert "BUDGET" in L._verdict(124) and "fige" in L._verdict(124)


def test_ctrl_c_au_TOP_NIVEAU_garde_la_fenetre_ouverte(monkeypatch):
    """La fenetre ne doit JAMAIS se fermer sans pause — meme sur un Ctrl-C hors du bloc protege."""
    appels = {"pause": 0}
    monkeypatch.setattr(L, "lancer", lambda _a=None: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(L, "_pause", lambda: appels.__setitem__("pause", appels["pause"] + 1))
    assert L.point_d_entree([]) == 130
    assert appels["pause"] == 1, "un Ctrl-C top-niveau doit PAUSER avant de fermer"
