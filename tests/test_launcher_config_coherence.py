"""COHERENCE DE LA CONFIG DU LANCEUR — garde-fou anti "deux sources de verite".

Bug reel trouve a l'audit du 2026-07-11 : `LANCER_HYPERSMART.cmd` reglait des valeurs
(min_edge 40, levier 5, budget 400, TP 160...) que `start_hypersmart_simulation.ps1` ECRASAIT
ensuite via `[Environment]::SetEnvironmentVariable(..., "Process")` (16 / 10 / 1000 / 40...).
Le .cmd etait donc un LEURRE : ce qu'on y lisait etait FAUX au runtime, et les tests se
contredisaient entre eux.

Ce test empeche la reapparition du probleme : toute variable presente dans les DEUX fichiers
doit y avoir la MEME valeur. (Le .ps1 reste l'autorite : c'est lui qui force.)
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CMD = ROOT / "LANCER_HYPERSMART.cmd"
PS1 = ROOT / "tools" / "start_hypersmart_simulation.ps1"


def _cmd_vars() -> dict[str, str]:
    text = CMD.read_text(encoding="utf-8", errors="replace")
    return dict(re.findall(r'set "([A-Z0-9_]+)=([^"]*)"', text))


def _ps1_forced_vars() -> dict[str, str]:
    """Seules les valeurs FORCEES comptent (SetEnvironmentVariable ... "Process").
    `Set-HyperSmartDefaultEnv` ne s'applique que si la variable est absente : pas de conflit."""
    text = PS1.read_text(encoding="utf-8", errors="replace")
    pat = r'\[Environment\]::SetEnvironmentVariable\(\s*"([A-Z0-9_]+)"\s*,\s*"([^"]*)"\s*,\s*"Process"\s*\)'
    return dict(re.findall(pat, text))


def test_cmd_and_ps1_never_contradict_each_other():
    cmd, ps1 = _cmd_vars(), _ps1_forced_vars()
    conflicts = [
        f"{name}: .cmd={cmd[name]!r} MAIS .ps1 force {ps1[name]!r}"
        for name in sorted(set(cmd) & set(ps1))
        if cmd[name] != ps1[name]
    ]
    assert not conflicts, (
        "Le .cmd affiche des valeurs que le .ps1 ecrase -> reglage LEURRE :\n  "
        + "\n  ".join(conflicts)
    )


def test_no_real_execution_anywhere_in_the_launcher():
    """La securite ne depend d'aucun reglage tunable : elle est ecrite en dur dans le lanceur."""
    cmd = CMD.read_text(encoding="utf-8", errors="replace")
    assert "HL_ENABLE_MAINNET_EXECUTION=0" in cmd
    assert "HL_ENABLE_TESTNET_EXECUTION=0" in cmd
    assert "HL_ENV=paper" in cmd
    assert "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW" in cmd


def test_risk_caps_are_present_and_positive():
    """Les plafonds de risque doivent EXISTER et etre > 0 (jamais desactives par omission)."""
    cmd = _cmd_vars()
    for name in (
        "HYPERSMART_MAX_POSITION_USDT",
        "HYPERSMART_MAX_OPEN_POSITIONS",
        "HYPERSMART_MAX_TOTAL_EXPOSURE_USDT",
        "HYPERSMART_SIMULATION_LEVERAGE",
    ):
        assert name in cmd, f"plafond de risque absent du lanceur: {name}"
        assert float(cmd[name]) > 0, f"plafond de risque neutralise: {name}={cmd[name]}"


def effective_launcher_config() -> dict[str, str]:
    """La config REELLEMENT appliquee au runtime : .cmd, puis defauts .ps1, puis forcages .ps1.
    C'est la seule verite. Les autres tests doivent l'utiliser au lieu de figer des chiffres."""
    cfg = _cmd_vars()
    text = PS1.read_text(encoding="utf-8", errors="replace")
    for name, value in re.findall(r'Set-HyperSmartDefaultEnv\s+"([A-Z0-9_]+)"\s+"([^"]*)"', text):
        cfg.setdefault(name, value)          # defaut : seulement si absent
    cfg.update(_ps1_forced_vars())           # forcage : autorite finale
    return cfg
