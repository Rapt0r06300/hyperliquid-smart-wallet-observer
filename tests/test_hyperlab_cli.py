"""[Bloc 6/58] CLI `python -m hl_observer.hyperlab` : smoke offline retourne 0 (chaine tient)."""
from hl_observer.hyperlab.__main__ import main


def test_smoke_retourne_0(capsys):
    assert main(["smoke"]) == 0
    out = capsys.readouterr().out
    assert "verdict_chaine_ok" in out and "REQUIRES_NETWORK" in out


def test_mode_full_ok():
    assert main(["full"]) == 0


def test_mode_inconnu_nonzero():
    assert main(["turbo"]) == 2
