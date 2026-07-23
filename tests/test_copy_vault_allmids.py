"""Copy-Vaults (rectif 23/07) : on PROUVE que le signal détecte le changement d'exposition PAR COIN
d'un vault suivi et le price au prix HL exécutable — BBO synchro prioritaire, sinon cache allMids
(tous-coins, frais < 60 s). Le collecteur allMids parse/écrit proprement. Aucune exécution réelle."""
from __future__ import annotations

import json

from hl_observer.experimental import moteur_paper as MP
from hl_observer.experimental.signaux import signaux_vaults, _allmids, SPREAD_ESTIME_ALT_BPS
import tools.collecter_allmids as CA


def _ecrire(root, snaps, allmids=None, ts_allmids_ms=None):
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "data" / "vault_snapshots.jsonl").write_text(
        "\n".join(json.dumps(s) for s in snaps), encoding="utf-8")
    (root / "config" / "frais_venues.json").write_text(json.dumps({"hl_taker_bps": 3.5, "bin_taker_bps": 4.5}))
    if allmids is not None:
        (root / "runtime" / "data" / "hl_allmids.json").write_text(
            json.dumps({"ts_ms": ts_allmids_ms, "mids": allmids}))


# ─────────────────────────────── collecteur allMids ───────────────────────────────

def test_parser_allmids_tolerant():
    assert CA.parser_allmids({"HYPE": "20.5", "BTC": "60000"}) == {"HYPE": 20.5, "BTC": 60000.0}
    assert CA.parser_allmids({"mids": {"sol": "150"}}) == {"SOL": 150.0}      # enveloppe + upper
    assert CA.parser_allmids({"X": "nan?", "Y": "-3", "Z": "0"}) == {}        # illisible / <=0 ignoré


def test_ecrire_cache_atomique(tmp_path):
    n = CA.ecrire_cache(tmp_path, {"HYPE": 20.0, "FARTCOIN": 1.23})
    assert n == 2
    d = json.loads((tmp_path / CA.SORTIE).read_text())
    assert d["n"] == 2 and d["mids"]["HYPE"] == 20.0 and "ts_ms" in d


def test_une_passe_ecrit_le_cache(tmp_path):
    n = CA.une_passe(tmp_path, post_allmids=lambda: {"HYPE": "20", "NEO": "12.5"})
    assert n == 2 and (tmp_path / CA.SORTIE).exists()
    assert CA.une_passe(tmp_path, post_allmids=lambda: (_ for _ in ()).throw(OSError())) == 0  # réseau KO -> 0


# ─────────────────────────────── fraîcheur allMids ───────────────────────────────

def test_allmids_ignore_si_perime(tmp_path):
    now = 1_000_000_000_000.0
    _ecrire(tmp_path, [], allmids={"HYPE": 20.0}, ts_allmids_ms=now - 2000)
    assert _allmids(tmp_path, now_ms=now).get("HYPE") == 20.0           # frais (<60 s)
    _ecrire(tmp_path, [], allmids={"HYPE": 20.0}, ts_allmids_ms=now - 120_000)
    assert _allmids(tmp_path, now_ms=now) == {}                          # périmé -> ignoré


# ─────────────────────────────── détection PAR COIN + prix allMids ───────────────────────────────

def test_copy_vault_detecte_move_par_coin_et_price_via_allmids(tmp_path):
    now = 1_000_000_000_000.0
    snaps = [
        {"vault": "0xAAA", "ts_ms": now - 300_000, "nav_usd": 100_000,
         "positions": [{"coin": "HYPE", "szi": 0.0, "entryPx": 20.0}]},
        {"vault": "0xAAA", "ts_ms": now - 5_000, "nav_usd": 100_000,
         "positions": [{"coin": "HYPE", "szi": 1000.0, "entryPx": 20.0}]},   # +20 000 $ = 20 % du NAV
    ]
    _ecrire(tmp_path, snaps, allmids={"HYPE": 20.0}, ts_allmids_ms=now - 2000)
    sigs, refus = signaux_vaults(tmp_path, now_ms=now)
    assert len(sigs) == 1 and not refus
    s = sigs[0]
    assert s.coin == "HYPE" and s.sens == 1 and s.meta["src_prix"] == "allmids"
    assert s.prix_entree == round(20.0 * (1 + SPREAD_ESTIME_ALT_BPS / 1e4), 6)  # côté taker
    assert s.meta["observation_lag_ms"] == 5000 and s.ts_signal_ms == now       # entrée au prix FRAIS
    # passe le barème exigeant SANS OOS (fraîcheur + exécutable + gros edge + pas de centimes)
    assert MP.admettre(s, MP.charger_store(tmp_path), now_ms=now) == (True, None)


def test_copy_vault_refuse_move_trop_faible(tmp_path):
    now = 1_000_000_000_000.0
    snaps = [
        {"vault": "0xBBB", "ts_ms": now - 300_000, "nav_usd": 100_000,
         "positions": [{"coin": "HYPE", "szi": 0.0, "entryPx": 20.0}]},
        {"vault": "0xBBB", "ts_ms": now - 5_000, "nav_usd": 100_000,
         "positions": [{"coin": "HYPE", "szi": 50.0, "entryPx": 20.0}]},      # +1 000 $ = 1 % du NAV < 5 %
    ]
    _ecrire(tmp_path, snaps, allmids={"HYPE": 20.0}, ts_allmids_ms=now - 2000)
    sigs, refus = signaux_vaults(tmp_path, now_ms=now)
    assert not sigs and refus and refus[0]["motif"] == "CHANGEMENT_TROP_FAIBLE"


def test_copy_vault_refuse_si_coin_non_executable(tmp_path):
    now = 1_000_000_000_000.0
    snaps = [
        {"vault": "0xCCC", "ts_ms": now - 300_000, "nav_usd": 100_000,
         "positions": [{"coin": "OBSCURE", "szi": 0.0, "entryPx": 5.0}]},
        {"vault": "0xCCC", "ts_ms": now - 5_000, "nav_usd": 100_000,
         "positions": [{"coin": "OBSCURE", "szi": 8000.0, "entryPx": 5.0}]},  # gros move mais aucun prix HL
    ]
    _ecrire(tmp_path, snaps, allmids={"HYPE": 20.0}, ts_allmids_ms=now - 2000)  # OBSCURE absent d'allMids
    sigs, refus = signaux_vaults(tmp_path, now_ms=now)
    assert not sigs and refus and refus[0]["motif"] == "PRIX_NON_EXECUTABLE_HL"
