"""In a clean process, importing the Hyperliquid runtime loads NO dYdX module."""

from __future__ import annotations

import os
import subprocess
import sys


def test_hl_runtime_subprocess_imports_no_dydx():
    code = (
        "import sys\n"
        "import hyper_smart_observer.copy_mode.copy_loop\n"
        "import hyper_smart_observer.copy_mode.copy_signal_detector\n"
        "import hyper_smart_observer.market_signals.market_signal_features\n"
        "import hyper_smart_observer.hyperliquid_client.info_client\n"
        "import hyper_smart_observer.paper_trading.simulator\n"
        "import hyper_smart_observer.dashboard.exporter\n"
        "bad=[m for m in sys.modules if m.lower().startswith('hyper_smart_observer.dydx') or '.dydx_v4' in m.lower()]\n"
        "print('BAD:' + ','.join(bad) if bad else 'OK')\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + os.path.join(os.getcwd(), "src")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=os.getcwd())
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout, result.stdout + result.stderr
