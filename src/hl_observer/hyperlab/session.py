"""[Bloc 52 / AUD-095,096] Cycle de vie de session : ouvrir -> add_artifact (hash de contenu) ->
fermer avec marqueur COMPLETE + manifest de hashes. Une session NON fermee reste INCOMPLETE (jamais un
faux COMPLETE). verifier() recompute les hashes pour prouver l'integrite. ts fournis (deterministe)."""
from __future__ import annotations

import hashlib
from typing import Mapping


def _h(contenu) -> str:
    b = contenu if isinstance(contenu, bytes) else str(contenu).encode("utf-8")
    return hashlib.sha256(b).hexdigest()


class Session:
    def __init__(self, session_id: str, *, ts: float) -> None:
        self.session_id = session_id
        self.debut = ts
        self.fin = None
        self.statut = "INCOMPLETE"
        self.artefacts: dict = {}

    def add_artifact(self, name: str, contenu) -> str:
        h = _h(contenu)
        self.artefacts[name] = h
        return h

    def fermer(self, *, ts: float) -> dict:
        self.fin = ts
        self.statut = "COMPLETE"
        return self.manifest()

    def manifest(self) -> dict:
        return {"session_id": self.session_id, "statut": self.statut, "debut": self.debut,
                "fin": self.fin, "artefacts": dict(self.artefacts)}


def verifier(manifest: Mapping, artefacts_recus: Mapping) -> dict:
    """Recompute les hashes des artefacts recus et compare au manifest. COMPLETE + hashes concordants."""
    manquants, alteres = [], []
    for name, h in manifest.get("artefacts", {}).items():
        if name not in artefacts_recus:
            manquants.append(name)
        elif _h(artefacts_recus[name]) != h:
            alteres.append(name)
    ok = manifest.get("statut") == "COMPLETE" and not manquants and not alteres
    return {"ok": ok, "statut": manifest.get("statut"), "manquants": manquants, "alteres": alteres}
