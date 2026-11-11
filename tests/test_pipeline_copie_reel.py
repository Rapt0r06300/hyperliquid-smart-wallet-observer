"""Orchestrateur du pipeline RÉEL (rectif Flo 23/07) : charge les entrées alpha des épisodes backfillés
+ NAV, mesure OOS purgée. NEED_MORE_DATA honnête sans historique. Sans réseau (fichiers locaux)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / ("%s.py" % nom))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


PR = _mod("pipeline_copie_reel")


def test_charger_entrees_alpha_exclut_retraits_et_ajoute_move_frac(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vault_snapshots.jsonl").write_text(
        json.dumps({"vault": "0xA", "ts_ms": 1, "nav_usd": 100_000})
    )
    episodes = [
        {"ts_ms": 1, "vault": "0xA", "coin": "SOL", "action": "OPEN", "direction": 1, "taille_usd": 9000.0},
        {"ts_ms": 2, "vault": "0xA", "coin": "BTC", "action": "REDUCE", "direction": 1, "taille_usd": 5000.0,
         "retrait_probable": True, "retrait_source": "ledger"},        # retrait ledger -> exclu
    ]
    (tmp_path / "runtime" / "data" / "vault_episodes.jsonl").write_text("\n".join(json.dumps(e) for e in episodes))
    entrees = PR.charger_entrees_alpha(tmp_path)
    assert len(entrees) == 1 and entrees[0]["coin"] == "SOL" and entrees[0]["move_frac"] == 0.09


def test_reconstruire_episodes_propage_la_lignee_du_shard_et_du_frame():
    fill = {
        "vault": "0xA",
        "coin": "BTC",
        "ts_ms": 1_000,
        "signe": 1,
        "sz": 2.0,
        "px": 100.0,
        "dir": "Open Long",
        "source": "LIVE_WS",
        "isSnapshot": False,
        "received_at_ms": 1_010,
        "source_dataset_id": "dataset-live-1",
        "source_shard_sha256": "a" * 64,
        "source_raw_sha256": "b" * 64,
    }

    episodes = PR.VB.reconstruire_episodes([fill])

    assert len(episodes) == 1
    assert episodes[0]["source_dataset_id"] == "dataset-live-1"
    assert episodes[0]["source_shard_sha256"] == "a" * 64
    assert episodes[0]["source_raw_sha256"] == "b" * 64
    assert episodes[0]["received_at_ms"] == 1_010


def test_nav_asof_interdit_fuite_future_et_deduplique_episodes(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    snapshots = [
        {"vault": "0xA", "ts_ms": 100, "nav_usd": 1_000},
        {"vault": "0xA", "ts_ms": 300, "nav_usd": 10_000},
    ]
    (data / "vault_snapshots.jsonl").write_text("\n".join(map(json.dumps, snapshots)))
    old = {"ts_ms": 50, "vault": "0xA", "coin": "BTC", "action": "OPEN", "direction": 1,
           "taille_usd": 100.0, "fill_id": "old"}
    valid = {"ts_ms": 200, "vault": "0xA", "coin": "SOL", "action": "OPEN", "direction": 1,
             "taille_usd": 100.0, "fill_id": "same"}
    (data / "vault_episodes.jsonl").write_text("\n".join(map(json.dumps, [old, valid, valid])))

    entries, audit = PR.charger_entrees_alpha_avec_audit(tmp_path)

    assert len(entries) == 1
    assert entries[0]["nav_at_signal_usd"] == 1_000
    assert entries[0]["move_frac"] == 0.1
    assert audit["duplicate_episodes_rejected"] == 1
    assert audit["missing_or_stale_asof_nav_rejected"] == 1


def test_notional_fixe_preserve_entree_sans_inventer_nav(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    entry = {
        "ts_ms": 200,
        "observed_at_ms": 205,
        "vault": "0xA",
        "coin": "BTC",
        "action": "OPEN",
        "direction": 1,
        "taille_usd": 100.0,
        "source": "LIVE_WS",
        "is_snapshot": False,
        "received_at_ms": 205,
        "fill_id": "causal-entry",
    }
    (data / "vault_episodes.jsonl").write_text(json.dumps(entry), encoding="utf-8")

    entries, audit = PR.charger_entrees_alpha_notional_fixe_avec_audit(tmp_path)

    assert len(entries) == 1
    assert entries[0]["sizing_policy"] == "FIXED_PAPER_NOTIONAL_USD"
    assert entries[0]["nav_required"] is False
    assert "move_frac" not in entries[0]
    assert audit["causal_alpha_entries"] == 1
    assert audit["missing_or_stale_asof_nav_rejected"] == 0


def test_pipeline_reconstruit_depuis_fills_dedupliques_et_preserve_identite(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "vault_snapshots.jsonl").write_text(json.dumps(
        {"vault": "0xA", "ts_ms": 100, "nav_usd": 10_000}
    ))
    fill = {"vault": "0xA", "ts_ms": 200, "coin": "BTC", "px": 100.0, "sz": 1.0,
            "signe": 1, "dir": "Open Long", "start_position": 0.0, "oid": 42, "hash": "0xabc"}
    (data / "vault_fills.jsonl").write_text("\n".join(map(json.dumps, [fill, fill])))

    entries, audit = PR.charger_entrees_alpha_avec_audit(tmp_path)

    assert len(entries) == 1
    assert entries[0]["oid"] == 42 and entries[0]["fill_id"]
    assert audit["duplicate_fills_rejected"] == 1
    assert audit["episode_source"] == "vault_fills_deduped_reconstructed"


def test_pipeline_rejette_timestamps_episode_non_entiers_sans_troncature(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    rows = [
        {"vault": "0xA", "ts_ms": 1.5, "coin": "BTC", "action": "OPEN", "direction": 1,
         "taille_usd": 100.0, "fill_id": "fractional"},
        {"vault": "0xA", "ts_ms": 2_000, "coin": "SOL", "action": "OPEN", "direction": 1,
         "taille_usd": 100.0, "fill_id": "valid"},
    ]
    (data / "vault_episodes.jsonl").write_text("\n".join(map(json.dumps, rows)))

    episodes, audit = PR._episodes_canoniques(tmp_path)

    assert [row["event_id"] for row in episodes] == ["valid"]
    assert episodes[0]["ts_ms"] == 2_000
    assert audit["invalid_episode_timestamps_rejected"] == 1


def test_pipeline_fusionne_live_causal_exclut_snapshots_et_prefere_preuve_ws(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    shared = {
        "vault": "0xA", "ts_ms": 200, "coin": "BTC", "px": 100.0,
        "sz": 1.0, "signe": 1, "dir": "Open Long", "start_position": 0.0,
        "hash": "0xshared",
    }
    (data / "vault_fills.jsonl").write_text(json.dumps({**shared, "oid": 42}), encoding="utf-8")
    live_rows = [
        {**shared, "source": "LIVE_WS", "isSnapshot": False, "received_at_ms": 205},
        {**shared, "hash": "0xsnapshot", "source": "LIVE_WS", "isSnapshot": True},
        {**shared, "hash": "0xunknown", "isSnapshot": False},
    ]
    (data / "vault_fills_live.jsonl").write_text(
        "\n".join(map(json.dumps, live_rows)), encoding="utf-8"
    )

    fills, audit = PR._fills_canoniques(tmp_path)
    episodes, _ = PR._episodes_canoniques(tmp_path)

    assert len(fills) == 1
    assert fills[0]["source"] == "LIVE_WS" and fills[0]["received_at_ms"] == 205
    assert len(episodes) == 1 and episodes[0]["observed_at_ms"] == 205
    assert audit["causal_live_fill_rows"] == 1
    assert audit["live_snapshot_rows_rejected"] == 1
    assert audit["live_unprovenanced_rows_rejected"] == 1
    assert audit["cross_source_or_internal_duplicates_rejected"] == 1
    assert audit["causal_rows_preferred_on_duplicate"] is True


def test_pipeline_admet_le_poll_forward_comme_observation_causale(tmp_path):
    """Régression 2026-11-11 : 5,2 M de fills ``LIVE_POLL`` étaient tous écartés (seul
    ``LIVE_WS`` passait), le labo cherchait alors 133 676 fois sur une entrée vide."""
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    poll = {
        "vault": "0xA", "ts_ms": 1_000, "coin": "BTC", "px": 100.0, "sz": 1.0, "signe": 1,
        "dir": "Open Long", "startPosition": "0.0", "tid": 7, "hash": "0xpoll",
        "source": "LIVE_POLL", "isSnapshot": False, "received_at_ms": 83_000,
        "champ_volumineux_inutile": "x" * 64,
    }
    futur = {**poll, "tid": 8, "hash": "0xfutur", "ts_ms": 90_000, "received_at_ms": 80_000}
    (data / "vault_fills_live.jsonl").write_text(
        "\n".join(map(json.dumps, [poll, futur])), encoding="utf-8"
    )

    fills, audit = PR._fills_canoniques(tmp_path)
    entries, entries_audit = PR.charger_entrees_alpha_notional_fixe_avec_audit(tmp_path)

    assert audit["causal_live_fill_rows"] == 1
    assert audit["causal_live_fill_rows_by_source"] == {"LIVE_POLL": 1}
    assert audit["live_unprovenanced_rows_rejected"] == 0
    # une réception antérieure au fill est impossible : jamais causale, gardée pour audit seulement
    assert audit["live_incremental_without_valid_receive_time_audit_only"] == 1
    assert "champ_volumineux_inutile" not in fills[0]
    causales = [row for row in entries if row["source"] == "LIVE_POLL" and row["tid"] == 7]
    # l'instant utilisable est NOTRE réception (83 s après le fill), jamais l'heure du fill
    assert causales and causales[0]["observed_at_ms"] == 83_000 and causales[0]["ts_ms"] == 1_000
    assert entries_audit["causal_alpha_entries"] == 1


def test_un_fill_de_poll_en_cours_de_position_n_est_pas_pris_pour_une_ouverture(tmp_path):
    """Le champ natif ``startPosition`` recale la position : fermer un short n'est pas un OPEN long."""
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    fermeture = {
        "vault": "0xA", "ts_ms": 1_000, "coin": "MINA", "px": 0.05, "sz": 300.0, "signe": 1,
        "dir": "Close Short", "startPosition": "-1000.0", "tid": 1, "hash": "0xclose",
        "source": "LIVE_POLL", "isSnapshot": False, "received_at_ms": 2_000,
    }
    (data / "vault_fills_live.jsonl").write_text(json.dumps(fermeture), encoding="utf-8")

    episodes, _ = PR._episodes_canoniques(tmp_path)
    entries, _ = PR.charger_entrees_alpha_notional_fixe_avec_audit(tmp_path)

    assert [row["action"] for row in episodes] == ["REDUCE"]
    assert episodes[0]["direction"] == -1 and episodes[0]["pos_avant"] == -1000.0
    assert entries == []


def test_les_cycles_ne_sont_reconstruits_qu_une_fois_tant_que_les_entrees_ne_changent_pas(tmp_path, monkeypatch):
    """Le labo demande les entrées PUIS les cycles de vie : un seul chargement du ruban, pas deux."""
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    fill = {"vault": "0xA", "ts_ms": 1_000, "coin": "BTC", "px": 100.0, "sz": 1.0, "signe": 1,
            "dir": "Open Long", "startPosition": "0.0", "tid": 1, "source": "LIVE_POLL",
            "isSnapshot": False, "received_at_ms": 2_000}
    (data / "vault_fills_live.jsonl").write_text(json.dumps(fill), encoding="utf-8")
    appels = []
    reel = PR._reconstruire_episodes_canoniques
    monkeypatch.setattr(PR, "_reconstruire_episodes_canoniques", lambda root: appels.append(1) or reel(root))

    entrees, _ = PR.charger_entrees_alpha_notional_fixe_avec_audit(tmp_path)
    cycles, audit = PR.charger_evenements_lifecycle_avec_audit(tmp_path)
    assert len(appels) == 1 and len(entrees) == 1 and len(cycles) == 1
    # la copie rendue peut être modifiée sans corrompre la mémoire
    cycles.clear()
    audit["altere"] = True
    encore, audit2 = PR.charger_evenements_lifecycle_avec_audit(tmp_path)
    assert len(encore) == 1 and "altere" not in audit2 and len(appels) == 1

    # une entrée modifiée invalide la mémoire : jamais de résultat périmé
    (data / "vault_fills_live.jsonl").write_text(
        "\n".join(json.dumps(row) for row in (fill, {**fill, "tid": 2, "ts_ms": 3_000, "received_at_ms": 4_000,
                                                      "startPosition": "1.0"})), encoding="utf-8")
    assert len(PR.charger_evenements_lifecycle_avec_audit(tmp_path)[0]) == 2 and len(appels) == 2


def test_pipeline_ne_compte_pas_un_ancien_live_sans_horloge_comme_causal(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    historical = {
        "vault": "0xA", "ts_ms": 200, "coin": "BTC", "px": 100.0,
        "sz": 1.0, "signe": 1, "dir": "Open Long", "start_position": 0.0,
        "hash": "0xshared",
    }
    legacy_live = {
        **historical, "source": "LIVE_WS", "isSnapshot": False,
    }
    (data / "vault_fills.jsonl").write_text(json.dumps(historical), encoding="utf-8")
    (data / "vault_fills_live.jsonl").write_text(json.dumps(legacy_live), encoding="utf-8")

    fills, audit = PR._fills_canoniques(tmp_path)
    episodes, episode_audit = PR._episodes_canoniques(tmp_path)

    assert len(fills) == 1
    assert fills[0].get("source") != "LIVE_WS"
    assert episodes[0]["source"] == "REST_BACKFILL"
    assert episodes[0]["is_snapshot"] is None
    assert audit["live_incremental_rows"] == 1
    assert audit["causal_live_fill_rows"] == 0
    assert audit["live_incremental_without_valid_receive_time_audit_only"] == 1
    assert episode_audit["causal_live_fill_rows"] == 0


def test_construire_need_more_data_sans_historique(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vault_episodes.jsonl").write_text("")
    rap = PR.construire(tmp_path)
    assert rap["mesure"]["statut"] == "NEED_MORE_DATA" and "gel" not in rap
