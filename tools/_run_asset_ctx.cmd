@echo off
rem Wrapper : collecteur asset-ctx (OI/premium/funding/volume) SANS fenetre.
rem Flux separe (metaAndAssetCtxs) : aucune contention avec fills/L2. Herite CV_* + PYTHONPATH.
rem Il boucle tout seul (resilient). PAPER / lecture seule.
"%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\collecter_asset_ctx.py" --root "%CV_ROOT%." >> "%CV_ROOT%runtime\logs\asset-ctx.log" 2>&1
