"""#410 / H-05 + #435 / H-30 — LA COUPE TRAIN/TEST FUYAIT. Purge + embargo (2026-07-13).

🔴 LA FUITE, EN CINQ LIGNES :

    def temporal_split(candidates, train_frac=0.7):
        k = int(len(cs) * train_frac)
        return cs[:k], cs[k:]              # AUCUNE purge. AUCUN embargo.

Un candidat en **fin de TRAIN** ouvre un trade dont la SORTIE arrive jusqu'a **8 HEURES** plus
tard -- donc **DANS la periode de TEST**. Son PnL d'entrainement etait calcule avec des prix du
test... et c'est sur ce train contamine qu'on **CHOISISSAIT** la config.

    **Le test etait deja dans le train.**

`purged_walk_forward_splits` (IDEA-30) existait POUR CA. **Il etait mort.**
*H-05 et H-30 pointaient un bug chez NOUS, pas une idee a copier chez eux.*

Aucun ordre reel.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hl_observer.backtesting.purged_split import (
    EMBARGO_FRACTION_DE_L_HORIZON,
    fuite_potentielle,
    purged_temporal_split,
)

RACINE = Path(__file__).resolve().parents[1]
SEARCH = RACINE / "src" / "hl_observer" / "backtesting" / "scenario_search.py"


def _cands(n: int, *, pas_s: float = 60.0):
    """n candidats, espaces d'une minute."""
    return [{"recorded_at": float(i) * pas_s, "coin": "BTC"} for i in range(n)]


# ============================================================ 1. 🔴 LA PURGE MORD


def test_un_candidat_dont_la_SORTIE_tombe_dans_le_TEST_est_PURGE():
    """🔴 LE TEST QUI JUSTIFIE TOUT LE MODULE.

    100 candidats, 1 par minute. Coupe a 70 % -> frontiere a t=70 min.
    Horizon de 30 min : un candidat entre a `t` sort au plus tard a `t+30`. Il est SAIN si
    `t + 30 <= 70`, donc `t <= 40`. Le train garde t=0..40 (**41** candidats) et en purge **29**.

    🚩 J'AVAIS ECRIT 30. **La borne est INCLUSIVE** : un trade qui sort EXACTEMENT a la frontiere
    ne fuit pas. Le code avait raison, mon arithmetique avait tort.
    *C'est la TROISIEME borne qui me mord aujourd'hui (#588, dead_zones:159, edge_calculator:64).*
    """
    c = purged_temporal_split(_cands(100), train_frac=0.7, horizon_min=30.0, embargo_min=0.0)
    assert c.n_purges == 29, (
        "%d candidats purges au lieu de 29 : la purge ne couvre pas exactement l'horizon"
        % c.n_purges
    )
    assert len(c.train) == 41
    # le dernier candidat du train sort AVANT la frontiere
    assert max(x["recorded_at"] for x in c.train) + 30 * 60 <= c.frontiere_ts


def test_un_horizon_de_ZERO_ne_purge_RIEN():
    """Sanite : sans horizon, il n'y a pas de fuite. Un garde-fou qui purge quand il n'y a rien
    a purger detruirait des donnees pour rien."""
    c = purged_temporal_split(_cands(100), train_frac=0.7, horizon_min=0.0, embargo_min=0.0)
    assert c.n_purges == 0
    assert len(c.train) == 70


def test_un_horizon_ENORME_vide_le_train_et_on_le_DIT():
    """Si l'horizon depasse toute la periode d'entrainement, il ne reste RIEN. Ce n'est pas un
    bug : c'est l'aveu que **l'echantillon est trop court pour cet horizon**.

    *Un backtest qui garderait quand meme des donnees ici serait un backtest qui triche.*
    """
    c = purged_temporal_split(_cands(100), train_frac=0.7, horizon_min=999.0, embargo_min=0.0)
    assert c.train == []
    assert c.valide is False


# ============================================================ 2. L'EMBARGO


def test_l_embargo_ecarte_les_premiers_candidats_du_TEST():
    c = purged_temporal_split(_cands(100), train_frac=0.7, horizon_min=10.0, embargo_min=15.0)
    assert c.n_embargo == 15
    assert min(x["recorded_at"] for x in c.test) >= c.frontiere_ts + 15 * 60


def test_l_embargo_par_defaut_est_une_FRACTION_DE_L_HORIZON_pas_une_CONSTANTE():
    """🚩 MA 1re VERSION LE FIXAIT A **30 MINUTES EN DUR**.

    Sur un jeu ou la periode de test dure 8 minutes, il l'a **entierement mangee** -- le test a
    rougi, a raison.

    Un embargo constant est un **nombre invente**. L'auto-correlation qu'il doit briser vit a
    l'echelle de temps du TRADE (son horizon), pas a une echelle que j'aurais choisie.
    *Une constante qu'on ne peut pas justifier est une constante qui finira par mentir.*
    """
    assert 0.0 < EMBARGO_FRACTION_DE_L_HORIZON < 1.0
    c = purged_temporal_split(_cands(1000), train_frac=0.7, horizon_min=100.0)
    assert c.embargo_min == pytest.approx(10.0)          # 10 % de 100 min
    petit = purged_temporal_split(_cands(1000), train_frac=0.7, horizon_min=2.0)
    assert petit.embargo_min == pytest.approx(0.2)       # il s'ADAPTE, il n'ecrase pas


# ============================================================ 3. LE CHIFFRE DE LA FAUTE


def test_on_MESURE_de_combien_l_ancienne_coupe_TRICHAIT():
    """C'est ce que H-30 appelle `lookahead-analysis` : *de combien mon backtest triche-t-il ?*

    Un chiffre, pas une impression. Avec un horizon de 8 h (notre plafond reel) sur des candidats
    espaces d'une minute : frontiere a t=700, un candidat est sain si `t + 480 <= 700`, soit
    `t <= 220` -> **221 sains, 479 qui FUYAIENT**.

    🔴 **479 candidats sur 700, soit 68 % du train, avaient leur SORTIE dans la periode de TEST.**
    C'est enorme. Le « hors echantillon » n'en etait pas un.
    """
    r = fuite_potentielle(_cands(1000), train_frac=0.7, horizon_min=480.0)   # 8 h
    assert r["n_candidats_qui_FUYAIENT"] == 479
    assert r["part_du_train_contaminee"] == pytest.approx(479 / 700, rel=0.01)
    assert r["part_du_train_contaminee"] > 0.6, (
        "plus de 60 %% du train etait contamine par le test. Ce n'est pas un detail."
    )
    assert "FUYAIENT" in r["verdict"] or "🔴" in r["verdict"]


def test_sans_fuite_le_verdict_le_DIT_aussi():
    r = fuite_potentielle(_cands(1000), train_frac=0.7, horizon_min=0.0)
    assert r["n_candidats_qui_FUYAIENT"] == 0
    assert "AUCUNE FUITE" in r["verdict"]


# ============================================================ 4. L'INVARIANT DE CABLAGE


def test_la_purge_est_REELLEMENT_APPELEE_par_scenario_search():
    """*Un import n'est pas un appel.* Sept garde-fous anti-overfit existaient, testes,
    documentes -- **et aucun n'etait appele** (M-19). Celui-ci ne rejoindra pas le cimetiere."""
    arbre = ast.parse(SEARCH.read_text(encoding="utf-8"))
    appels = {
        (n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", ""))
        for n in ast.walk(arbre) if isinstance(n, ast.Call)
    }
    assert "purged_temporal_split" in appels, (
        "🔴 la purge n'est plus appelee par scenario_search : la coupe train/test fuit de nouveau."
    )


def test_les_DEUX_chemins_de_recherche_sont_PURGES():
    """`search()` ET `search_over_db()`.

    *Une jambe reparee et l'autre laissee, c'est une jambe laissee.* (Le poller L2 nous l'a appris :
    funding repare le 08/07, carnet oublie -- et personne ne s'en est apercu pendant 4 jours.)
    """
    src = SEARCH.read_text(encoding="utf-8")
    assert src.count("purged_temporal_split(") >= 2, (
        "un seul des deux chemins de recherche est purge : l'autre fuit encore"
    )


def test_la_coupe_DIT_ce_qu_elle_a_JETE():
    """Une purge silencieuse serait une purge inutile : personne ne saurait que le chiffre d'avant
    etait FAUX."""
    src = SEARCH.read_text(encoding="utf-8")
    assert "coupe_purgee" in src, (
        "le rapport ne dit pas combien de candidats ont ete purges : la correction est invisible"
    )
