from hl_observer.signals.fill_admission import (
    FillAdmission,
    KIND_ENTRY,
    KIND_EXIT,
    KIND_SKIP,
    R_FRESH_ENTRY,
    R_STALE_BACKFILL,
    R_NO_POSITION_FOR_EXIT,
)
from hl_observer.signals.entry_supply_diagnostics import (
    CycleEvent,
    build_entry_supply_report,
    format_entry_supply_report,
    BOTTLENECK_SUPPLY,
    BOTTLENECK_GATES,
    BOTTLENECK_OK,
    BOTTLENECK_NO_DATA,
)
from hl_observer.calibration.shadow_runner import ShadowCalibrationRunner


def _entry(fresh=True, accepted=None, refusal=None):
    adm = FillAdmission(admit=True, kind=KIND_ENTRY, reason=R_FRESH_ENTRY, age_ms=2000, log_decision=True, is_fresh=fresh)
    return CycleEvent(admission=adm, accepted=accepted, refusal_reason=refusal)


def _skip(reason):
    adm = FillAdmission(admit=False, kind=KIND_SKIP, reason=reason, age_ms=0, log_decision=False, is_fresh=False)
    return CycleEvent(admission=adm)


# ---------- A. Entry-supply diagnostics ----------

def test_bottleneck_no_data():
    r = build_entry_supply_report([])
    assert r.bottleneck == BOTTLENECK_NO_DATA


def test_bottleneck_supply_when_no_fresh_entry():
    # Que du bruit (backfill / close-sans-position), aucune entrée fraîche
    events = [_skip(R_STALE_BACKFILL)] * 900 + [_skip(R_NO_POSITION_FOR_EXIT)] * 100
    r = build_entry_supply_report(events)
    assert r.candidates == 1000 and r.skipped == 1000
    assert r.fresh_entries == 0 and r.admitted_entries == 0
    assert r.bottleneck == BOTTLENECK_SUPPLY
    assert "Élargir" in r.next_action


def test_bottleneck_gates_when_fresh_entries_all_refused():
    events = [_entry(fresh=True, accepted=False, refusal="EDGE_REMAINING_TOO_LOW") for _ in range(5)]
    events += [_skip(R_STALE_BACKFILL) for _ in range(20)]
    r = build_entry_supply_report(events)
    assert r.fresh_entries == 5 and r.accepted_entries == 0 and r.refused_entries == 5
    assert r.bottleneck == BOTTLENECK_GATES
    assert r.refusal_reasons.get("EDGE_REMAINING_TOO_LOW") == 5


def test_bottleneck_ok_when_some_entry_accepted():
    events = [_entry(fresh=True, accepted=True), _entry(fresh=True, accepted=False, refusal="LIQUIDITY_TOO_LOW")]
    r = build_entry_supply_report(events)
    assert r.accepted_entries == 1 and r.bottleneck == BOTTLENECK_OK
    text = format_entry_supply_report(r)
    assert "bottleneck=OK" in text and "execution=forbidden" in text


# ---------- B. Shadow -> primary runner ----------

def test_shadow_runner_promotes_when_shadow_is_better_and_enough_samples():
    run = ShadowCalibrationRunner(min_samples=50, min_advantage=0.01)
    # outcome=1 ; shadow prédit ~0.9 (bon), primary ~0.6 (moins bon) -> brier shadow plus bas
    for _ in range(100):
        run.observe(primary_prob=0.6, shadow_prob=0.9, outcome=1)
    primary, shadow = run.scores()
    assert shadow.acting is False  # invariant
    assert shadow.brier < primary.brier
    dec = run.decision()
    assert dec.ready_for_promotion is True and dec.shadow_acts is False


def test_shadow_runner_not_ready_when_too_few_samples():
    run = ShadowCalibrationRunner(min_samples=200)
    for _ in range(10):
        run.observe(primary_prob=0.6, shadow_prob=0.9, outcome=1)
    dec = run.decision()
    assert dec.ready_for_promotion is False
    assert any("INSUFFICIENT_SAMPLES" in r for r in dec.reasons)


def test_shadow_runner_shadow_never_acts_invariant():
    run = ShadowCalibrationRunner()
    assert run.shadow_has_acted is False
    run.observe(primary_prob=0.5, shadow_prob=0.5, outcome=0)
    _, shadow = run.scores()
    assert shadow.acting is False and run.shadow_has_acted is False
