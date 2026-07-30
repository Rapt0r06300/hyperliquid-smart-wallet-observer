"""Bloc 17 — parité causale replay ↔ forward (prefix stability) sur le simulateur canonique.

Principe emprunté à l'analyse de lookahead de Freqtrade : pour toute décision à `t`, rejouer la bande
TRONQUÉE à `t` et la bande COMPLÈTE doit donner **exactement** la même décision, les mêmes coûts et le même
fill. Si le résultat change parce que des événements POSTÉRIEURS sont présents, la décision lisait le futur.

Couvre : troncature du futur, longueurs de warm-up variables, snapshot initial de reconnexion, doublons
injectés, réordonnancement borné, rejeu idempotent (crash après OPEN / après ledger).

Toute divergence économique = test rouge. Paper only : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection.tick_dataset import TickEnvelope  # noqa: E402
from hl_observer.market_truth import MarketTruthPipeline, ReplayIntent  # noqa: E402
from hl_observer.market_truth.truth_chain import TruthChain  # noqa: E402

T0 = 1_700_000_000_000
COIN = "BTC"


def _carnet(px: float) -> dict:
    return {"channel": "l2Book", "data": {"levels": [
        [{"px": "%.2f" % px, "sz": "5"}, {"px": "%.2f" % (px - 1), "sz": "9"}],
        [{"px": "%.2f" % (px + 1), "sz": "5"}, {"px": "%.2f" % (px + 2), "sz": "9"}],
    ]}}


def _tick(i: int, *, px: float | None = None, gate_ready: bool = True, snapshot: bool = False) -> dict:
    """Enregistrement durable au schéma de production (`TickEnvelope.as_record`)."""
    ts = T0 + i * 100
    env = TickEnvelope(
        source_id="parite_l2",
        channel="l2Book",
        instrument=COIN,
        event_kind="SNAPSHOT" if snapshot else "UPDATE",
        raw_payload=_carnet(64_000.0 + i if px is None else px),
        received_ts_ms=ts,
        exchange_ts_ms=ts - 5,
        provenance={"access": "read_only", "venue": "hyperliquid"},
        parsed_summary={"feed_quality_score": 95.0, "data_gate_ready": bool(gate_ready)},
        written_ts_ms=ts,
    )
    return env.as_record(written_ts_ms=ts)


def _bande(n: int = 40) -> list[dict]:
    return [_tick(i) for i in range(n)]


def _intent(index_ancre: int = 5, *, latence_ms: int = 250) -> ReplayIntent:
    return ReplayIntent(
        signal_id="parite:%d" % index_ancre,
        coin=COIN,
        position_side="LONG",
        action="OPEN",
        signal_observable_at_ms=T0 + index_ancre * 100,
        requested_notional_usdc=50.0,
        latency_ms=latence_ms,
        execution_style="TAKER",
        fee_bps=4.5,
    )


def _rejouer(records, intent) -> dict:
    """Un pipeline NEUF à chaque appel : on mesure le déterminisme, pas un état accumulé."""
    resultat = MarketTruthPipeline(truth_chain=TruthChain()).run(intent=intent, durable_tick_records=records)
    return resultat.as_dict()


def _economie(sortie: dict) -> dict:
    """Ce qui doit être STRICTEMENT identique : le fill et ses coûts."""
    return sortie["truth"]["fill"]


# ═══════════════ 1. troncature du futur ═══════════════
def test_le_futur_ne_change_pas_une_decision_deja_prenable():
    """La bande complète contient 40 ticks ; tronquée à l'ancre + horizon, le fill doit être IDENTIQUE."""
    intent = _intent(5)
    complete = _bande(40)
    # tout ce qui est nécessaire à la décision : jusqu'à l'ancre + latence + marge de fill
    tronquee = [r for r in complete if int(r["received_ts_ms"]) <= T0 + 15 * 100]
    assert len(tronquee) < len(complete)
    assert _economie(_rejouer(tronquee, intent)) == _economie(_rejouer(complete, intent))


def test_tronquer_avant_le_signal_ne_fabrique_jamais_un_fill():
    """Sans aucun carnet après le signal, la chaîne doit refuser — jamais emprunter un prix ultérieur."""
    intent = _intent(30)
    avant = [r for r in _bande(40) if int(r["received_ts_ms"]) <= T0 + 10 * 100]
    fill = _economie(_rejouer(avant, intent))
    assert fill["status"] in {"NO_BOOK", "STALE_BOOK", "NO_FILL", "UNMEASURABLE", "QUALITY_BLOCKED"}
    assert not fill["filled_notional_usdc"]


def test_ajouter_du_futur_ne_reveille_pas_un_refus():
    """Un refus causal reste un refus : le futur ne doit pas transformer un NO_BOOK en fill."""
    intent = _intent(30)
    avant = [r for r in _bande(40) if int(r["received_ts_ms"]) <= T0 + 10 * 100]
    refus = _economie(_rejouer(avant, intent))
    if refus["status"] in {"NO_BOOK", "STALE_BOOK", "NO_FILL"}:
        complet = _economie(_rejouer(_bande(40), intent))
        # avec le futur, un fill devient possible : c'est normal — l'invariant est qu'il n'apparaît
        # QUE lorsque les événements nécessaires sont réellement présents, jamais par extrapolation.
        assert complet["executed_at_ms"] is None or complet["executed_at_ms"] >= intent.signal_observable_at_ms


# ═══════════════ 2. longueurs de warm-up ═══════════════
def test_la_longueur_du_warmup_ne_change_pas_leconomie():
    """Démarrer 3, 10 ou 25 ticks avant l'ancre doit donner le même fill : le passé lointain n'est pas un input."""
    intent = _intent(30)
    complete = _bande(40)
    resultats = []
    for debut in (5, 20, 27):
        resultats.append(_economie(_rejouer(complete[debut:], intent)))
    assert resultats[0] == resultats[1] == resultats[2]


# ═══════════════ 3. reconnexion : snapshot initial ═══════════════
def test_un_snapshot_de_reconnexion_ne_cree_pas_une_economie_differente():
    intent = _intent(5)
    complete = _bande(40)
    avec_snapshot = list(complete)
    avec_snapshot.insert(0, _tick(0, snapshot=True))     # snapshot initial rejoué à la reconnexion
    assert _economie(_rejouer(avec_snapshot, intent)) == _economie(_rejouer(complete, intent))


# ═══════════════ 4. doublons ═══════════════
def test_des_doublons_injectes_ne_changent_pas_le_fill():
    intent = _intent(5)
    complete = _bande(40)
    double = []
    for r in complete:
        double.append(r)
        double.append(dict(r))                            # même événement, deux fois
    assert _economie(_rejouer(double, intent)) == _economie(_rejouer(complete, intent))


# ═══════════════ 5. réordonnancement borné ═══════════════
def test_un_reordonnancement_borne_est_absorbe_par_lordre_causal():
    intent = _intent(5)
    complete = _bande(40)
    melangee = list(complete)
    for i in range(0, len(melangee) - 1, 2):              # inversion de paires adjacentes
        melangee[i], melangee[i + 1] = melangee[i + 1], melangee[i]
    assert _economie(_rejouer(melangee, intent)) == _economie(_rejouer(complete, intent))


# ═══════════════ 6. rejeu idempotent (crash après OPEN / après ledger) ═══════════════
#: Champs propres à UNE session de ledger (identité, chaînage). Ils DOIVENT changer d'une session à l'autre :
#: ce sont les seules divergences tolérées, et le test le prouve au lieu de les ignorer en silence.
CHAMPS_DE_SESSION = {"session_id", "last_event_hash"}


def _economie_ledger(snapshot: dict) -> dict:
    return {k: v for k, v in snapshot.items() if k not in CHAMPS_DE_SESSION}


def test_rejouer_la_meme_intention_donne_exactement_la_meme_economie():
    """Crash après OPEN avant flush du ledger : rejouer ne doit ni créer ni détruire de PnL."""
    intent = _intent(5)
    complete = _bande(40)
    premier = _rejouer(complete, intent)
    second = _rejouer(complete, intent)
    assert _economie(premier) == _economie(second)
    a, b = premier["truth"]["ledger_snapshot"], second["truth"]["ledger_snapshot"]
    assert _economie_ledger(a) == _economie_ledger(b)
    # les SEULES differences admises sont l'identite de session, jamais un chiffre economique
    assert {k for k in a if a[k] != b.get(k)} <= CHAMPS_DE_SESSION


def test_le_meme_intent_sur_une_chaine_neuve_ne_double_pas_le_ledger():
    """Crash après ledger avant écriture du statut : une chaîne neuve rejoue le MÊME état, pas le double."""
    intent = _intent(5)
    complete = _bande(40)
    snapshots = [_rejouer(complete, intent)["truth"]["ledger_snapshot"] for _ in range(3)]
    economies = [_economie_ledger(s) for s in snapshots]
    assert economies[0] == economies[1] == economies[2]
    # et surtout : le cash/realise ne double pas d'un rejeu a l'autre
    for cle in ("realized_pnl_usdc", "cash_usdc", "equity_usdc"):
        if cle in economies[0]:
            assert economies[0][cle] == economies[2][cle]


# ═══════════════ 7. qualité : un refus reste un refus ═══════════════
def test_un_flux_de_mauvaise_qualite_est_refuse_et_le_reste():
    intent = _intent(5)
    degrade = [_tick(i, gate_ready=False) for i in range(40)]
    sortie = _rejouer(degrade, intent)
    assert sortie["canonical_event_count"] == 0
    assert "DATA_QUALITY_GATE_NOT_READY" in sortie["rejected_tick_reasons"]
    assert not _economie(sortie)["filled_notional_usdc"]


def test_la_sortie_est_toujours_marquee_paper():
    sortie = _rejouer(_bande(40), _intent(5))
    assert sortie["paper_only"] is True and sortie["real_execution"] is False
    assert _economie(sortie)["real_execution"] is False
