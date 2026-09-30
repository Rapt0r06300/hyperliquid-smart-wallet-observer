"""[LANCEUR item 11] Stockage durable BORNÉ — remplace le stockage brut illimité.

Le stack durable existe déjà (collection/tick_dataset : JSONL fsync + shards gzip immuables + manifeste
+ raw_sha256 ; collection/collecte_fiable : append_jsonl fsync, ecrire_atomique). Il manquait la BORNE :
quota disque, ALARME AVANT saturation, et une rétention EXPLICITE — jamais de suppression silencieuse.

Ce module apporte :
  · mesurer_usage      — octets réellement occupés par le stockage
  · evaluer_quota      — état OK / ALERTE_PRE_SATURATION / SATURATION (+ alarme opérateur)
  · GardeStockage      — backpressure : refuse une écriture qui FERAIT dépasser le quota
  · plan_retention     — liste les shards les PLUS VIEUX à archiver pour repasser sous la ligne basse
  · executer_retention — ARCHIVE (déplace) les shards + les inscrit au manifeste avec checksum

RÈGLE DURE : rien n'est supprimé en silence. La rétention DÉPLACE des shards immuables vers une archive
et enregistre chaque mouvement (chemin, octets, sha256, motif). Le pruning éventuel reste une décision
explicite, tracée. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

ETAT_OK = "OK"
ETAT_ALERTE = "ALERTE_PRE_SATURATION"
ETAT_SATURATION = "SATURATION"

SEUIL_ALERTE_DEFAUT = 0.80          # 80 % du quota -> on ALERTE (jamais en silence)
LIGNE_BASSE_DEFAUT = 0.70          # cible après rétention
QUOTA_DEFAUT_OCTETS = 20 * 1024**3  # 20 Go par défaut (bornage durable)


@dataclass(frozen=True)
class Shard:
    chemin: str
    octets: int
    ts_ms: int                      # âge (mtime) — la rétention vise les PLUS VIEUX
    sha256: str | None = None


@dataclass(frozen=True)
class UsageStockage:
    octets: int
    n_fichiers: int


@dataclass(frozen=True)
class VerdictQuota:
    etat: str
    usage_octets: int
    quota_octets: int
    pct: float
    alerte: bool
    raison: str

    def alerte_operateur(self) -> dict[str, str] | None:
        if self.etat == ETAT_SATURATION:
            return {"severity": "CRITICAL", "code": "STORAGE_SATURATION", "msg": self.raison}
        if self.etat == ETAT_ALERTE:
            return {"severity": "WARN", "code": "STORAGE_PRESATURATION", "msg": self.raison}
        return None


@dataclass(frozen=True)
class PlanRetention:
    a_archiver: tuple[Shard, ...] = field(default_factory=tuple)
    octets_liberes: int = 0
    reste_octets: int = 0
    suffisant: bool = True
    manifeste: tuple[dict[str, Any], ...] = field(default_factory=tuple)


def _lister_reel(chemin: Path) -> Iterable[tuple[str, int, int]]:
    for racine, _dirs, fichiers in os.walk(chemin):
        for f in fichiers:
            p = Path(racine) / f
            try:
                st = p.stat()
                yield (str(p), int(st.st_size), int(st.st_mtime * 1000))
            except OSError:
                continue


def mesurer_usage(chemins: Sequence[str | Path], *,
                  lister: Callable[[Path], Iterable[tuple[str, int, int]]] | None = None) -> UsageStockage:
    """Octets réellement occupés par les répertoires de stockage. `lister` injectable → testable."""
    walk = lister if lister is not None else _lister_reel
    total = 0
    n = 0
    for c in chemins:
        for _p, octets, _ts in walk(Path(c)):
            total += int(octets)
            n += 1
    return UsageStockage(total, n)


def evaluer_quota(usage_octets: int, quota_octets: int, *,
                  seuil_alerte: float = SEUIL_ALERTE_DEFAUT) -> VerdictQuota:
    q = max(1, int(quota_octets))
    pct = float(usage_octets) / float(q)
    if pct >= 1.0:
        etat, alerte = ETAT_SATURATION, True
    elif pct >= seuil_alerte:
        etat, alerte = ETAT_ALERTE, True
    else:
        etat, alerte = ETAT_OK, False
    raison = "stockage %.1f%% du quota (%d / %d octets)" % (pct * 100.0, usage_octets, q)
    return VerdictQuota(etat, int(usage_octets), q, pct, alerte, raison)


class GardeStockage:
    """Backpressure : refuse toute écriture qui FERAIT dépasser le quota (on ne blesse jamais la borne).
    L'appelant met à jour l'usage observé et demande l'autorisation avant d'écrire un lot."""

    def __init__(self, quota_octets: int = QUOTA_DEFAUT_OCTETS, *, seuil_alerte: float = SEUIL_ALERTE_DEFAUT):
        self.quota_octets = max(1, int(quota_octets))
        self.seuil_alerte = seuil_alerte
        self._usage = 0

    def mettre_a_jour(self, usage_octets: int) -> None:
        self._usage = max(0, int(usage_octets))

    def verdict(self) -> VerdictQuota:
        return evaluer_quota(self._usage, self.quota_octets, seuil_alerte=self.seuil_alerte)

    def autoriser_ecriture(self, taille_prevue: int) -> tuple[bool, VerdictQuota]:
        """Autorise si usage + taille_prevue <= quota. Sinon REFUSE (backpressure) : au lieu de dépasser,
        on force l'appelant à déclencher une rétention explicite d'abord."""
        futur = self._usage + max(0, int(taille_prevue))
        autorise = futur <= self.quota_octets
        v = evaluer_quota(self._usage, self.quota_octets, seuil_alerte=self.seuil_alerte)
        return autorise, v


def plan_retention(shards: Sequence[Shard], *, quota_octets: int, usage_octets: int,
                   ligne_basse: float = LIGNE_BASSE_DEFAUT, motif: str = "quota") -> PlanRetention:
    """Sélectionne les shards les PLUS VIEUX à archiver pour repasser sous `ligne_basse × quota`. Ne
    supprime rien : produit une liste + un manifeste explicite (chemin, octets, sha256, motif)."""
    cible = int(quota_octets * ligne_basse)
    if usage_octets <= cible:
        return PlanRetention(reste_octets=usage_octets, suffisant=True)
    par_age = sorted(shards, key=lambda s: s.ts_ms)          # plus vieux d'abord
    a_archiver: list[Shard] = []
    reste = int(usage_octets)
    manifeste: list[dict[str, Any]] = []
    for s in par_age:
        if reste <= cible:
            break
        a_archiver.append(s)
        reste -= int(s.octets)
        manifeste.append({"chemin": s.chemin, "octets": int(s.octets), "sha256": s.sha256,
                          "motif": motif, "action": "ARCHIVER"})
    liberes = int(usage_octets) - reste
    return PlanRetention(tuple(a_archiver), liberes, max(0, reste), reste <= cible, tuple(manifeste))


def sha256_fichier(chemin: str | Path, *, blocs: int = 1 << 20) -> str | None:
    try:
        h = hashlib.sha256()
        with Path(chemin).open("rb") as fh:
            for morceau in iter(lambda: fh.read(blocs), b""):
                h.update(morceau)
        return h.hexdigest()
    except OSError:
        return None


def _archiver_reel(shard: Shard, dossier_archive: Path) -> str | None:
    """Déplace un shard immuable vers l'archive (jamais unlink silencieux). Rend le chemin d'archive."""
    try:
        dossier_archive.mkdir(parents=True, exist_ok=True)
        dest = dossier_archive / Path(shard.chemin).name
        os.replace(shard.chemin, dest)                       # atomique, même volume
        return str(dest)
    except OSError:
        return None


def executer_retention(plan: PlanRetention, *, dossier_archive: str | Path,
                       deplaceur: Callable[[Shard, Path], str | None] | None = None) -> dict[str, Any]:
    """Applique la rétention : ARCHIVE chaque shard (déplacement, pas suppression) et enregistre le
    mouvement. `deplaceur` injectable → testable. Rien n'est supprimé en silence."""
    move = deplaceur if deplaceur is not None else _archiver_reel
    arch = Path(dossier_archive)
    faits: list[dict[str, Any]] = []
    for s in plan.a_archiver:
        dest = move(s, arch)
        faits.append({"chemin": s.chemin, "octets": s.octets, "sha256": s.sha256,
                      "archive": dest, "ok": dest is not None, "action": "ARCHIVE"})
    return {"archives": faits, "n": len(faits), "octets_liberes": plan.octets_liberes,
            "aucune_suppression_silencieuse": True}


def format_quota(v: VerdictQuota) -> str:
    return "[stockage %s] %s" % (v.etat, v.raison)


__all__ = ["ETAT_OK", "ETAT_ALERTE", "ETAT_SATURATION", "SEUIL_ALERTE_DEFAUT", "LIGNE_BASSE_DEFAUT",
           "QUOTA_DEFAUT_OCTETS", "Shard", "UsageStockage", "VerdictQuota", "PlanRetention",
           "mesurer_usage", "evaluer_quota", "GardeStockage", "plan_retention", "sha256_fichier",
           "executer_retention", "format_quota"]
