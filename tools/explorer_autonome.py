#!/usr/bin/env python3
"""Explorer AUTONOME — tourne seul, se répare seul, décide seul. Idées #1-10, #30, #84.

Boucle sans supervision : à chaque cycle il
1. lance les collecteurs explorer (activité de TOUS les users) + trades marché (prix/taille) ;
2. décode les ordres (indice d'actif -> coin via meta publique) ;
3. **auto-découvre** les leaders actifs (classement d'activité) -> `config/copy_vault_leaders_candidats.json` ;
4. **estime** les fills exécutés des leaders connus (corrélation ordres<->trades) -> tape
   `runtime/data/explorer_inferred_fills.jsonl` (étiquetée EXPLORER_INFERRED, **jamais certifiée SAFE**) ;
5. s'auto-répare (toute erreur -> log + backoff), s'adapte, et recommence — indéfiniment.

PAPER / lecture seule : code Python maison, aucun binaire tiers, aucune clé, aucun ordre.
Ctrl+C pour arrêter proprement.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection.explorer_intelligence import (  # noqa: E402
    inferer_fills, normaliser_ordre, rang_activite)

TAPE_EXPLORER = Path("runtime") / "data" / "explorer_tx_tape.jsonl"
TAPE_TRADES = Path("runtime") / "data" / "copy_vault_trades_lane.jsonl"
TAPE_INFERRED = Path("runtime") / "data" / "explorer_inferred_fills.jsonl"
CANDIDATS = Path("config") / "copy_vault_leaders_candidats.json"
CLASSEMENT = Path("config") / "leaders_actifs_classement.json"
LEADERS = Path("config") / "copy_vault_leaders.json"


def charger_univers(timeout: float = 6.0) -> list[str]:
    """Univers des coins (meta publique) pour décoder l'indice d'actif des ordres. Fail-soft."""
    try:
        req = urllib.request.Request("https://api.hyperliquid.xyz/info",
                                     data=json.dumps({"type": "meta"}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (API publique connue)
            meta = json.loads(r.read().decode())
        return [str(a.get("name")) for a in meta.get("universe", []) if a.get("name")]
    except Exception as exc:  # noqa: BLE001
        print(f"[auto] meta indisponible ({type(exc).__name__}) — décodage d'indice limité.", flush=True)
        return []


def _charger_leaders(root: Path) -> set[str]:
    try:
        data = json.loads((root / LEADERS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    v = data.get("vaults") if isinstance(data, dict) else data
    return {str(x).strip().lower() for x in (v or []) if str(x).strip().lower().startswith("0x")}


def _lire_depuis(path: Path, offset: int):
    """Rend (nouvelles_lignes_dict, nouvel_offset). Gère la rotation (fichier réécrit)."""
    rows: list[dict] = []
    try:
        taille = path.stat().st_size
    except OSError:
        return rows, offset
    if taille < offset:
        offset = 0
    if taille <= offset:
        return rows, offset
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(offset)
            for ligne in fh:
                ligne = ligne.strip()
                if ligne:
                    try:
                        obj = json.loads(ligne)
                        if isinstance(obj, dict):
                            rows.append(obj)
                    except (ValueError, TypeError):
                        pass
            offset = fh.tell()
    except OSError:
        pass
    return rows, offset


def _lancer_collecteurs(root: Path, duree: int):
    env = {**__import__("os").environ, "PYTHONPATH": str(root / "src")}
    procs = []
    for script, extra in ((("tools/collecter_explorer_lane.py"), ["--toutes-actions"]),
                          (("tools/collecter_market_lane.py"), [])):
        try:
            procs.append(subprocess.Popen(
                [sys.executable, "-B", str(root / script), "--duree-s", str(duree), *extra],
                cwd=str(root), env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        except OSError as exc:
            print(f"[auto] lancement {script} échoué ({exc}).", flush=True)
    return procs


def _ecrire_jsonl(path: Path, rows: list[dict]):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def cycle(root: Path, duree: int, univers: list[str], etat: dict) -> dict:
    leaders = _charger_leaders(root)
    procs = _lancer_collecteurs(root, duree)
    t_fin = time.monotonic() + duree + 45
    for p in procs:
        try:
            p.wait(timeout=max(1, t_fin - time.monotonic()))
        except subprocess.TimeoutExpired:
            p.kill()

    rows_exp, etat["off_exp"] = _lire_depuis(root / TAPE_EXPLORER, etat.get("off_exp", 0))
    rows_tr, etat["off_tr"] = _lire_depuis(root / TAPE_TRADES, etat.get("off_tr", 0))
    now_ms = int(time.time() * 1000)

    # 1) auto-découverte de leaders actifs (hors leaders déjà suivis)
    classement = rang_activite(rows_exp, now_ms=now_ms, exclure=leaders)
    candidats = [u for u, _ in classement[:50]]
    if candidats:
        (root / CANDIDATS).parent.mkdir(parents=True, exist_ok=True)
        (root / CANDIDATS).write_text(json.dumps(
            {"genere_le_ms": now_ms, "candidats": candidats,
             "scores": {u: round(s, 3) for u, s in classement[:50]}},
            ensure_ascii=False, indent=2), encoding="utf-8")

    # 1bis) classement d'activité COMPLET (y compris leaders suivis) -> priorisation du suivi.
    #       Permet de suivre en priorité les traders RÉELLEMENT actifs (budget constant).
    complet = rang_activite(rows_exp, now_ms=now_ms)
    if complet:
        (root / CLASSEMENT).parent.mkdir(parents=True, exist_ok=True)
        (root / CLASSEMENT).write_text(json.dumps(
            {"genere_le_ms": now_ms, "n": len(complet),
             "actifs": [{"vault": u, "score": round(s, 3)} for u, s in complet[:200]]},
            ensure_ascii=False, indent=2), encoding="utf-8")

    # 2) ordres (intention) des leaders connus -> estimation de fills via trades
    ordres = []
    for row in rows_exp:
        u = str(row.get("user") or "").strip().lower()
        if u not in leaders:
            continue
        t = row.get("time") or row.get("ts_ms")
        for o in row.get("orders") or []:
            if isinstance(o, dict) and isinstance(t, int):
                norm = normaliser_ordre(o, univers, user=u, t_ms=t)
                if norm:
                    ordres.append(norm)
    inferes = inferer_fills(ordres, rows_tr) if ordres else []
    _ecrire_jsonl(root / TAPE_INFERRED, inferes)

    return {"explorer": len(rows_exp), "trades": len(rows_tr), "candidats": len(candidats),
            "ordres_leaders": len(ordres), "fills_inferes": len(inferes)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Explorer autonome (auto-découverte + inférence, lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--duree-cycle-s", type=int, default=600)
    p.add_argument("--max-cycles", type=int, default=0, help="0 = infini")
    args = p.parse_args(argv)
    root = Path(args.root)
    pid_file = root / "runtime" / "data" / "explorer_autonome.pid"
    try:
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    print("[auto] Explorer autonome démarré. Ctrl+C pour arrêter.", flush=True)
    univers = charger_univers()
    print(f"[auto] univers : {len(univers)} coins.", flush=True)
    etat: dict = {}
    n = 0
    echecs = 0
    try:
        while args.max_cycles == 0 or n < args.max_cycles:
            n += 1
            t0 = time.time()
            try:
                stats = cycle(root, args.duree_cycle_s, univers, etat)
                echecs = 0
                print(f"[auto] cycle {n} ({time.time()-t0:.0f}s) : "
                      f"{stats['explorer']} évts explorer, {stats['trades']} trades, "
                      f"{stats['candidats']} candidats, {stats['fills_inferes']} fills estimés.", flush=True)
                if n % 6 == 0:   # rafraîchit l'univers périodiquement (nouveaux coins listés)
                    univers = charger_univers() or univers
            except Exception as exc:  # noqa: BLE001  — auto-réparation : on ne meurt jamais
                echecs += 1
                attente = min(120, 5 * echecs)
                print(f"[auto] cycle {n} erreur ({type(exc).__name__}: {exc}) — "
                      f"reprise dans {attente}s.", flush=True)
                time.sleep(attente)
    except KeyboardInterrupt:
        print("\n[auto] arrêt demandé. À bientôt.", flush=True)
    finally:
        try:
            pid_file.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
