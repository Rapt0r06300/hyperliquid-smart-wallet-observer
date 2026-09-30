"""[AUD-033..040 — RECONSTRUIT] Les intitules d'origine de AUD-033..040 (herites 'MASTER V3') sont
PERDUS au niveau projet (la tasklist elle-meme porte 'titre a retrouver' ; introuvables sur le disque et
dans l'historique git). Plutot que de laisser 8 cases vides ou d'inventer un faux 'done', ce module
implemente une RECONSTRUCTION honnete de leur cluster evident — reproductibilite / provenance / supply
chain de release — situe entre AUD-032 'Release prouvee' et AUD-041 'GIT_HEAD_AUDIT_TRAIL', et DISTINCT
des items deja couverts (031 deps hermetiques, 187 deps hashees, 188 SBOM, 189 pas d'install pendant run).
A CONFIRMER contre le MASTER V3 de Flo. stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence

RECONSTRUIT = True  # ces 8 fonctions couvrent une reconstruction, a valider contre le MASTER V3 original


# --- AUD-033 (reconstruit) : reproductibilite bit-a-bit ---
def hash_artefact(fichiers: Mapping[str, bytes]) -> str:
    """Empreinte DETERMINISTE d'un artefact = sha256 sur (chemin, hash_contenu) tries. Ordre/horodatage
    n'influencent pas le hash (build reproductible)."""
    paires = sorted((chemin, hashlib.sha256(_b(contenu)).hexdigest()) for chemin, contenu in fichiers.items())
    return hashlib.sha256(json.dumps(paires, sort_keys=True).encode("utf-8")).hexdigest()


def reproductible(build_a: Mapping[str, bytes], build_b: Mapping[str, bytes]) -> dict:
    ha, hb = hash_artefact(build_a), hash_artefact(build_b)
    return {"reproductible": ha == hb, "hash_a": ha, "hash_b": hb}


# --- AUD-034 (reconstruit) : attestation de provenance (artefact <- commit <- builder) ---
def attestation(artefact_hash: str, commit_sha: str, builder: str) -> dict:
    ident = hashlib.sha256(("%s|%s|%s" % (artefact_hash, commit_sha, builder)).encode()).hexdigest()
    return {"artefact_hash": artefact_hash, "commit_sha": commit_sha, "builder": builder, "attestation_id": ident}


def verifier_attestation(att: Mapping, artefact_hash: str, commit_sha: str) -> bool:
    """Vrai seulement si l'attestation lie exactement cet artefact a ce commit (chaine non falsifiee)."""
    return bool(att) and att.get("artefact_hash") == artefact_hash and att.get("commit_sha") == commit_sha


# --- AUD-035 (reconstruit) : integrite du lockfile a l'installation ---
def verifier_lock(lock: Mapping[str, str], installe: Mapping[str, str]) -> dict:
    """Chaque paquet installe doit matcher le hash du lock. Mismatch/absent -> refus DUR (liste)."""
    ecarts = []
    for paquet, h in lock.items():
        if installe.get(paquet) != h:
            ecarts.append({"paquet": paquet, "attendu": h, "obtenu": installe.get(paquet)})
    return {"ok": not ecarts, "ecarts": ecarts}


# --- AUD-036 (reconstruit) : detection de dependance non epinglee ---
def deps_non_epinglees(reqs: Sequence[str]) -> list:
    """Refuse >=, <=, >, <, ~=, !=, *, ou l'absence de version. Une dep est epinglee UNIQUEMENT si elle
    porte '==' avec une version concrete et AUCUN operateur flou."""
    flous = []
    for r in reqs:
        s = r.strip()
        if not s or s.startswith("#"):
            continue
        base = s.split(";")[0].strip()          # retire les markers d'environnement
        if "==" not in base:
            flous.append(r)
            continue
        if any(op in base for op in (">=", "<=", "~=", "!=", ">", "<", "*")):
            flous.append(r)
    return flous


# --- AUD-037 (reconstruit) : version yankee / retiree interdite ---
def deps_interdites(reqs: Sequence[str], registre_yank: Mapping[str, Sequence[str]]) -> list:
    """Signale toute dep dont la version figure dans le registre local des versions yankees/retirees."""
    interdits = []
    for r in reqs:
        if "==" in r:
            nom, ver = r.split("==", 1)
            nom, ver = nom.strip(), ver.strip()
            if ver in set(registre_yank.get(nom, ())):
                interdits.append({"paquet": nom, "version": ver})
    return interdits


# --- AUD-038 (reconstruit) : empreinte d'environnement d'execution ---
def empreinte_env(python: str, os_: str, arch: str) -> str:
    return hashlib.sha256(("%s|%s|%s" % (python, os_, arch)).encode()).hexdigest()


def env_compatible(attendu: str, courant: str) -> bool:
    return attendu == courant


# --- AUD-039 (reconstruit) : non-regression taille/contenu d'artefact ---
def diff_artefact(ref: Mapping[str, bytes], courant: Mapping[str, bytes]) -> dict:
    """Diff inattendu (fichier ajoute/retire/modifie) -> alerte (jamais masque)."""
    r, c = set(ref), set(courant)
    modifies = sorted(f for f in (r & c) if _b(ref[f]) != _b(courant[f]))
    return {"ajoutes": sorted(c - r), "retires": sorted(r - c), "modifies": modifies,
            "identique": (r == c) and not modifies}


# --- AUD-040 (reconstruit) : chaine de garde build->test->release (meme arbre) ---
def chaine_garde(sha_build: str, sha_test: str, sha_release: str) -> dict:
    """Anti-swap d'artefact : build, test et release doivent porter le MEME SHA d'arbre."""
    ok = sha_build == sha_test == sha_release
    return {"ok": ok, "sha_build": sha_build, "sha_test": sha_test, "sha_release": sha_release}


def _b(x) -> bytes:
    return x if isinstance(x, bytes) else str(x).encode("utf-8")
