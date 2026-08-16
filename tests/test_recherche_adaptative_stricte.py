from __future__ import annotations

from pathlib import Path

from hl_observer.backtesting.recherche_adaptative_stricte import (
    cribler_train_only,
    chercher_copy_strict,
    write_strict_report,
)
from hl_observer.backtesting.recherche_scenario import DonneesReplay


def _candidate(ts: float) -> dict:
    return {
        "recorded_at": ts,
        "coin": "HYPE",
        "strategie": "copy",
        "signal_age_ms": 1_000,
        "consensus_wallets": 4,
        "liquidity_score": 0.9,
    }


def _fake_screen(train_is_good: bool = True):
    calls: list[list[float]] = []

    def screen(candidates, marks, *, base_config, horizon_min, cost_bps):
        timestamps = [float(row["recorded_at"]) for row in candidates]
        calls.append(timestamps)
        net = 1.0 if train_is_good else -1.0
        return {"arm_a": {"net_total_usd": net, "trades": len(candidates), "profit_factor": 1.2}}

    screen.calls = calls  # type: ignore[attr-defined]
    return screen


def test_crible_train_only_ne_voit_jamais_la_moitie_validation() -> None:
    candidates = [_candidate(float(i * 1_000)) for i in range(100)]
    data = DonneesReplay(candidats=candidates, marks=[])
    cfg = {"sl": 40.0, "tp": 80.0, "horizon_min": 1.0, "filtres": {}}
    screen = _fake_screen(True)

    kept, audit = cribler_train_only(data, [cfg], screen=screen, cap_candidats=1_000)
    train, validation = data.moities_avec_embargo(1.0)
    train_ts = {float(row["recorded_at"]) for row in train}
    validation_ts = {float(row["recorded_at"]) for row in validation}
    seen = {value for call in screen.calls for value in call}  # type: ignore[attr-defined]

    assert kept == [cfg]
    assert seen
    assert seen <= train_ts
    assert seen.isdisjoint(validation_ts)
    assert audit["validation_rows_seen"] == 0
    assert audit["validation_used_for_selection"] is False


def test_crible_peut_eliminer_un_perdant_train_sans_consulter_validation() -> None:
    candidates = [_candidate(float(i * 1_000)) for i in range(100)]
    data = DonneesReplay(candidats=candidates, marks=[])
    cfg = {"sl": 40.0, "tp": 80.0, "horizon_min": 1.0, "filtres": {}}
    screen = _fake_screen(False)

    kept, audit = cribler_train_only(data, [cfg], screen=screen, cap_candidats=1_000)
    assert kept == []
    assert audit["screened_configs"] == 1
    assert audit["validation_rows_seen"] == 0


def test_trop_peu_de_train_laisse_passer_au_lieu_dinventer_un_verdict() -> None:
    data = DonneesReplay(candidats=[_candidate(float(i * 1_000)) for i in range(20)], marks=[])
    cfg = {"sl": 40.0, "tp": 80.0, "horizon_min": 1.0, "filtres": {}}
    screen = _fake_screen(False)
    kept, audit = cribler_train_only(data, [cfg], screen=screen)
    assert kept == [cfg]
    assert audit["screened_configs"] == 0
    assert screen.calls == []  # type: ignore[attr-defined]


def _fake_full_ab(candidates, marks, *, base_config, horizon_min, cost_bps):
    # Le candidat n'est intéressant que pour vérifier le parcours, pas pour fabriquer un PnL.
    if cost_bps > 15:
        net = 1.0
    else:
        net = 2.0
    return {"arm_a": {"net_total_usd": net, "trades": 60, "profit_factor": 1.5}}


def test_recherche_stricte_ecrit_sa_preuve_train_only(tmp_path: Path) -> None:
    # Large séparation temporelle pour conserver >30 observations de chaque côté de l'embargo.
    candidates = [_candidate(float(i * 10_000)) for i in range(120)]
    data = DonneesReplay(candidats=candidates, marks=[])
    cfg = {"sl": 40.0, "tp": 80.0, "horizon_min": 1.0, "filtres": {}}
    result = chercher_copy_strict(
        tmp_path,
        configs=[cfg],
        donnees=data,
        evaluer_ab=_fake_full_ab,
        raffiner=False,
        max_essais=1,
    )
    assert result["strict_train_only"] is True
    assert result["scout_audit"]["validation_rows_seen"] == 0
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False

    path = write_strict_report(tmp_path, result)
    text = path.read_text(encoding="utf-8")
    assert '"strict_train_only": true' in text
    assert '"validation_rows_seen": 0' in text
