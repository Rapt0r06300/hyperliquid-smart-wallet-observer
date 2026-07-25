"""LOT 3 — RUN shadow : backteste les plugins MESURABLES sur données existantes -> chiffres réels + décision.

RESIDUAL_MOMENTUM (neutre bêta BTC/ETH) est le plus mesurable : il ne dépend que du prix (qu'on a). On
BALAYE l'historique (point-in-time), on émet long-top/short-bottom résidu, on mesure le net CAUSAL au bid/ask
réel, puis décision SCALE/ARM/SHADOW/KILL avec placebo + IC + 2 moitiés + LOO. Lecture seule, 0 ordre.

Entrée : un fichier série `coin\\tts_ms\\tbid\\task` (construit depuis le bbo_tape/shards). Rapport écrit sous
research_lab/rapports.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research_parallel import execution as EX  # noqa: E402
from hl_observer.research_parallel import isolation as ISO  # noqa: E402
from hl_observer.research_parallel.plugins import vague1 as V  # noqa: E402


def charger_series(fichier: Path) -> dict:
    out: dict[str, list] = {}
    for l in Path(fichier).read_text(encoding="utf-8").splitlines():
        p = l.split("\t")
        if len(p) != 4:
            continue
        c, ts, b, a = p
        out.setdefault(c, []).append((float(ts), float(b), float(a)))
    for c in out:
        out[c].sort()
    return out


def backtest_residual(series: dict, *, lookback_ms: float, horizon_s: int, variante: str,
                      pas_ms: float = 600_000.0) -> list[dict]:
    """Balaye l'historique tous les `pas_ms`. À chaque t : résidus sur [t−lookback ; t] (passé), signaux
    long-top/short-bottom, net causal mesuré APRÈS t. Épisodes indépendants (une éval par pas)."""
    tous_ts = sorted(t for s in series.values() for t, _b, _a in s)
    if len(tous_ts) < 10:
        return []
    t0, t1 = tous_ts[0] + lookback_ms, tous_ts[-1] - horizon_s * 1000
    episodes = []
    t = t0
    while t <= t1:
        tronque = {c: [x for x in s if x[0] <= t] for c, s in series.items()}
        tronque = {c: s for c, s in tronque.items() if s}
        res = V._residuals(tronque, lookback_ms=lookback_ms)
        if len(res) >= 4:
            classe = sorted(res.items(), key=lambda kv: kv[1])
            for coin, sens in ((classe[-1][0], 1), (classe[0][0], -1)):
                # fraîcheur 60 s : négligeable devant un hold de 30-120 min, mais indispensable sur une
                # série HL éparse downsamplée à 5 s (sinon on rate la cotation à l'horizon exact).
                net = EX.net_causal({"ts_ms": t, "coin": coin, "sens": sens}, series[coin],
                                    horizon_s=horizon_s, fraicheur_ms=60_000.0)
                if net is not None:
                    episodes.append({"ts_ms": t, "coin": coin, "variante": variante, "sens": sens, "net_bps": net})
        t += pas_ms
    return episodes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RUN shadow labo (backtest plugins mesurables), lecture seule.")
    ap.add_argument("--serie", required=True)
    ap.add_argument("--root", default=str(RACINE))
    a = ap.parse_args(argv)
    series = charger_series(Path(a.serie))
    par_coin = {c: len(v) for c, v in series.items()}
    variantes = {
        "RESMOM_COURT": dict(lookback_ms=900_000, horizon_s=1800, pas_ms=600_000),
        "RESMOM_LONG": dict(lookback_ms=3_600_000, horizon_s=7200, pas_ms=1_200_000),
    }
    rap = {"plugin": "RESIDUAL_MOMENTUM", "quotes_par_coin": par_coin, "variantes": {}}
    for var, prm in variantes.items():
        eps = backtest_residual(series, variante=var, **prm)
        pl = EX.placebo(series, horizon_s=prm["horizon_s"], n=300)
        rap["variantes"][var] = {"decision": EX.decision(eps, placebo_median=pl["median_bps"]),
                                 "placebo": pl, "n_episodes": len(eps)}
    ISO.preparer(Path(a.root))
    dest = ISO.lab_root(Path(a.root)) / "rapports" / "shadow_residual_momentum.json"
    dest.write_text(json.dumps(rap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rap, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
