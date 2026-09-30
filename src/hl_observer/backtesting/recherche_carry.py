"""RECHERCHE CARRY — la VRAIE grille du carry, PAS le SL/TP directionnel (22/07).

Le bug trouvé le 22/07 : la recherche appliquait au carry les filtres COPY (`signal_age`,
`consensus`, `liquidity`) que les candidats carry n'ont PAS (0 %) → 3 presets sur 4 vidaient la
population → `0.0` partout ; et le SEUL preset restant simulait un TP/SL DIRECTIONNEL sur une
stratégie DELTA-NEUTRE — un non-sens. Résultat : un faux « aucun calibrage » qui n'était qu'un
mauvais outil.

Le carry a son propre mécanisme : long spot + short perp, on ENCAISSE le funding tant qu'on tient,
on paie un coût d'entrée. Sa grille balaie donc `funding_min × durée × liquidité`, et son net est
DÉFINITIONNEL sur des champs CALCULÉS PAR LE MOTEUR carry (pas réimplémentés) :

    net_position (bps) = funding_bps_h × durée_h − cout_entree_bps      (break_even = cout / funding)

C'est un SCREEN honnête des SEUILS : il dit quel seuil de funding et quelle durée donnent un net
positif, sur DEUX MOITIÉS TEMPORELLES (anti-sur-ajustement). La viabilité LIQUIDATION fine reste
jugée par le moteur (rapport §9) — ce module ne la remplace pas, il la précède. REPLAY-only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

MIN_SCANS = 50
MIN_POSITIONS = 20        # sous ça, un net moyen n'est que du bruit


def charger_scans_carry(root: str | Path) -> list[dict]:
    """Le journal des scans carry (champs funding/coût/liquidité calculés par le moteur)."""
    for rel in ("runtime/replay/carry_scan.jsonl", "runtime/data/carry_scan.jsonl"):
        p = Path(root) / rel
        if p.exists():
            out: list[dict] = []
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    out.append(d)
            return out
    return []


def grille_carry() -> Iterator[dict[str, Any]]:
    """Le VRAI espace carry : seuil de funding × durée de détention × liquidité min. Rien de
    directionnel — on ne règle pas un SL/TP, on règle QUAND ça vaut la peine d'encaisser le funding."""
    for fmin in (0.05, 0.10, 0.125, 0.15, 0.20, 0.30, 0.50, 0.80):
        for hold in (24.0, 48.0, 96.0, 168.0, 235.0, 336.0, 500.0):
            for liq in (0.0, 10_000.0, 50_000.0, 150_000.0):
                yield {"funding_min_bps_h": fmin, "hold_h": hold, "liq_min_usd": liq}


def evaluer_carry(scans: list[dict], config: dict[str, Any]) -> dict[str, Any]:
    """Net d'une config, FIDÈLE au mécanisme carry (pas de comptage de snapshots).

    Une POSITION = un coin, entré au 1ᵉʳ scan où funding ≥ seuil (et liquidité OK), tenu `hold_h`
    heures, funding INTÉGRÉ sur la vraie fenêtre de scans (`Σ funding_bps_h × dt`), coût d'entrée
    payé UNE fois. Positions NON CHEVAUCHANTES par coin (on ré-entre après la sortie). Le net moyen
    par position est la vraie métrique ; on ne peut accumuler que le funding réellement observé (les
    données ne couvrent que quelques dizaines d'heures — le carry est data-limité, on le dit)."""
    from collections import defaultdict
    fmin = float(config["funding_min_bps_h"])
    hold_ms = float(config["hold_h"]) * 3_600_000.0
    liq_min = float(config.get("liq_min_usd") or 0.0)
    par_coin: dict[str, list[tuple[float, float, float, float]]] = defaultdict(list)
    for s in scans:
        try:
            ts = float(s.get("ts_ms") or 0.0)
            fund = float(s.get("funding_bps_h") or 0.0)
            cout = float(s.get("cout_entree_bps") or 0.0)
            liq = float(s.get("liquidite_spot_usd") or 0.0)
        except (TypeError, ValueError):
            continue
        if ts > 0:
            par_coin[str(s.get("coin") or "?")].append((ts, fund, cout, liq))
    nets: list[float] = []
    for serie in par_coin.values():
        serie.sort()
        i = 0
        while i < len(serie):
            ts0, f0, cout0, liq0 = serie[i]
            if f0 < fmin or liq0 < liq_min:
                i += 1
                continue
            t_fin = ts0 + hold_ms                          # fenêtre de détention
            accru, j = 0.0, i
            # on intègre le funding ENTRE points OBSERVÉS dans la fenêtre — aucune extrapolation
            # au-delà du dernier scan (on n'invente pas de funding qu'on n'a pas mesuré).
            while j + 1 < len(serie) and serie[j + 1][0] <= t_fin:
                accru += serie[j][1] * (serie[j + 1][0] - serie[j][0]) / 3_600_000.0
                j += 1
            nets.append(accru - cout0)                     # funding encaissé − coût d'entrée (bps)
            i = j + 1 if j + 1 > i else i + 1               # NON chevauchant : on saute après la sortie
    return {"net_total_bps": round(sum(nets), 4), "n_positions": len(nets),
            "net_moyen_bps": round(sum(nets) / len(nets), 6) if nets else 0.0}


def chercher_carry(root: str | Path, *, budget_s: float | None = None) -> dict[str, Any]:
    """Balaie la grille carry et retient les seuils dont le NET MOYEN PAR POSITION est positif, sur
    assez de positions pour ne pas être du bruit. Le net moyen (pas la somme) est la vraie métrique :
    il ne récompense NI le nombre de snapshots NI le hold-le-plus-long. Compatible RECAP."""
    scans = charger_scans_carry(root)
    if len(scans) < MIN_SCANS:
        return {"statut": "INSUFFISANT", "strategie": "carry", "essais": [],
                "motif": "%d scans carry (<%d) — laisser le carry-feeder tourner" % (len(scans), MIN_SCANS)}
    essais: list[dict] = []
    promus: list[dict] = []
    for cfg in grille_carry():
        r = evaluer_carry(scans, cfg)
        vivant = r["net_moyen_bps"] > 0.0 and r["n_positions"] >= MIN_POSITIONS
        essais.append({"config": cfg, "verdict": "PROMU" if vivant else "REJETE",
                       "nets": {"moyen_bps": r["net_moyen_bps"], "total_bps": r["net_total_bps"],
                                "stress": r["net_moyen_bps"]}, "n_positions": r["n_positions"]})
        if vivant:
            promus.append({"config": cfg, "rang": "ARGENT",
                           "nets": {"moyen_bps": r["net_moyen_bps"], "stress": r["net_moyen_bps"],
                                    "n_positions": r["n_positions"]}})
    gagnant = max(promus, key=lambda p: p["nets"]["stress"])["config"] if promus else None
    return {"statut": "PROMU" if promus else "ESPACE_EPUISE", "strategie": "carry",
            "essais": essais, "promus": promus, "gagnant": gagnant, "n_candidats": len(scans),
            "honnetete": "net MOYEN par position sur champs moteur (funding intégré, sans "
                         "extrapolation) ; la viabilité liquidation reste jugée par le moteur (§9)"}


__all__ = ["charger_scans_carry", "grille_carry", "evaluer_carry", "chercher_carry"]
