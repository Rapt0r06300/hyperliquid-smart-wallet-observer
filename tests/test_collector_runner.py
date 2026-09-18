from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

from hl_observer.ops import collector_runner as CR


def test_une_passe_en_echec_ecrit_un_etat_machine_lisible(tmp_path: Path) -> None:
    """Casse si une erreur enfant peut redevenir invisible derrière le wrapper."""
    script = tmp_path / "failure.py"
    script.write_text("raise SystemExit(7)\n", encoding="utf-8")
    log = tmp_path / "runtime" / "logs" / "demo.log"

    code, _ = CR.executer_une_passe(
        root=tmp_path,
        nom="demo",
        script=script,
        arguments=(),
        python=Path(sys.executable),
        log=log,
        etat_precedent={},
    )

    etat = json.loads(
        (tmp_path / "runtime" / "data" / "collecteurs" / "demo.json").read_text(
            encoding="utf-8"
        )
    )
    assert code == 7
    assert etat["state"] == "ERROR"
    assert etat["exit_code"] == 7
    assert etat["consecutive_failures"] == 1
    assert "failure.py" in log.read_text(encoding="utf-8")


def test_rotation_compressee_preserve_tout_le_log(tmp_path: Path) -> None:
    """Casse si la rotation tronque ou écrase encore l'autopsie précédente."""
    log = tmp_path / "runtime" / "logs" / "demo.log"
    log.parent.mkdir(parents=True)
    contenu = "preuve-importante\n" * 20
    log.write_text(contenu, encoding="utf-8")

    archive = CR.archiver_log_si_necessaire(tmp_path, "demo", max_bytes=1)

    assert archive is not None and archive.suffix == ".gz"
    with gzip.open(archive, "rt", encoding="utf-8") as stream:
        assert stream.read() == contenu
    assert not log.exists()


def test_un_echec_est_relance_vite_avec_backoff_borne() -> None:
    """Casse si une cadence de quatre heures retarde aussi la réparation d'un crash."""
    assert CR.delai_apres_passe(intervalle_s=14_400, echecs_consecutifs=1) == 30
    assert CR.delai_apres_passe(intervalle_s=14_400, echecs_consecutifs=8) == 256
    assert CR.delai_apres_passe(intervalle_s=14_400, echecs_consecutifs=20) == 300
    assert CR.delai_apres_passe(intervalle_s=60, echecs_consecutifs=0) == 60


def test_main_borne_execute_la_vraie_boucle_et_publie_son_succes(
    tmp_path: Path, monkeypatch
) -> None:
    """Casse si le .cmd peut lancer un runner qui ne lance pas réellement son enfant."""
    marker = tmp_path / "runtime" / "data" / "lanceur_session_marqueur.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("session-test", encoding="utf-8")
    marker.touch()
    script = tmp_path / "success.py"
    sortie = tmp_path / "arguments.json"
    script.write_text(
        "import json,sys\n"
        f"open({str(sortie)!r}, 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLLECTOR_RUNNER_MAX_PASSES", "1")

    assert CR.main(["demo", str(script), "60", "--coin", "BTC"]) == 0
    assert json.loads(sortie.read_text(encoding="utf-8")) == ["--coin", "BTC"]
    etat = json.loads(
        (tmp_path / "runtime" / "data" / "collecteurs" / "demo.json").read_text(
            encoding="utf-8"
        )
    )
    assert etat["state"] == "WAITING" and etat["exit_code"] == 0
