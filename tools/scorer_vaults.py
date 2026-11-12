"""SCORER LES VAULTS (rectif Flo 23/07) — écrit vaults_scores.json depuis l'historique de snapshots.

On ne sélectionne PLUS sur l'APR : ce collecteur applique le score 8-facteurs (vault_scoring) à chaque
vault réellement snapshoté, et publie le classement + la liste RETENUE. Le signal copy_vault ne copie
QUE des vaults retenus. `coins_executables` = coins vus dans le carnet (L2 capturé) ∪ coins BBO : la
copyabilité mesure la part d'expo qu'on peut RÉELLEMENT pricer/exécuter.

READ-ONLY : lecture de snapshots publics, écriture d'un fichier de scores. Aucune exécution.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.experimental import vault_scoring as VS  # noqa: E402

SNAP = Path("runtime") / "data" / "vault_snapshots.jsonl"
SUIVIS = Path("runtime") / "data" / "vaults_suivis.json"
CARNET = Path("runtime") / "data" / "carnet_venues.jsonl"
SORTIE = Path("runtime") / "data" / "vaults_scores.json"
COINS_BBO = ("BTC", "ETH", "SOL", "INJ", "DASH", "AVAX", "LINK", "NEO")
#: Le lanceur certifie puis ARCHIVE les rubans à chaque démarrage (``runtime/archive/session_<date>_<heure>/``,
#: ``tools/archiver_tapes.py``) : ``runtime/data`` repart de zéro. Sans relire ces sessions, le score ne
#: voyait que la session en cours — zéro vault au démarrage, donc aucun vault retenu et rien à rattraper
#: pendant 4 heures (mesuré le 2026-11-11). L'historique d'un vault est SA SÉRIE, pas la dernière session.
ARCHIVE = Path("runtime") / "archive"
HISTORIQUE_J = 30.0


def _rubans(root: Path, nom: str, *, depuis_j: float = HISTORIQUE_J, now: float | None = None) -> list[Path]:
    """Le ruban ``nom`` des sessions archivées des ``depuis_j`` derniers jours (du plus ancien au plus
    récent), puis celui de la session en cours. Un dossier au nom illisible est ignoré."""
    limite = datetime.datetime.fromtimestamp(now if now is not None else time.time()) - datetime.timedelta(
        days=float(depuis_j))
    sessions: list[tuple[datetime.datetime, Path]] = []
    try:
        dossiers = [p for p in (root / ARCHIVE).iterdir() if p.is_dir() and p.name.startswith("session_")]
    except OSError:
        dossiers = []
    for dossier in dossiers:
        try:
            quand = datetime.datetime.strptime(dossier.name[len("session_"):], "%Y%m%d_%H%M%S")
        except ValueError:
            continue
        if quand >= limite and (dossier / nom).is_file():
            sessions.append((quand, dossier / nom))
    return [chemin for _, chemin in sorted(sessions)] + [root / "runtime" / "data" / nom]


def _snaps_par_vault(root: Path, *, now: float | None = None) -> dict[str, list[dict]]:
    """Série de snapshots de chaque vault : sessions archivées récentes + session en cours, sans doublon."""
    out: dict[str, list[dict]] = {}
    vus: set[tuple[str, object]] = set()
    for chemin in _rubans(root, SNAP.name, now=now):
        try:
            lignes = chemin.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for l in lignes:
            try:
                d = json.loads(l)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            a = str(d.get("vault") or "")
            cle = (a, d.get("ts_ms"))
            if a and cle not in vus:
                vus.add(cle)
                out.setdefault(a, []).append(d)
    return out


def _meta_depuis_suivis(root: Path) -> dict[str, dict]:
    """{adr: {age_j, tvl_usd}} depuis la provenance de vaults_suivis.json (si présente)."""
    try:
        d = json.loads((root / SUIVIS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, dict] = {}
    for v in (d.get("_provenance", {}).get("vaults") or []):
        a = str(v.get("address") or "").lower()
        if a:
            out[a] = {"age_j": float(v.get("age_j") or 0.0), "tvl_usd": float(v.get("tvl_usd") or 0.0)}
    return out


def coins_executables(root: Path, *, now: float | None = None) -> set[str]:
    """Coins qu'on peut réellement pricer : vus dans le carnet (L2 capturé) ∪ coins BBO."""
    exe = set(COINS_BBO)
    restant = 20000
    for chemin in reversed(_rubans(root, CARNET.name, depuis_j=2.0, now=now)):   # session en cours, puis les récentes
        if restant <= 0:
            break
        try:
            lignes = chemin.read_text(encoding="utf-8", errors="ignore").splitlines()[-restant:]
        except OSError:
            continue
        restant -= len(lignes)
        for l in lignes:
            try:
                c = str(json.loads(l).get("coin") or "").upper()
            except (ValueError, AttributeError):
                continue
            if c:
                exe.add(c)
    return exe


def construire(root: Path) -> dict:
    """Score tous les vaults snapshotés, publie classement + retenus. Meta (age/tvl) par adresse
    insensible à la casse."""
    snaps = _snaps_par_vault(root)
    meta_bas = _meta_depuis_suivis(root)
    meta = {a: meta_bas.get(a.lower(), {}) for a in snaps}
    exe = coins_executables(root)
    classement = VS.classer(snaps, meta=meta, coins_executables=exe)
    retenus = [c["vault"] for c in classement if c["retenu"]]
    return {"maj_ms": int(time.time() * 1000), "n_vaults": len(snaps), "n_retenus": len(retenus),
            "n_coins_executables": len(exe), "retenus": retenus, "classement": classement}


def ecrire(root: Path, payload: dict) -> int:
    dest = root / SORTIE
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(dest)
    return payload["n_retenus"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Score multi-facteurs des vaults (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--intervalle", type=float, default=600.0)
    p.add_argument("--une-fois", action="store_true")
    a = p.parse_args(argv)
    root = Path(a.root)
    while True:
        payload = construire(root)
        n = ecrire(root, payload)
        print("[scorer-vaults] %s  vaults=%d retenus=%d coins_exe=%d"
              % (time.strftime("%H:%M:%S"), payload["n_vaults"], n, payload["n_coins_executables"]), flush=True)
        if a.une_fois:
            return 0
        time.sleep(max(120.0, float(a.intervalle)))


if __name__ == "__main__":
    raise SystemExit(main())
