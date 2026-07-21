r"""LE PLAN DE SCAN — *ces tests empechent le scan de redevenir aveugle.*

═══════════════════════════════════════════════════════════════════════════════════════════════
LE DEFAUT LE PLUS IRONIQUE DU PROJET
═══════════════════════════════════════════════════════════════════════════════════════════════

Le scan commencait a `stars:5..20`, avec ce commentaire :

    # On ignore < 5 etoiles

Or la moisson de **5 617 repos** a **MESURE** que les **4 repos les plus exactement sur cible**
avaient **1, 2, 3 et 3 etoiles** :

    Giri-Aayush/hyperliquid-data-pipeline   position FIFO **depuis le noeud**
    horn111/hip4-mm-simulator               file par volume cumule, latence 50 ms
    zer0cache/hyperliquid-market-maker-bot  MarkoutTracker
    mackinac/dex-exec                       la jambe de couverture de T2

    ***Le scan ecartait A L'ENTREE exactement le profil qu'on a mesure comme le meilleur.***

C'est **le meme prejuge** (« etoiles = qualite ») que celui qu'on venait de tuer dans le TRI.
Il vivait aussi dans le **SCAN**, et personne ne s'en plaignait. **19e forme de la maladie.**

Aucun ordre reel. Aucun reseau. Lecture seule.
"""
from __future__ import annotations

import pytest

from hl_observer.research.github_scan_plan import (
    REQUETES_CODE,
    TRANCHES_ETOILES,
    TRIS,
    deduplique,
    plan_de_scan,
    resume,
    tranches_de_dates,
)

SUJETS = ["market-making", "hyperliquid"]
TEXTE = ["hyperliquid funding bot"]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  1. 🔴 LE TEST QUI COMPTE — le scan ne doit PLUS s'interdire les petites etoiles.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_LE_SCAN_NE_S_INTERDIT_PLUS_les_repos_sous_5_etoiles() -> None:
    """🔑 **LE TEST CENTRAL.**

    *Les 4 repos les plus exactement sur cible avaient 1, 2, 3 et 3 etoiles.*
    Un repo a 0 etoile n'est pas « mauvais » : c'est un repo **que personne n'a encore lu**.
    """
    assert "0..1" in TRANCHES_ETOILES, (
        "REGRESSION : le scan s'interdit de nouveau les repos < 2 etoiles -- "
        "***c'est-a-dire exactement le profil qu'on a MESURE comme le meilleur.***"
    )
    assert "2..4" in TRANCHES_ETOILES, "3 des 4 meilleures cibles sont dans cette tranche"


def test_les_petites_tranches_arrivent_AVANT_les_grosses() -> None:
    """*Un scan peut etre interrompu (Ctrl-C, quota). Ce qu'on met en premier est ce qu'on aura.*"""
    assert TRANCHES_ETOILES.index("0..1") < TRANCHES_ETOILES.index(">800")


def test_le_plan_signale_EXPLICITEMENT_la_tranche_qu_on_s_interdisait() -> None:
    """*Un plan qui ne dit pas ce qu'il repare laissera quelqu'un le re-casser.*"""
    p = plan_de_scan(SUJETS, TEXTE, avec_dates=False)
    petites = [r for r in p if "stars:0..1" in r.q]
    assert petites
    assert any("interdisait" in r.pourquoi for r in petites)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  2. LE PLAFOND DE 1 000 — les tranches d'etoiles ne le franchissent que x5.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_la_partition_par_DATE_fait_tomber_le_plafond() -> None:
    """`created:2024-01-01..2024-03-31` est une requete **differente** : son propre quota de 1000.

    24 tranches = **24 000 resultats** la ou les etoiles n'en donnaient que 5 000.
    """
    d = tranches_de_dates(2020, 2025, mois_par_tranche=3)
    assert len(d) == 6 * 4, "6 ans x 4 trimestres = 24 tranches"
    assert all(x.startswith("created:") for x in d)
    assert "created:2020-01-01..2020-03-31" in d
    assert "created:2025-10-01..2025-12-31" in d


def test_les_tranches_de_dates_ne_se_CHEVAUCHENT_pas_et_ne_laissent_aucun_TROU() -> None:
    """*Un trou dans la partition, c'est une periode qu'on ne scannera JAMAIS.*"""
    from datetime import date as _d

    d = tranches_de_dates(2023, 2024, mois_par_tranche=3)
    bornes = []
    for x in d:
        a, b = x.replace("created:", "").split("..")
        bornes.append((_d.fromisoformat(a), _d.fromisoformat(b)))
    bornes.sort()
    for i in range(1, len(bornes)):
        assert bornes[i][0].toordinal() == bornes[i - 1][1].toordinal() + 1, (
            "trou ou chevauchement entre %s et %s" % (bornes[i - 1], bornes[i]))
    assert bornes[0][0] == _d(2023, 1, 1)
    assert bornes[-1][1] == _d(2024, 12, 31)


def test_une_partition_MENSUELLE_est_possible_pour_creuser_encore() -> None:
    assert len(tranches_de_dates(2024, 2024, mois_par_tranche=1)) == 12


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  3. 🔑 CHERCHER DANS LE **CODE** — la seule source qui ne peut pas mentir.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_LE_SCAN_CHERCHE_ENFIN_DANS_LE_CODE() -> None:
    """***Le README est la page de vente. Le code est la verite.***

    `/search/code` trouve un repo **sans topic, sans etoile, et dont le README ne dit rien**.
    """
    p = plan_de_scan(SUJETS, TEXTE, avec_code=True, avec_dates=False)
    codes = [r for r in p if r.genre == "code"]
    assert len(codes) >= 12, "le scan doit chercher DANS le code, pas seulement dans les metadonnees"


def test_les_requetes_CODE_visent_des_choses_qu_on_ne_SAIT_PAS_faire() -> None:
    """*Chaque requete code vient d'un trou MESURE, pas d'un mot a la mode.*"""
    joint = " ".join(q + " " + p for q, p in REQUETES_CODE).lower()
    assert "qty_ahead" in joint          # la position dans la file
    assert "kappa" in joint              # l'intensite de fill, jamais mesuree
    assert "embargo" in joint            # notre coupe train/test FUYAIT
    assert "liquidationpx" in joint      # la derniere piste non mesuree
    for q, pourquoi in REQUETES_CODE:
        assert q and len(pourquoi) > 15, "une requete sans motif est du bruit"


def test_le_CODE_est_cherche_EN_PREMIER_car_le_quota_peut_tout_couper() -> None:
    """*Un scan peut mourir sur le quota. Ce qu'on met en premier est ce qu'on est SUR d'avoir.*"""
    p = plan_de_scan(SUJETS, TEXTE, avec_code=True)
    assert p[0].genre == "code"


def test_on_DIT_que_la_recherche_code_EXIGE_un_token_on_ne_fait_pas_semblant() -> None:
    r = resume(plan_de_scan(SUJETS, TEXTE))
    assert "token" in r["avertissement_token"].lower()
    assert "impossible" in r["avertissement_token"].lower()


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  4. LE TRI — `sort=stars` re-commettait le defaut n°1 a CHAQUE requete.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_on_n_utilise_PAS_QUE_le_tri_par_etoiles() -> None:
    """Avec un plafond a 1 000, `sort=stars` ne montre **que les gros**.

    C'est-a-dire qu'il **re-commet le defaut n°1** a chaque requete.
    """
    assert len(set(TRIS)) >= 3
    p = plan_de_scan(SUJETS, TEXTE, avec_dates=False)
    tris = {r.tri for r in p if r.genre == "repo"}
    assert len(tris) >= 3, "un seul tri = un seul point de vue = un angle mort"


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  5. LE PLAN LUI-MEME
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_CHAQUE_requete_porte_sa_PROVENANCE() -> None:
    """*Une requete sans motif est du bruit -- et on ne saura jamais pourquoi on l'a lancee.*"""
    for r in plan_de_scan(SUJETS, TEXTE):
        assert r.q and r.pourquoi, "requete sans motif : %r" % (r,)


def test_le_plan_est_DEDUPLIQUE_le_quota_est_notre_limite() -> None:
    p = plan_de_scan(SUJETS, TEXTE)
    assert len(deduplique(p)) == len({(r.q, r.genre, r.tri) for r in p})


def test_le_plan_est_CHIFFRABLE_donc_budgetable() -> None:
    """*Un plan qu'on ne peut pas chiffrer est un plan qu'on ne peut pas budgeter.*"""
    r = resume(plan_de_scan(SUJETS, TEXTE))
    assert r["n_requetes"] > 0
    assert r["n_code"] > 0 and r["n_repo"] > 0
    assert r["minutes_estimees"] > 0


def test_la_partition_par_date_AUGMENTE_vraiment_la_couverture() -> None:
    sans = len(plan_de_scan(SUJETS, TEXTE, avec_dates=False))
    avec = len(plan_de_scan(SUJETS, TEXTE, avec_dates=True))
    assert avec > sans * 2, "la partition par date doit ouvrir BEAUCOUP plus de terrain"


@pytest.mark.parametrize("sujets,texte", [([], []), (["x"], []), ([], ["y"])])
def test_un_plan_vide_ne_plante_PAS_il_renvoie_ce_qu_il_peut(sujets, texte) -> None:
    p = plan_de_scan(sujets, texte)
    assert isinstance(p, list)
    assert all(r.q for r in p)
