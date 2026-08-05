"""AUD-093 — invalidation de cache COMPLÈTE.

(a) La LATENCE (modèle de stress figé, paramètre de coût pertinent) entre dans la clé de cache :
    un changement du modèle de latence produit une clé différente (le cache périme).
(b) `_hash_donnees` couvre les champs ÉCONOMIQUES (prix / taille / carnet) et parcourt tous les
    événements : une donnée économiquement différente périme le cache (pas seulement coin/ts/signe).
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

import hl_observer.ops.lab_recherche as L   # noqa: E402

T = 1_700_000_000_000
CFG = {"notional_max": 300.0, "fee_bps": 4.5, "min_fill_ratio": 0.85, "seuil_edge_cross_venue_bps": 1.0}


def _evs(px=60000.0, sz=0.3, n=8):
    out = []
    for i in range(n):
        p = px + i * 10.0
        out.append({"coin": "BTC", "px": p, "mid": p, "sz": sz, "signe": 1 if i % 2 == 0 else -1,
                    "ts_ms": T + i * 1000, "vault": "A",
                    "book": {"asks": [[p + 10.0, 5.0]], "bids": [[p - 10.0, 5.0]]}})
    return out


# ---------- (b) digest des données couvre les champs économiques ----------

def test_hash_donnees_change_si_prix_change():
    # mêmes (coin, ts, signe) et même longueur — seul le PRIX diffère : le cache doit périmer.
    assert L._hash_donnees(_evs(px=60000.0)) != L._hash_donnees(_evs(px=61000.0))


def test_hash_donnees_change_si_taille_change():
    # seule la TAILLE (sz) change.
    assert L._hash_donnees(_evs(sz=0.3)) != L._hash_donnees(_evs(sz=0.9))


def test_hash_donnees_change_si_carnet_change():
    a = _evs()
    b = _evs()
    b[0] = {**b[0], "book": {"asks": [[b[0]["px"] + 999.0, 5.0]], "bids": [[b[0]["px"] - 10.0, 5.0]]}}
    assert L._hash_donnees(a) != L._hash_donnees(b)   # profondeur du carnet différente


def test_hash_donnees_stable_si_identique():
    assert L._hash_donnees(_evs()) == L._hash_donnees(_evs())   # déterministe


# ---------- (a) la latence entre dans la clé de cache ----------

def test_cle_cache_change_si_latence_change():
    dh = L._hash_donnees(_evs())
    lat_a = {"delai_sec": 1.0, "coeff_bps_per_sec": 0.20, "cap_bps": 15.0}
    lat_b = {"delai_sec": 1.0, "coeff_bps_per_sec": 0.40, "cap_bps": 15.0}
    assert L._cle_cache(CFG, dh, lat_a) != L._cle_cache(CFG, dh, lat_b)


def test_cle_cache_defaut_reflete_le_modele_latence(monkeypatch):
    dh = L._hash_donnees(_evs())
    base = L._cle_cache(CFG, dh)                          # défaut = _LATENCE_STRESS du module
    assert base == L._cle_cache(CFG, dh, L._LATENCE_STRESS)
    monkeypatch.setattr(L, "_LATENCE_STRESS", {**L._LATENCE_STRESS, "coeff_bps_per_sec": 0.99})
    assert L._cle_cache(CFG, dh) != base                 # modèle de latence changé -> clé (cache) différente
