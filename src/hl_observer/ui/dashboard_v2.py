"""Dashboard v2 — terminal de trading hacker, complet et lisible.

Router FastAPI SÉPARÉ monté à /v2. Ne touche jamais le gros routes.py. Read-only:
/api/simulation/status (ledger canonique) + /v2/equity_history (courbe réelle
persistante). « On voit tout » : PnL héros, courbe, flux d'activité live, scanner,
coûts nets, refus (no-trade), positions, câblage. Aucune donnée inventée : chaque
panneau lit un champ réel du status, sinon état vide honnête.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

CANONICAL_STATUS_FIELDS = (
    "net_pnl_usdt", "equity_usdt", "winrate_pct", "open_positions", "open_exposure_usdt",
    "closed_trades", "realized_pnl_usdt", "unrealized_pnl_usdt", "positions",
    "paper_ledger", "fusion_runtime", "scanner", "engine_running", "server_running",
    "read_only", "equity",
)

_PAGE = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HYPERSMART // OBSERVER</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root{
 --bg:#0d161b;--surface:rgba(255,255,255,.045);--surface2:rgba(255,255,255,.07);
 --green:#2ce69b;--green2:#39d99a;--red:#ff5c6a;--amber:#ffce5b;--cyan:#4fd8ff;
 --txt:#eef6f1;--mut:#93a89d;--mut2:#5c6f66;
 --line:rgba(255,255,255,.10);--line2:rgba(44,230,155,.30);
 --sans:'Space Grotesk',system-ui,sans-serif;--mono:'JetBrains Mono',ui-monospace,monospace;
}
*{box-sizing:border-box}html,body{margin:0}
body{background:
 radial-gradient(1250px 680px at 80% -20%,rgba(44,230,155,.11),transparent 60%),
 radial-gradient(900px 600px at 3% 118%,rgba(79,216,255,.06),transparent 58%),
 linear-gradient(180deg,#101c22,var(--bg) 40%);
 color:var(--txt);font-family:var(--sans);min-height:100vh;padding:22px 20px 34px;-webkit-font-smoothing:antialiased;overflow-x:hidden}
/* grille de fond + scanlines */
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
 background-image:linear-gradient(rgba(44,230,155,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(44,230,155,.04) 1px,transparent 1px);
 background-size:44px 44px;mask:radial-gradient(1200px 700px at 50% 8%,#000,transparent 78%)}
body::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:1;opacity:.28;
 background:repeating-linear-gradient(0deg,rgba(0,0,0,0) 0,rgba(0,0,0,0) 2px,rgba(0,0,0,.10) 3px);mix-blend-mode:multiply;animation:scan 8s linear infinite}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
.wrap{max-width:1180px;margin:auto;position:relative;z-index:2}
@keyframes blink{0%,46%{opacity:1}50%,96%{opacity:.12}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.28}}
@keyframes ring{0%{r:3.2;opacity:.7}100%{r:16;opacity:0}}
@keyframes fade{from{opacity:0;transform:translateX(-4px)}to{opacity:1;transform:none}}
@keyframes scan{to{transform:translateY(44px)}}
@keyframes sweep{0%{left:-30%}100%{left:130%}}
@keyframes flick{0%,100%{opacity:.5}50%{opacity:1}}
/* top bar */
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding-bottom:14px;border-bottom:1px solid var(--line)}
.logo{font-family:var(--sans);font-weight:700;font-size:16px;letter-spacing:4px;color:var(--txt)}
.logo b{color:var(--green)}.logo .s{color:var(--mut2)}
.logo .c{color:var(--green);animation:blink 1.15s steps(1) infinite}
.logo .sub{display:block;font-family:var(--mono);font-size:9.5px;letter-spacing:2.5px;color:var(--mut);margin-top:4px;font-weight:400}
.leds{font-family:var(--mono);font-size:11px;color:var(--mut);display:flex;gap:16px;align-items:center}
.led{display:inline-flex;align-items:center;gap:6px}
.led .d{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 9px var(--green);animation:pulse 2.4s infinite}
.led.off .d{background:var(--red);box-shadow:0 0 9px var(--red)}
.led.warn .d{background:var(--amber);box-shadow:0 0 9px var(--amber)}
.clk{color:var(--mut2)}
/* hero */
.hero{position:relative;margin-bottom:18px}
.hero-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px}
.pnl-big{font-family:var(--mono);font-weight:700;font-size:68px;line-height:.98;letter-spacing:-1.5px;transition:color .5s}
.pnl-pos{color:var(--green);text-shadow:0 0 26px rgba(44,230,155,.4)}
.pnl-neg{color:var(--red);text-shadow:0 0 26px rgba(255,92,106,.34)}
.pnl-sub{font-family:var(--mono);font-size:12.5px;color:var(--mut);margin-top:8px;letter-spacing:.3px}
.hero-hl{text-align:right;font-family:var(--mono);font-size:10.5px;color:var(--mut2);letter-spacing:1px;line-height:1.7}
.hero-hl b{color:var(--green2)}
.chart{position:relative;height:210px;margin-top:6px;border:1px solid var(--line);border-radius:12px;background:linear-gradient(180deg,rgba(44,230,155,.02),transparent);overflow:hidden}
.chart svg{width:100%;height:100%;display:block}
.axis{position:absolute;left:12px;right:12px;bottom:6px;display:flex;justify-content:space-between;font-family:var(--mono);font-size:9.5px;color:var(--mut2)}
/* strip KPI */
.strip{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:16px 0}
.st{border:1px solid var(--line);border-radius:11px;padding:12px 14px;background:var(--surface);position:relative;overflow:hidden}
.st::after{content:"";position:absolute;top:0;left:-30%;width:26%;height:100%;background:linear-gradient(90deg,transparent,rgba(44,230,155,.06),transparent);animation:sweep 7s linear infinite}
.st .k{font-family:var(--mono);font-size:9.5px;letter-spacing:1.5px;color:var(--mut);text-transform:uppercase}
.st .v{font-family:var(--mono);font-size:22px;font-weight:700;margin-top:6px;color:var(--txt)}
/* grilles */
.g2{display:grid;grid-template-columns:1.15fr .85fr;gap:12px;margin-bottom:12px}
.g3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px}
.card{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:var(--surface);position:relative}
.card h3{margin:0 0 12px;font-family:var(--mono);font-size:10.5px;font-weight:600;letter-spacing:2px;color:var(--green2);text-transform:uppercase;display:flex;justify-content:space-between;align-items:center}
.card h3 .hint{color:var(--mut2);letter-spacing:0;font-weight:400}
/* flux d'activité */
.feed{height:296px;overflow:hidden;font-family:var(--mono);font-size:11px;line-height:1.75;display:flex;flex-direction:column-reverse}
.feed .ev{animation:fade .25s ease;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.feed .t{color:var(--mut2)}
.feed .tag{display:inline-block;min-width:64px;color:var(--mut)}
.ev-open .tag{color:var(--green)}.ev-close .tag{color:var(--cyan)}.ev-no .tag{color:var(--amber)}
.ev-scan .tag{color:var(--mut)}.ev-warn .tag{color:var(--red)}.ev-sys .tag{color:var(--mut2)}
.cur{color:var(--green);animation:blink 1.1s steps(1) infinite}
/* tables */
table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:11.5px}
th{text-align:left;font-weight:500;color:var(--mut);font-size:9.5px;letter-spacing:1px;text-transform:uppercase;padding:0 0 8px;border-bottom:1px solid var(--line)}
td{padding:7px 0;border-bottom:1px solid rgba(255,255,255,.03);color:var(--txt)}
tr:last-child td{border-bottom:0}
.tag2{font-family:var(--mono);font-size:9px;font-weight:700;padding:2px 6px;border-radius:5px;letter-spacing:.5px}
.tg-s{color:var(--amber);background:rgba(255,206,91,.1)}.tg-g{color:var(--green);background:rgba(44,230,155,.1)}
/* kv + barres */
.kv{display:flex;justify-content:space-between;font-family:var(--mono);font-size:11px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.03);color:var(--mut)}
.kv:last-child{border-bottom:0}.kv b{color:var(--txt);font-weight:500}
.bar{height:6px;border-radius:4px;background:rgba(255,255,255,.05);overflow:hidden;margin-top:4px}
.bar>i{display:block;height:100%;border-radius:4px}
.scanline{position:absolute;top:14px;right:16px;font-family:var(--mono);font-size:9px;letter-spacing:1px;color:var(--green);animation:flick 1.4s infinite}
/* wiring */
.rail{display:flex;gap:8px;flex-wrap:wrap;align-items:center;font-family:var(--mono);font-size:10.5px;color:var(--mut);border:1px solid var(--line);border-radius:11px;padding:11px 14px;background:var(--surface)}
.rail .n{display:inline-flex;align-items:center;gap:6px;padding:2px 9px;border-radius:20px;background:rgba(255,255,255,.03)}
.rail .n .d{width:6px;height:6px;border-radius:50%}
.foot{text-align:center;font-family:var(--mono);font-size:9.5px;color:var(--mut2);margin-top:16px;letter-spacing:1px}
@media(max-width:820px){.strip{grid-template-columns:repeat(2,1fr)}.g2,.g3{grid-template-columns:1fr}.pnl-big{font-size:52px}}

/* ═══════════ FINITION HACKER PRO (surcouche, mêmes classes) ═══════════ */
#matrix{position:fixed;inset:0;z-index:0;opacity:.045;pointer-events:none}
@keyframes reveal{from{opacity:0;transform:translateY(15px)}to{opacity:1;transform:none}}
.wrap>*{animation:reveal .6s cubic-bezier(.2,.7,.2,1) both}
.wrap>*:nth-child(2){animation-delay:.05s}.wrap>*:nth-child(3){animation-delay:.1s}
.wrap>*:nth-child(4){animation-delay:.15s}.wrap>*:nth-child(5){animation-delay:.2s}
.wrap>*:nth-child(6){animation-delay:.25s}.wrap>*:nth-child(7){animation-delay:.3s}
.wrap>*:nth-child(n+8){animation-delay:.35s}
/* cartes: coins de terminal + hover lumineux + léger lift */
.card{transition:border-color .35s ease,box-shadow .35s ease,transform .25s cubic-bezier(.2,.7,.2,1)}
.card::before,.card::after{content:"";position:absolute;width:13px;height:13px;pointer-events:none;opacity:.4;transition:opacity .35s,width .35s,height .35s}
.card::before{top:-1px;left:-1px;border-top:1.5px solid var(--green);border-left:1.5px solid var(--green);border-top-left-radius:12px}
.card::after{bottom:-1px;right:-1px;border-bottom:1.5px solid var(--green);border-right:1.5px solid var(--green);border-bottom-right-radius:12px}
.card:hover{border-color:var(--line2);box-shadow:0 0 0 1px rgba(44,230,155,.16),0 16px 44px -20px rgba(44,230,155,.4);transform:translateY(-3px)}
.card:hover::before,.card:hover::after{opacity:1;width:19px;height:19px}
/* KPI: hover + valeur verte lumineuse */
.st{transition:border-color .3s,box-shadow .3s,transform .25s cubic-bezier(.2,.7,.2,1)}
.st:hover{border-color:var(--line2);box-shadow:0 12px 34px -18px rgba(44,230,155,.45);transform:translateY(-3px)}
.st .v{color:var(--green2);text-shadow:0 0 18px rgba(44,230,155,.28)}
/* lignes de table: hover vert avec barre latérale */
tbody tr{transition:background .2s,box-shadow .2s}
tbody tr:hover{background:rgba(44,230,155,.06);box-shadow:inset 2px 0 0 var(--green)}
/* flash quand une valeur change (feeling live) */
@keyframes flashv{0%{color:var(--green);text-shadow:0 0 18px var(--green)}100%{}}
.flash{animation:flashv .75s ease}
/* le graphe respire */
@keyframes breathe{0%,100%{box-shadow:inset 0 0 0 1px var(--line)}50%{box-shadow:inset 0 0 36px -12px rgba(44,230,155,.3),inset 0 0 0 1px rgba(44,230,155,.24)}}
.chart{animation:breathe 4.5s ease-in-out infinite}
/* accent scan sous le logo */
.logo{position:relative}
.logo::after{content:"";position:absolute;left:0;bottom:-7px;height:1px;width:100%;background:linear-gradient(90deg,var(--green),transparent);opacity:.45}
/* LED plus nettes, hero plus riche */
.led .d{box-shadow:0 0 11px var(--green),0 0 4px var(--green)}
.pnl-pos{text-shadow:0 0 32px rgba(44,230,155,.48),0 0 9px rgba(44,230,155,.32)}
/* titres verts un peu plus vifs + scrollbars discrètes */
.card h3{color:var(--green)}
::-webkit-scrollbar{width:6px;height:6px}::-webkit-scrollbar-thumb{background:rgba(44,230,155,.22);border-radius:3px}
::-webkit-scrollbar-track{background:transparent}

/* ═══ CRÉATIF v2 ═══ */
#spot{position:fixed;inset:0;z-index:1;pointer-events:none;background:radial-gradient(380px circle at var(--mx,50%) var(--my,-300px),rgba(44,230,155,.075),transparent 66%)}
.hero{position:relative;z-index:1}
.hero::before{content:"";position:absolute;top:-80px;left:-90px;width:300px;height:300px;border-radius:50%;background:conic-gradient(from 0deg,transparent,rgba(44,230,155,.17),transparent 44%);filter:blur(30px);animation:spin 11s linear infinite;z-index:-1;pointer-events:none}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes glitch{0%,90%,100%{transform:none;text-shadow:none}91%{transform:translate(1px,-1px);text-shadow:-1px 0 var(--cyan),1px 0 var(--red)}93%{transform:translate(-1px,1px)}95%{transform:none}}
.logo b{animation:glitch 7s infinite}
.ticker{overflow:hidden;border:1px solid var(--line);border-radius:9px;background:var(--surface);margin-bottom:14px;padding:7px 0;position:relative;white-space:nowrap}
.ticker::before,.ticker::after{content:"";position:absolute;top:0;width:64px;height:100%;z-index:2;pointer-events:none}
.ticker::before{left:0;background:linear-gradient(90deg,var(--bg),transparent)}
.ticker::after{right:0;background:linear-gradient(270deg,var(--bg),transparent)}
.ticker-in{display:inline-block;animation:marq 30s linear infinite;font-family:var(--mono);font-size:11px;color:var(--mut);letter-spacing:.4px;will-change:transform}
.ticker-in b{color:var(--green)}.ticker-in .s{color:var(--mut2);margin:0 13px}
.ticker:hover .ticker-in{animation-play-state:paused}
@keyframes marq{from{transform:translateX(0)}to{transform:translateX(-50%)}}
#mg-live{filter:drop-shadow(0 0 11px #2ce69b) drop-shadow(0 0 3px #eafff5)}
</style></head>
<body><canvas id="matrix"></canvas><div id="spot"></div><div class="wrap">
 <div class="top">
   <div class="logo"><b>HYPER</b>SMART<span class="s">//</span>OBSERVER<span class="c">_</span>
     <span class="sub" id="boot">BOOT · HYPERLIQUID READ-ONLY · PAPER SIMULATION</span></div>
   <div class="leds">
     <span class="led" id="l-safe"><span class="d"></span>SAFE·<span id="ro">read_only</span></span>
     <span class="led" id="l-eng"><span class="d"></span>ENGINE</span>
     <span class="led" id="l-ws"><span class="d"></span>WS</span>
     <span class="led" id="l-fund"><span class="d"></span>FUNDING</span>
     <span class="clk" id="clk">--:--:--</span>
   </div>
 </div>

 <div class="ticker"><div class="ticker-in" id="tick"></div></div>
 <div class="hero">
   <div class="hero-head">
     <div>
       <div class="pnl-big pnl-pos" id="pnl">+0.00</div>
       <div class="pnl-sub">PnL net <span id="pnl-unit">USDC</span> · equity <span id="eq" class="num">…</span> · <span id="chg" class="num">+0.00%</span> · <span id="mode">live</span></div>
     </div>
     <div class="hero-hl">EQUITY // <span id="mg-span">…</span><br><b id="mg-hi"></b><br><span id="mg-lo"></span></div>
   </div>
   <div class="chart">
   <svg viewBox="0 0 1000 210" preserveAspectRatio="none">
     <defs>
       <linearGradient id="mgfill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2ce69b" stop-opacity="0.22"/><stop offset="1" stop-color="#2ce69b" stop-opacity="0"/></linearGradient>
       <filter id="glow" x="-15%" y="-40%" width="130%" height="180%"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
     </defs>
     <line id="mg-base" x1="0" x2="1000" stroke="#2ce69b" stroke-width="1" stroke-dasharray="2 7" opacity="0.3"/>
     <path id="mg-area" fill="url(#mgfill)" d=""/>
     <path id="mg-line" fill="none" stroke="#2ce69b" stroke-width="2.1" stroke-linejoin="round" stroke-linecap="round" filter="url(#glow)" d=""/>
     <circle id="mg-ring" r="3.2" fill="none" stroke="#2ce69b" stroke-width="1.4" style="animation:ring 2s ease-out infinite"/>
     <circle id="mg-live" r="3.3" fill="#2ce69b" style="filter:drop-shadow(0 0 7px #2ce69b)"/>
   </svg>
   <div class="axis"><span id="mg-t0"></span><span style="color:var(--mut2)">╌ base = equity départ</span><span id="mg-t1"></span></div>
   </div>
 </div>

 <div class="strip">
   <div class="st"><div class="k">Winrate</div><div class="v" id="wr">…</div></div>
   <div class="st"><div class="k">Positions</div><div class="v" id="pos">…</div></div>
   <div class="st"><div class="k">Trades clos</div><div class="v" id="trd">…</div></div>
   <div class="st"><div class="k">Exposition</div><div class="v" id="expo">…</div></div>
   <div class="st"><div class="k">Profit factor</div><div class="v" id="pf">…</div></div>
 </div>

 <div class="card" style="margin-bottom:12px"><h3>TOP OPPORTUNITÉS <span class="hint" id="oppsum">— toutes stratégies · edge net après coûts —</span></h3>
   <table><thead><tr><th style="width:7%">#</th><th style="width:23%">coin</th><th style="width:28%">stratégie</th><th style="width:20%">edge net</th><th style="width:22%;text-align:right">power</th></tr></thead><tbody id="opptb"></tbody></table></div>

 <div class="g2">
   <div class="card"><h3>FLUX D'ACTIVITÉ <span class="hint" id="feedhint">live · dérivé du ledger</span></h3>
     <div class="feed" id="feed"></div></div>
   <div class="card"><h3>POSITIONS <span class="hint" id="poslbl"></span></h3>
     <table><thead><tr><th style="width:26%">coin</th><th style="width:26%">mode</th><th style="width:22%">notl</th><th style="width:26%;text-align:right">pnl</th></tr></thead><tbody id="postb"></tbody></table></div>
 </div>

 <div class="g3">
   <div class="card"><div class="scanline" id="scanpulse">▮ SCAN</div><h3>SCANNER</h3>
     <div class="kv"><span>leaders retenus</span><b id="sc-sel">…</b></div>
     <div class="kv"><span>leaders frais</span><b id="sc-fresh">…</b></div>
     <div class="kv"><span>par poll</span><b id="sc-poll">…</b></div>
     <div class="kv"><span>trades publics</span><b id="sc-trades">…</b></div>
     <div class="kv"><span>deltas d'entrée frais</span><b id="sc-deltas">…</b></div>
   </div>
   <div class="card"><h3>COÛTS NETS <span class="hint">cumul</span></h3>
     <div class="kv"><span>frais</span><b id="c-fees" style="color:var(--red)">…</b></div>
     <div class="bar"><i id="c-fees-b" style="background:var(--red);width:0"></i></div>
     <div class="kv" style="margin-top:8px"><span>funding</span><b id="c-fund">…</b></div>
     <div class="bar"><i id="c-fund-b" style="background:var(--cyan);width:0"></i></div>
     <div class="kv" style="margin-top:8px"><span>realized / unreal.</span><b id="ru">…</b></div>
   </div>
   <div class="card"><h3>REFUS · NO-TRADE <span class="hint">discipline</span></h3>
     <div id="refus" style="font-family:var(--mono);font-size:11px;line-height:1.9;color:var(--mut)">…</div>
   </div>
 </div>

 <div class="card" style="margin-bottom:12px"><h3>ÉTAT MOTEUR</h3>
   <div class="g3" style="margin:0">
     <div class="kv"><span>moteur</span><b id="engine">…</b></div>
     <div class="kv"><span>funding · paires</span><b id="m_funding">…</b></div>
     <div class="kv"><span>modes</span><b id="modes">…</b></div>
     <div class="kv"><span>réconciliation</span><b id="recon">…</b></div>
     <div class="kv"><span>marks marché</span><b id="fresh">…</b></div>
     <div class="kv"><span>equity départ</span><b id="startbal">…</b></div>
   </div>
 </div>

 <div class="rail" id="wiring"></div>
 <div class="foot" id="footnote">HYPERSMART OBSERVER · 0 ORDRE RÉEL · 0 CLÉ · 0 SIGNATURE · PAPER-ONLY</div>
</div>
<script>
function n(x,d){x=Number(x);return isNaN(x)?'—':x.toFixed(d==null?2:d)}
function col(v){return v>=0?'var(--green)':'var(--red)'}
function hhmm(ms){var d=new Date(ms);return ('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2)}
function hms(){var d=new Date();return ('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2)+':'+('0'+d.getSeconds()).slice(-2)}
var FEED=[],PREV=null,BOOTED=false;
function push(cls,tag,msg){FEED.push({t:hms(),cls:cls,tag:tag,msg:msg});if(FEED.length>60)FEED.shift();renderFeed();}
function renderFeed(){var f=document.getElementById('feed');f.innerHTML=FEED.slice().reverse().map(function(e){
  return '<div class="ev '+e.cls+'"><span class="t">'+e.t+'</span> <span class="tag">'+e.tag+'</span> '+e.msg+'</div>';}).join('')
  +'<div class="ev"><span class="t">'+hms()+'</span> <span class="cur">▮</span></div>';}
function smoothPath(pts){if(pts.length<2)return pts.length?('M'+pts[0][0]+' '+pts[0][1]):'';
  var d='M'+pts[0][0].toFixed(1)+' '+pts[0][1].toFixed(1);
  for(var i=0;i<pts.length-1;i++){var p0=pts[i>0?i-1:0],p1=pts[i],p2=pts[i+1],p3=pts[i+2<pts.length?i+2:i+1];
    d+=' C'+(p1[0]+(p2[0]-p0[0])/6).toFixed(1)+' '+(p1[1]+(p2[1]-p0[1])/6).toFixed(1)+','+(p2[0]-(p3[0]-p1[0])/6).toFixed(1)+' '+(p2[1]-(p3[1]-p1[1])/6).toFixed(1)+','+p2[0].toFixed(1)+' '+p2[1].toFixed(1);}
  return d;}
function drawMeta(pts){var W=1000,H=210,PAD=14;if(!pts.length)return;
  var eqs=pts.map(function(p){return p.equity}),base=pts[0].equity;
  var lo=Math.min.apply(null,eqs.concat([base])),hi=Math.max.apply(null,eqs.concat([base]));
  var rng=(hi-lo)||1,pd=rng*0.16;lo-=pd;hi+=pd;rng=hi-lo;
  var t0=pts[0].t,t1=pts[pts.length-1].t,ts=(t1-t0)||1;
  function X(t){return PAD+(W-2*PAD)*(t-t0)/ts}function Y(e){return PAD+(H-2*PAD)*(1-(e-lo)/rng)}
  var xy=pts.map(function(p){return [X(p.t),Y(p.equity)]}),line=smoothPath(xy),last=pts[pts.length-1];
  var c=last.equity>=base?'#2ce69b':'#ff5c6a';
  var L=document.getElementById('mg-line');L.setAttribute('d',line);L.setAttribute('stroke',c);
  document.getElementById('mg-area').setAttribute('d',line+' L'+xy[xy.length-1][0].toFixed(1)+' '+(H-PAD)+' L'+xy[0][0].toFixed(1)+' '+(H-PAD)+' Z');
  var by=Y(base),bl=document.getElementById('mg-base');bl.setAttribute('y1',by);bl.setAttribute('y2',by);bl.setAttribute('stroke',c);
  var lx=xy[xy.length-1][0],ly=xy[xy.length-1][1];
  ['mg-live','mg-ring'].forEach(function(id){var e=document.getElementById(id);e.setAttribute('cx',lx);e.setAttribute('cy',ly);e.setAttribute(id==='mg-live'?'fill':'stroke',c);});
  document.getElementById('mg-hi').textContent='↑ '+n(hi-pd);document.getElementById('mg-lo').textContent='↓ '+n(lo+pd);
  document.getElementById('mg-t0').textContent=hhmm(t0);document.getElementById('mg-t1').textContent=hhmm(t1)+' · '+pts.length+'pts';
  var sp=(t1-t0)/3600000;document.getElementById('mg-span').textContent=sp>=1?(sp.toFixed(1)+'h'):(Math.round((t1-t0)/60000)+'min');
  window._base=base;}
function loadMeta(){fetch('/v2/equity_history?max=600').then(function(r){return r.json()}).then(function(d){
  var pts=(d.points||[]).map(function(p){return {t:Number(p.t),equity:Number(p.equity),pnl:Number(p.pnl)}}).filter(function(p){return p.equity>0});
  if(pts.length)drawMeta(pts);}).catch(function(){});}
function modeOf(p){var m=(p.position_mode||'').toUpperCase();
  return (m.indexOf('FUNDING')>=0||m.indexOf('ARBITRAGE')>=0||m.indexOf('TRIANGULAR')>=0||m.indexOf('DELTA')>=0||m.indexOf('EXTERNAL_GITHUB')>=0)?'GRINDER':'SNIPER';}
function led(id,st){var e=document.getElementById(id);e.className='led'+(st==='ok'?'':st==='warn'?' warn':' off');}
function tick(){
  fetch('/api/simulation/status').then(function(r){return r.json()}).then(function(d){
    if(!BOOTED){BOOTED=true;document.getElementById('boot').textContent='SESSION ATTACHÉE · '+(d.read_only?'READ-ONLY':'?')+' · PAPER SIMULATION';push('ev-sys','SYS','session attachée · lecture seule · ledger canonique');}
    document.getElementById('ro').textContent=d.read_only?'read_only':'??';led('l-safe',d.read_only?'ok':'off');
    var pnl=Number(d.net_pnl_usdt||0),eq=Number(d.equity_usdt||0);
    var P=document.getElementById('pnl');P.textContent=(pnl>=0?'+':'')+n(pnl);P.className='pnl-big '+(pnl>=0?'pnl-pos':'pnl-neg');
    document.getElementById('eq').textContent=n(eq);
    var base=window._base||(eq-pnl)||1000;var chg=base>0?(pnl/base*100):0;
    var C=document.getElementById('chg');C.textContent=(chg>=0?'+':'')+n(chg,2)+'%';C.style.color=col(chg);
    document.getElementById('wr').textContent=n(d.winrate_pct,0)+'%';
    document.getElementById('pos').textContent=(d.open_positions||0);
    document.getElementById('trd').textContent=(d.closed_trades||0);
    document.getElementById('expo').textContent=n(d.open_exposure_usdt);
    var rp=Number(d.realized_pnl_usdt||0),ps=(d.positions||[]);
    // profit factor approx = gains/pertes réalisés si dispo, sinon —
    var pf=d.paper_ledger&&d.paper_ledger.profit_factor;document.getElementById('pf').textContent=(pf!=null?n(pf,2):(rp>=0?'≥1':'<1'));
    // marks
    var eqo=d.equity||{},av=Number(eqo.market_marks_available||0),mi=Number(eqo.market_marks_missing||0),fr=document.getElementById('fresh');
    if(mi>0&&av===0){fr.textContent='⚠ '+mi+' manquants';fr.style.color='var(--red)';}else if(mi>0){fr.textContent=av+'/'+(av+mi);fr.style.color='var(--amber)';}else{fr.textContent='✓ '+av;fr.style.color='var(--green)';}
    document.getElementById('startbal').textContent=n(eqo.starting_balance_usdc||base);
    // modes
    var sniper=0,grinder=0;ps.forEach(function(p){if(modeOf(p)==='SNIPER')sniper++;else grinder++;});
    document.getElementById('modes').innerHTML='<span style="color:var(--amber)">'+sniper+' sniper</span> · <span style="color:var(--green)">'+grinder+' grinder</span>';
    var fus=d.fusion_runtime||{},fa=fus.funding_arb||{};
    document.getElementById('m_funding').textContent=(fa.open_pairs!=null?fa.open_pairs:0)+(fa.enabled?'':' · off');led('l-fund',fa.enabled?'ok':'warn');
    document.getElementById('engine').innerHTML=d.engine_running?'<span style="color:var(--green)">● actif</span>':'<span style="color:var(--red)">○ arrêté</span>';
    led('l-eng',d.engine_running?'ok':'off');
    var pl=d.paper_ledger||{},rec=pl.reconciliation||{},gap=Math.abs(Number(rec.expected_equity_usdc||0)-Number(rec.actual_equity_usdc||0));
    document.getElementById('recon').innerHTML='<span style="color:'+(gap<0.01?'var(--green)':'var(--red)')+'">écart '+n(gap,6)+'</span>';
    document.getElementById('ru').innerHTML='<span style="color:'+col(rp)+'">'+n(rp)+'</span> / <span style="color:'+col(Number(d.unrealized_pnl_usdt||0))+'">'+n(d.unrealized_pnl_usdt)+'</span>';
    // scanner
    var sc=d.scanner||{};
    document.getElementById('sc-sel').textContent=(sc.leaders_selected!=null?sc.leaders_selected:'—');
    document.getElementById('sc-fresh').textContent=(sc.fresh_leaders_selected!=null?sc.fresh_leaders_selected:'—');
    document.getElementById('sc-poll').textContent=(sc.leaders_per_poll!=null?sc.leaders_per_poll:'—');
    document.getElementById('sc-trades').textContent=(sc.fresh_public_trade_events!=null?sc.fresh_public_trade_events:(sc.public_trade_events!=null?sc.public_trade_events:'—'));
    document.getElementById('sc-deltas').textContent=(sc.fresh_entry_deltas!=null?sc.fresh_entry_deltas:'—');
    document.getElementById('l-ws').className='led'+(sc.engine_running||d.engine_running?'':' off');
    // TOP OPPORTUNITÉS (tableau unifié cross-stratégie, edge net)
    var ob=(fus.opportunity_board)||{},obe=(ob.entries)||[],otb=document.getElementById('opptb');otb.innerHTML='';
    var SC={COPY:'var(--amber)',DISTILLED:'var(--green)',FUNDING_ARB:'var(--cyan)',ARBITRAGE:'#c9a6ff'};
    obe.slice(0,8).forEach(function(e,i){var tr=document.createElement('tr');
      tr.innerHTML='<td style="color:var(--mut2)">'+(i+1)+'</td><td>'+e.coin+' <span style="color:var(--mut2)">'+(e.side||'')+'</span></td><td><span style="color:'+(SC[e.strategy]||'var(--mut)')+'">'+e.strategy+'</span></td><td class="num">'+n(e.net_edge_bps,1)+' bps</td><td style="text-align:right;color:var(--green)">'+n(e.power_score,1)+'</td>';otb.appendChild(tr);});
    if(!obe.length)otb.innerHTML='<tr><td colspan="5" style="color:var(--mut2);border:0;padding-top:10px">— aucune opportunité au-dessus des planchers ce tick —</td></tr>';
    var os=ob.summary||{};document.getElementById('oppsum').textContent=os.total?(os.total+' retenues · meilleur edge '+n(os.best_net_edge_bps,1)+' bps'):'— toutes stratégies · edge net —';
    // coûts (somme positions + closed si dispo)
    var fees=0,fund=0;ps.forEach(function(p){fees+=Number(p.fee_cost_usdc||0);fund+=Number(p.funding_cost_usdc||0);});
    if(pl.total_fees_usdc!=null)fees=Number(pl.total_fees_usdc);if(pl.total_funding_usdc!=null)fund=Number(pl.total_funding_usdc);
    document.getElementById('c-fees').textContent='-'+n(Math.abs(fees),4);
    document.getElementById('c-fund').textContent=(fund>=0?'+':'')+n(fund,4);document.getElementById('c-fund').style.color=col(fund);
    var mx=Math.max(Math.abs(fees),Math.abs(fund),0.0001);
    document.getElementById('c-fees-b').style.width=(Math.abs(fees)/mx*100)+'%';
    document.getElementById('c-fund-b').style.width=(Math.abs(fund)/mx*100)+'%';
    // refus / no-trade
    var nt=d.no_trade_reasons||pl.no_trade_reasons||(fus.no_trade_reasons)||null,R=document.getElementById('refus');
    if(nt&&typeof nt==='object'&&Object.keys(nt).length){R.innerHTML=Object.keys(nt).slice(0,6).map(function(k){
      return '<div><span style="color:var(--amber)">✕</span> '+k.toLowerCase()+' <span style="color:var(--mut2)">×'+nt[k]+'</span></div>';}).join('');}
    else{R.innerHTML='<span style="color:var(--mut2)">— aucun refus enregistré ce tick —</span>';}
    // positions table
    var tb=document.getElementById('postb');tb.innerHTML='';document.getElementById('poslbl').textContent=ps.length+' ouvertes';
    ps.slice(0,8).forEach(function(p){var g=modeOf(p),pp=Number(p.unrealized_pnl_usdc||p.pnl_usdc||0),notl=Number(p.notional_usdt||p.copied_notional_usdt||0),tr=document.createElement('tr');
      tr.innerHTML='<td>'+(p.coin||'?')+'</td><td><span class="tag2 '+(g==='SNIPER'?'tg-s':'tg-g')+'">'+g+'</span></td><td>'+n(notl)+'</td><td style="text-align:right;color:'+col(pp)+'">'+(pp>=0?'+':'')+n(pp)+'</td>';tb.appendChild(tr);});
    if(!ps.length)tb.innerHTML='<tr><td colspan="4" style="color:var(--mut2);border:0;padding-top:10px">— aucune position ouverte —</td></tr>';
    // wiring
    var pe=(fus.paper_engine)||{},summ=fus.external_profile_execution_summary||{};
    function nd(ok,l,v){return '<span class="n"><span class="d" style="background:'+(ok?'var(--green)':'var(--red)')+';box-shadow:0 0 7px '+(ok?'var(--green)':'var(--red)')+'"></span>'+l+' <span style="color:var(--mut2)">'+v+'</span></span>';}
    document.getElementById('wiring').innerHTML='<span style="color:var(--mut2);letter-spacing:1px">WIRING</span>'+nd(d.engine_running,'ws',(sc.engine_running?'live':'off'))+nd((fus.status||'').indexOf('OK')>=0,'fusion',(summ.profiles_executed!=null?summ.profiles_executed:'—'))+nd(true,'paper_engine',(pe.accepted_count!=null?pe.accepted_count:'—'))+nd(gap<0.01,'ledger',(pl.open_positions_count!=null?pl.open_positions_count+'pos':'—'));
    // dérive les événements du flux depuis les deltas réels
    deriveEvents(d,ps,sniper+grinder);
    document.getElementById('clk').textContent=hms();
  }).catch(function(){document.getElementById('engine').innerHTML='<span style="color:var(--red)">✕ injoignable</span>';led('l-eng','off');});
}
function deriveEvents(d,ps,npos){
  var cur={op:Number(d.open_positions||0),ct:Number(d.closed_trades||0),pnl:Number(d.net_pnl_usdt||0),
    sel:(d.scanner||{}).leaders_selected,coins:ps.map(function(p){return p.coin}).join(',')};
  if(PREV){
    if(cur.op>PREV.op){var nw=ps.filter(function(p){return PREV.coins.indexOf(p.coin)<0});nw.slice(0,3).forEach(function(p){
      push('ev-open','OPEN',(p.coin||'?')+' '+modeOf(p)+' · notl '+n(Number(p.notional_usdt||p.copied_notional_usdt||0)));});}
    if(cur.ct>PREV.ct){push('ev-close','CLOSE',(cur.ct-PREV.ct)+' trade(s) clos · PnL net '+(cur.pnl>=0?'+':'')+n(cur.pnl));}
    if((cur.pnl>=0)!==(PREV.pnl>=0)){push('ev-warn','PNL',(cur.pnl>=0?'repasse POSITIF ':'bascule NÉGATIF ')+n(cur.pnl));}
    if(cur.sel!=null&&cur.sel!==PREV.sel){push('ev-scan','SCAN',cur.sel+' leaders retenus · '+npos+' pos actives');}
  }
  PREV=cur;
}
renderFeed();tick();setInterval(tick,2000);loadMeta();setInterval(loadMeta,10000);
setInterval(function(){var s=document.getElementById('scanpulse');s.style.opacity=s.style.opacity==='0.3'?'1':'0.3';},900);

// ── Matrix rain (subtil, atmosphérique) ──
(function(){var c=document.getElementById('matrix');if(!c)return;var x=c.getContext('2d');
function R(){c.width=window.innerWidth;c.height=window.innerHeight;}R();window.addEventListener('resize',R);
var G='01≡⌐¬△▽◇+×·HYPRSMT${}[]<>/#'.split(''),fs=15,cols=Math.ceil(c.width/fs),y=[];
for(var i=0;i<cols;i++)y[i]=Math.floor(Math.random()*-50);
setInterval(function(){x.fillStyle='rgba(13,22,27,.11)';x.fillRect(0,0,c.width,c.height);x.font=fs+'px JetBrains Mono, monospace';
for(var i=0;i<cols;i++){var g=G[Math.floor(Math.random()*G.length)],yy=y[i]*fs;
x.fillStyle=Math.random()>.945?'rgba(150,255,210,.9)':'rgba(44,230,155,.5)';x.fillText(g,i*fs,yy);
if(yy>c.height&&Math.random()>.975)y[i]=0;y[i]++;}},68);})();
// ── Flash-on-change sur les valeurs clés (effet live) ──
function _flash(el){if(!el)return;el.classList.remove('flash');void el.offsetWidth;el.classList.add('flash');}
try{document.querySelectorAll('#pnl,#eq,.st .v').forEach(function(el){
  new MutationObserver(function(){_flash(el);}).observe(el,{childList:true,characterData:true,subtree:true});});}catch(e){}

// ── Projecteur qui suit la souris ──
(function(){var sp=document.getElementById('spot');if(!sp)return;window.addEventListener('mousemove',function(e){sp.style.setProperty('--mx',e.clientX+'px');sp.style.setProperty('--my',e.clientY+'px');},{passive:true});})();
// ── Machine à écrire au démarrage ──
(function(){var el=document.getElementById('boot');if(!el)return;var full=el.textContent||'';el.textContent='';var i=0;var t=setInterval(function(){el.textContent=full.slice(0,i++);if(i>full.length)clearInterval(t);},26);})();
// ── Ticker défilant alimenté par les KPIs + opportunités ──
function buildTicker(){var t=document.getElementById('tick');if(!t)return;
 function g(id){var e=document.getElementById(id);return e?e.textContent.trim():'';}
 var seg='<b>HYPERSMART</b><span class="s">//</span>PnL '+g('pnl')+'<span class="s">·</span>equity '+g('eq')+'<span class="s">·</span>WR '+g('wr')+'<span class="s">·</span>pos '+g('pos')+'<span class="s">·</span>expo '+g('expo')+'<span class="s">·</span>';
 var rows=document.querySelectorAll('#opptb tr');if(rows.length){seg+='TOP<span class="s">»</span>';rows.forEach(function(r){var td=r.querySelectorAll('td');if(td.length>=5){seg+='<b>'+(td[1].textContent||'').trim().split(' ')[0]+'</b> '+(td[3].textContent||'').trim()+'<span class="s">·</span>';}});}
 seg+='READ-ONLY PAPER<span class="s">·</span>0 ORDRE REEL<span class="s">·</span>';
 t.innerHTML=seg+seg;}
setInterval(buildTicker,3000);setTimeout(buildTicker,400);
</script></body></html>"""


def create_dashboard_v2_router() -> APIRouter:
    router = APIRouter()

    @router.get("/v2", response_class=HTMLResponse)
    def dashboard_v2() -> HTMLResponse:
        return HTMLResponse(_PAGE)

    @router.get("/v2/equity_history")
    def equity_history(request: Request, max: int = 600) -> JSONResponse:
        # Priorite: historique persiste par le MOTEUR (survit a la fermeture de Chrome).
        try:
            from hl_observer.runtime.equity_history_store import read_equity_points
            persisted = read_equity_points(max=max)
        except Exception:
            persisted = []
        if persisted:
            return JSONResponse({"points": persisted})
        state = getattr(request.app.state, "ui_state", None)
        raw = list(getattr(state, "simulation_equity_history", None) or [])
        if max and len(raw) > max:
            raw = raw[-max:]
        points = []
        for p in raw:
            try:
                points.append({
                    "t": int(p.get("timestamp_ms") or 0),
                    "equity": float(p.get("current_equity_usdt") or 0.0),
                    "pnl": float(p.get("current_pnl_usdc") or 0.0),
                })
            except Exception:
                continue
        return JSONResponse({"points": points})

    return router


__all__ = ["create_dashboard_v2_router", "CANONICAL_STATUS_FIELDS"]
