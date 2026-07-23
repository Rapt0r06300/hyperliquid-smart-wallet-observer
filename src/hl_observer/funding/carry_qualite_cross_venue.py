"""QUALITÉ DE CARRY HL depuis la dispersion funding HL↔Binance (23/07).

Contexte (Flo : « gagner de l'argent avec le cross-venue »). L'arb cross-venue pur (short la venue
qui paie le plus, long l'autre) MESURE un écart qu'on ne peut PAS capturer — pas d'exécution Binance
(cf. `funding_cross_venue`, « mesurer n'est pas capturer »). MAIS le funding Binance est un SIGNAL DE
QUALITÉ **capturable** pour le carry HL qu'on fait DÉJÀ : ce module l'utilise pour INCLINER le capital
du carry vers les coins dont le funding HL est le plus robuste, sans jamais toucher au levier ni à une
porte. C'est le « filtre maintenant » ; la vraie capture (jambe Binance paper) est un chantier séparé.

CE QUE MESURE LE FACTEUR
------------------------
Par coin, sur la dispersion récente (`dispersion_venues.jsonl`, champs `hl_bps_h`/`bin_bps_h`) :
  * premium = moyenne(hl − bin). Persistance = fraction du temps où hl est du bon côté.
  * `PREMIUM_HL_PERSISTANT` (hl > bin de façon persistante) → le funding HL est structurellement le
    plus haut : carry robuste → bonus BORNÉ (+10 %).
  * `INVERSE` (hl < bin persistant) → le coin paie moins que le benchmark → carry plus faible →
    malus BORNÉ (−10 %).
  * `PRIME_MARCHE` (≈ égal) ou données minces → facteur 1.0 (NEUTRE : allocation inchangée).

GARDES (leçons du projet)
-------------------------
  * JAMBE FIGÉE = artefact : si `bin_bps_h` n'a qu'une valeur (coin absent de Binance, ex. VINE) ou
    `hl_bps_h` figé à 0 (ex. MAVIA) → aucun tilt (1.0). *Ce qui ne bouge pas n'est pas un signal.*
  * Lecture BORNÉE (tail ≤ 4 Mo) : ne ralentit pas le poll carry. Fichier absent/illisible → {}.
  * Tilt SOFT et BORNÉ [0.90 ; 1.10] : ne peut ni créer un gagnant ni renverser l'ordre du net³.
    Un net ≤ 0 reste à ZÉRO (la barre n'est JAMAIS baissée). PAPER-only, read-only.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

FACTEUR_MAX = 1.10
FACTEUR_MIN = 0.90
SEUIL_PREMIUM_BPS_H = 0.02        # ≈ 17 %/an : au-delà, le premium HL est jugé réel (pas du bruit)
PERSIST_MIN = 0.80               # 80 % du temps du bon côté pour trancher (sinon NEUTRE)
MIN_OBS = 25                     # sous ça, la persistance n'est que du bruit
MAX_OCTETS_TAIL = 4_000_000      # on ne lit que la fin du fichier (récent) — poll non ralenti


def _tail_lignes(p: Path, max_octets: int = MAX_OCTETS_TAIL) -> list[str]:
    """Les lignes de la FIN du fichier (au plus `max_octets`). La 1re ligne partielle est jetée."""
    taille = p.stat().st_size
    with p.open("rb") as f:
        if taille > max_octets:
            f.seek(taille - max_octets)
            f.readline()                                  # jeter la ligne coupée
        brut = f.read()
    return brut.decode("utf-8", "ignore").splitlines()


def charger_dispersion_recente(root: str | Path, *,
                               max_octets: int = MAX_OCTETS_TAIL) -> dict[str, list[tuple[float, float]]]:
    """{coin: [(hl_bps_h, bin_bps_h), ...]} depuis la fin de `dispersion_venues.jsonl`.
    Fichier absent → {} (jamais une exception : le carry doit tourner sans cette source)."""
    p = Path(root) / "runtime" / "data" / "dispersion_venues.jsonl"
    if not p.exists():
        return {}
    par: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for ligne in _tail_lignes(p, max_octets):
        try:
            d = json.loads(ligne)
            c = d["coin"]
            hl = float(d["hl_bps_h"])
            bn = float(d["bin_bps_h"])
        except (ValueError, KeyError, TypeError):
            continue
        par[str(c)].append((hl, bn))
    return dict(par)


def facteur_qualite(series: list[tuple[float, float]], *, min_obs: int = MIN_OBS) -> tuple[float, str]:
    """(facteur ∈ [0.90, 1.10], label) pour UN coin, depuis sa série (hl_bps_h, bin_bps_h).

    PUR (aucune I/O). Garde anti-artefact : une jambe figée ne produit AUCUN tilt (1.0)."""
    if len(series) < min_obs:
        return 1.0, "INSUFFISANT"
    hl = [h for h, _ in series]
    bn = [b for _, b in series]
    # Artefact, PAS un signal : jambe Binance figée (coin absent de Binance, ex. VINE : bin à une
    # seule valeur) OU funding HL entièrement mort à ~0 (ex. MAVIA : hlmax=0). ⚠️ un funding HL
    # CONSTANT à une valeur NON nulle (0.125 = le plancher protocolaire) est NORMAL, pas un artefact.
    bin_fige = len(set(round(b, 6) for b in bn)) <= 1
    hl_mort = max(abs(h) for h in hl) < 1e-9
    if bin_fige or hl_mort:
        return 1.0, "JAMBE_FIGEE"
    diffs = [hl[i] - bn[i] for i in range(len(series))]
    premium = sum(diffs) / len(diffs)
    persist_haut = sum(1 for x in diffs if x > 0) / len(diffs)
    persist_bas = sum(1 for x in diffs if x < 0) / len(diffs)
    if premium > SEUIL_PREMIUM_BPS_H and persist_haut >= PERSIST_MIN:
        return FACTEUR_MAX, "PREMIUM_HL_PERSISTANT"
    if premium < -SEUIL_PREMIUM_BPS_H and persist_bas >= PERSIST_MIN:
        return FACTEUR_MIN, "INVERSE"
    return 1.0, "PRIME_MARCHE"


def facteurs_qualite_carry(root: str | Path, *, min_obs: int = MIN_OBS,
                           max_octets: int = MAX_OCTETS_TAIL) -> dict[str, float]:
    """{coin: facteur} prêt pour `allouer_marges(..., qualite_par_coin=...)`.
    Seuls les coins avec un facteur ≠ 1.0 sont retournés (les neutres n'ont pas besoin d'entrée)."""
    séries = charger_dispersion_recente(root, max_octets=max_octets)
    out: dict[str, float] = {}
    for coin, série in séries.items():
        f, _label = facteur_qualite(série, min_obs=min_obs)
        if f != 1.0:
            out[coin] = f
    return out


def rapport_qualite(root: str | Path, *, min_obs: int = MIN_OBS) -> list[dict]:
    """Table lisible {coin, facteur, label, premium, n} triée — pour le rapport/dashboard/audit."""
    séries = charger_dispersion_recente(root)
    lignes: list[dict] = []
    for coin, série in séries.items():
        if len(série) < min_obs:
            continue
        f, label = facteur_qualite(série, min_obs=min_obs)
        premium = sum(h - b for h, b in série) / len(série)
        lignes.append({"coin": coin, "facteur": f, "label": label,
                       "premium_bps_h": round(premium, 5), "n": len(série)})
    lignes.sort(key=lambda r: -r["premium_bps_h"])
    return lignes


__all__ = ["FACTEUR_MAX", "FACTEUR_MIN", "SEUIL_PREMIUM_BPS_H", "MIN_OBS",
           "charger_dispersion_recente", "facteur_qualite", "facteurs_qualite_carry",
           "rapport_qualite"]
