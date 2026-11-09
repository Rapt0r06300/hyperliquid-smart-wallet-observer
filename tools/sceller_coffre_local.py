#!/usr/bin/env python3
"""Scelle les données LOCALES certifiées dans le coffre-fort « données certifiées ».

Portail LOCAL du coffre (tier=LOCAL). Fait transiter chaque flux par le module
``hl_observer.datasets.coffre_certifie`` : seuls les enregistrements **replayables
+ backtestables** (bruts, réparés ou salvagés) sont déposés ; le reste va en
**quarantaine** (avec raison). Rien n'est supprimé en silence.

Modes :
- (défaut)  : scelle les flux connus de ``runtime/data`` (collecte courante).
- ``--tout`` : scanne récursivement tout ``Projet invest`` et certifie TOUTE donnée
  reconnue (hors ``.git``, ``catalog`` déjà SAFE, ``runtime/recovery`` SAFE, caches).

Sorties (sous ``runtime/coffre_certifie/``) :
- ``local/shards/<famille>/<batch>__<source>.jsonl.gz`` — enregistrements certifiés.
- ``local/manifests/<batch>.json`` — certificat du lot (SHA-256, comptes, fenêtres,
  histogramme coin/jour, tier=LOCAL, reconciliation_status=LOCAL_UNRECONCILED).
- ``quarantine/<batch>/<famille>.jsonl`` — rejets + raison.
- ``LOCAL_INDEX.json`` / ``COFFRE_INDEX.json`` — catalogues (le labo les lit).
- ``CERTIF_JOURNAL.jsonl`` + ``runtime/logs/coffre_certifie/certif_<ts>.log`` — logs.

LECTURE SEULE / PAPER : aucun réseau. Fail-closed : on ne vide jamais un brut sans
avoir vérifié le SHA de la copie scellée (option ``--reset-affichage``).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.datasets.coffre_certifie import (  # noqa: E402
    FAMILLE_BBO, FAMILLE_BOOK_L2, FAMILLE_FILLS_BACKFILL, FAMILLE_FILLS_FORWARD,
    FAMILLE_VENUE,
    PASS, QUARANTAINE, REPARE, StatsCertif, certifier_record, detecter_famille,
    identite, sniffer_famille,
)

COFFRE_RELDIR = Path("runtime") / "coffre_certifie"
LOG_RELDIR = Path("runtime") / "logs" / "coffre_certifie"

# Flux de sortie « vivants » remis à zéro après scellage (option --reset-affichage).
FLUX_VIVANTS = (
    "vault_fills_poll.jsonl", "vault_fills_live.jsonl",
    "copy_vault_l2_tape.jsonl", "bbo_tape.jsonl", "vault_snapshots.jsonl",
    "copy_vault_trades_lane.jsonl", "copy_vault_candle_lane.jsonl",
    "hl_allmids_tape.jsonl", "asset_ctx_tape.jsonl",
    "liquidations_confirmees.jsonl", "overshoots_liquidation.jsonl",
    "carnet_venues.jsonl", "dispersion_venues.jsonl",
)
# Dossiers jamais descendus par --tout. On exclut : le VCS/éditeurs/caches, les
# stores canoniques déjà SAFE ou volumineux (gérés par référence), et tout le
# bruit non-données (logs, rapports, recherche, archives, dépôts clonés…).
# Sans ça, os.walk plonge dans des arbres gigantesques (ex. runtime/research_lab/
# github_repos) et le scan semble « bloqué ».
_EXCLUS = {
    # VCS / éditeurs / caches
    ".git", ".github", ".idea", ".vscode", ".claude", ".agents", ".codex",
    "__pycache__", ".venv", "venv", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", "node_modules",
    # stores canoniques / déjà SAFE / volumineux (référencés, pas re-certifiés)
    "catalog", "datasets", "recovery", "coffre_certifie",
    "dist", "build", "wheelhouse", "portable-build", "portable_runtime",
    # bruit non-données : logs, rapports, recherche, archives, clones…
    "logs", "locks", "rapports", "Rapports en continu", "reports",
    "research", "research_lab", "github_repos_v24", "codex_experiments",
    "codex_research", "scenarios", "replay", "history", "archive", "archives",
    "EVIDENCE", "audit", "clone_payload", "docs", "tests", "outils de test",
    "src", "tools", "hyper_smart_observer", "agent_efficiency", "heartbeats",
}
#: garde-fou dur contre un arbre pathologique : au-delà, on arrête le scan.
_MAX_DOSSIERS_SCAN = 60_000
#: on ne RENIFLE (ouvre pour deviner la famille) que les fichiers assez gros : les
#: vrais flux de donnees font des Mo, les recus/metadonnees font des Ko. Les flux
#: au NOM connu restent reconnus quelle que soit leur taille. Evite des milliers
#: d'ouvertures inutiles (ex. les ~19 000 petits .jsonl de runtime/data).
_TAILLE_MIN_SNIFF = 64 * 1024  # 64 Ko


def _dossier_ignore(nom: str) -> bool:
    """Dossiers ignorés en plus de ``_EXCLUS`` : venvs et dossiers temporaires."""
    bas = nom.lower()
    return (
        "venv" in bas
        or bas.startswith(("cvprobe", "tmp", "pytest-", "pytest_tmp", ".tmp"))
    )


def _horodate() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fmt_duree(secondes: float) -> str:
    secondes = max(0, int(secondes))
    h, reste = divmod(secondes, 3600)
    m, s = divmod(reste, 60)
    if h:
        return f"{h:d}h{m:02d}m{s:02d}s"
    if m:
        return f"{m:d}m{s:02d}s"
    return f"{s:d}s"


def _jour_utc(ts_ms: int | None) -> str:
    if not ts_ms:
        return "0000-00-00"
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")


def _ts_primaire(record: dict[str, Any], famille: str) -> int | None:
    if famille == FAMILLE_BOOK_L2:
        return record.get("exchange_ts_ms")
    if famille == FAMILLE_BBO:
        return record.get("recv_wall_ts_ms")
    if famille == FAMILLE_VENUE:
        return record.get("snapshot_ts_ms")
    return record.get("ts_ms")


def _sha256_fichier(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for bloc in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            h.update(bloc)
    return h.hexdigest()


def _lire_lignes(path: Path) -> Iterator[str]:
    ouvre = gzip.open if path.suffix == ".gz" else open
    with ouvre(path, "rt", encoding="utf-8", errors="replace") as handle:  # type: ignore[operator]
        for ligne in handle:
            yield ligne


def _lire_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _ecrire_json_atomique(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _etat_source(path: Path) -> dict[str, Any]:
    st = path.stat()
    return {"taille": st.st_size, "mtime_ms": int(st.st_mtime * 1000)}


def sceller_fichier(
    source: Path, coffre: Path, batch_id: str, *, source_tag: str, famille: str,
    now_ms: int, deja_vus: set, log, prefixe: str = "",
) -> dict[str, Any] | None:
    """Certifie un fichier source, écrit le shard scellé + la quarantaine.

    Renvoie une entrée de manifeste (ou None si 0 enregistrement déposé).
    Streaming strict : une seule passe, un seul handle de sortie.
    """
    stats = StatsCertif()
    rel_src = source.relative_to(coffre.parents[1]) if coffre.parents[1] in source.parents else source.name
    base = source.name.replace(".gz", "").replace(".jsonl", "")
    shard_rel = COFFRE_RELDIR / "local" / "shards" / famille / f"{batch_id}__{base}.jsonl.gz"
    quar_rel = COFFRE_RELDIR / "quarantine" / batch_id / f"{famille}__{base}.jsonl"
    shard_abs = coffre.parents[1] / shard_rel
    quar_abs = coffre.parents[1] / quar_rel
    shard_abs.parent.mkdir(parents=True, exist_ok=True)

    coins: dict[str, int] = {}
    jours: dict[str, int] = {}
    ts_min: int | None = None
    ts_max: int | None = None
    quar_handle = None
    ecrits = 0
    try:
        with gzip.open(shard_abs, "wt", encoding="utf-8") as sortie:
            for brut in _lire_lignes(source):
                brut = brut.strip()
                if not brut:
                    continue
                stats.entrees += 1
                if stats.entrees % 250_000 == 0:
                    _log(log, f"        ... {stats.entrees:,} lignes lues, {ecrits:,} gardees jusqu'ici")
                try:
                    record = json.loads(brut)
                except (ValueError, UnicodeError):
                    stats.quarantaine += 1
                    stats._ajouter_raison("json_invalide")
                    quar_handle = quar_handle or _ouvrir_quar(quar_abs)
                    quar_handle.write(json.dumps({"raison": "json_invalide", "ligne": brut[:2000]}) + "\n")
                    continue
                norm, decision, raison = certifier_record(
                    record, famille=famille, source=source_tag, now_ms=now_ms,
                )
                if decision == QUARANTAINE:
                    stats.quarantaine += 1
                    stats._ajouter_raison(raison or "quarantaine")
                    quar_handle = quar_handle or _ouvrir_quar(quar_abs)
                    quar_handle.write(json.dumps({"raison": raison, "record": record}, ensure_ascii=False) + "\n")
                    continue
                cle = identite(norm, famille)
                if cle in deja_vus:
                    stats.doublons += 1
                    stats._ajouter_raison("doublon")
                    continue
                deja_vus.add(cle)
                if decision == REPARE:
                    stats.repares += 1
                else:
                    stats.passes += 1
                sortie.write(json.dumps({**norm, "tier": "LOCAL",
                                         "reconciliation_status": "LOCAL_UNRECONCILED"},
                                        ensure_ascii=False) + "\n")
                ecrits += 1
                coin = str(norm.get("coin") or "?")
                coins[coin] = coins.get(coin, 0) + 1
                tsp = _ts_primaire(norm, famille)
                jour = _jour_utc(tsp)
                jours[jour] = jours.get(jour, 0) + 1
                if tsp:
                    ts_min = tsp if ts_min is None else min(ts_min, tsp)
                    ts_max = tsp if ts_max is None else max(ts_max, tsp)
    finally:
        if quar_handle is not None:
            quar_handle.close()

    if ecrits == 0:
        # rien de déposable : retire le shard vide, garde la quarantaine + stats.
        try:
            shard_abs.unlink()
        except OSError:
            pass
        _log(log, f"        -> rien de bon a garder ici "
                  f"({stats.quarantaine:,} ecartees, {stats.doublons:,} doublons).")
        return {"source": str(rel_src), "famille": famille, "deposes": 0,
                "stats": stats.resume(), "shard": None}

    shard_sha = _sha256_fichier(shard_abs)
    _log(log, f"        -> {ecrits:,} gardees | {stats.repares:,} reparees | "
              f"{stats.quarantaine:,} ecartees | {stats.doublons:,} doublons")
    return {
        "source": str(rel_src), "famille": famille, "source_tag": source_tag,
        "shard": str(shard_rel).replace("\\", "/"),
        "shard_sha256": shard_sha, "shard_octets": shard_abs.stat().st_size,
        "deposes": ecrits, "coins": dict(sorted(coins.items(), key=lambda kv: -kv[1])),
        "jours": dict(sorted(jours.items())),
        "ts_min_ms": ts_min, "ts_max_ms": ts_max,
        "stats": stats.resume(),
    }


def _ouvrir_quar(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("w", encoding="utf-8")


def _log(handle, message: str) -> None:
    print(message, flush=True)
    if handle is not None:
        handle.write(message + "\n")
        handle.flush()


def collecter_fichiers(root: Path, *, tout: bool, log=None) -> list[tuple[Path, str, str]]:
    """Liste des (fichier, famille, source) à certifier.

    En mode ``tout``, le scan élague les dossiers de ``_EXCLUS`` et émet un
    battement régulier (jamais de blocage silencieux), avec un garde-fou dur.
    """
    trouves: list[tuple[Path, str, str]] = []
    if not tout:
        # Scan EXHAUSTIF de runtime/data : on ne se limite plus a une liste figee.
        # Chaque .jsonl est classe par NOM (familles connues) puis, si inconnu, par
        # CONTENU (reniflage) -> le coffre trouve TOUT, y compris de nouveaux flux.
        data = root / "runtime" / "data"
        if not data.is_dir():
            return trouves
        try:
            entrees = sorted(data.iterdir(), key=lambda e: e.name)
        except OSError:
            return trouves
        for p in entrees:
            try:
                nom = p.name
                if not (nom.endswith(".jsonl") or nom.endswith(".jsonl.gz")):
                    continue
                if not p.is_file() or p.stat().st_size == 0:
                    continue
                info = detecter_famille(nom)
                if info is None:
                    info = _sniffer_fichier(p)   # inconnu par nom -> on renifle le contenu
                    if info is None:
                        continue
                trouves.append((p, info[0], info[1]))
            except OSError:
                continue
        return trouves
    # --tout : scan récursif borné via os.scandir. Sur Windows, DirEntry.stat()
    # est MIS EN CACHE par scandir -> aucun appel système par fichier, donc rapide
    # meme dans un dossier a 100 000+ entrees (ex. runtime/data et ses recus).
    vus_dossiers = 0
    vus_entrees = 0
    pile = [str(root)]
    while pile:
        dossier = pile.pop()
        vus_dossiers += 1
        if vus_dossiers > _MAX_DOSSIERS_SCAN:
            if log is not None:
                _log(log, f"   [!] scan arrete a {vus_dossiers:,} dossiers (garde-fou).")
            break
        try:
            iterateur = os.scandir(dossier)
        except OSError:
            continue
        with iterateur:
            for e in iterateur:
                vus_entrees += 1
                if log is not None and vus_entrees % 25000 == 0:
                    _log(log, f"   ... scan : {vus_entrees:,} entrees vues, "
                              f"{len(trouves):,} fichier(s) de donnees reperes")
                try:
                    if e.is_dir(follow_symlinks=False):
                        if e.name not in _EXCLUS and not _dossier_ignore(e.name):
                            pile.append(e.path)
                        continue
                    if not e.is_file(follow_symlinks=False):
                        continue
                    nom = e.name
                    if not (nom.endswith(".jsonl") or nom.endswith(".jsonl.gz")):
                        continue
                    info = detecter_famille(nom)
                    if info is None:
                        # reniflage (ouverture) RESERVE aux fichiers assez gros.
                        if e.stat().st_size < _TAILLE_MIN_SNIFF:  # stat en cache
                            continue
                        info = _sniffer_fichier(Path(e.path))
                        if info is None:
                            continue
                    elif e.stat().st_size == 0:  # stat en cache
                        continue
                    trouves.append((Path(e.path), info[0], info[1]))
                except OSError:
                    continue
    if log is not None:
        _log(log, f"   -> scan termine : {vus_dossiers:,} dossiers, {len(trouves):,} fichier(s) de donnees.")
    return trouves


def _sniffer_fichier(path: Path) -> tuple[str, str] | None:
    """Reconnaît la famille d'un fichier de données par son contenu (1re ligne)."""
    try:
        for brut in _lire_lignes(path):
            brut = brut.strip()
            if not brut:
                continue
            try:
                record = json.loads(brut)
            except (ValueError, UnicodeError):
                return None  # 1re ligne non-JSON -> pas un flux de données reconnu
            return sniffer_famille(record)
    except OSError:
        return None
    return None


STATUT_RELPATH = COFFRE_RELDIR / "SUIVI_COFFRE.json"  # statut live lu par tools/suivi_coffre.py


def _ecrire_statut(root: Path, **champs: Any) -> None:
    """Écrit/merge le statut live de la certification (best-effort, jamais bloquant)."""
    try:
        chemin = root / STATUT_RELPATH
        chemin.parent.mkdir(parents=True, exist_ok=True)
        base = _lire_json(chemin) or {}
        base.update(champs)
        base["updated_ms"] = int(time.time() * 1000)
        _ecrire_json_atomique(chemin, base)
    except (OSError, TypeError, ValueError):
        pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Scelle les données locales certifiées dans le coffre-fort.")
    p.add_argument("--root", default=str(ROOT))
    p.add_argument("--tout", action="store_true",
                   help="scanne TOUT le dossier projet (sinon seulement runtime/data)")
    p.add_argument("--reset-affichage", action="store_true",
                   help="après scellage vérifié, remet à zéro les flux vivants de runtime/data")
    p.add_argument("--now-ms", type=int, default=0, help="horloge injectable (tests)")
    args = p.parse_args(argv)
    root = Path(args.root).resolve()
    coffre = root / COFFRE_RELDIR
    coffre.mkdir(parents=True, exist_ok=True)
    now_ms = args.now_ms or int(time.time() * 1000)
    from uuid import uuid4
    batch_id = f"{_horodate()}_{uuid4().hex[:8]}"  # unique même si 2 runs/seconde
    _ecrire_statut(root, active=True, stage="SCAN", batch_id=batch_id, pct=0.0,
                   i=0, n=0, fichier="", octets_faits=0, octets_total=0,
                   eta_s=0.0, debit_mo_s=0.0, termine=False, code=None, resume=None)

    log_dir = root / LOG_RELDIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"certif_{batch_id}.log"
    etat_path = coffre / "SOURCES_TRAITEES.json"
    etat = _lire_json(etat_path) or {}

    deja_vus: set = set()
    entrees_manifeste: list[dict[str, Any]] = []
    total = StatsCertif()
    scelles_pour_reset: list[Path] = []

    with log_path.open("w", encoding="utf-8") as log:
        _log(log, "============================================================")
        _log(log, "  CERTIFICATEUR DU COFFRE-FORT - donnees certifiees")
        _log(log, "============================================================")
        _log(log, "Ce que je fais : je passe en revue tes donnees, je GARDE")
        _log(log, "celles qui sont bonnes pour les tests (je les REPARE si besoin),")
        _log(log, "j'ECARTE les mauvaises (en disant pourquoi), et je range tout")
        _log(log, "dans le coffre-fort que le labo pourra utiliser.")
        _log(log, "")
        portee = "TOUT le projet" if args.tout else "la collecte en cours (runtime/data)"
        _log(log, f"ETAPE 1/3 - Je cherche les donnees dans : {portee}")
        fichiers = collecter_fichiers(root, tout=args.tout, log=log)
        total_octets = 0
        for f, _, _ in fichiers:
            try:
                total_octets += f.stat().st_size
            except OSError:
                pass
        total_octets = total_octets or 1
        n = len(fichiers)
        _log(log, f"   -> {n} fichier(s) a certifier, {total_octets / 1048576:.1f} Mo a examiner.")
        _log(log, "")
        _log(log, "ETAPE 2/3 - Je certifie chaque fichier (% = progression totale) :")
        t0 = time.monotonic()
        faits_octets = 0
        _ecrire_statut(root, active=True, stage="CERTIFICATION", n=n,
                       octets_total=total_octets, pct=0.0, i=0)
        for i, (source, famille, source_tag) in enumerate(fichiers, 1):
            try:
                src_etat = _etat_source(source)
            except OSError:
                continue
            taille = src_etat["taille"]
            pct = faits_octets / total_octets * 100
            ecoule = time.monotonic() - t0
            eta = (ecoule * (total_octets - faits_octets) / faits_octets) if faits_octets else 0
            tete = f"[{pct:4.0f}% | {i}/{n} | reste ~{_fmt_duree(eta)}]"
            _log(log, f"{tete} {source.name}  ({taille / 1048576:.1f} Mo)")
            _ecrire_statut(root, active=True, stage="CERTIFICATION", i=i, n=n,
                           fichier=source.name, pct=round(pct, 1),
                           octets_faits=faits_octets, octets_total=total_octets,
                           eta_s=round(eta, 1), batch_id=batch_id,
                           debit_mo_s=round((faits_octets / 1048576) / ecoule, 2) if ecoule > 0 else 0.0)
            cle_src = str(source.relative_to(root)) if root in source.parents else str(source)
            sha_src = _sha256_fichier(source)
            ancien = etat.get(cle_src)
            if ancien and ancien.get("sha256") == sha_src:
                _log(log, "        deja certifie (inchange depuis la derniere fois) - je passe.")
                faits_octets += taille
                continue
            entree = sceller_fichier(
                source, coffre, batch_id, source_tag=source_tag, famille=famille,
                now_ms=now_ms, deja_vus=deja_vus, log=log, prefixe=tete,
            )
            faits_octets += taille
            if entree is not None:
                entrees_manifeste.append(entree)
                st = entree.get("stats", {})
                total.entrees += st.get("entrees", 0)
                total.passes += st.get("passes", 0)
                total.repares += st.get("repares", 0)
                total.quarantaine += st.get("quarantaine", 0)
                total.doublons += st.get("doublons", 0)
                if entree.get("deposes") and source.name in FLUX_VIVANTS and source.parent.name == "data":
                    scelles_pour_reset.append(source)
            etat[cle_src] = {"sha256": sha_src, **src_etat, "batch": batch_id}

        if not entrees_manifeste:
            # Rien de nouveau (tout sauté/inchangé) : ne touche PAS aux index existants.
            _ecrire_json_atomique(etat_path, etat)
            _log(log, "")
            _log(log, "Rien de nouveau : toutes les donnees etaient deja dans le coffre. Rien a faire.")
            _ecrire_statut(root, active=False, termine=True, code=0, pct=100.0,
                           stage="RIEN DE NOUVEAU", eta_s=0.0, resume=total.resume())
            return 0

        # Manifeste du lot
        manifeste = {
            "schema": "hypersmart.coffre_certifie.local.v1",
            "batch_id": batch_id, "tier": "LOCAL",
            "reconciliation_status": "LOCAL_UNRECONCILED",
            "genere_ms": now_ms, "git_head": _git_head(root),
            "mode": "tout" if args.tout else "runtime_data",
            "fichiers": entrees_manifeste, "total": total.resume(),
        }
        _ecrire_json_atomique(coffre / "local" / "manifests" / f"{batch_id}.json", manifeste)
        _maj_local_index(coffre, manifeste)
        _log(log, "")
        _log(log, "ETAPE 3/3 - Je range le coffre et je recense les donnees GitHub deja certifiees...")
        _maj_coffre_index(root, coffre)
        _journaliser(coffre, manifeste)
        _ecrire_json_atomique(etat_path, etat)

        # Reset affichage (fail-closed : seulement les shards vérifiés SHA)
        if args.reset_affichage and scelles_pour_reset:
            for src in scelles_pour_reset:
                try:
                    src.write_text("", encoding="utf-8")
                    _log(log, f"  [RESET] {src.name} remis à zéro (données dans le coffre)")
                except OSError as exc:
                    _log(log, f"  [RESET-KO] {src.name}: {exc}")

        coffre_index = _lire_json(coffre / "COFFRE_INDEX.json") or {}
        tiers = coffre_index.get("tiers", {})
        local_t = tiers.get("LOCAL", {})
        safe_t = tiers.get("SAFE_CLOUD", {})
        _log(log, "")
        _log(log, "============================================================")
        _log(log, "  TERMINE - voici le bilan")
        _log(log, "============================================================")
        _log(log, f"  Donnees examinees      : {total.entrees:,}")
        _log(log, f"  Gardees dans le coffre : {total.deposes():,}  (dont {total.repares:,} reparees)")
        _log(log, f"  Ecartees (mauvaises)   : {total.quarantaine:,}")
        _log(log, f"  Doublons ignores       : {total.doublons:,}")
        _log(log, "")
        _log(log, f"  Tier LOCAL  : {local_t.get('deposes', 0):,} donnees | "
                  f"{len(local_t.get('coins', []))} coins | {len(local_t.get('jours', []))} jours")
        if safe_t.get("present"):
            _log(log, f"  Tier GitHub : {safe_t.get('shards_safe', 0):,} lots SAFE deja certifies "
                      f"(references tels quels, jamais modifies)")
        _log(log, "")
        _log(log, "  Les donnees ecartees sont rangees (avec la raison) dans :")
        _log(log, "     runtime\\coffre_certifie\\quarantine\\")
        _log(log, "  Le labo pourra puiser dans ce coffre pour ses backtests et replays.")
        _log(log, f"  Coffre : {coffre}")
        _ecrire_statut(root, active=False, termine=True, code=0, pct=100.0,
                       stage="TERMINE", eta_s=0.0, fichier="", resume=total.resume())
    return 0


def _git_head(root: Path) -> str | None:
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
                           check=False, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = r.stdout.strip().lower()
    return sha if len(sha) == 40 and all(c in "0123456789abcdef" for c in sha) else None


def _maj_local_index(coffre: Path, manifeste: dict[str, Any]) -> None:
    idx_path = coffre / "LOCAL_INDEX.json"
    idx = _lire_json(idx_path) or {"schema": "hypersmart.coffre_certifie.local_index.v1",
                                   "tier": "LOCAL", "lots": [], "shards": []}
    idx["lots"] = [l for l in idx.get("lots", []) if l.get("batch_id") != manifeste["batch_id"]]
    idx["lots"].append({"batch_id": manifeste["batch_id"], "genere_ms": manifeste["genere_ms"],
                        "total": manifeste["total"], "mode": manifeste["mode"]})
    # shards : (famille, coin, jour) -> référence, pour ciblage par le labo
    shards = [s for s in idx.get("shards", []) if s.get("batch_id") != manifeste["batch_id"]]
    for entree in manifeste["fichiers"]:
        if not entree.get("shard"):
            continue
        shards.append({
            "batch_id": manifeste["batch_id"], "famille": entree["famille"],
            "shard": entree["shard"], "sha256": entree.get("shard_sha256"),
            "octets": entree.get("shard_octets"), "deposes": entree.get("deposes"),
            "coins": list(entree.get("coins", {}).keys()),
            "jours": list(entree.get("jours", {}).keys()),
            "ts_min_ms": entree.get("ts_min_ms"), "ts_max_ms": entree.get("ts_max_ms"),
            "quality_status": "LOCAL_CERTIFIED", "tier": "LOCAL",
        })
    idx["shards"] = shards
    _ecrire_json_atomique(idx_path, idx)


def _maj_coffre_index(root: Path, coffre: Path) -> None:
    """Catalogue unifié 2 tiers que le labo lit (SAFE-cloud référencé + LOCAL)."""
    local_idx = _lire_json(coffre / "LOCAL_INDEX.json") or {}
    shards = local_idx.get("shards", [])
    par_famille: dict[str, int] = {}
    coins: set = set()
    jours: set = set()
    deposes = 0
    for s in shards:
        par_famille[s["famille"]] = par_famille.get(s["famille"], 0) + (s.get("deposes") or 0)
        coins.update(s.get("coins", []))
        jours.update(j for j in s.get("jours", []) if j != "0000-00-00")
        deposes += s.get("deposes") or 0
    safe_inv = _inventaire_safe(root)
    coffre_index = {
        "schema": "hypersmart.coffre_certifie.index.v1",
        "genere_ms": int(time.time() * 1000),
        "tiers": {
            "SAFE_CLOUD": {
                "catalogue": "catalog/DATA_INDEX.json",
                "recovery": "runtime/recovery/full",
                "note": "certifié-cloud fail-closed ; référencé en place, jamais modifié ni bloqué",
                **safe_inv,
            },
            "LOCAL": {
                "index": "runtime/coffre_certifie/LOCAL_INDEX.json",
                "deposes": deposes, "par_famille": par_famille,
                "coins": sorted(coins), "jours": sorted(jours),
                "n_shards": len(shards),
            },
        },
    }
    _ecrire_json_atomique(coffre / "COFFRE_INDEX.json", coffre_index)


def _inventaire_safe(root: Path) -> dict[str, Any]:
    """Référence (lecture seule) les shards SAFE copy-vault collectés via GitHub.

    N'altère ni ne bloque rien : lit ``catalog/DATA_INDEX.json`` et compte les
    shards ``copy_vault_* / SAFE``. Fail-soft : si absent/illisible, renvoie un
    statut explicite sans planter la certification locale.
    """
    cat = root / "catalog" / "DATA_INDEX.json"
    if not cat.is_file():
        return {"present": False, "raison": "DATA_INDEX_absent"}
    try:
        from tools.partitioned_data_index import select_index_rows  # noqa: WPS433
    except Exception:  # pragma: no cover
        try:
            from partitioned_data_index import select_index_rows  # type: ignore
        except Exception:
            return {"present": True, "raison": "selecteur_indisponible"}
    try:
        _index, rows = select_index_rows(
            cat, lambda r: str(r.get("family") or "").startswith("copy_vault_"),
        )
    except Exception as exc:  # pragma: no cover
        return {"present": True, "raison": f"lecture_index_KO:{type(exc).__name__}"}
    familles: dict[str, int] = {}
    tags: set = set()
    n_safe = 0
    for r in rows:
        if r.get("quality_status") != "SAFE":
            continue
        n_safe += 1
        fam = str(r.get("family"))
        familles[fam] = familles.get(fam, 0) + 1
        if isinstance(r.get("release_tag"), str):
            tags.add(r["release_tag"])
    return {
        "present": True, "shards_safe": n_safe, "par_famille": familles,
        "n_releases": len(tags), "derniers_tags": sorted(tags)[-5:],
    }


def _journaliser(coffre: Path, manifeste: dict[str, Any]) -> None:
    journal = coffre / "CERTIF_JOURNAL.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    ligne = {
        "batch_id": manifeste["batch_id"], "genere_ms": manifeste["genere_ms"],
        "mode": manifeste["mode"], "total": manifeste["total"],
        "n_fichiers": len(manifeste["fichiers"]),
    }
    with journal.open("a", encoding="utf-8") as h:
        h.write(json.dumps(ligne, ensure_ascii=False) + "\n")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
