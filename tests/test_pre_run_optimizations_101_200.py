from __future__ import annotations
from pathlib import Path
from hl_observer.audit.pre_run_101_200 import ITEMS, ids, inspect_coverage
from hl_observer.research.experiment_infra import CacheNoeudDag, RegistreExperiencesSQLite
from hl_observer.research.qa_rigor import detecter_dependance_ordre, detecter_flaky
from hl_observer.research.scenario_rigor import ablation_sweep, evaluer_transfert
from hl_observer.research.validation_stats import alpha_spending, model_confidence_set
ROOT=Path(__file__).resolve().parents[1]

def test_registry_exact_101_200_and_evidence_present():
    assert ids()==tuple(range(101,201)) and len(ITEMS)==100 and len(set(ids()))==100
    r=inspect_coverage(ROOT)
    assert r['historical_registry_present'] and r['exact_ids'] and r['duplicate_free']
    assert r['n_items']==100 and r['n_code_present']==100 and r['n_missing']==0 and r['all_code_present']
    assert r['verified_by_presence'] is False and all(x['verified'] is False for x in r['details'])

def test_range_bindings_are_current_and_explicit():
    for i in range(101,131):
        x=ITEMS[i]; assert 'src/hl_observer/ops/lab_rapport.py' in x.sources; assert 'src/hl_observer/paper_trading/paper_engine.py' in x.sources; assert 'ANALYSER_BACKTESTS_REPLAYS.cmd' in x.sources; assert 'tests/test_recette_windows_e2e.py' in x.tests
    for i in range(131,161):
        x=ITEMS[i]; assert 'src/hl_observer/runtime/protections.py' in x.sources; assert 'src/hl_observer/research/scenario_rigor.py' in x.sources; assert 'tests/test_validation_stats.py' in x.tests
    for i in range(161,201):
        x=ITEMS[i]; assert 'src/hl_observer/research/experiment_infra.py' in x.sources; assert '.github/workflows/portable-release-windows.yml' in x.sources; assert 'tests/test_portable_release_ci.py' in x.tests

def test_experiment_persistence_dag_and_fail_closed_research(tmp_path):
    p=tmp_path/'r.sqlite'; r=RegistreExperiencesSQLite(p); r.enregistrer('a',{'x':1},{'pnl':4.2}); r.fermer(); r=RegistreExperiencesSQLite(p); assert r.lire('a')['metriques']['pnl']==4.2; r.fermer()
    c=CacheNoeudDag(); c.poser('n',{'x':1},7); assert c.obtenir('n',{'x':1})==7 and c.obtenir('n',{'x':2}) is None
    a=ablation_sweep(['g1','g2'],lambda removed:10-(3 if 'g1' in removed else 0)-(1 if 'g2' in removed else 0)); assert a[0]['composant']=='g1'
    t=evaluer_transfert({'a':1.0,'b':-0.1},seuil=0.0); assert not t['transfere_partout'] and 'b' in t['echecs']
    assert not detecter_dependance_ordre([{'a':True},{'a':False}])['independant']; assert detecter_flaky({'ok':[True,True],'f':[True,False]})['flaky']==['f']
    assert isinstance(model_confidence_set({'a':[1,1.1,.9],'b':[-1,-.8,-1.2]},alpha=.1),dict); assert len(alpha_spending(5,alpha=.05))==5

def test_registry_has_no_network_or_order_surface():
    s=(ROOT/'src/hl_observer/audit/pre_run_101_200.py').read_text(encoding='utf-8').lower()
    for bad in ('requests.post','websockets.connect','/exchange','place_order(','market_order('): assert bad not in s
