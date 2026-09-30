r"""UN SCAN NE DOIT JAMAIS MOURIR — *et « ne pas mourir » n'est PAS « ignorer les erreurs ».*

═══════════════════════════════════════════════════════════════════════════════════════════════
LA DISTINCTION QUE CES TESTS PROTEGENT
═══════════════════════════════════════════════════════════════════════════════════════════════

Il y a **deux facons** de ne jamais mourir, et **une seule est acceptable** :

  🔴 avaler les erreurs, continuer en silence, finir avec un fichier qui a l'air complet.
     ***C'est exactement le bug qui a perdu 235 README -- dont hftbacktest, notre cible n°1.***
     Un `except: pass` transforme « je n'ai pas su lire » en « il n'y avait rien ».
     **Un scan qui ne meurt jamais ET qui ne se plaint jamais est un scan qui MENT.**

  ✅ survivre a tout, **compter chaque blessure**, et **DIRE a la fin ce qu'on n'a pas su lire**.

    ***Ne jamais mourir, jamais mentir.***

Et pour les sources sociales (X) : **le meme filtre que partout**. Un post qui promet +300 %
marque **NEGATIF**. Un post qui avoue une perte marque **POSITIF**.
*Ce n'est pas de la pruderie : c'est de l'arithmetique de survie.*

Aucun ordre reel. Aucun reseau.
"""
from __future__ import annotations

import pytest

from hl_observer.research.scan_resilience import (
    ABANDONNER,
    ATTENDRE,
    ATTENTE_MAX,
    MAX_ESSAIS_SERVEUR,
    REESSAYER,
    REUSSI,
    Blessures,
    decider,
)
from hl_observer.research.sources import (
    SEUIL_GARDE,
    catalogue,
    juger,
    rapport_sources,
)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  1. 🔑 LE QUOTA N'EST **JAMAIS** UNE RAISON D'ABANDONNER
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("statut", [403, 429])
def test_le_QUOTA_fait_ATTENDRE_jamais_abandonner(statut: int) -> None:
    """*Se faire bannir = MOINS de donnees, pas plus.* On attend, puis on **RETENTE**."""
    for essai in (0, 5, 50, 500):
        d = decider(statut, essai=essai, alea=0.5)
        assert d.action == ATTENDRE, "le quota est TEMPORAIRE : on ne renonce jamais pour ca"
        assert d.fatal_pour_cette_requete is False
        assert 0 < d.attente_s <= ATTENTE_MAX


def test_on_ECOUTE_la_source_quand_elle_dit_quand_revenir() -> None:
    """*GitHub dit lui-meme quand revenir. On l'ecoute plutot que de deviner.*"""
    d = decider(429, retry_after=120.0)
    assert d.action == ATTENDRE
    assert d.attente_s >= 120.0


def test_l_attente_est_BORNEE_on_ne_dort_pas_une_journee() -> None:
    d = decider(429, reset_dans_s=999_999.0)
    assert d.attente_s <= ATTENTE_MAX


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  2. LE JITTER — *une tempete de reessais synchronises est une AUTO-ATTAQUE.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_le_backoff_est_EXPONENTIEL() -> None:
    a = decider(500, essai=0, alea=1.0).attente_s
    b = decider(500, essai=2, alea=1.0).attente_s
    assert b > a * 2


def test_le_JITTER_desynchronise_les_reessais() -> None:
    """Sans jitter, tous les reessais retombent au meme instant -> on se refait jeter."""
    bas = decider(500, essai=3, alea=0.0).attente_s
    haut = decider(500, essai=3, alea=1.0).attente_s
    assert bas < haut, "sans jitter, le backoff est deterministe -> tempete synchronisee"
    assert bas >= haut * 0.4


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  3. CE QU'ON ABANDONNE — *et on le COMPTE, jamais en silence.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("statut", [422, 404, 401])
def test_une_erreur_DEFINITIVE_est_abandonnee_mais_NOTEE(statut: int) -> None:
    """*« Je n'ai pas su lire » n'est PAS « il n'y avait rien ».*"""
    d = decider(statut)
    assert d.action == ABANDONNER
    assert d.fatal_pour_cette_requete is True
    assert d.raison, "un abandon muet est un abandon inauditable"


def test_le_serveur_casse_est_REESSAYE_mais_pas_a_l_infini() -> None:
    """*On ne repare pas GitHub en insistant.*"""
    assert decider(503, essai=0).action == REESSAYER
    assert decider(503, essai=MAX_ESSAIS_SERVEUR).action == ABANDONNER


def test_un_echec_RESEAU_est_traite_comme_un_5xx() -> None:
    assert decider(None, essai=0).action == REESSAYER
    assert decider(None, essai=MAX_ESSAIS_SERVEUR).action == ABANDONNER


def test_le_succes_est_un_succes() -> None:
    for s in (200, 201, 204):
        assert decider(s).action == REUSSI


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  4. 🔑 LE JOURNAL DES BLESSURES — *un scan qui ne se plaint jamais est un scan qui MENT.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_LE_TEST_QUI_COMPTE_les_non_lus_sont_COMPTES_et_PUBLIES() -> None:
    """***C'est le bug qui a perdu hftbacktest : l'erreur etait AVALEE.***"""
    b = Blessures()
    b.note("repo/a", decider(404))
    b.note("repo/b", decider(422))
    b.note("repo/c", decider(429))
    d = b.as_dict()
    assert d["n_non_lus"] == 2
    assert "repo/a" in d["non_lus"] and "repo/b" in d["non_lus"]
    assert d["quotas_attendus"] == 1
    assert "n'ont PAS été lues" in d["avertissement"]
    assert "pas vides" in d["avertissement"] or "pas** vides" in d["avertissement"]


def test_un_scan_SANS_blessure_le_dit_aussi() -> None:
    assert "aucune blessure" in Blessures().rapport()


def test_le_rapport_distingue_NON_LU_de_VIDE() -> None:
    b = Blessures()
    b.note("x", decider(404))
    assert "n'est PAS" in b.rapport() or "pas" in b.rapport()
    assert "NON LUE" in b.rapport()


def test_un_meme_abandon_n_est_compte_qu_UNE_fois() -> None:
    b = Blessures()
    for _ in range(5):
        b.note("repo/a", decider(404))
    assert b.as_dict()["n_non_lus"] == 1


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  5. 🚨 X / TWITTER — *le meme filtre que partout. Il ne demande pas D'OU ca vient.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def _src(nom: str):
    return next(s for s in catalogue(jeton_github="x", jeton_x="x") if s.nom == nom)


HYPE_POST = "🚀 Turned $500 into $50,000 with my secret grinder strategy! 300% in a week. DM me!"
HONNETE_POST = (
    "Our market maker lost money on thin books. Post-mortem: we ignored adverse selection. "
    "Fill was 100% in backtest, ~12% live. Net of fees we were -8 bps per round trip. "
    "lambda(delta) = A * exp(-kappa*delta) fit poorly below 5 ticks. It didn't work."
)


def test_LE_TEST_QUI_COMPTE_un_post_qui_PROMET_marque_NEGATIF() -> None:
    """🚨 ***Biais du survivant : tu vois celui qui a gagne, jamais les mille qui ont perdu
    avec la meme methode.*** Le corpus social est **mecaniquement menteur**.
    """
    v = juger(HYPE_POST, source=_src("x_twitter"))
    assert v.garde is False
    assert v.score < 0, "une promesse sans preuve doit COUTER, pas rapporter"
    assert v.hype
    assert "survivant" in v.pourquoi.lower()


def test_un_post_qui_AVOUE_une_perte_marque_POSITIF_meme_sur_X() -> None:
    """🔑 ***Dans un corpus ou tout le monde promet, celui qui doute est le seul qui ait
    travaille.*** Le filtre ne demande pas D'OU ca vient : il demande CE QUE CA PROUVE.
    """
    v = juger(HONNETE_POST, source=_src("x_twitter"))
    assert v.garde is True, "un aveu de perte + une formule + un chiffre : ca, on le garde"
    assert v.honnetete
    assert v.score >= SEUIL_GARDE


def test_X_pese_MOINS_qu_un_papier_a_contenu_EGAL() -> None:
    """*Un post X doit etre 3x meilleur qu'un papier arXiv pour compter autant.*

    Ce n'est pas un prejuge : le grinder (0/29) et le sniper (-7,97 bps) sont MORTS, et X est
    la source la plus dense au monde en promesses sur ces deux-la.
    """
    sur_x = juger(HONNETE_POST, source=_src("x_twitter")).score
    sur_arxiv = juger(HONNETE_POST, source=_src("arxiv")).score
    assert sur_arxiv > sur_x * 2


def test_le_grinder_et_le_sniper_ne_sont_PAS_recompenses_parce_qu_ils_sont_a_la_mode() -> None:
    """*« best grinder method » sans un seul chiffre = du bruit, quel que soit le nombre de likes.*"""
    v = juger("The best grinder and sniper method for max PnL! Guaranteed. 🚀",
              source=_src("x_twitter"))
    assert v.garde is False


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  6. LES SOURCES — *on ne fait pas semblant de chercher.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_SANS_jeton_X_la_source_est_INDISPONIBLE_et_on_le_DIT() -> None:
    """*Une source qu'on n'a pas lue n'est PAS une source vide.*"""
    x = next(s for s in catalogue() if s.nom == "x_twitter")
    assert x.disponible is False
    assert "PAYANTE" in x.pourquoi_indisponible or "payant" in x.pourquoi_indisponible.lower()


def test_SANS_jeton_github_la_recherche_CODE_est_INDISPONIBLE_et_on_le_DIT() -> None:
    c = next(s for s in catalogue() if s.nom == "github_code")
    assert c.disponible is False
    assert "token" in c.pourquoi_indisponible.lower()


def test_arxiv_et_HN_sont_TOUJOURS_disponibles_ils_sont_gratuits() -> None:
    """*Flo : « je ne veux rien de payant ». arXiv et HN sont ouverts, sans jeton.*"""
    noms = {s.nom for s in catalogue() if s.disponible}
    assert "arxiv" in noms and "hackernews" in noms and "stackexchange_quant" in noms


def test_arxiv_est_la_source_la_PLUS_fiable() -> None:
    """*Le code est une implementation ; le papier est le RAISONNEMENT.* Et il est relu."""
    cat = {s.nom: s.fiabilite for s in catalogue(jeton_github="x", jeton_x="x")}
    assert cat["arxiv"] > cat["hackernews"] > cat["x_twitter"]


def test_le_rapport_ANNONCE_les_sources_indisponibles() -> None:
    r = rapport_sources(catalogue())
    assert "x_twitter" in r["indisponibles"]
    assert "INDISPONIBLE" in r["avertissement"]
    assert "0,35" in r["note_x"] or "0.35" in r["note_x"]


def test_un_texte_vide_ne_marque_RIEN() -> None:
    v = juger("", source=_src("arxiv"))
    assert v.garde is False
