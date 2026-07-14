"""H-160 / GH-02 — LE BIAIS RECURSIF, MESURE SUR NOS VRAIS PRIX.

    python tools/mesurer_biais_recursif.py

Lit les mids REELS enregistres (`runtime/replay/l2_book.*.jsonl`), et pour chaque coin ayant assez
de points, compare -- au MEME instant --

    BACKTEST : la feature calculee sur TOUTE l'histoire
    LIVE     : la feature calculee sur un buffer BORNE (200 points)

Une feature a fenetre glissante rend un ecart **exactement nul**. Une feature a etat propage (EMA
amorcee sur le premier point, lissage de Wilder du RSI) rend un ecart **non nul** -- et c'est cet
ecart qui separe le backtest du live.

⚠️ UN ECART N'EST PAS UN BUG EN SOI. Il devient un bug quand il depasse ce que la feature DECIDE :
`DirectionConfig.flat_threshold_bps` vaut 5 bps -- si l'ecart backtest/live approche ce seuil, la
direction peut basculer UP/FLAT/DOWN selon la seule quantite d'historique. C'est ca qu'on regarde.

Lecture seule. Aucun ordre, aucun reseau.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting.recursive_bias_probe import sonder  # noqa: E402
from hl_observer.features.direction import DirectionConfig, _signed_strength_bps  # noqa: E402
from hl_observer.features.rsi_overheat import rsi  # noqa: E402
from hl_observer.features.vol_sigma import sigma_fast_slow_blend  # noqa: E402
from hl_observer.features.volatility import compute_volatility_blend  # noqa: E402

HISTORIQUE_LIVE = 200
MIN_POINTS = 400
MAX_COINS = 8


def _mids_par_coin() -> dict[str, list[float]]:
    """Les mids REELS, dans l'ordre d'arrivee. Aucune donnee fabriquee."""
    series: dict[str, list[float]] = defaultdict(list)
    for f in sorted((RACINE / "runtime" / "replay").glob("l2_book.*.jsonl")):
        try:
            with f.open("r", encoding="utf-8", errors="ignore") as fh:
                for ligne in fh:
                    try:
                        d = json.loads(ligne)
                    except ValueError:
                        continue
                    coin = str(d.get("coin") or "").upper()
                    mid = d.get("mid")
                    if coin and isinstance(mid, (int, float)) and mid > 0:
                        series[coin].append(float(mid))
        except OSError:
            continue
    return series


def main() -> int:
    series = _mids_par_coin()
    retenus = sorted(
        ((c, s) for c, s in series.items() if len(s) >= MIN_POINTS),
        key=lambda kv: len(kv[1]),
        reverse=True,
    )[:MAX_COINS]

    if not retenus:
        print("Aucun coin avec >= %d mids reels dans runtime/replay/l2_book.*.jsonl." % MIN_POINTS)
        print("-> AUCUNE mesure produite. Un blanc doit se VOIR, pas se deviner.")
        return 2

    cfg = DirectionConfig()
    features = {
        # BORNEES (attendu : ecart nul)
        "vol_sigma.sigma_blend": (
            lambda xs: sigma_fast_slow_blend(_rendements(xs))["sigma_blend"], "bornee"),
        "volatility.blend_bps": (
            lambda xs: (compute_volatility_blend(xs).blend_bps or 0.0), "bornee"),
        # RECURSIVES (attendu : ecart non nul)
        "direction.strength_bps": (lambda xs: _signed_strength_bps(xs, cfg), "recursive"),
        "rsi_overheat.rsi_14": (lambda xs: rsi(xs, 14), "recursive"),
    }

    print("=" * 92)
    print("  H-160 — BIAIS RECURSIF sur les MIDS REELS (backtest=toute l'histoire vs live=%d pts)"
          % HISTORIQUE_LIVE)
    print("  seuil de decision de la direction : %.1f bps (DirectionConfig.flat_threshold_bps)"
          % cfg.flat_threshold_bps)
    print("=" * 92)
    print("  %-26s %-10s %8s %13s %13s  %s"
          % ("feature", "nature", "coin", "ecart_max", "ecart_moyen", "verdict"))
    print("-" * 92)

    rapport: list[dict] = []
    for nom, (f, nature) in features.items():
        for coin, mids in retenus:
            s = sonder(nom, f, mids, historique_live=HISTORIQUE_LIVE)
            if s.n_points == 0:
                continue
            verdict = "STABLE" if s.stable else "RECURSIF"
            # ⚠️ NOTATION SCIENTIFIQUE, ET C'EST IMPORTANT : un ecart de 1e-8 affiche en %.6f
            # devient « 0.000000 » -- et le rapport a alors l'air de se CONTREDIRE (« RECURSIF »
            # avec un ecart nul). Un rapport qu'on ne peut pas relire sans le soupconner ne sert
            # a rien. On montre l'ordre de grandeur, toujours.
            print("  %-26s %-10s %8s %13.3e %13.3e  %s"
                  % (nom, nature, coin, s.ecart_max, s.ecart_moyen, verdict))
            rapport.append({**s.as_dict(), "coin": coin, "nature_attendue": nature,
                            "n_mids": len(mids)})

    print("-" * 92)
    _conclure(rapport, cfg.flat_threshold_bps)

    sortie = RACINE / "data" / "reports" / "biais_recursif.json"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(
        json.dumps(
            {
                "historique_live": HISTORIQUE_LIVE,
                "seuil_direction_bps": cfg.flat_threshold_bps,
                "source": "runtime/replay/l2_book.*.jsonl (mids REELS)",
                "sondes": rapport,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print("-> %s" % sortie)
    return 0


def _rendements(prix: list[float]) -> list[float]:
    return [math.log(prix[i] / prix[i - 1]) for i in range(1, len(prix)) if prix[i - 1] > 0]


def _conclure(rapport: list[dict], seuil_bps: float) -> None:
    bornees = [r for r in rapport if r["nature_attendue"] == "bornee"]
    recursives = [r for r in rapport if r["nature_attendue"] == "recursive"]
    surprises = [r for r in bornees if not r["stable"]]
    if surprises:
        print("  🔴 UNE FEATURE CENSEE BORNEE EST RECURSIVE : %s"
              % ", ".join("%s/%s" % (r["feature"], r["coin"]) for r in surprises))

    direction = [r for r in recursives if r["feature"] == "direction.strength_bps"]
    if direction:
        pire = max(r["ecart_max"] for r in direction)
        print("  direction.strength_bps : ecart max %.3e bps -- le seuil de DECISION est %.1f bps."
              % (pire, seuil_bps))
        if pire >= seuil_bps:
            print("  🔴 L'ECART ATTEINT LE SEUIL : la direction (UP/FLAT/DOWN) peut basculer selon")
            print("     la seule QUANTITE d'historique fournie. Backtest et live ne decident PAS")
            print("     la meme chose.")
        else:
            marge = seuil_bps / pire if pire > 0 else float("inf")
            print("  ✅ VERDICT (H-160) : la feature EST recursive PAR CONSTRUCTION, mais l'ecart")
            print("     qu'elle produit est %.0e fois plus PETIT que le seuil qui decide." % marge)
            print("     Le seed de l'EMA s'oublie GEOMETRIQUEMENT : apres 200 points de buffer,")
            print("     il n'en reste rien de mesurable.")
            print("     -> Backtest et live decident LA MEME CHOSE. Le biais recursif n'est PAS")
            print("        l'explication de nos ecarts. Ne pas 'corriger' ce qui ne casse rien.")


if __name__ == "__main__":
    raise SystemExit(main())
