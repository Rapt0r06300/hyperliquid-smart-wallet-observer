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
    assert "HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS=15000" in text
    assert "HYPERSMART_SIMULATION_ALLOW_ADD_AS_ENTRY=1" in text
    assert "HYPERSMART_SIMULATION_MIN_EDGE_BPS=15" in text
    assert "HYPERSMART_V12_SQLITE_PATH" in text
    assert "HYPERSMART_SLTP_ENABLED=1" in text
    assert "HYPERSMART_ADAPTIVE_PAPER_SIZING=1" in text
    assert "-Port 8794" in text
    assert "-IntervalSeconds 15" in text
    assert "-MaxLeaders 50" in text
    assert "-Interactive" in text
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
    assert "python -m hl_observer init-db" in text
    assert "python -m hl_observer reset-simulation-state --starting-equity 1000" in text
    assert "python -m hl_observer discover-markets --store --max-coins 80" in text
    assert "scan-markets --all --store --max-coins 80 --l2book --candles" in text
    assert "Warm scan WebSocket public Hyperliquid" in text
    assert "startup_public_trade_scan" in text
    assert "live-public-scan --network-read --store --duration-seconds 6 --coins AUTO --max-coins 60 --max-wallets 20000" in text
    assert "Nouvelle session simulation" in text
    assert "HL_ENABLE_MAINNET_EXECUTION" in text
    assert "HL_ENABLE_TESTNET_EXECUTION" in text
    assert "HL_DATABASE_URL" in text
    assert "HYPERSMART_V12_SQLITE_PATH" in text
    assert 'Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_ENABLED" "1"' in text
    assert 'Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_TAKE_PROFIT_BPS" "85"' in text
    assert 'Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_STOP_LOSS_BPS" "30"' in text
    assert 'Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_TRAILING_BPS" "30"' in text
    assert 'Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS" "55"' in text
    assert 'Set-HyperSmartDefaultEnv "HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS" "8"' in text
    assert 'Set-HyperSmartDefaultEnv "HYPERSMART_ADAPTIVE_PAPER_SIZING" "1"' in text
    assert "runtime\\data" in text
    assert "hypersmart_simulation_session.sqlite3" in text
    assert "hypersmart_v12_artifacts.sqlite3" in text
    assert "DB session simulation" in text
    assert "HL_LOG_LEVEL" in text
    assert 'Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_MIN_EDGE_BPS" "15"' in text
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
    assert "Rafraichissement allMids Hyperliquid read-only" in poll_loop_text
    assert "opportunity-report --active-window-seconds 120" in poll_loop_text
    assert "warehouse-report --fresh-window-seconds 120" in poll_loop_text
    assert "$logsToSendDir" in poll_loop_text
    assert "simulation-readiness --from-logs" in poll_loop_text
    assert "[Math]::Min($MaxLeaders, 10)" in poll_loop_text
    assert "Commande [R=status, Q=stop]" in text
    assert "Cette fenetre est le moteur" in text
    assert "Stop-HyperSmartRuntime" in text
    assert "ALERTE: serveur UI local ne repond pas encore" in text
    assert "ALERTE: le serveur UI s'est arrete juste apres le lancement" in text
    assert "ALERTE: le poller simulation s'est arrete juste apres le lancement" in text
    assert "Test-ProcessAlive" in text
    assert '("logs " + [char]0x00E0 + " envoyer")' in text
    assert "Start-Process -NoNewWindow" in text
    assert "RedirectStandardOutput" in text
    assert "RedirectStandardError" in text
    assert "Start-Process -WindowStyle Hidden" not in text
    assert "/static/simulation_v2.html" in text
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
