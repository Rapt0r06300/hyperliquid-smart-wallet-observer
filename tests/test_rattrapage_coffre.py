"""Le rattrapage se règle sur le coffre (demande du 22/11/2026)."""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.ops import rattrapage_coffre as RC  # noqa: E402

H = 3_600_000
J = 86_400_000
NOW = 1_800_000_000_000


def test_un_curseur_qui_promet_plus_que_le_coffre_est_recule() -> None:
    couverture = {"1h": {"BTC": [NOW - 100 * H, NOW - 10 * H], "ETH": [NOW - 100 * H, NOW - H]}}
    curseur = {"1h": {"BTC": NOW - H, "ETH": NOW - H, "SOL": NOW - H}}
    c = {(x["coin"], x["motif"]): x for x in RC.corrections(curseur, couverture, now_ms=NOW)}
    assert set(c) == {("BTC", "FIN_ABSENTE_DU_COFFRE"), ("SOL", "RIEN_AU_COFFRE")}     # ETH : à jour
    assert c[("BTC", "FIN_ABSENTE_DU_COFFRE")]["nouveau_ms"] == NOW - 10 * H
    neuf = RC.appliquer(curseur, list(c.values()))
    assert neuf["1h"] == {"BTC": NOW - 10 * H, "ETH": NOW - H}                        # SOL repart de zéro
    assert all(neuf["1h"][k] <= curseur["1h"][k] for k in neuf["1h"])                  # jamais avancé


def test_une_marque_de_plancher_n_est_pas_une_donnee_promise() -> None:
    """Faux positif réel : 211 coins « à 1 106 jours » = origine atteinte, pas 129 015 jours perdus."""
    couverture = {"funding": {"XMR": [NOW - 300 * J, NOW - H], "BTC": [NOW - 300 * J, NOW - H]}}
    curseur = {"funding_ancien": {"XMR": NOW - 1106 * J,                               # plancher
                                  "BTC": NOW - 800 * J}}                               # vraie profondeur promise
    c = RC.corrections(curseur, couverture, now_ms=NOW)
    assert [(x["coin"], x["motif"]) for x in c] == [("BTC", "PROFONDEUR_ABSENTE_DU_COFFRE")]
    assert c[0]["nouveau_ms"] == NOW - 300 * J


def test_un_coffre_illisible_ne_recule_rien(tmp_path) -> None:
    assert RC.corrections({"1h": {"BTC": NOW}}, {}, now_ms=NOW) == []
    assert RC.couverture_du_coffre(tmp_path) == {}


def test_la_couverture_se_lit_dans_les_shards_et_ignore_la_bougie_du_direct(tmp_path) -> None:
    shards = tmp_path / "runtime" / "coffre_certifie" / "local" / "shards" / "candle"
    shards.mkdir(parents=True)
    lignes = [{"coin": "BTC", "interval": "1h", "open_ts_ms": NOW - 5 * H, "source": "REST_BACKFILL_1H"},
              {"coin": "BTC", "interval": "1h", "open_ts_ms": NOW - 2 * H, "source": "REST_BACKFILL_1H"},
              {"coin": "BTC", "interval": "1m", "open_ts_ms": NOW, "source": "HYPERLIQUID_CANDLE_WS"},
              {"coin": "BTC", "interval": "1h", "open_ts_ms": NOW, "source": "HYPERLIQUID_CANDLE_WS"}]   # le direct, même en 1 h
    chemin = shards / "lot__candles_1h.jsonl.gz"
    with gzip.open(chemin, "wt", encoding="utf-8") as f:
        f.write("".join(json.dumps(x) + "\n" for x in lignes))
    index = {"shards": [{"famille": "candle", "shard": str(chemin.relative_to(tmp_path)), "shard_sha256": "a"}]}
    (tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").write_text(json.dumps(index), encoding="utf-8")
    assert RC.couverture_du_coffre(tmp_path) == {"1h": {"BTC": [NOW - 5 * H, NOW - 2 * H]}}
    chemin.unlink()                                                    # 2e lecture : le cache suffit
    assert RC.couverture_du_coffre(tmp_path) == {"1h": {"BTC": [NOW - 5 * H, NOW - 2 * H]}}


def test_ce_qui_attend_le_scellage_n_est_pas_redemande(tmp_path) -> None:
    """Rattrapage interrompu : la page est sur le disque, pas au coffre. Ne pas la payer deux fois."""
    ruban = tmp_path / "funding.jsonl"
    ruban.write_text("".join(json.dumps({"coin": "BTC", "ts_ms": NOW - k * H}) + "\n" for k in range(1, 4)),
                     encoding="utf-8")
    a_faire = RC.corrections({"funding": {"BTC": NOW - H, "ETH": NOW - H}},
                             {"funding": {"BTC": [NOW - 900 * H, NOW - 500 * H], "ETH": [NOW - 900 * H, NOW - 500 * H]}},
                             now_ms=NOW)
    assert {c["coin"] for c in a_faire} == {"BTC", "ETH"}
    locaux = RC.couverture_des_rubans(tmp_path, {"funding"}, {"funding": Path("funding.jsonl")})
    garder, attente = RC.ecarter_ce_qui_attend_le_scellage(a_faire, locaux)
    assert [c["coin"] for c in garder] == ["ETH"] and [c["coin"] for c in attente] == ["BTC"]
