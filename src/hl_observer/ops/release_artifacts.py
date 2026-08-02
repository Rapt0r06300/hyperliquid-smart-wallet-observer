"""Artefacts externes d'une release portable HyperSmart.

Ces rapports vivent a cote du ZIP. Ils peuvent donc contenir une date humaine
de build sans casser la reproductibilite des octets de l'archive.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from hl_observer.ops.archive_portable import NOM_MANIFESTE

NOMS_ARTEFACTS = {
    "manifeste": "PORTABLE_MANIFEST.json",
    "rapport_json": "RELEASE_REPORT.json",
    "rapport_md": "RELEASE_REPORT.md",
    "sbom": "SBOM.cyclonedx.json",
    "licences": "LICENCES_RELEASE.json",
    "inventaire": "INVENTAIRE_RELEASE.json",
    "tests": "TESTS_ARCHIVE_EXTRAITE.json",
    "modules": "MODULES_COLLECTEURS_VERIFIES.json",
    "ecritures": "PREUVE_ZERO_ECRITURE_EXTERNE.json",
}


def _sha256(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    taille = 0
    with path.open("rb") as flux:
        for bloc in iter(lambda: flux.read(1024 * 1024), b""):
            h.update(bloc)
            taille += len(bloc)
    return h.hexdigest(), taille


def _ecrire_atomique(path: Path, contenu: bytes) -> None:
    temporaire = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    temporaire.write_bytes(contenu)
    os.replace(temporaire, path)


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _composants_cyclonedx(manifeste: dict) -> list[dict]:
    composants = []
    motif = re.compile(r"^([A-Za-z0-9_.-]+)==([^ ;\\]+)")
    for ligne in manifeste.get("deps", []):
        match = motif.match(str(ligne))
        if not match:
            continue
        nom, version = match.groups()
        composants.append({
            "type": "library",
            "name": nom,
            "version": version,
            "purl": "pkg:pypi/%s@%s" % (nom.lower().replace("_", "-"), version),
        })
    return sorted(composants, key=lambda c: (c["name"].casefold(), c["version"]))


def construire_sbom_cyclonedx(manifeste: dict) -> dict:
    empreinte = str(manifeste.get("empreinte_globale", ""))
    identifiant = uuid.uuid5(uuid.NAMESPACE_URL, "hypersmart:" + empreinte)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:%s" % identifiant,
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "HyperSmart Observer Portable",
                "version": manifeste.get("hypersmart_version", "unknown"),
                "hashes": [{"alg": "SHA-256", "content": empreinte}],
            },
            "properties": [
                {"name": "hypersmart:git-sha", "value": manifeste.get("git_sha", "")},
                {"name": "hypersmart:target", "value": "Windows-x64"},
            ],
        },
        "components": _composants_cyclonedx(manifeste),
    }


def _raison_exclusion(rel: str) -> str:
    low = rel.lower()
    if ".git" in low:
        return "controle_version_source"
    if any(x in low for x in ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")):
        return "cache_reproductible"
    if low.endswith((".key", ".p12", ".pfx")) or ".env" in low:
        return "secret_interdit"
    if low.endswith((".zip", ".7z", ".rar", ".sha256")) or low.startswith("dist/"):
        return "ancienne_release_interdite"
    if low.endswith((".pid", ".lock", ".tmp", "-wal", "-shm")):
        return "etat_runtime_transitoire"
    return "hors_perimetre_portable"


def _rapport_markdown(rapport: dict) -> str:
    pret = bool(rapport.get("RELEASE_READY"))
    lignes = [
        "# Rapport de release portable HyperSmart",
        "",
        "- Verdict : **RELEASE_READY=%s**" % str(pret).lower(),
        "- Archive : `%s`" % rapport.get("archive", ""),
        "- SHA-256 : `%s`" % rapport.get("archive_sha256", ""),
        "- Taille : `%s` octets" % rapport.get("archive_taille", 0),
        "- Git : `%s`" % rapport.get("git_sha", ""),
        "- Version : `%s`" % rapport.get("version", ""),
        "- Construit (rapport externe) : `%s`" % rapport.get("date_rapport_utc", ""),
        "",
        "## Portes",
        "",
    ]
    for porte in rapport.get("gates", []):
        lignes.append("- [%s] `%s` : %s" % (
            "x" if porte.get("ok") else " ", porte.get("gate", "?"), porte.get("detail", ""),
        ))
    limites = rapport.get("limitations", [])
    if limites:
        lignes.extend(["", "## Limitations", ""])
        lignes.extend("- %s" % x for x in limites)
    lignes.extend([
        "", "## Securite", "",
        "Paper/read-only uniquement : aucun ordre reel, aucune cle privee, aucune signature, aucun `/exchange`.",
        "",
    ])
    return "\n".join(lignes)


def produire_artefacts_release(
    archive: str | Path,
    *,
    validation: dict | None = None,
    verdict: dict | None = None,
    exclusions: list[str] | None = None,
    horloge: Callable[[], datetime] | None = None,
) -> dict:
    """Produit atomiquement tous les livrables externes demandes."""
    archive = Path(archive).resolve()
    if not archive.is_file():
        raise FileNotFoundError(archive)
    sortie = archive.parent
    validation = dict(validation or {})
    verdict = dict(verdict or {})
    with zipfile.ZipFile(archive, "r") as z:
        manifeste_bytes = z.read(NOM_MANIFESTE)
        manifeste = json.loads(manifeste_bytes.decode("utf-8"))
    archive_sha, archive_taille = _sha256(archive)
    maintenant = horloge() if horloge is not None else datetime.now(timezone.utc)
    if maintenant.tzinfo is None:
        maintenant = maintenant.replace(tzinfo=timezone.utc)

    inclus = sorted(manifeste.get("fichiers", {}))
    exclus = sorted(set(exclusions or manifeste.get("donnees_exclues", [])))
    modules = sorted(x for x in inclus if x.startswith("src/hl_observer/") and x.endswith(".py"))
    collecteurs = sorted(x for x in modules if "collect" in x.casefold() or "source" in x.casefold())
    licences = []
    for rel in manifeste.get("sbom", {}).get("licences", []):
        meta = manifeste.get("fichiers", {}).get(rel, {})
        licences.append({"chemin": rel, **meta})

    rapport = {
        "schema": "hypersmart.release_report.v1",
        "RELEASE_READY": bool(verdict.get("RELEASE_READY", False)),
        "gates": verdict.get("gates", []),
        "manquants": verdict.get("manquants", []),
        "archive": archive.name,
        "archive_sha256": archive_sha,
        "archive_taille": archive_taille,
        "git_sha": manifeste.get("git_sha", ""),
        "git_dirty": manifeste.get("etat_git", {}).get("dirty"),
        "version": manifeste.get("hypersmart_version", ""),
        "source_date_epoch": manifeste.get("source_date_epoch"),
        "date_rapport_utc": maintenant.astimezone(timezone.utc).isoformat(),
        "validation": validation,
        "limitations": validation.get("limitations", []),
        "securite": {
            "paper_read_only": True,
            "ordre_reel": False,
            "cle_privee": False,
            "signature": False,
            "exchange_endpoint": False,
        },
    }
    artefacts = {
        NOMS_ARTEFACTS["manifeste"]: _json_bytes(manifeste),
        NOMS_ARTEFACTS["rapport_json"]: _json_bytes(rapport),
        NOMS_ARTEFACTS["rapport_md"]: _rapport_markdown(rapport).encode("utf-8"),
        NOMS_ARTEFACTS["sbom"]: _json_bytes(construire_sbom_cyclonedx(manifeste)),
        NOMS_ARTEFACTS["licences"]: _json_bytes({"licences": licences}),
        NOMS_ARTEFACTS["inventaire"]: _json_bytes({
            "inclus": inclus,
            "exclus": [{"chemin": x, "justification": _raison_exclusion(x)} for x in exclus],
        }),
        NOMS_ARTEFACTS["tests"]: _json_bytes(validation.get("tests", {"ok": False, "detail": "absent"})),
        NOMS_ARTEFACTS["modules"]: _json_bytes({
            "modules": modules,
            "collecteurs": collecteurs,
            "validation": validation.get("modules", {"ok": False, "detail": "absent"}),
        }),
        NOMS_ARTEFACTS["ecritures"]: _json_bytes(
            validation.get("zero_ecriture_externe", {"ok": False, "detail": "absent"})
        ),
        archive.name + ".sha256": ("%s  %s\n" % (archive_sha, archive.name)).encode("ascii"),
    }
    chemins = {}
    for nom, contenu in artefacts.items():
        cible = sortie / nom
        _ecrire_atomique(cible, contenu)
        chemins[nom] = str(cible)
    return {"ok": True, "archive_sha256": archive_sha, "archive_taille": archive_taille,
            "artefacts": chemins, "rapport": rapport}


__all__ = ["NOMS_ARTEFACTS", "construire_sbom_cyclonedx", "produire_artefacts_release"]
