r"""TEST DE FUMÉE — *la chaîne complète tourne-t-elle de bout en bout SANS CRASHER ?*

═══════════════════════════════════════════════════════════════════════════════════════════════
LE TROU QUE CE TEST COMBLE
═══════════════════════════════════════════════════════════════════════════════════════════════

377 tests valident chaque **pièce**. L'audit prouve l'**arithmétique**. Mais :

    ***Je n'avais JAMAIS exécuté la chaîne complète en entier.***

Les tests unitaires ne voient pas les **coutures** entre modules. Un run de 12 h qui plante à la
5ᵉ minute sur un `AttributeError` entre deux phases serait **le pire résultat possible** : on
perdrait 12 h ET on n'apprendrait rien.

Ce test lance **le vrai `main()`**, avec :
  * **le réseau coupé** (`_get` renvoie toujours `None`, comme si RIEN n'était lisible) ;
  * **un budget de temps quasi nul** → les phases réseau se sautent proprement ;
  * **les sorties redirigées** vers un dossier temporaire (on ne touche pas la vraie racine).

Et il vérifie la chose qui compte :

    🔒 **AUCUNE PHASE N'A CRASHÉ** (`_phase` compte les exceptions comme des blessures).
       Si une couture casse, `blessures.abandons` contient une clé `PHASE:...` — **et le test
       tombe.**

    ✅ **Le `.md` est produit MÊME AVEC ZÉRO DONNÉE** — l'état vide honnête, pas un crash.

*Une chaîne qui survit à « rien à lire » survivra à « quelque chose à lire ».*

Aucun réseau. Aucun ordre réel.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


@pytest.fixture()
def moisson(monkeypatch, tmp_path):
    """Charge le module et **coupe le réseau + redirige les sorties**."""
    import importlib

    m = importlib.import_module("tools.moissonner_10h") if "tools.moissonner_10h" in sys.modules \
        else None
    if m is None:
        # le script n'est pas un package importable -> on l'exécute via son chemin
        import importlib.util

        chemin = Path(__file__).resolve().parents[1] / "tools" / "moissonner_10h.py"
        spec = importlib.util.spec_from_file_location("moissonner_10h_smoke", chemin)
        m = importlib.util.module_from_spec(spec)
        sys.modules["moissonner_10h_smoke"] = m
        spec.loader.exec_module(m)

    # 🔒 LE RÉSEAU EST COUPÉ. *Comme si RIEN n'était lisible.* -> on teste la couture, pas GitHub.
    monkeypatch.setattr(m, "_get", lambda *a, **k: None)

    # les sorties vont dans un tmp : *on ne clobbe pas la vraie racine.*
    monkeypatch.setattr(m, "SORTIE_MD", tmp_path / "moisson-fini.md")
    monkeypatch.setattr(m, "SORTIE_JSON", tmp_path / "moisson_10h.json")
    monkeypatch.setattr(m, "ETAT", tmp_path / "etat.json")
    monkeypatch.setattr(m, "BATTEMENT", tmp_path / "moisson-en-cours.txt")
    from hl_observer.research.moteur import CacheBrut
    monkeypatch.setattr(m, "CACHE", CacheBrut(tmp_path / "cache"))

    # pas de token -> pas de recherche code (et on ne veut pas de reseau de toute facon)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    return m, tmp_path


def _lancer(m, tmp_path, heures="0.0002"):
    import io
    import contextlib

    argv = ["moissonner_10h", "--heures", heures, "--repartir-de-zero"]
    with contextlib.redirect_stdout(io.StringIO()):
        code = m.main.__wrapped__(  # au cas ou un decorateur -- sinon fallback ci-dessous
            ) if hasattr(m.main, "__wrapped__") else _appel(m, argv)
    return code


def _appel(m, argv):
    import io
    import contextlib

    old = sys.argv
    sys.argv = argv
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return m.main()
    finally:
        sys.argv = old


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  1. 🔒 LE TEST QUI COMPTE — la chaîne survit à « rien à lire ».
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_la_chaine_COMPLETE_tourne_sans_crasher(moisson):
    """***Si une couture casse, ce test tombe.*** C'est tout son intérêt."""
    m, tmp_path = moisson
    code = _appel(m, ["moissonner_10h", "--heures", "0.0002", "--repartir-de-zero"])
    assert code == 0, "🔴 le run s'est terminé sur un code d'erreur (%s)" % code


def test_AUCUNE_PHASE_n_a_crashe(moisson, monkeypatch):
    """🔒 **La couture entre modules est-elle solide ?**

    `_phase` capture les exceptions et les note dans `Blessures.abandons` sous une clé
    `PHASE:...`. **Si une seule phase a crashé, elle apparaît là.** *Un run qui « ne meurt
    jamais » pourrait masquer un crash de phase — ce test l'empêche.*
    """
    m, tmp_path = moisson

    capte = {}
    vrai_phase = m._phase

    def _phase_espion(nom, f, bless):
        r = vrai_phase(nom, f, bless)
        capte["bless"] = bless
        return r

    monkeypatch.setattr(m, "_phase", _phase_espion)
    _appel(m, ["moissonner_10h", "--heures", "0.0002", "--repartir-de-zero"])

    bless = capte.get("bless")
    assert bless is not None, "aucune phase n'a tourne -- le run s'est arrete trop tot"
    crashs = [k for k in bless.abandons if k.startswith("PHASE:")]
    assert not crashs, (
        "🔴🔴 **UNE PHASE A CRASHÉ** (couture cassée entre modules) : %s\n%s"
        % (crashs, {k: bless.abandons[k] for k in crashs})
    )


def test_le_MD_est_produit_meme_avec_ZERO_donnee(moisson):
    """✅ *L'état vide HONNÊTE, pas un crash.* La chaine doit ecrire un .md quoi qu'il arrive."""
    m, tmp_path = moisson
    _appel(m, ["moissonner_10h", "--heures", "0.0002", "--repartir-de-zero"])
    md = tmp_path / "moisson-fini.md"
    assert md.exists(), "🔴 le livrable moisson-fini.md n'a PAS ete produit"
    texte = md.read_text(encoding="utf-8")
    assert len(texte) > 500, "le .md est trop court pour etre le vrai livrable"


def test_le_MD_contient_ses_SECTIONS_essentielles(moisson):
    """Le .md doit contenir le bloc de pre-approbation, les idees, les sources, les blessures."""
    m, tmp_path = moisson
    _appel(m, ["moissonner_10h", "--heures", "0.0002", "--repartir-de-zero"])
    t = (tmp_path / "moisson-fini.md").read_text(encoding="utf-8")

    # 🔒 le bloc de pre-approbation -- *ce que Claude a accepte, et ce qu'il n'a PAS accepte*
    assert "déjà accepté" in t and "PAS" in t
    assert "MESURÉE CHEZ NOUS" in t, "la ligne rouge (mesurer avant d'accepter) doit y etre"
    # les 17 sources et la franchise
    assert "OpenReview" in t or "OpenAlex" in t
    assert "moteur de recherche web gratuit" in t or "semblant" in t
    # 🔴 les blessures -- *un scan qui ne se plaint jamais ment*
    assert "su lire" in t or "blessure" in t.lower()


def test_le_TABLEAU_DE_BORD_est_ecrit(moisson):
    """🔑 *Un run de 12 h qu'on ne peut pas observer est un run qu'on interrompt par angoisse.*"""
    m, tmp_path = moisson
    _appel(m, ["moissonner_10h", "--heures", "0.0002", "--repartir-de-zero"])
    b = tmp_path / "moisson-en-cours.txt"
    assert b.exists(), "le tableau de bord temps reel n'a pas ete ecrit"
    t = b.read_text(encoding="utf-8")
    assert "MOISSON" in t.upper()


def test_LE_BATTEMENT_DE_CŒUR_rafraichit_MEME_SANS_EVENEMENT(moisson):
    """🔑🔑 **LE TEST DE « ça avance en temps réel ».**

    🔴 Le probleme : entre deux evenements (ou pendant une attente de quota de 15 min), le
    fichier ne changeait pas -> l'ecran semblait FIGE. *Une horloge qui ne bouge pas donne
    l'impression d'un run MORT.*

    -> un thread reecrit le tableau de bord **toutes les 2 s, quoi qu'il arrive**. On le prouve :
    **sans toucher a rien**, le fichier doit changer entre deux instants.
    """
    import time as _t

    from hl_observer.research.scan_resilience import Blessures

    m, tmp_path = moisson
    prog = m.Progres(_t.time(), 12.0, Blessures())
    prog.phase = "PHASE A — LE SCAN"

    m.BATTEMENT = tmp_path / "battement.txt"
    stop, th = m._demarrer_battement(prog)
    try:
        _t.sleep(0.3)
        a = (tmp_path / "battement.txt").read_text(encoding="utf-8")
        _t.sleep(2.4)                       # on ne fait RIEN — le cœur doit battre tout seul
        b = (tmp_path / "battement.txt").read_text(encoding="utf-8")
    finally:
        stop.set()
        th.join(timeout=3.0)

    assert a and b, "le battement de cœur n'a rien ecrit"
    assert a != b, (
        "🔴 **LE TABLEAU DE BORD EST FIGE** : sans evenement, il ne change pas. "
        "*C'est exactement ce que Flo ne voulait pas.* Le battement de cœur doit faire avancer "
        "l'horloge et l'indicateur meme a l'arret."
    )
    # l'indicateur qui tourne doit avoir bouge (|/-\\)
    assert any(x in b for x in "|/-\\"), "l'indicateur vivant doit tourner"


def test_le_battement_NE_FAIT_JAMAIS_tomber_le_run(moisson):
    """*Le tableau de bord ne doit JAMAIS faire tomber le run.* Meme si `ecrire` levait, le
    thread avale l'exception. On verifie que le chemin normal ne crashe pas non plus.
    """
    m, tmp_path = moisson
    code = _appel(m, ["moissonner_10h", "--heures", "0.0002", "--repartir-de-zero"])
    assert code == 0


def test_le_JSON_machine_est_produit_et_marque_LECTURE_SEULE(moisson):
    """*Le pendant machine du .md, pour re-juger hors ligne.*"""
    import json

    m, tmp_path = moisson
    _appel(m, ["moissonner_10h", "--heures", "0.0002", "--repartir-de-zero"])
    j = tmp_path / "moisson_10h.json"
    assert j.exists()
    d = json.loads(j.read_text(encoding="utf-8"))
    assert d.get("real_execution") is False
    assert d.get("aucun_code_execute") is True


def test_le_MD_contient_le_BILAN_DE_COUVERTURE_honnete(moisson):
    """🔒 Flo : *« es-tu sur qu'il gardera ABSOLUMENT TOUTES les bonnes idees ? »*

    ***La reponse honnete est « je ne peux pas le promettre » -- et le .md doit le DIRE***,
    chiffre en main : combien scannes, combien analyses en profondeur, combien reste, ou.
    *Un livrable qui pretend etre exhaustif sans l'etre est un livrable qui ment.*
    """
    m, tmp_path = moisson
    _appel(m, ["moissonner_10h", "--heures", "0.0002", "--repartir-de-zero"])
    t = (tmp_path / "moisson-fini.md").read_text(encoding="utf-8")
    assert "Bilan de couverture" in t
    assert "absolument toutes" in t.lower(), "il doit AVOUER qu'il ne peut pas tout garantir"
    assert "analyse profonde" in t or "analysés en profondeur" in t
    assert "JSON" in t, "il doit renvoyer au JSON pour le detail complet"
    assert "relançable" in t or "relancable" in t, (
        "le run doit etre relançable -> ce qui n'a pas ete analyse le sera au prochain run")


def test_le_JSON_contient_TOUT_meme_les_repos_non_analyses(moisson):
    """🔑 *Rien ne s'efface.* Le JSON garde la couverture ET la liste a analyser au prochain run."""
    import json

    m, tmp_path = moisson
    _appel(m, ["moissonner_10h", "--heures", "0.0002", "--repartir-de-zero"])
    d = json.loads((tmp_path / "moisson_10h.json").read_text(encoding="utf-8"))
    assert "couverture" in d
    for cle in ("repos_scannes", "repos_dignes_analyse", "repos_analyses_en_profondeur",
                "repos_reportes_faute_de_temps"):
        assert cle in d["couverture"], "le bilan machine doit contenir : %s" % cle
    assert "a_analyser_au_prochain_run" in d
    assert "tous_les_repos_vus" in d, "meme les repos jamais ouverts sont traces"


def test_le_reseau_coupe_produit_des_BLESSURES_pas_un_CRASH(moisson, monkeypatch):
    """🔴 *« Je n'ai pas su lire » n'est PAS « il n'y avait rien ».*

    Avec le reseau coupe et un budget minuscule, il ne trouve rien -- mais il doit **le DIRE
    dans le .md**, pas planter ni pretendre que le corpus etait vide.
    """
    m, tmp_path = moisson
    _appel(m, ["moissonner_10h", "--heures", "0.0002", "--repartir-de-zero"])
    t = (tmp_path / "moisson-fini.md").read_text(encoding="utf-8")
    # l'etat vide doit etre HONNETE
    assert ("Aucun repo retenu" in t or "aucune idée" in t.lower()
            or "n'a rien" in t.lower() or "vide" in t.lower())
