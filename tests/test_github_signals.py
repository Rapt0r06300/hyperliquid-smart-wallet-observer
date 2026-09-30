r"""LE TRI DU MOISSONNEUR — *ces tests empechent le retour du bavardage.*

═══════════════════════════════════════════════════════════════════════════════════════════════
LE BUG QU'ILS VERROUILLENT — mesure sur 5 617 repos REELS
═══════════════════════════════════════════════════════════════════════════════════════════════

L'ancien tri comptait **combien de concepts un README mentionne**. Mesure :

    n_concepts = 0   ->  mediane **15 etoiles**
    n_concepts = 12  ->  mediane **5 etoiles**       ***ANTI-CORRELE.***

Le champion (12/13 concepts) a **5 etoiles** et un README qui **recite le catalogue du metier**.

    🔑 ***Le grep mesurait la VERBOSITE, pas la SUBSTANCE.***

C'est la meme faute que `signal_age` (une tautologie) ou le voyant securite soude au vert :
**une metrique qui a l'air rigoureuse et qui mesure autre chose.**

Ces tests opposent, a chaque fois, **un README BAVARD** a **un README SUBSTANTIEL**.
Si le bavard repasse devant, ils tombent.

Aucun ordre reel. Lecture seule.
"""
from __future__ import annotations

import pytest

from hl_observer.research.github_signals import (
    Signaux,
    analyser,
    fichiers_a_lire,
    liste_de_lecture,
    score,
    trier,
)

# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  LES DEUX README QUI RESUMENT TOUT LE PROBLEME
# ═══════════════════════════════════════════════════════════════════════════════════════════════

# 🔴 LE BAVARD — il RECITE le catalogue. C'est le vrai champion de l'ancien tri (5 etoiles).
BAVARD = """
# Quant Finance Library
A comprehensive library covering market making, Avellaneda-Stoikov, queue position,
adverse selection, market impact, funding rates, liquidation, mempool, latency,
walk-forward validation, lookahead bias, order book reconstruction and kappa estimation.
The ultimate toolkit for profitable algorithmic trading. Guaranteed profit!
"""

# ✅ LE SUBSTANTIEL — il POSE une formule, il AVOUE une limite, il DONNE un chiffre.
SUBSTANTIEL = """
# hl-queue-model
We estimate the fill intensity as lambda(delta) = A * exp(-kappa * delta), fitting kappa
per coin from L2 deltas and trades.

## Limitations
This is **not a substitute for real L3 data**: we only approximate queue position from
level-2 deltas. On thin books the estimate is unrealistic.

## Results
Round-trip cost 9.0 bps. Measured edge: -7.97 bps over 24133 out-of-sample signals.
It didn't work. We publish it anyway.
"""


def test_LE_TEST_QUI_COMPTE_le_substantiel_bat_le_bavard() -> None:
    """🔑 **LE TEST CENTRAL.** Le bavard cite 10 concepts ; le substantiel en cite 2.

    ***L'ancien tri classait le bavard PREMIER.*** Si ce test tombe, on est retombe dedans.
    """
    s_bav = score(analyser(BAVARD), etoiles=5)
    s_sub = score(analyser(SUBSTANTIEL), etoiles=3)
    assert s_sub > s_bav, (
        "REGRESSION : le README BAVARD (%0.1f) repasse devant le SUBSTANTIEL (%0.1f). "
        "Le tri mesure de nouveau la VERBOSITE, pas la substance." % (s_bav, s_sub)
    )


def test_le_bavard_est_meme_PENALISE_car_il_promet_sans_douter() -> None:
    """*« Guaranteed profit » : promettre sans jamais douter est une signature d'arnaque.*"""
    sig = analyser(BAVARD)
    assert sig.promesses_creuses, "« Guaranteed profit ! » doit etre releve"
    assert not sig.aveux, "le bavard n'avoue JAMAIS rien -- c'est precisement le probleme"


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  1. LES FORMULES — *un nom propre se copie ; une formule se pose.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_citer_un_nom_ne_suffit_PAS_il_faut_la_formule() -> None:
    """« Avellaneda-Stoikov » est **gratuit**. `A * exp(-kappa * delta)` engage."""
    nom_seul = analyser("We use the Avellaneda-Stoikov market making model.")
    la_formule = analyser("lambda(delta) = A * exp(-kappa * delta)")
    assert nom_seul.n_formules == 0, "citer un nom propre n'est PAS poser une formule"
    assert la_formule.n_formules >= 1
    assert "kappa_intensite_de_fill" in la_formule.formules


@pytest.mark.parametrize("txt,attendu", [
    ("qty_ahead = cumulative volume before our order", "position_dans_la_file"),
    ("sinh(x) appears in the GLFT closed form", "gueant_lehalle_glft"),
    ("impact = Y * sigma * sqrt(volume / adv)", "impact_racine_carree"),
    ("round-trip cost is 23.0 bps", "cout_chiffre_en_bps"),
    ("solving the Hamilton-Jacobi-Bellman equation", "controle_stochastique"),
    ("we compute the micro-price from order flow imbalance", "microprix"),
])
def test_chaque_formule_est_reconnue(txt: str, attendu: str) -> None:
    assert attendu in analyser(txt).formules


def test_une_formule_porte_toujours_sa_PREUVE() -> None:
    """*Un score sans preuve est un score qu'on ne peut pas contester -- donc pas corriger.*"""
    sig = analyser(SUBSTANTIEL)
    for _concept, preuves in sig.formules.items():
        assert preuves and all(isinstance(p, str) and p for p in preuves)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  2. 🔑 LES AVEUX — *la seule signature possible de l'honnetete.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("aveu", [
    "not a substitute for real VPIN",
    "it didn't work",
    "we lost money on this",
    "the backtest was misleading",
    "Known limitations: assumes instant fills",
    "this is unrealistic on thin books",
    "the model is overfit",
    "educational purposes only",
    "ne marche pas en production",
])
def test_un_aveu_de_limite_est_TOUJOURS_releve(aveu: str) -> None:
    """***Dans un corpus ou tout le monde promet de l'alpha, l'aveu est le seul signal vrai.***"""
    assert analyser(aveu).aveux, "aveu manque : %r" % aveu


def test_l_aveu_pese_PLUS_qu_une_formule() -> None:
    """C'est **notre propre critere** : on valorise « je ne sais pas » plutot que l'affirmation."""
    from hl_observer.research.github_signals import POIDS_AVEU, POIDS_FORMULE
    assert POIDS_AVEU > POIDS_FORMULE, (
        "l'aveu de limite doit rester le signal le PLUS fort : c'est la seule chose "
        "qu'un README menteur ne peut pas simuler"
    )


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  3. LES ETOILES NE SONT PAS LA CREDIBILITE
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_les_etoiles_ne_peuvent_PAS_sauver_un_repo_creux() -> None:
    """🔴 Les 4 repos les plus **exactement** sur cible avaient **1, 2, 3 et 3 etoiles**.

    Un repo a 20 000 etoiles sans une seule formule ni un seul aveu ne doit **pas** passer
    devant un repo a 2 etoiles qui pose sa formule et avoue sa limite.
    """
    creux_celebre = score(analyser("An awesome trading bot. Very fast."), etoiles=20_000)
    obscur_serieux = score(analyser(SUBSTANTIEL), etoiles=2)
    assert obscur_serieux > creux_celebre, (
        "REGRESSION : les etoiles ecrasent la substance (%0.1f vs %0.1f). "
        "hftbacktest etait bon MALGRE ses etoiles, pas grace a elles."
        % (creux_celebre, obscur_serieux)
    )


def test_un_texte_vide_ne_marque_RIEN_jamais_un_score_positif() -> None:
    for vide in ("", None):
        s = analyser(vide)          # type: ignore[arg-type]
        assert s.n_formules == 0 and not s.aveux and not s.chiffres
        assert score(s, etoiles=0) == 0.0


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  4. 🔑 LA LISTE DE LECTURE — *trier ne remplacera jamais LIRE.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_on_selectionne_les_fichiers_de_CODE_pas_le_bruit() -> None:
    arbre = [
        "src/queue_model.py",          # ✅
        "src/latency.rs",              # ✅
        "README.md",                   # ❌ pas du code
        "tests/test_queue.py",         # ❌ un test
        "examples/queue_demo.py",      # ❌ un exemple
        "vendor/queue.py",             # ❌ dependance tierce
        "docs/queue.md",               # ❌ doc
        "src/random_utils.py",         # ❌ hors sujet
        "src/funding_carry.py",        # ✅
    ]
    f = fichiers_a_lire(arbre)
    assert "src/queue_model.py" in f
    assert "src/latency.rs" in f
    assert "src/funding_carry.py" in f
    assert "README.md" not in f
    assert "tests/test_queue.py" not in f
    assert "src/random_utils.py" not in f


def test_LA_SORTIE_QUI_COMPTE_un_fichier_une_ligne_un_pourquoi() -> None:
    """***8 passes de tri sur 5 617 repos -> 3 idees.
       20 min a lire le code d'UN repo -> 5 bugs dans notre simu.***

    -> le livrable du moissonneur n'est **pas un classement**, c'est une **liste de lecture**.
    """
    src = "\n".join([
        "def fill_prob(delta):",
        "    # lambda = A * exp(-kappa * delta)",
        "    return A * math.exp(-kappa * delta)",
        "",
        "# NOTE: this assumes instant fills, which is unrealistic",
        "x = 1",
    ])
    lus = liste_de_lecture("owner/repo", "src/fill.py", src)
    assert lus, "la liste de lecture ne doit pas etre vide sur ce code"
    assert all(x.ligne > 0 for x in lus), "une ligne sans numero n'est pas une adresse"
    assert all(x.code for x in lus), "une lecture sans le CODE est inutile"
    assert any("FORMULE" in x.pourquoi for x in lus)
    assert any("AVEU" in x.pourquoi for x in lus), (
        "l'aveu de limite doit remonter jusque dans le CODE, pas seulement dans le README"
    )


def test_une_ligne_minifiee_n_est_PAS_du_code_lisible() -> None:
    """*Un blob de 5 000 caracteres n'est pas une ligne a lire : c'est de la donnee.*"""
    assert liste_de_lecture("o/r", "f.js", "kappa=" + "x" * 500) == []


def test_le_classement_se_fait_sur_la_SUBSTANCE() -> None:
    rs = [
        {"nom": "bavard", "score_substance": 12.0},
        {"nom": "substantiel", "score_substance": 48.0},
        {"nom": "creux", "score_substance": -25.0},
    ]
    assert [r["nom"] for r in trier(rs)] == ["substantiel", "bavard", "creux"]


def test_Signaux_expose_ses_preuves_pour_l_audit() -> None:
    d = analyser(SUBSTANTIEL).as_dict()
    for cle in ("formules", "aveux_de_limite", "chiffres_verifiables", "promesses_creuses"):
        assert cle in d
