"""[DATA pépite 278] CHUNK CHECKSUM : chaque segment de dataset porte un hash. Il permet de distinguer un TROU
DE MARCHÉ (segment légitimement vide, checksum cohérent) d'une CORRUPTION DISQUE (contenu altéré, checksum qui
ne correspond plus). Sans ça, un fichier tronqué ressemble à un marché calme — et le backtest intègre du bruit
comme s'il était réel. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import hashlib
from typing import Any

OK = "OK"
TROU_MARCHE_VALIDE = "TROU_MARCHE_VALIDE"
CORRUPTION = "CORRUPTION"


def checksum(donnees: bytes) -> str:
    """SHA-256 hex du contenu brut du chunk."""
    if not isinstance(donnees, (bytes, bytearray)):
        donnees = str(donnees).encode("utf-8")
    return hashlib.sha256(bytes(donnees)).hexdigest()


def verifier(donnees: bytes, checksum_attendu: str) -> dict[str, Any]:
    """Checksum différent → CORRUPTION (disque). Checksum OK et segment vide → TROU_MARCHE_VALIDE (calme réel,
    pas une perte). Checksum OK et non vide → OK."""
    reel = checksum(donnees)
    if reel != checksum_attendu:
        return {"etat": CORRUPTION, "checksum": reel, "raison": "CHECKSUM_DIFFERENT"}
    if len(donnees) == 0:
        return {"etat": TROU_MARCHE_VALIDE, "checksum": reel}
    return {"etat": OK, "checksum": reel}


__all__ = ["checksum", "verifier", "OK", "TROU_MARCHE_VALIDE", "CORRUPTION"]
