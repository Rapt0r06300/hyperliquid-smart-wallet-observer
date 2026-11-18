"""LE CLIQUET LABO -> MOTEUR : le champion deployable, ecrit, relu, et jamais applique tout seul.

POURQUOI CE MODULE EXISTE A PART. Ces trois fonctions vivaient dans `copy_vault_local_lab.py`, que
la protection du champion par tranche a reporte au-dessus de son plafond de lignes. Elles forment
un ensemble : ce qui ECRIT le champion, ce qui le RELIT, et le raccourci qui en tire un seuil.

CE QU'IL FAUT SAVOIR AVANT D'Y TOUCHER :

* `runtime/champion_deploye.json` est un chemin UNIQUE. Une campagne qui ne couvre qu'une TRANCHE
  de temps ne doit donc pas l'ecrire : dix-neuf tranches s'y ecraseraient l'une l'autre, et le
  fichier final porterait un candidat choisi sur quatre a onze heures, presente comme deployable.
  Le refus est applique chez l'appelant (`run_local_campaign`) et publie sous
  `champion_deploye_refuse` ;
* l'ecriture est ATOMIQUE et fail-soft : temporaire, `fsync`, puis `os.replace`. Elle ne leve
  jamais et n'altere ni la campagne ni ses gardiens. Un champion mal forme n'ecrit rien plutot
  qu'un fichier a moitie juste ;
* le moteur ne l'applique QUE s'il opte explicitement. Ecrire ce fichier ne deploie rien par
  soi-meme, et `respecter_opt_in` garde ce contrat du cote de la lecture.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Le fichier du cliquet, relatif a la racine du depot. Chemin UNIQUE : voir l'avertissement
#: ci-dessus sur les campagnes qui ne couvrent qu'une tranche.
CHEMIN_CHAMPION_DEPLOYE = ("runtime", "champion_deploye.json")

def _ecrire_champion_deploye(
    root: str | Path,
    best: Mapping[str, Any],
    *,
    extra: Mapping[str, Any] | None = None,
) -> Path | None:
    """Écrit (atomiquement) le champion gelé dans un fichier de déploiement stable.

    Étape 1 du cliquet labo->moteur. PUREMENT additif et fail-soft : ne lève jamais,
    n'altère ni la campagne ni ses gardiens. Le moteur ne l'applique QUE s'il opte
    explicitement (voir ``note``). ``best['candidate']`` = params que v21 interprète,
    dont ``overshoot_seuil_bps``.
    """
    try:
        if not isinstance(best, Mapping):
            return None
        params = best.get("candidate")
        if not isinstance(params, Mapping):
            return None
        root = Path(root)
        cible = root.joinpath(*CHEMIN_CHAMPION_DEPLOYE)
        cible.parent.mkdir(parents=True, exist_ok=True)
        if cible.is_symlink():
            raise OSError("CHAMPION_DEPLOYE_SYMLINKED")
        payload: dict[str, Any] = {
            "schema_version": "hypersmart.copy_vault_champion_deploy.v1",
            "ecrit_le_utc": datetime.now(UTC).isoformat(),
            "candidate_id": best.get("candidate_id"),
            "params": dict(params),
            "overshoot_seuil_bps": params.get("overshoot_seuil_bps"),
            "score_usd_per_active_day": best.get("score_usd_per_active_day"),
            "train_daily_mean_net_pnl_usd": (
                best.get("train", {}).get("daily_mean_net_pnl_usd")
                if isinstance(best.get("train"), Mapping) else None
            ),
            "trial_number": best.get("trial_number"),
            "paper_read_only": True,
            "real_execution": False,
            "applique_par_defaut": False,
            "note": (
                "Champion gelé par le labo. Le moteur ne l'applique QUE si "
                "HL_APPLY_CHAMPION=1. Aucun ordre, aucune clé, aucune signature."
            ),
        }
        if extra:
            for cle, valeur in extra.items():
                payload.setdefault(str(cle), valeur)
        tmp = cible.with_suffix(cible.suffix + ".tmp")
        texte = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(texte)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, cible)
        return cible
    except Exception:  # fail-soft : jamais bloquer la campagne pour un fichier annexe
        return None

def charger_champion_deploye(
    root: str | Path,
    *,
    respecter_opt_in: bool = True,
) -> dict[str, Any] | None:
    """Lit le champion déployé par le labo (côté moteur). Read-only, fail-soft.

    Par défaut, ne renvoie quelque chose QUE si le moteur a opté explicitement via
    ``HL_APPLY_CHAMPION=1`` (garde-fou : rien n'est appliqué sans décision humaine).
    Renvoie le payload (dont ``overshoot_seuil_bps``) ou ``None``.
    """
    try:
        if respecter_opt_in and os.environ.get("HL_APPLY_CHAMPION") != "1":
            return None
        cible = Path(root).joinpath(*CHEMIN_CHAMPION_DEPLOYE)
        if cible.is_symlink() or not cible.is_file():
            return None
        payload = json.loads(cible.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        if payload.get("schema_version") != "hypersmart.copy_vault_champion_deploy.v1":
            return None
        return payload
    except Exception:
        return None

def seuil_overshoot_champion(
    root: str | Path,
    *,
    respecter_opt_in: bool = True,
) -> float | None:
    """Raccourci : le seuil overshoot du champion déployé, ou ``None`` (porte off)."""
    payload = charger_champion_deploye(root, respecter_opt_in=respecter_opt_in)
    if not payload:
        return None
    seuil = payload.get("overshoot_seuil_bps")
    try:
        seuil = float(seuil) if seuil is not None else None
    except (TypeError, ValueError):
        return None
    # Valeur « off » conventionnelle du labo (très grande) -> porte désactivée.
    if seuil is None or seuil >= 1_000_000.0:
        return None
    return seuil


__all__ = ["CHEMIN_CHAMPION_DEPLOYE", "_ecrire_champion_deploye", "charger_champion_deploye", "seuil_overshoot_champion"]
