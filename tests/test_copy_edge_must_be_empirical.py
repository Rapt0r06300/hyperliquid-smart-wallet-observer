"""LE 2e EDGE FABRIQUÉ — neutralisé au goulot commun de la copie (2026-07-11).

`fresh_opportunity._expected_edge_bps` produisait l'« edge attendu » d'un signal de copie ainsi :

    score × 0,55  +  wallets × 9  +  notional / 25 000  +  tightness × 10

Aucune de ces constantes ne vient d'une mesure. **Ce nombre n'a jamais touché un prix.**
`realtime_magic_score` le prenait, le multipliait par la fraîcheur, lui soustrayait des coûts, le
comparait à un seuil — et ouvrait. Tout cet appareil de rigueur s'appliquait à une fiction.
*Une fiction qui décroît reste une fiction.*

`score_realtime_copy_candidate` est le point de passage COMMUN de tous les chemins de copie
(viral_bot_engine, fresh_opportunity, pipeline_integrator). Le gate est posé là : un seul endroit,
tous les chemins couverts.

Règle : **l'appelant doit DÉCLARER que son edge est mesuré. Par défaut : non → NO_TRADE.**

Aucun ordre réel.
"""
from __future__ import annotations

import dataclasses

from hl_observer.copying.realtime_magic_score import (
    RealtimeCopyScoreInput,
    score_realtime_copy_candidate,
)

_CHAMPS = {f.name for f in dataclasses.fields(RealtimeCopyScoreInput)}


def _candidat(**surcharges) -> RealtimeCopyScoreInput:
    """Un candidat PARFAIT par ailleurs : frais, liquide, consensuel, edge élevé.
    S'il est refusé, ce ne peut être QUE pour l'empiricité de son edge."""
    base = dict(
        action_type="OPEN_LONG", direction="LONG",
        leader_expected_edge_bps=60.0,          # un edge énorme... mais inventé
        leader_consistency_factor=1.0,
        signal_age_ms=500,                      # très frais
        liquidity_score=0.9,                    # très liquide
        consensus_wallets=3,                    # consensus
        leader_score=90.0,                      # excellent leader
        leader_reference_price=100.0, current_mid=100.0,
        leader_notional_usdt=10_000.0,
        current_open_exposure_usdt=0.0, current_open_positions=0, max_open_positions=12,
    )
    base.update(surcharges)
    return RealtimeCopyScoreInput(**{k: v for k, v in base.items() if k in _CHAMPS})


# ------------------------------------------------------------------ LE gate

def _sans_table_mesuree(tmp_path, monkeypatch) -> None:
    """AUCUNE table d'edge mesuree. C'est l'etat par defaut de la verite : on ne SAIT pas.

    REECRIT LE 2026-07-12. Ces tests posaient `edge_is_empirical=False` sur l'ENTREE et
    attendaient un refus. Ca marchait tant que l'empiricite se DECLARAIT. Depuis Q1, elle se
    DERIVE : c'est la table mesuree qui tranche, et l'appelant n'a plus voix au chapitre --
    precisement parce que "l'appelant declare" etait la porte par laquelle un `True` ecrit en
    dur a laisse passer un 3e edge fabrique.

    L'intention du test est INCHANGEE et reste la bonne : un edge qui ne vient pas d'une mesure
    ne doit rien autoriser. Seul le levier change. On le tire donc au bon endroit.

    2e REECRITURE (#594, 13/07) : la porte a encore change de serrure -- et c'est la BONNE fois.
    Le scoreur lisait `empirical_edge` (table indexee sur le seul age) alors que le chemin LIVE
    mesurait deja par `edge_source` (Q1 : coin x age x score x consensus, borne basse,
    anti-lookahead). DEUX tables ; la plus pauvre gagnait. On a supprime la seconde.
    Pour retirer la mesure, il faut donc retirer la table Q1 -- pas l'autre.
    """
    monkeypatch.setenv(
        "HYPERSMART_EDGE_CALIBRATION_PATH", str(tmp_path / "aucune_table.json")
    )
    monkeypatch.delenv("HYPERSMART_EDGE_TABLE_PATH", raising=False)   # la TEST_FIXTURE de conftest
    monkeypatch.setenv("HYPERSMART_ROOT", str(tmp_path))              # ... et rien dans la racine

    from hl_observer.edge.edge_source import vider_le_cache

    vider_le_cache()


def test_a_perfect_candidate_with_a_fabricated_edge_is_REFUSED(tmp_path, monkeypatch):
    """LE TEST QUI COMPTE. Signal frais, liquide, consensuel, edge de 60 bps — et REFUSÉ,
    parce que ces 60 bps sortent d'une formule, pas d'un prix.

    Avant : ce candidat ouvrait une position. C'est ainsi qu'on perdait de l'argent avec méthode.
    """
    _sans_table_mesuree(tmp_path, monkeypatch)
    r = score_realtime_copy_candidate(_candidat())
    assert r.accepted is False
    assert any("EDGE" in motif for motif in r.refusal_reasons), (
        f"aucun motif d'edge dans {r.refusal_reasons} : sans table mesuree, un candidat "
        "parfait par ailleurs doit etre refuse POUR SON EDGE, et le dire."
    )


def test_the_default_is_to_refuse_not_to_trust(tmp_path, monkeypatch):
    """DENY-BY-DEFAULT : sans mesure, on refuse. C'est la seule position sûre.

    Et le candidat a beau porter 60 bps d'edge sur lui-meme : ce nombre n'a plus aucun pouvoir.
    """
    _sans_table_mesuree(tmp_path, monkeypatch)
    r = score_realtime_copy_candidate(_candidat(leader_expected_edge_bps=5_000.0))
    assert r.accepted is False, (
        "un signal s'est declare 5 000 bps d'edge et a ete cru, alors qu'AUCUNE mesure "
        "n'existe. C'est exactement le mecanisme des edges fabriques."
    )


def test_a_measured_edge_passes_the_gate():
    """Symétrie : un edge MESURE (table Q1 TEST_FIXTURE posee par conftest) passe.
    Le gate ne bloque pas tout — il bloque ce qui n'est pas mesure."""
    r = score_realtime_copy_candidate(_candidat())
    assert r.accepted is True
    assert "EDGE_NOT_EMPIRICAL_NO_TRADE" not in r.refusal_reasons
    assert "EDGE_FROM_MEASURED_TABLE" in r.warnings, "l'edge doit venir de la TABLE (porte Q1)"


def test_the_flag_can_restore_the_old_path_for_A_B_only(tmp_path, monkeypatch):
    """L'ancien chemin (edge inventé) reste atteignable pour COMPARER — jamais par défaut.

    #594 : le levier a change de nom. `HYPERSMART_REQUIRE_EMPIRICAL_EDGE=0` visait la table
    `empirical_edge`, qui n'est plus consultee. Le levier officiel est celui de la porte unique :
    `HYPERSMART_EDGE_SOURCE=formule` -- et il est MEILLEUR, car la valeur qui en sort est
    ESTAMPILLEE `fabrique=True` / `EDGE_FABRIQUE_FORMULE`. On peut mentir a la machine ; on ne se
    ment plus a soi-meme.
    """
    _sans_table_mesuree(tmp_path, monkeypatch)
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", "formule")
    r = score_realtime_copy_candidate(_candidat())
    assert "EDGE_NOT_EMPIRICAL_NO_TRADE" not in r.refusal_reasons
    assert "EDGE_FABRIQUE_FORMULE" in r.warnings, (
        "le mode A/B doit ESTAMPILLER la valeur comme fabriquee -- sinon on retombe dans le "
        "peche d'origine : un chiffre invente qui se fait passer pour une mesure"
    )


# ------------------------------------------------------------------ le gate ne relâche jamais

def test_a_broken_gate_refuses_it_never_opens():
    """FAIL-SAFE : si le contrôle d'empiricité plante, on REFUSE. Un gate cassé ne doit jamais
    devenir une autorisation — c'est le bug « fail-open » déjà trouvé ailleurs."""
    import hl_observer.copying.realtime_magic_score as mod

    src = mod.score_realtime_copy_candidate.__code__.co_consts
    assert any(isinstance(c, str) and c == "EDGE_EMPIRICITY_CHECK_FAILED" for c in src), (
        "le chemin d'erreur du gate n'existe pas : un plantage pourrait laisser passer un trade"
    )


def test_an_empirical_edge_still_faces_the_other_gates():
    """Un edge mesuré n'est PAS un laissez-passer : les autres refus tiennent toujours."""
    r = score_realtime_copy_candidate(
        _candidat(edge_is_empirical=True, liquidity_score=0.01)      # marché illiquide
    )
    assert r.accepted is False
    assert "LIQUIDITY_TOO_LOW" in r.refusal_reasons
