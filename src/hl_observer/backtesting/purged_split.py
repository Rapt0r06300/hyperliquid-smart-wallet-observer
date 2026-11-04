"""#410 / H-05 + #435 / H-30 — LA COUPE TRAIN/TEST FUITAIT. Purge + embargo (2026-07-13).

═══════════════════════════════════════════════════════════════════════════════════════════════
🔴 LA FUITE, EN CINQ LIGNES
═══════════════════════════════════════════════════════════════════════════════════════════════

    def temporal_split(candidates, train_frac=0.7):
        k = int(len(cs) * train_frac)
        return cs[:k], cs[k:]              # AUCUNE purge. AUCUN embargo.

Un candidat en **fin de TRAIN** ouvre un trade. Sa **sortie** arrive `horizon_min` plus tard --
et notre horizon monte jusqu'a **8 HEURES**. Elle tombe donc **DANS la periode de TEST**.

Consequence : le PnL d'entrainement de ce trade est calcule **avec des prix du test**. Et c'est
sur ce train contamine qu'on **CHOISIT** la configuration SL/TP.

    **Le test etait deja dans le train.** On mesurait « hors echantillon » un choix fait AVEC
    l'echantillon.

C'est exactement le bug que `purged_walk_forward_splits` (IDEA-30) devait empecher.
**Il etait MORT : zero appelant** -- comme les six autres garde-fous anti-overfit (M-19).
*H-05 et H-30 pointaient un bug chez NOUS, pas une idee a copier chez eux.*

═══════════════════════════════════════════════════════════════════════════════════════════════
LE CORRECTIF, ET SES DEUX MOITIES
═══════════════════════════════════════════════════════════════════════════════════════════════

  **PURGE** (obligatoire) : on RETIRE du TRAIN tout candidat dont le trade peut encore etre
  ouvert quand le TEST commence. `entree + horizon > frontiere` -> dehors.
  *C'est ce qui empeche le futur de couler dans le passe.*

  **EMBARGO** (prudence) : on retire du TEST les premiers candidats apres la frontiere. Leurs
  chemins de prix partagent des instants avec les trades du train ; sans embargo, une
  auto-correlation residuelle peut encore relier les deux.

⚠️ ON PERD DES DONNEES. C'est le PRIX de l'honnetete, et il faut le dire : purger REDUIT
l'echantillon. Un backtest qui refuse de purger « pour garder des donnees » est un backtest qui
choisit de se mentir.

PUR. Aucun ordre reel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

# 🔴 L'EMBARGO EST UNE **FRACTION DE L'HORIZON**, PAS UNE CONSTANTE.
#
# Ma 1re version le fixait a **30 minutes en dur**. Sur un jeu de test ou la periode de test dure
# 8 minutes, il l'a **entierement mangee** -- et le test a rougi, a raison.
#
# Un embargo constant est un nombre INVENTE. L'auto-correlation qu'il doit briser vit a l'echelle
# de temps du TRADE (son horizon), pas a une echelle que j'aurais choisie. On l'y attache donc :
#     embargo = 10 % de l'horizon.
# *Une constante qu'on ne peut pas justifier est une constante qui finira par mentir.*
EMBARGO_FRACTION_DE_L_HORIZON = 0.10

MOTIF_TRAIN_VIDE = "PURGE_A_VIDE_LE_TRAIN_HORIZON_TROP_LONG_POUR_CET_ECHANTILLON"


@dataclass(frozen=True, slots=True)
class Coupe:
    """Une coupe train/test HONNETE : elle DIT ce qu'elle a jete."""

    train: list[dict[str, Any]]
    test: list[dict[str, Any]]
    n_purges: int              # retires du TRAIN (leur sortie tombait dans le test)
    n_embargo: int             # retires du TEST (trop proches de la frontiere)
    frontiere_ts: float
    horizon_min: float
    embargo_min: float

    @property
    def valide(self) -> bool:
        return bool(self.train) and bool(self.test)

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_train": len(self.train), "n_test": len(self.test),
            "n_purges": self.n_purges, "n_embargo": self.n_embargo,
            "frontiere_ts": self.frontiere_ts,
            "horizon_min": self.horizon_min, "embargo_min": self.embargo_min,
            "valide": self.valide,
            "note": (
                "PURGE : les candidats du train dont le trade pouvait encore etre ouvert dans le "
                "test ont ete RETIRES. Sans elle, le PnL du train se calculait avec des prix du "
                "test -- et la config etait CHOISIE dessus."
            ),
            "real_execution": False,
        }


def _ts(c: Mapping[str, Any]) -> float:
    return float(c.get("recorded_at") or 0.0)


def purged_temporal_split(
    candidates: Sequence[Mapping[str, Any]],
    *,
    train_frac: float = 0.7,
    horizon_min: float,
    embargo_min: float | None = None,
) -> Coupe:
    """La coupe train/test AVEC purge et embargo.

    `horizon_min` : la duree MAXIMALE pendant laquelle un trade peut rester ouvert. C'est elle
    qui dit jusqu'ou le futur peut couler dans le passe. **On prend le PIRE horizon de la grille**,
    pas le moyen : une seule config qui fuit suffit a contaminer la selection.
    """
    # L'embargo est une FRACTION de l'horizon, jamais une constante inventee.
    embargo_min = (float(horizon_min) * EMBARGO_FRACTION_DE_L_HORIZON
                   if embargo_min is None else float(embargo_min))

    cs = sorted((dict(c) for c in candidates), key=_ts)
    if len(cs) <= 1:
        return Coupe(cs, [], 0, 0, 0.0, float(horizon_min), float(embargo_min))

    k = max(1, min(len(cs) - 1, int(len(cs) * float(train_frac))))
    frontiere = _ts(cs[k])

    h_s = float(horizon_min) * 60.0
    e_s = float(embargo_min) * 60.0

    # 🔴 LA PURGE : un candidat du train dont la sortie peut tomber APRES la frontiere est retire.
    train_brut = cs[:k]
    train = [c for c in train_brut if _ts(c) + h_s <= frontiere]
    n_purges = len(train_brut) - len(train)

    # L'EMBARGO : on ecarte les premiers candidats du test.
    test_brut = cs[k:]
    test = [c for c in test_brut if _ts(c) >= frontiere + e_s]
    n_embargo = len(test_brut) - len(test)

    return Coupe(
        train=train, test=test, n_purges=n_purges, n_embargo=n_embargo,
        frontiere_ts=frontiere, horizon_min=float(horizon_min),
        embargo_min=float(embargo_min),
    )


def fuite_potentielle(
    candidates: Sequence[Mapping[str, Any]],
    *,
    train_frac: float = 0.7,
    horizon_min: float,
) -> dict[str, Any]:
    """Combien de candidats la coupe NON purgee laissait fuir ? **Le chiffre de la faute.**

    C'est la mesure que H-30 appelle `lookahead-analysis` : *de combien mon backtest triche-t-il ?*
    """
    coupe = purged_temporal_split(
        candidates, train_frac=train_frac, horizon_min=horizon_min, embargo_min=0.0,
    )
    n_train_brut = coupe.n_purges + len(coupe.train)
    part = (coupe.n_purges / n_train_brut) if n_train_brut else 0.0
    return {
        "n_train_avant_purge": n_train_brut,
        "n_candidats_qui_FUYAIENT": coupe.n_purges,
        "part_du_train_contaminee": round(part, 4),
        "horizon_min": float(horizon_min),
        "verdict": (
            "AUCUNE FUITE" if coupe.n_purges == 0 else
            "🔴 %d candidats du train (%.1f %%) avaient leur SORTIE dans la periode de TEST. "
            "Leur PnL d'entrainement etait calcule avec des prix du test -- et la config etait "
            "CHOISIE dessus." % (coupe.n_purges, 100 * part)
        ),
        "real_execution": False,
    }


def purge_overlapping_periods(
    train_rows: Sequence[Mapping[str, Any]],
    oos_rows: Sequence[Mapping[str, Any]],
    *,
    embargo_ms: int = 0,
    start_field: str = "start_ms",
    end_field: str = "end_ms",
    episode_id_field: str = "episode_id",
) -> dict[str, Any]:
    """Remove interval overlap from both TRAIN and OOS, fail-closed.

    A row is removed from its split when its measured interval overlaps any
    row in the other split, expanded by the declared embargo.  Missing or
    invalid boundaries and duplicate episode identifiers are not silently
    discarded: the result is ``UNMEASURABLE``.
    """

    if isinstance(embargo_ms, bool) or not isinstance(embargo_ms, int) or embargo_ms < 0:
        return {"status": "UNMEASURABLE", "reason": "INVALID_EMBARGO", "paper_read_only": True}

    def _parse(rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
        parsed: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows or ():
            if not isinstance(row, Mapping):
                return [], "INVALID_ROW"
            episode = str(row.get(episode_id_field) or "").strip()
            start = row.get(start_field)
            end = row.get(end_field)
            if (
                not episode
                or episode in seen
                or isinstance(start, bool)
                or not isinstance(start, int)
                or isinstance(end, bool)
                or not isinstance(end, int)
                or start <= 0
                or end < start
            ):
                return [], "INVALID_INTERVAL_OR_DUPLICATE_EPISODE"
            seen.add(episode)
            parsed.append({**dict(row), "_start_ms": start, "_end_ms": end, "_episode_id": episode})
        return parsed, None

    train, train_error = _parse(train_rows)
    oos, oos_error = _parse(oos_rows)
    if train_error or oos_error or not train or not oos:
        return {
            "status": "UNMEASURABLE",
            "reason": train_error or oos_error or "EMPTY_SPLIT",
            "paper_read_only": True,
            "real_execution": False,
        }

    train_overlap: set[str] = set()
    oos_overlap: set[str] = set()
    overlap_pairs: list[tuple[str, str]] = []
    for left in train:
        for right in oos:
            overlaps = (
                left["_start_ms"] <= right["_end_ms"] + embargo_ms
                and right["_start_ms"] <= left["_end_ms"] + embargo_ms
            )
            if overlaps:
                train_overlap.add(left["_episode_id"])
                oos_overlap.add(right["_episode_id"])
                overlap_pairs.append((left["_episode_id"], right["_episode_id"]))

    kept_train = [row for row in train if row["_episode_id"] not in train_overlap]
    kept_oos = [row for row in oos if row["_episode_id"] not in oos_overlap]
    for row in (*kept_train, *kept_oos):
        row.pop("_start_ms", None)
        row.pop("_end_ms", None)
        row.pop("_episode_id", None)
    return {
        "status": "COMPARABLE" if kept_train and kept_oos else "UNMEASURABLE",
        "reason": None if kept_train and kept_oos else "PURGE_REMOVED_A_SPLIT",
        "train": kept_train,
        "oos": kept_oos,
        "purged_train": len(train_overlap),
        "purged_oos": len(oos_overlap),
        "overlap_pairs": [list(pair) for pair in sorted(overlap_pairs)],
        "embargo_ms": embargo_ms,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "EMBARGO_FRACTION_DE_L_HORIZON", "MOTIF_TRAIN_VIDE",
    "Coupe", "fuite_potentielle", "purge_overlapping_periods", "purged_temporal_split",
]
