"""[Bloc 43 / AUD-238,239] Calibration des couts a partir de donnees MESUREES (jamais heuristique).

Chaque parametre du moteur (spread, slippage, latence, frais, adverse selection) est ESTIME a partir
d'echantillons reels, pas fixe a une constante. Sans donnee suffisante -> None (jamais un chiffre invente).
numpy pour les percentiles. deterministe."""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np


def calibrer_spread_bps(quotes: Sequence[dict]) -> Optional[float]:
    """quotes = [{bid, ask}] -> spread moyen en bps ((ask-bid)/mid)."""
    vals = []
    for q in quotes:
        b, a = q.get("bid"), q.get("ask")
        if b is None or a is None:
            continue
        mid = (b + a) / 2.0
        if mid > 0:
            vals.append((a - b) / mid * 1e4)
    return float(np.mean(vals)) if vals else None


def calibrer_slippage_bps(fills: Sequence[dict]) -> Optional[float]:
    """fills = [{prix_exec, mid_ref}] -> slippage moyen |exec-mid|/mid en bps."""
    vals = []
    for f in fills:
        ex, mid = f.get("prix_exec"), f.get("mid_ref")
        if ex is None or mid is None or mid == 0:
            continue
        vals.append(abs(ex - mid) / mid * 1e4)
    return float(np.mean(vals)) if vals else None


def calibrer_latence(deltas_ms: Sequence[float]) -> Optional[dict]:
    """Percentiles de latence mesuree (p50/p95/p99)."""
    xs = [float(d) for d in deltas_ms if d is not None]
    if len(xs) < 2:
        return None
    a = np.asarray(xs)
    return {"p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)),
            "p99": float(np.percentile(a, 99)), "n": len(xs)}


def calibrer_frais_bps(fills: Sequence[dict]) -> Optional[float]:
    """frais effectifs = frais/notionnel en bps, moyennes sur les fills mesures."""
    vals = []
    for f in fills:
        frais, notion = f.get("frais"), f.get("notionnel")
        if frais is None or not notion:
            continue
        vals.append(frais / notion * 1e4)
    return float(np.mean(vals)) if vals else None


def adverse_selection_bps(fills: Sequence[dict]) -> Optional[float]:
    """Derive defavorable post-fill : pour un buy, (mid_apres-exec)/exec<0 est defavorable. On mesure la
    derive SIGNEE dans le sens de la position (positive = favorable)."""
    vals = []
    for f in fills:
        ex, mid_ap, side = f.get("prix_exec"), f.get("mid_apres"), f.get("side")
        if ex is None or mid_ap is None or ex == 0 or side not in ("buy", "sell"):
            continue
        drift = (mid_ap - ex) / ex * 1e4
        vals.append(drift if side == "buy" else -drift)
    return float(np.mean(vals)) if vals else None


def parametres_calibres(quotes, fills, latences) -> dict:
    """Assemble les parametres calibres a injecter dans le moteur (au lieu de constantes)."""
    return {"spread_bps": calibrer_spread_bps(quotes), "slippage_bps": calibrer_slippage_bps(fills),
            "frais_bps": calibrer_frais_bps(fills), "latence": calibrer_latence(latences),
            "adverse_selection_bps": adverse_selection_bps(fills)}
