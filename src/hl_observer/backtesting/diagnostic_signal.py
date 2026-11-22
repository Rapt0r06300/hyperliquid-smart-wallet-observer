"""Couverture du signal des leaders et DIAGNOSTIC de la separation temporelle.

POURQUOI CE MODULE EXISTE (21/11/2026). `copy_vault_local_lab.py` est un gros fichier
historique, epingle a 4 971 lignes par `tests/test_invariants_architecture.py` : la regle du
depot interdit d'AGRANDIR une dette historique. En ajoutant `_diagnostic_du_split` je l'ai
pousse a 5 018 lignes et la suite complete l'a vu (3 echecs sur 20 057). La reparation
honnete n'est pas de relever le plafond, c'est d'extraire -- comme `ops/budget_cpu.py` plus
tot le meme jour.

CE QU'IL CONTIENT. Deux fonctions PURES sur les horodatages de signal, et la constante
qu'elles partagent :

* `MINIMUM_SIGNAL_UTC_DAYS` -- le nombre de journees UTC distinctes exigees pour former une
  separation TRAIN/VALIDATION/OOS. Elle vit ICI et le labo la RE-EXPORTE, et pas l'inverse :
  une constante lue par tout le monde ne doit dependre de personne, sinon l'extraction cree
  un cycle d'import entre le labo et ce module.
* `signal_coverage` -- ce que le signal couvre reellement (journees, trous, etendue).
* `diagnostic_du_split` -- POURQUOI aucune separation n'a pu etre formee.

Le second repond a une mesure precise : une conduite de 23 tranches de 4 a 26 h a rendu
23 fois `MORE_DATA` / `TEMPORAL_SPLIT_INVALID_AFTER_PURGE` avec **0 candidat essaye** en
2 h 17, alors que la seule premiere tranche portait 34 863 metaordres et 680 896 lignes de
carnet. Le verdict accusait le corpus ; la cause etait une fenetre plus etroite que l'unite
de decoupe du split. Sans motif chiffre, les deux sont indistinguables.
"""
from __future__ import annotations

from datetime import UTC, datetime

#: Journees UTC distinctes exigees pour une separation TRAIN/VALIDATION/OOS. Source unique :
#: `copy_vault_local_lab._MINIMUM_SIGNAL_UTC_DAYS` et `tools/conduire_labo_par_tranches.py`
#: la lisent d'ici (le second l'importe deja plutot que de la recopier).
MINIMUM_SIGNAL_UTC_DAYS = 6

#: Millisecondes par journee UTC. L'unite de decoupe du split, nommee une seule fois.
JOUR_MS = 86_400_000


def signal_coverage(timestamps: list[int]) -> dict[str, int | float | None]:
    """Describe actual leader-signal coverage used by the temporal split."""
    valid = sorted(
        {timestamp for timestamp in timestamps if type(timestamp) is int and timestamp > 0}
    )
    day_ms = JOUR_MS
    jours = sorted({timestamp // day_ms for timestamp in valid})
    distinct_days = len(jours)
    median_gap_s: float | None = None
    p95_gap_s: float | None = None
    gap_count_gt_60s = 0
    if len(valid) >= 2:
        gaps = [valid[i + 1] - valid[i] for i in range(len(valid) - 1)]
        gaps.sort()
        median_gap_s = round(gaps[len(gaps) // 2] / 1000.0, 3)
        p95_gap_s = round(gaps[int(len(gaps) * 0.95)] / 1000.0, 3)
        gap_count_gt_60s = sum(1 for g in gaps if g > 60_000)
    return {
        "distinct_utc_days": distinct_days,
        # La LISTE, pas seulement le nombre : une conduite par tranches doit pouvoir faire l'UNION
        # des journees de ses tranches, et deux tranches de la meme journee ne font qu'une journee.
        # Sans cette cle, `agregation_tranches.unir_les_jours` lisait zero partout et le seuil des
        # six journees etait infranchissable -- constate a la premiere conduite reelle.
        "utc_days": [
            datetime.fromtimestamp(jour * day_ms / 1000, UTC).strftime("%Y-%m-%d")
            for jour in jours
        ],
        "minimum_utc_days_required": MINIMUM_SIGNAL_UTC_DAYS,
        "signal_start_ms": valid[0] if valid else None,
        "signal_end_ms": valid[-1] if valid else None,
        "signal_span_hours": round((valid[-1] - valid[0]) / 3_600_000, 3) if valid else None,
        "signal_count": len(valid),
        "median_gap_s": median_gap_s,
        "p95_gap_s": p95_gap_s,
        "gaps_gt_60s": gap_count_gt_60s,
    }


def diagnostic_du_split(
    timestamps: list[int], *, seuil_jours: int | None = None
) -> dict[str, int | float | str]:
    """Pourquoi AUCUNE separation TRAIN/VALIDATION/OOS n'a pu etre formee.

    Sans ce diagnostic, le refus `TEMPORAL_SPLIT_INVALID_AFTER_PURGE` ressemble a un
    manque de donnees -- et `MORE_DATA` accuse alors le corpus. Or la cause la plus
    courante est tout autre : une FENETRE plus etroite que l'unite de decoupe du split
    lui-meme. Le split compte des JOURS UTC ; une tranche de quelques heures ne peut
    jamais en contenir six, quel que soit le volume lu.

    MESURE DU 21/11/2026 : une conduite de 23 tranches de 4 a 26 h a rendu 23 fois
    `MORE_DATA` et **0 candidat essaye** pour 2 h 17 de calcul, avec 34 863 metaordres et
    680 896 lignes de carnet dans la seule premiere tranche. La donnee n'y etait pour
    rien : chaque fenetre portait 1 a 2 jours UTC contre 6 requis. Un `n=0` sans motif
    cache toujours un << je n'ai pas su mesurer >>.
    """
    day_ms = JOUR_MS
    valides = sorted({int(x) for x in timestamps if type(x) is int and int(x) > 0})
    jours = {x // day_ms for x in valides}
    minimum = max(3, int(seuil_jours or MINIMUM_SIGNAL_UTC_DAYS))
    etendue_ms = (valides[-1] - valides[0]) if len(valides) >= 2 else 0
    # Combien de jours UTC cette fenetre peut porter AU MIEUX : deux bornes a 4 h
    # d'intervalle peuvent chevaucher deux dates, jamais six.
    plafond_jours = (etendue_ms // day_ms) + 1 if valides else 0
    if not valides:
        motif = "AUCUN_HORODATAGE_LISIBLE"
    elif plafond_jours < minimum:
        motif = "FENETRE_PLUS_ETROITE_QUE_L_UNITE_DE_DECOUPE"
    elif len(jours) < minimum:
        motif = "JOURS_UTC_INSUFFISANTS_DANS_LA_FENETRE"
    else:
        motif = "SPLIT_VIDE_APRES_PURGE"
    return {
        "jours_distincts": len(jours),
        "jours_requis": minimum,
        "jours_possibles_dans_la_fenetre": int(plafond_jours),
        "etendue_h": round(etendue_ms / 3_600_000.0, 2),
        "unite_du_split": "UTC_DAY",
        "motif": motif,
    }


def bounds(
    timestamps: list[int], *, seuil_jours: int | None = None, purge_ms: int
) -> dict[str, int | bool | str] | None:
    """Split by UTC day and purge the longest searched holding horizon.

    `purge_ms` ARRIVE EN PARAMETRE depuis le 22/11/2026 : il se calculait sur les domaines de
    recherche du labo (`_PARAMETER_DOMAINS`, `cv.COPY_DELAY_MS`, `cv.MAX_TARGET_LAG_MS`), ce
    qui attachait cette fonction au gros module. Le rendre explicite la libere et permet de la
    tester sans le labo -- la purge reste calculee par l appelant, qui seul connait ses
    horizons."""
    day_ms = JOUR_MS
    # The search includes holding horizons up to four hours. Purge at least
    # the maximum candidate horizon so replayed positions cannot cross a split.
    purge_ms = int(purge_ms)
    days = sorted({int(timestamp) // day_ms for timestamp in timestamps if int(timestamp) > 0})
    # Seuil de L'APPELANT, minimum ABSOLU 3 : TRAIN + VALIDATION + OOS = 2 journees impossibles.
    minimum = max(3, int(seuil_jours or MINIMUM_SIGNAL_UTC_DAYS))
    if len(days) < minimum:
        return None
    train_cut = max(2, int(len(days) * 0.60))
    validation_cut = max(train_cut + 1, int(len(days) * 0.80))
    if validation_cut >= len(days):
        return None
    validation_boundary = days[train_cut] * day_ms
    oos_boundary = days[validation_cut] * day_ms
    result: dict[str, int | bool | str] = {
        "train_start_ms": days[0] * day_ms,
        "train_end_ms": validation_boundary - purge_ms - 1,
        "validation_start_ms": validation_boundary + purge_ms,
        "validation_end_ms": oos_boundary - purge_ms - 1,
        "oos_start_ms": oos_boundary + purge_ms,
        "oos_end_ms": max(int(timestamp) for timestamp in timestamps),
        "purge_ms": purge_ms,
        "split_unit": "UTC_DAY",
        "validation_empty_after_purge": False,
    }
    if not (
        int(result["train_start_ms"]) < int(result["train_end_ms"])
        < int(result["validation_start_ms"]) < int(result["validation_end_ms"])
        < int(result["oos_start_ms"]) <= int(result["oos_end_ms"])
    ):
        return None
    return result
