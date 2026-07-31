"""ALPHA FACTORY — squelette générique + registre global des essais + table canonique de candidats.

Idée : chaque expérience du labo, quelle que soit sa piste, produit UNE ligne canonique commune :

    DATA × EVENT × STATE × FILTER × HORIZON × EXECUTION → RESULT

et est enregistrée dans le **registre global** — y compris les essais négatifs (c'est le but : garder la
trace de tout, pour ne pas re-tester en boucle et pour lire la queue de distribution). Pas de data
snooping : `config_frozen` décrit l'espace de recherche gelé AVANT l'OOS ; la sélection ne s'y touche plus.

Anti-maquillage : tout champ non mesuré sort en `UNMEASURABLE` (jamais 0). Le coût total additionne
seulement les composantes mesurables et signale si la somme est incomplète. La table finale n'a QUE les
colonnes demandées : IDEA | CONFIG FROZEN | N IND | GROSS | COST | NET | LCB | OOS | FORWARD | CAPACITY | VERDICT.

Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "hypersmart.alpha_factory.v1"
UNMEASURABLE = "UNMEASURABLE"


def _hash(*parts: Any) -> str:
    """Hash déterministe court (repro : même entrée -> même hash)."""
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]

#: Dimensions de l'espace de recherche (pour tracer chaque essai sans ambiguïté).
DIMENSIONS = ("data", "event", "state", "filter", "horizon", "execution")

#: Composantes de coût additionnées pour COST (bps).
COMPOSANTES_COUT = ("fees_bps", "spread_bps", "slippage_bps", "latency_bps")

#: Champs de la ligne canonique (ordre stable).
CHAMPS = (
    "trial_id", "config_hash", "dataset_hash", "pipeline_hash",
    "idea", "config_frozen", *DIMENSIONS,
    "n_raw", "n_independent", "gross_bps",
    *COMPOSANTES_COUT, "cost_total_bps", "cost_incomplet",
    "net_bps", "lcb_net_bps", "pf", "dd", "es",
    "fill_ratio", "capacity_usd", "discovery", "oos", "forward",
    "verdict", "notes", "sha",
)


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def cout_total(row: Mapping[str, Any]) -> tuple[float | str, bool]:
    """Somme des composantes de coût MESURABLES. Retourne (total_ou_UNMEASURABLE, incomplet?)."""
    vals = [(_num(row.get(c))) for c in COMPOSANTES_COUT]
    presents = [v for v in vals if v is not None]
    incomplet = any(v is None for v in vals)
    if not presents:
        return UNMEASURABLE, True
    return round(sum(presents), 4), incomplet


def ligne_canonique(idea: str, *, config_frozen: Mapping[str, Any] | str, verdict: str,
                    data: Any = UNMEASURABLE, event: Any = UNMEASURABLE, state: Any = UNMEASURABLE,
                    filter: Any = UNMEASURABLE, horizon: Any = UNMEASURABLE, execution: Any = UNMEASURABLE,
                    n_raw: Any = UNMEASURABLE, n_independent: Any = UNMEASURABLE, gross_bps: Any = UNMEASURABLE,
                    fees_bps: Any = UNMEASURABLE, spread_bps: Any = UNMEASURABLE, slippage_bps: Any = UNMEASURABLE,
                    latency_bps: Any = UNMEASURABLE, net_bps: Any = UNMEASURABLE, lcb_net_bps: Any = UNMEASURABLE,
                    pf: Any = UNMEASURABLE, dd: Any = UNMEASURABLE, es: Any = UNMEASURABLE,
                    fill_ratio: Any = UNMEASURABLE, capacity_usd: Any = UNMEASURABLE,
                    discovery: Any = UNMEASURABLE, oos: Any = UNMEASURABLE, forward: Any = UNMEASURABLE,
                    notes: str = "", sha: str = UNMEASURABLE,
                    dataset_hash: str = UNMEASURABLE, pipeline_hash: str = UNMEASURABLE) -> dict[str, Any]:
    """Construit une ligne canonique ; tout champ non fourni reste UNMEASURABLE (jamais 0).

    P13: chaque ligne porte trial_id + config_hash (deterministe sur idea+config+dimensions) + dataset_hash
    + pipeline_hash, pour la reproductibilite et la correction multiple-testing."""
    config_hash = _hash(idea, config_frozen, data, event, state, filter, horizon, execution)
    row: dict[str, Any] = {
        "trial_id": config_hash[:12], "config_hash": config_hash,
        "dataset_hash": dataset_hash, "pipeline_hash": pipeline_hash,
        "idea": idea, "config_frozen": config_frozen, "data": data, "event": event, "state": state,
        "filter": filter, "horizon": horizon, "execution": execution, "n_raw": n_raw,
        "n_independent": n_independent, "gross_bps": gross_bps, "fees_bps": fees_bps,
        "spread_bps": spread_bps, "slippage_bps": slippage_bps, "latency_bps": latency_bps,
        "net_bps": net_bps, "lcb_net_bps": lcb_net_bps, "pf": pf, "dd": dd, "es": es,
        "fill_ratio": fill_ratio, "capacity_usd": capacity_usd, "discovery": discovery, "oos": oos,
        "forward": forward, "verdict": verdict, "notes": notes, "sha": sha,
    }
    total, incomplet = cout_total(row)
    row["cost_total_bps"] = total
    row["cost_incomplet"] = incomplet
    return row


class TrialRegistry:
    """Registre global append-only (JSONL). Tous les essais, positifs comme négatifs."""

    def __init__(self, path: str) -> None:
        self.path = path

    def record(self, row: Mapping[str, Any]) -> dict[str, Any]:
        r = dict(row)
        if "cost_total_bps" not in r:
            total, incomplet = cout_total(r)
            r["cost_total_bps"], r["cost_incomplet"] = total, incomplet
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return r

    def load(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        out.append(json.loads(line))
        except FileNotFoundError:
            pass
        return out


def _c(v: Any) -> str:
    if v is None:
        return "?"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def _config_court(cfg: Any) -> str:
    if isinstance(cfg, str):
        return cfg
    if isinstance(cfg, Mapping):
        return " ".join(f"{k}={cfg[k]}" for k in list(cfg)[:6])
    return str(cfg)


#: Ordre de tri des verdicts (les vrais candidats d'abord).
_RANG_VERDICT = {"CANDIDAT": 0, "FORWARD_REQUIS": 1, "OOS_POSITIF_A_FORWARD": 1, "MORE_DATA": 2,
                 "PROMETTEUR": 2, "KILL_CONCENTRE": 3, "KILL": 4, "BLOCKED_EXTERNAL": 5}


def emit_table(rows: Sequence[Mapping[str, Any]]) -> str:
    """Rend la table canonique markdown, candidats en tête."""
    def cle(r: Mapping[str, Any]) -> tuple:
        lcb = _num(r.get("lcb_net_bps"))
        return (_RANG_VERDICT.get(str(r.get("verdict")), 9), -(lcb if lcb is not None else -1e9))

    ordered = sorted(rows, key=cle)
    head = ("| IDEA | CONFIG FROZEN | N IND | GROSS | COST | NET | LCB | OOS | FORWARD | CAPACITY | VERDICT |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|")
    lignes = [head]
    for r in ordered:
        lignes.append("| " + " | ".join([
            str(r.get("idea", "?")), _config_court(r.get("config_frozen")),
            _c(r.get("n_independent")), _c(r.get("gross_bps")), _c(r.get("cost_total_bps")),
            _c(r.get("net_bps")), _c(r.get("lcb_net_bps")), _c(r.get("oos")), _c(r.get("forward")),
            _c(r.get("capacity_usd")), str(r.get("verdict", "?")),
        ]) + " |")
    return "\n".join(lignes)


__all__ = ["SCHEMA_VERSION", "UNMEASURABLE", "DIMENSIONS", "COMPOSANTES_COUT", "CHAMPS",
           "cout_total", "ligne_canonique", "TrialRegistry", "emit_table"]
