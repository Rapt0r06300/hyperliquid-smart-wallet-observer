"""CHANTIER — rejeu Wallet×Binance sur une GRANDE population : la déflation anti-sur-ajustement (FIX-36)
s'applique à l'échelle. Un anticipateur marginal qui survit dans une petite population est DÉ-PROMU dans une
grande (tester des milliers de wallets = surface de multiple-testing → barre plus haute). Jamais un faux champion.
"""

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import rejeu_population as RP   # noqa: E402

JOUR = 86_400_000


def _ecrire(tmp_path, n_noise, name):
    # 0xMARG : anticipateur MARGINAL (net +25/−5 bps, Sharpe modéré) sur 80 jours (>= 25 votes OOS pour le DSR).
    # n_noise wallets de bruit (8 fills en zone plate → comptés mais non promus) gonflent la surface d'essais.
    pts, fills = [], []
    for d in range(80):
        T = d * JOUR + 30_000
        net = 25 if d % 2 == 0 else -5
        frac = (net + 9) / 1e4
        pts += [(T, 100.0), (T + 5000, 100.0 * (1 + frac))]
        fills.append({"adresse": "0xMARG", "coin": "BTC", "side": "LONG", "ts_ms": T})
    for w in range(n_noise):
        for k in range(8):
            T = (400 + w) * JOUR + k * 3_600_000
            pts += [(T, 100.0), (T + 5000, 100.0)]
            fills.append({"adresse": "0xN%04d" % w, "coin": "BTC", "side": "LONG", "ts_ms": T})
    pts.sort()
    b = tmp_path / (name + "_bbo.jsonl")
    f = tmp_path / (name + "_fills.jsonl")
    b.write_text("\n".join(json.dumps({"coin": "BTC", "ts_ms": t, "bin_mid": m}) for t, m in pts), encoding="utf-8")
    f.write_text("\n".join(json.dumps(x) for x in fills), encoding="utf-8")
    return str(f), str(b)


def test_chantier_rejeu_grande_population_deflate_le_multiple_testing(tmp_path):
    fp_s, bp_s = _ecrire(tmp_path, 1, "small")
    fp_l, bp_l = _ecrire(tmp_path, 200, "large")
    small = RP.rejouer_wallet_binance(fp_s, bp_s)
    large = RP.rejouer_wallet_binance(fp_l, bp_l)
    assert small["statut"] == "OK" and small["n_essais"] == small["n_wallets"]
    ms = [v for v in small["top"] if v["wallet"] == "0xMARG"][0]
    ml = [v for v in large["top"] if v["wallet"] == "0xMARG"][0]
    # petite population -> l'anticipateur marginal SURVIT ; grande population -> DÉ-PROMU (multiple-testing)
    assert ms["verdict"] == "ANTICIPATEUR_A_FORWARD" and ms["proba_deflatee"] > 0.95
    assert ml["verdict"] == "MORE_DATA" and ml["proba_deflatee"] < 0.95
    assert ml["proba_deflatee"] < ms["proba_deflatee"]         # plus d'essais -> barre plus haute
    assert large["n_essais"] > small["n_essais"] and large["real_execution"] is False


def test_chantier_rejeu_sans_donnees_est_blocked_external(tmp_path):
    r = RP.rejouer_wallet_binance(str(tmp_path / "absent_f.jsonl"), str(tmp_path / "absent_b.jsonl"))
    assert r["statut"] == "BLOCKED_EXTERNAL" and r["real_execution"] is False
