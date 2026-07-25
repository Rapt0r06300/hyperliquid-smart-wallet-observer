"""Plugin DATA du labo — enveloppe le collecteur isolé (LOT 1) pour qu'il tourne DANS le superviseur
(tout passe par le registre, plus jamais par le lanceur). categorie="data" -> collecté AVANT les signaux.
0 variante de signal (n'entame pas le plafond de 12). Persiste sa dédup pour les passes one-shot.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from hl_observer.research_parallel import isolation as ISO
from hl_observer.research_parallel import registre as REG

_RACINE = Path(__file__).resolve().parents[4]        # .../Projet invest
if str(_RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(_RACINE / "tools"))

ETATS_REL = "data/_dedup_etats.json"


def _charger_etats(root: Path) -> dict:
    try:
        return json.loads((ISO.lab_root(root) / ETATS_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _sauver_etats(root: Path, etats: dict) -> None:
    p = ISO.lab_root(root) / ETATS_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps(etats, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _tick(contexte: dict) -> list[dict]:
    """Un cycle de collecte isolée. `contexte` fournit root et (optionnel) un poster mocké pour les tests.
    En prod, le poster REST public réel est utilisé. Rend une ligne de résumé pour le ledger du labo."""
    import collecter_lab_ctx as LC              # import tardif (tools sur le path)
    root = Path(contexte.get("root") or ".")
    poster = contexte.get("poster") or LC._post
    etats = _charger_etats(root)
    res = LC.une_passe(root, poster=poster, etats=etats)
    _sauver_etats(root, etats)
    return [{"kind": "COLLECTE", **res}]


PLUGIN = REG.Plugin(id="DATA_CTX", categorie="data", variantes=(), tick=_tick,
                    exige=("hl_rest_public",))

try:
    REG.enregistrer(PLUGIN)
except ValueError:
    pass          # déjà enregistré (ré-import) : sans effet
