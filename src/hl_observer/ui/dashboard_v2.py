"""Dashboard v2 — thème hacker high-tech (UI refonte).

Router FastAPI SÉPARÉ monté à /v2. Ne touche jamais le gros routes.py. Read-only
strict: /api/simulation/status (ledger canonique) + /v2/equity_history (courbe
d'equity réelle persistante). Visuel: glassmorphism, néons, grille animée,
metagraphe rayonnant. L'ancienne UI reste à /.
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
<title>HYPERSMART // observer</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700;800&family=Orbitron:wght@600;800&display=swap" rel="stylesheet">
<style>
:root{
 --bg0:#03060a;--bg1:#060d0f;--green:#3dfc9a;--green2:#0affc0;--cyan:#22d3ee;
 --amber:#ffcf4a;--red:#ff5f6d;--dim:#4a6a5c;--dim2:#2e4a3e;--txt:#d6f5e6;
 --line:rgba(61,252,154,.14);--line2:rgba(61,252,154,.30);--glass:rgba(8,18,14,.55);
 --mono:'JetBrains Mono',ui-monospace,Consolas,monospace;--disp:'Orbitron',var(--mono);
}
*{box-sizing:border-box}
html,body{margin:0}
body{
 background:radial-gradient(1200px 700px at 78% -12%,rgba(10,255,192,.10),transparent 60%),
            radial-gradient(900px 600px at 8% 108%,rgba(34,211,238,.08),transparent 55%),
            linear-gradient(180deg,#03060a,#04080b 60%,#03050a);
 color:var(--txt);font-family:var(--mono);min-height:100vh;padding:20px 18px 30px;
 -webkit-font-smoothing:antialiased;letter-spacing:.2px;position:relative;overflow-x:hidden;
}
/* grille animée + scanline */
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
 background-image:linear-gradient(rgba(61,252,154,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(61,252,154,.045) 1px,transparent 1px);
 background-size:44px 44px;mask-image:radial-gradient(circle at 50% 30%,#000 55%,transparent 100%);animation:drift 24s linear infinite}
body::after{content:"";position:fixed;left:0;right:0;height:180px;top:-180px;z-index:1;pointer-events:none;
 background:linear-gradient(180deg,transparent,rgba(61,252,154,.05),transparent);animation:scan 7s linear infinite}
@keyframes drift{to{background-position:44px 44px,44px 44px}}
@keyframes scan{0%{top:-180px}100%{top:100%}}
@keyframes blink{0%,48%{opacity:1}50%,100%{opacity:.15}}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.35;transform:scale(.82)}}
@keyframes ring{0%{r:3;opacity:.85}100%{r:16;opacity:0}}
@keyframes fadein{from{opacity:0;transform:translateY(-3px)}to{opacity:1;transform:none}}
@keyframes flick{0%,19%,21%,100%{opacity:1}20%{opacity:.5}}
@keyframes sheen{0%{background-position:-200% 0}100%{background-position:200% 0}}
.wrap{position:relative;z-index:2;max-width:1120px;margin:auto}
/* header */
.hd{display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:8px;margin-bottom:16px;
 padding-bottom:12px;border-bottom:1px solid var(--line);position:relative}
.hd::after{content:"";position:absolute;left:0;bottom:-1px;height:1px;width:100%;
 background:linear-gradient(90deg,transparent,var(--green),var(--cyan),transparent);background-size:200% 100%;animation:sheen 6s linear infinite}
.brand{font-family:var(--disp);font-weight:800;font-size:20px;letter-spacing:3px;
 color:var(--green);text-shadow:0 0 12px rgba(61,252,154,.55),0 0 26px rgba(61,252,154,.25)}
.brand small{color:var(--dim);font-family:var(--mono);font-weight:500;font-size:11px;letter-spacing:1px;text-shadow:none}
.brand .cur{animation:blink 1.1s steps(1) infinite;color:var(--green2)}
.meta-line{font-size:11px;color:var(--dim);text-align:right;line-height:1.7;font-variant-numeric:tabular-nums}
.chip{display:inline-flex;align-items:center;gap:5px;padding:2px 8px;border:1px solid var(--line);border-radius:20px;background:var(--glass)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green);animation:pulse 2s infinite;display:inline-block}
.num{font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* cards */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:14px}
.stat{position:relative;padding:12px 14px;border-radius:12px;background:var(--glass);backdrop-filter:blur(8px);
 border:1px solid var(--line);overflow:hidden;transition:border-color .3s}
.stat::before{content:"";position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,var(--green),transparent 70%);opacity:.8}
.stat .k{font-size:10px;letter-spacing:1.5px;color:var(--dim);text-transform:uppercase}
.stat .val{font-family:var(--disp);font-size:23px;font-weight:600;margin-top:4px}
.glow-g{color:var(--green);text-shadow:0 0 10px rgba(61,252,154,.5)}
.glow-c{color:var(--cyan);text-shadow:0 0 10px rgba(34,211,238,.5)}
.glow-a{color:var(--amber);text-shadow:0 0 10px rgba(255,207,74,.45)}
.glow-r{color:var(--red);text-shadow:0 0 10px rgba(255,95,109,.5)}
.panel{position:relative;padding:14px;border-radius:14px;background:var(--glass);backdrop-filter:blur(8px);
 border:1px solid var(--line);margin-bottom:14px}
.panel::after,.panel::before{content:"";position:absolute;width:12px;height:12px;pointer-events:none}
.panel::before{top:7px;left:7px;border-top:1px solid var(--line2);border-left:1px solid var(--line2)}
.panel::after{bottom:7px;right:7px;border-bottom:1px solid var(--line2);border-right:1px solid var(--line2)}
.ttl{font-size:10px;letter-spacing:2px;color:var(--dim);text-transform:uppercase;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center}
.ttl b{color:var(--green);font-weight:700;letter-spacing:2px}
.row2{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin-bottom:14px}
.row3{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:14px}
table{width:100%;font-size:12px;border-collapse:collapse;table-layout:fixed}
th{font-weight:500;color:var(--dim);text-align:left;font-size:10px;letter-spacing:1px;text-transform:uppercase;padding-bottom:6px;border-bottom:1px solid var(--line)}
td{padding:6px 0;border-bottom:1px solid rgba(61,252,154,.06)}
.tag{font-size:10px;padding:1px 7px;border-radius:5px;font-weight:500}
.tag-s{color:var(--amber);background:rgba(255,207,74,.1)}
.tag-g{color:var(--cyan);background:rgba(34,211,238,.1)}
.ev{animation:fadein .5s ease-out;line-height:1.9}
.mg-legend{position:absolute;top:34px;right:16px;font-size:10px;color:var(--dim);text-align:right;line-height:1.6}
.foot{display:flex;justify-content:space-between;font-size:10px;color:var(--dim2);margin-top:4px}
.wire{display:flex;gap:8px;flex-wrap:wrap;align-items:center;font-size:11.5px}
.wnode{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:8px;background:rgba(61,252,154,.05);border:1px solid var(--line)}
.arrow{color:var(--dim2)}
</style></head><body><div class="wrap">
 <div class="hd">
   <div class="brand">HYPERSMART<small> // observer.v2</small> <span class="cur">▊</span></div>
   <div class="meta-line num">
     <span class="chip"><span class="dot"></span><span id="mode">…</span></span>
     <span class="chip" style="border-color:var(--line2)"><span id="ro" style="color:var(--green)">read_only</span></span><br>
     <span style="opacity:.85">marks <span id="fresh">…</span> · <span id="clk">…</span></span>
   </div>
 </div>

 <div class="stats">
   <div class="stat"><div class="k">PnL net</div><div class="val glow-g" id="pnl">…</div></div>
   <div class="stat"><div class="k">Equity</div><div class="val" id="eq" style="color:var(--txt)">…</div></div>
   <div class="stat"><div class="k">Winrate</div><div class="val glow-a" id="wr">…</div></div>
   <div class="stat"><div class="k">Positions</div><div class="val" id="pos" style="color:var(--txt)">…</div></div>
   <div class="stat"><div class="k">Exposition</div><div class="val glow-c" id="expo">…</div></div>
   <div class="stat"><div class="k">Trades</div><div class="val" id="trd" style="color:var(--txt)">…</div></div>
 </div>

 <div class="panel">
   <div class="ttl"><span><b>METAGRAPHE</b> &nbsp;equity · session</span><span id="mg-span" style="color:var(--dim)"></span></div>
   <div style="position:relative">
   <svg id="mg" viewBox="0 0 1000 210" preserveAspectRatio="none" style="width:100%;height:210px;display:block">
     <defs>
       <linearGradient id="mgfill" x1="0" y1="0" x2="0" y2="1">
         <stop offset="0" stop-color="#3dfc9a" stop-opacity="0.34"/><stop offset="1" stop-color="#3dfc9a" stop-opacity="0"/>
       </linearGradient>
       <filter id="glow" x="-20%" y="-40%" width="140%" height="180%">
         <feGaussianBlur stdDeviation="3.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
       </filter>
     </defs>
     <line id="mg-base" x1="0" x2="1000" stroke="#3dfc9a" stroke-width="1" stroke-dasharray="5 6" opacity="0.4"/>
     <path id="mg-area" fill="url(#mgfill)" d=""/>
     <path id="mg-line" fill="none" stroke="#3dfc9a" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round" filter="url(#glow)" d=""/>
     <circle id="mg-ring" r="3" fill="none" stroke="#3dfc9a" stroke-width="1.5" style="animation:ring 1.8s ease-out infinite"/>
     <circle id="mg-live" r="3.4" fill="#0affc0" style="filter:drop-shadow(0 0 6px #3dfc9a)"/>
   </svg>
   <div class="mg-legend"><span id="mg-hi"></span><br><span id="mg-lo"></span></div>
   </div>
   <div class="foot"><span id="mg-t0"></span><span style="color:var(--dim)">╌╌ base = equity départ</span><span id="mg-t1"></span></div>
 </div>

 <div class="row3">
   <div class="stat"><div class="k">Sniper</div><div class="val" id="m_sniper" style="font-size:18px">—</div></div>
   <div class="stat"><div class="k">Grinder</div><div class="val" id="m_grinder" style="font-size:18px">—</div></div>
   <div class="stat"><div class="k">Funding · paires</div><div class="val glow-g" id="m_funding" style="font-size:18px">—</div></div>
 </div>

 <div class="row2">
   <div class="panel"><div class="ttl"><span><b>POSITIONS</b></span><span class="num" id="poslbl" style="color:var(--dim)"></span></div>
     <table><thead><tr><th style="width:26%">coin</th><th style="width:26%">mode</th><th style="width:22%">notl</th><th style="width:26%;text-align:right">pnl</th></tr></thead><tbody id="postb"></tbody></table></div>
   <div class="panel"><div class="ttl"><span><b>SANTÉ</b> &nbsp;ledger · réconciliation</span></div>
     <div class="num" id="health" style="font-size:12px;color:#9ec7b3;line-height:2.1"></div></div>
 </div>

 <div class="panel"><div class="ttl"><span><b>WIRING</b> &nbsp;source → ledger</span></div>
   <div id="wiring" class="wire num"></div></div>
 <div class="panel"><div class="ttl"><span><b>ÉTAT</b> &nbsp;moteur / fusion</span></div>
   <div id="state" class="num" style="font-size:12px;color:#9ec7b3;line-height:2"></div></div>
</div>
<script>
function n(x,d){x=Number(x);return isNaN(x)?'—':x.toFixed(d==null?2:d)}
function col(v){return v>=0?'var(--green)':'var(--red)'}
function hhmm(ms){var d=new Date(ms);return ('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2)}
function smoothPath(pts){
  if(pts.length<2) return pts.length?('M'+pts[0][0]+' '+pts[0][1]):'';
  var d='M'+pts[0][0].toFixed(1)+' '+pts[0][1].toFixed(1);
  for(var i=0;i<pts.length-1;i++){
    var p0=pts[i>0?i-1:0],p1=pts[i],p2=pts[i+1],p3=pts[i+2<pts.length?i+2:i+1];
    var c1x=p1[0]+(p2[0]-p0[0])/6,c1y=p1[1]+(p2[1]-p0[1])/6,c2x=p2[0]-(p3[0]-p1[0])/6,c2y=p2[1]-(p3[1]-p1[1])/6;
    d+=' C'+c1x.toFixed(1)+' '+c1y.toFixed(1)+','+c2x.toFixed(1)+' '+c2y.toFixed(1)+','+p2[0].toFixed(1)+' '+p2[1].toFixed(1);
  } return d;
}
function drawMeta(pts){
  var W=1000,H=210,PAD=12; if(!pts.length)return;
  var eqs=pts.map(function(p){return p.equity}),base=pts[0].equity;
  var lo=Math.min.apply(null,eqs.concat([base])),hi=Math.max.apply(null,eqs.concat([base]));
  var rng=(hi-lo)||1,pd=rng*0.14; lo-=pd; hi+=pd; rng=hi-lo;
  var t0=pts[0].t,t1=pts[pts.length-1].t,tspan=(t1-t0)||1;
  function X(t){return PAD+(W-2*PAD)*(t-t0)/tspan} function Y(e){return PAD+(H-2*PAD)*(1-(e-lo)/rng)}
  var xy=pts.map(function(p){return [X(p.t),Y(p.equity)]}),line=smoothPath(xy),last=pts[pts.length-1];
  var up=last.equity>=base,c=up?'#3dfc9a':'#ff5f6d';
  var L=document.getElementById('mg-line');L.setAttribute('d',line);L.setAttribute('stroke',c);
  document.getElementById('mg-area').setAttribute('d',line+' L'+xy[xy.length-1][0].toFixed(1)+' '+(H-PAD)+' L'+xy[0][0].toFixed(1)+' '+(H-PAD)+' Z');
  var by=Y(base),bl=document.getElementById('mg-base');bl.setAttribute('y1',by);bl.setAttribute('y2',by);bl.setAttribute('stroke',c);
  var lx=xy[xy.length-1][0],ly=xy[xy.length-1][1];
  ['mg-live','mg-ring'].forEach(function(id){var e=document.getElementById(id);e.setAttribute('cx',lx);e.setAttribute('cy',ly);e.setAttribute(id==='mg-live'?'fill':'stroke',c);});
  document.getElementById('mg-hi').textContent='▲ '+n(hi-pd);
  document.getElementById('mg-lo').textContent='▼ '+n(lo+pd);
  document.getElementById('mg-t0').textContent=hhmm(t0);
  document.getElementById('mg-t1').textContent=hhmm(t1)+' · '+pts.length+' pts';
  var sp=(t1-t0)/3600000;document.getElementById('mg-span').textContent=sp>=1?(sp.toFixed(1)+'h'):(Math.round((t1-t0)/60000)+'min');
}
function loadMeta(){fetch('/v2/equity_history?max=600').then(function(r){return r.json()}).then(function(d){
  var pts=(d.points||[]).map(function(p){return {t:Number(p.t),equity:Number(p.equity),pnl:Number(p.pnl)}}).filter(function(p){return p.equity>0});
  if(pts.length)drawMeta(pts);}).catch(function(){});}
function modeOf(p){var m=(p.position_mode||'').toUpperCase();
  return (m.indexOf('FUNDING')>=0||m.indexOf('ARBITRAGE')>=0||m.indexOf('TRIANGULAR')>=0||m.indexOf('DELTA')>=0||m.indexOf('EXTERNAL_GITHUB')>=0)?'GRINDER':'SNIPER';}
function tick(){
  fetch('/api/simulation/status').then(function(r){return r.json()}).then(function(d){
    document.getElementById('mode').textContent=(d.mode||'').slice(0,26)||'live';
    document.getElementById('ro').textContent=d.read_only?'read_only':'??';
    var pnl=Number(d.net_pnl_usdt||0),e=document.getElementById('pnl');e.textContent=(pnl>=0?'+':'')+n(pnl);
    e.className='val '+(pnl>=0?'glow-g':'glow-r');
    document.getElementById('eq').textContent=n(d.equity_usdt);
    document.getElementById('wr').textContent=n(d.winrate_pct,0)+'%';
    document.getElementById('pos').textContent=(d.open_positions||0);
    document.getElementById('expo').textContent=n(d.open_exposure_usdt);
    document.getElementById('trd').textContent=(d.closed_trades||0);
    var eqo=d.equity||{},av=Number(eqo.market_marks_available||0),mi=Number(eqo.market_marks_missing||0),fr=document.getElementById('fresh');
    if(mi>0&&av===0){fr.textContent='⚠ manquants';fr.style.color='var(--red)';}
    else if(mi>0){fr.textContent=av+'✓/'+mi+'✗';fr.style.color='var(--amber)';}
    else{fr.textContent=av+' ✓';fr.style.color='var(--green)';}
    var ps=(d.positions||[]),sniper={n:0,p:0},grinder={n:0,p:0};
    ps.forEach(function(p){var g=modeOf(p),pp=Number(p.unrealized_pnl_usdc||p.pnl_usdc||0);if(g==='SNIPER'){sniper.n++;sniper.p+=pp;}else{grinder.n++;grinder.p+=pp;}});
    document.getElementById('m_sniper').innerHTML=sniper.n+' <span style="font-size:12px;color:'+col(sniper.p)+'">'+(sniper.p>=0?'+':'')+n(sniper.p)+'</span>';
    document.getElementById('m_grinder').innerHTML=grinder.n+' <span style="font-size:12px;color:'+col(grinder.p)+'">'+(grinder.p>=0?'+':'')+n(grinder.p)+'</span>';
    var fus=d.fusion_runtime||{},fa=fus.funding_arb||{};
    document.getElementById('m_funding').textContent=(fa.open_pairs!=null?fa.open_pairs:0)+(fa.enabled?'':' ·off');
    var tb=document.getElementById('postb');tb.innerHTML='';document.getElementById('poslbl').textContent=ps.length+' ouvertes';
    ps.slice(0,12).forEach(function(p){var g=modeOf(p),pp=Number(p.unrealized_pnl_usdc||p.pnl_usdc||0),notl=Number(p.notional_usdt||p.copied_notional_usdt||0),tr=document.createElement('tr');
      tr.innerHTML='<td style="color:var(--txt)">'+(p.coin||'?')+'</td><td><span class="tag '+(g==='SNIPER'?'tag-s':'tag-g')+'">'+g+'</span></td><td class="num">'+n(notl)+'</td><td class="num" style="text-align:right;color:'+col(pp)+'">'+(pp>=0?'+':'')+n(pp)+'</td>';tb.appendChild(tr);});
    if(!ps.length)tb.innerHTML='<tr><td colspan="4" style="color:var(--dim)">— aucune position ouverte —</td></tr>';
    var pl=d.paper_ledger||{},rec=pl.reconciliation||{},exp=Number(rec.expected_equity_usdc||0),act=Number(rec.actual_equity_usdc||0),gap=Math.abs(exp-act);
    document.getElementById('health').innerHTML='realized <b style="color:'+col(Number(d.realized_pnl_usdt||0))+'">'+n(d.realized_pnl_usdt)+'</b> &nbsp;·&nbsp; unrealized <b style="color:'+col(Number(d.unrealized_pnl_usdt||0))+'">'+n(d.unrealized_pnl_usdt)+'</b><br>réconciliation <b style="color:'+(gap<0.01?'var(--green)':'var(--red)')+'">écart '+n(gap,6)+'</b> &nbsp;·&nbsp; '+(d.winning_trades||0)+'W / '+(d.losing_trades||0)+'L';
    var sc=d.scanner||{},pe=(fus.paper_engine)||{},summ=fus.external_profile_execution_summary||{};
    function node(ok,label,val){return '<span class="wnode"><span class="dot" style="background:'+(ok?'var(--green)':'var(--red)')+';box-shadow:0 0 8px '+(ok?'var(--green)':'var(--red)')+'"></span>'+label+' <b style="color:var(--dim)">'+val+'</b></span>';}
    document.getElementById('wiring').innerHTML=[node(d.engine_running,'ws_scan',(sc.engine_running?'live':'off')),node((fus.status||'').indexOf('OK')>=0,'fusion',(fus.status||'—').slice(0,12)),node(true,'profils',(summ.profiles_executed!=null?summ.profiles_executed:'—')),node(true,'paper_engine',(pe.accepted_count!=null?pe.accepted_count:'—')),node(gap<0.01,'ledger',(pl.open_positions_count!=null?pl.open_positions_count+' pos':'—'))].join('<span class="arrow">▶</span>');
    document.getElementById('state').innerHTML='moteur <b style="color:'+(d.engine_running?'var(--green)':'var(--red)')+'">'+(d.engine_running?'● actif':'○ arrêté')+'</b> &nbsp;│&nbsp; serveur '+(d.server_running?'●':'○')+' &nbsp;│&nbsp; fusion <b style="color:var(--dim)">'+((fus.status)||'—')+'</b>';
    document.getElementById('clk').textContent=new Date().toLocaleTimeString();
  }).catch(function(){document.getElementById('state').innerHTML='<span style="color:var(--red)">✕ serveur injoignable</span>';});
}
tick();setInterval(tick,2000);loadMeta();setInterval(loadMeta,10000);
</script></body></html>"""


def create_dashboard_v2_router() -> APIRouter:
    router = APIRouter()

    @router.get("/v2", response_class=HTMLResponse)
    def dashboard_v2() -> HTMLResponse:
        return HTMLResponse(_PAGE)

    @router.get("/v2/equity_history")
    def equity_history(request: Request, max: int = 600) -> JSONResponse:
        state = getattr(request.app.state, "ui_state", None)
        raw = list(getattr(state, "simulation_equity_history", None) or [])
        if max and max > 0:
            raw = raw[-int(max):]
        points = []
        for p in raw:
            if not isinstance(p, dict):
                continue
            try:
                points.append({
                    "t": int(p.get("timestamp_ms") or 0),
                    "equity": float(p.get("current_equity_usdt") or 0.0),
                    "pnl": float(p.get("current_pnl_usdc") or 0.0),
                })
            except (TypeError, ValueError):
                continue
        return JSONResponse({"points": points, "count": len(points), "read_only": True})

    return router


__all__ = ["create_dashboard_v2_router", "CANONICAL_STATUS_FIELDS"]
