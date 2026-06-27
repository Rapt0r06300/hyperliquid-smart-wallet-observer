/* HyperSmart Observer — charts_lwc.js (V12, repo 14)
 *
 * ADDITIVE / OPTIONAL progressive-enhancement layer for TradingView
 * lightweight-charts. It does NOT replace the existing canvas equity renderer —
 * it only activates when (a) the global `LightweightCharts` is present (CDN) and
 * (b) a target container element exists. Otherwise every function is a safe no-op.
 *
 * Hard rule (mirror of src/hl_observer/ui/charts/series.py): NO FAKE POINTS.
 * Empty input -> empty series. We never invent a baseline or a synthetic tick.
 * Read-only / display-only: this file places no orders and touches no money.
 *
 * To enable, add to simulation_v2.html (optional):
 *   <script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
 *   <div id="lwc-equity"></div><div id="lwc-drawdown"></div>
 *   <script src="/static/charts_lwc.js"></script>
 */
(function () {
  "use strict";

  var HAS_LWC = typeof window !== "undefined" && typeof window.LightweightCharts !== "undefined";

  // ---- series builders (mirror of the Python module) ----------------------
  function sortedUniqueByTime(points) {
    var byTime = {};
    (points || []).forEach(function (p) {
      if (p == null || p.time == null) return;
      byTime[String(parseInt(p.time, 10))] = p;
    });
    return Object.keys(byTime)
      .map(function (k) { return parseInt(k, 10); })
      .sort(function (a, b) { return a - b; })
      .map(function (t) { return byTime[String(t)]; });
  }

  function buildEquitySeries(points) {
    return sortedUniqueByTime(points)
      .filter(function (p) { return p.equity != null; })
      .map(function (p) { return { time: parseInt(p.time, 10), value: Number(p.equity) }; });
  }

  function buildDrawdownSeries(equityPoints) {
    var out = [], peak = null;
    sortedUniqueByTime(equityPoints).forEach(function (p) {
      if (p.equity == null) return;
      var eq = Number(p.equity);
      peak = peak == null ? eq : Math.max(peak, eq);
      var dd = peak <= 0 ? 0 : ((eq - peak) / peak) * 100;
      out.push({ time: parseInt(p.time, 10), value: dd });
    });
    return out;
  }

  function buildLineSeries(points, key) {
    return sortedUniqueByTime(points)
      .filter(function (p) { return p[key] != null; })
      .map(function (p) { return { time: parseInt(p.time, 10), value: Number(p[key]) }; });
  }

  function buildCandleSeries(ohlc) {
    return sortedUniqueByTime(ohlc)
      .filter(function (p) { return p.open != null && p.high != null && p.low != null && p.close != null; })
      .map(function (p) {
        return { time: parseInt(p.time, 10), open: Number(p.open), high: Number(p.high),
                 low: Number(p.low), close: Number(p.close) };
      });
  }

  function buildPositionMarkers(positions) {
    return (positions || [])
      .filter(function (p) { return p && p.time != null; })
      .map(function (p) {
        var isLong = String(p.side || "").toUpperCase() === "LONG";
        var isOpen = ["OPEN", "ADD"].indexOf(String(p.action || "").toUpperCase()) >= 0;
        return {
          time: parseInt(p.time, 10),
          position: isLong ? "belowBar" : "aboveBar",
          color: isOpen ? "#26a69a" : "#ef5350",
          shape: isLong ? "arrowUp" : "arrowDown",
          text: ((p.action || "") + " " + (p.coin || "")).trim(),
        };
      })
      .sort(function (a, b) { return a.time - b.time; });
  }

  function buildNoTradeMarkers(noTrades) {
    return (noTrades || [])
      .filter(function (n) { return n && n.time != null; })
      .map(function (n) {
        return { time: parseInt(n.time, 10), position: "inBar", color: "#b0b0b0",
                 shape: "circle", text: String(n.code || "NO_TRADE") };
      })
      .sort(function (a, b) { return a.time - b.time; });
  }

  function incrementalUpdate(series, newPoint) {
    if (!newPoint || newPoint.time == null) return series;
    var t = parseInt(newPoint.time, 10);
    var out = (series || []).filter(function (p) { return parseInt(p.time, 10) !== t; });
    var merged = {}; for (var k in newPoint) merged[k] = newPoint[k]; merged.time = t;
    out.push(merged);
    return out.sort(function (a, b) { return parseInt(a.time, 10) - parseInt(b.time, 10); });
  }

  // ---- chart wiring (no-op when LWC/containers absent) ---------------------
  var charts = {};

  function makeLineChart(elId, opts) {
    if (!HAS_LWC) return null;
    var el = document.getElementById(elId);
    if (!el) return null;
    var chart = window.LightweightCharts.createChart(el, {
      height: (opts && opts.height) || 220,
      layout: { background: { color: "transparent" }, textColor: "#c9d1d9" },
      grid: { vertLines: { color: "#1c2230" }, horzLines: { color: "#1c2230" } },
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    var series = chart.addLineSeries({ color: (opts && opts.color) || "#26a69a", lineWidth: 2 });
    charts[elId] = { chart: chart, series: series };
    return charts[elId];
  }

  function renderEquity(points) {
    var c = charts["lwc-equity"] || makeLineChart("lwc-equity", { color: "#26a69a" });
    if (!c) return;
    c.series.setData(buildEquitySeries(points)); // empty -> clears, never fakes
  }

  function renderDrawdown(equityPoints) {
    var c = charts["lwc-drawdown"] || makeLineChart("lwc-drawdown", { color: "#ef5350" });
    if (!c) return;
    c.series.setData(buildDrawdownSeries(equityPoints));
  }

  function pushEquity(point) {
    var c = charts["lwc-equity"];
    if (!c || !point || point.time == null || point.equity == null) return;
    c.series.update({ time: parseInt(point.time, 10), value: Number(point.equity) });
  }

  window.HSCharts = {
    enabled: HAS_LWC,
    buildEquitySeries: buildEquitySeries,
    buildDrawdownSeries: buildDrawdownSeries,
    buildLineSeries: buildLineSeries,
    buildCandleSeries: buildCandleSeries,
    buildPositionMarkers: buildPositionMarkers,
    buildNoTradeMarkers: buildNoTradeMarkers,
    incrementalUpdate: incrementalUpdate,
    renderEquity: renderEquity,
    renderDrawdown: renderDrawdown,
    pushEquity: pushEquity,
  };
})();
