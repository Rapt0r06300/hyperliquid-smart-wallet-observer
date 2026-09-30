from pathlib import Path


def test_single_hypersmart_launcher_exists_and_forces_simulation_mode():
    launcher = Path("LANCER_HYPERSMART.cmd")
    text = launcher.read_text(encoding="utf-8")

    assert launcher.exists()
    assert "start_hypersmart_simulation.ps1" in text
    assert "HL_ENV=paper" in text
    assert "HL_ENABLE_MAINNET_EXECUTION=0" in text
    assert "HL_ENABLE_TESTNET_EXECUTION=0" in text
    assert "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW" in text
    assert "HYPERSMART_MIN_REDUCE_NOTIONAL_USDT=0" in text
    assert "HYPERSMART_V9_PIPELINE_AUTHORITATIVE=1" in text
    assert "HYPERSMART_SIMULATION_ALLOW_ADD_AS_ENTRY=0" in text
    assert "HYPERSMART_SIMULATION_MIN_EDGE_BPS=" in text  # calibre -> valeur non figee   # valeur calibree -> coherence testee ailleurs
    assert "HYPERSMART_SLTP_TAKE_PROFIT_BPS=" in text  # calibre -> valeur non figee
    assert "HYPERSMART_SLTP_STOP_LOSS_BPS=" in text  # calibre -> valeur non figee
    assert "HYPERSMART_SLTP_TRAILING_BPS=" in text  # calibre -> valeur non figee
    assert "HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS=" in text  # calibre -> valeur non figee
    assert "HYPERSMART_SLTP_STOP_MIN_HOLD_MS=" in text  # calibre -> valeur non figee
    assert "HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS=" in text  # calibre -> valeur non figee
    assert "HYPERSMART_V12_SQLITE_PATH" in text
    assert "HYPERSMART_UI_STATE_DIR" in text
    assert "HYPERSMART_SLTP_ENABLED=1" in text
    assert "HYPERSMART_ADAPTIVE_PAPER_SIZING=" in text  # calibre -> valeur non figee
    assert "-Port 8794" in text
    assert "-IntervalSeconds 15" in text
    assert "-MaxLeaders 50" in text
    assert "-Interactive" in text
    # L'IA shadow reste disponible, mais elle n'est pas un composant necessaire
    # au runtime de collecte/decision et ne doit plus alourdir le double-clic.
    assert "HYPERSMART_ENABLE_AUX_IA=0" in text
    assert "HYPERSMART_ENABLE_AUX_STREAM=1" in text
    assert 'start "HyperSmart IA"' not in text
    assert 'start "HyperSmart Stream"' not in text
    assert "WindowStyle Hidden" not in text


def test_legacy_program_launchers_removed_to_keep_one_entrypoint():
    assert not Path("LANCER_HYPERSMART_SIMULATION.cmd").exists()
    assert not Path("DEMARRER_SIMULATION_LIVE_1000_USDT.cmd").exists()
    assert not Path("Ouvrir_Command_Center.bat").exists()


def test_runtime_session_database_is_ignored():
    gitignore = Path(".gitignore").read_text(encoding="utf-8")

    assert "runtime/" in gitignore
    assert "*.sqlite3" in gitignore


def test_start_script_initializes_everything_without_execution():
    text = Path("tools/start_hypersmart_simulation.ps1").read_text(encoding="utf-8")
    poll_loop_text = Path("tools/hypersmart_simulation_poll_loop.ps1").read_text(encoding="utf-8")

    assert "[int]$Port = 8794" in text
    assert "& $PythonExe -m hl_observer init-db" in text
    assert '$HealthUrl = "http://127.0.0.1:$Port/api/simulation/status"' in text
    assert "Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl" in text
    assert "& $PythonExe -m hl_observer reset-simulation-state --starting-equity 1000" in text
    assert 'HYPERSMART_RESET_ON_LAUNCH -eq "1"' in text  # 25/07 Fix1 : reset SEULEMENT si =1 explicite
    assert "CONSERVE par defaut" in text                  # defaut garanti = conserver equity/PnL/ledgers
    assert "& $PythonExe -m hl_observer discover-markets --store --max-coins 80" in text
    assert "scan-markets --all --store --max-coins 80 --l2book --candles" in text
    assert "Warm scan WebSocket public Hyperliquid" in text
    assert "startup_public_trade_scan" in text
    assert "live-public-scan --network-read --store --duration-seconds 6 --coins AUTO --max-coins 60 --max-wallets 20000" in text
    assert "Nouvelle session simulation" in text
    assert "HL_ENABLE_MAINNET_EXECUTION" in text
    assert "HL_ENABLE_TESTNET_EXECUTION" in text
    assert "HL_DATABASE_URL" in text
    assert "HYPERSMART_V12_SQLITE_PATH" in text
    assert "HYPERSMART_UI_STATE_DIR" in text
    # V25 (2026-07-03): profil catastrophique uniquement — les stops scalping
    # (SL 55 bps) se faisaient prendre par le bruit et le trailing coupait les
    # gains (session live PF=0.34). Sorties normales = replay leader + guard.
    assert "HYPERSMART_ADAPTIVE_PAPER_SIZING" in text  # calibre -> valeur non figee
    assert "runtime\\data" in text
    assert "hypersmart_simulation_session.sqlite3" in text
    assert "hypersmart_v12_artifacts.sqlite3" in text
    assert "DB session simulation" in text
    assert "HL_LOG_LEVEL" in text
    assert "HYPERSMART_SIMULATION_MIN_EDGE_BPS" in text  # calibre -> valeur non figee
    assert 'Set-HyperSmartDefaultEnv "HYPERSMART_MIN_REDUCE_NOTIONAL_USDT" "0"' in text
    assert 'Set-HyperSmartDefaultEnv "HYPERSMART_V9_PIPELINE_AUTHORITATIVE" "1"' in text
    assert "HYPERSMART_MAX_OPEN_POSITIONS" in text  # calibre -> valeur non figee
    assert "HYPERSMART_MAX_POSITION_USDT" in text  # calibre -> valeur non figee
    assert "HYPERSMART_SIMULATION_LEVERAGE" in text  # calibre -> valeur non figee
    # V25: hard halt 1% du capital (10 USDC) — a 2.50 la session gelait apres
    # quelques stops et refusait ensuite des edges 64-68 bps en boucle.
    assert "HYPERSMART_SESSION_GUARD_SOFT_LOSS_USDC" in text  # calibre -> valeur non figee
    assert "HYPERSMART_SESSION_GUARD_HARD_LOSS_USDC" in text  # calibre -> valeur non figee
    assert "HYPERSMART_DIRECT_COPY_MIN_EDGE_BPS" in text  # calibre -> valeur non figee
    assert "simulation-readiness --from-logs" in text
    assert "hypersmart_simulation_poll_loop.ps1" in text
    assert "hl_observer live-user-fills-scan" in text
    assert "Write-LauncherEngineStatus" in text
    assert "launcher_starting" in text
    assert "startup_guard" in text
    assert '"-MaxRuns", "5760"' in text
    assert "RestartExisting" in text
    assert "Arret ancien processus HyperSmart" in text
    assert "Waiting for old HyperSmart runtime processes to exit" in text
    assert "FreshWindowMinutes" in text
    assert "MaxRuns = 5760" in poll_loop_text
    assert "if ($MaxRuns -le 0)" in poll_loop_text
    assert 'max_runs_guard_applied' in poll_loop_text
    assert "hypersmart_simulation_poll_loop.lock" in poll_loop_text
    assert "LeadersPerPoll" in text
    assert '"-LeadersPerPoll", "10"' in text
    assert "--leader-offset $leaderOffset" in poll_loop_text
    assert '"-PublicTradeScanEveryPolls", "1"' in text
    assert '"-PublicTradeCoins", "AUTO"' in text
    assert '"-PublicTradeMaxCoins", "60"' in text
    assert '"-PublicTradeScanSeconds", "8"' in text
    assert '"-PublicTradeMaxWallets", "10000"' in text
    assert '"-UserFillsMaxLiveAgeMs", "20000"' in text
    assert "UserFillsMaxLiveAgeMs" in poll_loop_text
    assert "--max-live-fill-age-ms $UserFillsMaxLiveAgeMs" in poll_loop_text
    assert "throughput-plan" in poll_loop_text
    assert "fresh-scan-plan --network-read" in poll_loop_text
    assert "fresh-data-plan --network-read" in poll_loop_text
    assert "periodic_collect_all" in poll_loop_text
    assert "hl_observer.collection.run_collect_all --max-coins $PublicTradeMaxCoins" in poll_loop_text
    assert "periodic_explorer_scrape" in poll_loop_text
    assert "scrape-explorer --store --max-events 250" in poll_loop_text
    assert "explorer-candidates --store" in poll_loop_text
    assert "($i % 20) -eq 0" in poll_loop_text
    assert "market_marks_refresh" in poll_loop_text
    assert "discover-markets --store --max-coins $PublicTradeMaxCoins" in poll_loop_text
    assert "scan-markets --all --store --max-coins $PublicTradeMaxCoins --l2book --candles" in poll_loop_text
    assert "v12_sqlite_path" in poll_loop_text
    assert "sltp_enabled" in poll_loop_text
    assert "adaptive_paper_sizing" in poll_loop_text
    assert "min_reduce_notional_usdt" in text
    assert "min_reduce_notional_usdt" in poll_loop_text
    assert "Rafraichissement allMids Hyperliquid read-only" in poll_loop_text
    assert "opportunity-report --active-window-seconds 120" in poll_loop_text
    assert "warehouse-report --fresh-window-seconds 120" in poll_loop_text
    assert "$logsToSendDir" in poll_loop_text
    assert "simulation-readiness --from-logs" in poll_loop_text
    assert "fusion_runtime_latest_delta_age_ms" in poll_loop_text
    assert "fusion_runtime_recent_entry_deltas" in poll_loop_text
    assert "fusion_runtime_current_equity_usdt" in poll_loop_text
    assert "[regex]::Matches($text" in poll_loop_text
    assert "${safeLabel}_" in poll_loop_text
    assert "[Math]::Min($MaxLeaders, 10)" in poll_loop_text
    assert "Commande [R=status, Q=stop]" in text
    assert "Cette fenetre est le moteur" in text
    assert "Stop-HyperSmartRuntime" in text
    assert "HYPERSMART_RUNTIME_STOP_FILE" in text
    assert "tools\\ia_train_loop.ps1" in text
    assert "tools\\stream_loop.ps1" in text
    assert "live-user-fills-stream" in text
    assert "Start-Process -WindowStyle Hidden" in text
    assert "ALERTE: serveur UI local ne repond pas encore" in text
    assert "ALERTE: le serveur UI s'est arrete juste apres le lancement" in text
    assert "ALERTE: le poller simulation s'est arrete juste apres le lancement" in text
    assert "Test-ProcessAlive" in text
    assert '("logs " + [char]0x00E0 + " envoyer")' in text
    assert "Start-Process -NoNewWindow" in text
    assert "RedirectStandardOutput" in text
    assert "RedirectStandardError" in text
    assert "/v2" in text  # UI officielle = /v2 (refonte ecaa0ff)
    # (l'ancien jeton anti-cache de l'UI statique n'existe plus depuis la refonte /v2)
    assert "/exchange" not in text


def test_poll_loop_runs_public_trades_discovery_before_copy_run():
    text = Path("tools/hypersmart_simulation_poll_loop.ps1").read_text(encoding="utf-8")

    assert "live-public-scan" in text
    assert "scrape-explorer --store --max-events 250" in text
    assert "explorer-candidates --store" in text
    assert "discover-markets --store --max-coins $PublicTradeMaxCoins" in text
    assert "scan-markets --all --store --max-coins $PublicTradeMaxCoins --l2book --candles" in text
    assert "--max-coins $PublicTradeMaxCoins" in text
    assert "--network-read" in text
    assert "--store" in text
    assert "copy-run" in text
    assert "Write-CommandOutput" in text
    assert 'Write-Host "[$stamp] $Message"' in text
    assert "suppressed $suppressedHttpOk successful /info HTTP 200 log lines" in text
    assert text.index("discover-markets --store") < text.index("live-public-scan")
    assert text.index("scan-markets --all --store") < text.index("live-public-scan")
    assert text.index("live-public-scan") < text.index("copy-run")
    assert "/exchange" not in text


def test_auxiliary_loops_are_stoppable_and_do_not_recycle_stale_snapshots():
    stream_text = Path("tools/stream_loop.ps1").read_text(encoding="utf-8")
    ia_text = Path("tools/ia_train_loop.ps1").read_text(encoding="utf-8")

    assert "HYPERSMART_RUNTIME_STOP_FILE" in stream_text
    assert "Test-StopRequested" in stream_text
    assert "--duration-seconds 0" not in stream_text
    assert "--duration-seconds $durationSeconds" in stream_text
    assert "HYPERSMART_STREAM_SEGMENT_SECONDS" in stream_text

    assert "HYPERSMART_RUNTIME_STOP_FILE" in ia_text
    assert "Test-StopRequested" in ia_text
    assert "HYPERSMART_IA_MAX_SNAPSHOT_AGE_SEC" in ia_text
    assert "snapshot stale" in ia_text
