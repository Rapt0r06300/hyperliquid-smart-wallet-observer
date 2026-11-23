"""Recensement de TOUTES les données du projet : chaque fichier de données reçoit UN verdict, rien n'est oublié.

Demande de l'opérateur (23/11/2026) : « le certificateur n'oublie aucune donnée dans l'ensemble du dossier du
projet », avec un scan rapide. Ce module ne réutilise PAS la découverte du certificateur (``collecter_fichiers``) :
une couverture mesurée par l'outil qu'elle juge serait de 100 % par construction.

Méthode :
1. Une table de ZONES, apprise de l'inventaire réel du 23/11 (9,2 M fichiers, 87 241 dossiers) : chaque dossier de
   données y a sa règle. Les MAGASINS auto-vérifiés (ticks, SAFE, coffre, recovery…) et l'ENVIRONNEMENT (venv,
   Python embarqué) ne sont pas parcourus fichier par fichier : ils sont couverts par leur propre manifeste. Le
   balayage passe ainsi de ~9 M à ~0,15 M fichiers.
2. Tout fichier de données hors de ces arbres reçoit un verdict :
   ``SCELLE`` (le coffre en détient tout), ``EN_COURS`` (ruban vivant, la fin attend le passage suivant),
   ``A_SCELLER`` (zone de collecte, famille connue, rien au coffre), ``EXTERNE_VALIDE`` / ``EXTERNE_NON_MANIFESTE``,
   ``PAR_CONCEPTION`` (dérivé, rapport, quarantaine, journal… avec son motif) ou ``INCONNU``.
3. 100 % = aucun ``INCONNU``, aucun ``A_SCELLER``, aucun ``EXTERNE_NON_MANIFESTE``, balayage non tronqué.
Lecture seule : ce module n'écrit que son rapport. Les ``A_SCELLER`` sont rendus au certificateur, qui les scelle.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from hl_observer.datasets.coffre_certifie import detecter_famille, motif_non_certifie, sniffer_famille
from hl_observer.ops.echec_silencieux import noter as _noter_echec

EXTENSIONS_DONNEES = (".jsonl", ".jsonl.gz", ".ndjson", ".csv", ".csv.gz", ".parquet", ".lz4", ".zst", ".npz",
                      ".feather", ".arrow", ".sqlite", ".db")
RAPPORT = Path("runtime") / "coffre_certifie" / "COUVERTURE_PROJET.json"
ETAT_COFFRE = Path("runtime") / "coffre_certifie" / "SOURCES_TRAITEES.json"
INDEX_COFFRE = Path("runtime") / "coffre_certifie" / "LOCAL_INDEX.json"
PREUVES = Path("runtime") / "coffre_certifie" / "PREUVES_SCELLEMENT.json"


@dataclass(frozen=True)
class Zone:
    motif: str          # préfixe de chemin relatif (posix), « * » = un segment quelconque
    genre: str          # COLLECTE | MAGASIN | EXTERNE | DERIVE | QUARANTAINE | JOURNAL | DOC | ENVIRONNEMENT
    pourquoi: str


#: Ordre = priorité (le motif le plus spécifique d'abord). Apprise de l'inventaire du 23/11 ; un dossier absent de
#: cette table qui contient des données sort en INCONNU : c'est ainsi qu'on apprend une règle, jamais en silence.
ZONES: tuple[Zone, ...] = (
    Zone("runtime/data/market_ticks", "MAGASIN", "magasin de ticks auto-manifesté (tools/verifier_store_ticks.py)"),
    Zone("runtime/coffre_certifie/local", "MAGASIN", "le coffre lui-même (shards scellés, SHA-256 à l'index)"),
    Zone("runtime/coffre_certifie/quarantine", "QUARANTAINE", "lignes écartées par le certificateur, avec raison"),
    Zone("runtime/coffre_certifie", "JOURNAL", "journaux et états du certificateur (CERTIF_JOURNAL…)"),
    Zone("runtime/recovery", "MAGASIN", "copies de restauration SAFE (AlinaSync)"),
    Zone("runtime/sauvegardes", "MAGASIN", "sauvegardes du catalogue"),
    Zone("runtime/research_lab/copy_vault_safe", "MAGASIN", "corpus SAFE déballé pour le labo (vérifié au déballage)"),
    Zone("runtime/research_lab/archives", "MAGASIN", "archives du labo de recherche (copies de rubans déjà scellés)"),
    Zone("datasets", "MAGASIN", "jeux SAFE / rejetés / quarantaine du pipeline SAFE"),
    Zone("catalog", "MAGASIN", "catalogue SAFE (campagnes, Git est la source)"),
    Zone("runtime/research_lab/data/goal2_cache", "DERIVE", "caches de recherche calculés depuis le coffre"),
    Zone("runtime/data/sessions", "DERIVE", "sessions de démonstration portables (fixtures de fumée)"),
    Zone("runtime/history/ironflow", "EXTERNE", "source externe brute, listée et vérifiée dans MANIFESTE.json"),
    Zone("runtime/history/tardis", "EXTERNE", "source externe brute, listée et vérifiée dans MANIFESTE.json"),
    Zone("runtime/history/hydromancer", "EXTERNE", "source externe brute (Reservoir HF), listée dans MANIFESTE.json"),
    Zone("runtime/archive/*", "COLLECTE", "rubans des sessions archivées à l'arrêt des collecteurs"),
    Zone("runtime/data", "COLLECTE", "rubans des collecteurs (vivants)"),
    Zone("runtime/history", "COLLECTE", "rubans des backfills (vivants) et rubans externes de transit"),
    Zone("runtime/research_lab/data", "COLLECTE", "microstructure et caches du labo"),
    Zone("runtime/reports", "DERIVE", "rapports et sorties calculées du labo"),
    Zone("runtime/labo_*", "DERIVE", "espaces de travail du labo (tranches)"),
    Zone("runtime/replay", "DERIVE", "rejeux calculés"),
    Zone("runtime/codex_research", "DERIVE", "recherches calculées"),
    Zone("runtime/research", "DERIVE", "recherches calculées"),
    Zone("runtime/research_lab", "DERIVE", "registres et sorties du labo de recherche"),
    Zone("runtime/roadmap", "DERIVE", "feuille de route et ses sauvegardes"),
    Zone("runtime/models", "DERIVE", "modèles entraînés"),
    Zone("runtime/ml", "DERIVE", "apprentissage"),
    Zone("runtime/learning", "DERIVE", "apprentissage"),
    Zone("runtime/cvprobe*", "DERIVE", "sondes ponctuelles"),
    Zone("runtime/logs", "JOURNAL", "journaux"),
    Zone("logs", "JOURNAL", "journaux"),
    Zone("docs", "DOC", "documentation"),
    Zone("config", "DOC", "configuration"),
    Zone("data", "DOC", "données d'exemple versionnées"),
    Zone("tests", "DOC", "jeux de test"),
    Zone("runtime/clean-test-venv", "ENVIRONNEMENT", "environnement Python de test"),
    Zone("tools/python", "ENVIRONNEMENT", "Python embarqué"),
    Zone(".venv", "ENVIRONNEMENT", "environnement Python"),
    Zone("venv", "ENVIRONNEMENT", "environnement Python"),
    Zone(".git", "ENVIRONNEMENT", "dépôt Git"),
    Zone("node_modules", "ENVIRONNEMENT", "dépendances"),
)
#: fichiers de FONCTIONNEMENT des collecteurs, posés dans une zone de collecte : des plans, pas des observations
OPERATIONNELS = {
    "poll_cadence_plan.ndjson": "plan de cadence du sondage des leaders (slots_userfills)",
    "userfills_pages.ndjson": "affectation des vaults aux pages du sondage (slots_userfills)",
}
#: 11/11/2026 12:20:45 (heure de Paris) -- commit 391efb93b1a3 : depuis, `tools/archiver_tapes.py` ne déplace un ruban
#: dans `runtime/archive/session_<horodate locale>` QUE si l'état du coffre connaît exactement son contenu (SHA-256
#: du fichier entier). Une session postérieure est donc scellée PAR CONSTRUCTION, même quand l'état ne garde plus
#: la trace (8 préfixes par chemin). Antérieure et sans trace : « A_PROUVER », jamais rescellée à l'aveugle.
REGLE_ARCHIVEUR_DEPUIS = "20261111_122045"

#: segments élagués où qu'ils soient
ELAGUES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", "site-packages"}
NON_PARCOURUS = {"MAGASIN", "ENVIRONNEMENT"}
#: verdicts qui empêchent les 100 %
BLOQUANTS = ("INCONNU", "A_SCELLER", "A_PROUVER", "EXTERNE_NON_MANIFESTE")


def _correspond(rel: str, motif: str) -> bool:
    a, b = rel.split("/"), motif.split("/")
    if len(a) < len(b):
        return False
    for x, m in zip(a, b):
        if m == "*":
            continue
        if m.endswith("*"):
            if not x.startswith(m[:-1]):
                return False
        elif x != m:
            return False
    return True


def zone_de(rel: str) -> Zone | None:
    for z in ZONES:
        if _correspond(rel, z.motif):
            return z
    return None


def est_donnee(nom: str) -> bool:
    n = nom.lower()
    return any(n.endswith(e) for e in EXTENSIONS_DONNEES)


def _cle(rel: str) -> str:
    return rel.replace("\\", "/").lower()


def _tronc(nom: str) -> str:
    import re
    base = nom[:-3] if nom.endswith(".gz") else nom
    base = base[:-6] if base.endswith(".jsonl") else base
    return re.sub(r"_\d{10,}$", "", base)


class Coffre:
    """Ce que le certificateur dit avoir scellé : clés exactes et préfixes connus par ruban logique."""

    def __init__(self, root: Path) -> None:
        try:
            etat = json.loads((root / ETAT_COFFRE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            etat = {}
        self.par_cle = {_cle(k): v for k, v in etat.items() if isinstance(v, dict)}
        self.prefixes: dict[str, set[tuple[int, str]]] = {}
        for k, v in self.par_cle.items():
            ens = self.prefixes.setdefault(_tronc(PurePosixPath(k).name), set())
            if v.get("prefixe_octets") and v.get("prefixe_sha256"):
                ens.add((int(v["prefixe_octets"]), str(v["prefixe_sha256"])))
            for p in v.get("prefixes_precedents") or []:
                if isinstance(p, list) and len(p) == 2 and p[0] and p[1]:
                    ens.add((int(p[0]), str(p[1])))


def _sha256_fichier(chemin: Path) -> str:
    h = hashlib.sha256()
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(4 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def verdict_scellement(chemin: Path, rel: str, taille: int, coffre: Coffre, *, verifier_sha: bool) -> tuple[str, str]:
    """(verdict, détail) d'un ruban de collecte au regard de l'état du certificateur."""
    e = coffre.par_cle.get(_cle(rel))
    nom = chemin.name
    if nom.endswith(".gz"):
        idx = chemin.with_name(nom + ".idx.json")
        if idx.is_file():                                      # archive par blocs : identité exacte sans décompresser
            try:
                d = json.loads(idx.read_text(encoding="utf-8"))
                if (int(d["taille_clair"]), str(d["sha256_clair"])) in coffre.prefixes.get(_tronc(nom), set()):
                    return "SCELLE", "archive compressée : son contenu est un préfixe scellé"
            except (OSError, ValueError, KeyError) as exc:
                _noter_echec("datasets/recensement_donnees.py:coffre_prefix", exc)
        if e and int(e.get("taille", -1)) == taille:
            return "SCELLE", "archive scellée telle quelle"
        if e:
            return "EN_COURS", "archive modifiée depuis son scellement"
        if coffre.prefixes.get(_tronc(nom)):
            # 23/11/2026 : une ROTATION dont le ruban vivant a été scellé au fil de l'eau. Son contenu est sans doute
            # déjà au coffre, mais l'état n'en garde plus la preuve (8 préfixes par chemin). La sceller en entier
            # créerait des doublons : elle se PROUVE par identité, elle ne se scelle pas à l'aveugle.
            return "A_PROUVER", "rotation d'un ruban scellé au fil de l'eau ; preuve d'état périmée"
        return "A_SCELLER", "archive jamais scellée"
    if e:
        scelle = int(e.get("prefixe_octets") or e.get("taille") or 0)
        if scelle >= taille:
            return "SCELLE", "scellé jusqu'à sa fin"
        return "EN_COURS", f"{taille - scelle:,} octets attendent le prochain passage"
    connus = {n for n, _ in coffre.prefixes.get(_tronc(nom), set())}
    if taille in connus:
        if not verifier_sha:
            return "SCELLE", "longueur d'un préfixe scellé (empreinte non relue)"
        sha = _sha256_fichier(chemin)
        if (taille, sha) in coffre.prefixes.get(_tronc(nom), set()):
            return "SCELLE", "contenu identique à un préfixe scellé (ruban déplacé)"
    return "A_SCELLER", "aucune trace au coffre"


def _verdict_de_la_preuve(preuves: dict, shards_au_coffre: set[str], rel: str, entree_os: Any,
                          verdict: str, detail: str) -> tuple[str, str]:
    """Un « à prouver » devient SCELLE si ``tools/prouver_scellement.py`` l'a prouvé par identité, sur CE contenu
    (taille et date inchangées), et que ses lignes absentes, s'il y en avait, sont au coffre."""
    p = preuves.get(rel)
    if not isinstance(p, dict):
        return verdict, detail
    try:
        st = entree_os.stat()
    except OSError:
        return verdict, detail
    if p.get("taille") != st.st_size or p.get("mtime_ns") != st.st_mtime_ns:
        return verdict, "preuve périmée : le fichier a changé depuis"
    ruban = p.get("ruban_des_absentes")
    if ruban and ruban.replace(".gz", "").replace(".jsonl", "") + ".jsonl.gz" not in shards_au_coffre:
        return verdict, f"prouvé ; ses {p.get('absentes_versees')} ligne(s) absente(s) attendent leur scellement"
    return "SCELLE", (f"prouvé par identité : {p.get('presentes')} ligne(s) déjà au coffre"
                      + (f", {p.get('absentes_versees')} absente(s) versée(s)" if ruban else ""))


def _sniffer(chemin: Path) -> tuple[str, str] | None:
    try:
        ouvrir = gzip.open if chemin.name.endswith(".gz") else open
        with ouvrir(chemin, "rt", encoding="utf-8", errors="replace") as f:
            for ligne in f:
                if ligne.strip():
                    return sniffer_famille(json.loads(ligne))
    except (OSError, ValueError, EOFError):
        return None
    return None


def _manifeste_externe(root: Path, dossier: str) -> dict[str, Any]:
    try:
        return json.loads((root / dossier / "MANIFESTE.json").read_text(encoding="utf-8")).get("fichiers", {})
    except (OSError, ValueError, AttributeError):
        return {}


def recenser(root: Path, *, verifier_sha: bool = False, max_listes: int = 200) -> dict[str, Any]:
    """Parcourt le projet et rend la couverture. Ne modifie rien."""
    root = Path(root).resolve()
    t0 = time.time()
    coffre = Coffre(root)
    manifestes = {z.motif: _manifeste_externe(root, z.motif) for z in ZONES if z.genre == "EXTERNE"}
    try:
        preuves = json.loads((root / PREUVES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        preuves = {}
    try:
        index = json.loads((root / INDEX_COFFRE).read_text(encoding="utf-8"))
        shards_au_coffre = {PurePosixPath(str(s.get("shard"))).name.split("__", 1)[-1]
                            for s in index.get("shards", []) if isinstance(s, dict)}
    except (OSError, ValueError, AttributeError):
        shards_au_coffre = set()
    totaux: dict[str, list[int]] = {}
    zones_vues: dict[str, dict[str, Any]] = {}
    listes: dict[str, list[dict[str, Any]]] = {"INCONNU": [], "A_SCELLER": [], "A_PROUVER": [],
                                               "EXTERNE_NON_MANIFESTE": []}
    a_sceller: list[dict[str, Any]] = []
    non_parcourus: dict[str, str] = {}
    fichiers_vus = dossiers_vus = 0

    def noter(verdict: str, rel: str, taille: int, zone: str, detail: str, famille: str | None = None) -> None:
        t = totaux.setdefault(verdict, [0, 0])
        t[0] += 1
        t[1] += taille
        zv = zones_vues.setdefault(zone, {"fichiers": 0, "octets": 0, "verdicts": {}})
        zv["fichiers"] += 1
        zv["octets"] += taille
        zv["verdicts"][verdict] = zv["verdicts"].get(verdict, 0) + 1
        if verdict in listes and len(listes[verdict]) < max_listes:
            listes[verdict].append({"fichier": rel, "octets": taille, "detail": detail, "famille": famille})
        if verdict == "A_SCELLER" and famille:
            a_sceller.append({"fichier": rel, "famille": famille[0], "source": famille[1]})

    pile = [""]
    while pile:
        rel_d = pile.pop()
        dossiers_vus += 1
        try:
            it = os.scandir(root / rel_d if rel_d else root)
        except OSError:
            continue
        with it:
            for e in it:
                rel = f"{rel_d}/{e.name}" if rel_d else e.name
                try:
                    if e.is_dir(follow_symlinks=False):
                        if e.name in ELAGUES:
                            continue
                        z = zone_de(rel)
                        if z is not None and z.genre in NON_PARCOURUS and _correspond(rel, z.motif) and \
                                len(rel.split("/")) == len(z.motif.split("/")):
                            non_parcourus[rel] = f"{z.genre} : {z.pourquoi}"
                            continue
                        pile.append(rel)
                        continue
                    if not e.is_file(follow_symlinks=False) or not est_donnee(e.name):
                        continue
                    fichiers_vus += 1
                    taille = e.stat().st_size
                except OSError:
                    continue
                z = zone_de(rel)
                nom_zone = z.motif if z else "(aucune règle)"
                if z is None:
                    noter("INCONNU", rel, taille, nom_zone, "dossier sans règle de recensement")
                elif z.genre == "EXTERNE":
                    sous = rel[len(z.motif) + 1:]
                    m = manifestes.get(z.motif, {}).get(sous)
                    if m:
                        noter("EXTERNE_VALIDE" if m.get("statut") == "EXTERNAL_VALIDATED" else "PAR_CONCEPTION",
                              rel, taille, nom_zone, str(m.get("statut")))
                    else:
                        noter("EXTERNE_NON_MANIFESTE", rel, taille, nom_zone, "fichier absent du manifeste")
                elif taille == 0:
                    noter("VIDE", rel, taille, nom_zone, "fichier vide : rien à certifier")
                elif z.genre == "COLLECTE" and e.name in OPERATIONNELS:
                    noter("PAR_CONCEPTION", rel, taille, nom_zone, f"OPERATIONNEL : {OPERATIONNELS[e.name]}")
                elif z.genre == "COLLECTE":
                    motif = motif_non_certifie(e.name)
                    fam = detecter_famille(e.name) or (None if motif else _sniffer(Path(e.path)))
                    if fam is None:
                        noter("PAR_CONCEPTION" if motif else "INCONNU", rel, taille, nom_zone,
                              motif or "zone de collecte, famille non reconnue (ni par le nom, ni par le contenu)")
                    else:
                        v, detail = verdict_scellement(Path(e.path), rel, taille, coffre, verifier_sha=verifier_sha)
                        session = rel.split("/")[2] if rel.startswith("runtime/archive/session_") else ""
                        # la garantie de l'archiveur prime sur la règle des rotations : une session archivée (même
                        # compressée) n'est PAS une rotation d'un ruban vivant
                        if v in ("A_SCELLER", "A_PROUVER") and session:
                            if session[len("session_"):] >= REGLE_ARCHIVEUR_DEPUIS:
                                v, detail = "SCELLE", ("garanti par l'archiveur : déplacé seulement si son contenu exact "
                                                       "était certifié (règle du 11/11/2026 12:20)")
                            else:
                                v, detail = "A_PROUVER", "session antérieure à la règle de l'archiveur, sans trace d'état"
                        if v == "A_PROUVER":
                            v, detail = _verdict_de_la_preuve(preuves, shards_au_coffre, rel, e, v, detail)
                        noter(v, rel, taille, nom_zone, detail, fam)
                else:
                    noter("PAR_CONCEPTION", rel, taille, nom_zone, f"{z.genre} : {z.pourquoi}")
    bloquants = sum(totaux.get(v, [0])[0] for v in BLOQUANTS)
    n = sum(t[0] for t in totaux.values())
    return {
        "schema": "hypersmart.recensement_donnees.v1", "genere_ms": int(time.time() * 1000),
        "duree_s": round(time.time() - t0, 1), "dossiers_parcourus": dossiers_vus, "fichiers_de_donnees": n,
        "complet": True, "couverture_pct": round(100.0 * (n - bloquants) / n, 4) if n else 100.0,
        "cent_pour_cent": bloquants == 0,
        "totaux": {k: {"fichiers": v[0], "octets": v[1]} for k, v in sorted(totaux.items())},
        "zones": dict(sorted(zones_vues.items(), key=lambda kv: -kv[1]["octets"])),
        "non_parcourus": non_parcourus, "listes": listes, "a_sceller": a_sceller,
    }


def ecrire_rapport(root: Path, rapport: dict[str, Any]) -> Path:
    chemin = Path(root) / RAPPORT
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")
    for i in range(8):
        try:
            os.replace(tmp, chemin)
            break
        except PermissionError:
            if i == 7:
                raise
            time.sleep(0.25 * (i + 1))
    return chemin


__all__ = ["ZONES", "Zone", "zone_de", "est_donnee", "recenser", "ecrire_rapport", "verdict_scellement", "Coffre"]
