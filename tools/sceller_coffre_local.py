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
import re
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
    identite, motif_non_certifie, nouvellement_accepte, sniffer_famille, version_certificateur,
)

COFFRE_RELDIR = Path("runtime") / "coffre_certifie"
#: Dossiers où les collecteurs écrivent leurs rubans. Le second (microstructure Hyperliquid :
#: BBO dense, carnets L2, transactions) n'était jamais visité : 1,4 Go restaient hors coffre.
DOSSIERS_COLLECTE = (
    Path("runtime") / "data",
    Path("runtime") / "research_lab" / "data",   # microstructure Hyperliquid
    Path("runtime") / "history",                 # bougies de backfill
)
LOG_RELDIR = Path("runtime") / "logs" / "coffre_certifie"

# Flux de sortie « vivants » remis à zéro après scellage (option --reset-affichage).
FLUX_VIVANTS = (
    "vault_fills_poll.jsonl", "vault_fills_live.jsonl",
    "copy_vault_l2_tape.jsonl", "bbo_tape.jsonl", "vault_snapshots.jsonl",
    "copy_vault_trades_lane.jsonl", "copy_vault_candle_lane.jsonl",
    "hl_allmids_tape.jsonl", "asset_ctx_tape.jsonl",
    "liquidations_confirmees.jsonl", "overshoots_liquidation.jsonl",
    "carnet_venues.jsonl", "dispersion_venues.jsonl", "explorer_tx_tape.jsonl",
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
    if famille == "candle":
        return record.get("open_ts_ms")
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


def _lire_lignes(path: Path, *, debut: int = 0, fin: int | None = None) -> Iterator[str]:
    """Lignes du fichier ; pour un ruban texte, uniquement les octets ``[debut, fin)``.

    ``fin`` est une frontière de ligne figée au début du scellage : une ligne encore en cours
    d'écriture par un collecteur n'est ni lue ni mise en quarantaine, elle sera scellée au
    passage suivant."""
    if path.suffix == ".gz":
        # archive tournante : flux décompressé, complet (aucune ligne en cours d'écriture)
        with gzip.open(path, "rb") as handle:
            if debut > 0:
                handle.seek(debut)
            for brut in handle:
                yield brut.decode("utf-8", errors="replace")
        return
    with path.open("rb") as handle:
        handle.seek(max(0, debut))
        restant = None if fin is None else max(0, fin - max(0, debut))
        for brut in handle:
            if restant is not None:
                if len(brut) > restant:
                    break
                restant -= len(brut)
            yield brut.decode("utf-8", errors="replace")


def _sha256_prefixe(path: Path, octets: int) -> str:
    """SHA-256 des ``octets`` premiers octets (identité d'un préfixe déjà scellé)."""
    h = hashlib.sha256()
    restant = max(0, int(octets))
    ouvrir = gzip.open if path.suffix == ".gz" else open   # .gz : préfixe du flux décompressé
    with ouvrir(path, "rb") as handle:
        while restant > 0:
            bloc = handle.read(min(4 * 1024 * 1024, restant))
            if not bloc:
                break
            h.update(bloc)
            restant -= len(bloc)
    return h.hexdigest()


def _fin_derniere_ligne(path: Path, taille: int) -> int:
    """Plus grand offset ``<= taille`` situé juste après un saut de ligne (0 si aucun)."""
    with path.open("rb") as handle:
        pos = max(0, int(taille))
        while pos > 0:
            pas = min(1 << 16, pos)
            handle.seek(pos - pas)
            k = handle.read(pas).rfind(b"\n")
            if k >= 0:
                return pos - pas + k + 1
            pos -= pas
    return 0


_ROTATION = re.compile(r"_\d{10,}$")


def _tronc(nom: str) -> str:
    """Nom logique d'un ruban : sans ``.gz``, sans ``.jsonl``, sans suffixe de rotation horodaté.

    ``micro_bbo_1794306635046325200.jsonl.gz`` et ``micro_bbo.jsonl`` sont le même ruban :
    le second devient le premier quand le collecteur le fait tourner."""
    base = str(nom).replace(chr(92), "/").rsplit("/", 1)[-1]
    if base.endswith(".gz"):
        base = base[:-3]
    if base.endswith(".jsonl"):
        base = base[:-6]
    return _ROTATION.sub("", base)


def _prefixes_connus(source: Path, etat: dict[str, Any], version: int) -> list[tuple[int, str]]:
    """Préfixes déjà scellés (règle courante) pour ce ruban, du plus long au plus court."""
    tronc = _tronc(source.name)
    connus: set[tuple[int, str]] = set()
    for cle, e in etat.items():
        if not isinstance(e, dict) or _tronc(str(cle)) != tronc:
            continue
        if int(e.get("certif_version", 1)) < version:
            continue   # préfixe scellé avec une règle périmée : à relire entièrement
        if e.get("prefixe_octets") and e.get("prefixe_sha256"):
            connus.add((int(e["prefixe_octets"]), str(e["prefixe_sha256"])))
        for ancien in e.get("prefixes_precedents") or []:
            if isinstance(ancien, list) and len(ancien) == 2 and ancien[0] and ancien[1]:
                connus.add((int(ancien[0]), str(ancien[1])))
    return sorted(connus, reverse=True)


def _reprise_append_only(source: Path, fin: int | None, etat: dict[str, Any], *, essais: int = 5,
                         version: int = 1) -> int:
    """Offset à partir duquel sceller : fin du plus long préfixe DÉJÀ scellé de ce ruban.

    Un ruban de collecte ne fait que grossir : si ses N premiers octets ont le SHA-256 d'un
    préfixe déjà scellé (même ruban, y compris après déplacement en archive ou rotation en
    ``.jsonl.gz`` — on compare alors le flux décompressé), seuls les octets suivants sont
    nouveaux. Sans préfixe reconnu (fichier réécrit, nouvelle session) on rescelle tout :
    jamais de donnée sautée sur une simple supposition."""
    candidats = [c for c in _prefixes_connus(source, etat, version) if fin is None or c[0] <= fin]
    for octets, sha in candidats[:essais]:
        if _sha256_prefixe(source, octets) == sha:
            return octets
    return 0


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
    debut_octets: int = 0, fin_octets: int | None = None, rattrapage: bool = False,
) -> dict[str, Any] | None:
    """Certifie un fichier source, écrit le shard scellé + la quarantaine.

    Renvoie une entrée de manifeste (ou None si 0 enregistrement déposé).
    Streaming strict : une seule passe, un seul handle de sortie.
    ``debut_octets``/``fin_octets`` : tranche du ruban à sceller (reprise incrémentale).
    Le shard est écrit sous un nom temporaire puis renommé : une interruption ne laisse
    jamais un shard tronqué à son chemin définitif.
    """
    stats = StatsCertif()
    rel_src = source.relative_to(coffre.parents[1]) if coffre.parents[1] in source.parents else source.name
    base = _base_shard(source, coffre.parents[1])
    shard_rel = COFFRE_RELDIR / "local" / "shards" / famille / f"{batch_id}__{base}.jsonl.gz"
    quar_rel = COFFRE_RELDIR / "quarantine" / batch_id / f"{famille}__{base}.jsonl"
    shard_abs = coffre.parents[1] / shard_rel
    quar_abs = coffre.parents[1] / quar_rel
    shard_abs.parent.mkdir(parents=True, exist_ok=True)
    if shard_abs.exists():
        # Un shard déposé est immuable : on ne l'écrase JAMAIS (l'index pointerait alors vers un
        # contenu qui n'est plus celui certifié). Mieux vaut refuser que perdre un dépôt.
        raise FileExistsError(f"shard deja present, ecrasement refuse : {shard_rel}")

    coins: dict[str, int] = {}
    jours: dict[str, int] = {}
    ts_min: int | None = None
    ts_max: int | None = None
    quar_handle = None
    ecrits = 0
    shard_final = shard_abs
    shard_abs = shard_final.with_name(f".{shard_final.name}.partial")
    try:
        with gzip.open(shard_abs, "wt", encoding="utf-8") as sortie:
            for brut in _lire_lignes(source, debut=debut_octets, fin=fin_octets):
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
                if rattrapage and not nouvellement_accepte(source.name, norm):
                    # ruban archivé déjà scellé avec l'ancienne règle : cette ligne y est déjà
                    stats.doublons += 1
                    stats._ajouter_raison("deja_couvert_regle_precedente")
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
    except BaseException:
        try:
            shard_abs.unlink()   # interruption : aucun fichier partiel ne survit
        except OSError:
            pass
        raise
    finally:
        if quar_handle is not None:
            quar_handle.close()

    if ecrits:
        os.replace(shard_abs, shard_final)   # publication atomique du shard complet
        shard_abs = shard_final
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
        "source_octets": [int(debut_octets), None if fin_octets is None else int(fin_octets)],
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
        entrees: list[Path] = []
        for data in DOSSIERS_COLLECTE:
            try:
                # une archive tournante passe AVANT le ruban actif homonyme : elle contient ce
                # que le ruban actif avait déjà fait sceller, la reprise par préfixe doit la
                # reconnaître avant que l'état du ruban actif ne soit remplacé.
                entrees += sorted((root / data).iterdir(),
                                  key=lambda e: (_tronc(e.name), not e.name.endswith(".gz"), e.name))
            except OSError:
                continue
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


def _classer(path: Path) -> tuple[str, str] | None:
    """(famille, source) d'un fichier de collecte : par son nom, sinon par son contenu."""
    return detecter_famille(path.name) or _sniffer_fichier(path)


def _est_ruban(path: Path) -> bool:
    return path.name.endswith(".jsonl") or path.name.endswith(".jsonl.gz")


def collecter_archives(root: Path) -> list[tuple[Path, str, str]]:
    """Rubans des sessions archivées (``runtime/archive/<session>/``), classés comme les autres.

    Les archives sont exclues du scan ``--tout`` (déjà scellées à l'arrêt). ``--archives`` les
    réintègre : indispensable quand une règle de certification corrigée doit rattraper des
    rubans rejetés à tort par l'ancienne règle."""
    trouves: list[tuple[Path, str, str]] = []
    base = root / "runtime" / "archive"
    if not base.is_dir():
        return trouves
    for session in sorted(d for d in base.iterdir() if d.is_dir()):
        for fichier in sorted(session.iterdir(), key=lambda e: e.name):
            try:
                if not fichier.is_file() or not _est_ruban(fichier) or fichier.stat().st_size == 0:
                    continue
                info = _classer(fichier)
            except OSError:
                continue
            if info is not None:
                trouves.append((fichier, info[0], info[1]))
    return trouves


def recenser_non_certifies(root: Path, *, archives: bool = False) -> list[dict[str, Any]]:
    """Fichiers de collecte présents mais NON certifiés, chacun avec sa raison.

    ``categorie`` : motif par conception (INFERENCE, DERIVE, REDONDANT, HORS_PERIMETRE,
    DIAGNOSTIC) ou ``INCONNU`` — un flux que le certificateur ne sait pas traiter et qu'il
    faut lui apprendre. Rien n'est ignoré en silence : la liste entre au manifeste et au
    fichier ``COUVERTURE.json``."""
    dossiers = [root / d for d in DOSSIERS_COLLECTE]
    if archives and (root / "runtime" / "archive").is_dir():
        dossiers += sorted(d for d in (root / "runtime" / "archive").iterdir() if d.is_dir())
    vus: dict[str, dict[str, Any]] = {}
    for dossier in dossiers:
        if not dossier.is_dir():
            continue
        for fichier in sorted(dossier.iterdir(), key=lambda e: e.name):
            try:
                if not fichier.is_file() or not _est_ruban(fichier) or fichier.stat().st_size == 0:
                    continue
                if _classer(fichier) is not None:
                    continue
                taille = fichier.stat().st_size
            except OSError:
                continue
            motif = motif_non_certifie(fichier.name)
            ligne = vus.setdefault(fichier.name, {
                "fichier": fichier.name, "octets": 0, "exemplaires": 0,
                "categorie": motif[0] if motif else "INCONNU",
                "motif": motif[1] if motif else "aucune règle de certification : flux à apprendre au certificateur",
            })
            ligne["octets"] += taille
            ligne["exemplaires"] += 1
    return sorted(vus.values(), key=lambda l: (l["categorie"] != "INCONNU", -l["octets"], l["fichier"]))


def _base_shard(source: Path, racine: Path) -> str:
    """Nom de base du shard d'une source, UNIQUE dans un lot.

    Un ruban des dossiers de collecte garde son nom nu (``bbo_tape``). Une source située
    ailleurs — session archivée, scan ``--tout`` — reçoit une empreinte de son chemin : dix
    sessions archivées contiennent chacune un ``bbo_tape.jsonl``, et sans cette empreinte
    leurs shards porteraient le même nom dans un même lot et s'écraseraient l'un l'autre."""
    base = source.name.replace(".gz", "").replace(".jsonl", "")
    if source.parent in [racine / d for d in DOSSIERS_COLLECTE]:
        return base
    try:
        relatif = source.relative_to(racine).as_posix()
    except ValueError:
        relatif = source.as_posix()
    return f"{base}__{hashlib.sha256(relatif.encode('utf-8')).hexdigest()[:10]}"


def verifier_lot(racine: Path, fichiers: list[dict[str, Any]]) -> list[str]:
    """Relit chaque shard du lot : présent, et de SHA-256 égal à celui du manifeste.

    Renvoie la liste des anomalies (vide = lot intègre). Appelée en fin de scellage : un
    dépôt dont le contenu ne correspond pas à son empreinte ne passe jamais inaperçu."""
    anomalies: list[str] = []
    vus: set[str] = set()
    for entree in fichiers:
        relatif = entree.get("shard")
        if not relatif:
            continue
        if relatif in vus:
            anomalies.append(f"deux sources pointent vers le meme shard : {relatif}")
            continue
        vus.add(relatif)
        chemin = racine / relatif
        if not chemin.is_file():
            anomalies.append(f"shard absent : {relatif}")
        elif _sha256_fichier(chemin) != entree.get("shard_sha256"):
            anomalies.append(f"empreinte differente du manifeste : {relatif}")
    return anomalies


def _precharger_identites(coffre: Path, lots: list[str], source: Path, famille: str, deja_vus: set) -> int:
    """Identités déjà déposées pour ce ruban dans ``lots`` -> ``deja_vus`` (aucun doublon à la reprise)."""
    nu = source.name.replace(".gz", "").replace(".jsonl", "")
    noms = {nu, _base_shard(source, coffre.parents[1])}
    charges = 0
    for lot in lots:
        for base in sorted(noms):
            shard = coffre / "local" / "shards" / famille / f"{lot}__{base}.jsonl.gz"
            if shard.is_file():
                break
        else:
            continue
        with gzip.open(shard, "rt", encoding="utf-8") as handle:
            for ligne in handle:
                try:
                    deja_vus.add(identite(json.loads(ligne), famille))
                    charges += 1
                except (ValueError, TypeError):
                    continue
    return charges


def _lots_ayant_scelle(source: Path, sha_src: str, frontiere: int, etat: dict[str, Any]) -> list[str]:
    """Lots qui ont déjà scellé ce contenu : même SHA, ou préfixe reconnu d'un ruban homonyme."""
    lots: set[str] = set()
    for cle, e in etat.items():
        if not isinstance(e, dict) or not e.get("batch"):
            continue
        if e.get("sha256") == sha_src:
            lots.add(str(e["batch"]))
        elif (Path(str(cle).replace(chr(92), "/")).name == source.name and e.get("prefixe_octets")
              and e.get("prefixe_sha256") and int(e["prefixe_octets"]) <= frontiere
              and _sha256_prefixe(source, int(e["prefixe_octets"])) == e["prefixe_sha256"]):
            lots.add(str(e["batch"]))
    return sorted(lots)


def _verifier_magasin_ticks(root: Path, coffre: Path, budget_s: float, log) -> dict[str, Any] | None:
    """Vérifie et référence EN PLACE le magasin de ticks natifs (``runtime/data/market_ticks``).

    Ce magasin (des dizaines de Go, déjà auto-manifesté) n'est pas recopié : chaque shard
    immuable est relu et comparé à son manifeste, puis référencé. Passage borné et repris au
    suivant : la fermeture des collecteurs n'attend jamais. Ne fait jamais échouer le scellage
    des rubans ; une anomalie est écrite en clair dans le journal et dans les index.
    """
    try:
        import verifier_store_ticks

        resume = verifier_store_ticks.verifier_store(root, budget_s=budget_s)
    except Exception as exc:  # noqa: BLE001 - le coffre LOCAL ne doit pas dépendre de ce contrôle
        if type(exc).__name__ == "VerificationEnCours":
            _log(log, "   [ticks] une autre verification du magasin de ticks est deja en cours : "
                      "rien n'est modifie, son index fera foi.")
        else:
            _log(log, f"   [ticks] verification du magasin de ticks impossible : {type(exc).__name__}: {exc}")
        return None
    if not resume.get("present"):
        return resume
    etat = "complet" if resume["complet"] else f"partiel, {resume['dossiers_restants']} dossier(s) au prochain passage"
    _log(log, f"   [ticks] magasin de ticks natifs : {resume['shards_verifies']:,} shard(s) verifie(s) et "
              f"reference(s) en place ({resume['octets_verifies'] / 1e9:.2f} Go), +{resume['verifies_ce_passage']:,} "
              f"a ce passage ; {etat}.")
    _log(log, f"   [ticks] rubans encore en cours d'ecriture (non immuables) : {resume['rubans_en_cours']:,} "
              f"({resume['octets_en_cours'] / 1e9:.2f} Go) - verifiables a leur rotation.")
    if resume["anomalies"]:
        _log(log, f"   [INTEGRITE-TICKS] {resume['anomalies']} shard(s) du magasin ne correspondent pas a leur "
                  f"manifeste (liste dans MARKET_TICKS_INDEX.json).")
    index_path = coffre / "COFFRE_INDEX.json"
    index = _lire_json(index_path)
    if isinstance(index, dict) and isinstance(index.get("tiers"), dict):
        index["tiers"]["MARKET_TICKS_STORE"] = {
            "index": "runtime/coffre_certifie/MARKET_TICKS_INDEX.json",
            "note": "magasin de ticks natifs : verifie par SHA-256 contre ses manifestes et reference en place",
            "shards_verifies": resume["shards_verifies"], "octets_verifies": resume["octets_verifies"],
            "anomalies": resume["anomalies"], "complet": resume["complet"],
            "rubans_en_cours": resume["rubans_en_cours"],
        }
        _ecrire_json_atomique(index_path, index)
    return resume


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


def boucler(argv: list[str], intervalle_s: float, *, limite_passes: int = 0,
            dormir=None, horloge=None) -> int:
    """Certifie en continu : une passe, attente, recommence.

    POURQUOI. La certification n'avait lieu qu'a l'ARRET PROPRE d'une campagne (touche q) ou au
    DEMARRAGE suivant. Une campagne de six jours fermee brutalement au jour cinq laissait donc cinq
    jours de donnees non certifiees — or le labo ne lit QUE le coffre certifie : ces jours lui
    restaient invisibles tant que personne ne relancait. Ici, au pire on perd l'intervalle en cours.

    C'est sans danger pendant que les collecteurs ECRIVENT : le scellage s'arrete au dernier saut de
    ligne COMPLET (`_fin_derniere_ligne`) et reprend ou il s'etait arrete (`_reprise_append_only`).
    Une ligne a moitie ecrite n'est donc jamais certifiee, et la passe suivante la reprendra entiere.

    On n'arrete JAMAIS la boucle sur une passe en echec : une certification qui echoue a 3 h du matin
    ne doit pas condamner les cinq jours suivants. On l'annonce et on reessaie au tour d'apres.
    """
    import time as _time
    dormir = _time.sleep if dormir is None else dormir
    horloge = _time.monotonic if horloge is None else horloge
    passes, echecs, dernier = 0, 0, 0
    while True:
        debut = horloge()
        try:
            dernier = main(argv)
        except KeyboardInterrupt:                      # Ctrl+C : on sort TOUT DE SUITE
            raise
        except Exception as exc:                       # noqa: BLE001 — une passe ratee n'arrete rien
            dernier, echecs = 1, echecs + 1
            print(f"[coffre] passe en echec ({type(exc).__name__}: {exc}) — on reessaie",
                  flush=True)
        else:
            if dernier != 0:
                echecs += 1
        passes += 1
        print(f"[coffre] passe {passes} terminee en {horloge() - debut:.0f}s "
              f"(code {dernier}, {echecs} echec(s) depuis le debut) — "
              f"prochaine dans {intervalle_s / 60:.0f} min", flush=True)
        if limite_passes and passes >= limite_passes:
            return dernier
        dormir(intervalle_s)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Scelle les données locales certifiées dans le coffre-fort.")
    p.add_argument("--root", default=str(ROOT))
    p.add_argument("--tout", action="store_true",
                   help="scanne TOUT le dossier projet (sinon seulement runtime/data)")
    p.add_argument("--reset-affichage", action="store_true",
                   help="après scellage vérifié, remet à zéro les flux vivants de runtime/data")
    p.add_argument("--now-ms", type=int, default=0, help="horloge injectable (tests)")
    p.add_argument("--famille", default="",
                   help="ne certifie que cette famille (ex. snapshot) ; vide = toutes")
    p.add_argument("--budget-ticks-s", type=float, default=45.0,
                   help="duree maximale (s) consacree a verifier le magasin de ticks natifs a ce passage")
    p.add_argument("--nom", default="",
                   help="ne certifie que les fichiers de ce nom (ex. vault_fills_live.jsonl)")
    p.add_argument("--boucle-s", type=float, default=0.0,
                   help="certifie EN CONTINU : une passe, puis attente de N secondes, sans fin "
                        "(0 = une seule passe, comportement d'origine). Sert a ne PAS perdre la "
                        "certification si une campagne est fermee brutalement.")
    p.add_argument("--archives", action="store_true",
                   help="inclut les rubans des sessions archivées (rattrapage après correction d'une règle)")
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
        if args.tout:
            # Le scan récursif saute ``research_lab`` (où vit la microstructure) : sans ce retour
            # explicite aux dossiers de collecte, le mode par défaut du lanceur ne la verrait jamais.
            deja = {str(f[0]) for f in fichiers}
            fichiers += [f for f in collecter_fichiers(root, tout=False) if str(f[0]) not in deja]
        if args.archives:
            deja = {str(f[0]) for f in fichiers}
            laisses = 0
            for f in collecter_archives(root):
                if str(f[0]) in deja:
                    continue
                if not args.nom and version_certificateur(f[0].name) <= 1:
                    # Session archivée, règle inchangée : ce ruban a été scellé à l'arrêt de sa
                    # session. Le relire en entier ne créerait que des doublons d'un lot à l'autre.
                    laisses += 1
                    continue
                fichiers.append(f)
            if laisses:
                _log(log, f"   -> {laisses} ruban(s) d'archive a regle inchangee laisses (deja scelles a "
                          f"l'arret de leur session ; --nom <fichier> pour en forcer un).")
        if args.famille:
            fichiers = [f for f in fichiers if f[1] == args.famille]
        if args.nom:
            fichiers = [f for f in fichiers if f[0].name == args.nom]
        # COUVERTURE : ce que je vois mais ne certifie pas, et pourquoi (jamais en silence).
        non_certifies = recenser_non_certifies(root, archives=args.archives)
        inconnus = [l for l in non_certifies if l["categorie"] == "INCONNU"]
        _ecrire_json_atomique(coffre / "COUVERTURE.json", {
            "schema": "hypersmart.coffre_certifie.couverture.v1", "genere_ms": now_ms,
            "certifiables": sorted({f"{f[0].name} -> {f[1]}" for f in fichiers}),
            "non_certifies": non_certifies, "inconnus": len(inconnus),
        })
        if non_certifies:
            _log(log, f"   -> {len(non_certifies)} type(s) de fichier de collecte NON certifie(s) :")
            for ligne in non_certifies:
                _log(log, f"      [{ligne['categorie']}] {ligne['fichier']} "
                          f"({ligne['octets'] / 1048576:.1f} Mo) - {ligne['motif']}")
        if inconnus:
            _log(log, f"   [!] {len(inconnus)} flux INCONNU(S) : le certificateur doit apprendre a les traiter.")
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
            version = version_certificateur(source.name)
            if ancien and ancien.get("sha256") == sha_src and int(ancien.get("certif_version", 1)) >= version:
                _log(log, "        deja certifie (inchange depuis la derniere fois) - je passe.")
                faits_octets += taille
                continue
            debut, fin = 0, None
            frontiere = None
            if True:
                # Même contenu déjà scellé sous un autre chemin (ruban déplacé en archive) :
                # le resceller ne créerait que des doublons d'un lot à l'autre.
                jumeau = next((c for c, e in etat.items() if isinstance(e, dict)
                               and e.get("sha256") == sha_src and c != cle_src
                               and int(e.get("certif_version", 1)) >= version), None)
                if jumeau is not None:
                    _log(log, f"        meme contenu deja certifie ({Path(jumeau).name}) - je passe.")
                    etat[cle_src] = {"sha256": sha_src, **src_etat, "batch": etat[jumeau].get("batch"),
                                     "meme_contenu_que": jumeau, "certif_version": version,
                                     "prefixe_octets": etat[jumeau].get("prefixe_octets"),
                                     "prefixe_sha256": etat[jumeau].get("prefixe_sha256")}
                    faits_octets += taille
                    continue
                # ``fin`` fige la lecture à la taille observée maintenant ; ``frontiere`` (dernier
                # saut de ligne) borne le préfixe réputé scellé : une ligne finale encore en
                # cours d'écriture sera relue complète au prochain passage.
                if source.suffix != ".gz":
                    fin = taille
                    frontiere = _fin_derniere_ligne(source, taille)
                debut = _reprise_append_only(source, frontiere, etat, version=version)
                rattrapage = False
                if version > 1 and not debut and frontiere is not None:
                    # Règle de certification corrigée : je relis TOUT le ruban, mais les lignes
                    # déjà déposées par un lot précédent ne doivent pas l'être une seconde fois.
                    lots = _lots_ayant_scelle(source, sha_src, frontiere, etat)
                    if lots:
                        connues = _precharger_identites(coffre, lots, source, famille, deja_vus)
                        _log(log, f"        regle de certification mise a jour (v{version}) : je reprends ce "
                                  f"fichier ; {connues:,} ligne(s) deja au coffre ne seront pas dupliquees.")
                    elif "archive" in source.parts:
                        # Session archivée (donc scellée à son arrêt avec l'ancienne règle) dont le
                        # lot exact n'est plus identifiable : je ne dépose que ce que cette règle
                        # rejetait à tort ; le reste est déjà au coffre.
                        rattrapage = True
                        _log(log, f"        rattrapage (regle v{version}) : seules les lignes rejetees "
                                  f"a tort par l'ancienne regle sont deposees.")
                if debut:
                    _log(log, f"        ruban deja certifie jusqu'a {debut / 1048576:.1f} Mo : "
                              f"je ne scelle que la suite.")
            entree = sceller_fichier(
                source, coffre, batch_id, source_tag=source_tag, famille=famille,
                now_ms=now_ms, deja_vus=deja_vus, log=log, prefixe=tete,
                debut_octets=debut, fin_octets=fin, rattrapage=rattrapage,
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
            etat[cle_src] = {"sha256": sha_src, **src_etat, "batch": batch_id, "certif_version": version}
            # Historique des préfixes scellés sous ce chemin : quand le ruban actif repart de zéro
            # (rotation), l'ancienne identité reste connue pour reconnaître l'archive tournante.
            historique = list((ancien or {}).get("prefixes_precedents") or [])
            if ancien and ancien.get("prefixe_octets") and ancien.get("prefixe_sha256"):
                historique.insert(0, [int(ancien["prefixe_octets"]), str(ancien["prefixe_sha256"])])
            if historique:
                etat[cle_src]["prefixes_precedents"] = historique[:8]
            if fin is not None:
                # identité du préfixe scellé : base de la reprise incrémentale au prochain passage
                etat[cle_src]["prefixe_octets"] = frontiere
                etat[cle_src]["prefixe_sha256"] = _sha256_prefixe(source, frontiere)
            if entrees_manifeste:
                # POINT DE REPRISE après chaque fichier : manifeste, index et état sont écrits
                # (atomiquement) au fur et à mesure. Une interruption — Ctrl+C, coupure, arrêt du
                # PC — ne laisse donc jamais un shard déposé hors index, ni un fichier déjà
                # scellé à refaire (ce qui créerait des doublons d'un lot à l'autre).
                manifeste_partiel = {
                    "schema": "hypersmart.coffre_certifie.local.v1",
                    "batch_id": batch_id, "tier": "LOCAL",
                    "reconciliation_status": "LOCAL_UNRECONCILED",
                    "genere_ms": now_ms, "git_head": None,
                    "mode": "tout" if args.tout else "runtime_data",
                    "fichiers": entrees_manifeste, "total": total.resume(),
                    "non_certifies": non_certifies, "en_cours": True,
                }
                _ecrire_json_atomique(coffre / "local" / "manifests" / f"{batch_id}.json", manifeste_partiel)
                _maj_local_index(coffre, manifeste_partiel)
                _ecrire_json_atomique(etat_path, etat)

        if not entrees_manifeste:
            # Rien de nouveau (tout sauté/inchangé) : ne touche PAS aux index existants.
            _ecrire_json_atomique(etat_path, etat)
            _log(log, "")
            _log(log, "Rien de nouveau : toutes les donnees etaient deja dans le coffre. Rien a faire.")
            if not (args.nom or args.famille):
                _verifier_magasin_ticks(root, coffre, args.budget_ticks_s, log)
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
            "non_certifies": non_certifies,
        }
        anomalies = verifier_lot(root, entrees_manifeste)
        manifeste["integrite"] = {"verifie": True, "anomalies": anomalies}
        _ecrire_json_atomique(coffre / "local" / "manifests" / f"{batch_id}.json", manifeste)
        _maj_local_index(coffre, manifeste)
        if anomalies:
            _log(log, "")
            _log(log, f"[INTEGRITE] {len(anomalies)} anomalie(s) dans ce lot - a corriger avant usage :")
            for anomalie in anomalies[:20]:
                _log(log, f"   - {anomalie}")
        _log(log, "")
        _log(log, "ETAPE 3/3 - Je range le coffre et je recense les donnees GitHub deja certifiees...")
        _maj_coffre_index(root, coffre)
        if not (args.nom or args.famille):
            _verifier_magasin_ticks(root, coffre, args.budget_ticks_s, log)
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
        code_final = 4 if anomalies else 0   # 4 = lot déposé mais intégrité à corriger
        _ecrire_statut(root, active=False, termine=True, code=code_final, pct=100.0,
                       stage="TERMINE" if not anomalies else "INTEGRITE A CORRIGER",
                       eta_s=0.0, fichier="", resume=total.resume())
    return code_final


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


def _point_d_entree(argv: list[str] | None = None) -> int:
    """Aiguille entre une passe unique et la boucle, en retirant `--boucle-s` de la ligne passee."""
    import sys as _sys
    args = list(_sys.argv[1:] if argv is None else argv)
    intervalle = 0.0
    nettoye: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--boucle-s" and i + 1 < len(args):
            intervalle = float(args[i + 1])
            i += 2
            continue
        if args[i].startswith("--boucle-s="):
            intervalle = float(args[i].split("=", 1)[1])
            i += 1
            continue
        nettoye.append(args[i])
        i += 1
    if intervalle <= 0:
        return main(nettoye)
    print(f"[coffre] certification EN CONTINU toutes les {intervalle / 60:.0f} min. "
          "Ctrl+C pour arreter.", flush=True)
    try:
        return boucler(nettoye, intervalle)
    except KeyboardInterrupt:
        print("[coffre] arret demande — la derniere passe complete reste certifiee.", flush=True)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_point_d_entree())
