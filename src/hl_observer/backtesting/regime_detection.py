"""Détection de régime & état latent — pur, testé. Exécution du backlog :
kalman_filter_1d (IDEA-83), garch11_variance (IDEA-84), cusum_change_points (IDEA-82).
Outils de mesure ; aucun ordre, aucune promesse.
"""
from __future__ import annotations


def kalman_filter_1d(observations, *, process_var: float = 1e-3, obs_var: float = 1.0) -> list:
    """Filtre de Kalman scalaire : estime le NIVEAU latent lissé d'une série bruitée."""
    obs = [float(z) for z in observations]
    if not obs:
        return []
    x = obs[0]
    p = 1.0
    out = []
    for z in obs:
        p += process_var                 # prédiction
        k = p / (p + obs_var)            # gain de Kalman
        x = x + k * (z - x)             # mise à jour
        p = (1.0 - k) * p
        out.append(x)
    return out


def garch11_variance(returns, *, omega: float = 1e-6, alpha: float = 0.1, beta: float = 0.85) -> list:
    """Variance conditionnelle GARCH(1,1), version EX-POST (descriptive).

    🔴 INTERDIT SUR TOUT CHEMIN DE DÉCISION — cette fonction LIT LE FUTUR, deux fois :

      1. `var` est initialisée avec la variance de **TOUTE la série**, futur compris.
         Chaque valeur suivante en hérite.
      2. `out[i]` est calculée **après avoir vu `r[i]`** : c'est la variance *sachant* le
         rendement de l'instant i. L'utiliser pour décider à l'instant i, c'est décider en
         connaissant le rendement qu'on cherche justement à anticiper.

    Elle reste valable pour DÉCRIRE a posteriori (« la vol a-t-elle monté après ce choc ? »).
    Pour étiqueter un régime au moment d'une décision, utiliser `garch11_variance_causale`.
    """
    rs = [float(r) for r in returns]
    if not rs:
        return []
    var = sum(r * r for r in rs) / len(rs)
    out = []
    for r in rs:
        var = omega + alpha * r * r + beta * var
        out.append(var)
    return out


def garch11_variance_causale(
    returns,
    *,
    omega: float = 1e-6,
    alpha: float = 0.1,
    beta: float = 0.85,
    warmup: int = 20,
) -> list:
    """GARCH(1,1) **CAUSAL** : `out[i]` n'utilise QUE `returns[:i]`. Jamais `returns[i]`, jamais après.

    Deux différences avec la version ex-post, et ce sont exactement les deux fuites :

      * l'amorçage se fait sur les `warmup` PREMIERS rendements seulement (pas sur toute la série) ;
      * on ÉMET la variance prédite AVANT d'incorporer `r[i]` (`out.append(var)` *puis* mise à jour).

    Les `warmup` premières valeurs valent `None` : on n'a pas encore de quoi estimer.
    **`None` est un refus honnête** — bien plus utile qu'un chiffre inventé qui passerait les gates.

    Un test différentiel (`test_regime_label.py`) le prouve : modifier le FUTUR ne change AUCUNE
    valeur passée. La version ex-post, elle, échoue ce test — c'est ainsi qu'on l'a démasquée.
    """
    rs = [float(r) for r in returns]
    n = len(rs)
    w = max(1, int(warmup))
    if n <= w:
        return [None] * n

    var = sum(r * r for r in rs[:w]) / w  # amorçage : PASSÉ uniquement
    out: list = [None] * w
    for i in range(w, n):
        out.append(var)                    # 1) on PRÉDIT avec l'info disponible avant i
        r = rs[i]
        var = omega + alpha * r * r + beta * var  # 2) puis seulement on apprend de r[i]
    return out


def cusum_change_points(series, *, threshold: float) -> list:
    """Détection de ruptures par CUSUM symétrique. Retourne les indices de changement de régime."""
    xs = [float(v) for v in series]
    if len(xs) < 3:
        return []
    points = []
    s_pos = s_neg = 0.0
    ref = xs[0]
    for i in range(1, len(xs)):
        diff = xs[i] - ref
        s_pos = max(0.0, s_pos + diff)
        s_neg = min(0.0, s_neg + diff)
        if s_pos > threshold or s_neg < -threshold:
            points.append(i)
            s_pos = s_neg = 0.0
            ref = xs[i]
        else:
            ref = 0.98 * ref + 0.02 * xs[i]
    return points
