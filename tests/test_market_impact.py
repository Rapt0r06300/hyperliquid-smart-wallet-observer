"""L'impact de marché : un COÛT, qui se SOUSTRAIT — et jamais un zéro silencieux."""
from __future__ import annotations

from hl_observer.market.market_impact import edge_net_apres_impact, impact_bps


def test_impact_positif_et_croissant_avec_la_taille() -> None:
    petit = impact_bps(100.0, 10000.0)     # 1 % du carnet
    gros = impact_bps(1000.0, 10000.0)     # 10 % du carnet
    assert petit is not None and gros is not None
    assert 0.0 < petit < gros


def test_profondeur_inconnue_renvoie_None_pas_zero() -> None:
    assert impact_bps(100.0, 0.0) is None
    assert impact_bps(100.0, -5.0) is None
    assert impact_bps(100.0, None) is None   # type: ignore[arg-type]


def test_l_impact_se_SOUSTRAIT_de_l_edge() -> None:
    # edge brut 30 bps, impact 5 bps → edge net 25 bps (soustraction, pas addition)
    assert edge_net_apres_impact(30.0, 5.0) == 25.0
    # un impact plus gros que l'edge → edge net NÉGATIF (on ne le cache pas)
    assert edge_net_apres_impact(4.0, 10.0) == -6.0


def test_impact_inconnu_empeche_de_garantir_l_edge_net() -> None:
    assert edge_net_apres_impact(30.0, None) is None
