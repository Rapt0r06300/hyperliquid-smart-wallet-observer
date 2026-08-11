from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"expected marker missing for {label}")
    return text.replace(old, new, 1)


def patch_strict_lead_lag_lane() -> None:
    path = ROOT / "src" / "hl_observer" / "runtime" / "lead_lag_event_runtime.py"
    text = path.read_text(encoding="utf-8")
    if 'LANE_ID = "LEAD_LAG_STRICT_EVENT"' not in text:
        text = _replace_once(
            text,
            'STATE_SCHEMA = "hypersmart.lead_lag_event_state.v1"\n',
            'STATE_SCHEMA = "hypersmart.lead_lag_event_state.v1"\nLANE_ID = "LEAD_LAG_STRICT_EVENT"\n',
            "strict lane constant",
        )
    if '"lane": LANE_ID' not in text:
        text = _replace_once(
            text,
            '                "event_driven": True,\n',
            '                "event_driven": True,\n                "lane": LANE_ID,\n',
            "strict decision lane",
        )
        text = _replace_once(
            text,
            '            "real_execution": False,\n            **extra,\n',
            '            "real_execution": False,\n            "lane": LANE_ID,\n            **extra,\n',
            "strict decision record lane",
        )
        text = _replace_once(
            text,
            '            "schema": STATE_SCHEMA,\n            "real_execution": False,\n',
            '            "schema": STATE_SCHEMA,\n            "lane": LANE_ID,\n            "real_execution": False,\n',
            "strict state lane",
        )
        text = _replace_once(
            text,
            '            "enabled": self.enabled,\n            "real_execution": False,\n',
            '            "enabled": self.enabled,\n            "lane": LANE_ID,\n            "real_execution": False,\n',
            "strict status lane",
        )
        text = _replace_once(
            text,
            '__all__ = ["LeadLagEventOutcome", "LeadLagEventPaperRuntime"]',
            '__all__ = ["LANE_ID", "LeadLagEventOutcome", "LeadLagEventPaperRuntime"]',
            "strict lane export",
        )
    path.write_text(text, encoding="utf-8", newline="\n")


def patch_experimental_lead_lag_lane() -> None:
    path = ROOT / "src" / "hl_observer" / "experimental" / "runner.py"
    text = path.read_text(encoding="utf-8")
    if 'LEAD_LAG_EXPERIMENTAL_LANE = "LEAD_LAG_EXP_CALIBRATION"' not in text:
        text = _replace_once(
            text,
            'STATUS_RELPATH = MP.STATUS_RELPATH  # versionné (v2) : la v1 reste en quarantaine\n',
            'STATUS_RELPATH = MP.STATUS_RELPATH  # versionné (v2) : la v1 reste en quarantaine\n'
            'LEAD_LAG_EXPERIMENTAL_LANE = "LEAD_LAG_EXP_CALIBRATION"\n',
            "experimental lane constant",
        )
    if '"lead_lag_lane": LEAD_LAG_EXPERIMENTAL_LANE' not in text:
        text = _replace_once(
            text,
            '        "real_execution": False,\n    }\n    p = statut_path\n',
            '        "lead_lag_lane": LEAD_LAG_EXPERIMENTAL_LANE,\n'
            '        "lead_lag_lane_semantics": "calibration_only_separate_from_strict_event",\n'
            '        "real_execution": False,\n    }\n    p = statut_path\n',
            "experimental status lane",
        )
    text = text.replace(
        '__all__ = ["tick", "STATUS_RELPATH"]',
        '__all__ = ["LEAD_LAG_EXPERIMENTAL_LANE", "tick", "STATUS_RELPATH"]',
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def patch_bbo_promoted_coverage() -> None:
    path = ROOT / "tools" / "collecter_bbo.py"
    text = path.read_text(encoding="utf-8")
    if 'LEAD_LAG_CONFIG_REL = Path("runtime") / "data" / "lead_lag_config_gele.json"' not in text:
        text = _replace_once(
            text,
            'LIQ_CONFIRMEES_REL = Path("runtime") / "data" / "liquidations_confirmees.jsonl"\n',
            'LIQ_CONFIRMEES_REL = Path("runtime") / "data" / "liquidations_confirmees.jsonl"\n'
            'LEAD_LAG_CONFIG_REL = Path("runtime") / "data" / "lead_lag_config_gele.json"\n',
            "lead lag config path",
        )
    if "def coins_lead_lag_promus(" not in text:
        marker = "\ndef coins_couverture(root: Path | str = \".\", *, k: int = 16) -> list[str]:\n"
        helper = '''\ndef coins_lead_lag_promus(root: Path | str = ".") -> list[str]:
    """Return coins from the validated frozen Lead-Lag evidence, or none.

    Invalid/unfrozen evidence never expands live subscriptions. This is coverage
    only: it cannot create a paper decision and has no execution surface.
    """
    path = Path(root) / LEAD_LAG_CONFIG_REL
    if not path.is_file():
        return []
    try:
        from hl_observer.backtesting.lead_lag_evidence import load_frozen_evidence
        config = load_frozen_evidence(path)
    except Exception as exc:  # evidence invalid => fail closed, but observable
        import logging
        logging.getLogger(__name__).warning(
            "lead-lag frozen coverage ignored: %s", exc.__class__.__name__
        )
        return []
    selected: list[str] = []
    for raw in config.get("coins") or []:
        coin = str(raw or "").strip().upper()
        if coin and coin not in selected:
            selected.append(coin)
    return selected

'''
        if marker not in text:
            raise RuntimeError("coins_couverture marker missing")
        text = text.replace(marker, helper + marker, 1)
    old_tail = '''    except (OSError, ValueError):
        pass
    return coins
'''
    new_tail = '''    except (OSError, ValueError):
        import logging
        logging.getLogger(__name__).debug("liquidation coverage journal unavailable", exc_info=True)
    # A frozen/promoted Lead-Lag coin must never be absent merely because it is
    # neither a hard-coded major nor a frequent liquidation coin.
    for coin in coins_lead_lag_promus(root):
        if coin not in coins:
            coins.append(coin)
    return coins
'''
    if "for coin in coins_lead_lag_promus(root):" not in text:
        text = _replace_once(text, old_tail, new_tail, "promoted BBO coverage union")
    path.write_text(text, encoding="utf-8", newline="\n")


def verify() -> None:
    strict = (ROOT / "src" / "hl_observer" / "runtime" / "lead_lag_event_runtime.py").read_text(encoding="utf-8")
    exp = (ROOT / "src" / "hl_observer" / "experimental" / "runner.py").read_text(encoding="utf-8")
    bbo = (ROOT / "tools" / "collecter_bbo.py").read_text(encoding="utf-8")
    assert 'LANE_ID = "LEAD_LAG_STRICT_EVENT"' in strict
    assert strict.count('"lane": LANE_ID') >= 3
    assert 'LEAD_LAG_EXPERIMENTAL_LANE = "LEAD_LAG_EXP_CALIBRATION"' in exp
    assert '"lead_lag_lane": LEAD_LAG_EXPERIMENTAL_LANE' in exp
    assert "def coins_lead_lag_promus(" in bbo
    assert "for coin in coins_lead_lag_promus(root):" in bbo


def main() -> None:
    patch_strict_lead_lag_lane()
    patch_experimental_lead_lag_lane()
    patch_bbo_promoted_coverage()
    verify()
    print("FINAL_STRATEGY_GAPS_OK")


if __name__ == "__main__":
    main()
