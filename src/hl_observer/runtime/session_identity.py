"""#286 (P1) — LA source de vérité de la SESSION.

Le problème mesuré : les 3 processus (UI, poller, collecteur) n'avaient AUCUN identifiant
commun. Mélanger deux sessions dans un même ledger = un PnL fabriqué sans que personne ne
mente volontairement.

Ce module fournit :
  * `demarrer_session(root)`  — appelé UNE fois par lancement (par le poll loop .ps1) ;
    écrit le manifeste `runtime/data/hypersmart_session_manifest.json` (atomique).
  * `session_courante(root)`  — env `HYPERSMART_SESSION_ID` > manifeste > "" (JAMAIS inventée :
    une session inconnue vaut chaîne vide, pas un id fabriqué).
  * `verifier_coherence(root)` — LE LECTEUR (sans lecteur, un identifiant est la maladie du
    projet : une capacité sans consommateur). Il échoue si le manifeste manque, si
    l'engine status porte un autre id, ou si le ledger contient des événements ANTÉRIEURS
    au démarrage de la session (= mélange de sessions).

Read-only / paper-only. Aucun ordre, aucune clé, aucune signature.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

SESSION_ENV = "HYPERSMART_SESSION_ID"
MANIFEST_RELPATH = Path("runtime") / "data" / "hypersmart_session_manifest.json"


def _manifest_path(root: str | Path) -> Path:
    return Path(root) / MANIFEST_RELPATH


def generer_session_id(now_ms: int | None = None) -> str:
    ts = datetime.fromtimestamp((now_ms or int(time.time() * 1000)) / 1000.0)
    return f"S{ts:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


def demarrer_session(root: str | Path = ".", *, session_id: str | None = None,
                     now_ms: int | None = None) -> str:
    """Écrit le manifeste de session (atomique). Le DÉMARRAGE du lanceur EST la nouvelle
    session — un self-restart du runner n'en crée pas une nouvelle (il hérite de l'env)."""
    sid = session_id or os.environ.get(SESSION_ENV, "").strip() or generer_session_id(now_ms)
    path = _manifest_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": sid,
        "started_at_ms": int(now_ms or time.time() * 1000),
        "pid": os.getpid(),
        "real_execution": False,
    }
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return sid


def lire_manifest(root: str | Path = ".") -> dict[str, Any] | None:
    try:
        raw = _manifest_path(root).read_text(encoding="utf-8-sig")
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def session_courante(root: str | Path = ".") -> str:
    """Env d'abord (posé par le lanceur pour tous ses enfants), manifeste ensuite (pour les
    processus frères comme l'UI), et sinon chaîne VIDE — on n'invente pas une identité."""
    env = os.environ.get(SESSION_ENV, "").strip()
    if env:
        return env
    manifest = lire_manifest(root)
    if manifest:
        sid = str(manifest.get("session_id") or "").strip()
        if sid:
            return sid
    return ""


def _premier_ts_ms_du_jsonl(path: Path, *, champs: tuple[str, ...] = ("ts_ms", "timestamp_ms", "time_ms", "ts")) -> int | None:
    """Le timestamp de la PREMIÈRE ligne du ledger export. Une seule ligne lue : pas de scan."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    return None
                if not isinstance(row, dict):
                    return None
                for champ in champs:
                    v = row.get(champ)
                    if isinstance(v, (int, float)) and v > 0:
                        v = float(v)
                        # Piege d'unite (#318): on ne devine JAMAIS a l'aveugle. Seule une valeur
                        # dans la plage des epoch SECONDES plausibles (1e9..1e12) est convertie;
                        # tout le reste est traite comme des millisecondes, tel quel.
                        if 1e9 < v < 1e12:
                            v *= 1000.0
                        return int(v)
                return None
    except OSError:
        return None
    return None


def verifier_coherence(root: str | Path = ".", *,
                       engine_status_path: str | Path | None = None,
                       ledger_jsonl_path: str | Path | None = None) -> tuple[bool, list[str]]:
    """LE LECTEUR. (ok, motifs). Un motif non vide = risque de PnL fabriqué par mélange."""
    root = Path(root)
    motifs: list[str] = []
    manifest = lire_manifest(root)
    if not manifest:
        return False, ["MANIFEST_SESSION_ABSENT: aucun demarrage de session enregistre"]
    sid = str(manifest.get("session_id") or "")
    started = int(manifest.get("started_at_ms") or 0)
    if not sid or started <= 0:
        return False, ["MANIFEST_SESSION_INVALIDE"]

    env = os.environ.get(SESSION_ENV, "").strip()
    if env and env != sid:
        motifs.append(f"ENV_VS_MANIFEST: env={env} manifeste={sid}")

    es_path = Path(engine_status_path) if engine_status_path else root / "runtime" / "data" / "hypersmart_engine_status.json"
    try:
        es = json.loads(es_path.read_text(encoding="utf-8-sig"))
        es_sid = str(es.get("session_id") or "").strip()
        if es_sid and es_sid != sid:
            motifs.append(f"ENGINE_STATUS_AUTRE_SESSION: {es_sid} != {sid}")
    except (OSError, ValueError):
        pass  # engine status absent/corrompu: pas un mélange, juste pas de preuve

    lp = Path(ledger_jsonl_path) if ledger_jsonl_path else root / "logs" / "logs à envoyer" / "simulation_pnl_ledger_latest.jsonl"
    if lp.exists():
        premier = _premier_ts_ms_du_jsonl(lp)
        if premier is not None and premier < started:
            motifs.append(
                f"LEDGER_MELANGE_DE_SESSIONS: premiere ligne a {premier} < demarrage {started} "
                "(le ledger contient une session precedente)"
            )
    return (len(motifs) == 0), motifs


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Identite de session HyperSmart (#286, read-only)")
    p.add_argument("--root", default=".")
    p.add_argument("--start", action="store_true", help="demarre une session et imprime son id")
    p.add_argument("--verify", action="store_true", help="verifie la coherence (code retour 1 si melange)")
    args = p.parse_args(argv)
    if args.start:
        print(demarrer_session(args.root))
        return 0
    if args.verify:
        ok, motifs = verifier_coherence(args.root)
        print("session_check=OK" if ok else "session_check=FAIL " + " | ".join(motifs))
        return 0 if ok else 1
    print(session_courante(args.root) or "(aucune session)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
