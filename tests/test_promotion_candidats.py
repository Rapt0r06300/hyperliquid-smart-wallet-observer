"""Promotion des candidats observés (rectif Flo 23/07) : score fréquence/copyabilité/shadow depuis le
journal de fills, promotion des 2 meilleurs en mini-PROBE (5-10 $) SI shadow net>0. Aucun réseau."""
from __future__ import annotations

import json

from hl_observer.experimental import promotion_candidats as PC


def _journal(root, lignes):
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "data" / "fills_journal.jsonl").write_text("\n".join(json.dumps(x) for x in lignes))


def _fills_live(root, lignes):
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    causal = []
    for raw in lignes:
        fill = dict(raw)
        ts_ms = fill.get("fill_ts_ms") or fill.get("ts_ms") or fill.get("time")
        fill.setdefault("source", "LIVE_WS")
        fill.setdefault("isSnapshot", False)
        fill.setdefault("received_at_ms", ts_ms + 100 if ts_ms else None)
        causal.append(fill)
    (root / "runtime" / "data" / "vault_fills_live.jsonl").write_text(
        "\n".join(json.dumps(x) for x in causal)
    )


def test_scorer_et_promouvoir(tmp_path):
    T = 1_000_000_000_000
    winner = "0x1111111111111111111111111111111111111111"
    flat = "0x2222222222222222222222222222222222222222"
    # WIN : 6 OPEN sur DOT (coin PROBE), tape montante -> shadow>0. FLAT : 6 OPEN mais tape plate -> shadow 0.
    lignes = []
    for i in range(6):
        lignes.append({"vault": winner, "coin": "DOT", "dir": "Open Long", "fill_ts_ms": T + i * 60000})
        lignes.append({"vault": flat, "coin": "DOT", "dir": "Open Long", "fill_ts_ms": T + i * 60000})
    _fills_live(tmp_path, lignes)
    tape = {"DOT": [(T + i * 60000, 100.0 + i * 0.1) for i in range(200)]}   # +~10 bps/min -> shadow>0
    scores = PC.scorer_candidats(tmp_path, coins_probe={"DOT"}, tape=tape,
                                 candidats_observes={winner, flat})
    assert len(scores) == 2 and all(s["copyabilite"] == 1.0 for s in scores)   # tous OPEN sur DOT (PROBE)
    promus = PC.promouvoir(scores)
    assert winner in promus and promus[winner]["notional_usd"] == PC.NOTIONAL_MINI_USD
    assert 5.0 <= promus[winner]["notional_usd"] <= 10.0


def test_pas_de_promotion_sans_shadow_positif(tmp_path):
    T = 1_000_000_000_000
    vault = "0x3333333333333333333333333333333333333333"
    _fills_live(tmp_path, [{"vault": vault, "coin": "DOT", "dir": "Open Long", "fill_ts_ms": T + i * 60000} for i in range(6)])
    tape = {"DOT": [(T + i * 60000, 100.0) for i in range(200)]}             # plat -> shadow ~0 -> pas promu
    scores = PC.scorer_candidats(tmp_path, coins_probe={"DOT"}, tape=tape, candidats_observes={vault})
    assert PC.promouvoir(scores) == {}                                       # deny-by-default


def test_shadow_respecte_le_sens_short(tmp_path):
    """Une baisse favorise un short et défavorise un long au même instant."""
    T = 1_000_000_000_000
    short = "0x1111111111111111111111111111111111111111"
    long = "0x2222222222222222222222222222222222222222"
    lignes = []
    for i in range(6):
        ts = T + i * 60_000
        lignes.append({"vault": short, "coin": "DOT", "dir": "Open Short", "fill_ts_ms": ts})
        lignes.append({"vault": long, "coin": "DOT", "dir": "Open Long", "fill_ts_ms": ts})
    _fills_live(tmp_path, lignes)
    tape = {"DOT": [(T + i * 60_000, 120.0 - i * 0.1) for i in range(200)]}

    scores = PC.scorer_candidats(
        tmp_path,
        coins_probe={"DOT"},
        tape=tape,
        candidats_observes={short, long},
        frais_bps=1.0,
    )
    par_vault = {score["vault"]: score for score in scores}

    assert par_vault[short]["shadow_net_bps"] > 0
    assert par_vault[long]["shadow_net_bps"] < 0
    assert short in PC.promouvoir(scores)
    assert long not in PC.promouvoir(scores)


def test_shadow_paire_respecte_le_sens_short(tmp_path):
    T = 1_000_000_000_000
    vault = "0x6666666666666666666666666666666666666666"
    _fills_live(
        tmp_path,
        [
            {"vault": vault, "coin": "LDO", "dir": "Open Short", "fill_ts_ms": T}
        ],
    )
    tape = {"LDO": [(T + i * 60_000, 100.0 - i * 0.1) for i in range(120)]}

    paires = PC.scorer_paires(tmp_path, tape=tape, frais_bps=1.0)

    assert paires[f"{vault}|LDO"]["shadow_net_bps"] > 0
    assert paires[f"{vault}|LDO"]["positive"] is True


def test_flux_live_canonique_evite_troncature_et_triple_comptage(tmp_path):
    T = 1_000_000_000_000
    vault = "0x4444444444444444444444444444444444444444"
    fill = {
        "vault": vault,
        "coin": "DOT",
        "dir": "Open Long",
        "ts_ms": T,
        "tid": 42,
    }
    _fills_live(tmp_path, [fill])
    _journal(
        tmp_path,
        [
            {"vault": vault[:12], "coin": "DOT", "dir": "Open Long", "fill_ts_ms": T, "cohorte": cohorte}
            for cohorte in ("ALPHA", "PROBE", "RAW_PROBE")
        ],
    )
    tape = {"DOT": [(T + i * 60_000, 100.0 + i * 0.1) for i in range(120)]}

    scores = PC.scorer_candidats(
        tmp_path,
        coins_probe={"DOT"},
        tape=tape,
        candidats_observes={vault},
        frais_bps=1.0,
    )

    assert len(scores) == 1
    assert scores[0]["vault"] == vault
    assert scores[0]["n_open"] == 1
    assert scores[0]["shadow_net_bps"] is not None


def test_repli_journal_deduplique_les_cohortes(tmp_path):
    T = 1_000_000_000_000
    vault = "0x5555555555555555555555555555555555555555"
    _journal(
        tmp_path,
        [
            {
                "vault": vault,
                "coin": "DOT",
                "dir": "Open Long",
                "fill_ts_ms": T,
                "tid": 99,
                "cohorte": cohorte,
                "source": "LIVE_WS",
                "isSnapshot": False,
                "recu_ms": T + 100,
            }
            for cohorte in ("ALPHA", "PROBE", "RAW_PROBE")
        ],
    )

    scores = PC.scorer_candidats(
        tmp_path,
        coins_probe={"DOT"},
        candidats_observes={vault},
    )

    assert len(scores) == 1
    assert scores[0]["n_open"] == 1


def test_scorer_paires_meme_hors_table(tmp_path):
    """Shadow PAR PAIRE vault+coin depuis le journal, même hors table PROBE. Paire montante -> positive."""
    T = 1_000_000_000_000
    vault = "0x7777777777777777777777777777777777777777"
    _fills_live(tmp_path, [{"vault": vault, "coin": "LDO", "dir": "Open Long",
                            "fill_ts_ms": T + i * 60000} for i in range(4)])
    tape = {"LDO": [(T + i * 60000, 100.0 + i * 0.1) for i in range(200)]}   # monte -> shadow net>0
    paires = PC.scorer_paires(tmp_path, tape=tape, frais_bps=1.0)
    assert f"{vault}|LDO" in paires and paires[f"{vault}|LDO"]["positive"] is True
    assert paires[f"{vault}|LDO"]["n_open"] == 4


def test_construire_ecrit_et_relit(tmp_path):
    T = 1_000_000_000_000
    vault = "0x8888888888888888888888888888888888888888"
    _fills_live(tmp_path, [{"vault": vault, "coin": "DOT", "dir": "Open Long", "fill_ts_ms": T + i * 60000} for i in range(6)])
    tape = {"DOT": [(T + i * 60000, 100.0 + i * 0.1) for i in range(200)]}
    PC.construire(tmp_path, coins_probe={"DOT"}, tape=tape, candidats_observes={vault})
    assert vault in PC.charger_promus(tmp_path)


def test_snapshot_reste_observe_mais_ne_peut_pas_etre_promu(tmp_path):
    T = 1_000_000_000_000
    vault = "0x9999999999999999999999999999999999999999"
    _fills_live(
        tmp_path,
        [{"vault": vault, "coin": "DOT", "dir": "Open Long", "ts_ms": T + i * 60_000,
          "isSnapshot": True} for i in range(6)],
    )

    scores = PC.scorer_candidats(
        tmp_path, coins_probe={"DOT"}, candidats_observes={vault}
    )

    assert scores[0]["n_open_observed"] == 6
    assert scores[0]["n_open"] == 0
    assert scores[0]["causal_rejections"] == {"SNAPSHOT_OR_UNKNOWN": 6}
    assert PC.promouvoir(scores) == {}


def test_fill_recu_trop_tard_ne_produit_pas_edge(tmp_path):
    T = 1_000_000_000_000
    vault = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    _fills_live(
        tmp_path,
        [{"vault": vault, "coin": "DOT", "dir": "Open Long", "ts_ms": T,
          "received_at_ms": T + 30_001}],
    )
    tape = {"DOT": [(T + i * 60_000, 100.0 + i * 0.1) for i in range(120)]}

    paires = PC.scorer_paires(tmp_path, tape=tape, frais_bps=1.0)
    pair = paires[f"{vault}|DOT"]

    assert pair["n_open_observed"] == 1
    assert pair["n_open"] == 0
    assert pair["n_shadow"] == 0
    assert pair["positive"] is False
    assert pair["causal_rejections"] == {"RECEIVE_LAG_TOO_HIGH": 1}


def test_cibles_prix_shadow_gardent_seulement_les_open_causaux_recents(tmp_path):
    T = 1_000_000_000_000
    vault = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    _fills_live(
        tmp_path,
        [
            {"vault": vault, "coin": "BTC", "dir": "Open Long", "ts_ms": T},
            {"vault": vault, "coin": "ETH", "dir": "Open Short", "ts_ms": T + 1_000},
            {"vault": vault, "coin": "SOL", "dir": "Close Long", "ts_ms": T + 2_000},
            {"vault": vault, "coin": "HYPE", "dir": "Open Long", "ts_ms": T + 3_000,
             "isSnapshot": True},
        ],
    )

    targets = PC.cibles_prix_shadow(tmp_path, max_evenements=1)

    assert targets == {"ETH": [T + 1_000]}
