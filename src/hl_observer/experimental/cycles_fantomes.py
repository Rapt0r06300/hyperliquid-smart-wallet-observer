r"""Cycles FANTÔMES du bac à sable : de quoi apprendre sans jamais créer de PnL économique.

POURQUOI (22/11/2026). La boucle d'auto-amélioration jugeait les cycles CLOS du bac à sable
(RAW_PROBE). Or une garde VOULUE, verrouillée par `test_raw_probe_sans_edge_reste_shadow_sans_pnl`,
interdit à ce bac à sable d'ouvrir sans avance mesurée : il n'ouvre donc jamais, et la boucle
attendait des cycles qui ne pouvaient pas exister (mesuré en direct : 660 ouvertures de leaders vues,
0 position, 0/20). La garde reste ; la boucle apprend sur des cycles SIMULÉS, marqués `fantome`.

LA RÈGLE SIMULÉE, celle du bac à sable :
* déclenchement : fill d'ouverture d'un leader dont le notionnel atteint le seuil relatif
  `clamp(frac × TVL, plancher, plafond)` (par fill : approximation du cumul du moteur, déclarée) ;
* entrée : premier prix de la bande ≥ l'heure de RÉCEPTION du fill (ce que le moteur savait) ;
  un prix vieux de plus de 30 s refuse l'entrée ;
* sortie : la PREMIÈRE de trois — le leader ferme ou réduit (sortie miroir, comme `LEADER_A_CLOS`),
  le stop est touché, l'horizon est atteint ; chacune au premier prix ≥ son instant ;
  (approximation déclarée : sortie COMPLÈTE au premier fill de clôture, là où le moteur réduit au prorata) ;
* coût : frais aller-retour + écart supposé, déclarés dans chaque cycle.

TROIS PRÉCAUTIONS, tirées des erreurs du 22/11 :
1. **Aucune sélection sur l'issue.** Une entrée n'est simulée qu'une fois plus vieille que l'horizon
   (+ marge) : elle est alors résolue QUEL QUE SOIT son résultat. Une entrée dont la bande de prix
   ne couvre pas la vie est COMPTÉE `non_resolue`, jamais ignorée en silence.
2. **Données neuves seulement.** Une variante n'est jugée que sur les entrées postérieures à sa mise
   en service (`depuis_ms`) : pas de re-notation du même passé jusqu'à trouver un gagnant.
3. **Registre durable.** Le journal des fills est archivé à chaque arrêt ; les cycles, eux, sont
   ajoutés à `runtime/auto_amelioration/cycles_fantomes.ndjson`, dédoublonnés par (fill, variante).

PAPER, LECTURE SEULE du marché. Aucun ordre, aucun réseau.
"""
from __future__ import annotations

import bisect
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

JOURNAL = Path("runtime") / "data" / "fills_journal.jsonl"
REGISTRE = Path("runtime") / "auto_amelioration" / "cycles_fantomes.ndjson"
SCORES = Path("runtime") / "data" / "vaults_scores.json"
PRIX_PERIME_MS = 30_000
MARGE_RESOLUTION_MS = 120_000
COUT_BPS = 12.0                  # même hypothèse que `raw_shadow_variantes` : 2 × 4,5 bps + 3 bps d'écart
FLOOR_USD, PLAFOND_USD = 150.0, 2000.0


def _cote(direction: str) -> int | None:
    d = str(direction or "")
    if d.endswith("Long"):
        return 1
    if d.endswith("Short"):
        return -1
    return None


def _prix_a(serie: Sequence[tuple[int, float]], instants: list[int], t_ms: float) -> tuple[int, float] | None:
    """Premier point de la bande à ou après `t_ms`, s'il n'est pas périmé."""
    i = bisect.bisect_left(instants, t_ms)
    if i >= len(serie) or serie[i][0] - t_ms > PRIX_PERIME_MS:
        return None
    return serie[i]


def tvl_par_vault(root: Path) -> dict[str, float]:
    try:
        d = json.loads((Path(root) / SCORES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(c["vault"]).lower(): float((c.get("facteurs") or {}).get("tvl_usd") or 0.0)
            for c in (d.get("classement") or []) if isinstance(c, dict) and c.get("vault")}


def simuler(lignes: Sequence[Mapping[str, Any]], tape: Mapping[str, Sequence[tuple[int, float]]],
            tvl: Mapping[str, float], *, frac_tvl: float, stop_bps: float, horizon_ms: float,
            depuis_ms: float, now_ms: float, notional_usd: float = 20.0, cout_bps: float = COUT_BPS,
            etiquette: str = "") -> dict[str, Any]:
    """Les cycles fantômes RÉSOLUS d'une variante, plus le compte de ce qui ne l'est pas (et pourquoi)."""
    ouvertures, clotures = [], {}
    for x in lignes:
        cote = _cote(x.get("dir"))
        recu = x.get("recu_ms") or x.get("received_at_ms")
        if cote is None or not isinstance(recu, (int, float)) or x.get("isSnapshot"):
            continue
        cle = (str(x.get("vault") or "").lower(), str(x.get("coin") or ""), cote)
        if str(x.get("dir")).startswith("Open"):
            ouvertures.append((float(recu), cle, x))
        elif str(x.get("dir")).startswith("Close"):
            clotures.setdefault(cle, []).append(float(recu))
    for v in clotures.values():
        v.sort()
    index = {c: [p[0] for p in s] for c, s in tape.items()}
    cycles: list[dict[str, Any]] = []
    compte = {"declenchements": 0, "trop_recents": 0, "sans_prix": 0, "non_resolue": 0, "doublons": 0}
    vus: set[str] = set()
    for recu, (vault, coin, cote), x in sorted(ouvertures, key=lambda e: e[0]):
        if recu < depuis_ms:
            continue                                         # données neuves seulement
        try:
            notionnel = abs(float(x.get("sz") or 0.0)) * float(x.get("px") or 0.0)
        except (TypeError, ValueError):
            continue
        t = tvl.get(vault, 0.0)
        seuil = min(max(FLOOR_USD, frac_tvl * t), PLAFOND_USD) if t > 0 else PLAFOND_USD
        if notionnel < seuil:
            continue
        # 22/11/2026 : l'identité d'un cycle est l'ORDRE du leader (`oid`), pas le fill. Un ordre exécuté en
        # quatre fills faisait quatre cycles fantômes identiques : un échantillon gonflé de doublons corrélés.
        oid = x.get("oid")
        identite = (f"oid:{vault}:{coin}:{oid}" if oid not in (None, "")
                    else str(x.get("hash") or x.get("tid") or f"{vault}:{coin}:{recu}"))
        if identite in vus:
            compte["doublons"] += 1                          # plusieurs fills d'un même ordre : un seul cycle
            continue
        vus.add(identite)
        compte["declenchements"] += 1
        if recu > now_ms - horizon_ms - MARGE_RESOLUTION_MS:
            compte["trop_recents"] += 1                      # pas encore résolu QUEL QUE SOIT son sort : attendu
            continue
        serie = tape.get(coin) or tape.get(coin.upper())
        instants = index.get(coin) if coin in tape else index.get(coin.upper())
        if not serie:
            compte["sans_prix"] += 1
            continue
        entree = _prix_a(serie, instants, recu)
        if entree is None:
            compte["sans_prix"] += 1
            continue
        t0, p0 = entree
        fin = t0 + horizon_ms
        candidats = [("HORIZON", fin)]
        sorties = clotures.get((vault, coin, cote), [])
        j = bisect.bisect_right(sorties, recu)
        if j < len(sorties) and sorties[j] < fin:
            candidats.append(("LEADER_A_CLOS", sorties[j]))
        i0 = bisect.bisect_left(instants, t0)
        stop_t = None
        for ts, p in serie[i0:]:
            if ts > fin:
                break
            if 1e4 * cote * (p / p0 - 1.0) <= -stop_bps:
                stop_t = ts
                break
        if stop_t is not None:
            candidats.append(("STOP", stop_t))
        motif, t_sortie = min(candidats, key=lambda c: c[1])
        sortie = _prix_a(serie, instants, t_sortie)
        if sortie is None:
            compte["non_resolue"] += 1                       # la bande ne couvre pas sa vie : compté, pas sauté
            continue
        brut = 1e4 * cote * (sortie[1] / p0 - 1.0)
        # CONTEXTE CONNU À L'ENTRÉE (22/11/2026) — pour juger plus tard, sur données neuves, des règles de
        # REFUS (signal déjà absorbé, latence) sans toucher à la règle simulée : n'entre dans aucun gain.
        try:
            px_leader = float(x.get("px"))
            absorption = 1e4 * cote * (p0 / px_leader - 1.0) if px_leader > 0 else None
        except (TypeError, ValueError):
            absorption = None
        fill_ts = x.get("fill_ts_ms") or x.get("ts_ms")
        cycles.append({
            "evt": "CLOSE", "fantome": True, "trigger_version": etiquette, "identite": identite,
            "vault": vault, "coin": coin, "sens": cote, "entree_ms": int(t0), "sortie_ms": int(sortie[0]),
            "motif_sortie": motif, "brut_bps": round(brut, 3), "cout_bps": cout_bps,
            "realized_usd": round(notional_usd * (brut - cout_bps) / 1e4, 6),
            "notional_usd": notional_usd, "paper": True, "real_execution": False,
            "contexte": {"absorption_bps": None if absorption is None else round(absorption, 3),
                         "latence_ms": int(t0 - fill_ts) if isinstance(fill_ts, (int, float)) else None,
                         "notionnel_leader_usd": round(notionnel, 2)},
        })
    return {"cycles": cycles, "compte": compte}


BANDE_DE_PRIX = Path("runtime") / "data" / "hl_allmids_tape.jsonl"
BLOC_OCTETS = 4 * 1024 * 1024


def bande_de_prix(root: Path, *, depuis_ms: float, chemin: Path | None = None) -> dict[str, list[tuple[int, float]]]:
    """La bande de prix (allMids) sur la seule fenêtre utile, lue DEPUIS LA FIN du fichier.

    22/11/2026 : le fichier grossit d'environ 500 Mo par jour, et l'apprentissage le relisait EN ENTIER
    toutes les 5 minutes (l'écran en direct, toutes les 3 secondes). On remonte par blocs jusqu'à la
    première ligne antérieure à `depuis_ms`, sans jamais décoder le reste. Clés en majuscules, comme
    `copy_edge_forward.charger_prix_tape`, pour que les deux lecteurs rendent la même chose."""
    p = chemin or (Path(root) / BANDE_DE_PRIX)
    try:
        f = p.open("rb")
    except OSError:
        return {}
    morceaux: list[bytes] = []
    with f:
        fin = f.seek(0, 2)
        pos = fin
        while pos > 0:
            debut = max(0, pos - BLOC_OCTETS)
            f.seek(debut)
            bloc = f.read(pos - debut)
            morceaux.append(bloc)
            pos = debut
            if pos == 0:
                break
            # la première ligne COMPLÈTE de ce bloc dit si l'on est remonté assez loin
            nl = bloc.find(b"\n")
            if nl < 0:
                continue
            premiere = bloc[nl + 1: bloc.find(b"\n", nl + 1) if bloc.find(b"\n", nl + 1) > 0 else None]
            try:
                ts = json.loads(premiere).get("ts_ms")
            except ValueError:
                continue
            if isinstance(ts, (int, float)) and ts < depuis_ms:
                break
    brut = b"".join(reversed(morceaux))
    if pos > 0:
        brut = brut[brut.find(b"\n") + 1:]                 # première ligne coupée par le bloc
    tape: dict[str, list[tuple[int, float]]] = {}
    for ligne in brut.splitlines():
        try:
            d = json.loads(ligne)
        except ValueError:
            continue
        ts = d.get("ts_ms")
        if not isinstance(ts, int) or isinstance(ts, bool) or ts < depuis_ms:
            continue
        for c, px in (d.get("mids") or {}).items():
            try:
                prix = float(px)
            except (TypeError, ValueError):
                continue
            if prix > 0 and prix == prix and prix != float("inf"):
                tape.setdefault(str(c).upper(), []).append((ts, prix))
    for serie in tape.values():
        serie.sort()
    return tape


def lire_registre(root: Path) -> list[dict[str, Any]]:
    try:
        texte = (Path(root) / REGISTRE).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    out = []
    for ligne in texte.splitlines():
        try:
            x = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(x, dict) and x.get("fantome") is True:
            out.append(x)
    return out


def ajouter_au_registre(root: Path, cycles: Sequence[Mapping[str, Any]]) -> int:
    """Ajoute les cycles jamais vus (clé : identité du fill + variante). Rend le nombre ajouté."""
    connus = {(c.get("identite"), c.get("trigger_version")) for c in lire_registre(root)}
    neufs = [c for c in cycles if (c.get("identite"), c.get("trigger_version")) not in connus]
    if not neufs:
        return 0
    chemin = Path(root) / REGISTRE
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("a", encoding="utf-8") as f:
        for c in neufs:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return len(neufs)


def lire_journal(root: Path) -> list[dict[str, Any]]:
    try:
        texte = (Path(root) / JOURNAL).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    out = []
    for ligne in texte.splitlines():
        try:
            x = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(x, dict) and x.get("cohorte") in (None, "RAW_PROBE"):
            out.append(x)
    return out


__all__ = ["COUT_BPS", "REGISTRE", "ajouter_au_registre", "lire_journal", "lire_registre", "simuler",
           "tvl_par_vault"]
