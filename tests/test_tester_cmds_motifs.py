"""Le détecteur d'erreurs du harnais de lanceurs : ce qu'il doit attraper, et ce qu'il doit laisser.

LE FAIT À EXPLIQUER (20/11/2026). `SUIVI_COFFRE.cmd` sortait en **code 0** en annonçant
« CRITIQUE=5 ERREUR=99 ». Les cinq « critiques » étaient des lignes de RÉUSSITE :

    [candles] 1d termine : 157 bougies, 106/263 deja a jour | debit 600 u/min | 0 refus encaisse(s)

Le motif `\\brefus` les attrapait — donc c'est l'**absence** de refus qui déclenchait l'alarme.
Un outil de surveillance qui crie au loup sur des succès apprend à l'opérateur à l'ignorer, et
c'est la troisième fois que cette classe de défaut apparaît dans ce dépôt.

LA LIGNE À TENIR, ET POURQUOI CES TESTS EXISTENT. Corriger un faux positif en introduisant un
faux négatif serait bien pire : un vrai refus encaissé par un collecteur passerait inaperçu.
Chaque test ci-dessous va donc PAR PAIRE — ce qui doit se taire, et ce qui doit toujours hurler.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

import tester_cmds as T  # noqa: E402


def _categorie(ligne: str) -> str | None:
    """La catégorie attribuée à une ligne, ou ``None`` : la première qui matche gagne."""
    for nom, motif in T.MOTIFS:
        if motif.search(ligne):
            return nom
    return None


# --------------------------------------------------------------- un compteur à zéro se tait


def test_zero_refus_n_est_pas_une_alerte() -> None:
    """La ligne EXACTE qui a produit le faux « CRITIQUE=5 »."""
    ligne = ("  [candles] 1d termine : 157 bougies, 106/263 deja a jour | "
             "debit 600 u/min (x6.0 vs depart) | 0 refus encaisse(s)")
    assert _categorie(ligne) != "CRITIQUE"


def test_aucun_refus_n_est_pas_une_alerte() -> None:
    assert _categorie("resume : aucun refus, aucune reconnexion") != "CRITIQUE"


# --------------------------------------------------------------- un vrai refus hurle toujours


def test_un_refus_compte_reste_critique() -> None:
    """LA régression à ne JAMAIS introduire : un refus encaissé doit rester visible."""
    assert _categorie("[candles] 4h termine : 1315 bougies | 3 refus encaisse(s)") == "CRITIQUE"


def test_dix_et_cent_cinquante_refus_restent_critiques() -> None:
    """Le piège du lookbehind : « 10 » et « 150 » se terminent par le même « 0 » que « 0 ».

    Un `(?<!0 )` naïf aurait rendu MUETS les refus les plus graves — exactement l'erreur
    inverse de celle qu'on corrige. La frontière de mot `\\b` les distingue.
    """
    assert _categorie("| 10 refus encaisses") == "CRITIQUE"
    assert _categorie("| 150 refus encaisses") == "CRITIQUE"


def test_un_refus_sans_compteur_reste_critique() -> None:
    assert _categorie("refus de connexion par l hote distant") == "CRITIQUE"
    assert _categorie("HTTP 429 : requete refusee, backoff") == "CRITIQUE"


# --------------------------------------------------------------- les autres motifs intacts


def test_les_vraies_pannes_restent_classees() -> None:
    """Le correctif ne doit toucher QUE `refus` : le reste du détecteur est inchangé."""
    assert _categorie("Traceback (most recent call last):") == "CRITIQUE"
    assert _categorie("ModuleNotFoundError: no module named 'x'") == "CRITIQUE"
    assert _categorie("ALINA_SYNC_FAIL: local CODE files were modified") == "CRITIQUE"
    assert _categorie("'POUSSER-GITHUB.cmd' n'est pas reconnu") == "CRITIQUE"
    assert _categorie("exit code 3") == "ERREUR"
    assert _categorie("WARNING: deprecated") == "AVERT"


def test_une_ligne_banale_n_est_classee_nulle_part() -> None:
    assert _categorie("[candles] 1h : 263 coins a jour") is None
    assert _categorie("[OK] 1 792 577 shards restaures") is None


# ------------------------------------------------- une réussite déclarée n'est pas une panne

_SUCCES = ('log_schema="3" event="RESULT" status="SUCCESS" phase="preflight" '
           'operation="python-version-dependencies-critical-files-watchdog-syntax" '
           'exit_code="0" elapsed_ms="920"')


def test_une_reussite_declaree_est_ignoree() -> None:
    """La ligne EXACTE qui produisait trois des cinq faux « CRITIQUE ».

    Son champ ``operation`` est un NOM de contrôle — « ...critical-files... » — et le mot
    ``CRITICAL`` du détecteur l'attrapait, alors que la ligne porte son verdict en clair.
    """
    assert T._SUCCES_DECLARE.search(_SUCCES)
    assert _categorie(_SUCCES) == "CRITIQUE", "sans la garde, l étiquette serait lue comme erreur"


def test_un_succes_avec_code_de_sortie_NON_NUL_reste_visible() -> None:
    """Les deux champs sont exigés ENSEMBLE : ce désaccord-là doit rester criant."""
    menteur = 'status="SUCCESS" operation="critical" exit_code="2"'
    assert not T._SUCCES_DECLARE.search(menteur)


def test_la_garde_n_avale_JAMAIS_une_vraie_panne() -> None:
    """LE test qui a sauvé ce correctif.

    Première tentative : appliquer `_CLASSER`, le tri partagé de `rapport_collecteurs`, à tous
    les logs du projet. Il rend ``None`` pour tout ce qu'il ne connaît PAS comme événement de
    collecteur — donc il avalait ``ALINA_SYNC_FAIL``, LA panne qui bloquait la synchronisation
    ce jour-là. « Inoffensif » et « je n'ai pas su lire » ne se confondent pas.
    """
    for panne in (
        "ALINA_SYNC_FAIL: local CODE files were modified",
        "Traceback (most recent call last):",
        'status="FAILURE" exit_code="3"',
        "| 7 refus encaisses",
    ):
        assert not T._SUCCES_DECLARE.search(panne), panne
        assert _categorie(panne) is not None, panne


# ------------------------------------------------- le garde-fou contre l'octet égaré


def test_un_avertissement_python_est_un_AVERTISSEMENT() -> None:
    """Le « CRITIQUE=1 » du certificateur, sur une ligne de CONSEIL.

    ``ResourceWarning: Enable tracemalloc to get the object allocation traceback`` contient
    le mot ``traceback`` — dans une phrase d'aide, pas dans une trace. Troisième faux positif
    de la même famille en un jour : le détecteur lisait du texte d'aide comme un diagnostic.
    """
    ligne = "ResourceWarning: Enable tracemalloc to get the object allocation traceback"
    assert T._AVERTISSEMENT_PYTHON.search(ligne)
    assert _categorie(ligne) == "CRITIQUE", "sans la garde, le mot « traceback » gagnerait"


def test_une_VRAIE_trace_reste_critique_car_elle_ne_porte_aucun_Warning() -> None:
    """La règle ne doit jamais dégrader une vraie panne : elle n'en porte pas la marque."""
    for panne in (
        "Traceback (most recent call last):",
        "RuntimeError: la base est verrouillee",
        "ALINA_SYNC_FAIL: local CODE files were modified",
    ):
        assert not T._AVERTISSEMENT_PYTHON.search(panne), panne
        assert _categorie(panne) == "CRITIQUE", panne


def test_un_avertissement_reste_COMPTE_jamais_masque() -> None:
    """La garde reclasse, elle ne fait pas disparaître : un `ResourceWarning` signale une
    ressource non fermée, et cela doit rester visible — en AVERT, à sa juste gravité."""
    assert T._AVERTISSEMENT_PYTHON.search("DeprecationWarning: x")
    assert T._AVERTISSEMENT_PYTHON.search("ResourceWarning: unclosed file")
    # Un mot qui finit par « Warning » sans les deux-points n'est pas une déclaration Python.
    assert not T._AVERTISSEMENT_PYTHON.search("le mode Warning est actif")


def test_aucun_motif_ne_contient_de_caractere_de_controle() -> None:
    """20/11/2026 — un ``\\b`` écrit hors chaîne brute est devenu l'octet 0x08 DANS le source.

    Le motif lisait alors « retour arrière suivi de exit_code », qui n'arrive jamais : la règle
    ne se déclenchait plus du tout, et ``grep`` affichait la ligne comme si de rien n'était.
    Sept tests passaient — pour la mauvaise raison. Ce contrôle rend la faute impossible à
    rejouer, dans ce fichier comme dans les motifs eux-mêmes.
    """
    motifs = [rx.pattern for _, rx in T.MOTIFS] + [
        T._SUCCES_DECLARE.pattern, T._AVERTISSEMENT_PYTHON.pattern]
    for motif in motifs:
        egares = sorted({c for c in motif if ord(c) < 32})
        assert not egares, f"caractere(s) de controle dans un motif : {[hex(ord(c)) for c in egares]}"
# ------------------------------------------------- un plafond prevu n'est pas un echec


def _resultat(code, *, tue=False, categorie="sur", critiques=0, erreurs=0):
    return {"nom": "X", "code": code, "tue": tue, "categorie": categorie, "duree": 1.0,
            "comptes": {"CRITIQUE": critiques, "ERREUR": erreurs, "AVERT": 0}}


def test_un_service_plafonne_ne_se_lit_plus_comme_une_panne() -> None:
    """LE DEFAUT : un timeout rend ``code = None``, donc les quatre entrees ``long`` --
    plafonnees PAR CONCEPTION -- ressortaient toutes « A VOIR », comme une vraie panne."""
    assert T.etat_du_resultat(
        _resultat(None, tue=True, categorie="long")) == "PLAFOND"


def test_plafond_ne_vaut_pas_termine() -> None:
    """« PLAFOND » doit rester DISTINCT de « OK » : le travail a ete coupe, pas abouti."""
    assert T.etat_du_resultat(_resultat(0)) == "OK"
    assert T.etat_du_resultat(
        _resultat(None, tue=True, categorie="long")) != "OK"


def test_une_commande_dite_sure_doit_se_terminer() -> None:
    """La moitie qui compte (1/2) : un plafond sur une categorie ``sur`` reste une alerte.

    C'est exactement le cas d'``ALINA_SYNC_preflight``, classee ``sur`` avec 900 s alors
    qu'elle scanne le corpus en SHA-256 : l'indulgence ne doit PAS s'etendre a elle.
    """
    assert T.etat_du_resultat(
        _resultat(None, tue=True, categorie="sur")) == "A VOIR"


def test_un_plafond_n_avale_jamais_une_ligne_critique() -> None:
    """La moitie qui compte (2/2) : une seule CRITIQUE suffit, plafond ou pas."""
    assert T.etat_du_resultat(
        _resultat(None, tue=True, categorie="long", critiques=1)) == "A VOIR"


def test_un_echec_avant_le_plafond_reste_un_echec() -> None:
    """Sortir en code 2 SANS avoir ete tue n'a rien d'attendu, meme en categorie ``long``."""
    assert T.etat_du_resultat(
        _resultat(2, tue=False, categorie="long")) == "A VOIR"


def test_skip_reste_accepte() -> None:
    """Les entrees ``danger`` rendent ``"SKIP"`` : ne pas les transformer en alerte."""
    assert T.etat_du_resultat(_resultat("SKIP", categorie="danger")) == "OK"


# ------------------------------------- un travail lourd n'est ni un service ni un echec


def test_un_travail_lourd_plafonne_est_attendu() -> None:
    """`ALINA_SYNC_preflight` dure ~85 min MESUREES : son plafond est le denouement prevu."""
    assert T.etat_du_resultat(
        _resultat(None, tue=True, categorie="lourd")) == "PLAFOND"


def test_un_travail_lourd_ne_tue_jamais_les_collecteurs() -> None:
    """LE PIEGE EVITE (20/11/2026). Reclasser le preflight en `long` aurait semble naturel
    -- et aurait ARRETE LES COLLECTEURS a chaque test, coupant une collecte de donnees
    irremplacable pour un simple test de lanceur. L'arret reste reserve aux services.
    """
    assert T.doit_arreter_les_collecteurs("long") is True
    assert T.doit_arreter_les_collecteurs("lourd") is False
    assert T.doit_arreter_les_collecteurs("sur") is False
    assert T.doit_arreter_les_collecteurs("danger") is False


def test_la_passe_rapide_reste_rapide() -> None:
    """La garde structurelle qui aurait attrape le defaut du jour.

    `ALINA_SYNC_preflight` sejournait en categorie `sur` avec un plafond de 900 s pour un
    travail de 85 minutes : la passe dite rapide ne pouvait que le tuer, a chaque fois.
    Une passe rapide ne contient donc RIEN qui depasse 10 minutes.
    """
    rapides = [(nom, t) for nom, _f, _a, t, cat in T.REGISTRE if cat == "sur"]
    assert len(rapides) >= 4, (
        f"{len(rapides)} entree(s) rapide(s) : la regle ne couvre plus la passe")
    trop_longs = [(nom, t) for nom, t in rapides if t > 600]
    assert not trop_longs, (
        "plafond > 10 min dans la passe RAPIDE (a reclasser en `lourd`) : " + str(trop_longs))


def test_le_preflight_alinasync_est_classe_sur_sa_duree_mesuree() -> None:
    """Le defaut precis du 20/11/2026, verrouille : categorie ET plafond."""
    entrees = [r for r in T.REGISTRE if r[0] == "ALINA_SYNC_preflight"]
    assert len(entrees) == 1, "entree ALINA_SYNC_preflight introuvable"
    _nom, _fichier, _args, timeout, categorie = entrees[0]
    assert categorie == "lourd", (
        f"categorie {categorie!r} : un scan SHA-256 de 85 min n a sa place ni dans la "
        "passe rapide ni parmi les services continus")
    assert timeout >= 10800, (
        f"plafond {timeout} s : ~117 min (7 020 s) MESUREES, et une garde se calibre sur le "
        "pire cas mesure AVEC marge -- sinon elle tue le travail qu elle doit surveiller")


# ------------------------- un journal append-only ne doit pas rejouer son PASSE


def _journal(tmp_path, nom, contenu):
    chemin = tmp_path / "runtime" / "logs" / "launchers" / nom
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8")
    return chemin


def _scanner(monkeypatch, tmp_path, tailles_avant):
    monkeypatch.setattr(T, "RACINE", tmp_path)
    import time as _t
    return T.scanner_logs_projet(_t.time() - 3600, tailles_avant=tailles_avant)


def test_les_erreurs_ANCIENNES_ne_sont_plus_recomptees(tmp_path, monkeypatch) -> None:
    """LE DEFAUT MESURE : un passage du preflight a rapporte 128 erreurs, toutes datees
    des jours precedents. Le filtre portait sur la DATE DU FICHIER, puis lisait 600 Ko de
    queue : un journal append-only rejouait tout son passe des qu une ligne y etait
    ajoutee. Le compte ne pouvait que croitre, a jamais.
    """
    passe = "ALINA_SYNC_FAIL: git merge failed (exit 1)" + chr(10)
    journal = _journal(tmp_path, "ALINA_SYNC_COMPLETE.log", passe * 5)
    avant = {str(journal.resolve()): journal.stat().st_size}
    with journal.open("a", encoding="utf-8") as fh:
        fh.write("tout va bien, rien a signaler" + chr(10))
    trouve, comptes = _scanner(monkeypatch, tmp_path, avant)
    assert comptes["CRITIQUE"] == 0 and comptes["ERREUR"] == 0, (
        f"erreurs du PASSE recomptees : {comptes} / {trouve}")


def test_une_erreur_AJOUTEE_pendant_le_run_est_vue(tmp_path, monkeypatch) -> None:
    """La moitie qui compte : borner la lecture ne doit JAMAIS rendre muet sur du neuf."""
    journal = _journal(tmp_path, "ALINA_SYNC_COMPLETE.log", "historique calme" + chr(10))
    avant = {str(journal.resolve()): journal.stat().st_size}
    with journal.open("a", encoding="utf-8") as fh:
        fh.write("ALINA_SYNC_FAIL: git merge failed (exit 1)" + chr(10))
    trouve, comptes = _scanner(monkeypatch, tmp_path, avant)
    assert sum(comptes.values()) >= 1, (
        f"une erreur AJOUTEE pendant le run est passee inapercue : {comptes}")


def test_un_journal_CREE_pendant_le_run_est_lu_en_entier(tmp_path, monkeypatch) -> None:
    """Absent de l empreinte = cree pendant le run : tout son contenu est neuf."""
    _journal(tmp_path, "nouveau.log", "ALINA_SYNC_FAIL: git merge failed" + chr(10))
    trouve, comptes = _scanner(monkeypatch, tmp_path, {})
    assert sum(comptes.values()) >= 1, (
        f"un journal cree pendant le run a ete ignore : {comptes}")


def test_sans_empreinte_le_comportement_reste_celui_d_avant(tmp_path, monkeypatch) -> None:
    """Appelee sans empreinte, la fonction garde son ancien comportement (queue bornee) :
    le correctif ne change que le chemin du harnais, qui lui en fournit toujours une.
    """
    _journal(tmp_path, "vieux.log", "ALINA_SYNC_FAIL: git merge failed" + chr(10))
    _trouve, comptes = _scanner(monkeypatch, tmp_path, None)
    assert sum(comptes.values()) >= 1
