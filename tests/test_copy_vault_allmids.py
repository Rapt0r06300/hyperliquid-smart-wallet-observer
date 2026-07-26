"""Copy-Vaults (rectif Flo 23/07) — DISCIPLINE : allMids ne sert QU'À détecter/pricer grossièrement ;
AUCUNE position n'est admise sans (a) L2 HL frais sur le coin (profondeur/VWAP + coût de sortie) ET
(b) un edge de copie MESURÉ et gelé (jamais inventé). On prouve les refus honnêtes ET l'ouverture
quand les deux conditions réelles sont réunies. Le collecteur allMids parse/écrit/archive proprement.
Aucune exécution réelle."""
from __future__ import annotations

import json

from hl_observer.experimental import moteur_paper as MP
from hl_observer.experimental.signaux import signaux_vaults, _allmids, COINS_BOUGES_RELPATH
from hl_observer.experimental.copy_edge_forward import geler
import tools.collecter_allmids as CA


def _base(root, snaps, *, carnet=None, gele=False, allmids=None, ts_allmids_ms=None,
          retenus=("0xAAA",), now=1_000_000_000_000.0):
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "data" / "vault_snapshots.jsonl").write_text(
        "\n".join(json.dumps(s) for s in snaps), encoding="utf-8")
    (root / "config" / "frais_venues.json").write_text(json.dumps({"hl_taker_bps": 3.5, "bin_taker_bps": 4.5}))
    if retenus is not None:                                         # DENY-BY-DEFAULT : sans score, rien n'est copié
        (root / "runtime" / "data" / "vaults_scores.json").write_text(json.dumps({"retenus": list(retenus)}))
    if carnet is not None:
        (root / "runtime" / "data" / "carnet_venues.jsonl").write_text(
            "\n".join(json.dumps(c) for c in carnet), encoding="utf-8")
    if allmids is not None:
        (root / "runtime" / "data" / "hl_allmids.json").write_text(json.dumps({"ts_ms": ts_allmids_ms, "mids": allmids}))
    if gele:
        geler(root, horizon_ms=900_000.0, edge_brut_bps=45.0, edge_net_mesure_bps=33.0)


def _snaps_move(vault="0xAAA", coin="HYPE", szi0=0.0, szi1=1000.0, px=20.0, nav=100_000, now=1_000_000_000_000.0):
    return [{"vault": vault, "ts_ms": now - 300_000, "nav_usd": nav,
             "positions": [{"coin": coin, "szi": szi0, "entryPx": px}]},
            {"vault": vault, "ts_ms": now - 5_000, "nav_usd": nav,
             "positions": [{"coin": coin, "szi": szi1, "entryPx": px}]}]


def _carnet(coin="HYPE", bid=19.99, ask=20.01, taille=5000.0, now=1_000_000_000_000.0):
    return [{"coin": coin, "hl_bid": bid, "hl_ask": ask, "bin_bid": bid, "bin_ask": ask,
             "taille_min_usd": taille, "collecte_ts": now / 1000.0}]


# ─────────────────────────────── collecteur allMids (parse / cache / tape) ───────────────────────────────

def test_parser_allmids_tolerant():
    assert CA.parser_allmids({"HYPE": "20.5", "BTC": "60000"}) == {"HYPE": 20.5, "BTC": 60000.0}
    assert CA.parser_allmids({"mids": {"sol": "150"}}) == {"SOL": 150.0}
    assert CA.parser_allmids({"X": "nan?", "Y": "-3", "Z": "0"}) == {}


def test_une_passe_ecrit_cache_et_tape(tmp_path):
    n = CA.une_passe(tmp_path, post_allmids=lambda: {"HYPE": "20", "NEO": "12.5"}, archiver_tape=True)
    assert n == 2 and (tmp_path / CA.SORTIE).exists() and (tmp_path / CA.TAPE).exists()
    tape = (tmp_path / CA.TAPE).read_text().splitlines()
    assert len(tape) == 1 and json.loads(tape[0])["mids"]["HYPE"] == 20.0
    assert CA.une_passe(tmp_path, post_allmids=lambda: (_ for _ in ()).throw(OSError())) == 0


def test_allmids_ignore_si_perime(tmp_path):
    now = 1_000_000_000_000.0
    _base(tmp_path, [], allmids={"HYPE": 20.0}, ts_allmids_ms=now - 2000)
    assert _allmids(tmp_path, now_ms=now).get("HYPE") == 20.0
    _base(tmp_path, [], allmids={"HYPE": 20.0}, ts_allmids_ms=now - 120_000)
    assert _allmids(tmp_path, now_ms=now) == {}


# ─────────────────────────────── discipline d'admission ───────────────────────────────

def test_sans_edge_mesure_NO_TRADE_meme_avec_carnet(tmp_path):
    """Barre (b) : sans config d'edge gelée, on n'ouvre RIEN même si le L2 est là (pas d'edge inventé)."""
    now = 1_000_000_000_000.0
    _base(tmp_path, _snaps_move(), carnet=_carnet(), gele=False)
    sigs, refus = signaux_vaults(tmp_path, now_ms=now)
    assert not sigs and refus[0]["motif"] == "EDGE_NON_MESURE"


def test_sans_carnet_frais_NO_TRADE_et_coin_file_au_carnet(tmp_path):
    """Barre (a) : edge gelé mais L2 absent -> CARNET_ABSENT, et le coin est ABONNÉ au carnet."""
    now = 1_000_000_000_000.0
    _base(tmp_path, _snaps_move(), carnet=[], gele=True)                 # carnet vide -> aucun L2 <1 s
    sigs, refus = signaux_vaults(tmp_path, now_ms=now)
    assert not sigs and refus[0]["motif"] == "L2_INDISPONIBLE_1S"
    files = json.loads((tmp_path / COINS_BOUGES_RELPATH).read_text())["coins"]
    assert "HYPE" in files                                               # abonnement dynamique


def test_ouvre_quand_L2_frais_ET_edge_mesure(tmp_path):
    """Les DEUX conditions réunies : prix/profondeur = L2 réel, edge = mesuré − coût L2, admission OK."""
    now = 1_000_000_000_000.0
    _base(tmp_path, _snaps_move(), carnet=_carnet(bid=19.99, ask=20.01, taille=5000.0), gele=True)
    sigs, refus = signaux_vaults(tmp_path, now_ms=now)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.coin == "HYPE" and s.sens == 1 and s.meta["src_prix"] == "carnet"
    assert s.prix_entree == 20.01                                        # ask L2 réel (taker long)
    assert s.notional_usd == 150.0                                       # min(cible 150, profondeur 5000)
    assert s.meta["fill_partiel"] is False and s.meta["l2_age_ms"] <= 1000   # L2 < 1 s
    # edge net = edge_brut mesuré (45) − coût A/R L2 réel (spread+2×slippage+frais) ; mesuré, pas inventé
    assert s.meta["edge_brut_mesure_bps"] == 45.0 and s.edge_estime_bps < 45.0
    assert MP.admettre(s, MP.charger_store(tmp_path), now_ms=now) == (True, None)


def test_profondeur_insuffisante_NO_TRADE(tmp_path):
    """Dimensionnement par la profondeur : un L2 trop mince -> LIQUIDITE_INSUFFISANTE (jamais forcé)."""
    now = 1_000_000_000_000.0
    _base(tmp_path, _snaps_move(), carnet=_carnet(taille=5.0), gele=True)   # 5 $ de profondeur
    sigs, refus = signaux_vaults(tmp_path, now_ms=now)
    assert not sigs and refus[0]["motif"] == "LIQUIDITE_INSUFFISANTE"


def test_move_trop_faible_NO_TRADE(tmp_path):
    now = 1_000_000_000_000.0
    _base(tmp_path, _snaps_move(szi1=50.0), carnet=_carnet(), gele=True)     # +1 % du NAV < 5 %
    sigs, refus = signaux_vaults(tmp_path, now_ms=now)
    assert not sigs and refus[0]["motif"] == "CHANGEMENT_TROP_FAIBLE"


def test_deny_by_default_sans_scoring(tmp_path):
    """Rectif Flo : PAS de repli permissif. Sans fichier de scores, on ne copie RIEN, même move+L2+edge."""
    now = 1_000_000_000_000.0
    _base(tmp_path, _snaps_move(), carnet=_carnet(), gele=True, retenus=None)   # aucun vaults_scores.json
    sigs, refus = signaux_vaults(tmp_path, now_ms=now)
    assert not sigs and not refus                                       # deny silencieux : aucun vault retenu


def test_l2_trop_vieux_refuse(tmp_path):
    """Un carnet vieux de > 1 s n'est PAS un L2 admissible (rectif Flo : 120 s trop vieux)."""
    now = 1_000_000_000_000.0
    vieux = [{"coin": "HYPE", "hl_bid": 19.99, "hl_ask": 20.01, "taille_min_usd": 5000.0,
              "collecte_ts": now / 1000.0 - 30}]                         # 30 s -> périmé
    _base(tmp_path, _snaps_move(), carnet=vieux, gele=True)
    sigs, refus = signaux_vaults(tmp_path, now_ms=now)
    assert not sigs and refus[0]["motif"] == "L2_INDISPONIBLE_1S"


def test_lecteur_l2_on_demand(tmp_path):
    """Lecture L2 À LA DEMANDE (WS/REST au signal) : source la plus fraîche, admet quand fournie."""
    now = 1_000_000_000_000.0
    _base(tmp_path, _snaps_move(), carnet=[], gele=True)                 # pas de carnet
    l2 = lambda coin: {"hl_bid": 19.99, "hl_ask": 20.01, "depth_usd": 4000.0, "age_ms": 50}
    sigs, _ = signaux_vaults(tmp_path, now_ms=now, lecteur_l2=l2)
    assert len(sigs) == 1 and sigs[0].meta["src_prix"] == "on_demand" and sigs[0].meta["l2_age_ms"] == 50


def test_leader_close_declenche_sortie(tmp_path):
    """Suivi réel du leader (LOT14 P1/P2/P3) : _etat_leader classe AUCUN/CLOSE/REDUCE depuis un snapshot
    COMPLET, FRAIS et POSTÉRIEUR à l'entrée (taille SIGNÉE, dédup snapshot par le runner)."""
    from hl_observer.experimental.runner import _etat_leader
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    snap = tmp_path / "runtime" / "data" / "vault_snapshots.jsonl"
    now = 1_000_000.0
    pos = {"coin": "HYPE", "moteur": "copy_vault", "ts_ouverture_ms": now - 10_000, "entry_leader_szi": 1000.0,
           "last_leader_szi_applied": 1000.0, "meta": {"vault": "0xAAA", "coin": "HYPE", "szi_apres": 1000.0}}

    def w(szi, sid):
        positions = [{"coin": "HYPE", "szi": szi}] if szi else []
        snap.write_text(json.dumps({"vault": "0xAAA", "ts_ms": int(now - 1000), "nav_usd": 100000.0,
                                    "positions": positions, "snapshot_id": sid}))
    w(1000.0, "s1"); assert _etat_leader(pos, tmp_path, now_ms=now)["action"] == "AUCUN"     # leader tient
    w(0.0, "s2");    assert _etat_leader(pos, tmp_path, now_ms=now)["action"] == "CLOSE"     # leader a clos
    w(300.0, "s3");  assert _etat_leader(pos, tmp_path, now_ms=now)["action"] == "REDUCE"    # réduit à 30 %


def test_filtre_de_retention_du_score(tmp_path):
    """Seul un vault RETENU par le score est copié : un vault absent des retenus est ignoré en silence."""
    now = 1_000_000_000_000.0
    _base(tmp_path, _snaps_move(vault="0xAAA"), carnet=_carnet(), gele=True)
    # score qui NE retient PAS 0xAAA -> aucun signal
    (tmp_path / "runtime" / "data" / "vaults_scores.json").write_text(json.dumps({"retenus": ["0xAUTRE"]}))
    sigs, refus = signaux_vaults(tmp_path, now_ms=now)
    assert not sigs and not any(r.get("vault") == "0xAAA"[:10] for r in refus)   # ignoré, pas même un refus
    # score qui RETIENT 0xAAA -> le signal repart
    (tmp_path / "runtime" / "data" / "vaults_scores.json").write_text(json.dumps({"retenus": ["0xAAA"]}))
    sigs2, _ = signaux_vaults(tmp_path, now_ms=now)
    assert len(sigs2) == 1 and sigs2[0].meta["vault"] == "0xAAA"
