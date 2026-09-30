"""IDEA-92 + IDEA-93 — LES OUTILS QUI TESTENT NOS TESTS, testes eux-memes.

🚩 LA REGLE QUE J'AI PAYEE CINQ FOIS AUJOURD'HUI :

    « Un garde-fou qui ne peut pas echouer ne garde rien. »
    « Un test qui passe pour la MAUVAISE RAISON est un test qui MENT. »

Un detecteur de mutants qui ne trouve aucun mutant serait VERT et AVEUGLE.
Un moteur de proprietes qui n'echoue jamais serait VERT et AVEUGLE.

Donc, ici, chaque outil est teste DANS LES DEUX SENS :
  * il MORD sur du code / une propriete fabriques FAUX ;
  * il NE MORD PAS sur du code / une propriete corrects.

Aucun ordre reel.
"""
from __future__ import annotations

import ast

import pytest

from hl_observer.testing.mutation import (
    ResultatMutation,
    _compter_cibles,
    generer_mutants,
    verdict_global,
)
from hl_observer.testing.property_based import (
    ProprieteViolee,
    bps,
    entiers,
    flottants,
    listes,
    pour_tout,
    prix,
)

# =============================================================================================
# 1. MUTATION (IDEA-93)
# =============================================================================================

SOURCE_SIMPLE = (
    "def survit(marge, mm):\n"
    "    return marge > mm\n"
)


def test_le_muteur_produit_bien_un_mutant_sur_une_comparaison():
    ms = generer_mutants(SOURCE_SIMPLE, fichier="f.py")
    assert len(ms) == 1
    assert ms[0].operateur == "Gt->GtE"
    assert "marge >= mm" in ms[0].code


def test_le_mutant_reproduit_EXACTEMENT_le_bug_de_588():
    """🔴 CE N'EST PAS UNE MUTATION ABSTRAITE : c'est le bug que j'ai commis le 13/07.

    `survit = r_liq > pire` (strict) declarait LIQUIDEE une marge qui survivait EXACTEMENT au
    pire mouvement -- et produisait un rapport qui se contredisait lui-meme.
    Si nos tests ne tuent pas ce mutant, ils ne nous protegent pas de le refaire.
    """
    ms = generer_mutants(SOURCE_SIMPLE, fichier="carry.py")
    mute = {}
    exec(compile(ms[0].code, "<mutant>", "exec"), mute)   # noqa: S102 - code que NOUS generons
    original = {}
    exec(compile(SOURCE_SIMPLE, "<origine>", "exec"), original)   # noqa: S102
    # a l'EGALITE, l'original et le mutant divergent : c'est exactement le cas-limite paye.
    assert original["survit"](5.0, 5.0) is False
    assert mute["survit"](5.0, 5.0) is True


def test_le_compteur_et_le_muteur_sont_D_ACCORD():
    """🚩 SANS CE TEST, LE SCORE SERAIT GONFLE.

    Si `_compter_cibles` compte plus d'occurrences que `_Muteur` n'en visite, `generer_mutants`
    produirait des mutants VIDES (identiques a l'original) -- qui seraient donc « survivants »
    et feraient CHUTER le score sans raison. Ou l'inverse : des mutations jamais generees.
    On verifie que les deux comptent la MEME chose.
    """
    source = (
        "def f(a, b, ok):\n"
        "    if a < b and ok is True:\n"
        "        return a + b\n"
        "    if a >= b or not ok:\n"
        "        return a - b * 2\n"
        "    return False\n"
    )
    attendu = _compter_cibles(ast.parse(source))
    obtenus = generer_mutants(source, fichier="f.py", maximum=9999)
    assert len(obtenus) == attendu, (
        "le compteur annonce %d mutations, le muteur en a produit %d : le score de mutation "
        "serait FAUX" % (attendu, len(obtenus))
    )
    # ... et chaque mutant est REELLEMENT different de l'original
    origine = ast.unparse(ast.parse(source))
    for m in obtenus:
        assert m.code != origine, "mutant VIDE (identique a l'original) : %s" % m.id


def test_chaque_mutant_reste_du_python_VALIDE():
    """Un mutant qui ne compile pas serait « tue » par une SyntaxError -- et gonflerait le score
    sans qu'aucun test n'ait rien verifie. On l'interdit."""
    source = (
        "def f(xs, seuil):\n"
        "    total = 0\n"
        "    for x in xs:\n"
        "        if x > seuil and x != 0:\n"
        "            total = total + x / 2\n"
        "    return total >= 0 or False\n"
    )
    for m in generer_mutants(source, fichier="f.py"):
        ast.parse(m.code)          # leve SyntaxError si le mutant est casse


def test_un_source_illisible_ne_produit_RIEN_plutot_qu_un_faux_score():
    """DENY-BY-DEFAULT : on ne devine pas. Zero mutant, pas un score invente."""
    assert generer_mutants("def f( : pass", fichier="casse.py") == []


def test_le_score_de_mutation_dit_la_VERITE():
    r = ResultatMutation(fichier="f.py", tues=3)
    ms = generer_mutants(SOURCE_SIMPLE, fichier="f.py")
    r.survivants.append(ms[0])
    assert r.total_valides == 4
    assert r.score == pytest.approx(0.75)
    v = verdict_global([r], plancher=0.8)
    assert v["ok"] is False              # 0,75 < 0,80 -> le cliquet MORD
    assert v["survivants"] == 1
    assert v["real_execution"] is False


def test_un_mutant_INVALIDE_n_est_ni_tue_ni_survivant():
    """🚩 Sinon on gonflerait le score en cassant le code plus fort : un mutant qui ne s'importe
    meme pas ferait rougir la suite et compterait comme « tue ». Ce serait un mensonge."""
    r = ResultatMutation(fichier="f.py", tues=1, invalides=5)
    assert r.total_valides == 1                      # les 5 invalides ne comptent PAS
    assert r.score == pytest.approx(1.0)


# =============================================================================================
# 2. PROPERTY-BASED (IDEA-92)
# =============================================================================================


def test_une_propriete_VRAIE_passe():
    @pour_tout(bps(), bps())
    def commutativite(a, b):
        assert a + b == b + a

    commutativite()          # ne doit pas lever


def test_une_propriete_FAUSSE_est_ATTRAPEE():
    """« Un garde-fou qui ne peut pas echouer ne garde rien. »"""
    @pour_tout(flottants())
    def faux(x):
        assert x >= 0        # faux des qu'on tire un negatif

    with pytest.raises(ProprieteViolee):
        faux()


def test_le_contre_exemple_est_RETRECI_donc_LISIBLE():
    """Un contre-exemple de 17 decimales n'est pas un diagnostic. On veut le PLUS PETIT."""
    @pour_tout(flottants(mini=-1000, maxi=1000))
    def faux(x):
        assert x < 100

    with pytest.raises(ProprieteViolee) as e:
        faux()
    msg = str(e.value)
    assert "contre-exemple" in msg
    assert "RETRECI" in msg or "retrecissement" in msg


def test_les_cas_DEGENERES_sont_essayes_EN_PREMIER():
    """🔴 C'EST LE CŒUR DE L'IDEE. Tous nos bugs vivaient dans les degenerescences :
    l'EGALITE (#588), le NEGATIF (#594), la LISTE VIDE (le poller L2).
    Un tirage purement aleatoire les manquerait presque toujours."""
    vus: list[float] = []

    @pour_tout(flottants(), cas=3)
    def collecte(x):
        vus.append(x)

    collecte()
    assert 0.0 in vus, "le zero doit etre essaye d'office, pas par chance"


def test_la_LISTE_VIDE_est_toujours_essayee():
    """Le poller de carnet L2 n'a JAMAIS demarre parce qu'une liste vide eteignait la collecte
    en silence. Une liste vide n'est pas un cas exotique : c'est LE cas."""
    vus: list[list] = []

    @pour_tout(listes(prix()), cas=4)
    def collecte(xs):
        vus.append(list(xs))

    collecte()
    assert [] in vus


def test_une_TypeError_n_est_PAS_masquee_en_succes():
    """⚠️ Si le moteur avalait les TypeError, un generateur mal branche rendrait le test VERT et
    AVEUGLE -- exactement le bug de mon audit de couverture (il annoncait 0 % et personne ne
    bronchait)."""
    @pour_tout(entiers())
    def casse(x):
        return x + "texte"        # TypeError, pas AssertionError

    with pytest.raises(TypeError):
        casse()


def test_le_seed_est_FIXE_donc_le_test_est_REPRODUCTIBLE():
    """Un test qui echoue un jour sur trois n'est pas un test, c'est une loterie."""
    def tirer() -> list[float]:
        out: list[float] = []

        @pour_tout(flottants(), cas=25)
        def collecte(x):
            out.append(x)

        collecte()
        return out

    assert tirer() == tirer()
