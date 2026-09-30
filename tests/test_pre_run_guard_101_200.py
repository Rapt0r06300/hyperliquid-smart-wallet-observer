import json
import runpy
import sys
from pathlib import Path

import pytest

from hl_observer.ops.pre_run_guard_101_200 import build_report

ROOT=Path(__file__).resolve().parents[1]
SAFE={'HL_ENABLE_MAINNET_EXECUTION':'0','HL_ENABLE_TESTNET_EXECUTION':'0','REAL_MAINNET_TRADING':'false','TESTNET_EXECUTION_ENABLED':'false','HYPERSMART_ENABLE_REAL_ORDERS':'0','ENABLE_REAL_ORDERS':'0'}

def test_guard_101_200_coverage_is_not_presence_verification():
    r=build_report(ROOT,environ=SAFE); c=r['coverage']
    assert (c['first_id'],c['last_id'],c['n_items'],c['n_missing'])==(101,200,100,0)
    assert c['verified_by_presence'] is False
    assert 'OPTIMIZATIONS_101_200_EVIDENCE_MISSING' not in r['blockers']
    assert r['paper_only'] is True and r['real_execution'] is False

def test_guard_keeps_real_execution_and_secret_blockers():
    e=dict(SAFE); e['HL_ENABLE_MAINNET_EXECUTION']='1'; r=build_report(ROOT,environ=e)
    assert r['status']=='BLOCKED' and 'REAL_OR_TESTNET_EXECUTION_FLAG_ARMED' in r['blockers']
    e=dict(SAFE); e['HYPERSMART_PRIVATE_KEY']='forbidden'; r=build_report(ROOT,environ=e)
    assert r['status']=='BLOCKED' and 'WALLET_OR_SECRET_CONFIGURATION_PRESENT' in r['blockers']

def test_guard_source_has_no_network_or_order_surface():
    s=(ROOT/'src/hl_observer/ops/pre_run_guard_101_200.py').read_text(encoding='utf-8').lower()
    for bad in ('requests.post','websockets.connect','/exchange','place_order(','market_order('): assert bad not in s

def test_guard_module_entrypoint_runs_the_paper_gate(monkeypatch, tmp_path):
    output=tmp_path/'pre_run_101_200.json'
    monkeypatch.setattr(sys,'argv',['pre_run_guard_101_200','--root',str(ROOT),'--output',str(output)])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(ROOT/'src/hl_observer/ops/pre_run_guard_101_200.py'),run_name='__main__')
    assert exc.value.code == 0
    report=json.loads(output.read_text(encoding='utf-8'))
    assert report['paper_only'] is True
    assert report['real_execution'] is False
