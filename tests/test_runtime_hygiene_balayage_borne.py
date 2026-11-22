"""`runtime-check` doit rester rapide quand `runtime/data` grossit — sans rien changer au rapport.

Le 22/11/2026 la commande mettait 149 s : elle construisait un `Path` et son chemin relatif pour
chacun des 5 170 447 fichiers balayés, alors que moins d'un sur mille est une base, un sidecar
SQLite ou un journal. Appelée trois fois par la suite, elle a fait prendre un test pour un
blocage. Le tri se fait désormais sur le NOM d'abord (10,9 s, rapport identique sur l'arbre réel).

Deux gardes : le rapport reste exactement celui attendu, et le coût par fichier sans intérêt
reste nul (aucun chemin relatif calculé pour eux).
"""
from __future__ import annotations

from pathlib import Path

from hl_observer.config.loader import load_settings
from hl_observer.runtime import hygiene as H


def _arbre(racine: Path) -> None:
    (racine / "logs").mkdir()
    (racine / "data" / "profond" / "encore").mkdir(parents=True)
    (racine / "logs" / "heritee.SQLITE3").write_bytes(b"x")          # base DANS logs/, casse mixte
    (racine / "logs" / "session.log").write_text("x", encoding="utf-8")
    (racine / "data" / "vraie.db").write_bytes(b"x")                 # base hors logs/
    (racine / "data" / "vraie.db-wal").write_bytes(b"x")             # sidecar
    (racine / "data" / "profond" / "encore" / "trace.LOG").write_text("x", encoding="utf-8")
    for i in range(200):                                             # la masse : rien a signaler
        (racine / "data" / "profond" / f"shard_{i}.jsonl.gz").write_bytes(b"x")
    (racine / "__pycache__").mkdir()
    (racine / "__pycache__" / "ignoree.db").write_bytes(b"x")        # dossier elague


def _rapport(racine: Path):
    reglages = load_settings()
    reglages.database_url = f"sqlite:///{racine / 'data' / 'vraie.db'}"
    return H.scan_runtime_hygiene(reglages, root=racine)


def test_le_rapport_est_exactement_celui_attendu(tmp_path) -> None:
    _arbre(tmp_path)
    r = _rapport(tmp_path)
    noms = lambda chemins: sorted(p.name for p in chemins)  # noqa: E731
    assert noms(r.databases) == ["heritee.SQLITE3", "vraie.db"]
    assert noms(r.databases_in_logs) == ["heritee.SQLITE3"]
    assert noms(r.sqlite_sidecars) == ["vraie.db-wal"]
    assert noms(r.log_files) == ["session.log", "trace.LOG"]
    assert all(isinstance(p, Path) for p in r.databases + r.log_files + r.sqlite_sidecars)
    assert any("legacy SQLite" in w for w in r.warnings) and any("sidecars" in w for w in r.warnings)


def test_aucun_chemin_relatif_n_est_calcule_pour_les_fichiers_sans_interet(tmp_path, monkeypatch) -> None:
    _arbre(tmp_path)
    appels: list[Path] = []
    vrai = H._safe_relative
    monkeypatch.setattr(H, "_safe_relative", lambda p, racine: (appels.append(p), vrai(p, racine))[1])
    _rapport(tmp_path)
    # 205 fichiers balayes, 2 bases : le chemin relatif ne sert qu'a dire si une BASE est dans logs/
    assert sorted(p.name for p in appels) == ["heritee.SQLITE3", "vraie.db"], len(appels)
