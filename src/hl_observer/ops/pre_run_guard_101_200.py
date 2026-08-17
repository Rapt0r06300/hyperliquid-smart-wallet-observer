"""Gate fail-closed du lot HyperSmart AUD-101 -> AUD-200."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from typing import Any,Mapping
from hl_observer.audit.pre_run_101_200 import inspect_coverage
from hl_observer.ops.pre_run_guard_001_100 import build_report as build_upstream_report, write_report
SCHEMA_VERSION='hypersmart.pre_run_guard_101_200.v1'
DEFAULT_OUTPUT=Path('runtime')/'reports'/'pre_run_101_200.json'

def build_report(root:Path|str,*,environ:Mapping[str,str]|None=None,require_clean_git:bool=False)->dict[str,Any]:
    upstream=build_upstream_report(root,environ=environ,require_clean_git=require_clean_git); coverage=inspect_coverage(root)
    blockers=list(upstream['blockers']); warnings=list(upstream['warnings'])
    if not coverage['all_code_present']: blockers.append('OPTIMIZATIONS_101_200_EVIDENCE_MISSING')
    blockers=list(dict.fromkeys(blockers)); warnings=list(dict.fromkeys(warnings)); status='BLOCKED' if blockers else ('PASS_WITH_WARNINGS' if warnings else 'PASS')
    return {**upstream,'schema_version':SCHEMA_VERSION,'status':status,'blockers':blockers,'warnings':warnings,'coverage':{'first_id':101,'last_id':200,'n_items':coverage['n_items'],'n_code_present':coverage['n_code_present'],'n_missing':coverage['n_missing'],'missing_ids':coverage['missing_ids'],'verified_by_presence':False},'upstream_001_100':{'status':upstream['status'],'blockers':list(upstream['blockers'])},'paper_only':True,'real_execution':False}

def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description='Gate pre-run HyperSmart optimisations 101-200'); p.add_argument('--root',default='.'); p.add_argument('--output',default=str(DEFAULT_OUTPUT)); p.add_argument('--require-clean-git',action='store_true'); a=p.parse_args(argv)
    report=build_report(a.root,require_clean_git=a.require_clean_git); output=Path(a.output); output=output if output.is_absolute() else Path(a.root)/output; write_report(report,output); print(json.dumps(report,ensure_ascii=False,sort_keys=True)); return 0 if report['status']!='BLOCKED' else 2
if __name__=='__main__': raise SystemExit(main())
