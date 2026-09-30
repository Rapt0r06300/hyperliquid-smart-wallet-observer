"""AUD-088 — l'espace de recherche du moteur adaptatif (ESPACE_DEFAUT) a une IDENTITÉ VERSIONNÉE.

`empreinte_espace_defaut()` : empreinte STABLE et DÉTERMINISTE, qui CHANGE si l'espace change (testé
avec un espace modifié EN MÉMOIRE). On prouve aussi que `search_space` — jusqu'ici orphelin — est
désormais IMPORTÉ et UTILISÉ par le runtime (`rechercher` expose l'empreinte via search_space).
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

import hl_observer.ops.lab_recherche as L         # noqa: E402
from hl_observer.research import search_space     # noqa: E402

T = 1_700_000_000_000


def _evs(n=8):
    out = []
    for i in range(n):
        p = 60000.0 + i * 10.0
        out.append({"coin": "BTC", "px": p, "mid": p, "sz": 0.3, "signe": 1 if i % 2 == 0 else -1,
                    "ts_ms": T + i * 1000, "vault": "A",
                    "book": {"asks": [[p + 10.0, 5.0]], "bids": [[p - 10.0, 5.0]]}})
    return out


def test_empreinte_stable_et_deterministe():
    a = L.empreinte_espace_defaut()
    assert isinstance(a, str) and a
    assert a == L.empreinte_espace_defaut()                        # stable / déterministe
    assert L.empreinte_espace_defaut(dict(L.ESPACE_DEFAUT)) == a   # copie -> même empreinte


def test_empreinte_change_si_espace_change():
    base = L.empreinte_espace_defaut()
    modifie = {k: list(v) for k, v in L.ESPACE_DEFAUT.items()}
    modifie["notional_max"] = modifie["notional_max"] + [999.0]    # espace modifié EN MÉMOIRE
    assert L.empreinte_espace_defaut(modifie) != base              # l'empreinte périme


def test_empreinte_insensible_a_l_ordre_des_valeurs():
    modifie = {k: list(v) for k, v in L.ESPACE_DEFAUT.items()}
    modifie["fee_bps"] = list(reversed(modifie["fee_bps"]))        # même SET, ordre inversé
    assert L.empreinte_espace_defaut(modifie) == L.empreinte_espace_defaut()


def test_search_space_cable_au_runtime():
    # `rechercher` expose l'empreinte -> search_space n'est plus orphelin.
    r = L.rechercher(_evs(), budget=2, leader_equity_defaut=100000.0, source="SYNTHETIQUE")
    assert r["espace_hash"] == L.empreinte_espace_defaut()
    # l'empreinte est bien produite PAR le module versionné search_space.
    attendu = search_space.hash_espace(
        {"execution": ["%s=%s" % (k, ",".join(sorted(str(x) for x in L.ESPACE_DEFAUT[k])))
                       for k in sorted(L.ESPACE_DEFAUT)]})
    assert L.empreinte_espace_defaut() == attendu
