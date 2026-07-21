"""ENREGISTREUR DE SCANS CARRY — le trou de données n°1, comblé (21/07).

LE CONSTAT
----------
Inventaire des données rejouables, ce jour :

    copy / replay      443 783 candidats + 355 190 marks   (215 Mo)  ✅ masse
    cross-venue          9 038 lignes sur 48 h                       ⚠️ correct
    **carry**               **96 lignes** (le ledger OPEN/CLOSE)     🔴 quasi rien

Le carry est notre SEUL module rentable, et c'est celui dont on ne garde presque rien. À
chaque passe, le feeder calcule pour ~20 coins un dossier complet — funding (snapshot,
persistant, z-score, prévu, premium, ΔOI, alerte de rupture), base VWAP et MID, liquidité
spot mesurée au carnet, levier retenu et levier max de la venue, pire hausse sur 200 jours,
coût d'entrée, break-even, rendement net — **puis il l'écrase**. Le fichier shortlist est
réécrit ; les coins REFUSÉS, avec leur motif, ne laissent aucune trace.

Conséquence directe : impossible de répondre par la mesure à « et si on avait mis le plancher
de break-even à 180 h ? », « et si la sécurité de liquidation valait 1,3 au lieu de 1,5 ? »,
« quel exposant d'allocation aurait le mieux marché la semaine dernière ? ». On ne pouvait que
raisonner. Ce module transforme chaque passe en données rejouables.

Volume attendu : ~20 lignes × 6 passes/h ≈ 2 900 lignes/jour, quelques Mo par semaine.

RÈGLES
------
  * **Ne lève JAMAIS.** Un enregistreur qui tue le feeder serait pire que l'absence de données.
  * **Liste blanche de champs**, valeurs coercées ou absentes — on n'invente jamais un nombre,
    et un champ manquant reste manquant (`None`), il ne devient pas 0.
  * **LIVE / BACKTEST / REPLAY / TEST_FIXTURE** sont étiquetés et ne se mélangent jamais.
  * **Append-only** + rotation par renommage au-delà d'un plafond : on n'efface rien.
  * Les coins REFUSÉS sont enregistrés AUSSI, avec leur motif — un refus est une donnée.

PAPER only : enregistrer une observation n'est pas passer un ordre.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterable

RELPATH = Path("runtime") / "replay" / "carry_scan.jsonl"
#: au-delà, on ROULE le fichier (renommage horodaté). On n'efface jamais une observation.
TAILLE_MAX_OCTETS = 512 * 1024 * 1024
MODES_VALIDES = ("LIVE", "BACKTEST", "REPLAY", "TEST_FIXTURE")

#: liste blanche — tout ce qu'il faut pour REJOUER une décision, rien de plus.
CHAMPS_NOMBRE = (
    "funding_bps_h", "funding_snapshot_bps_h", "funding_persistant_bps_h", "funding_zscore",
    "funding_prevu_bps_h", "premium_bps", "delta_oi_pct", "facteur_taille",
    "base_bps", "base_mid_bps", "liquidite_spot_usd", "perp_px", "spot_px",
    "levier_max", "levier_utilise", "marge_ratio", "pire_hausse_observee",
    "securite_liquidation", "cout_entree_bps", "break_even_h", "gain_net_24h_bps",
)
CHAMPS_TEXTE = ("coin", "motif", "alerte_rupture", "funding_regime", "funding_tendance", "source",
                # P1-4 : la PROVENANCE de l'appariement perp<->spot. Un appariement heuristique
                # doit rester identifiable dans l'historique, sinon on ne pourra jamais
                # rattacher une anomalie de base a un mauvais mapping.
                "mapping_source", "canonical_mapping", "hypercore_token_name")
CHAMPS_BOOL = ("viable", "funding_fiable", "maker")


def _nombre(v: Any) -> float | None:
    """Un nombre exploitable, sinon None. `None` = ABSENT, jamais 0 : un zéro fabriqué
    ment plus qu'un trou avoué."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return None if f != f or f in (float("inf"), float("-inf")) else f


def normaliser(brut: dict[str, Any], *, ts_ms: int, session_id: str = "",
               mode: str = "LIVE") -> dict[str, Any] | None:
    """Une ligne de scan prête à écrire, ou None si elle n'a même pas de coin.
    Les champs absents restent absents — on n'invente rien."""
    if not isinstance(brut, dict):
        return None
    coin = str(brut.get("coin") or "").strip().upper()
    if not coin:
        return None
    if mode not in MODES_VALIDES:
        raise ValueError("mode inconnu: %r (attendu %s)" % (mode, list(MODES_VALIDES)))
    ligne: dict[str, Any] = {"ts_ms": int(ts_ms), "mode": mode, "coin": coin,
                             "real_execution": False}
    if session_id:
        ligne["session_id"] = str(session_id)
    for k in CHAMPS_NOMBRE:
        v = _nombre(brut.get(k))
        if v is not None:
            ligne[k] = round(v, 8)
    for k in CHAMPS_TEXTE:
        if k == "coin":
            continue
        v = brut.get(k)
        if isinstance(v, dict):                    # ex. alerte_rupture -> son niveau
            v = v.get("niveau")
        if v is not None and str(v).strip():
            ligne[k] = str(v).strip()[:200]
    for k in CHAMPS_BOOL:
        v = brut.get(k)
        if isinstance(v, bool):
            ligne[k] = v
    return ligne


def _rouler_si_trop_gros(chemin: Path, taille_max: int) -> None:
    """Roule par RENOMMAGE. 🔴 Attrapé par son propre test : deux rotations dans la MÊME
    seconde produisaient le même nom d'archive, et `os.replace` écrasait la précédente —
    l'enregistreur perdait les observations qu'il était censé sauver. Le nom est désormais
    rendu unique par un suffixe incrémental : on n'efface JAMAIS une observation."""
    try:
        if not (chemin.exists() and chemin.stat().st_size >= int(taille_max)):
            return
        base = "%s.%s" % (chemin.stem, time.strftime("%Y%m%d-%H%M%S"))
        cible = chemin.with_name(base + ".jsonl")
        n = 1
        while cible.exists():
            cible = chemin.with_name("%s-%d.jsonl" % (base, n))
            n += 1
        os.replace(chemin, cible)
    except OSError:
        pass                                       # on n'efface jamais, et on ne bloque jamais


def enregistrer(root: str | Path, lignes: Iterable[dict[str, Any]], *,
                ts_ms: int | None = None, session_id: str = "", mode: str = "LIVE",
                taille_max: int = TAILLE_MAX_OCTETS) -> int:
    """Ajoute les lignes au journal de scans. Retourne le nombre écrit. **Ne lève jamais.**"""
    try:
        now = int(ts_ms if ts_ms is not None else time.time() * 1000)
        prets = []
        for brut in lignes or ():
            try:
                l = normaliser(brut, ts_ms=now, session_id=session_id, mode=mode)
            except ValueError:
                raise
            except Exception:                      # noqa: BLE001 — une ligne moche n'annule pas les 19 autres
                l = None
            if l is not None:
                prets.append(json.dumps(l, ensure_ascii=False))
        if not prets:
            return 0
        chemin = Path(root) / RELPATH
        chemin.parent.mkdir(parents=True, exist_ok=True)
        _rouler_si_trop_gros(chemin, taille_max)
        with chemin.open("a", encoding="utf-8") as f:
            f.write("\n".join(prets) + "\n")
        return len(prets)
    except ValueError:                             # mode invalide = faute de programmation, pas de données
        raise
    except Exception:                              # noqa: BLE001
        return 0


def charger(root: str | Path, *, mode: str = "LIVE", depuis_ms: int | None = None,
            coins: Iterable[str] | None = None, limite: int | None = None) -> list[dict]:
    """Relit le journal (filtrable). Fichier absent ou illisible -> liste VIDE, jamais une
    exception : un backtest sans données doit dire « pas de données », pas planter."""
    filtre_coins = {str(c).upper() for c in coins} if coins else None
    sortie: list[dict] = []
    try:
        chemin = Path(root) / RELPATH
        with chemin.open(encoding="utf-8", errors="ignore") as f:
            for l in f:
                l = l.strip()
                if not l:
                    continue
                try:
                    d = json.loads(l)
                except ValueError:
                    continue
                if not isinstance(d, dict) or d.get("mode") != mode:
                    continue
                if depuis_ms is not None and float(d.get("ts_ms") or 0) < float(depuis_ms):
                    continue
                if filtre_coins and str(d.get("coin") or "") not in filtre_coins:
                    continue
                sortie.append(d)
                if limite and len(sortie) >= int(limite):
                    break
    except OSError:
        return []
    return sortie


def resume(root: str | Path, *, mode: str = "LIVE") -> dict[str, Any]:
    """Ce que le journal contient, en clair — pour TOUT-TESTER et le rapport quotidien.
    Un volume de données qu'on ne peut pas citer finira par être surestimé."""
    lignes = charger(root, mode=mode)
    if not lignes:
        return {"lignes": 0, "coins": 0, "passes": 0, "etendue_h": 0.0, "viables": 0,
                "octets": 0, "mode": mode, "vide": True}
    ts = sorted({int(d.get("ts_ms") or 0) for d in lignes})
    coins = {str(d.get("coin")) for d in lignes}
    try:
        octets = (Path(root) / RELPATH).stat().st_size
    except OSError:
        octets = 0
    motifs: dict[str, int] = {}
    for d in lignes:
        if not d.get("viable"):
            m = str(d.get("motif") or "?")[:60]
            motifs[m] = motifs.get(m, 0) + 1
    return {
        "lignes": len(lignes), "coins": len(coins), "passes": len(ts),
        "etendue_h": round((ts[-1] - ts[0]) / 3.6e6, 2) if len(ts) > 1 else 0.0,
        "viables": sum(1 for d in lignes if d.get("viable")),
        "octets": octets, "mode": mode, "vide": False,
        "coins_listes": sorted(coins),
        "motifs_de_refus": dict(sorted(motifs.items(), key=lambda kv: -kv[1])[:8]),
    }


__all__ = ["RELPATH", "MODES_VALIDES", "TAILLE_MAX_OCTETS", "normaliser", "enregistrer",
           "charger", "resume"]
