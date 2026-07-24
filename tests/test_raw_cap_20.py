"""Cap RAW à 20 cycles + exemption d'auto-KILL (rectif Flo 24/07).

RAW_PROBE est une baseline de MESURE : elle n'est jamais promue, tourne jusqu'à 20 cycles clôturés (config
courante) puis se FIGE, et n'est PAS coupée par l'auto-KILL d'expectancy (sinon on n'atteindrait jamais 20).
Les cohortes à edge (ALPHA/PROBE) gardent, elles, l'auto-KILL. `config_hash` inchangé (le cap est un overlay).
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.experimental import cohortes as CO


def _ledger(root: Path, coh, n, config_hash, realized=-0.05):
    p = root / "runtime" / "data" / ("%s_ledger.jsonl" % coh.prefixe)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({"evt": "CLOSE", "coin": "SOL", "realized_usd": realized,
                                "notional_usd": 10.0, "config_hash": config_hash}) + "\n")


def test_raw_atteint_20_cycles_puis_condition_de_gel(tmp_path):
    _ledger(tmp_path, CO.RAW_PROBE, 20, "cfgX")
    ex = CO._expectancy(CO.RAW_PROBE, tmp_path, config_hash="cfgX")
    assert ex["n_trades"] == 20                                   # 20 cycles clôturés comptés (run-agnostique)
    assert ex["n_trades"] >= CO.RAW_BASELINE_MAX_CYCLES           # condition de gel atteinte -> RAW_BASELINE_FIGEE


def test_raw_exempte_de_l_auto_kill_meme_en_perte(tmp_path):
    _ledger(tmp_path, CO.RAW_PROBE, 15, "cfgX", realized=-0.10)   # 15 cycles perdants
    # RAW n'est PAS coupée par l'auto-KILL (gouvernée par le cap 20), donc reste "active" jusqu'au gel
    assert CO.cohorte_active(CO.RAW_PROBE, tmp_path, config_hash="cfgX") is True


def test_cohorte_a_edge_garde_l_auto_kill(tmp_path):
    _ledger(tmp_path, CO.ALPHA, 12, "cfgA", realized=-0.20)       # 12 cycles perdants sur une cohorte à edge
    assert CO.cohorte_active(CO.ALPHA, tmp_path, config_hash="cfgA") is False   # auto-KILL TOUJOURS actif ailleurs
