const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
let activeFilter = "ALL";
let logLines = [];
let autoscanRequested = false;
let fullRefreshInFlight = false;
let simulationRefreshInFlight = false;
let lastSimulationPayload = null;
let simulationFetchFailures = 0;

function tickClock() {
  $("#clock").textContent = new Date().toLocaleTimeString();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[m]));
}

function shortAddress(value) {
  const text = String(value || "");
  return text.length > 14 ? `${text.slice(0, 8)}...${text.slice(-6)}` : text;
}

function formatUsd(value) {
  const number = Number(value || 0);
  const sign = number > 0 ? "+" : "";
  return `${sign}$${number.toFixed(2)}`;
}

function formatClockMs(value) {
  const number = Number(value || 0);
  if (!number) return "-";
  return new Date(number).toLocaleTimeString();
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} ${response.status}`);
  return await response.json();
}

async function safeGetJson(url, fallback) {
  try {
    return await getJsonWithRetry(url, 2, 180);
  } catch (error) {
    console.warn(`load failed ${url}`, error);
    return fallback;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function getJsonWithRetry(url, attempts = 3, delayMs = 250) {
  let lastError = null;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await getJson(url);
    } catch (error) {
      lastError = error;
      if (attempt < attempts - 1) {
        await sleep(delayMs * (attempt + 1));
      }
    }
  }
  throw lastError || new Error(`${url} failed`);
}

async function getSimulationOverviewPayload() {
  try {
    const payload = await getJsonWithRetry("/api/simulation/overview", 3, 250);
    lastSimulationPayload = payload;
    simulationFetchFailures = 0;
    return payload;
  } catch (error) {
    simulationFetchFailures += 1;
    console.warn("simulation overview refresh failed", error);
    if (lastSimulationPayload) {
      return {
        ...lastSimulationPayload,
        connection_warning: `Connexion API instable, dernier etat conserve (${simulationFetchFailures})`,
        connection_retrying: true
      };
    }
    return {
      mode: "LOCAL_RESEARCH_SIMULATION_ONLY",
      connection_warning: "Connexion API en cours, aucune donnee simulation chargee pour l'instant.",
      connection_retrying: true,
      paper_mock_usdc_only: true,
      no_real_orders: true,
      no_testnet_executor: true,
      counts: {},
      equity: {
        current_pnl_usdc: 0,
        current_equity_usdt: 1000,
        unrealized_pnl_usdc: 0,
        realized_pnl_usdc: 0,
        source: "waiting_for_local_api"
      },
      bot_simulation: { events: [], open_positions: [], reproduced_entries: 0, reproduced_exits: 0, refused: 0 },
      no_trade_reasons: [{ reason: "LOCAL_API_RETRYING", count: simulationFetchFailures }],
      equity_candles: [],
      readiness: "LOCAL_API_RETRYING",
      message: "La page conserve l'etat precedent et retente la lecture locale automatiquement."
    };
  }
}

async function postJson(url, body = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) throw new Error(`${url} ${response.status}`);
  return await response.json();
}

function setAutopilot(discovery) {
  const title = $("#autopilotTitle");
  const subtitle = $("#autopilotSubtitle");
  const state = discovery.state;
  const running = discovery.running;
  if (running) {
    title.textContent = "Recherche automatique en cours";
    subtitle.textContent = "Decouverte des marches Hyperliquid, leaderboard, prix tous coins, puis recherche des meilleurs wallets.";
  } else if (state === "discovering") {
    title.textContent = "Recherche des meilleurs wallets";
    subtitle.textContent = "Le logiciel cherche des wallets performants sur plusieurs marches, BTC et altcoins compris.";
  } else if (state === "filtering") {
    title.textContent = "Filtrage PnL/ROI";
    subtitle.textContent = "Le logiciel filtre les wallets selon PnL, ROI, activite, liquidite du coin et copiabilite.";
  } else if (discovery.candidates_found === 0) {
    title.textContent = "Aucun wallet exploitable trouve";
    subtitle.textContent = "Aucune source disponible n'a fourni d'adresse exploitable pour le moment.";
  } else if (discovery.selected_wallets > 0) {
    title.textContent = "Resume pret";
    subtitle.textContent = "Recherche terminee. Consulte les resultats simples ou ouvre le mode expert.";
  } else {
    title.textContent = "Recherche automatique des meilleurs wallets";
    subtitle.textContent = "Des wallets ont ete trouves, mais aucun ne passe encore les filtres PnL/ROI/activite.";
  }
}

function renderTimeline(discovery) {
  const activeSteps = ["startup", "security"];
  if (discovery.last_run_at_ms || discovery.running) activeSteps.push("markets", "prices", "liquidity", "leaderboard", "validation", "sources");
  if (discovery.candidates_found > 0) activeSteps.push("filters");
  if (discovery.selected_wallets > 0) activeSteps.push("top500", "queue");
  if (discovery.backfilled_wallets > 0) activeSteps.push("backfill", "deltas", "openings", "closings", "profits", "playbooks", "follow", "risk");
  if (discovery.last_run_at_ms && !discovery.running) activeSteps.push("summary");
  $$(".timeline [data-step]").forEach((node) => {
    node.classList.toggle("active", activeSteps.includes(node.dataset.step));
  });
}

function renderScanOverview(home, autoscan) {
  const scan = autoscan || home.autoscan || {};
  const progress = Math.max(0, Math.min(100, Number(scan.progress_percent || 0)));
  const lastState = scan.last_state || scan.state || "idle";
  $("#scanStepTitle").textContent = scan.running ? `En cours : ${scan.current_step || "scan"}` : (scan.current_step || "Resume pret");
  $("#scanProgressBar").style.width = `${progress}%`;
  $("#scanProgressText").textContent = scan.running
    ? `${Math.round(progress)}% - le logiciel analyse les donnees disponibles en lecture seule.`
    : `${Math.round(progress)}% - dernier etat : ${lastState}.`;
  renderAnalysisMap((home.autoscan && home.autoscan.analyzes) || []);
}

function renderAnalysisMap(groups) {
  const target = $("#analysisMap");
  if (!target) return;
  target.innerHTML = groups.map((group) => `
    <div class="analysis-group">
      <strong>${escapeHtml(group.group)}</strong>
      <div>${(group.items || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>
    </div>
  `).join("");
}

function renderSimpleHome(home) {
  const discovery = home.simple_cards.discovery;
  const leaderboard = home.simple_cards.leaderboard || {};
  const explorer = home.simple_cards.explorer || {};
  const sources = home.simple_cards.sources || {};
  const market = home.simple_cards.market;
  const best = home.simple_cards.best_wallets || {};
  const intelligence = home.simple_cards.intelligence || {};
  const security = home.simple_cards.security;
  $("#cardMarket").textContent = `${sources.sources_attempted ?? 0} sources`;
  $("#cardMarketDetail").textContent = `Leaderboard ${sources.leaderboard_status || "?"}, Explorer ${sources.explorer_status || "?"}, erreurs ${sources.source_errors ?? 0}.`;
  $("#cardDiscovery").textContent = `${discovery.candidates_found ?? 0} candidats`;
  $("#cardDiscoveryDetail").textContent = `${discovery.selected_wallets ?? 0} selectionnes, ${leaderboard.truncated_addresses_rejected ?? 0} tronquees rejetees, ${explorer.candidates_created ?? 0} via Explorer.`;
  $("#cardBestWallets").textContent = `${intelligence.openings_detected ?? 0} ouvertures`;
  $("#cardBestWalletsDetail").textContent = `${market.coins_scanned ?? 0} marches, ${intelligence.closings_detected ?? 0} fermetures, ${intelligence.playbooks ?? 0} playbooks, ${intelligence.follow_signals ?? 0} signaux paper.`;
  $("#cardSecurity").textContent = security.kill_switch ? "STOP" : "Lecture seule";
  $("#cardSecurityDetail").textContent = security.testnet_locked ? "Mainnet interdit, testnet verrouille." : "Verifie la configuration testnet.";
  $("#discoveryMessage").textContent = home.discovery_empty_state;
  setAutopilot(discovery);
  renderTimeline(discovery);
}

function renderSourceBreakdown(home, explorerStatus) {
  const leaderboard = home.simple_cards.leaderboard || {};
  const explorer = explorerStatus || home.simple_cards.explorer || {};
  const sources = home.simple_cards.sources || {};
  $("#sourceBreakdown").innerHTML = [
    `Leaderboard :: ${leaderboard.status || "IMPORT_REQUIRED"} :: full ${leaderboard.full_addresses_found ?? 0} :: tronquees ${leaderboard.truncated_addresses_rejected ?? 0}`,
    `Explorer :: ${explorer.status || "IMPORT_REQUIRED"} :: tx ${explorer.transactions_stored ?? 0} :: full ${explorer.full_addresses_found ?? 0}`,
    `Imports :: disponibles :: prochaine action ${sources.next_action || "import_leaderboard_or_explorer"}`,
    `DB locale :: disponible :: sources essayees ${sources.sources_attempted ?? 0}`
  ].map((line) => `<div class="feed-line"><span class="cyan">[SRC]</span> ${escapeHtml(line)}</div>`).join("");
}

function renderExplorerTape(rows) {
  $("#explorerTape").innerHTML = rows.length
    ? rows.slice(0, 12).map((row) => `
      <div class="feed-line">
        <span class="${row.candidate_created ? "green" : "orange"}">[TX]</span>
        ${escapeHtml(row.tx_hash || "-")} :: ${escapeHtml(row.wallet_address || "adresse non exploitable")} :: ${escapeHtml(row.coin || "-")} :: ${escapeHtml(row.status)}
      </div>
    `).join("")
    : `<div class="feed-line"><span class="orange">[INFO]</span> Explorer inspecte, mais aucune transaction structuree exploitable n'a encore ete extraite.</div>`;
}

function renderRejectedWallets(rows) {
  $("#rejectedWallets").innerHTML = rows.length
    ? rows.slice(0, 12).map((row) => `<div class="feed-line"><span class="orange">[REJET]</span> ${escapeHtml(row.address || row.tx_hash || "-")} :: ${escapeHtml(row.reason || row.status || "raison stockee")}</div>`).join("")
    : `<div class="feed-line"><span class="cyan">[INFO]</span> Aucun rejet stocke pour le moment. Les adresses tronquees seront affichees ici si detectees.</div>`;
}

function renderStatus(status) {
  $("#modeBadge").textContent = status.mode;
  $("#safetyBadge").textContent = status.safety_status;
  $("#safetyBadge").className = `badge pulse ${status.safety_status === "SAFE" ? "green" : status.safety_status === "STOPPED" ? "red" : "orange"}`;
  $("#testnetBadge").textContent = status.testnet_enabled ? "TESTNET ENABLED" : "TESTNET LOCKED";
  $("#riskGates").innerHTML = status.risk_gates.map((gate) => `
    <div class="gate">
      <span>${escapeHtml(gate.name)}</span>
      <strong class="${gate.passed ? "green" : "red"}">${gate.passed ? "PASS" : "BLOCK"}</strong>
    </div>
  `).join("");
}

function renderEvents(events) {
  if (!events.length) {
    $("#eventFeed").innerHTML = `<div class="feed-line"><span class="cyan">[INFO]</span> Demarrage de la recherche automatique.</div>`;
    return;
  }
  $("#eventFeed").innerHTML = events.slice(-18).reverse().map((event) => `
    <div class="feed-line">
      <span class="${event.level === "ERROR" || event.level === "SECURITY" ? "red" : event.level === "WARN" || event.level === "RISK" ? "orange" : "cyan"}">[${escapeHtml(event.level)}]</span>
      ${escapeHtml(event.message)}
    </div>
  `).join("");
}

function renderDiscoveryStatus(status) {
  $("#discoveryStatus").textContent = JSON.stringify(status, null, 2);
}

function renderCandidates(candidates) {
  $("#candidateTable").innerHTML = candidates.map((candidate) => `
    <tr>
      <td>${escapeHtml(candidate.address)}</td>
      <td>${escapeHtml(candidate.coin || "GLOBAL")}</td>
      <td>${escapeHtml(candidate.source)}</td>
      <td>${escapeHtml(candidate.external_pnl_usdc ?? "-")}</td>
      <td>${escapeHtml(candidate.external_roi_pct ?? "-")}</td>
      <td>${escapeHtml(Math.round(candidate.discovery_score ?? 0))}</td>
      <td>${escapeHtml(candidate.decision)}</td>
    </tr>
  `).join("");
}

function renderSelected(rows) {
  $("#selectedWallets").innerHTML = rows.length
    ? rows.map((row) => `<div class="feed-line"><span class="green">${escapeHtml(Math.round(row.discovery_score))}</span> ${escapeHtml(row.wallet_address)} :: ${escapeHtml(row.coin || "GLOBAL")} :: ${escapeHtml(row.source)}</div>`).join("")
    : `<div class="feed-line"><span class="orange">[INFO]</span> Aucun wallet selectionne pour le moment.</div>`;
}

function renderWalletsFeed(candidates, selected, knownWallets) {
  const target = $("#walletsFeed");
  if (!target) return;
  const rows = candidates.length ? candidates : selected.map((row) => ({
    address: row.wallet_address,
    coin: row.coin,
    source: row.source,
    discovery_score: row.discovery_score,
    decision: row.status
  }));
  const fallback = knownWallets.map((row) => ({
    address: row.address,
    coin: "GLOBAL",
    source: row.source,
    discovery_score: row.score,
    decision: row.status
  }));
  const finalRows = rows.length ? rows : fallback;
  target.innerHTML = finalRows.length
    ? finalRows.slice(0, 12).map((row) => `
      <div class="feed-line">
        <span class="green">[WALLET]</span>
        ${escapeHtml(shortAddress(row.address))} :: ${escapeHtml(row.coin || "GLOBAL")} ::
        score ${escapeHtml(Math.round(row.discovery_score ?? 0))} :: ${escapeHtml(row.decision || row.source || "observe")}
      </div>
    `).join("")
    : `<div class="feed-line"><span class="orange">[VIDE]</span> Aucun wallet complet stocke pour le moment. Le leaderboard va etre re-tente avant tout import manuel.</div>`;
}

function renderPositionsFeed(rows) {
  const target = $("#positionsFeed");
  if (!target) return;
  target.innerHTML = rows.length
    ? rows.slice(0, 12).map((row) => `
      <div class="feed-line">
        <span class="cyan">${escapeHtml(row.coin)}</span>
        ${escapeHtml(shortAddress(row.wallet_address))} :: ${escapeHtml(row.side || "?")} ${escapeHtml(row.size ?? 0)} ::
        notional ${escapeHtml(Math.round(row.notional_usdc ?? 0))} :: conf ${escapeHtml(Math.round((row.confidence_score ?? 0) * 100))}%
      </div>
    `).join("")
    : `<div class="feed-line"><span class="orange">[VIDE]</span> Aucune position reconstruite. Il faut des fills complets via backfill read-only.</div>`;
}

function renderFillsFeed(rows) {
  const target = $("#fillsFeed");
  if (!target) return;
  target.innerHTML = rows.length
    ? rows.slice(0, 12).map((row) => `
      <div class="feed-line">
        <span class="green">[FILL]</span>
        ${escapeHtml(shortAddress(row.wallet_address))} :: ${escapeHtml(row.coin)} :: ${escapeHtml(row.direction || row.side || "?")} ::
        px ${escapeHtml(row.price ?? "-")} size ${escapeHtml(row.size ?? "-")} pnl ${escapeHtml(row.closed_pnl ?? "-")}
      </div>
    `).join("")
    : `<div class="feed-line"><span class="orange">[VIDE]</span> Aucun fill stocke pour le moment. Le backfill demarre seulement sur wallets full-address selectionnes.</div>`;
}

function renderDeltasFeed(rows) {
  const target = $("#deltasFeed");
  if (!target) return;
  target.innerHTML = rows.length
    ? rows.slice(0, 12).map((row) => `
      <div class="feed-line">
        <span class="${row.action === "OPEN" || row.action === "ADD" ? "green" : "orange"}">[${escapeHtml(row.action || "DELTA")}]</span>
        ${escapeHtml(shortAddress(row.wallet_address))} :: ${escapeHtml(row.coin)} ::
        ${escapeHtml(row.previous_size ?? 0)} -> ${escapeHtml(row.new_size ?? 0)} :: ${escapeHtml(Math.round(row.delta_notional_usdc ?? 0))} USDC
      </div>
    `).join("")
    : `<div class="feed-line"><span class="orange">[VIDE]</span> Aucun delta reconstruit pour le moment. Les cas incertains restent marques bas-confidence.</div>`;
}

function renderOpenOrdersFeed(rows) {
  const target = $("#openOrdersFeed");
  if (!target) return;
  target.innerHTML = rows.length
    ? rows.slice(0, 12).map((row) => `
      <div class="feed-line">
        <span class="cyan">[ORDER]</span>
        ${escapeHtml(shortAddress(row.wallet_address))} :: ${escapeHtml(row.coin)} :: oid ${escapeHtml(row.oid || row.cloid || "-")}
      </div>
    `).join("")
    : `<div class="feed-line"><span class="orange">[VIDE]</span> Aucun open order public stocke. Aucune action reelle n'est possible depuis l'UI.</div>`;
}

function renderTopByCoinFeed(rows) {
  const target = $("#topByCoinFeed");
  if (!target) return;
  target.innerHTML = rows.length
    ? rows.slice(0, 12).map((row) => `
      <div class="feed-line">
        <span class="green">${escapeHtml(row.coin || "GLOBAL")}</span>
        ${escapeHtml(shortAddress(row.wallet_address || row.wallet || row.address))} :: score ${escapeHtml(Math.round(row.final_score || row.score || 0))}
      </div>
    `).join("")
    : `<div class="feed-line"><span class="orange">[VIDE]</span> Aucun classement wallet x coin encore calcule.</div>`;
}

function renderCopyStatus(payload) {
  const target = $("#copyStatusFeed");
  if (!target) return;
  const leaders = payload.leaders_followed || [];
  const header = [
    `mode ${payload.mode || "PAPER_MOCK_USDC"}`,
    `interval ${payload.polling_interval_seconds || 300}s`,
    `leaders ${payload.leaders_count || leaders.length || 0}`,
    `edge obligatoire ${payload.edge_remaining_bps_required ? "oui" : "non"}`
  ];
  const leaderRows = leaders.slice(0, 5).map((row) => `
    <div class="feed-line">
      <span class="green">[LEADER]</span>
      ${escapeHtml(shortAddress(row.wallet_address))} :: score ${escapeHtml(Math.round(row.score || 0))} :: ${escapeHtml(row.source || "leaderboard")}
    </div>
  `).join("");
  target.innerHTML = `
    <div class="feed-line"><span class="cyan">[COPY]</span> ${header.map(escapeHtml).join(" :: ")}</div>
    <div class="feed-line"><span class="orange">[SAFE]</span> dry-run paper/mock USDC seulement, aucun ordre reel.</div>
    ${leaderRows || `<div class="feed-line"><span class="orange">[VIDE]</span> Aucun leader shortlist pour le moment.</div>`}
  `;
}

function renderLeaderActivity(rows) {
  const target = $("#leaderActivityFeed");
  if (!target) return;
  target.innerHTML = rows.length
    ? rows.slice(0, 12).map((row) => `
      <div class="feed-line">
        <span class="${row.copyable ? "green" : "orange"}">[${escapeHtml(row.action || "UNKNOWN")}]</span>
        ${escapeHtml(shortAddress(row.wallet_address))} :: ${escapeHtml(row.coin || "-")} ::
        ${escapeHtml(row.previous_size ?? 0)} -> ${escapeHtml(row.new_size ?? 0)} :: edge verifie avant paper
      </div>
    `).join("")
    : `<div class="feed-line"><span class="orange">[VIDE]</span> Aucun delta leader observe. Le copy loop reste en dry-run.</div>`;
}

function renderNoTradeReport(payload) {
  const target = $("#noTradeFeed");
  if (!target) return;
  const reasons = payload.reasons || [];
  target.innerHTML = reasons.length
    ? reasons.slice(0, 12).map((row) => `
      <div class="feed-line">
        <span class="orange">[NO-TRADE]</span>
        ${escapeHtml(row.reason)} :: ${escapeHtml(row.count)} refus
      </div>
    `).join("")
    : `<div class="feed-line"><span class="cyan">[INFO]</span> Aucun signal refuse stocke. Un signal sans edge_remaining_bps positif sera bloque.</div>`;
}

function renderSimulationOverview(payload) {
  const summary = $("#simulationSummary");
  if (!summary) return;
  const counts = payload.counts || {};
  const equity = payload.equity || {};

  // Update Metagraph Stats Bar
  const mRoi = $("#mStatRoi");
  const mWinRate = $("#mStatWinRate");
  const mPf = $("#mStatPf");
  const mDrawdown = $("#mStatDrawdown");
  if (mRoi) {
    const roi = ((equity.current_equity_usdt - equity.starting_equity_usdt) / equity.starting_equity_usdt) * 100;
    mRoi.textContent = `${roi.toFixed(2)}%`;
    mRoi.className = roi >= 0 ? "green" : "red";
  }
  if (mWinRate) mWinRate.textContent = `${((equity.win_rate || 0) * 100).toFixed(1)}%`;
  if (mPf) mPf.textContent = (equity.profit_factor || 0).toFixed(2);
  if (mDrawdown) mDrawdown.textContent = `${(equity.max_drawdown_pct || 0).toFixed(2)}%`;
  const scanner = payload.scanner || {};
  const autopilot = payload.autopilot || {};
  const metrics = [
    ["P&L bot", formatUsd(equity.current_pnl_usdc ?? 0)],
    ["Capital", `${formatUsd(equity.current_equity_usdt ?? 1000)} USDT`],
    ["Latent", formatUsd(equity.unrealized_pnl_usdc ?? 0)],
    ["Realise", formatUsd(equity.realized_pnl_usdc ?? 0)]
  ];
  summary.innerHTML = metrics.map(([label, value]) => `
    <div class="simulation-metric">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `).join("");

  const liveStrip = $("#simulationLiveStrip");
  if (liveStrip) {
    const secondsSince = payload.seconds_since_last_live_event;
    const lastEventText = secondsSince === null || secondsSince === undefined
      ? "aucun delta leader frais"
      : `${secondsSince}s depuis dernier delta`;
    const refused = Number(counts.bot_refused || 0);
    const entries = Number(counts.reproduced_entries || 0);
    const deltas = Number(counts.live_simulation_deltas || 0);
    const lastReason = (payload.no_trade_reasons || [])[0]?.reason || "aucun refus";
    const latestTrade = (payload.public_trade_activity || [])[0];
    const connectionWarning = payload.connection_warning
      ? `<div class="simulation-live-pill red"><span>Connexion</span><strong>${escapeHtml(payload.connection_warning)}</strong></div>`
      : "";
    liveStrip.innerHTML = `
      <div class="simulation-live-pill green">
        <span>Scan public read-only</span>
        <strong>${escapeHtml(counts.public_trade_wallets_seen || scanner.public_trade_wallets_seen || 0)} wallets vus / ${escapeHtml(counts.public_trade_promoted_wallets || scanner.public_trade_promoted_wallets || 0)} promus</strong>
      </div>
      <div class="simulation-live-pill ${deltas ? "green" : "orange"}">
        <span>Deltas leaders frais</span>
        <strong>${escapeHtml(deltas)} analyses :: ${escapeHtml(lastEventText)}</strong>
      </div>
      <div class="simulation-live-pill ${entries ? "green" : "orange"}">
        <span>Reproduction locale</span>
        <strong>${escapeHtml(entries)} entrees / ${escapeHtml(counts.reproduced_exits || 0)} sorties / ${escapeHtml(refused)} refus</strong>
      </div>
      <div class="simulation-live-pill ${refused && !entries ? "red" : "orange"}">
        <span>Dernier etat</span>
        <strong>${latestTrade ? `${escapeHtml(latestTrade.coin)} ${escapeHtml(formatUsd(latestTrade.notional_usdc || 0))}` : escapeHtml(lastReason)}</strong>
      </div>
      ${connectionWarning}
    `;
  }

  const walletsTarget = $("#simulationWalletsFeed");
  const consensusTarget = $("#simulationConsensusFeed");
  const deltasTarget = $("#simulationDeltasFeed");
  const replayTarget = $("#simulationReplayFeed");
  const positionsTarget = $("#simulationPositionsFeed");
  const noTradeTarget = $("#simulationNoTradeFeed");
  const decisionTape = $("#simulationDecisionTape");
  const leaders = payload.leaders || [];
  const consensus = payload.consensus || [];
  const entryDeltas = payload.entry_deltas || [];
  const botSimulation = payload.bot_simulation || payload.reproduction || {};
  const replay = botSimulation.events || [];
  const virtualPositions = botSimulation.open_positions || [];
  const reasons = payload.no_trade_reasons || [];
  equity.public_trade_wallets_seen = counts.public_trade_wallets_seen || scanner.public_trade_wallets_seen || 0;
  equity.live_simulation_deltas = counts.live_simulation_deltas || 0;
  equity.bot_refused = counts.bot_refused || 0;
  equity.reproduced_entries = counts.reproduced_entries || 0;
  equity.last_no_trade_reason = (reasons[0] || {}).reason || null;
  drawSimulationMetaGraph(payload.equity_candles || [], equity);

  if (decisionTape) {
    const decisionRows = replay.length
      ? replay.slice(0, 5).map((row) => {
        const pnl = row.estimated_net_pnl_usdc;
        const pnlClass = pnl === null || pnl === undefined ? "cyan" : Number(pnl) >= 0 ? "green" : "red";
        const statusClass = row.status === "LOCAL_REPLAY" ? "green" : "orange";
        return `
          <div class="feed-line">
            <span class="${statusClass}">[${escapeHtml(row.bot_replay_action || "NO_TRADE")}]</span>
            ${escapeHtml(formatClockMs(row.observed_at_ms))} :: ${escapeHtml(shortAddress(row.wallet_address))} ::
            ${escapeHtml(row.coin)} ${escapeHtml(row.leader_side || "")} ::
            <span class="${pnlClass}">${pnl === null || pnl === undefined ? "PnL -" : formatUsd(pnl)}</span> ::
            edge ${escapeHtml(row.edge_remaining_bps ?? "-")} bps :: risque ${escapeHtml(Math.round(row.risk_score ?? 0))} ::
            ${escapeHtml(row.reason || "simulation locale")}
          </div>
        `;
      }).join("")
      : `<div class="feed-line"><span class="cyan">[LIVE]</span> ${escapeHtml(payload.connection_warning || payload.next_step || "Simulation armee, attente d'un delta leader frais.")}</div>`;
    decisionTape.innerHTML = decisionRows;
  }

  walletsTarget.innerHTML = leaders.length
    ? leaders.slice(0, 50).map((row) => `
      <div class="feed-line">
        <span class="green">[LEADER]</span>
        ${escapeHtml(shortAddress(row.wallet_address))} :: score ${escapeHtml(Math.round(row.score || 0))} :: ${escapeHtml(row.status || "observe")}
      </div>
    `).join("")
    : `<div class="feed-line"><span class="orange">[VIDE]</span> Aucun wallet leader charge. Importer des adresses completes ou relancer la discovery read-only.</div>`;

  consensusTarget.innerHTML = consensus.length
    ? consensus.slice(0, 8).map((row) => `
      <div class="feed-line">
        <span class="${row.crowding_risk === "HIGH" ? "orange" : "green"}">[${escapeHtml(row.direction)}]</span>
        ${escapeHtml(row.coin)} :: ${escapeHtml(row.wallet_count)} wallets :: score ${escapeHtml(row.consensus_score)} ::
        crowding ${escapeHtml(row.crowding_risk)}
      </div>
    `).join("")
    : `<div class="feed-line"><span class="cyan">[INFO]</span> Aucun consensus multi-wallet detecte sur la fenetre 5 minutes.</div>`;

  deltasTarget.innerHTML = entryDeltas.length
    ? entryDeltas.slice(0, 10).map((row) => `
      <div class="feed-line">
        <span class="green">[${escapeHtml(row.action)}]</span>
        ${escapeHtml(shortAddress(row.wallet_address))} :: ${escapeHtml(row.coin)} ${escapeHtml(row.direction)} ::
        px ${escapeHtml(row.price ?? "-")} :: notional ${escapeHtml(Math.round(row.notional_usdc ?? 0))}
      </div>
    `).join("")
    : `<div class="feed-line"><span class="orange">[VIDE]</span> Aucune ouverture/augmentation exploitable pour entrer. ${escapeHtml(payload.next_step || "Collecter des fills/positions en lecture seule.")}</div>`;

  replayTarget.innerHTML = replay.length
    ? replay.slice(0, 14).map((row) => {
      const pnl = row.estimated_net_pnl_usdc;
      const pnlClass = pnl === null || pnl === undefined ? "cyan" : Number(pnl) >= 0 ? "green" : "red";
      const statusClass = row.status === "LOCAL_REPLAY" ? "green" : "orange";
      return `
        <div class="feed-line">
          <span class="${statusClass}">[${escapeHtml(row.bot_replay_action || "NO_TRADE")}]</span>
          ${escapeHtml(shortAddress(row.wallet_address))} :: ${escapeHtml(row.coin)} :: leader ${escapeHtml(row.leader_action)} ::
          <span class="${pnlClass}">${pnl === null || pnl === undefined ? "PnL -" : formatUsd(pnl)}</span> ::
          edge ${escapeHtml(row.edge_remaining_bps ?? "-")} bps :: score ${escapeHtml(Math.round(row.opportunity_score ?? 0))} ::
          risque ${escapeHtml(Math.round(row.risk_score ?? 0))} ::
          taille ${escapeHtml(row.copied_notional_usdt == null ? "-" : formatUsd(row.copied_notional_usdt))} ::
          ${escapeHtml(row.reason || "local replay")}
        </div>
      `;
    }).join("")
    : `<div class="feed-line"><span class="orange">[VIDE]</span> Le bot simule n'a encore aucune decision. Lance une collecte read-only bornee pour remplir les deltas.</div>`;

  positionsTarget.innerHTML = virtualPositions.length
    ? virtualPositions.slice(0, 12).map((row) => {
      const pnl = Number(row.unrealized_pnl_usdc || 0);
      return `
        <div class="feed-line">
          <span class="${pnl >= 0 ? "green" : "red"}">[${escapeHtml(row.direction)}]</span>
          ${escapeHtml(shortAddress(row.wallet_address))} :: ${escapeHtml(row.coin)} ::
          size ${escapeHtml(row.size)} :: entry ${escapeHtml(row.avg_entry_price)} :: mark ${escapeHtml(row.mark_price)} ::
          ${escapeHtml(formatUsd(pnl))}
        </div>
      `;
    }).join("")
    : `<div class="feed-line"><span class="cyan">[FLAT]</span> Le portefeuille virtuel du bot n'a aucune position ouverte.</div>`;

  noTradeTarget.innerHTML = reasons.length
    ? reasons.slice(0, 10).map((row) => `
      <div class="feed-line">
        <span class="orange">[REFUS]</span>
        ${escapeHtml(row.reason)} :: ${escapeHtml(row.count)}
      </div>
    `).join("")
    : `<div class="feed-line"><span class="cyan">[INFO]</span> Aucun refus stocke. Tout signal incertain sera refuse avant simulation locale.</div>`;

  noTradeTarget.innerHTML += `
    <div class="feed-line"><span class="green">[FRESH]</span> mode frais uniquement depuis ${escapeHtml(formatClockMs(payload.fresh_cutoff_ms || payload.simulation_started_at_ms))} :: anciens deltas ignores ${escapeHtml(counts.old_deltas_ignored_fresh_only ?? 0)} :: dernier frais ${escapeHtml(formatClockMs(payload.last_live_event_ms))}</div>
    <div class="feed-line"><span class="cyan">[SCAN]</span> surveillance ${scanner.active ? "active" : "inactive"} :: actifs ${escapeHtml(scanner.target_wallets || counts.target_leaders || 50)} wallets :: flux public ${escapeHtml(counts.public_trade_wallets_seen || scanner.public_trade_wallets_seen || 0)} wallets vus / ${escapeHtml(counts.public_trade_promoted_wallets || scanner.public_trade_promoted_wallets || 0)} promus :: refresh UI ${escapeHtml(scanner.ui_refresh_seconds || 5)}s :: poll ${escapeHtml(scanner.polling_interval_seconds || 300)}s</div>
    <div class="feed-line"><span class="cyan">[AUTO]</span> ${escapeHtml(autopilot.job_a || "leaderboard")} -> ${escapeHtml(autopilot.job_b || "copy_loop")} -> ${escapeHtml(autopilot.job_c || "reports")} :: reproduction ${escapeHtml(autopilot.position_reproduction || "paper research only")}</div>
    <div class="feed-line"><span class="cyan">[CAPITAL]</span> depart ${escapeHtml(formatUsd(equity.starting_equity_usdt || 1000))} USDT :: actuel ${escapeHtml(formatUsd(equity.current_equity_usdt || 1000))} USDT</div>
    <div class="feed-line"><span class="cyan">[PNL]</span> source ${escapeHtml(equity.source || "local")} :: realise ${escapeHtml(formatUsd(equity.realized_pnl_usdc || 0))} :: latent ${escapeHtml(formatUsd(equity.unrealized_pnl_usdc || 0))} :: couts ${escapeHtml(formatUsd(equity.bot_costs_paid_usdc || 0))}</div>
    <div class="feed-line"><span class="green">[HOLD]</span> une position virtuelle reste ouverte jusqu'a REDUCE/CLOSE leader correspondant; elle n'est jamais fermee uniquement parce que le latent est rouge.</div>
    <div class="feed-line"><span class="cyan">[ETAT]</span> ${escapeHtml(payload.readiness || "UNKNOWN")} :: ${escapeHtml(payload.message || "Simulation locale seulement.")}</div>
  `;
}

function drawSimulationMetaGraph(candles, equity) {
  const canvas = $("#simulationMetaGraph");
  const state = $("#simulationGraphState");
  const tooltip = $("#simulationGraphTooltip");
  const btnExport = $("#btnExportLedger");
  if (!canvas || !state || !tooltip) return;

  if (btnExport && !btnExport.dataset.wired) {
      btnExport.dataset.wired = "true";
      btnExport.onclick = () => {
          if (!candles.length) return;
          const headers = ["Timestamp", "Wallet", "Coin", "Action", "P&L", "Equity", "Costs", "Reason", "ID"];
          const rows = candles.map(c => [
              new Date(c.timestamp_ms).toISOString(),
              c.wallet_address || "",
              c.coin || "",
              c.action_type || "",
              c.pnl_usdc,
              c.equity_close,
              c.costs,
              `"${(c.reason || "").replace(/"/g, '""')}"`,
              c.position_id || ""
          ]);
          const csvContent = [headers, ...rows].map(e => e.join(",")).join("\n");
          const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.setAttribute("href", url);
          link.setAttribute("download", `simulation_ledger_${Date.now()}.csv`);
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
      };
  }

  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(640, Math.floor(rect.width || canvas.width));
  const height = 320;
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "rgba(5,7,13,0.74)";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(0,217,255,0.12)";
  ctx.lineWidth = 1;
  for (let x = 44; x < width; x += 64) {
    ctx.beginPath();
    ctx.moveTo(x, 12);
    ctx.lineTo(x, height - 28);
    ctx.stroke();
  }
  for (let y = 24; y < height - 28; y += 44) {
    ctx.beginPath();
    ctx.moveTo(44, y);
    ctx.lineTo(width - 18, y);
    ctx.stroke();
  }

  if (!candles.length) {
    const scanWallets = Number((equity && equity.public_trade_wallets_seen) || 0);
    const liveDeltas = Number((equity && equity.live_simulation_deltas) || 0);
    const refused = Number((equity && equity.bot_refused) || 0);
    const entries = Number((equity && equity.reproduced_entries) || 0);
    const mid = Math.round(height / 2);
    ctx.strokeStyle = "rgba(255,176,32,0.65)";
    ctx.setLineDash([8, 8]);
    ctx.beginPath();
    ctx.moveTo(44, mid);
    ctx.lineTo(width - 18, mid);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#ffb020";
    ctx.font = "14px Cascadia Code, Consolas, monospace";
    const waitText = liveDeltas > 0
      ? `Analyse active : ${liveDeltas} deltas frais, ${refused} refus, ${entries} reproductions. P&L stable car edge insuffisant.`
      : scanWallets > 0
      ? `Scan public actif : ${scanWallets} wallets vus. En attente d'un OPEN/ADD confirme pour bouger le P&L.`
      : "En attente d'un evenement leader frais : P&L bot maintenu a $0.00.";
    ctx.fillText(waitText, 58, mid - 14);
    state.textContent = "PNL $0.00 frais uniquement";
    if (liveDeltas > 0 && refused > 0) {
      state.textContent = `NO-TRADE ${refused} refus`;
      state.className = "badge red";
    } else {
      state.className = "badge orange";
    }
    canvas.onmousemove = null;
    tooltip.classList.add("hidden");
    return;
  }

  const values = candles.flatMap((row) => [row.ha_high, row.ha_low, row.equity_close, row.equity_open]);
  let minValue = Math.min(...values, 0);
  let maxValue = Math.max(...values, 0);
  const range = maxValue - minValue;
  const padding = range * 0.15 || 10;
  minValue -= padding;
  maxValue += padding;

  const plotLeft = 64;
  const plotRight = width - 24;
  const plotTop = 24;
  const plotBottom = height - 44;
  const plotHeight = plotBottom - plotTop;
  const xStep = (plotRight - plotLeft) / Math.max(1, candles.length);
  const candleWidth = Math.max(4, Math.min(14, xStep * 0.5));
  const yFor = (value) => plotBottom - ((value - minValue) / (maxValue - minValue)) * plotHeight;

  // Zero Line
  const zeroY = yFor(0);
  ctx.strokeStyle = "rgba(255,255,255,0.4)";
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(plotLeft, zeroY);
  ctx.lineTo(plotRight, zeroY);
  ctx.stroke();
  ctx.setLineDash([]);

  // Equity Area Gradient
  const gradient = ctx.createLinearGradient(0, plotTop, 0, plotBottom);
  gradient.addColorStop(0, "rgba(0, 217, 255, 0.15)");
  gradient.addColorStop(1, "rgba(0, 217, 255, 0)");
  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.moveTo(plotLeft + xStep / 2, plotBottom);
  candles.forEach((row, index) => {
    const x = plotLeft + index * xStep + xStep / 2;
    const y = yFor(row.equity_close);
    ctx.lineTo(x, y);
  });
  ctx.lineTo(plotLeft + (candles.length - 1) * xStep + xStep / 2, plotBottom);
  ctx.closePath();
  ctx.fill();

  // Equity Line
  ctx.strokeStyle = "rgba(0,217,255,0.8)";
  ctx.shadowBlur = 8;
  ctx.shadowColor = "rgba(0, 217, 255, 0.5)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  candles.forEach((row, index) => {
    const x = plotLeft + index * xStep + xStep / 2;
    const y = yFor(row.equity_close);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.lineWidth = 1;
  ctx.shadowBlur = 0;

  const hitboxes = [];
  candles.forEach((row, index) => {
    const x = plotLeft + index * xStep + xStep / 2;
    const openY = yFor(row.ha_open);
    const closeY = yFor(row.ha_close);
    const highY = yFor(row.ha_high);
    const lowY = yFor(row.ha_low);
    const top = Math.min(openY, closeY);
    const bodyHeight = Math.max(2, Math.abs(closeY - openY));
    const color = row.color === "green" ? "#00ff88" : "#ff3b5f";

    // Wicks
    ctx.strokeStyle = color;
    ctx.beginPath();
    ctx.moveTo(x, highY);
    ctx.lineTo(x, lowY);
    ctx.stroke();

    // Body
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.6;
    ctx.fillRect(x - candleWidth / 2, top, candleWidth, bodyHeight);
    ctx.globalAlpha = 1;

    // Action Markers
    const action = row.action_type || "";
    if (action.includes("ENTRY") || action.includes("ADD") || action.includes("JOIN")) {
      ctx.fillStyle = "#00ff88";
      ctx.beginPath();
      ctx.moveTo(x, lowY + 8);
      ctx.lineTo(x - 4, lowY + 16);
      ctx.lineTo(x + 4, lowY + 16);
      ctx.fill();
    } else if (action.includes("CLOSE") || action.includes("REDUCE")) {
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x - 4, highY - 12);
      ctx.lineTo(x + 4, highY - 4);
      ctx.moveTo(x + 4, highY - 12);
      ctx.lineTo(x - 4, highY - 4);
      ctx.stroke();
      ctx.lineWidth = 1;
    }

    hitboxes.push({ x, row });
  });

  ctx.fillStyle = "#8aa0b6";
  ctx.font = "11px Cascadia Code, Consolas, monospace";
  ctx.fillText(formatUsd(maxValue), 8, plotTop + 4);
  ctx.fillText(formatUsd(minValue), 8, plotBottom + 12);
  const current = Number(equity.current_pnl_usdc || (candles.length ? candles[candles.length - 1].equity_close : 0));
  state.textContent = `PNL ${formatUsd(current)}`;
  state.className = `badge ${current >= 0 ? "green" : "red"}`;

  canvas.onmousemove = (event) => {
    const bounds = canvas.getBoundingClientRect();
    const mouseX = (event.clientX - bounds.left) * (width / bounds.width);
    let nearest = hitboxes[0];
    for (const item of hitboxes) {
      if (Math.abs(item.x - mouseX) < Math.abs(nearest.x - mouseX)) nearest = item;
    }
    if (!nearest) return;
    const row = nearest.row;
    const dateStr = new Date(row.timestamp_ms).toLocaleTimeString();

    tooltip.classList.remove("hidden");
    tooltip.style.left = `${Math.min(width - 280, Math.max(8, (nearest.x * bounds.width / width) + 14))}px`;
    tooltip.style.top = `${Math.max(8, event.clientY - bounds.top - 18)}px`;
    tooltip.innerHTML = `
      <div style="border-bottom:1px solid rgba(255,255,255,0.1);padding-bottom:4px;margin-bottom:4px;">
        <strong>${escapeHtml(row.coin)} ${escapeHtml(shortAddress(row.wallet_address || ""))}</strong>
        <span style="float:right;opacity:0.6">${escapeHtml(dateStr)}</span>
      </div>
      Action: <span class="cyan">${escapeHtml(row.action_type || "MARK_TO_MARKET")}</span><br>
      Delta P&L: <span class="${row.pnl_usdc >= 0 ? "green" : "red"}">${escapeHtml(formatUsd(row.pnl_usdc))}</span><br>
      Equity After: <strong>${escapeHtml(formatUsd(row.equity_close))}</strong>
      <span style="opacity:0.6;font-size:0.9em">(${row.is_unrealized ? "latent" : "réalisé"})</span><br>
      Cumulative Costs: ${escapeHtml(formatUsd(row.cumulative_costs || 0))}<br>
      ID: <span style="font-family:monospace;font-size:0.85em;opacity:0.7">${escapeHtml(row.position_id || "-")}</span><br>
      <div style="margin-top:4px;font-size:0.9em;opacity:0.8;color:var(--orange);border-top:1px solid rgba(255,255,255,0.05);padding-top:4px;">
        Click to sync decision tape
      </div>
    `;
  };
  canvas.onclick = (event) => {
      const bounds = canvas.getBoundingClientRect();
      const mouseX = (event.clientX - bounds.left) * (width / bounds.width);
      let nearest = hitboxes[0];
      for (const item of hitboxes) {
          if (Math.abs(item.x - mouseX) < Math.abs(nearest.x - mouseX)) nearest = item;
      }
      if (!nearest) return;
      const row = nearest.row;
      const tape = $("#simulationDecisionTape");
      if (!tape) return;

      const entries = Array.from(tape.querySelectorAll(".feed-line"));
      const target = entries.find(el => el.textContent.includes(row.position_id) || el.textContent.includes(new Date(row.timestamp_ms).toLocaleTimeString()));

      if (target) {
          entries.forEach(el => el.classList.remove("highlight"));
          target.classList.add("highlight");
          target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
  };
  canvas.onmouseleave = () => tooltip.classList.add("hidden");
}

function renderCoinMetrics(metrics) {
  const target = $("#coinMetrics");
  if (!target) return;
  target.innerHTML = metrics.length
    ? metrics.slice(0, 20).map((row) => `
      <div class="feed-line">
        <span class="cyan">${escapeHtml(row.coin)}</span>
        depth ${escapeHtml(Math.round(row.depth_usdc ?? 0))} USDC ::
        spread ${escapeHtml(row.spread_bps == null ? "-" : row.spread_bps.toFixed(2))} bps ::
        ${row.is_scannable ? "scannable" : escapeHtml(row.rejection_reason || "non scannable")}
      </div>
    `).join("")
    : `<div class="feed-line"><span class="orange">[INFO]</span> Aucune metrique coin stockee pour le moment.</div>`;
}

function renderActionCatalog(items) {
  const target = $("#actionCatalog");
  if (!target) return;
  const groups = {};
  items.forEach((item) => {
    groups[item.group] = groups[item.group] || [];
    groups[item.group].push(item);
  });
  target.innerHTML = Object.entries(groups).map(([group, groupItems]) => `
    <div class="action-group">
      <h3>${escapeHtml(group)}</h3>
      <div class="action-grid">
        ${groupItems.map((item) => `
          <button data-action="${escapeHtml(item.action_id)}" ${item.enabled ? "" : "disabled"} title="${escapeHtml(item.description)}">
            <span>${escapeHtml(item.label)}</span>
            <small>${escapeHtml(item.enabled ? item.expected_result : item.disabled_reason || "Indisponible")}</small>
          </button>
        `).join("")}
      </div>
    </div>
  `).join("");
  target.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => runAction(button.dataset.action));
  });
}

function renderLogs(logs) {
  logLines = logs;
  const filtered = activeFilter === "ALL" ? logLines : logLines.filter((line) => line.level === activeFilter);
  $("#logConsole").textContent = filtered.map((line) => {
    const ts = new Date(line.timestamp_ms).toLocaleTimeString();
    return `${ts} [${line.level}] ${line.message}`;
  }).join("\n");
  $("#logConsole").scrollTop = $("#logConsole").scrollHeight;
}

async function loadSimpleHome() {
  if (fullRefreshInFlight) return;
  fullRefreshInFlight = true;
  try {
  const emptyDiscovery = { running: false, state: "idle", candidates_found: 0, selected_wallets: 0, backfilled_wallets: 0 };
  const home = await safeGetJson("/api/simple-home", {
    simple_cards: {
      sources: { sources_attempted: 0, leaderboard_status: "IMPORT_REQUIRED", explorer_status: "IMPORT_REQUIRED", source_errors: 0, next_action: "import_leaderboard_or_explorer" },
      market: { coins_discovered: 0, coins_scanned: 0, l2_books_analyzed: 0, altcoins_enabled: true },
      leaderboard: { full_addresses_found: 0, truncated_addresses_rejected: 0 },
      explorer: { status: "IMPORT_REQUIRED", transactions_stored: 0, full_addresses_found: 0, candidates_created: 0 },
      discovery: emptyDiscovery,
      intelligence: {},
      best_wallets: {},
      security: { kill_switch: false, testnet_locked: true }
    },
    autoscan: { analyzes: [] },
    discovery_empty_state: "Chargement du scan automatique..."
  });
  const [status, discovery, candidates, selected, metrics, events, logs, actions, autoscan, explorerStatus, explorerTape, rejectedCandidates, knownWallets, positions, fills, deltas, openOrders, topByCoin, copyStatus, leaderActivity, noTradeReport, simulationOverview] = await Promise.all([
    safeGetJson("/api/status", { mode: "PAPER", safety_status: "SAFE", risk_gates: [] }),
    safeGetJson("/api/discovery/status", emptyDiscovery),
    safeGetJson("/api/discovery/candidates", []),
    safeGetJson("/api/discovery/selected", []),
    safeGetJson("/api/markets/metrics", []),
    safeGetJson("/api/events/recent", []),
    safeGetJson("/api/logs", []),
    safeGetJson("/api/actions/catalog", []),
    safeGetJson("/api/autoscan/status", home.autoscan || {}),
    safeGetJson("/api/explorer/status", {}),
    safeGetJson("/api/explorer/transactions", []),
    safeGetJson("/api/candidates/rejected", []),
    safeGetJson("/api/wallets", []),
    safeGetJson("/api/positions", []),
    safeGetJson("/api/fills/recent", []),
    safeGetJson("/api/position-deltas/recent", []),
    safeGetJson("/api/open-orders", []),
    safeGetJson("/api/wallets/top-by-coin", []),
    safeGetJson("/api/copy/status", {}),
    safeGetJson("/api/copy/leader-activity", []),
    safeGetJson("/api/copy/no-trade-report", {}),
    getSimulationOverviewPayload()
  ]);
  renderSimpleHome(home);
  renderScanOverview(home, autoscan);
  renderSourceBreakdown(home, explorerStatus);
  renderExplorerTape(explorerTape);
  renderRejectedWallets(rejectedCandidates);
  renderStatus(status);
  renderDiscoveryStatus(discovery);
  renderCandidates(candidates);
  renderSelected(selected);
  renderWalletsFeed(candidates, selected, knownWallets);
  renderPositionsFeed(positions);
  renderFillsFeed(fills);
  renderDeltasFeed(deltas);
  renderOpenOrdersFeed(openOrders);
  renderTopByCoinFeed(topByCoin);
  renderCopyStatus(copyStatus);
  renderLeaderActivity(leaderActivity);
  renderNoTradeReport(noTradeReport);
  renderSimulationOverview(simulationOverview);
  renderCoinMetrics(metrics);
  renderEvents(events);
  renderLogs(logs);
  renderActionCatalog(actions);
  } finally {
    fullRefreshInFlight = false;
  }
}

async function refreshSimulationOverview() {
  if (simulationRefreshInFlight) return;
  simulationRefreshInFlight = true;
  try {
    const simulationOverview = await getSimulationOverviewPayload();
    renderSimulationOverview(simulationOverview);
  } finally {
    simulationRefreshInFlight = false;
  }
}

async function runAction(action) {
  const result = await postJson("/api/actions", { action });
  await loadSimpleHome();
  return result;
}

async function startAutoScanWithDiscoveryIfAllowed() {
  if (autoscanRequested) return;
  autoscanRequested = true;
  try {
    postJson("/api/autoscan/start", {})
      .then(() => loadSimpleHome().catch(() => {}))
      .catch((error) => {
        console.warn("autoscan failed", error);
        logLines.push({ level: "WARN", timestamp_ms: Date.now(), message: "Auto-scan indisponible cote UI, voir logs serveur." });
        renderLogs(logLines);
      });
  } catch (error) {
    console.warn("autoscan failed", error);
  }
}

function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${proto}://${location.host}/ws`);
  socket.onmessage = () => refreshSimulationOverview().catch(() => {});
  socket.onclose = () => setTimeout(connectWebSocket, 2000);
}

function wireUi() {
  $$("[data-action]").forEach((button) => {
    button.addEventListener("click", () => runAction(button.dataset.action));
  });
  $("#expertToggle").addEventListener("click", () => {
    const hidden = $("#expertPanel").classList.toggle("hidden");
    $("#terminalPanel").classList.toggle("hidden", hidden);
    $("#expertToggle").textContent = hidden ? "Afficher les details techniques" : "Masquer les details techniques";
  });
  $$("[data-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      activeFilter = button.dataset.filter;
      $$("[data-filter]").forEach((node) => node.classList.remove("active"));
      button.classList.add("active");
      renderLogs(logLines);
    });
  });
}

setInterval(tickClock, 1000);
setInterval(() => refreshSimulationOverview().catch(() => {}), 1000);
setInterval(() => loadSimpleHome().catch(() => {}), 10000);
tickClock();
wireUi();
connectWebSocket();
startAutoScanWithDiscoveryIfAllowed();
loadSimpleHome().catch(() => {});
