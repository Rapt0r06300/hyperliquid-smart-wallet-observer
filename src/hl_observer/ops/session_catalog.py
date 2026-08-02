"""[LANCEUR items 7 & 8] Session canonique + catalogue de donn?es + cl?ture/quarantaine s?res.

Chaque run de collecte poss?de UNE session fig?e sous ``runtime/data/sessions/<run_id>/`` dont le c?ur
est ``DATA_CATALOG.json``. Le catalogue est la SOURCE DE V?RIT? que l'analyse (ANALYSER, item 10) relit :
il d?clare, par source/venue/canal, le fichier/DB/shard produit, ses versions de sch?ma+parser, ses
premiers/derniers horodatages (exchange ET r?ception), le compte d'?v?nements re?us/valides/rejet?s/
d?dupliqu?s, les gaps/reconnects/stale/hors-ordre, la couverture, le **checksum SHA-256**, la taille,
l'?tat de sant?, la raison d'absence d'une source, et les m?tadonn?es (frais...).

Cycle de vie honn?te (jamais pr?senter incomplet comme complet) :

  ACTIVE       ? collecte en cours, le catalogue grossit (mise ? jour ATOMIQUE ? chaque source).
  COMPLETE     ? SEULEMENT apr?s : writers arr?t?s, flush/fsync, DB ferm?es, checksums recalcul?s,
                 fichiers v?rifi?s (pr?sents + taille + hash), Z?RO orphelin. Sinon on ne cl?t pas.
  QUARANTINED  ? une v?rification de cl?ture a ?chou? (hash divergent, fichier manquant, orphelin,
                 erreur d'archive/manifeste) ? la session est mise en quarantaine, jamais COMPLETE.

0 r?seau, 0 ordre. Checksums en STREAMING (m?moire born?e ? esprit item 11). ?critures atomiques
(temp + os.replace + fsync). Aucune suppression brutale : la quarantaine MARQUE, elle ne d?truit pas.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from hl_observer.runtime.protections import empreinte, manifeste_execution

SCHEMA_CATALOGUE = "hypersmart.data_catalog.v1"
NOM_CATALOGUE = "DATA_CATALOG.json"

STATUT_ACTIVE = "ACTIVE"
STATUT_COMPLETE = "COMPLETE"
STATUT_QUARANTINED = "QUARANTINED"
STATUTS = (STATUT_ACTIVE, STATUT_COMPLETE, STATUT_QUARANTINED)

# item 12 ? PROVENANCE des donn?es, distincte de `real_execution`. `real_execution` reste TOUJOURS
# False (invariant de s?curit? : aucun ordre r?el n'est jamais pass?, paper strict). `data_origin` dit
# une autre v?rit? : ces donn?es ont-elles ?t? R?ELLEMENT collect?es sur Hyperliquid (REEL), ou est-ce
# une FIXTURE synth?tique de test (SYNTHETIQUE) ? Un rapport ? vert ? sur du SYNTHETIQUE est un faux
# gain : les couches aval (pnl_improvement_lab) rejettent SYNTHETIC/FAKE/DEMO. La collecte de
# production attest REEL ; toute fixture doit attester SYNTHETIQUE.
ORIGINE_REEL = "REEL"
ORIGINE_SYNTHETIQUE = "SYNTHETIQUE"
ORIGINES = (ORIGINE_REEL, ORIGINE_SYNTHETIQUE)

# Extensions consid?r?es comme des DONN?ES (pour la d?tection d'orphelins ? la cl?ture ? item 8).
EXTENSIONS_DONNEES = (".jsonl", ".jsonl.gz", ".json.gz", ".ndjson", ".sqlite3", ".sqlite",
                      ".db", ".csv", ".parquet", ".gz")

_CHUNK = 1 << 20  # 1 Mo ? lecture born?e


def nouveau_run_id(prefixe: str = "run", *, horloge=time.time) -> str:
    """Identifiant de session : horodat? (tri naturel) + suffixe al?atoire (pas de collision)."""
    return "%s-%d-%s" % (prefixe, int(horloge() * 1000), os.urandom(4).hex())


def chemin_session(root: str | Path, run_id: str) -> Path:
    return Path(root) / "runtime" / "data" / "sessions" / run_id


def chemin_catalogue(root: str | Path, run_id: str) -> Path:
    return chemin_session(root, run_id) / NOM_CATALOGUE


def sha256_fichier(chemin: str | Path, *, chunk: int = _CHUNK) -> tuple[str, int]:
    """SHA-256 en streaming (m?moire born?e) + taille. Fichier absent ? ("", -1) (jamais un faux hash)."""
    p = Path(chemin)
    if not p.is_file():
        return "", -1
    h = hashlib.sha256()
    taille = 0
    with p.open("rb") as f:
        while True:
            bloc = f.read(chunk)
            if not bloc:
                break
            h.update(bloc)
            taille += len(bloc)
    return h.hexdigest(), taille


@dataclass
class EntreeSource:
    """Une entr?e de catalogue = un flux de donn?es (source ? venue ? canal ? artefact)."""
    source: str
    venue: str = ""
    canal: str = ""
    source_id: str = ""                     # item 7 : cl? STABLE ind?pendante du chemin (d?faut = source)
    chemin: str = ""                       # relatif ? la session (fichier / DB / shard)
    type_stockage: str = "fichier"         # fichier / db / shard
    schema_version: str = ""
    parser_version: str = ""
    premier_ts_exchange: int | None = None
    dernier_ts_exchange: int | None = None
    premier_ts_reception: int | None = None
    dernier_ts_reception: int | None = None
    evenements_recus: int = 0
    evenements_valides: int = 0
    evenements_rejetes: int = 0
    evenements_dedupes: int = 0
    gaps: int = 0
    reconnects: int = 0
    stale: bool = False
    hors_ordre: int = 0
    couverture: float | None = None        # ratio 0..1 (fen?tre r?ellement couverte)
    checksum_sha256: str = ""
    taille_octets: int = -1
    sante: str = "GRISE"                    # VERTE / ORANGE / ROUGE / GRISE
    raison_absence: str = ""               # renseign?e si la source est absente / non impl?ment?e
    frais: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.source_id:
            self.source_id = self.source        # item 7 : cl? stable par d?faut = nom de source

    def cle(self) -> str:
        return "%s|%s|%s|%s" % (self.source, self.venue, self.canal, self.chemin)


class CatalogueInvalideError(ValueError):
    """Chemin d'artefact refus? par le catalogue (item 6) : absolu / .. / hors session / symlink sortant /
    doublon. Aucune donn?e hors du dossier de session n'entre jamais au catalogue."""


def valider_chemin_artefact(dossier: str | Path, rel: str) -> str:
    """item 6 : n'autorise QU'un chemin RELATIF, strictement CONTENU dans le dossier de session, sans `..`,
    sans composante absolue, et dont la cible r?elle (apr?s r?solution des symlinks) reste DANS la session.
    Rend le chemin normalis? (posix). L?ve CatalogueInvalideError sinon."""
    dossier = Path(dossier)
    brut = str(rel or "")
    if not brut:
        raise CatalogueInvalideError("chemin d'artefact vide")
    p = Path(brut)
    if p.is_absolute() or (len(brut) >= 2 and brut[1] == ":"):          # absolu POSIX ou lecteur Windows
        raise CatalogueInvalideError("chemin absolu interdit: %s" % brut)
    parts = p.parts
    if ".." in parts:
        raise CatalogueInvalideError("remontee '..' interdite: %s" % brut)
    # la cible R?ELLE (symlinks r?solus) doit rester sous le dossier de session.
    cible = (dossier / p)
    try:
        racine_reelle = dossier.resolve()
        cible_reelle = cible.resolve()
    except OSError as e:
        raise CatalogueInvalideError("chemin irresolvable: %s (%s)" % (brut, e))
    try:
        cible_reelle.relative_to(racine_reelle)
    except ValueError:
        raise CatalogueInvalideError("artefact HORS de la session (symlink/echappement): %s" % brut)
    return p.as_posix()


def _ecrire_atomique(cible: Path, contenu: str) -> None:
    """?crit + fsync + os.replace (durable, jamais un catalogue ? moiti? ?crit)."""
    cible.parent.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_name(".%s.%d.%d.tmp" % (cible.name, os.getpid(), time.time_ns()))
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(contenu)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, cible)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


class CatalogueSession:
    """G?re le DATA_CATALOG.json d'UNE session. Mise ? jour atomique, cycle ACTIVE?COMPLETE/QUARANTINED."""

    def __init__(self, root: str | Path, run_id: str):
        self.root = Path(root)
        self.run_id = run_id
        self.dossier = chemin_session(root, run_id)
        self.chemin = chemin_catalogue(root, run_id)

    # ?? cr?ation / lecture ????????????????????????????????????????????????????????????????????
    def demarrer(self, *, git_head: str | None = None, contexte: Mapping[str, Any] | None = None,
                 data_origin: str = ORIGINE_REEL, horloge=time.time) -> dict:
        """Cr?e la session ACTIVE (idempotent : ne r??crase pas une session d?j? d?marr?e).
        `data_origin` (item 12) : REEL par d?faut (le chemin canonique = collecte de production r?elle) ;
        une FIXTURE de test DOIT passer ORIGINE_SYNTHETIQUE. `real_execution` reste False (s?curit?)."""
        if self.chemin.is_file():
            return self.lire()
        manifeste = manifeste_execution(self.root, tache="collecte_harvest", run_id=self.run_id)
        origine = data_origin if data_origin in ORIGINES else ORIGINE_REEL
        payload = {
            "schema_catalogue": SCHEMA_CATALOGUE,
            "run_id": self.run_id,
            "statut": STATUT_ACTIVE,
            "git_head": git_head if git_head is not None else manifeste.get("git_head"),
            "git_dirty": manifeste.get("git_dirty"),
            "manifeste": manifeste,
            "debut_ms": int(horloge() * 1000),
            "fin_ms": None,
            "sources": {},                 # cle -> entr?e
            "cloture": None,
            "contexte": dict(contexte or {}),
            "real_execution": False,       # invariant s?curit? : AUCUN ordre r?el, jamais
            "data_origin": origine,        # item 12 : provenance REELLE vs fixture SYNTHETIQUE
        }
        self._sauver(payload)
        return payload

    def lire(self) -> dict:
        try:
            return json.loads(self.chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _sauver(self, payload: Mapping[str, Any]) -> None:
        payload = dict(payload)
        payload["empreinte"] = empreinte({k: v for k, v in payload.items() if k != "empreinte"})
        _ecrire_atomique(self.chemin, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))

    # ?? enregistrement d'une source (met ? jour le catalogue ACTIVE, atomiquement) ?????????????
    def enregistrer_source(self, entree: EntreeSource | Mapping[str, Any], *,
                           calculer_checksum: bool = True) -> dict:
        """Ajoute/?crase l'entr?e d'une source. Si un artefact r?el existe, son checksum + taille sont
        calcul?s depuis le disque (jamais renseign?s ? la main)."""
        cat = self.lire()
        if not cat:
            cat = self.demarrer()
        if cat.get("statut") != STATUT_ACTIVE:
            raise SessionFigeeError("session %s fig?e (%s) : plus d'enregistrement" %
                                    (self.run_id, cat.get("statut")))
        e = entree if isinstance(entree, EntreeSource) else EntreeSource(**dict(entree))
        sources = cat.setdefault("sources", {})
        if e.chemin:
            # item 6 : rejette absolu / .. / hors-session / symlink sortant, et NORMALISE le chemin relatif.
            e.chemin = valider_chemin_artefact(self.dossier, e.chemin)
            # item 6 : doublon de chemin interdit (m?me artefact catalogu? deux fois sous des cl?s ?).
            for cle, autre in sources.items():
                if (autre.get("chemin") or "") and os.path.normpath(autre["chemin"]) == os.path.normpath(e.chemin) \
                        and cle != e.cle():
                    raise CatalogueInvalideError("doublon de chemin d'artefact: %s" % e.chemin)
            # item 7 : une source qui produit un vrai artefact ne garde PAS son entr?e vide (chemin="").
            vide_cle = "%s|%s|%s|" % (e.source, e.venue, e.canal)
            sources.pop(vide_cle, None)
            for cle in [k for k, v in sources.items()
                        if not (v.get("chemin") or "") and (v.get("source_id") or v.get("source")) == e.source_id]:
                sources.pop(cle, None)
        d = asdict(e)
        if calculer_checksum and e.chemin:
            artefact = self.dossier / e.chemin
            checksum, taille = sha256_fichier(artefact)
            d["checksum_sha256"] = checksum
            d["taille_octets"] = taille
        sources[e.cle()] = d
        self._sauver(cat)
        return d

    def enregistrer_artefact_live(self, entree: EntreeSource | Mapping[str, Any]) -> dict:
        """item 4 : enregistre un artefact ENCORE ACTIF (mutable) SANS checksum final. Le SHA-256 d?finitif
        n'est calcul? qu'? la CL?TURE (writers arr?t?s ? flush/fsync). Un fichier live qui GRANDIT depuis
        son premier enregistrement ne met donc JAMAIS la session en quarantaine."""
        return self.enregistrer_source(entree, calculer_checksum=False)

    # ?? cl?ture s?re (item 8) ???????????????????????????????????????????????????????????????????
    def cloturer(self, *, writers_arretes: bool, extensions_donnees: Iterable[str] = EXTENSIONS_DONNEES,
                 horloge=time.time, exiger_artefacts: bool = True) -> dict:
        """Passe la session en COMPLETE SEULEMENT si toutes les v?rifications passent. Sinon QUARANTINED.
        `exiger_artefacts` (item 3, d?faut True) : une session SANS aucun artefact r?el v?rifi? (fichier
        pr?sent + non vide) ne peut JAMAIS devenir COMPLETE ? elle est QUARANTINED (AUCUN_ARTEFACT_REEL).
        Renvoie le verdict de cl?ture {statut, verifications, orphelins, divergences, motifs}."""
        cat = self.lire()
        if not cat:
            return {"statut": "ABSENTE", "motifs": ["catalogue introuvable"]}
        if cat.get("statut") == STATUT_COMPLETE:
            return {"statut": STATUT_COMPLETE, "deja": True, "verifications": cat.get("cloture")}

        motifs: list[str] = []
        divergences: list[dict] = []
        if not writers_arretes:
            motifs.append("WRITERS_ENCORE_ACTIFS")

        sources = cat.get("sources") or {}
        catalogues_rel: set[str] = set()
        for cle, d in sources.items():
            rel = d.get("chemin") or ""
            if not rel:
                continue                    # source absente/non-impl?ment?e : pas d'artefact ? v?rifier
            if os.path.normpath(rel) in catalogues_rel:
                motifs.append("DOUBLON_CHEMIN")        # item 6 : jamais deux entr?es pour le m?me fichier
                divergences.append({"cle": cle, "chemin": rel, "probleme": "DOUBLON"})
                continue
            catalogues_rel.add(os.path.normpath(rel))
            artefact = self.dossier / rel
            checksum_now, taille_now = sha256_fichier(artefact)
            if taille_now < 0:
                motifs.append("FICHIER_MANQUANT")
                divergences.append({"cle": cle, "chemin": rel, "probleme": "MANQUANT"})
                continue
            if taille_now == 0:
                motifs.append("FICHIER_VIDE")          # item 6 : un artefact vide n'est jamais COMPLETE
                divergences.append({"cle": cle, "chemin": rel, "probleme": "VIDE"})
                continue
            attendu = d.get("checksum_sha256") or ""
            if attendu and checksum_now != attendu:
                motifs.append("CHECKSUM_DIVERGENT")
                divergences.append({"cle": cle, "chemin": rel, "probleme": "CHECKSUM",
                                    "attendu": attendu, "obtenu": checksum_now})
            elif not attendu:
                # jamais catalogu? : on le fige maintenant (checksum de cl?ture) plut?t que mentir.
                d["checksum_sha256"], d["taille_octets"] = checksum_now, taille_now

        orphelins = _detecter_orphelins(self.dossier, catalogues_rel, tuple(extensions_donnees))
        if orphelins:
            motifs.append("ORPHELINS")

        # item 3 : au moins UN artefact r?el v?rifi? (fichier pr?sent + non vide) est requis pour COMPLETE.
        artefacts_reels = sum(1 for cle, d in sources.items()
                              if (d.get("chemin") and (d.get("taille_octets") or 0) > 0
                                  and "MANQUANT" not in [x.get("probleme") for x in divergences
                                                         if x.get("cle") == cle]))
        if exiger_artefacts and artefacts_reels <= 0:
            motifs.append("AUCUN_ARTEFACT_REEL")

        # item 5 : une source d?clar?e VIVANTE (sant? VERTE) doit poss?der au moins un artefact r?el.
        # Source vivante SANS artefact = QUARANTINED (un seul fichier r?el ailleurs ne la couvre pas).
        vivantes_sans_artefact = sorted({str(d.get("source"))
                                         for d in sources.values()
                                         if str(d.get("sante", "")).upper() == "VERTE"
                                         and not (d.get("chemin") or "")})
        if exiger_artefacts and vivantes_sans_artefact:
            motifs.append("SOURCE_VIVANTE_SANS_ARTEFACT")

        verifications = {
            "writers_arretes": bool(writers_arretes),
            "n_sources": len(sources),
            "n_artefacts_verifies": len(catalogues_rel),
            "n_artefacts_reels": artefacts_reels,
            "orphelins": orphelins,
            "divergences": divergences,
            "vivantes_sans_artefact": vivantes_sans_artefact,
            "checksums_ok": not any(m in ("CHECKSUM_DIVERGENT", "FICHIER_MANQUANT", "FICHIER_VIDE",
                                          "DOUBLON_CHEMIN") for m in motifs),
            "zero_orphelin": not orphelins,
        }
        cat["sources"] = sources
        if motifs:
            cat["statut"] = STATUT_QUARANTINED
            cat["quarantaine"] = {"ms": int(horloge() * 1000), "motifs": sorted(set(motifs)),
                                  "verifications": verifications}
            self._sauver(cat)
            return {"statut": STATUT_QUARANTINED, "motifs": sorted(set(motifs)),
                    "verifications": verifications, "divergences": divergences, "orphelins": orphelins}

        cat["statut"] = STATUT_COMPLETE
        cat["fin_ms"] = int(horloge() * 1000)
        cat["cloture"] = verifications
        self._sauver(cat)
        return {"statut": STATUT_COMPLETE, "verifications": verifications}

    def quarantiner(self, raison: str, *, horloge=time.time) -> dict:
        """Met la session en quarantaine (ex. erreur d'archive/rotation) SANS rien supprimer."""
        cat = self.lire() or self.demarrer()
        cat["statut"] = STATUT_QUARANTINED
        cat["quarantaine"] = {"ms": int(horloge() * 1000), "motifs": [str(raison)[:200]]}
        self._sauver(cat)
        return {"statut": STATUT_QUARANTINED, "raison": raison}


class SessionFigeeError(RuntimeError):
    """Tentative d'?crire dans une session qui n'est plus ACTIVE."""


def verifier_catalogue(dossier: str | Path, sources: Mapping[str, Mapping[str, Any]], *,
                       extensions: Iterable[str] = EXTENSIONS_DONNEES) -> dict:
    """V?rification READ-ONLY du catalogue vs disque (r?utilis?e par la cl?ture ET par ANALYSER, item 10) :
    chaque artefact catalogu? est pr?sent + son checksum RECALCUL? correspond, et il n'y a AUCUN orphelin.
    Rend {divergences, orphelins, checksums_ok, zero_orphelin, n_artefacts_verifies, tout_ok}."""
    dossier = Path(dossier)
    divergences: list[dict] = []
    catalogues_rel: set[str] = set()
    for cle, d in (sources or {}).items():
        rel = (d or {}).get("chemin") or ""
        if not rel:
            continue                      # source d?clar?e sans artefact (absente/non impl?ment?e)
        # item 6/15 : re-valider le chemin INTERNE (absolu / .. / symlink sortant) ind?pendamment.
        try:
            rel = valider_chemin_artefact(dossier, rel)
        except CatalogueInvalideError:
            divergences.append({"cle": cle, "chemin": rel, "probleme": "CHEMIN_INVALIDE"})
            continue
        norm = os.path.normpath(rel)
        if norm in catalogues_rel:
            divergences.append({"cle": cle, "chemin": rel, "probleme": "DOUBLON"})
            continue
        catalogues_rel.add(norm)
        checksum_now, taille_now = sha256_fichier(dossier / rel)
        if taille_now < 0:
            divergences.append({"cle": cle, "chemin": rel, "probleme": "MANQUANT"})
            continue
        if taille_now == 0:
            divergences.append({"cle": cle, "chemin": rel, "probleme": "VIDE"})
            continue
        attendu = (d or {}).get("checksum_sha256") or ""
        if attendu and checksum_now != attendu:
            divergences.append({"cle": cle, "chemin": rel, "probleme": "CHECKSUM",
                                "attendu": attendu, "obtenu": checksum_now})
    orphelins = _detecter_orphelins(dossier, catalogues_rel, tuple(extensions))
    checksums_ok = not divergences
    zero_orphelin = not orphelins
    return {"divergences": divergences, "orphelins": orphelins, "checksums_ok": checksums_ok,
            "zero_orphelin": zero_orphelin, "n_artefacts_verifies": len(catalogues_rel),
            "tout_ok": checksums_ok and zero_orphelin}


def _detecter_orphelins(dossier: Path, catalogues_rel: set[str], extensions: tuple[str, ...]) -> list[str]:
    """Fichiers de DONN?ES pr?sents dans la session mais ABSENTS du catalogue (item 8 : z?ro orphelin)."""
    if not dossier.is_dir():
        return []
    orphelins: list[str] = []
    for p in dossier.rglob("*"):
        if not p.is_file():
            continue
        nom = p.name
        if nom == NOM_CATALOGUE or nom.startswith(".") or nom.endswith(".tmp") or nom.endswith(".lock"):
            continue
        if not any(nom.endswith(ext) for ext in extensions):
            continue
        rel = os.path.normpath(str(p.relative_to(dossier)))
        if rel not in catalogues_rel:
            orphelins.append(rel)
    return sorted(orphelins)


# ?? d?couverte de sessions (pour ANALYSER, item 10) ?????????????????????????????????????????????
def scanner_sessions(root: str | Path) -> list[dict]:
    """Liste (run_id, statut, debut_ms, chemin) de toutes les sessions, tri?es par d?but d?croissant."""
    base = Path(root) / "runtime" / "data" / "sessions"
    out: list[dict] = []
    if not base.is_dir():
        return out
    for d in base.iterdir():
        cat_p = d / NOM_CATALOGUE
        if not cat_p.is_file():
            continue
        try:
            cat = json.loads(cat_p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"run_id": cat.get("run_id") or d.name, "statut": cat.get("statut"),
                    "debut_ms": cat.get("debut_ms") or 0, "chemin": str(cat_p),
                    "data_origin": cat.get("data_origin") or ORIGINE_REEL})
    out.sort(key=lambda x: x.get("debut_ms") or 0, reverse=True)
    return out


def derniere_session_complete(root: str | Path) -> dict | None:
    """La session COMPLETE la plus r?cente ? ce que ANALYSER doit consommer (jamais ACTIVE/QUARANTINED)."""
    for s in scanner_sessions(root):
        if s.get("statut") == STATUT_COMPLETE:
            return s
    return None


__all__ = ["SCHEMA_CATALOGUE", "NOM_CATALOGUE", "STATUT_ACTIVE", "STATUT_COMPLETE",
           "STATUT_QUARANTINED", "STATUTS", "ORIGINE_REEL", "ORIGINE_SYNTHETIQUE", "ORIGINES",
           "EntreeSource", "CatalogueSession", "SessionFigeeError",
           "sha256_fichier", "nouveau_run_id", "chemin_session", "chemin_catalogue",
           "scanner_sessions", "derniere_session_complete", "verifier_catalogue",
           "CatalogueInvalideError", "valider_chemin_artefact"]
