"""[AUD-187/188] Chaine d'approvisionnement : SBOM (inventaire exhaustif des composants, style
CycloneDX) et verification que les dependances sont EPINGLEES PAR HASH (pip --require-hashes).
stdlib pure, 0 reseau."""
from __future__ import annotations

import hashlib
from typing import Mapping, Sequence


def generer_sbom(composants: Sequence[Mapping], *, format: str = "cyclonedx-min") -> dict:
    """SBOM minimal (Software Bill of Materials) : liste EXHAUSTIVE (nom, version, hash) -> on sait
    exactement ce qui tourne. Deterministe (tri stable)."""
    comps = []
    for c in composants:
        nom = str(c.get("nom", c.get("name", "?")))
        version = str(c.get("version", "0"))
        h = c.get("hash") or hashlib.sha256(("%s@%s" % (nom, version)).encode()).hexdigest()
        comps.append({"name": nom, "version": version, "hash": h})
    comps.sort(key=lambda d: (d["name"], d["version"]))
    return {"format": format, "n_composants": len(comps), "composants": comps}


def verifier_hashes_dependances(lignes_requirements: Sequence[str]) -> dict:
    """Verifie que CHAQUE dependance est epinglee par HASH (pip --require-hashes). Une dependance sans
    hash = surface d'attaque (substitution de paquet) -> signalee."""
    sans_hash: list[str] = []
    pinnees: list[str] = []
    for ligne in lignes_requirements:
        l = ligne.strip()
        if not l or l.startswith("#"):
            continue
        nom = l.split("==")[0].split(" ")[0].strip()
        if "--hash=" in l or "--hash " in l:
            pinnees.append(nom)
        else:
            sans_hash.append(nom)
    return {"toutes_pinnees": len(sans_hash) == 0, "sans_hash": sans_hash,
            "pinnees": pinnees, "n": len(pinnees) + len(sans_hash)}
