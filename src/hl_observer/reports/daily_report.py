from __future__ import annotations


def build_daily_report(summary: dict) -> dict:
    return {"type": "daily", "summary": summary}
