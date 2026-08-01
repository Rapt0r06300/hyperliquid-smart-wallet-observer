"""[LAB α item 11/5] INGESTION EN STREAMING À MÉMOIRE BORNÉE — supprime le plafond arbitraire de 200 000
événements SANS risque d'OOM.

Au lieu de charger tous les bundles/événements en RAM puis de couper à 200k, on lit les fichiers LIGNE
PAR LIGNE, on convertit chaque bundle en événements et on les DÉVERSE (spill) au fil de l'eau dans un
shard JSONL sur DISQUE. La RAM ne tient jamais plus d'un bundle à la fois. Un CHECKPOINT permet la
REPRISE (un shard déjà complet n'est pas recalculé). Le replay charge ensuite une FENÊTRE bornée du shard
(budget mémoire EXPLICITE, jamais un nombre magique).

`max_events <= 0` = pas de plafond arbitraire (lit tout, mémoire bornée par le streaming).
Réutilise les briques canoniques (lab_inventaire.lire_lignes/_row_to_bundle, feed_adapter). 0 réseau.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Iterator

from hl_observer.mega_cablage.feed_adapter import evenements_depuis_bundles
from hl_observer.ops.lab_inventaire import lire_lignes, _row_to_bundle, LabFormatBloque


def flux_evenements_stream(fichiers: Iterable[str | Path], *, max_events: int = 0) -> Iterator[dict[str, Any]]:
    """Générateur BORNÉ : pour chaque fichier, lit ligne par ligne, convertit CHAQUE bundle en événements
    et les yield un par un. Ne matérialise JAMAIS un dataset entier. `max_events<=0` = illimité (le
    streaming garde la mémoire bornée). Un fichier au format bloqué est sauté (compté par l'appelant)."""
    n = 0
    for f in fichiers:
        try:
            lignes = lire_lignes(f)
        except (OSError, LabFormatBloque):
            continue
        for row in lignes:
            try:
                bundle = _row_to_bundle(row)
                evs = evenements_depuis_bundles([bundle])
            except Exception:  # noqa: BLE001 — ligne défaillante = sautée, jamais fabriquée
                continue
            for ev in evs:
                yield ev
                n += 1
                if max_events > 0 and n >= max_events:
                    return


def materialiser_shard(fichiers: Iterable[str | Path], shard_path: str | Path, *, max_events: int = 0,
                       checkpoint_path: str | Path | None = None) -> dict[str, Any]:
    """Déverse le flux d'événements dans un shard JSONL sur DISQUE (un événement à la fois → RAM bornée).
    Écrit un checkpoint {n, complet}. REPRISE : si le shard existe et le checkpoint dit `complet`, on ne
    recalcule pas. Rend {n, shard, repris}."""
    shard_path = Path(shard_path)
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    cp = Path(checkpoint_path) if checkpoint_path else None
    if cp and cp.is_file() and shard_path.is_file():
        try:
            etat = json.loads(cp.read_text(encoding="utf-8"))
            if etat.get("complet"):
                return {"n": int(etat.get("n") or 0), "shard": str(shard_path), "repris": True}
        except (OSError, ValueError):
            pass
    n = 0
    tmp = shard_path.with_name(".%s.%d.tmp" % (shard_path.name, os.getpid()))
    with tmp.open("w", encoding="utf-8") as fh:
        for ev in flux_evenements_stream(fichiers, max_events=max_events):
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
            n += 1
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, shard_path)
    if cp:
        cp.write_text(json.dumps({"n": n, "complet": True}), encoding="utf-8")
    return {"n": n, "shard": str(shard_path), "repris": False}


def flux_depuis_shard(shard_path: str | Path) -> Iterator[dict[str, Any]]:
    """Relit le shard en streaming (une ligne à la fois → RAM bornée)."""
    p = Path(shard_path)
    if not p.is_file():
        return
    with p.open("r", encoding="utf-8") as fh:
        for ligne in fh:
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                yield json.loads(ligne)
            except ValueError:
                continue


def compter_shard(shard_path: str | Path) -> int:
    return sum(1 for _ in flux_depuis_shard(shard_path))


def charger_borne(shard_path: str | Path, *, max_ram: int = 0) -> list[dict[str, Any]]:
    """Charge une FENÊTRE bornée du shard (budget mémoire EXPLICITE). `max_ram<=0` = tout le shard. Le
    replay in-memory travaille sur cette fenêtre — jamais un plafond arbitraire codé en dur."""
    out: list[dict[str, Any]] = []
    for i, ev in enumerate(flux_depuis_shard(shard_path)):
        if max_ram > 0 and i >= max_ram:
            break
        out.append(ev)
    return out


__all__ = ["flux_evenements_stream", "materialiser_shard", "flux_depuis_shard", "compter_shard",
           "charger_borne"]
