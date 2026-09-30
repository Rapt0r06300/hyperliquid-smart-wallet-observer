from __future__ import annotations

from pathlib import Path

from hl_observer.research.pre_run_221_260 import (
    audit_point_entree_officiel,
    construire_placebos_causaux,
    compter_essais_effectifs,
    fingerprint_flux_complet,
    paginer_fills_e2e,
    purger_intervalles_labels,
    reconcilier_apres_reconnect,
    resoudre_role_adresse,
    verifier_equity_leader_vault,
)

ROOT = Path(__file__).resolve().parents[1]


def test_aud_221_222_223_226_point_entree_full_est_etendu_et_paper():
    cmd = (ROOT / 'ANALYSER_BACKTESTS_REPLAYS.cmd').read_text(encoding='utf-8')
    r = audit_point_entree_officiel(cmd)
    assert r['ok'] is True
    assert r['orchestrateur_canonique'] and r['suite_historique'] and r['full_etendu']
    assert r['quick_seul_court'] is True


def test_aud_228_fingerprint_couvre_evenement_au_dela_de_64_et_champs_economiques():
    base = [{'coin': 'BTC', 'ts_ms': i, 'px': 100 + i, 'sz': 1.0} for i in range(100)]
    changed = [dict(x) for x in base]
    changed[90]['px'] += 0.01
    assert fingerprint_flux_complet(base) != fingerprint_flux_complet(changed)
    changed2 = [dict(x) for x in base]
    changed2[90]['sz'] = 2.0
    assert fingerprint_flux_complet(base) != fingerprint_flux_complet(changed2)


def test_aud_230_purge_label_intervals_et_embargo():
    train = [(0, 9, 'a'), (10, 20, 'b'), (30, 40, 'c')]
    test = [(21, 29, 'test')]
    assert purger_intervalles_labels(train, test) == train
    purged = purger_intervalles_labels(train, test, embargo_ms=2)
    assert [x[2] for x in purged] == ['a']


def test_aud_237_placebos_direction_et_temps_distincts():
    events = [{'signe': 1, 'ts_ms': 1}, {'signe': -1, 'ts_ms': 2}, {'signe': 1, 'ts_ms': 3}]
    r = construire_placebos_causaux(events, shift=1)
    assert [x['signe'] for x in r['direction_opposed']] == [-1, 1, -1]
    assert [x['signe'] for x in r['time_shifted']] == [-1, 1, 1]


def test_aud_240_equity_absente_est_unmeasurable_jamais_fictive():
    assert verifier_equity_leader_vault(leader_equity=None, vault_equity=1000)['measurable'] is False
    assert verifier_equity_leader_vault(leader_equity=5000, vault_equity=1000)['measurable'] is True
    assert verifier_equity_leader_vault(leader_equity=-1, vault_equity=1000)['ok'] is False


def test_aud_241_pagination_e2e_cursor_dedup_et_fin_naturelle():
    pages = {
        100: [{'time': 100, 'tid': 'a'}, {'time': 101, 'tid': 'b'}],
        102: [{'time': 102, 'tid': 'b'}, {'time': 103, 'tid': 'c'}],
        104: [],
    }
    calls = []

    def fetch(cursor, limit):
        calls.append((cursor, limit))
        return pages.get(cursor, [])

    r = paginer_fills_e2e(fetch, start_ms=100, page_limit=2, max_pages=10)
    assert [x['tid'] for x in r['fills']] == ['a', 'b', 'c']
    assert r['complet'] is True and r['stopped_reason'] == 'empty_response'
    assert [c[0] for c in calls] == [100, 102, 104]


def test_aud_241_pagination_cap_est_explicitement_tronquee():
    def fetch(cursor, limit):
        return [{'time': cursor + i, 'tid': f'{cursor}-{i}'} for i in range(limit)]

    r = paginer_fills_e2e(fetch, start_ms=0, page_limit=2, max_pages=2)
    assert r['complet'] is False and r['tronque'] is True and r['stopped_reason'] == 'max_pages_reached'


def test_aud_242_role_adresse_deny_by_default():
    assert resoudre_role_adresse({'role': 'MASTER'})['ok'] is True
    assert resoudre_role_adresse({'role': 'AGENT'})['ok'] is False
    assert resoudre_role_adresse({'role': 'AGENT', 'master_address': '0xmaster'})['ok'] is True
    assert resoudre_role_adresse({})['role'] == 'UNKNOWN'


def test_aud_243_reconnect_reconcilie_snapshot_et_delta_sans_perte():
    r = reconcilier_apres_reconnect(['1', '2'], ['2', '3'], ['3', '4'])
    assert r['ids'] == ['1', '2', '3', '4']
    assert r['nouveaux'] == ['3', '4'] and r['duplicate_count'] == 2 and r['reconcilie'] is True


def test_aud_255_compte_les_idees_generees_dans_multiple_testing():
    r = compter_essais_effectifs({'a': [1, 2], 'b': [1, 2, 3]}, generated_candidates=17)
    assert r == {'grid_trials': 6, 'generated_trials': 17, 'effective_trials': 23}
