"""UN CARNET REÇU APRÈS LE SIGNAL N'A PAS PU SERVIR À DÉCIDER — et l'égalité à la ms non plus.

D'OÙ VIENNENT CES TESTS (bloqueur P0 confirmé le 16/11/2026). Le compagnon ne programmait le
checkpoint `REFERENCE` qu'APRÈS avoir lu le fill : sa requête REST revenait 320 à 1 527 ms après le
signal (51 références sur 51 dans les 4 000 dernières lignes inspectées). L'exécuteur les refusait,
à raison. Résultat : 77 008 refus `STALE_OR_MISSING_REFERENCE_BOOK` sur 98 138 signaux, et ZÉRO
trade exécutable — donc aucune preuve économique possible, quelle que soit la stratégie.

La réparation n'est pas d'élargir une fenêtre de fraîcheur : c'est de lier un carnet RÉELLEMENT
observé avant le signal, avec de quoi le revérifier.

MESURE QUI JUSTIFIE CE MODULE, fenêtres de temps appariées (195,9 min de carnets WS contre
194,5 min de fills) : 10 470 fills sur 10 470 ont un carnet du même coin reçu strictement avant le
signal et à moins de 30 s ; âge médian 6 637 ms, p90 11 329 ms.

Pur : aucun fichier, aucun réseau.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import copy_vault_reference_binding as B  # noqa: E402

LANE = "runtime/data/copy_vault_l2_lane.jsonl"


def _ligne(**kw) -> bytes:
    base = {"coin": "BTC", "received_at_ms": 1_000_000, "bid": 100.0, "ask": 100.5,
            "connection_id": "conn-A", "l2_gap_epoch": 7, "capacity_usd": 900.0,
            "exchange_ts_ms": 999_900}
    base.update(kw)
    return json.dumps(base).encode("utf-8")


def _liaison(**kw):
    return B.liaison_depuis_ligne(_ligne(**kw), source=LANE, offset=4_096)


# ─────────────── la causalité : strictement avant, sans exception ───────────────
def test_un_carnet_recu_avant_le_signal_est_eligible():
    assert B.eligible(_liaison(), signal_received_ms=1_000_500) == (True, "OK")


def test_un_carnet_recu_APRES_le_signal_est_refuse():
    ok, raison = B.eligible(_liaison(), signal_received_ms=999_999)
    assert ok is False and raison == "BOOK_NOT_RECEIVED_BEFORE_SIGNAL"


def test_une_EGALITE_EXACTE_a_la_milliseconde_est_REFUSEE():
    """Question laissée ouverte par le journal d'audit, tranchée ici.

    Dans une même milliseconde, l'ordre réel des deux réceptions n'est pas observable. Accepter
    reviendrait à SUPPOSER que le carnet est arrivé le premier — c'est-à-dire à fabriquer la
    causalité qu'on prétend mesurer.
    """
    ok, raison = B.eligible(_liaison(), signal_received_ms=1_000_000)
    assert ok is False and raison == "BOOK_NOT_RECEIVED_BEFORE_SIGNAL"


def test_un_carnet_trop_vieux_est_refuse_sans_elargir_la_fenetre():
    ok, raison = B.eligible(_liaison(), signal_received_ms=1_000_000 + B.AGE_MAX_MS + 1)
    assert ok is False and raison == "PRESIGNAL_BOOK_TOO_OLD"
    assert B.eligible(_liaison(), signal_received_ms=1_000_000 + B.AGE_MAX_MS)[0] is True


def test_l_absence_de_carnet_a_son_propre_motif():
    assert B.eligible(None, signal_received_ms=1_000_000) == (False, "NO_PRESIGNAL_BOOK")


def test_une_horloge_de_reception_absente_ferme_la_porte():
    ok, raison = B.eligible(_liaison(), signal_received_ms=None)
    assert ok is False and raison == "RECEIVE_CLOCK_MISSING"


# ─────────────── ce qu'une liaison doit porter pour être revérifiable ───────────────
def test_la_liaison_porte_source_offset_sha_connexion_et_epoque():
    liaison = _liaison()
    assert liaison["source_relpath"] == LANE and liaison["source_offset"] == 4_096
    assert len(liaison["line_sha256"]) == 64
    assert liaison["connection_id"] == "conn-A" and liaison["l2_gap_epoch"] == 7
    assert liaison["paper_read_only"] is True and liaison["real_execution"] is False


def test_une_ligne_SANS_identite_de_connexion_est_refusee():
    """14 878 refus « identité de connexion L2 incomplète » au rapport du 12/11 : on ne lie pas
    un carnet dont on ne sait pas de quel flux il vient."""
    for absent in (None, "", "   ", 5):
        assert B.liaison_depuis_ligne(_ligne(connection_id=absent), source=LANE, offset=0) is None


def test_une_ligne_sans_epoque_de_gap_est_refusee():
    for absent in (None, "7", 7.0, True):
        assert B.liaison_depuis_ligne(_ligne(l2_gap_epoch=absent), source=LANE, offset=0) is None


def test_un_prix_non_fini_ou_croise_est_refuse():
    assert B.liaison_depuis_ligne(_ligne(bid=float("nan")), source=LANE, offset=0) is None
    assert B.liaison_depuis_ligne(_ligne(ask=float("inf")), source=LANE, offset=0) is None
    assert B.liaison_depuis_ligne(_ligne(bid=0.0), source=LANE, offset=0) is None
    assert B.liaison_depuis_ligne(_ligne(bid=101.0, ask=100.0), source=LANE, offset=0) is None, (
        "un carnet croise n'est pas un carnet"
    )


def test_une_horloge_de_reception_non_entiere_est_refusee():
    for mauvais in (None, "1000", 1000.0, True, 0, -5):
        assert B.liaison_depuis_ligne(_ligne(received_at_ms=mauvais), source=LANE, offset=0) is None


def test_un_offset_negatif_ou_non_entier_est_refuse():
    for mauvais in (-1, None, "0", 1.5):
        assert B.liaison_depuis_ligne(_ligne(), source=LANE, offset=mauvais) is None


def test_une_ligne_illisible_ne_leve_pas():
    assert B.liaison_depuis_ligne(b"pas du json", source=LANE, offset=0) is None
    assert B.liaison_depuis_ligne(b"\xff\xfe", source=LANE, offset=0) is None
    assert B.liaison_depuis_ligne(b"[1,2,3]", source=LANE, offset=0) is None


# ─────────────── la vérification au chargement ───────────────
def test_une_liaison_dont_les_octets_sont_intacts_est_VERIFIEE():
    ligne = _ligne()
    liaison = B.liaison_depuis_ligne(ligne, source=LANE, offset=10)
    assert B.verifier_liaison(liaison, lire=lambda s, o: ligne) == (B.VERIFIEE, "OK")


def test_le_saut_de_ligne_ne_change_pas_l_empreinte():
    """Le ruban est lu tantôt avec son `\\n`, tantôt sans : l'empreinte doit être stable."""
    ligne = _ligne()
    liaison = B.liaison_depuis_ligne(ligne, source=LANE, offset=10)
    assert B.verifier_liaison(liaison, lire=lambda s, o: ligne + b"\n")[0] == B.VERIFIEE
    assert B.verifier_liaison(liaison, lire=lambda s, o: ligne + b"\r\n")[0] == B.VERIFIEE


def test_des_octets_DIFFERENTS_sont_une_DIVERGENCE_pas_une_absence():
    liaison = _liaison()
    statut, raison = B.verifier_liaison(liaison, lire=lambda s, o: _ligne(bid=999.0))
    assert statut == B.DIVERGENTE and raison == "LINE_SHA256_MISMATCH"


def test_un_ruban_qui_a_TOURNE_rend_INVERIFIABLE_et_non_une_erreur():
    """Le ruban est archivé toutes les quelques heures : ne plus pouvoir vérifier n'est pas une
    preuve de faux. C'est une preuve ABSENTE, donc exploratoire seulement."""
    liaison = _liaison()
    assert B.verifier_liaison(liaison, lire=lambda s, o: None)[0] == B.INVERIFIABLE
    def explose(s, o):
        raise OSError("fichier archive")
    assert B.verifier_liaison(liaison, lire=explose) == (B.INVERIFIABLE, "SOURCE_UNREADABLE")


def test_une_liaison_absente_ou_tronquee_est_INVERIFIABLE():
    assert B.verifier_liaison(None, lire=lambda s, o: b"x")[0] == B.INVERIFIABLE
    liaison = dict(_liaison())
    liaison.pop("line_sha256")
    assert B.verifier_liaison(liaison, lire=lambda s, o: b"x") == (B.INVERIFIABLE, "BINDING_INCOMPLETE")
    faux = {**_liaison(), "schema_version": "autre.v9"}
    assert B.verifier_liaison(faux, lire=lambda s, o: b"x")[0] == B.INVERIFIABLE


def test_l_age_mesure_le_retard_du_carnet_sur_le_signal():
    assert B.age_ms(_liaison(), signal_received_ms=1_006_637) == 6_637
    assert B.age_ms(_liaison(), signal_received_ms=None) is None


def test_une_ligne_sans_horloge_D_ECHANGE_valide_est_refusee_a_la_SOURCE():
    """Le chargeur impose `received >= exchange_ts > 0` et un retard <= 30 s.

    Sans ce contrôle ici, l'écrivain aurait lié un carnet que le chargeur rejetterait ensuite
    SILENCIEUSEMENT : le motif serait perdu, et le tunnel d'exécutabilité montrerait un refus
    sans cause lisible.
    """
    for mauvais in (None, 0, -1, "999900", 999900.0, True):
        assert B.liaison_depuis_ligne(_ligne(exchange_ts_ms=mauvais), source=LANE, offset=0) is None
    # horloge d'echange POSTERIEURE a la reception : impossible
    assert B.liaison_depuis_ligne(_ligne(exchange_ts_ms=1_000_001), source=LANE, offset=0) is None
    # retard superieur a la borne
    assert B.liaison_depuis_ligne(
        _ligne(exchange_ts_ms=1_000_000 - B.AGE_MAX_MS - 1), source=LANE, offset=0) is None
    # a la borne exacte : accepte
    liaison = B.liaison_depuis_ligne(
        _ligne(exchange_ts_ms=1_000_000 - B.AGE_MAX_MS), source=LANE, offset=0)
    assert liaison is not None and liaison["observed_exchange_ts_ms"] == 1_000_000 - B.AGE_MAX_MS


# ─────────────── l'écrivain émet-il vraiment une REFERENCE pré-signal ? ───────────────
def _fill_live(ts, *, coin="BTC", event="ref-1"):
    """Même forme que la fixture canonique : un fill inventé ne passe pas les classifieurs."""
    return {
        "vault": "0x" + "a" * 40, "coin": coin, "px": 60_000.0, "sz": 0.01, "signe": 1,
        "ts_ms": ts - 5, "dir": "Open Long", "start_position": 0.0, "hash": f"0x{event}",
        "tid": event, "oid": event, "isSnapshot": False, "source": "LIVE_WS",
        "stable_event_id": event, "received_at_ms": ts,
    }


def _monter(tmp_path, horloge, *, rest=None):
    """Compagnon réel, ruban WS vide, offset DEJA calé sur la fin.

    Le premier passage cale toujours l'offset sur la fin du ruban : en production il pèse 666 Mo
    et son historique ne doit jamais entrer. Les carnets de test arrivent donc après ce calage.
    """
    from hl_observer.collection.copy_vault_checkpoint_tail import (
        INPUT_RELPATH, LANE_RELPATH, CopyVaultCheckpointTail,
    )

    (tmp_path / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / INPUT_RELPATH).write_text("", encoding="utf-8")
    (tmp_path / LANE_RELPATH).write_text("", encoding="utf-8")
    tail = CopyVaultCheckpointTail(root=tmp_path, clock_ms=horloge,
                                   fetch_book=rest or (lambda coin: None))
    assert tail._lire_carnets_du_ruban() == 0, "le premier passage cale, il n'ingere rien"
    return tail, tmp_path / LANE_RELPATH, tmp_path / INPUT_RELPATH


def _ajouter(chemin: Path, octets: bytes) -> None:
    with chemin.open("ab") as fh:
        fh.write(octets + b"\n")


def test_l_ecrivain_emet_une_REFERENCE_liee_a_un_carnet_PRE_SIGNAL(tmp_path):
    """LA réparation du bloqueur P0, vérifiée de bout en bout sur l'écrivain réel.

    Le REST est volontairement piégé : s'il est appelé, le test échoue. La ligne produite doit
    porter un `received_at_ms` ANTERIEUR au signal — ce que l'ancien chemin ne pouvait pas faire,
    puisqu'il ne lançait sa requête qu'après avoir lu le fill.
    """
    import json as _json

    from hl_observer.collection.copy_vault_checkpoint_tail import OUTPUT_RELPATH

    signal_ms = 5_000_000
    def rest_interdit(coin):
        raise AssertionError("le REST ne doit PAS servir quand un carnet pre-signal existe")
    tail, lane, fills = _monter(tmp_path, lambda: signal_ms, rest=rest_interdit)
    _ajouter(lane, _ligne(coin="BTC", received_at_ms=signal_ms - 4_000,
                          exchange_ts_ms=signal_ms - 4_200,
                          connection_id="conn-7", l2_gap_epoch=2))
    with fills.open("a", encoding="utf-8") as fh:
        fh.write(_json.dumps(_fill_live(signal_ms)) + "\n")

    tail.poll_once()

    lignes = [_json.loads(l) for l in
              (tmp_path / OUTPUT_RELPATH).read_text(encoding="utf-8").splitlines() if l.strip()]
    references = [l for l in lignes if l.get("checkpoint_stage") == "REFERENCE"]
    assert len(references) == 1, f"une seule REFERENCE attendue, obtenu {len(references)}"
    ref = references[0]
    assert ref["received_at_ms"] == signal_ms - 4_000, "date de l'observation REELLE du carnet"
    assert ref["checkpoint_target_ms"] == signal_ms
    assert ref["received_at_ms"] < ref["checkpoint_target_ms"], (
        "c'est toute la reparation : le carnet precede le signal")
    assert ref["presignal_age_ms"] == 4_000
    liaison = ref["reference_binding"]
    assert liaison["connection_id"] == "conn-7" and liaison["l2_gap_epoch"] == 2
    assert len(liaison["line_sha256"]) == 64 and liaison["source_offset"] >= 0
    assert tail.state["counters"]["reference_bound_presignal"] == 1
    assert tail.state["counters"]["reference_no_presignal_book"] == 0
    assert not [c for c in tail.state["pending"] if c.get("stage") == "REFERENCE"], (
        "le repli REST ne doit pas etre arme quand la liaison a reussi")


def test_sans_carnet_pre_signal_l_ecrivain_RETOMBE_sur_le_REST_et_le_COMPTE(tmp_path):
    """Le refus doit rester VISIBLE : « référence post-signal » est un motif, « rien » n'en est pas."""
    import json as _json

    signal_ms = 6_000_000
    tail, lane, fills = _monter(tmp_path, lambda: signal_ms)
    # carnet POSTERIEUR au signal : inutilisable comme reference
    _ajouter(lane, _ligne(coin="BTC", received_at_ms=signal_ms + 500,
                          exchange_ts_ms=signal_ms + 300))
    with fills.open("a", encoding="utf-8") as fh:
        fh.write(_json.dumps(_fill_live(signal_ms)) + "\n")

    tail.poll_once()
    assert tail.state["counters"]["reference_bound_presignal"] == 0
    assert tail.state["counters"]["reference_no_presignal_book"] == 1
    assert [c for c in tail.state["pending"] if c.get("stage") == "REFERENCE"], (
        "le repli REST doit etre arme, pour que le refus garde son motif en aval")


def test_un_carnet_TROP_VIEUX_a_son_propre_compteur(tmp_path):
    import json as _json

    signal_ms = 7_000_000
    tail, lane, fills = _monter(tmp_path, lambda: signal_ms)
    _ajouter(lane, _ligne(coin="BTC", received_at_ms=signal_ms - B.AGE_MAX_MS - 1_000,
                          exchange_ts_ms=signal_ms - B.AGE_MAX_MS - 1_100))
    with fills.open("a", encoding="utf-8") as fh:
        fh.write(_json.dumps(_fill_live(signal_ms)) + "\n")
    tail.poll_once()
    assert tail.state["counters"]["reference_presignal_too_old"] == 1, (
        "on n'elargit pas la fenetre pour sauver un signal : on compte le refus a part")


def test_on_choisit_le_plus_RECENT_carnet_anterieur_et_non_le_dernier_lu(tmp_path):
    """Une ligne de ruban peut arriver entre deux passes et être POSTERIEURE au signal.

    Garder « le dernier carnet connu » refuserait alors la liaison alors qu'un carnet pré-signal
    existait. On choisit donc le plus récent STRICTEMENT antérieur.
    """
    import json as _json

    from hl_observer.collection.copy_vault_checkpoint_tail import OUTPUT_RELPATH

    signal_ms = 8_000_000
    tail, lane, fills = _monter(tmp_path, lambda: signal_ms)
    for decalage, echange in ((-9_000, -9_100), (-2_000, -2_100), (+700, +500)):
        _ajouter(lane, _ligne(coin="BTC", received_at_ms=signal_ms + decalage,
                              exchange_ts_ms=signal_ms + echange))
    with fills.open("a", encoding="utf-8") as fh:
        fh.write(_json.dumps(_fill_live(signal_ms)) + "\n")
    tail.poll_once()
    refs = [_json.loads(l) for l in
            (tmp_path / OUTPUT_RELPATH).read_text(encoding="utf-8").splitlines() if l.strip()]
    ref = [r for r in refs if r.get("checkpoint_stage") == "REFERENCE"][0]
    assert ref["received_at_ms"] == signal_ms - 2_000, (
        "le carnet de -2 s est le plus recent ANTERIEUR ; celui de +0,7 s ne doit pas gagner")


def test_le_ruban_n_est_JAMAIS_relu_depuis_le_debut(tmp_path):
    """Le ruban pèse 666 Mo : un calage sur la fin est la seule lecture acceptable au démarrage."""
    from hl_observer.collection.copy_vault_checkpoint_tail import (
        INPUT_RELPATH, LANE_RELPATH, CopyVaultCheckpointTail,
    )

    (tmp_path / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / INPUT_RELPATH).write_text("", encoding="utf-8")
    lane = tmp_path / LANE_RELPATH
    lane.write_bytes(b"".join(_ligne(received_at_ms=1_000 + i) + b"\n" for i in range(500)))
    tail = CopyVaultCheckpointTail(root=tmp_path, clock_ms=lambda: 9_000_000,
                                   fetch_book=lambda coin: None)
    assert tail._lire_carnets_du_ruban() == 0, "aucune ligne historique ne doit entrer"
    assert tail.state["lane_offset"] == lane.stat().st_size
    assert tail._dernier_carnet == {}


def test_une_ROTATION_du_ruban_oublie_les_carnets_au_lieu_d_en_inventer(tmp_path):
    signal_ms = 9_500_000
    tail, lane, _fills = _monter(tmp_path, lambda: signal_ms)
    _ajouter(lane, _ligne(received_at_ms=signal_ms - 1_000, exchange_ts_ms=signal_ms - 1_100))
    assert tail._lire_carnets_du_ruban() == 1 and tail._dernier_carnet
    lane.unlink()
    lane.write_bytes(_ligne(received_at_ms=signal_ms - 500, exchange_ts_ms=signal_ms - 600) + b"\n")
    assert tail._lire_carnets_du_ruban() == 0
    assert tail._dernier_carnet == {}, (
        "apres rotation, la memoire des carnets est VIDEE : on refuse des liaisons plutot que "
        "d'en fabriquer depuis un fichier dont on ignore la continuite")


# ─────────────── le lien est-il REVERIFIE au chargement ? ───────────────
def _ecrire_reference_liee(tmp_path, signal_ms=11_000_000):
    """Produit une vraie ligne REFERENCE liée, via l'écrivain, puis rend (tail, lane)."""
    import json as _json

    tail, lane, fills = _monter(tmp_path, lambda: signal_ms)
    _ajouter(lane, _ligne(coin="BTC", received_at_ms=signal_ms - 3_000,
                          exchange_ts_ms=signal_ms - 3_050))
    with fills.open("a", encoding="utf-8") as fh:
        fh.write(_json.dumps(_fill_live(signal_ms)) + "\n")
    tail.poll_once()
    assert tail.state["counters"]["reference_bound_presignal"] == 1
    return tail, lane


def test_un_lien_INTACT_est_VERIFIE_au_chargement(tmp_path):
    from hl_observer.backtesting.copy_vault_book_loader import load_observed_books

    _tail, _lane = _ecrire_reference_liee(tmp_path)
    _, audit = load_observed_books(tmp_path, coins={"BTC"})
    assert audit["clean_epoch_receipt"]["reference_binding_counts"] == {B.VERIFIEE: 1}


def test_un_lien_dont_les_OCTETS_ont_change_est_REFUSE(tmp_path):
    """Ce n'est pas une preuve absente, c'est une preuve FAUSSE : la ligne entière est rejetée."""
    from hl_observer.backtesting.copy_vault_book_loader import load_observed_books

    _tail, lane = _ecrire_reference_liee(tmp_path)
    brut = lane.read_bytes()
    lane.write_bytes(brut.replace(b'"bid": 100.0', b'"bid": 777.0'))
    _, audit = load_observed_books(tmp_path, coins={"BTC"})
    recu = audit["clean_epoch_receipt"]
    assert recu["reference_binding_counts"].get(B.DIVERGENTE) == 1
    assert any("REFERENCE_BINDING_LINE_SHA256_MISMATCH" in motif
               for motif in audit["l2_rejection_reasons"]), (
        f"motifs : {audit['l2_rejection_reasons']}")
    assert recu["checkpoint_rows"] == 0, "une ligne au lien divergent ne peut pas etre certifiee"


def test_un_ruban_DISPARU_rend_le_lien_INVERIFIABLE_et_non_certifiable(tmp_path):
    """Le ruban est archivé toutes les quelques heures : la ligne reste exploratoire."""
    from hl_observer.backtesting.copy_vault_book_loader import load_observed_books

    _tail, lane = _ecrire_reference_liee(tmp_path)
    lane.unlink()
    _, audit = load_observed_books(tmp_path, coins={"BTC"})
    recu = audit["clean_epoch_receipt"]
    assert recu["reference_binding_counts"].get(B.INVERIFIABLE) == 1
    assert recu["checkpoint_rows"] == 0, (
        "un lien qu'on ne peut plus verifier ne doit pas compter comme preuve")


def test_un_lien_pointant_HORS_du_coffre_est_INVERIFIABLE(tmp_path):
    """Chemin borné : un offset dans un fichier hors racine ne doit jamais être lu."""
    import json as _json

    from hl_observer.backtesting.copy_vault_book_loader import load_observed_books
    from hl_observer.collection.copy_vault_checkpoint_tail import OUTPUT_RELPATH

    _tail, _lane = _ecrire_reference_liee(tmp_path)
    tape = tmp_path / OUTPUT_RELPATH
    lignes = []
    for l in tape.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        o = _json.loads(l)
        if isinstance(o.get("reference_binding"), dict):
            o["reference_binding"]["source_relpath"] = "../../ailleurs.jsonl"
        lignes.append(_json.dumps(o))
    tape.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    _, audit = load_observed_books(tmp_path, coins={"BTC"})
    assert audit["clean_epoch_receipt"]["reference_binding_counts"].get(B.INVERIFIABLE) == 1
