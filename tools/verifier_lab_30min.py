"""LOT 4 — VÉRIFICATEUR 30 MIN du laboratoire (Flo 25/07). Prouve que RESEARCH_PARALLEL_V1 tourne
proprement et N'IMPACTE PAS le moteur principal. Lecture seule.

Prend un INSTANTANÉ au début et à la fin (30 min par défaut) : PID unique du labo, fraîcheur du heartbeat,
TAILLE des fichiers de données isolés (doivent grossir), et les heartbeats du MAIN (bbo/userfills) qui
doivent continuer de battre (le labo ne les gèle pas). CPU/RAM/disque si psutil dispo. Rend un verdict.

Le verdict (`comparer`) est PUR -> testable. La boucle de 30 min tourne sur Windows où le labo est lancé.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research_parallel import isolation as ISO  # noqa: E402

MAIN_HEARTBEATS = ("runtime/data/bbo_heartbeat.json", "runtime/data/userfills_heartbeat.json")


def instantane(root: Path) -> dict:
    """Photo à un instant t : identité/heartbeat labo, tailles des données isolées, mtime des heartbeats main."""
    base = ISO.lab_root(root)
    ident = {}
    try:
        ident = json.loads((base / "run_identity.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    hb_age = None
    try:
        hb_age = time.time() - (base / "heartbeat.json").stat().st_mtime
    except OSError:
        pass
    tailles = {}
    d = base / "data"
    if d.is_dir():
        for f in sorted(d.glob("*.jsonl")):
            try:
                tailles[f.name] = f.stat().st_size
            except OSError:
                pass
    main_mtimes = {}
    for rel in MAIN_HEARTBEATS:
        try:
            main_mtimes[rel] = (Path(root) / rel).stat().st_mtime
        except OSError:
            main_mtimes[rel] = None
    ress = {}
    try:
        import psutil  # noqa: F401
        pid = ident.get("pid")
        if pid:
            p = psutil.Process(pid)
            ress = {"cpu_pct": p.cpu_percent(interval=0.2), "rss_mo": round(p.memory_info().rss / 1e6, 1)}
    except Exception:  # noqa: BLE001 (psutil absent ou process fini -> ressources non mesurées, honnête)
        ress = {"note": "psutil indisponible ou process absent"}
    return {"ts": time.time(), "run_id": ident.get("run_id"), "pid": ident.get("pid"),
            "heartbeat_age_s": hb_age, "tailles": tailles, "main_mtimes": main_mtimes, "ressources": ress}


def comparer(debut: dict, fin: dict, *, heartbeat_max_s: float = 180.0) -> dict:
    """Verdict PUR entre deux instantanés. PASS ssi : PID unique et stable, heartbeat labo frais, AU MOINS
    un fichier a grossi, et les heartbeats du MAIN ont bougé (le main n'a pas été gelé par le labo)."""
    pid_stable = debut.get("pid") is not None and debut.get("pid") == fin.get("pid")
    hb_frais = (fin.get("heartbeat_age_s") is not None) and fin["heartbeat_age_s"] <= heartbeat_max_s
    a_grossi = any(fin["tailles"].get(k, 0) > debut["tailles"].get(k, -1) for k in fin.get("tailles", {})) \
        if fin.get("tailles") else False
    # le main continue de battre : au moins un heartbeat main a un mtime plus récent
    main_vivant = any(
        (fin["main_mtimes"].get(k) or 0) > (debut["main_mtimes"].get(k) or 0)
        for k in fin.get("main_mtimes", {})
    )
    pass_ = bool(pid_stable and hb_frais and a_grossi and main_vivant)
    return {"verdict": "PASS" if pass_ else "ATTENTION", "pid_unique_stable": pid_stable,
            "heartbeat_labo_frais": hb_frais, "fichiers_ont_grossi": a_grossi,
            "main_toujours_vivant": main_vivant, "run_id": fin.get("run_id"),
            "duree_s": round(fin.get("ts", 0) - debut.get("ts", 0), 1)}


def main(argv=None) -> int:  # pragma: no cover (boucle temps réel, tourne sur Windows)
    ap = argparse.ArgumentParser(description="Vérificateur 30 min du labo (lecture seule).")
    ap.add_argument("--root", default=str(RACINE))
    ap.add_argument("--minutes", type=float, default=30.0)
    a = ap.parse_args(argv)
    root = Path(a.root)
    d = instantane(root)
    print("[verif] instantané début: pid=%s hb_age=%s fichiers=%d" % (
        d["pid"], d["heartbeat_age_s"], len(d["tailles"])), flush=True)
    time.sleep(a.minutes * 60.0)
    f = instantane(root)
    v = comparer(d, f)
    (ISO.lab_root(root) / "rapports").mkdir(parents=True, exist_ok=True)
    (ISO.lab_root(root) / "rapports" / "verif_30min.json").write_text(
        json.dumps({"debut": d, "fin": f, "verdict": v}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(v, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
