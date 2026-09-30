@echo off
cd /d "C:\Users\flo\Desktop\Projet invest"
set PYTHONPATH=src
echo ===PY_COMPILE=== > _scendb3m.txt
python -m py_compile src\hl_observer\backtesting\scenario_grid.py src\hl_observer\backtesting\scenario_db.py 2>> _scendb3m.txt && echo COMPILE_OK >> _scendb3m.txt
echo ===TEST (regression, doit rester vert)=== >> _scendb3m.txt
python -m pytest -q tests\test_scenario_db.py >> _scendb3m.txt 2>&1
echo ===BUILD 3 000 000 (streaming)=== >> _scendb3m.txt
python -c "import time,sys;sys.path.insert(0,'src');t=time.time();import importlib.util as u,pathlib as p;spec=u.spec_from_file_location('_sdb',p.Path('src/hl_observer/backtesting/scenario_db.py'));import sys as s;m=u.module_from_spec(spec);s.modules['_sdb']=m;spec.loader.exec_module(m);st=m.build_database('runtime/scenarios/scenarios.db',count=3000000,seed=7);import json;print(json.dumps(st,ensure_ascii=False,indent=2));print('elapsed_s',round(time.time()-t,1))" >> _scendb3m.txt 2>&1
echo ===VERIF INDEPENDANTE=== >> _scendb3m.txt
python -c "import sqlite3;c=sqlite3.connect(r'runtime\scenarios\scenarios.db');q=c.cursor();print('rows',q.execute('select count(*) from scenarios').fetchone()[0]);print('distinct_hash',q.execute('select count(distinct param_hash) from scenarios').fetchone()[0]);print('by_source',q.execute('select source,count(*) from scenarios group by source').fetchall());print('side',q.execute('select side_mode,count(*) from scenarios group by side_mode').fetchall());print('sl_distinct',q.execute('select count(distinct sl_bps) from scenarios').fetchone()[0]);print('tp_distinct',q.execute('select count(distinct tp_bps) from scenarios').fetchone()[0])" >> _scendb3m.txt 2>&1
echo ===FICHIER DB=== >> _scendb3m.txt
powershell -NoProfile -Command "Get-Item runtime\scenarios\scenarios.db | Select-Object @{N='MB';E={[math]::Round($_.Length/1MB,1)}},LastWriteTime | Format-Table -AutoSize | Out-String" >> _scendb3m.txt 2>&1
echo DONE_SCENDB3M >> _scendb3m.txt
