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
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.datasets.coffre_certifie import (  # noqa: E402
    ORIGINE_EXTERNE,
    PREFIXE_SOURCE_EXTERNE,
    FAMILLE_BBO,
    FAMILLE_BOOK_L2,
    FAMILLE_FILLS_BACKFILL,
    FAMILLE_FILLS_FORWARD,
    FAMILLE_POSITION,
    FAMILLE_TRADES,
    FAMILLE_VENUE,
    PASS,
    QUARANTAINE,
    REPARE,
    StatsCertif,
    certifier_record,
    detecter_famille,
    identite,
    motif_non_certifie,
    nouvellement_accepte,
    rattrapage_par_identite,
    sniffer_famille,
    version_certificateur,
)
from hl_observer.datasets.empreintes_compactes import EnsembleDIdentites
from hl_observer.ops import verrou_pid  # noqa: E402

COFFRE_RELDIR = Path("runtime") / "coffre_certifie"
#: 16/11 — VERROU DU SCELLEUR. Il n'en avait aucun, et la campagne le relance deja toutes les
#: 30 min (collecteur « coffre-certificateur »). Depuis que le rattrapage scelle lui-meme a la fin
#: de son passage, deux scellages peuvent tomber en meme temps : ils ecrivent le MEME
#: SOURCES_TRAITEES.json, et le dernier a ecrire efface les decalages d'octets de l'autre. La
#: donnee survit, le registre de ce qui est scelle non — et c'est lui qui dit au labo ce qu'il
#: peut lire.
VERROU_RELPATH = Path("runtime") / "data" / "coffre_certificateur.lock"
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

#: VITESSE — niveau de compression des shards. `gzip.open` par défaut utilise 9, le plus LENT.
#: Mesuré le 19/11/2026 sur un ruban réel de 162 Mo décompressés : niveau 9 = 1,54 s pour 17,2 Mo ;
#: niveau 6 = 1,12 s pour 16,5 Mo (donc PLUS RAPIDE *et* PLUS PETIT — 9 n'a aucun avantage ici) ;
#: niveau 4 = 0,88 s / 17,4 Mo ; niveau 1 = 0,33 s / 28,0 Mo (très rapide mais +63 % de disque).
#: La compression ne change QUE les octets du shard, jamais son contenu décompressé : aucun
#: enregistrement n'est perdu ni modifié, et le `shard_sha256` de chaque shard reste enregistré
#: dans l'index. Les shards DÉJÀ déposés sont immuables et ne sont jamais réécrits.
#: Réglable sans toucher au code : COFFRE_GZIP_NIVEAU=1 pour privilégier la vitesse.
def _niveau_gzip(defaut: int = 6) -> int:
    try:
        v = int(os.environ.get("COFFRE_GZIP_NIVEAU", "") or defaut)
    except (TypeError, ValueError):
        return defaut
    return v if 1 <= v <= 9 else defaut


NIVEAU_GZIP = _niveau_gzip()

#: VITESSE + TAILLE — séparateurs compacts pour la sérialisation des enregistrements scellés.
#: `json.dumps` par défaut écrit « , » et « : » (avec espaces) : des octets inutiles sur des
#: centaines de millions de lignes. Le JSON produit est strictement équivalent à la relecture.
_SEPARATEURS_COMPACTS = (",", ":")

#: VITESSE — JSON rapide OPTIONNEL. Mesuré le 19/11/2026 : `json.loads` et `json.dumps` pèsent
#: à eux deux ~48 % du temps de certification (0,68 s + 0,68 s pour 81 Mo). `orjson` les fait
#: typiquement 3 à 6 fois plus vite. Il est DÉJÀ traité comme optionnel ailleurs dans le projet
#: (`LANCER_COLLECTEURS.cmd` retente son contrôle de dépendances sans lui).
#: ABSENT = comportement d'avant, à l'octet près. Aucune dépendance n'est imposée.
try:                                   # pragma: no cover - dépend de l'environnement
    import orjson as _orjson
except ImportError:                    # pragma: no cover
    _orjson = None

JSON_RAPIDE = _orjson is not None


def _charger_json(texte: str):
    """Parse une ligne JSON. Lève ValueError sur entrée invalide (comme `json.loads`).

    `orjson.JSONDecodeError` dérive de `ValueError` : les appelants qui attrapent
    `(ValueError, UnicodeError)` gardent exactement le même comportement.
    """
    if _orjson is not None:
        return _orjson.loads(texte)
    return json.loads(texte)


#: ÉCRITURE : la bibliothèque standard est le DÉFAUT, volontairement.
#: Mesuré le 19/11/2026 sur 120 000 enregistrements réels (6 familles) : `orjson` et la lib
#: standard donnent un contenu identique à 100,000 % après relecture, mais seulement 71,2 %
#: d'octets identiques — les flottants n'ont pas la même représentation (les deux sont exactes
#: au retour). Or un shard est identifié par son SHA : laisser l'écriture dépendre d'une
#: bibliothèque OPTIONNELLE rendrait les octets du coffre dépendants de l'environnement, dans un
#: système bâti sur des reçus cryptographiques. Le déterminisme passe donc avant ces ~24 %.
#: Opt-in explicite pour qui privilégie la vitesse : COFFRE_JSON_ECRITURE_RAPIDE=1.
_ECRITURE_RAPIDE = (
    _orjson is not None
    and os.environ.get("COFFRE_JSON_ECRITURE_RAPIDE", "").strip() in {"1", "true", "oui", "on"}
)


def _ecrire_json(obj) -> str:
    """Sérialise un enregistrement scellé en JSON compact UTF-8 non échappé.

    Par défaut : bibliothèque standard, pour des octets de shard REPRODUCTIBLES quelle que
    soit la présence d'`orjson`. Sous `COFFRE_JSON_ECRITURE_RAPIDE=1`, `orjson` est utilisé
    (contenu identique, octets éventuellement différents sur les flottants), avec repli
    standard pour tout objet qu'il refuse : un type inattendu ne doit JAMAIS faire perdre
    un enregistrement.
    """
    if _ECRITURE_RAPIDE:
        try:
            return _orjson.dumps(obj).decode("utf-8")
        except TypeError:
            pass
    return json.dumps(obj, ensure_ascii=False, separators=_SEPARATEURS_COMPACTS)


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
    """L'horloge qui DATE une ligne de cette famille, pour l'histogramme de jours de l'index.

    16/11/2026 — DEFAUT MESURE PAR LA MATRICE DU COFFRE. Le repli `record.get("ts_ms")` ne
    convenait pas a deux familles qui ne portent PAS ce champ :

    * `position` (171 shards, 870 142 lignes) n'a que `received_at_ms` ;
    * `trades_marche` (192 shards, 24 095 493 lignes) a `exchange_ts_ms` et `received_at_ms`.

    Resultat : leurs 363 shards etaient indexes avec `jours = ["0000-00-00"]`, le sentinelle
    « jour inconnu ». Consequence directe sur la recherche : **aucune etude ne peut decouper ces
    familles par jour**, alors que la seule hypothese non refutee par `docs/LOIS_MESUREES.md`
    (operateurs lents, replication d'inventaire) exige justement des TRANSITIONS DE POSITION sur
    des jours independants. Le pont du labo avait recu ce correctif le 16/11 ; le scelleur, non.

    Les shards deja scelles gardent leur sentinelle : rien n'est reecrit retroactivement. Seuls
    les nouveaux lots porteront la vraie date, et un reindexage explicite serait necessaire pour
    les anciens.
    """
    if famille == "candle":
        return record.get("open_ts_ms")
    if famille == FAMILLE_BOOK_L2:
        return record.get("exchange_ts_ms")
    if famille == FAMILLE_BBO:
        return record.get("recv_wall_ts_ms")
    if famille == FAMILLE_VENUE:
        return record.get("snapshot_ts_ms")
    if famille == FAMILLE_POSITION:
        return record.get("received_at_ms")
    if famille == FAMILLE_TRADES:
        return record.get("exchange_ts_ms") or record.get("received_at_ms")
    return record.get("ts_ms")


def _sha256_fichier(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for bloc in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            h.update(bloc)
    return h.hexdigest()


def _sha256_contenu_source(path: Path, *, progression: Callable[[int], None] | None = None) -> str:
    """Empreinte du contenu logique d'un ruban, pas de son emballage gzip.

    Le registre de reprise identifie un ruban par les octets JSONL décompressés. Une
    archive doit donc avoir la même identité que le ruban clair qu'elle remplace ;
    hasher les membres gzip bruts ferait croire à une nouvelle source et redéposerait
    tout le ruban.
    """
    h = hashlib.sha256()
    ouvrir = gzip.open if path.suffix == ".gz" else open
    lus = 0
    with ouvrir(path, "rb") as handle:
        while True:
            bloc = handle.read(4 * 1024 * 1024)
            if not bloc:
                break
            h.update(bloc)
            lus += len(bloc)
            if progression is not None:
                try:
                    progression(lus)
                except Exception:  # noqa: BLE001 - le suivi ne doit jamais interrompre le scellage
                    pass
    return h.hexdigest()


class _SortieHachee(io.RawIOBase):
    """Relais d'écriture qui HACHE les octets au passage.

    VITESSE : le shard était écrit, refermé, puis RELU entièrement pour calculer son
    `shard_sha256`. Comme le SHA porte sur les octets compressés, on peut l'accumuler
    pendant l'écriture : le résultat est le MÊME condensé, sans la seconde lecture.
    Le condensé n'est complet qu'une fois le GzipFile fermé (il écrit sa bande-annonce).
    """

    def __init__(self, brut, digest) -> None:
        super().__init__()
        self._brut = brut
        self._digest = digest

    def writable(self) -> bool:
        return True

    def write(self, donnees) -> int:  # type: ignore[override]
        vue = bytes(donnees)
        self._digest.update(vue)
        self._brut.write(vue)
        return len(vue)

    def flush(self) -> None:
        self._brut.flush()


def _lire_lignes(path: Path, *, debut: int = 0, fin: int | None = None,
                 progression: Callable[[int, int], None] | None = None) -> Iterator[str]:
    """Lignes du fichier ; pour un ruban texte, uniquement les octets ``[debut, fin)``.

    ``fin`` est une frontière de ligne figée au début du scellage : une ligne encore en cours
    d'écriture par un collecteur n'est ni lue ni mise en quarantaine, elle sera scellée au
    passage suivant."""
    lus = lignes = dernier_lus = 0
    derniere_publication = time.monotonic()

    def decoder(handle, restant: int | None = None):
        nonlocal lus, lignes, dernier_lus, derniere_publication
        while True:
            brut = handle.readline()
            if not brut:
                break
            if restant is not None:
                if len(brut) > restant:
                    break
                restant -= len(brut)
            lus += len(brut)
            lignes += 1
            maintenant = time.monotonic()
            if progression is not None and (
                lus - dernier_lus >= 1 * 1024 * 1024 or maintenant - derniere_publication >= 1.0
            ):
                try:
                    progression(lus, lignes)
                except Exception:  # noqa: BLE001 - diagnostic best-effort
                    pass
                dernier_lus, derniere_publication = lus, maintenant
            yield brut.decode("utf-8", errors="replace")
        if progression is not None and (lus != dernier_lus or lignes == 0):
            try:
                progression(lus, lignes)
            except Exception:  # noqa: BLE001 - diagnostic best-effort
                pass
            dernier_lus, derniere_publication = lus, time.monotonic()

    if path.suffix == ".gz":
        # archive tournante : flux décompressé, complet (aucune ligne en cours d'écriture)
        with gzip.open(path, "rb") as handle:
            if debut > 0:
                handle.seek(debut)
            yield from decoder(handle)
        return
    with path.open("rb") as handle:
        handle.seek(max(0, debut))
        restant = None if fin is None else max(0, fin - max(0, debut))
        yield from decoder(handle, restant)


def _sha256_prefixe(path: Path, octets: int, *, progression: Callable[[int], None] | None = None) -> str:
    """SHA-256 des ``octets`` premiers octets (identité d'un préfixe déjà scellé)."""
    h = hashlib.sha256()
    restant = max(0, int(octets))
    lus = 0
    ouvrir = gzip.open if path.suffix == ".gz" else open   # .gz : préfixe du flux décompressé
    with ouvrir(path, "rb") as handle:
        while restant > 0:
            bloc = handle.read(min(4 * 1024 * 1024, restant))
            if not bloc:
                raise OSError(f"source raccourcie pendant le hash du prefixe : {path}")
            h.update(bloc)
            lus += len(bloc)
            restant -= len(bloc)
            if progression is not None:
                try:
                    progression(lus)
                except Exception:  # noqa: BLE001 - le suivi ne doit jamais interrompre le scellage
                    pass
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
                         version: int = 1,
                         progression: Callable[[int, int], None] | None = None) -> int:
    """Offset à partir duquel sceller : fin du plus long préfixe DÉJÀ scellé de ce ruban.

    Un ruban de collecte ne fait que grossir : si ses N premiers octets ont le SHA-256 d'un
    préfixe déjà scellé (même ruban, y compris après déplacement en archive ou rotation en
    ``.jsonl.gz`` — on compare alors le flux décompressé), seuls les octets suivants sont
    nouveaux. Sans préfixe reconnu (fichier réécrit, nouvelle session) on rescelle tout :
    jamais de donnée sautée sur une simple supposition."""
    candidats = [c for c in _prefixes_connus(source, etat, version) if fin is None or c[0] <= fin]
    if source.suffix == ".gz":
        # 23/11/2026 -- ARCHIVE : sa longueur decompressee est connue sans la decompresser (index d'une archive par
        # blocs, sinon champ ISIZE du gzip). Avant, les 5 prefixes les PLUS LONGS etaient essayes a l'aveugle : un
        # prefixe plus long que l'archive faisait planter le hash (« source raccourcie »), et le bon prefixe -- de
        # la longueur de l'archive -- n'etait jamais essaye des que l'historique depassait 5 entrees.
        longueur, exacte = _longueur_claire(source)
        if longueur is not None:
            if exacte:
                candidats = [c for c in candidats if c[0] <= longueur]
            candidats.sort(key=lambda c: (abs(c[0] - longueur), -c[0]))
        for octets, sha in candidats[:max(essais, 8)]:
            try:
                cb = (lambda lus, total=octets: progression(lus, total)) if progression else None
                if _sha256_prefixe(source, octets, progression=cb) == sha:
                    return octets
            except OSError:
                continue                     # archive plus courte que ce prefixe : ce n'est pas le sien
        return 0
    for octets, sha in candidats[:essais]:
        cb = (lambda lus, total=octets: progression(lus, total)) if progression else None
        if _sha256_prefixe(source, octets, progression=cb) == sha:
            return octets
    return 0


def _horodatage_large(record: dict[str, Any], famille: str) -> int | None:
    t = _ts_primaire(record, famille)
    for champ in ("ts_ex", "ts_wall_ms", "ts_ms", "exchange_ts_ms", "recv_wall_ts_ms", "received_at_ms"):
        if isinstance(t, (int, float)) and not isinstance(t, bool):
            break
        t = record.get(champ)
    return int(t) if isinstance(t, (int, float)) and not isinstance(t, bool) else None


def _precharger_identites_fenetre(coffre: Path, source: Path, famille: str, deja_vus, faits: set) -> int | None:
    """Identités du coffre (famille) sur la période RÉELLE d'une archive : la plus ancienne et la plus récente de ses lignes.

    23/11/2026 : la première version supposait « première ligne -> horodatage de rotation du nom, sinon + 6 h ». Une
    archive de session sans horodatage dans son nom (``vault_episodes.jsonl.gz``) couvre des MOIS : 16 093 lignes
    déjà au coffre ont été redéposées. La période se LIT sur toutes les lignes (une lecture de plus), jamais supposée."""
    debut_ms = fin_ms = None
    maintenant = int(time.time() * 1000)
    for brut in _lire_lignes(source):
        try:
            rec = json.loads(brut)
            t = _horodatage_large(rec, famille)
            if t is None:
                # l'horloge BRUTE peut porter un autre nom (``time`` des fills Hyperliquid) : c'est celle de la ligne
                # CERTIFIÉE qui date les shards de l'index
                norm, _d, _m = certifier_record(rec, famille=famille, source=str(rec.get("source") or famille),
                                                now_ms=maintenant)
                t = _horodatage_large(norm, famille) if isinstance(norm, dict) else None
        except (ValueError, TypeError, AttributeError, KeyError):
            continue
        if t is None:
            continue
        while t > 10 ** 13:                                   # µs / ns -> ms, comme l'index
            t //= 1000
        debut_ms = t if debut_ms is None else min(debut_ms, t)
        fin_ms = t if fin_ms is None else max(fin_ms, t)
    if debut_ms is None:
        return None     # période illisible : l'appelant NE DÉPOSE RIEN (échec fermé), le fichier reste à prouver
    index = _lire_json(coffre / "LOCAL_INDEX.json") or {}
    n = 0
    for s in index.get("shards", []):
        if not isinstance(s, dict) or s.get("famille") != famille or s.get("shard") in faits:
            continue
        a, b = s.get("ts_min_ms"), s.get("ts_max_ms")
        if isinstance(a, int) and isinstance(b, int) and (b < debut_ms - 3_600_000 or a > fin_ms + 3_600_000):
            continue
        faits.add(s.get("shard"))
        try:
            with gzip.open(coffre.parents[1] / s["shard"], "rb") as g:
                for ligne in g:
                    deja_vus.add(empreinte_contenu(ligne.rstrip(b"\r\n")))
                    n += 1
        except OSError:
            continue
    return n


def empreinte_contenu(octets: bytes) -> int:
    """Empreinte (8 octets) du CONTENU exact d'une ligne scellee.

    24/11/2026 -- AUCUNE VERSION PERDUE. Le prechargement de periode (rotation, ruban reecrit) comparait les IDENTITES :
    une nouvelle version d'un fill deja au coffre (enrichie de pos_avant, fee, closedPnl...) etait ecartee comme un
    doublon. Mesure du 23/11 : 21 % des lignes de meme identite n'avaient PAS le meme contenu. Seule une ligne
    identique a l'octet a celle deja scellee est un doublon ; une autre version entre au coffre."""
    return int.from_bytes(hashlib.blake2b(octets, digest_size=8).digest(), "little")


def _longueur_claire(source: Path) -> tuple[int | None, bool]:
    """(longueur decompressee, exacte ?) d'une archive ``.gz``, sans la decompresser."""
    idx = source.with_name(source.name + ".idx.json")
    if idx.is_file():
        try:
            return int(json.loads(idx.read_text(encoding="utf-8"))["taille_clair"]), True
        except (OSError, ValueError, KeyError):
            pass
    try:
        with source.open("rb") as f:
            f.seek(-4, 2)
            return int.from_bytes(f.read(4), "little"), False      # ISIZE : modulo 2^32, dernier membre seulement
    except OSError:
        return None, False


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
    expected_source_sha256: str | None = None, source_snapshot_octets: int | None = None,
    contenus_coffre: set | None = None,
    progression_cb: Callable[[str, int, int | None, int | None], None] | None = None,
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
    if source.suffix == ".gz":
        longueur, exacte = _longueur_claire(source)
        total_logique = longueur if exacte else None
    else:
        borne = source.stat().st_size if fin_octets is None else int(fin_octets)
        total_logique = max(0, borne - max(0, int(debut_octets)))

    def progression_lignes(octets_lus: int, lignes_lues: int) -> None:
        if progression_cb is not None:
            progression_cb("LECTURE JSONL", octets_lus, total_logique, lignes_lues)

    shard_final = shard_abs
    shard_abs = shard_final.with_name(f".{shard_final.name}.partial")
    h_shard = hashlib.sha256()
    try:
        with open(shard_abs, "wb") as _octets_shard, \
             _SortieHachee(_octets_shard, h_shard) as _relais, \
             gzip.GzipFile(fileobj=_relais, mode="wb", compresslevel=NIVEAU_GZIP) as _gz, \
             io.TextIOWrapper(_gz, encoding="utf-8", newline="\n") as sortie:
            for brut in _lire_lignes(
                source, debut=debut_octets, fin=fin_octets,
                progression=progression_lignes if progression_cb is not None else None,
            ):
                brut = brut.strip()
                if not brut:
                    continue
                stats.entrees += 1
                if stats.entrees % 250_000 == 0:
                    _log(log, f"        ... {stats.entrees:,} lignes lues, {ecrits:,} gardees jusqu'ici")
                try:
                    record = _charger_json(brut)
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
                ligne_scellee = _ecrire_json({**norm, "tier": "LOCAL", "reconciliation_status": "LOCAL_UNRECONCILED"})
                if contenus_coffre and empreinte_contenu(ligne_scellee.encode("utf-8")) in contenus_coffre:
                    # deja au coffre A L'OCTET (rotation, ruban reecrit) ; une AUTRE version de meme identite entre
                    stats.doublons += 1
                    stats._ajouter_raison("deja_au_coffre_a_l_octet")
                    continue
                deja_vus.add(cle)
                if decision == REPARE:
                    stats.repares += 1
                else:
                    stats.passes += 1
                sortie.write(ligne_scellee + "\n")
                ecrits += 1
                coin = str(norm.get("coin") or "?")
                coins[coin] = coins.get(coin, 0) + 1
                tsp = _ts_primaire(norm, famille)
                jour = _jour_utc(tsp)
                jours[jour] = jours.get(jour, 0) + 1
                if tsp:
                    ts_min = tsp if ts_min is None else min(ts_min, tsp)
                    ts_max = tsp if ts_max is None else max(ts_max, tsp)
            if expected_source_sha256 is not None:
                if source_snapshot_octets is None:
                    raise ValueError("source_snapshot_octets manquant")
                if source.suffix == ".gz":
                    def progresser_hash_final(lus: int) -> None:
                        if progression_cb is not None:
                            progression_cb("VÉRIFICATION FINALE", lus, total_logique, None)
                    after_sha = _sha256_contenu_source(source, progression=progresser_hash_final)
                else:
                    def progresser_prefixe_final(lus: int) -> None:
                        if progression_cb is not None:
                            progression_cb("VÉRIFICATION FINALE", lus, source_snapshot_octets, None)
                    after_sha = _sha256_prefixe(
                        source, source_snapshot_octets, progression=progresser_prefixe_final
                    )
                if after_sha != expected_source_sha256:
                    raise RuntimeError(f"source modifiee pendant la certification : {source}")
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

    # Condensé accumulé PENDANT l'écriture (cf. _SortieHachee) : identique à une relecture
    # complète du shard, sans la payer. Complet ici, le GzipFile étant refermé.
    shard_sha = h_shard.hexdigest()
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


def _cle_fichier(chemin) -> str:
    """Cle d identite d un fichier, insensible a la casse et au chemin relatif.

    Le scan --tout redescend dans runtime/data : sans cette cle, chaque ruban y
    serait inventorie deux fois.
    """
    return os.path.normcase(os.path.abspath(str(chemin)))


def collecter_fichiers(root: Path, *, tout: bool, log=None,
                       progression_cb: Callable[[dict[str, Any]], None] | None = None
                       ) -> list[tuple[Path, str, str]]:
    """Liste des (fichier, famille, source) à certifier.

    En mode ``tout``, le scan élague les dossiers de ``_EXCLUS`` et émet un
    battement régulier (jamais de blocage silencieux), avec un garde-fou dur.
    """
    trouves: list[tuple[Path, str, str]] = []
    vus_entrees = 0
    vus_dossiers = 0
    dernier_battement = 0.0

    def battre(force: bool = False) -> None:
        nonlocal dernier_battement
        maintenant = time.monotonic()
        if progression_cb is None or (not force and maintenant - dernier_battement < 1.0):
            return
        try:
            progression_cb({"stage": "SCAN", "scan_entrees_vues": vus_entrees,
                            "scan_donnees_trouvees": len(trouves), "scan_dossiers_vus": vus_dossiers,
                            "progression_ms": int(time.time() * 1000)})
        except Exception:  # noqa: BLE001 — le suivi n'est pas une dépendance du scellage
            pass
        dernier_battement = maintenant

    battre(force=True)
    # 19/11/2026 -- CE BLOC TOURNE AUSSI EN MODE --tout. Avant, il etait garde par
    # `if not tout`, et --tout partait en scan recursif en elaguant _EXCLUS, qui
    # contient `history` ET `research_lab` : --tout scellait donc MOINS que le mode
    # par defaut (il perdait les bougies de backfill et la microstructure). --tout
    # est desormais un SUR-ENSEMBLE STRICT du defaut.
    if DOSSIERS_COLLECTE:
        # Scan EXHAUSTIF de runtime/data : on ne se limite plus a une liste figee.
        # Chaque .jsonl est classe par NOM (familles connues) puis, si inconnu, par
        # CONTENU (reniflage) -> le coffre trouve TOUT, y compris de nouveaux flux.
        entrees: list[Path] = []
        for data in DOSSIERS_COLLECTE:
            try:
                # une archive tournante passe AVANT le ruban actif homonyme : elle contient ce
                # que le ruban actif avait déjà fait sceller, la reprise par préfixe doit la
                # reconnaître avant que l'état du ruban actif ne soit remplacé.
                dossier = root / data
                vus_dossiers += 1
                with os.scandir(dossier) as scan:
                    locales = []
                    for entree in scan:
                        locales.append(Path(entree.path))
                        vus_entrees += 1
                        battre()
                entrees += sorted(locales,
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
            battre()
        if not tout:
            battre(force=True)
            return trouves
    # --tout : scan récursif borné via os.scandir. Sur Windows, DirEntry.stat()
    # est MIS EN CACHE par scandir -> aucun appel système par fichier, donc rapide
    # meme dans un dossier a 100 000+ entrees (ex. runtime/data et ses recus).
    # Les dossiers de collecte sont deja inventories ci-dessus : on ne les
    # recense pas deux fois (un meme ruban scelle en double est du travail perdu).
    deja_vus = {_cle_fichier(c) for c, _fam, _src in trouves}
    pile = [str(root)]
    while pile:
        dossier = pile.pop()
        vus_dossiers += 1
        battre()
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
                    if _cle_fichier(e.path) in deja_vus:
                        continue   # deja inventorie par les dossiers de collecte
                    trouves.append((Path(e.path), info[0], info[1]))
                except OSError:
                    continue
    if log is not None:
        _log(log, f"   -> scan termine : {vus_dossiers:,} dossiers, {len(trouves):,} fichier(s) de donnees.")
    battre(force=True)
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


def _precharger_identites(
    coffre: Path, lots: list[str], source: Path, famille: str,
    deja_vus: "EnsembleDIdentites | set",
) -> int:
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


def _precharger_identites_du_ruban(
    coffre: Path, source: Path, famille: str, deja_vus: "EnsembleDIdentites | set", deja_faits: set,
) -> int:
    """Identités de TOUS les lots déjà déposés pour ce ruban, tous lots confondus (une fois par passage).

    Sert quand c'est l'IDENTITÉ qui a été corrigée : le lot d'origine d'une session archivée n'est
    pas toujours retrouvable, et une ligne déjà au coffre ne doit jamais y entrer deux fois."""
    nu = source.name.replace(".gz", "").replace(".jsonl", "")
    if (famille, nu) in deja_faits:
        return 0
    deja_faits.add((famille, nu))
    charges = 0
    dossier = coffre / "local" / "shards" / famille
    for shard in sorted(dossier.glob(f"*__{nu}*.jsonl.gz")) if dossier.is_dir() else ():
        reste = shard.name.split("__", 1)[1][len(nu):]
        if not (reste == ".jsonl.gz" or reste.startswith("__")):
            continue                                   # un autre ruban dont le nom commence pareil
        try:
            with gzip.open(shard, "rt", encoding="utf-8") as handle:
                for ligne in handle:
                    try:
                        deja_vus.add(identite(json.loads(ligne), famille))
                        charges += 1
                    except (ValueError, TypeError):
                        continue
        except OSError:
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
    # ANNONCE (22/11/2026) : cette etape ne disait rien avant d'avoir fini ; pendant 3 min 29 s
    # l'ecran est reste sur « ETAPE 3/3 » et le certificateur a paru bloque.
    _log(log, f"   [ticks] verification du magasin de ticks natifs (au plus {budget_s:.0f} s, reprise au "
              f"prochain passage)...")
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


class _ProgressionFichier:
    """Publie un battement par seconde et une projection explicite pendant les lectures longues."""

    def __init__(self, root: Path, *, batch_id: str, fichier: str, index: int, nombre: int,
                 total_source: int, source_terminee: int, taille_source: int,
                 debut_lot: float) -> None:
        self.root = root
        self.batch_id = batch_id
        self.fichier = fichier
        self.index = index
        self.nombre = nombre
        self.total_source = max(1, int(total_source))
        self.source_terminee = max(0, int(source_terminee))
        self.taille_source = max(0, int(taille_source))
        self.debut_lot = debut_lot
        self.phase = ""
        self.derniere_publication = 0.0
        self.echantillons: list[tuple[float, int]] = []

    def publier(self, phase: str, octets_lus: int, total_logique: int | None = None,
                lignes_lues: int | None = None) -> None:
        maintenant = time.monotonic()
        octets_lus = max(0, int(octets_lus))
        if phase != self.phase:
            self.phase = phase
            self.echantillons.clear()
            self.derniere_publication = 0.0
        elif self.echantillons and octets_lus < self.echantillons[-1][1]:
            self.echantillons.clear()
        # Écritures atomiques bornées : au plus une par seconde et par phase.
        if maintenant - self.derniere_publication < 1.0:
            return
        self.echantillons.append((maintenant, octets_lus))
        self.echantillons = [e for e in self.echantillons if maintenant - e[0] <= 5.0]
        debit_fichier = None
        if len(self.echantillons) >= 2:
            dt = self.echantillons[-1][0] - self.echantillons[0][0]
            if dt > 0:
                debit_fichier = max(0.0, (self.echantillons[-1][1] - self.echantillons[0][1]) / dt / 1048576)

        exact = isinstance(total_logique, int) and total_logique > 0
        fraction = min(1.0, octets_lus / total_logique) if exact else 0.0
        equiv_faits = min(self.total_source, self.source_terminee + int(self.taille_source * fraction))
        pct_confirme = min(100.0, self.source_terminee / self.total_source * 100.0)
        pct_estime = min(100.0, equiv_faits / self.total_source * 100.0)
        elapsed = max(0.0, maintenant - self.debut_lot)
        eta = None
        debit_lot = None
        if elapsed > 0 and equiv_faits > 0:
            debit_lot = equiv_faits / elapsed / 1048576
            eta = max(0.0, elapsed * (self.total_source - equiv_faits) / equiv_faits)
        _ecrire_statut(
            self.root,
            active=True,
            stage="CERTIFICATION",
            batch_id=self.batch_id,
            i=self.index,
            n=self.nombre,
            fichier=self.fichier,
            fichier_phase=phase,
            fichier_octets_lus=octets_lus,
            fichier_octets_total=total_logique if exact else None,
            fichier_pct=round(fraction * 100.0, 1) if exact else None,
            fichier_lignes_lues=lignes_lues,
            fichier_debit_mo_s=round(debit_fichier, 2) if debit_fichier is not None else None,
            octets_faits=self.source_terminee,
            octets_total=self.total_source,
            octets_estimes_faits=equiv_faits,
            pct_confirme=round(pct_confirme, 1),
            pct_estime=round(pct_estime, 1),
            pct=round(pct_estime, 1),
            debit_mo_s=round(debit_lot, 2) if debit_lot is not None else None,
            eta_s=round(eta, 1) if eta is not None else None,
            eta_updated_ms=int(time.time() * 1000) if eta is not None else None,
            progression_ms=int(time.time() * 1000),
        )
        self.derniere_publication = maintenant


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
                   help="scan RECURSIF du projet EN PLUS des dossiers de collecte (qui sont "
                        "toujours inventories, meme sans cette option)")
    # DANGER — NOM HISTORIQUE TROMPEUR. « reset-affichage » ne remet PAS un affichage à zéro :
    # il VIDE (tronque à 0 octet) les rubans de données vivants de runtime/data dont le scellage
    # a été vérifié par SHA. Le 19/11/2026 j'ai lancé ce drapeau en croyant nettoyer un simple
    # drapeau d'état ; seule l'interruption de la passe a évité la troncature. L'ancien nom est
    # CONSERVÉ (des appelants existent), mais l'alias explicite est désormais à préférer.
    p.add_argument("--reset-affichage", "--vider-flux-vivants-apres-scellage-verifie",
                   dest="reset_affichage", action="store_true",
                   help="DESTRUCTIF : vide (0 octet) les rubans vivants de runtime/data dont le "
                        "scellage est vérifié par SHA. Les données restent dans le coffre. "
                        "Ne PAS utiliser pour corriger un drapeau d'état.")
    p.add_argument("--now-ms", type=int, default=0, help="horloge injectable (tests)")
    p.add_argument("--famille", default="",
                   help="ne certifie que cette famille (ex. snapshot) ; vide = toutes")
    p.add_argument("--budget-ticks-s", type=float, default=45.0,
                   help="duree maximale (s) consacree a verifier le magasin de ticks natifs a ce passage")
    p.add_argument("--nom", action="append", default=[],
                   help="ne certifie que les fichiers de ce nom (ex. vault_fills_live.jsonl) ; répétable")
    p.add_argument("--boucle-s", type=float, default=0.0,
                   help="certifie EN CONTINU : une passe, puis attente de N secondes, sans fin "
                        "(0 = une seule passe, comportement d'origine). Sert a ne PAS perdre la "
                        "certification si une campagne est fermee brutalement.")
    p.add_argument("--recensement", action="store_true",
                   help="recense TOUT le projet, scelle les donnees oubliees, ecrit COUVERTURE_PROJET.json")
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
                   pct_confirme=0.0, pct_estime=0.0, octets_estimes_faits=0,
                   fichier_phase="RECENSEMENT", fichier_octets_lus=0,
                   fichier_octets_total=None, fichier_pct=None, fichier_lignes_lues=0,
                   fichier_debit_mo_s=None, eta_s=None, eta_updated_ms=None, debit_mo_s=0.0,
                   progression_ms=int(time.time() * 1000),
                   scan_entrees_vues=0, scan_donnees_trouvees=0, scan_dossiers_vus=0,
                   termine=False, code=None, resume=None)

    log_dir = root / LOG_RELDIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"certif_{batch_id}.log"
    etat_path = coffre / "SOURCES_TRAITEES.json"
    etat = _lire_json(etat_path) or {}

    # Un ENSEMBLE COMPACT, pas un `set` de tuples : l'identite d'un fill contient un hash de
    # 66 caracteres, et 27,5 millions d'entrees coutaient 8,9 Go -- de quoi faire tomber la machine
    # a 1,8 Go libres et menacer les collecteurs (18/11/2026, scellement arrete a 68,6 %).
    # Mesure : 323,2 octets/entree contre 16,4, soit x19,6. Meme reponse a `in` et `add`.
    deja_vus = EnsembleDIdentites()
    rubans_precharges: set = set()
    shards_fenetre: set = set()
    contenus_coffre: set = set()
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
        def progression_scan(mesure: dict[str, Any]) -> None:
            _ecrire_statut(root, active=True, termine=False, batch_id=batch_id, **mesure)

        fichiers = collecter_fichiers(root, tout=args.tout, log=log, progression_cb=progression_scan)
        if args.tout:
            # Le scan récursif saute ``research_lab`` (où vit la microstructure) : sans ce retour
            # explicite aux dossiers de collecte, le mode par défaut du lanceur ne la verrait jamais.
            deja = {str(f[0]) for f in fichiers}
            fichiers += [f for f in collecter_fichiers(root, tout=False, progression_cb=progression_scan)
                         if str(f[0]) not in deja]
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
            fichiers = [f for f in fichiers if f[0].name in set(args.nom)]
        recensement_avant = None
        a_prouver_gz: set = set()
        if args.recensement:
            # 23/11/2026 -- AUCUNE DONNEE OUBLIEE. Le recensement parcourt TOUT le projet avec ses propres regles
            # (pas cette decouverte-ci, sinon la couverture serait de 100 % par construction) ; ce qu'il trouve en
            # zone de collecte, de famille connue et absent du coffre (« A_SCELLER ») rejoint CE passage. Les
            # sessions anterieures a la regle de l'archiveur (« A_PROUVER ») ne sont jamais rescellees a l'aveugle.
            from hl_observer.datasets import recensement_donnees as RD
            recensement_avant = RD.recenser(root)
            deja = {_cle_fichier(f[0]) for f in fichiers}
            ajoutes = 0
            # 23/11 : les archives .gz « à prouver » aussi -- ce passage précharge les identités du coffre sur leur
            # période (_precharger_identites_fenetre) : seules leurs lignes absentes entrent, jamais un doublon
            a_prouver_gz = {_cle_fichier(root / a["fichier"]) for a in recensement_avant.get("a_prouver_gz", [])}
            for a in recensement_avant["a_sceller"] + recensement_avant.get("a_prouver_gz", []):
                chemin = root / a["fichier"]
                if _cle_fichier(chemin) not in deja and (not args.famille or a["famille"] == args.famille):
                    fichiers.append((chemin, a["famille"], a["source"]))
                    deja.add(_cle_fichier(chemin))
                    ajoutes += 1
            _log(log, f"   -> recensement du projet ({recensement_avant['duree_s']} s, "
                      f"{recensement_avant['fichiers_de_donnees']:,} fichiers de donnees, couverture "
                      f"{recensement_avant['couverture_pct']} %) : {ajoutes} fichier(s) oublie(s) ajoute(s) a ce passage.")
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
                       octets_total=total_octets, pct=0.0, pct_confirme=0.0,
                       pct_estime=0.0, octets_estimes_faits=0, pct_mode="CONFIRME_ET_FICHIER",
                       i=0, fichier_phase="PREPARATION", fichier_octets_lus=0,
                       fichier_octets_total=None, fichier_pct=None, fichier_lignes_lues=0,
                       fichier_debit_mo_s=None, eta_s=None, eta_updated_ms=None,
                       progression_ms=int(time.time() * 1000))
        for i, (source, famille, source_tag) in enumerate(fichiers, 1):
            try:
                src_etat = _etat_source(source)
            except OSError:
                continue
            # Les collecteurs continuent d'écrire pendant ce lot. L'horloge de validité
            # doit suivre la frontière du fichier capturée ici, pas le début du lot.
            # --now-ms reste une horloge fixe injectable pour les tests/replays.
            source_cutoff_ms = args.now_ms if args.now_ms else int(time.time() * 1000)
            taille = src_etat["taille"]
            if source.suffix == ".gz":
                taille_logique, exacte = _longueur_claire(source)
                total_logique = taille_logique if exacte else None
            else:
                total_logique = taille
            pct = faits_octets / total_octets * 100
            ecoule = time.monotonic() - t0
            eta = (ecoule * (total_octets - faits_octets) / faits_octets) if faits_octets else 0
            tete = f"[{pct:4.0f}% | {i}/{n} | reste ~{_fmt_duree(eta)}]"
            _log(log, f"{tete} {source.name}  ({taille / 1048576:.1f} Mo)")
            _ecrire_statut(root, active=True, stage="CERTIFICATION", i=i, n=n,
                           fichier=source.name, pct=round(pct, 1), pct_confirme=round(pct, 1),
                           pct_estime=round(pct, 1), octets_estimes_faits=faits_octets,
                           octets_faits=faits_octets, octets_total=total_octets,
                           eta_s=round(eta, 1) if faits_octets else None,
                           eta_updated_ms=int(time.time() * 1000) if faits_octets else None,
                           progression_ms=int(time.time() * 1000), batch_id=batch_id,
                           fichier_phase="PREPARATION", fichier_octets_lus=0,
                           fichier_octets_total=total_logique, fichier_pct=0.0,
                           fichier_lignes_lues=0, fichier_debit_mo_s=None,
                           debit_mo_s=round((faits_octets / 1048576) / ecoule, 2) if ecoule > 0 else 0.0)
            suivi_fichier = _ProgressionFichier(
                root, batch_id=batch_id, fichier=source.name, index=i, nombre=n,
                total_source=total_octets, source_terminee=faits_octets,
                taille_source=taille, debut_lot=t0,
            )

            def progression_hash_source(lus: int) -> None:
                suivi_fichier.publier("HASH SOURCE", lus, total_logique)

            cle_src = str(source.relative_to(root)) if root in source.parents else str(source)
            # Le hash et la lecture portent sur le même préfixe d'un ruban vivant.
            sha_src = (_sha256_contenu_source(source, progression=progression_hash_source)
                       if source.suffix == ".gz"
                       else _sha256_prefixe(source, taille, progression=progression_hash_source))
            ancien = etat.get(cle_src)
            version = version_certificateur(source.name)
            if ancien and ancien.get("sha256") == sha_src and int(ancien.get("certif_version", 1)) >= version:
                _log(log, "        deja certifie (inchange depuis la derniere fois) - je passe.")
                suivi_fichier.publier("DÉJÀ CERTIFIÉ", total_logique or taille, total_logique)
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
                    suivi_fichier.publier("DOUBLON VÉRIFIÉ", total_logique or taille, total_logique)
                    faits_octets += taille
                    continue
                # ``fin`` fige la lecture à la taille observée maintenant ; ``frontiere`` (dernier
                # saut de ligne) borne le préfixe réputé scellé : une ligne finale encore en
                # cours d'écriture sera relue complète au prochain passage.
                if source.suffix != ".gz":
                    fin = taille
                    frontiere = _fin_derniere_ligne(source, taille)
                    if "archive" in source.parts:
                        # Session ARCHIVÉE : ruban figé, rien n'y est en cours d'écriture. Sa dernière ligne
                        # est complète même sans retour final ; le préfixe scellé couvre tout ce qui est lu.
                        frontiere = taille
                    else:
                        # 23/11/2026 -- LA LECTURE S'ARRÊTE À LA FRONTIÈRE. Avant, elle allait jusqu'à `taille` et
                        # le préfixe réputé scellé s'arrêtait à la frontière : une dernière ligne complète mais
                        # sans retour était déposée MAINTENANT puis UNE SECONDE FOIS au passage suivant (doublon),
                        # et une ligne coupée en cours d'écriture partait en quarantaine pour rien. Trouvé par
                        # tests/test_archive_gzip_blocs.py. Ce que `_lire_lignes` promettait déjà : « une ligne
                        # encore en cours d'écriture n'est ni lue ni mise en quarantaine ».
                        fin = frontiere
                debut = _reprise_append_only(
                    source, frontiere, etat, version=version,
                    progression=lambda lus, total: suivi_fichier.publier(
                        "VÉRIFICATION PRÉFIXE", lus, total
                    ),
                )
                rattrapage = False
                if version > 1 and not debut and frontiere is not None:
                    # Règle de certification corrigée : je relis TOUT le ruban, mais les lignes
                    # déjà déposées par un lot précédent ne doivent pas l'être une seconde fois.
                    lots = _lots_ayant_scelle(source, sha_src, frontiere, etat)
                    if rattrapage_par_identite(source.name) and (lots or "archive" in source.parts):
                        # C'est l'IDENTITE qui a ete corrigee : tout ce que ce ruban a deja depose
                        # (tous lots) est precharge, et seules les lignes que l'ancienne identite
                        # confondait avec une autre sont deposees.
                        connues = _precharger_identites_du_ruban(coffre, source, famille, deja_vus, rubans_precharges)
                        rattrapage = True
                        _log(log, f"        rattrapage d'identite (regle v{version}) : {connues:,} ligne(s) deja au "
                                  f"coffre prechargee(s) ; seules les lignes confondues a tort sont deposees.")
                    elif lots:
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
                # 23/11/2026 (soir) -- RUBAN REECRIT. `tools/backfill_vault_fills.py` reecrit vault_episodes.jsonl EN
                # ENTIER a chaque collecte (write_text) : son debut ne correspond jamais au prefixe scelle, et chaque
                # passage le rescellait en entier -- 60 % des lignes fills_backfill du coffre etaient en double (mesure :
                # tools/auditer_doublons_coffre.py). Un ruban en clair qui n'est PAS remis a zero apres scellement
                # (hors FLUX_VIVANTS) et dont le prefixe n'est plus reconnu est traite comme une rotation.
                if (not debut and not rattrapage and (source.suffix == ".gz" or source.name not in FLUX_VIVANTS)
                        and (_cle_fichier(source) in a_prouver_gz or _prefixes_connus(source, etat, version))):
                    # 23/11/2026 -- ROTATION D'UN RUBAN SCELLE AU FIL DE L'EAU, PREFIXE NON RECONNU. Sans cela,
                    # elle se rescellait EN ENTIER (vu le 23/11 : 148 526 micro-BBO et 784 648 BBO redeposes). Les
                    # identites du coffre sur SA periode sont prechargees : seules les lignes absentes entrent.
                    connues = _precharger_identites_fenetre(coffre, source, famille, contenus_coffre, shards_fenetre)
                    if connues is None:
                        _log(log, "        [!] archive a prouver sans aucun horodatage lisible : je ne depose RIEN "
                                  "(sinon elle entrerait en entier) ; elle reste a prouver.")
                        faits_octets += taille
                        continue
                    _log(log, f"        rotation d'un ruban deja scelle, prefixe non reconnu : {connues:,} identite(s) "
                              f"du coffre prechargee(s) sur sa periode ; seules les lignes absentes sont deposees.")
                if debut:
                    _log(log, f"        ruban deja certifie jusqu'a {debut / 1048576:.1f} Mo : "
                              f"je ne scelle que la suite.")
            entree = sceller_fichier(
                source, coffre, batch_id, source_tag=source_tag, famille=famille,
                now_ms=source_cutoff_ms, deja_vus=deja_vus, log=log, prefixe=tete,
                debut_octets=debut, fin_octets=fin, rattrapage=rattrapage,
                expected_source_sha256=sha_src, source_snapshot_octets=taille,
                contenus_coffre=contenus_coffre,
                progression_cb=suivi_fichier.publier,
            )
            faits_octets += taille
            if entree is not None:
                entree["source_cutoff_ms"] = source_cutoff_ms
                entrees_manifeste.append(entree)
                st = entree.get("stats", {})
                total.entrees += st.get("entrees", 0)
                total.passes += st.get("passes", 0)
                total.repares += st.get("repares", 0)
                total.quarantaine += st.get("quarantaine", 0)
                total.doublons += st.get("doublons", 0)
                for raison, count in st.get("raisons", st.get("raisons_top", {})).items():
                    total.raisons[raison] = total.raisons.get(raison, 0) + count
                if entree.get("deposes") and source.name in FLUX_VIVANTS and source.parent.name == "data":
                    scelles_pour_reset.append(source)
            etat[cle_src] = {"sha256": sha_src, **src_etat, "batch": batch_id, "certif_version": version}
            # Historique des préfixes scellés sous ce chemin : quand le ruban actif repart de zéro
            # (rotation), l'ancienne identité reste connue pour reconnaître l'archive tournante.
            historique = list((ancien or {}).get("prefixes_precedents") or [])
            if ancien and ancien.get("prefixe_octets") and ancien.get("prefixe_sha256"):
                historique.insert(0, [int(ancien["prefixe_octets"]), str(ancien["prefixe_sha256"])])
            if historique:
                # 23/11/2026 -- 8 -> PREFIXES_GARDES. Avec 8, un certificateur bloque plus d'une heure laissait
                # s'empiler plus de 8 rotations : la plus ancienne n'etait plus reconnue et se rescellait EN
                # ENTIER (2 rotations micro_bbo du 23/11 : 49 086 lignes deja au coffre, redeposees).
                etat[cle_src]["prefixes_precedents"] = historique[:PREFIXES_GARDES]
            if fin is not None:
                # identité du préfixe scellé : base de la reprise incrémentale au prochain passage
                etat[cle_src]["prefixe_octets"] = frontiere
                etat[cle_src]["prefixe_sha256"] = _sha256_prefixe(
                    source, frontiere,
                    progression=lambda lus: suivi_fichier.publier("HASH PRÉFIXE FINAL", lus, frontiere),
                )
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

        # DESTRUCTIF, fail-closed : ne vide QUE des rubans dont le shard scellé a été vérifié
        # par SHA. On l'annonce fort dans le log : c'est une troncature de données vivantes,
        # pas un réglage d'affichage (cf. le nom historique trompeur du drapeau).
        if args.reset_affichage and scelles_pour_reset:
            _log(log, f"  [RESET] DESTRUCTIF : {len(scelles_pour_reset)} ruban(s) vivant(s) vont "
                      f"etre VIDES (0 octet) ; leurs donnees sont deja scellees et verifiees.")
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
        if args.recensement:
            # couverture APRES ce passage : ce qui vient d'etre scelle n'est plus « oublie »
            from hl_observer.datasets import recensement_donnees as RD
            apres = RD.recenser(root)
            apres["avant_ce_passage"] = {k: recensement_avant[k] for k in ("couverture_pct", "totaux")}                 if recensement_avant else None
            RD.ecrire_rapport(root, apres)
            _log(log, "")
            _log(log, f"  COUVERTURE DU PROJET : {apres['couverture_pct']} % des {apres['fichiers_de_donnees']:,} "
                      f"fichiers de donnees ({'100 %' if apres['cent_pour_cent'] else 'reste a traiter'}) -> "
                      f"runtime/coffre_certifie/COUVERTURE_PROJET.json")
            for verdict in RD.BLOQUANTS:
                n = apres["totaux"].get(verdict, {}).get("fichiers", 0)
                if n:
                    _log(log, f"     {verdict:<22} {n:>6,} fichier(s)")
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
            # 23/11/2026 : une donnée EXTERNE (Ironflow, Tardis) le dit dans l'index, pas seulement ligne par
            # ligne -- un lecteur qui choisit ses shards par famille la voit sans décompresser.
            **({"provenance": ORIGINE_EXTERNE, "source_tag": str(entree.get("source_tag"))}
               if str(entree.get("source_tag") or "").startswith(PREFIXE_SOURCE_EXTERNE) else {}),
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


def _racine_des_args(args: list[str]) -> Path:
    """La racine demandee sur la ligne de commande, pour poser le verrou au bon endroit.

    `main()` la lit avec argparse, mais le verrou se prend AVANT d'entrer dans `main()` : deux
    analyses de la meme option, c'est le prix d'un verrou qui protege aussi la boucle continue.
    """
    for i, a in enumerate(args):
        if a == "--root" and i + 1 < len(args):
            return Path(args[i + 1])
        if a.startswith("--root="):
            return Path(a.split("=", 1)[1])
    return ROOT


#: 23/11/2026 -- COMPRESSION INTELLIGENTE (demande de l'operateur : « tout doit etre compresse sans perte » ;
#: « le certificateur doit savoir compresser intelligemment si besoin »). Mesure du jour : ~80 Go de rubans EN CLAIR
#: dans les sessions archivees, que plus personne n'ecrit. Seuls ces dossiers de rubans FIGES sont compresses : un
#: ruban qu'un collecteur ou le backfill ecrit encore ne l'est jamais (son ecrivain relit sa fin pour reprendre).
DOSSIERS_COMPRESSIBLES = (Path("runtime") / "archive",)
#: prefixes scelles gardes par chemin pour reconnaitre une rotation (voir l'historique dans main)
PREFIXES_GARDES = 64
COMPRESSION_TAILLE_MIN = 256 * 1024
COMPRESSION_RAPPORT = Path("runtime") / "coffre_certifie" / "COMPRESSION.json"


def _compresser_un(chemin: str, progression_path: str | None = None) -> dict[str, Any]:
    """Travailleur (processus separe) : un ruban -> archive gzip par blocs VERIFIEE, puis retrait du clair."""
    from hl_observer.datasets import archive_gzip_blocs as A
    p = Path(chemin)
    avant = p.stat().st_size

    def progression(phase: str, faits: int, total: int) -> None:
        if not progression_path:
            return
        path = Path(progression_path)
        temporaire = path.with_suffix(".partial")
        try:
            temporaire.write_text(json.dumps({
                "phase": phase, "octets_faits": int(faits), "octets_total": int(total),
                "updated_ms": int(time.time() * 1000),
            }), encoding="utf-8")
            temporaire.replace(path)
        except OSError:
            pass  # télémetrie best-effort : elle ne doit jamais interrompre la compression

    try:
        idx = A.remplacer_par_archive(p, progression=progression if progression_path else None)
        return {"fichier": chemin, "octets_clair": avant, "octets_archive": idx["octets_archive"],
                "sha256_clair": idx["sha256_clair"], "statut": "COMPRESSE"}
    except Exception as exc:  # noqa: BLE001 - chaque refus est NOMME dans le rapport, la source reste intacte
        return {"fichier": chemin, "octets_clair": avant, "statut": f"CONSERVE_EN_CLAIR : {type(exc).__name__}: {exc}"}


def compresser_rubans_figes(root: Path, *, age_min_s: float = 600.0, travailleurs: int = 3,
                            maintenant: float | None = None,
                            progression_cb: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Compresse SANS PERTE (gzip par blocs indexe, relecture integrale verifiee) les rubans en clair figes des
    dossiers ``DOSSIERS_COMPRESSIBLES``. Le certificateur relit ces archives (prefixe du flux decompresse) et le
    lecteur de preuves y retrouve chaque ligne a son offset d'origine. Rend un bilan ; n'echoue jamais en silence."""
    from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
    import shutil
    from uuid import uuid4

    t = time.time() if maintenant is None else maintenant
    candidats: list[Path] = []
    tailles: dict[str, int] = {}
    ignores: dict[str, int] = {}
    scan_count = 0
    dernier_scan = 0.0

    def publier(champs: dict[str, Any]) -> None:
        if progression_cb is not None:
            try:
                progression_cb(champs)
            except Exception:  # noqa: BLE001 — diagnostic best-effort
                pass

    publier({"stage": "COMPRESSION_SCAN", "compression_scannes": 0,
             "compression_candidats": 0, "compression_octets_total": 0,
             "compression_faits": 0, "compression_octets_traites": 0,
             "compression_octets_compressees": 0, "compression_en_traitement": 0,
             "compression_actifs": [], "compression_pct_estime": None,
             "eta_s": None, "eta_updated_ms": None})
    for base in DOSSIERS_COMPRESSIBLES:
        # Parcours progressif : trier tout le rglob avant la première mise à jour rendait
        # l'écran muet pendant l'inventaire des gros répertoires. L'ordre final est stabilisé
        # plus bas pour les reçus; l'ordre du scan n'a aucune incidence sur l'admission.
        for f in (root / base).rglob("*.jsonl") if (root / base).is_dir() else ():
            scan_count += 1
            try:
                st = f.stat()
            except OSError:
                st = None
            if st is not None:
                if st.st_size < COMPRESSION_TAILLE_MIN:
                    ignores["trop_petit"] = ignores.get("trop_petit", 0) + 1
                elif t - st.st_mtime < age_min_s:
                    ignores["modifie_recemment"] = ignores.get("modifie_recemment", 0) + 1
                elif f.with_name(f.name + ".gz").exists():
                    ignores["archive_homonyme_deja_presente"] = ignores.get("archive_homonyme_deja_presente", 0) + 1
                else:
                    candidats.append(f)
                    tailles[str(f)] = int(st.st_size)
            maintenant = time.monotonic()
            if maintenant - dernier_scan >= 1.0:
                publier({"stage": "COMPRESSION_SCAN", "compression_scannes": scan_count,
                         "compression_candidats": len(candidats),
                         "compression_octets_total": sum(tailles.values()),
                         "compression_en_traitement": 0, "compression_actifs": []})
                dernier_scan = maintenant
    publier({"stage": "COMPRESSION_SCAN", "compression_scannes": scan_count,
             "compression_candidats": len(candidats),
             "compression_octets_total": sum(tailles.values()),
             "compression_en_traitement": 0, "compression_actifs": []})

    resultats: list[dict[str, Any]] = []
    if candidats:
        progression_dir = root / COFFRE_RELDIR / ".compression-live" / uuid4().hex
        progression_dir.mkdir(parents=True, exist_ok=True)
        tries: list[tuple[float, float]] = []
        dernier_etat = 0.0
        dernier_travail = -1.0
        total_source = sum(tailles.values())
        total_travail = float(total_source)
        ordre = sorted(candidats, key=lambda p: -tailles[str(p)])
        try:
            with ProcessPoolExecutor(max_workers=max(1, int(travailleurs))) as pool:
                futures = {}
                progression_paths: dict[str, Path] = {}
                for index, candidat in enumerate(ordre):
                    progress_path = progression_dir / f"{index:06d}.json"
                    progression_paths[str(candidat)] = progress_path
                    future = pool.submit(_compresser_un, str(candidat), str(progress_path))
                    futures[future] = candidat
                pending = set(futures)
                while pending:
                    finis, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                    for future in finis:
                        candidat = futures[future]
                        try:
                            resultat = future.result()
                        except Exception as exc:  # le fichier source reste en clair si le worker échoue
                            resultat = {"fichier": str(candidat), "octets_clair": tailles[str(candidat)],
                                        "statut": f"CONSERVE_EN_CLAIR : worker {type(exc).__name__}: {exc}"}
                        resultats.append(resultat)
                        etat = "ok " if resultat["statut"] == "COMPRESSE" else "!! "
                        print(f"[coffre] compression {etat}{Path(resultat['fichier']).name} : "
                              f"{resultat['octets_clair'] / 1e6:,.0f} Mo -> "
                              f"{(resultat.get('octets_archive') or resultat['octets_clair']) / 1e6:,.0f} Mo  "
                              f"{'' if etat == 'ok ' else resultat['statut']}", flush=True)

                    maintenant = time.monotonic()
                    if maintenant - dernier_etat < 0.8 and pending:
                        continue
                    travail = sum(float(tailles.get(r["fichier"], r["octets_clair"])) for r in resultats)
                    actifs: list[str] = []
                    for future in pending:
                        candidat = futures[future]
                        path = progression_paths[str(candidat)]
                        try:
                            mesure = json.loads(path.read_text(encoding="utf-8"))
                            total = max(1, int(mesure.get("octets_total") or tailles[str(candidat)]))
                            faits = min(total, max(0, int(mesure.get("octets_faits") or 0)))
                            phase = str(mesure.get("phase") or "")
                            fraction = (0.5 * faits / total if phase == "COMPRESSION_SOURCE"
                                        else 0.5 + 0.5 * faits / total if phase == "VERIFICATION_ARCHIVE" else 0.0)
                            travail += tailles[str(candidat)] * min(1.0, fraction)
                            if phase:
                                actifs.append(f"{candidat.name} [{phase.lower().replace('_', ' ')}]")
                            else:
                                actifs.append(candidat.name)
                        except (OSError, ValueError, TypeError):
                            actifs.append(candidat.name)
                    travail = min(float(total_source), travail)
                    progression_nouvelle = travail > dernier_travail
                    if progression_nouvelle:
                        tries.append((maintenant, travail))
                        tries = [e for e in tries if maintenant - e[0] <= 8.0]
                        dernier_travail = travail
                    debit = eta = None
                    if len(tries) >= 2:
                        dt = tries[-1][0] - tries[0][0]
                        delta = tries[-1][1] - tries[0][1]
                        if dt > 0 and delta > 0:
                            debit = delta / dt / 1048576
                            eta = max(0.0, (total_source - travail) / (delta / dt))
                    pct = 100.0 * travail / total_source if total_source else 100.0
                    mesure_live = {
                        "stage": "COMPRESSION", "compression_scannes": scan_count,
                        "compression_candidats": len(candidats), "compression_faits": len(resultats),
                        "compression_octets_total": total_source,
                        "compression_octets_traites": sum(int(r["octets_clair"]) for r in resultats),
                        "compression_octets_compressees": sum(int(r["octets_clair"]) for r in resultats
                                                               if r["statut"] == "COMPRESSE"),
                        "compression_en_traitement": len(pending), "compression_actifs": actifs,
                        "compression_pct_estime": round(pct, 1), "pct": round(pct, 1),
                        "compression_debit_mo_s": round(debit, 2) if debit is not None else None,
                    }
                    if progression_nouvelle:
                        mesure_live["progression_ms"] = int(time.time() * 1000)
                        mesure_live["eta_s"] = round(eta, 1) if eta is not None else None
                        mesure_live["eta_updated_ms"] = int(time.time() * 1000) if eta is not None else None
                    publier(mesure_live)
                    dernier_etat = maintenant
            resultats.sort(key=lambda r: r["fichier"])
        finally:
            shutil.rmtree(progression_dir, ignore_errors=True)
    faits = [r for r in resultats if r["statut"] == "COMPRESSE"]
    bilan = {"genere_ms": int(time.time() * 1000), "candidats": len(candidats), "compresses": len(faits),
             "conserves_en_clair": [r for r in resultats if r["statut"] != "COMPRESSE"],
             "octets_avant": sum(r["octets_clair"] for r in faits),
             "octets_apres": sum(r["octets_archive"] for r in faits), "ignores": ignores,
             "regle": "gzip par blocs indexe, decompression integrale verifiee (taille + SHA-256) avant retrait du clair"}
    historique = _lire_json(root / COMPRESSION_RAPPORT) or {"passages": []}
    historique["passages"] = (historique.get("passages") or [])[-49:] + [
        {**bilan, "fichiers": [{k: r[k] for k in ("fichier", "octets_clair", "octets_archive", "sha256_clair")}
                               for r in faits]}]
    _ecrire_json_atomique(root / COMPRESSION_RAPPORT, historique)
    publier({"stage": "COMPRESSION_TERMINEE", "compression_scannes": scan_count,
             "compression_candidats": len(candidats), "compression_faits": len(resultats),
             "compression_octets_total": sum(tailles.values()),
             "compression_octets_traites": sum(int(r["octets_clair"]) for r in resultats),
             "compression_octets_compressees": sum(int(r["octets_clair"]) for r in faits),
             "compression_en_traitement": 0, "compression_actifs": [],
             "compression_pct_estime": 100.0, "pct": 100.0,
             "eta_s": 0.0, "eta_updated_ms": int(time.time() * 1000),
             "progression_ms": int(time.time() * 1000)})
    print(f"[coffre] compression : {len(faits)} ruban(s), {bilan['octets_avant'] / 1e9:.2f} Go -> "
          f"{bilan['octets_apres'] / 1e9:.2f} Go ; conserves en clair : {len(bilan['conserves_en_clair'])} ; "
          f"ignores : {ignores}", flush=True)
    return bilan


def _extraire_compression(args: list[str]) -> tuple[list[str], str, float]:
    """Retire ``--compresser`` / ``--compresser-seulement`` / ``--compresser-age-min N`` de la ligne passee a main."""
    mode, age, reste, i = "", 10.0, [], 0
    while i < len(args):
        if args[i] in ("--compresser", "--compresser-seulement"):
            mode = args[i][2:]
        elif args[i] == "--compresser-age-min" and i + 1 < len(args):
            age = float(args[i + 1])
            i += 1
        else:
            reste.append(args[i])
        i += 1
    return reste, mode, age


def _aiguiller(nettoye: list[str], intervalle: float) -> int:
    """Une passe unique, ou la boucle continue. Separe du verrou pour etre appelable sans lui."""
    nettoye, compression, age_min = _extraire_compression(nettoye)
    if compression:
        code = 0 if compression == "compresser-seulement" else main(nettoye)
        from uuid import uuid4
        root = _racine_des_args(nettoye).resolve()
        batch_id = f"{_horodate()}_compression_{uuid4().hex[:8]}"
        _ecrire_statut(root, active=True, termine=False, stage="COMPRESSION_SCAN",
                       batch_id=batch_id, pct=0.0, pct_confirme=0.0, pct_estime=0.0,
                       i=0, n=0, fichier="", fichier_phase="", fichier_octets_lus=0,
                       fichier_octets_total=None, fichier_pct=None, fichier_lignes_lues=0,
                       fichier_debit_mo_s=None, octets_faits=0, octets_total=0,
                       compression_scannes=0, compression_candidats=0, compression_faits=0,
                       compression_octets_total=0, compression_octets_traites=0,
                       compression_octets_compressees=0, compression_en_traitement=0,
                       compression_actifs=[], compression_pct_estime=None,
                       compression_debit_mo_s=None, eta_s=None, eta_updated_ms=None,
                       progression_ms=int(time.time() * 1000), code=None)

        def publier_compression(mesure: dict[str, Any]) -> None:
            champs = {k: v for k, v in mesure.items() if k != "progression_ms"}
            champs.update(active=True, termine=False, batch_id=batch_id)
            if mesure.get("progression_ms") is not None:
                champs["progression_ms"] = mesure["progression_ms"]
            _ecrire_statut(root, **champs)

        try:
            bilan = compresser_rubans_figes(root, age_min_s=60.0 * age_min,
                                            progression_cb=publier_compression)
        except KeyboardInterrupt:
            _ecrire_statut(root, active=False, termine=True, code=130,
                           stage="COMPRESSION INTERROMPUE — source conservée si non vérifiée",
                           eta_s=None, compression_en_traitement=0)
            print("[coffre] Compression interrompue proprement ; les sources non vérifiées restent en clair.",
                  flush=True)
            return 130
        code_final = code if code else (1 if bilan["conserves_en_clair"] else 0)
        _ecrire_statut(root, active=False, termine=True, code=code_final,
                       stage="TERMINE" if code_final == 0 else "COMPRESSION/SCELLEMENT À CORRIGER",
                       pct=100.0, compression_pct_estime=100.0,
                       compression_faits=int(bilan["compresses"] + len(bilan["conserves_en_clair"])),
                       compression_candidats=int(bilan["candidats"]),
                       compression_en_traitement=0, compression_actifs=[],
                       eta_s=0.0, eta_updated_ms=int(time.time() * 1000),
                       progression_ms=int(time.time() * 1000))
        return code_final
    if intervalle <= 0:
        try:
            return main(nettoye)
        except KeyboardInterrupt:
            # 16/11 — la passe UNIQUE n'attrapait pas le Ctrl+C : elle rendait une pile d'erreur
            # (vue dans coffre_session.log du 12/11, remontee en « erreur grave » par le rapport).
            # Le scellage est INCREMENTAL : tout ce qui est deja scelle le reste, et la passe
            # suivante reprend au dernier saut de ligne complet. Il n'y a rien a reparer, juste a
            # le dire — exigence de Florent : un Ctrl+C ne doit jamais perdre de donnee.
            print("[coffre] Ctrl+C — arret propre. Tout ce qui etait deja scelle le RESTE ; "
                  "la passe suivante reprend ou celle-ci s'arrete.", flush=True)
            return 130
    print(f"[coffre] certification EN CONTINU toutes les {intervalle / 60:.0f} min. "
          "Ctrl+C pour arreter.", flush=True)
    try:
        return boucler(nettoye, intervalle)
    except KeyboardInterrupt:
        print("[coffre] arret demande — la derniere passe complete reste certifiee.", flush=True)
        return 130


def _point_d_entree(argv: list[str] | None = None, *, verrouiller: bool = True) -> int:
    """Aiguille entre une passe unique et la boucle, en retirant `--boucle-s` de la ligne passee.

    ``verrouiller=False`` pour les tests qui verifient l'AIGUILLAGE des arguments : sans racine
    explicite le verrou se poserait dans l'arbre reel du projet, et un test interrompu y laisserait
    un verrou qui bloquerait la certification de la campagne pendant 6 h (defaut vu le 16/11, la
    suite de tests l'a attrape le jour meme).
    """
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
    if not verrouiller:
        return _aiguiller(nettoye, intervalle)
    verrou = _racine_des_args(nettoye) / VERROU_RELPATH
    obtenu, mot = verrou_pid.prendre(verrou, quoi="un scellage")
    if not obtenu:
        # Rendre 0 et non une erreur : rien n'a echoue. Un autre scellage couvre les memes
        # octets a cet instant, il est INCREMENTAL, et la campagne relance celui-ci dans 30 min.
        # Rougir ici ferait croire a une panne du coffre a chaque passage superpose.
        print(f"[coffre] RIEN A SCELLER MAINTENANT : {mot}. Le scellage en cours couvre les "
              "memes octets et reprend ou il s'arrete.", flush=True)
        return 0
    if mot:
        print(f"[coffre] {mot}", flush=True)
    try:
        return _aiguiller(nettoye, intervalle)
    finally:
        verrou_pid.rendre(verrou)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_point_d_entree())
