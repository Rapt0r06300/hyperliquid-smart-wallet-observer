"""#365 / X-04 / H-137 — funding arb PERP↔PERP. La voie de réouverture DÉSIGNÉE.

La zone morte `FUNDING_JAMBE_NUE` dit elle-meme comment sortir : *« une VRAIE jambe de couverture
(spot ou **perp oppose**) »*. Ce module l'emprunte. **Ce n'est pas un contournement.**

Mais la meme discipline s'applique : *le funding qu'on encaisse doit DOMINER ce que le prix nous
fait subir.* Sur la jambe nue, le ratio etait **0,0036** -- 281 bps de prix pour 1 bps de funding.

Aucun ordre reel.
"""
from __future__ import annotations

import math
import random

import pytest

from hl_observer.funding.funding_spread_perp_perp import (
    COUT_4_EXECUTIONS_BPS,
    MIN_POINTS,
    MIN_R2,
    MOTIF_COUTS_JAMAIS_AMORTIS,
    MOTIF_INSUFFISANT,
    MOTIF_PAS_UNE_COUVERTURE,
    MOTIF_RESIDU_DOMINE,
    beta_et_r2,
    evaluer_paire,
    residu_bps,
)


def _paire_correlee(n: int, *, beta: float, bruit_idio: float, seed: int):
    """B est un marche aleatoire ; A = beta*B + un bruit IDIOSYNCRATIQUE.

    `bruit_idio` EST le residu : c'est lui qui decide de tout.
    """
    r = random.Random(seed)
    pa, pb = [100.0], [50.0]
    for _ in range(n - 1):
        rb = r.gauss(0.0, 0.002)                       # 20 bps de vol par pas
        ra = beta * rb + r.gauss(0.0, bruit_idio)
        pb.append(pb[-1] * (1.0 + rb))
        pa.append(pa[-1] * (1.0 + ra))
    return pa, pb


# ============================================================ 1. LE BETA ET SON R²


def test_un_beta_SANS_R2_est_un_nombre_qui_ment():
    """Deux series INDEPENDANTES ont toujours un beta. Il ne veut simplement rien dire.
    C'est le R² qui dit si la « couverture » en est une."""
    r = random.Random(1)
    ra = [r.gauss(0, 0.01) for _ in range(500)]
    rb = [r.gauss(0, 0.01) for _ in range(500)]
    beta, r2 = beta_et_r2(ra, rb)
    assert r2 < 0.1, "R²=%.3f sur deux series INDEPENDANTES : le detecteur voit une couverture " \
                     "la ou il n'y en a pas" % r2


def test_le_beta_est_RETROUVE_sur_une_paire_construite():
    pa, pb = _paire_correlee(800, beta=2.0, bruit_idio=0.0002, seed=3)
    ra = [(pa[i] - pa[i - 1]) / pa[i - 1] for i in range(1, len(pa))]
    rb = [(pb[i] - pb[i - 1]) / pb[i - 1] for i in range(1, len(pb))]
    beta, r2 = beta_et_r2(ra, rb)
    assert beta == pytest.approx(2.0, abs=0.15)
    assert r2 > 0.8


# ============================================================ 2. LES TROIS PORTES


def test_donnees_insuffisantes_INSUFFICIENT_DATA():
    v = evaluer_paire("A", "B", [100.0] * 20, [50.0] * 20, 5.0, -2.0)
    assert v.viable is False
    assert v.motif == MOTIF_INSUFFISANT
    assert v.n_points < MIN_POINTS


def test_deux_perps_QUI_NE_BOUGENT_PAS_ENSEMBLE_ne_sont_PAS_une_couverture():
    """🔴 PORTE 1. Shorter l'un et longer l'autre, ce n'est alors pas une couverture :
    **c'est DEUX paris** -- et on paie 4 executions pour ca."""
    r = random.Random(5)
    pa = [100.0]
    pb = [50.0]
    for _ in range(500):
        pa.append(pa[-1] * (1 + r.gauss(0, 0.002)))
        pb.append(pb[-1] * (1 + r.gauss(0, 0.002)))    # INDEPENDANT
    v = evaluer_paire("A", "B", pa, pb, 5.0, -2.0)
    assert v.viable is False
    assert v.motif == MOTIF_PAS_UNE_COUVERTURE
    assert v.r2 < MIN_R2


def test_un_RESIDU_qui_domine_le_funding_est_le_MEME_PIEGE_que_la_jambe_nue():
    """🔴🔴 PORTE 2 -- LA QUESTION QUI DECIDE.

    Bien correles (R² eleve), mais le residu bouge beaucoup. On encaisse 3 bps/h de funding et le
    residu bouge de dizaines de bps/h.

    *C'est exactement ce qui a tue la jambe nue : ratio 0,0036, soit 281 bps de prix subi pour
    1 bps de funding encaisse. Ici on refait la meme chose -- en payant DEUX FOIS plus de frais.*
    """
    pa, pb = _paire_correlee(1000, beta=1.0, bruit_idio=0.0015, seed=7)   # gros residu
    v = evaluer_paire("A", "B", pa, pb, 2.0, -1.0, pas_par_heure=60.0)
    assert v.r2 >= MIN_R2, "le decor est faux : les deux perps doivent bouger ensemble"
    assert v.viable is False
    assert v.motif == MOTIF_RESIDU_DOMINE
    assert v.ratio < 1.0


def test_des_couts_JAMAIS_AMORTIS_font_refuser():
    """🔴 PORTE 3. Un ecart de funding minuscule met des centaines d'heures a payer 12 bps de
    couts. La correlation d'aujourd'hui ne survit pas a des centaines d'heures.

    🚩 MON 1er DECOR ETAIT FAUX : avec `bruit_idio=1e-5`, le residu valait deja 0,77 bps/h --
    soit **plus** que l'ecart de funding de 0,05. La PORTE 2 (le residu) tombait donc AVANT la
    porte 3, et le test rougissait. *Le code avait raison ; ma mise en scene ne testait pas ce
    qu'elle croyait.*
    Pour isoler la porte 3, il faut un residu VRAIMENT negligeable (1e-7).
    """
    pa, pb = _paire_correlee(1000, beta=1.0, bruit_idio=1e-7, seed=9)      # residu ~ 0,008 bps/h
    v = evaluer_paire("A", "B", pa, pb, 0.05, 0.0, pas_par_heure=60.0)     # ecart : 0,05 bps/h
    assert v.ratio > 1.0, "le decor est faux : le residu doit etre NEGLIGEABLE devant l'ecart"
    assert v.viable is False
    assert v.motif == MOTIF_COUTS_JAMAIS_AMORTIS
    assert v.heures_pour_amortir is not None
    assert v.heures_pour_amortir > 24.0


# ============================================================ 3. LE GARDE-FOU PEUT DIRE OUI


def test_une_VRAIE_couverture_avec_un_GROS_ecart_de_funding_est_VIABLE():
    """🚩 Le garde-fou doit pouvoir dire OUI. Sinon il refuse par principe : il ne mesure rien.

    Deux perps quasi identiques (residu minuscule) avec un ecart de funding enorme -> ca DOIT
    passer. Si ce test echoue, tout le module est VERT et AVEUGLE.
    """
    pa, pb = _paire_correlee(1200, beta=1.0, bruit_idio=0.000005, seed=13)
    v = evaluer_paire("A", "B", pa, pb, 6.0, -4.0, pas_par_heure=60.0)     # ecart ~ 10 bps/h
    assert v.r2 > MIN_R2
    assert v.viable is True, (
        "une couverture quasi parfaite avec 10 bps/h d'ecart de funding a ete REFUSEE : "
        "le module refuse tout par construction (residu=%.2f bps/h, ratio=%.3f)"
        % (v.residu_bps_h, v.ratio)
    )
    assert v.heures_pour_amortir is not None
    assert v.heures_pour_amortir < 24.0


def test_le_verdict_DIT_ce_qu_il_NE_MESURE_PAS():
    """⚠️ L'HONNETETE OBLIGATOIRE. Trois risques ne sont PAS modelises, et ils ne peuvent que
    DEGRADER le chiffre : la **liquidation** d'une jambe (T2b a divise le carry HYPE par DEUX),
    l'**ADL**, et la **rupture de correlation**.

    Un verdict « viable » qui ne le dit pas est un verdict qui MENT par omission -- exactement
    l'erreur que T2 avait commise en oubliant le capital de marge.
    """
    pa, pb = _paire_correlee(1200, beta=1.0, bruit_idio=0.000005, seed=13)
    v = evaluer_paire("A", "B", pa, pb, 6.0, -4.0, pas_par_heure=60.0)
    assert v.viable is True
    bas = v.note.lower()
    assert "liquidation" in bas
    assert "adl" in bas
    assert "correlation" in bas or "correlation" in bas


def test_le_residu_grandit_avec_le_bruit_idiosyncratique():
    """Sanite : plus les deux perps divergent, plus le residu est grand. Si ce n'etait pas le cas,
    la metrique qui decide de tout serait cassee."""
    ra = [0.001, -0.002, 0.003, -0.001] * 50
    rb = [0.001, -0.002, 0.003, -0.001] * 50
    assert residu_bps(ra, rb, 1.0) == pytest.approx(0.0, abs=1e-9)   # parfaitement couvert

    r = random.Random(2)
    ra2 = [x + r.gauss(0, 0.001) for x in rb]
    assert residu_bps(ra2, rb, 1.0) > 5.0                            # residu reel
