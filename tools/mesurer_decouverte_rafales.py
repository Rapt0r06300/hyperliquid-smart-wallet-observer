#!/usr/bin/env python3
"""Mesure la DÉCOUVERTE des rafales d'un leader par la capture en direct (lecture seule).

POURQUOI. Le 17/11/2026, la capture en direct (`vault_fills_live.jsonl`) captait ~100 % des fills
d'un leader abonné, mais elle mettait 38 à 114 minutes à s'apercevoir qu'un leader s'était remis à
trader : 30 reprises d'activité sur 49 n'ont jamais été vues, 61,0 % des fills de ces rafales
manquaient. La correction (`hl_observer.collection.slots_userfills`) fait suivre l'attribution des
emplacements par l'alerte du poll REST. CET OUTIL EST L'INSTRUMENT DE LA COMPARAISON : le relancer
après quelques jours de collecte dit si la perte a réellement baissé.

MÉTHODE. La vérité est l'historique complet des fills (`vault_fills.jsonl`, rattrapage REST, par
heure d'échange). Une RAFALE commence au premier fill qui suit au moins `--silence-min` minutes de
silence du leader. Pour chaque rafale on compte les fills antérieurs au premier fill vu en direct.
Le contrefactuel « alerte du poll » suppose une promotion à la page suivante (150 s) et un
emplacement disponible : c'est une BORNE, pas une prévision.

Rien n'est écrit dans les rubans. Aucun réseau.
"""
from __future__ import annotations

import argparse
import bisect
import json
import sys
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
SCHEMA = "hypersmart.decouverte_rafales.v1"
RUBAN_DIRECT = Path("runtime") / "data" / "vault_fills_live.jsonl"
RUBAN_COMPLET = Path("runtime") / "data" / "vault_fills.jsonl"
RUBAN_POLL = Path("runtime") / "data" / "vault_fills_poll.jsonl"
RAPPORT = Path("runtime") / "logs" / "mesures" / "decouverte_rafales.json"
SILENCE_MS = 45 * 60_000
PAGE_MS = 150_000


def decouper_en_rafales(instants: Sequence[int], *, silence_ms: int = SILENCE_MS,
                        debut_ms: int = 0) -> list[list[int]]:
    """Découpe des instants TRIÉS en rafales séparées par au moins ``silence_ms`` de silence.

    Une rafale dont le premier fill précède ``debut_ms`` est écartée : on ne sait pas si la capture
    en direct existait déjà.
    """
    rafales: list[list[int]] = []
    courante: list[int] = []
    for instant in instants:
        if courante and instant - courante[-1] >= silence_ms:
            rafales.append(courante)
            courante = []
        courante.append(instant)
    if courante:
        rafales.append(courante)
    return [r for r in rafales if r[0] >= debut_ms]


def _premier_dans(instants: Sequence[int], debut: int, fin: int) -> int | None:
    rang = bisect.bisect_left(instants, debut)
    return instants[rang] if rang < len(instants) and instants[rang] <= fin else None


def mesurer(complet: Mapping[str, Sequence[int]], direct: Mapping[str, Sequence[int]],
            alerte: Mapping[str, Sequence[int]] | None = None, *, silence_ms: int = SILENCE_MS,
            page_ms: int = PAGE_MS, debut_ms: int = 0) -> dict[str, Any]:
    """Bilan de découverte. ``complet`` et ``direct`` : heures d'ÉCHANGE triées par leader ;
    ``alerte`` : heures de RÉCEPTION des lignes du poll (l'instant où l'on a su)."""
    alerte = alerte or {}
    lignes: list[dict[str, Any]] = []
    total = manques = manques_avec = jamais = sans_alerte = 0
    for vault, instants in complet.items():
        vus = direct.get(vault) or []
        avertis = alerte.get(vault) or []
        for rafale in decouper_en_rafales(instants, silence_ms=silence_ms, debut_ms=debut_ms):
            debut, fin = rafale[0], rafale[-1]
            vu = _premier_dans(vus, debut, fin)
            averti = _premier_dans(avertis, debut, fin)
            perdus = sum(1 for t in rafale if vu is None or t < vu)
            promu = averti + page_ms if averti is not None else None
            abonne = min((x for x in (vu, promu) if x is not None), default=None)
            perdus_avec = sum(1 for t in rafale if abonne is None or t < abonne)
            total += len(rafale)
            manques += perdus
            manques_avec += perdus_avec
            jamais += vu is None
            sans_alerte += averti is None
            lignes.append({
                "vault": vault, "debut_ms": debut, "fills": len(rafale),
                "decouverte_ms": None if vu is None else vu - debut,
                "alerte_ms": None if averti is None else averti - debut,
                "fills_manques": perdus, "fills_manques_avec_alerte": perdus_avec,
            })
    lignes.sort(key=lambda l: -l["fills"])
    return {
        "schema_version": SCHEMA,
        "leaders": len(complet),
        "rafales": len(lignes),
        "fills": total,
        "fills_manques": manques,
        "part_manquee": (manques / total) if total else None,
        "fills_manques_avec_alerte": manques_avec,
        "part_manquee_avec_alerte": (manques_avec / total) if total else None,
        "rafales_jamais_vues": jamais,
        "rafales_sans_alerte": sans_alerte,
        "silence_ms": silence_ms, "page_ms": page_ms,
        "plus_grosses_rafales": lignes[:20],
        "paper_read_only": True, "real_execution": False,
    }


def _lire(chemin: Path, cle_instant: str, *, garder=None) -> Iterable[tuple[str, int, Any]]:
    try:
        flux = chemin.open("rb")
    except OSError:
        return
    with flux:
        for brut in flux:
            try:
                ligne = json.loads(brut)
            except ValueError:
                continue
            instant = ligne.get(cle_instant)
            vault = str(ligne.get("vault") or "").lower()
            if type(instant) is not int or not vault or (garder is not None and not garder(ligne)):
                continue
            yield vault, instant, ligne.get("tid")


def charger(root: Path) -> tuple[dict[str, list[int]], dict[str, list[int]], dict[str, list[int]], int]:
    """``(complet, direct, alerte, debut_du_direct)`` depuis les rubans de ``root``."""
    direct: dict[str, list[int]] = defaultdict(list)
    for vault, instant, _ in _lire(root / RUBAN_DIRECT, "ts_ms",
                                   garder=lambda l: l.get("source") == "LIVE_WS"
                                   and l.get("isSnapshot") is False):
        direct[vault].append(instant)
    debut = min((min(v) for v in direct.values() if v), default=0)
    complet: dict[str, list[int]] = defaultdict(list)
    vus: set[Any] = set()
    for vault, instant, tid in _lire(root / RUBAN_COMPLET, "ts_ms"):
        if vault in direct and instant >= debut - SILENCE_MS and tid not in vus:
            vus.add(tid)
            complet[vault].append(instant)
    alerte: dict[str, list[int]] = defaultdict(list)
    for vault, instant, _ in _lire(root / RUBAN_POLL, "received_at_ms"):
        if vault in complet:
            alerte[vault].append(instant)
    for groupe in (direct, complet, alerte):
        for instants in groupe.values():
            instants.sort()
    return dict(complet), dict(direct), dict(alerte), debut


def main(argv: Sequence[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    analyseur.add_argument("--root", default=str(RACINE))
    analyseur.add_argument("--silence-min", type=float, default=SILENCE_MS / 60_000)
    analyseur.add_argument("--sans-rapport", action="store_true", help="n'écrit pas le rapport JSON")
    args = analyseur.parse_args(argv)
    root = Path(args.root)
    complet, direct, alerte, debut = charger(root)
    if not complet:
        print("[decouverte] aucun leader commun entre l'historique complet et le direct : rien à mesurer")
        return 2
    bilan = mesurer(complet, direct, alerte, silence_ms=int(args.silence_min * 60_000), debut_ms=debut)
    bilan["genere_ms"] = int(time.time() * 1000)
    bilan["debut_du_direct_ms"] = debut

    def part(x: float | None) -> str:
        return "n/d" if x is None else f"{100 * x:.1f} %"

    print(f"[decouverte] {bilan['leaders']} leaders, {bilan['rafales']} rafales, {bilan['fills']} fills")
    print(f"[decouverte] manqués par le direct            : {bilan['fills_manques']} = {part(bilan['part_manquee'])}")
    print(f"[decouverte] manqués avec l'alerte du poll    : {bilan['fills_manques_avec_alerte']} = "
          f"{part(bilan['part_manquee_avec_alerte'])}  (borne : page suivante, emplacement libre)")
    print(f"[decouverte] rafales jamais vues en direct    : {bilan['rafales_jamais_vues']} / {bilan['rafales']}")
    if not args.sans_rapport:
        chemin = root / RAPPORT
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with chemin.open("w", encoding="utf-8", newline="") as flux:
            flux.write(json.dumps(bilan, ensure_ascii=False, indent=1) + "\n")
        print(f"[decouverte] rapport : {chemin.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
