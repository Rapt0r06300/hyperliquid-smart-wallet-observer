from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.research.manual_research_classifier import classify_manual_research
from hl_observer.research.manual_research_importer import import_manual_research


def _write_inbox(path: Path) -> None:
    path.write_text(
        """# Inbox

## Source officielle
Titre: Hyperliquid WS docs
URL: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
Type: docs
Resume: Snapshot userFills puis updates.
Pourquoi c'est utile: Dedupe des snapshots.
Ce que ca prouve: WS userFills a un snapshot.
Ce que ca ne prouve pas: Profit futur.
Module concerne: realtime_monitor
Decision a ameliorer: dedupe snapshot
UI concernee: live feed
Temps reel concerne: oui
Risque securite: aucun
Statut propose: actionable

## Source OSINT
Titre: Claude bot claim
URL: https://reddit.com/r/example
Type: claim
Resume: Bot annonce 70% winrate.
Pourquoi c'est utile: Inspiration.
Ce que ca prouve: Rien sans donnees.
Ce que ca ne prouve pas: Rentabilite future.
Module concerne: research
Decision a ameliorer: ne pas croire le claim
UI concernee: warnings
Temps reel concerne: non
Risque securite: aucun
Statut propose: research only

## Source dangereuse
Titre: Executor prive
URL: https://github.com/example/private-executor
Type: code
Resume: Place des ordres avec private key et signature.
Pourquoi c'est utile: A refuser.
Ce que ca prouve: rien
Ce que ca ne prouve pas: safe
Module concerne: execution
Decision a ameliorer: refuser
UI concernee: none
Temps reel concerne: none
Risque securite: private key signature execute
Statut propose: refuse
""",
        encoding="utf-8",
    )


def test_import_manual_research_parses_blocks(tmp_path):
    inbox = tmp_path / "inbox.md"
    _write_inbox(inbox)

    result = import_manual_research(inbox, output_path=tmp_path / "items.json")

    assert len(result.items) == 3
    assert result.items[0].title == "Hyperliquid WS docs"
    assert result.output_path.exists()


def test_classify_manual_research_separates_reliability_and_danger(tmp_path):
    inbox = tmp_path / "inbox.md"
    _write_inbox(inbox)

    rows = classify_manual_research(inbox, output_path=tmp_path / "classified.json")
    by_title = {row.title: row for row in rows}

    assert by_title["Hyperliquid WS docs"].reliability == "OFFICIAL_HYPERLIQUID"
    assert by_title["Claude bot claim"].status == "RESEARCH_ONLY"
    assert by_title["Executor prive"].status == "REFUSED_DANGEROUS"


def test_manual_research_cli_commands(tmp_path):
    inbox = tmp_path / "inbox.md"
    _write_inbox(inbox)

    imported = CliRunner().invoke(app, ["research-import-manual", "--path", str(inbox), "--output", str(tmp_path / "items.json")])
    classified = CliRunner().invoke(app, ["research-classify-manual", "--path", str(inbox)])
    mapped = CliRunner().invoke(app, ["research-to-feature-map", "--path", str(inbox)])

    assert imported.exit_code == 0
    assert "manual_research_import=local_only" in imported.output
    assert classified.exit_code == 0
    assert "OFFICIAL_HYPERLIQUID" in classified.output
    assert "REFUSED_DANGEROUS" in classified.output
    assert mapped.exit_code == 0
    assert "research_to_feature_map=" in mapped.output

