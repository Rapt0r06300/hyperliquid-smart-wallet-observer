"""P1C — identité économique : refs round-trip, clés non ambiguës, hash-chain intacte."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.simulation import economic_identity as EI          # noqa: E402
from hl_observer.simulation import ledger_integrity as LI           # noqa: E402


def test_to_refs_nemet_que_les_champs_presents():
    ident = EI.EconomicIdentity(strategy="copy_vault", coin="BTC", side="LONG")
    assert ident.to_refs() == {"strategy": "copy_vault", "coin": "BTC", "side": "LONG"}


def test_from_refs_round_trip():
    refs = {"strategy": "lead_lag", "intent_id": "i1", "plan_id": "pl1", "position_id": "p1",
            "episode_id": "E:abc", "execution_snapshot_id": "s1", "coin": "ETH", "side": "SHORT"}
    ident = EI.EconomicIdentity.from_refs(refs)
    assert ident.strategy == "lead_lag" and ident.position_id == "p1" and ident.episode_id == "E:abc"
    assert ident.to_refs() == refs


def test_position_key_prefere_lidentite_reelle():
    with_id = EI.EconomicIdentity(position_id="p42", coin="BTC", side="LONG")
    assert with_id.position_key() == "p42"                 # jamais COIN:SIDE quand un id existe


def test_position_key_repli_coin_side_sans_id():
    sans = EI.EconomicIdentity(coin="btc", side="long")
    assert sans.position_key() == "BTC:LONG"


def test_position_key_none_si_meme_le_repli_manque():
    assert EI.EconomicIdentity(strategy="copy_vault").position_key() is None


def test_episode_key_repli_sur_la_position():
    sans_ep = EI.EconomicIdentity(position_id="p1")
    assert sans_ep.episode_key() == "p1"
    avec_ep = EI.EconomicIdentity(position_id="p1", episode_id="E:xyz")
    assert avec_ep.episode_key() == "E:xyz"


def test_episode_id_deterministe_et_distinct():
    a = EI.nouvel_episode_id(session_id="S1", strategy="copy_vault", coin="BTC", side="LONG", ouverture_ref="o1")
    b = EI.nouvel_episode_id(session_id="S1", strategy="copy_vault", coin="BTC", side="LONG", ouverture_ref="o1")
    c = EI.nouvel_episode_id(session_id="S1", strategy="copy_vault", coin="BTC", side="LONG", ouverture_ref="o2")
    assert a == b and a != c and a.startswith("E:")


def test_missing_rend_les_trous_visibles():
    ident = EI.EconomicIdentity(strategy="copy_vault", coin="BTC", side="LONG")
    manques = ident.missing()
    assert "position_id" in manques and "episode_id" in manques and "plan_id" in manques
    assert "strategy" not in manques


def test_stamp_refs_necrase_pas_une_valeur_existante():
    refs = {"position_id": "deja_la", "note": "x"}
    ident = EI.EconomicIdentity(strategy="copy_vault", position_id="autre", coin="BTC")
    out = EI.stamp_refs(refs, ident)
    assert out["position_id"] == "deja_la"       # existant préservé
    assert out["strategy"] == "copy_vault" and out["coin"] == "BTC" and out["note"] == "x"


def test_identite_dans_refs_ne_casse_pas_la_hash_chain():
    # Sceller un événement dont refs porte l'identité complète : verify_chain doit passer.
    ident = EI.EconomicIdentity(strategy="copy_vault", session_id="S1", intent_id="i1",
                                plan_id="pl1", position_id="p1", episode_id="E:abc",
                                coin="BTC", side="LONG", action="OPEN")
    ev = {"event_id": "e1", "event_type": "PaperPositionOpened", "timestamp_ms": 0,
          "coin": "BTC", "side": "LONG", "quantity": 1.0, "refs": ident.to_refs()}
    sealed = LI.seal_chain([ev], session_id="S1")
    verifies = LI.verify_chain(sealed)               # ne lève pas
    assert verifies[0]["refs"]["episode_id"] == "E:abc"
    assert verifies[0]["refs"]["strategy"] == "copy_vault"
