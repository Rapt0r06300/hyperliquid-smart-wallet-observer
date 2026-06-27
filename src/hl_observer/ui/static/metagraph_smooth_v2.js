/* HyperSmart smooth metagraph renderer V2
 * READ-ONLY UI layer: the graph display is smoothed, but values come only from
 * server samples: Hyperliquid simulation overview and session candles.
 */
(function () {
  const state = {
    samples: [],
    targetPnl: 0,
    displayPnl: 0,
    initialized: false,
    lastTickAt: 0,
    raf: null,
    lastEquity: null,
    lastSource: "initial",
  };

  function q(selector) { return document.querySelector(selector); }
  function num(v, fallback) {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function smoothstep(t) { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); }
  function formatUsd(v) {
    const n = num(v, 0);
    return `${n > 0 ? "+" : ""}$${n.toFixed(2)}`;
  }

  function sampleFromOverview(overview) {
    const equity = overview && overview.equity ? overview.equity : {};
    const bot = overview && overview.bot_simulation ? overview.bot_simulation : {};
    const pnl = num(equity.current_pnl_usdc ?? bot.estimated_net_pnl_usdc, state.targetPnl);
    const eq = num(equity.current_equity_usdt ?? bot.current_equity_usdt, 1000 + pnl);
    return {
      pnl,
      equity: eq,
      timestamp: num(overview && overview.current_time_ms, Date.now()),
      source: equity.source || "hyperliquid_simulation_overview",
    };
  }

  function addSample(pnl, ts, source, equity) {
    const value = num(pnl, state.targetPnl || 0);
    const at = Math.max(1, Math.floor(num(ts, Date.now())));
    const previous = state.samples[state.samples.length - 1];
    if (previous && Math.abs(previous.value - value) < 0.000001 && at - previous.ts < 800) return;
    state.samples.push({ value, ts: at, source: source || "sample", equity: num(equity, 1000 + value), anchor: true });
    state.samples.sort((a, b) => a.ts - b.ts);
    state.samples = state.samples.slice(-420);
    state.targetPnl = value;
    state.lastTickAt = Date.now();
    state.lastEquity = num(equity, 1000 + value);
    state.lastSource = source || "sample";
    if (!state.initialized) {
      state.displayPnl = value;
      state.initialized = true;
    }
  }

  function seedFromCandles(candles, equity) {
    const rows = Array.isArray(candles) ? candles : [];
    for (const row of rows.slice(-240)) {
      addSample(
        num(row.equity_close ?? row.ha_close ?? row.pnl_usdc, 0),
        row.timestamp_ms || row.observed_at_ms || row.index || Date.now(),
        row.source || "equity_candle",
        row.current_equity_usdt
      );
    }
    if (equity) {
      addSample(
        num(equity.current_pnl_usdc ?? equity.net_pnl_usdt, state.targetPnl),
        equity.timestamp_ms || Date.now(),
        equity.source || "overview_equity",
        equity.current_equity_usdt
      );
    }
  }

  function buildSeries() {
    const raw = state.samples.slice(-180);
    if (!raw.length) return [];
    if (raw.length === 1) return [{ ...raw[0], display: raw[0].value }];
    const out = [];
    for (let i = 0; i < raw.length - 1; i += 1) {
      const a = raw[i];
      const b = raw[i + 1];
      out.push({ ...a, display: a.value, anchor: true });
      const dt = Math.max(1, b.ts - a.ts);
      const steps = clamp(Math.ceil(dt / 750), 1, 12);
      for (let s = 1; s < steps; s += 1) {
        const t = s / steps;
        const eased = smoothstep(t);
        out.push({
          ts: Math.round(a.ts + dt * t),
          value: a.value + (b.value - a.value) * eased,
          display: a.value + (b.value - a.value) * eased,
          source: "ui_interpolation_between_real_points",
          equity: a.equity + (b.equity - a.equity) * eased,
          anchor: false,
        });
      }
    }
    out.push({ ...raw[raw.length - 1], display: raw[raw.length - 1].value, anchor: true });
    return out.slice(-260);
  }

  function drawGrid(ctx, width, height) {
    ctx.fillStyle = "rgba(5,7,13,0.74)";
    ctx.fillRect(0, 0, width, height);
    ctx.strokeStyle = "rgba(0,217,255,0.12)";
    ctx.lineWidth = 1;
    for (let x = 44; x < width; x += 64) {
      ctx.beginPath(); ctx.moveTo(x, 12); ctx.lineTo(x, height - 28); ctx.stroke();
    }
    for (let y = 24; y < height - 28; y += 44) {
      ctx.beginPath(); ctx.moveTo(44, y); ctx.lineTo(width - 18, y); ctx.stroke();
    }
  }

  function drawLine(ctx, series, xFor, yFor) {
    ctx.beginPath();
    series.forEach((p, i) => {
      const x = xFor(i);
      const y = yFor(p.display);
      if (i === 0) ctx.moveTo(x, y);
      else {
        const prevX = xFor(i - 1);
        const prevY = yFor(series[i - 1].display);
        ctx.quadraticCurveTo((prevX + x) / 2, prevY, x, y);
      }
    });
  }

  function draw() {
    const canvas = q("#simulationMetaGraph");
    const badge = q("#simulationGraphState");
    const tooltip = q("#simulationGraphTooltip");
    if (!canvas || !badge || !tooltip) return;

    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(640, Math.floor(rect.width || canvas.width || 1180));
    const height = Math.max(220, Math.min(320, Math.floor(rect.height || 260)));
    const nextW = Math.floor(width * ratio);
    const nextH = Math.floor(height * ratio);
    if (canvas.width !== nextW) canvas.width = nextW;
    if (canvas.height !== nextH) canvas.height = nextH;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    drawGrid(ctx, width, height);

    const delta = state.targetPnl - state.displayPnl;
    const maxStep = Math.max(0.015, Math.abs(delta) * 0.085);
    state.displayPnl += clamp(delta, -maxStep, maxStep);
    if (Math.abs(delta) < 0.002) state.displayPnl = state.targetPnl;

    const base = buildSeries();
    const now = Date.now();
    const live = { value: state.displayPnl, display: state.displayPnl, ts: now, source: "ui_realtime_smooth", equity: state.lastEquity || 1000 + state.displayPnl, anchor: false };
    const series = base.length ? [...base.slice(-220), live] : [live];
    const values = series.map((p) => p.display);
    let minValue = Math.min(...values, 0);
    let maxValue = Math.max(...values, 0);
    const pad = Math.max(0.35, (maxValue - minValue) * 0.18);
    minValue -= pad;
    maxValue += pad;
    if (Math.abs(maxValue - minValue) < 0.5) { minValue -= 0.5; maxValue += 0.5; }

    const plotLeft = 54, plotRight = width - 24, plotTop = 18, plotBottom = height - 34;
    const plotHeight = plotBottom - plotTop;
    const yFor = (value) => plotBottom - ((value - minValue) / (maxValue - minValue)) * plotHeight;
    const xFor = (index) => plotLeft + (plotRight - plotLeft) * (index / Math.max(1, series.length - 1));

    ctx.strokeStyle = "rgba(232,250,255,0.28)";
    ctx.beginPath(); ctx.moveTo(plotLeft, yFor(0)); ctx.lineTo(plotRight, yFor(0)); ctx.stroke();

    const gradient = ctx.createLinearGradient(0, plotTop, 0, plotBottom);
    gradient.addColorStop(0, "rgba(0,255,136,0.18)");
    gradient.addColorStop(0.5, "rgba(0,217,255,0.07)");
    gradient.addColorStop(1, "rgba(255,59,95,0.10)");
    drawLine(ctx, series, xFor, yFor);
    ctx.lineTo(plotRight, plotBottom); ctx.lineTo(plotLeft, plotBottom); ctx.closePath();
    ctx.fillStyle = gradient; ctx.fill();

    ctx.globalAlpha = 0.25;
    ctx.fillStyle = "#e8faff";
    series.forEach((p, i) => {
      if (!p.anchor) return;
      ctx.beginPath(); ctx.arc(xFor(i), yFor(p.display), 2.1, 0, Math.PI * 2); ctx.fill();
    });
    ctx.globalAlpha = 1;

    const positive = state.displayPnl >= 0;
    ctx.strokeStyle = positive ? "#00ff88" : "#ff3b5f";
    ctx.shadowColor = positive ? "rgba(0,255,136,0.55)" : "rgba(255,59,95,0.55)";
    ctx.shadowBlur = 14;
    ctx.lineWidth = 2.5;
    drawLine(ctx, series, xFor, yFor);
    ctx.stroke();
    ctx.shadowBlur = 0;

    ctx.fillStyle = positive ? "#00ff88" : "#ff3b5f";
    ctx.beginPath(); ctx.arc(plotRight, yFor(state.displayPnl), 4.3, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = "rgba(232,250,255,0.65)"; ctx.stroke();

    ctx.fillStyle = "#8aa0b6";
    ctx.font = "12px Cascadia Code, Consolas, monospace";
    ctx.fillText(formatUsd(maxValue), 8, plotTop + 10);
    ctx.fillText(formatUsd(minValue), 8, plotBottom);
    const ageMs = Math.max(0, Date.now() - state.lastTickAt);
    badge.textContent = `Temps reel fluide ${formatUsd(state.displayPnl)}${ageMs > 7000 ? " · tick ancien" : ""}`;
    badge.className = `badge ${positive ? "green" : "red"}`;

    canvas.onmousemove = (event) => {
      const bounds = canvas.getBoundingClientRect();
      const mouseX = event.clientX - bounds.left;
      const idx = clamp(Math.round((mouseX - plotLeft) / Math.max(1, (plotRight - plotLeft) / Math.max(1, series.length - 1))), 0, series.length - 1);
      const p = series[idx];
      tooltip.classList.remove("hidden");
      tooltip.style.left = `${Math.min(width - 250, Math.max(8, mouseX + 14))}px`;
      tooltip.style.top = `${Math.max(8, event.clientY - bounds.top - 18)}px`;
      tooltip.innerHTML = `<strong>Metagraphe temps reel</strong><br>Gain/perte affiche: ${formatUsd(p.display)}<br>Source: ${p.source || "sample"}<br>${p.anchor ? "Point reel serveur" : "Interpolation visuelle entre points reels"}`;
    };
    canvas.onmouseleave = () => tooltip.classList.add("hidden");
  }

  function loop() {
    draw();
    state.raf = window.requestAnimationFrame(loop);
  }

  async function pollRealtimeTick() {
    if (document.hidden) return;
    try {
      const res = await fetch("/api/simulation/overview?limit=120", { cache: "no-store" });
      if (!res.ok) throw new Error(`tick ${res.status}`);
      const tick = sampleFromOverview(await res.json());
      addSample(tick.pnl, tick.timestamp, tick.source, tick.equity);
    } catch (_e) {
      // Never invent a value. Keep animating toward the last real target only.
    }
  }

  const originalDraw = window.drawSimulationMetaGraph;
  window.drawSimulationMetaGraph = function smoothDraw(candles, equity) {
    seedFromCandles(candles, equity);
    if (!state.raf) state.raf = window.requestAnimationFrame(loop);
    draw();
  };
  window.__hypersmartSmoothMetagraph = { state, addSample, pollRealtimeTick, originalDraw };
  window.setInterval(pollRealtimeTick, 2500);
  pollRealtimeTick();
})();
