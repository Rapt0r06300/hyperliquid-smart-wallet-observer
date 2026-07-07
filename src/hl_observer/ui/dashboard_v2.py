"""Dashboard v2 — terminal de trading premium, thème hacker épuré.

Router FastAPI SÉPARÉ monté à /v2. Ne touche jamais le gros routes.py. Read-only:
/api/simulation/status (ledger canonique) + /v2/equity_history (courbe réelle
persistante). Design: hiérarchie claire, courbe héros, glow parcimonieux.
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
<title>HYPERSMART</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root{
 --bg:#05080b;--surface:rgba(255,255,255,.022);--surface2:rgba(255,255,255,.04);
 --green:#2ce69b;--green-soft:#39d99a;--red:#ff5c6a;--txt:#eaf2ed;--mut:#6b7d74;--mut2:#3c4a43;
 --line:rgba(255,255,255,.06);--line2:rgba(44,230,155,.22);
 --sans:'Space Grotesk',system-ui,sans-serif;--mono:'JetBrains Mono',ui-monospace,monospace;
}
*{box-sizing:border-box}html,body{margin:0}
body{background:
 radial-gradient(1100px 620px at 82% -18%,rgba(44,230,155,.07),transparent 62%),
 radial-gradient(760px 520px at 6% 118%,rgba(44,230,155,.045),transparent 60%),var(--bg);
 color:var(--txt);font-family:var(--sans);min-height:100vh;padding:26px 22px 34px;-webkit-font-smoothing:antialiased}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
.wrap{max-width:960px;margin:auto}
@keyframes blink{0%,46%{opacity:1}50%,96%{opacity:.12}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
@keyframes ring{0%{r:3.2;opacity:.7}100%{r:15;opacity:0}}
@keyframes fade{from{opacity:0;transform:translateY(-2px)}to{opacity:1;transform:none}}
/* top bar */
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:26px}
.logo{font-family:var(--sans);font-weight:700;font-size:16px;letter-spacing:4px;color:var(--txt)}
.logo b{color:var(--green)}
.logo .c{color:var(--green);animation:blink 1.2s steps(1) infinite}
.status{font-family:var(--mono);font-size:11.5px;color:var(--mut);display:flex;gap:14px;align-items:center}
.led{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 9px var(--green);animation:pulse 2.4s infinite;display:inline-block;margin-right:6px}
/* hero */
.hero{position:relative;margin-bottom:24px}
.hero-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:2px}
.pnl-big{font-family:var(--sans);font-weight:600;font-size:46px;line-height:1;letter-spacing:-1px}
.pnl-pos{color:var(--green);text-shadow:0 0 26px rgba(44,230,155,.45)}
.pnl-neg{color:var(--red);text-shadow:0 0 26px rgba(255,92,106,.4)}
.pnl-sub{font-family:var(--mono);font-size:12.5px;color:var(--mut);margin-top:7px;letter-spacing:.3px}
.hero-hl{text-align:right;font-family:var(--mono);font-size:11px;color:var(--mut);line-height:1.7}
.chart{position:relative;margin-top:10px}
.chart svg{width:100%;height:220px;display:block}
.axis{display:flex;justify-content:space-between;font-family:var(--mono);font-size:10.5px;color:var(--mut2);margin-top:4px}
/* stat strip */
.strip{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line);border-radius:14px;overflow:hidden;margin-bottom:22px}
.st{background:var(--bg);padding:15px 18px}
.st .k{font-size:10.5px;letter-spacing:1.4px;color:var(--mut);text-transform:uppercase}
.st .v{font-family:var(--mono);font-size:22px;font-weight:500;margin-top:5px}
/* lower */
.low{display:grid;grid-template-columns:1.5fr 1fr;gap:16px;margin-bottom:20px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.card h3{font-family:var(--sans);font-weight:500;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--mut);margin:0 0 14px}
table{width:100%;font-family:var(--mono);font-size:12.5px;border-collapse:collapse;table-layout:fixed}
th{font-weight:400;color:var(--mut);text-align:left;font-size:10px;letter-spacing:.6px;text-transform:uppercase;padding-bottom:8px}
td{padding:7px 0;border-top:1px solid rgba(255,255,255,.04)}
.tag{font-size:10px;padding:2px 8px;border-radius:20px}
.tg-s{color:#ffce5b;background:rgba(255,206,91,.09)}
.tg-g{color:var(--green);background:rgba(44,230,155,.09)}
.kv{display:flex;justify-content:space-between;font-family:var(--mono);font-size:12.5px;padding:6px 0;color:#a9bcb1}
.kv span:first-child{color:var(--mut)}
/* status rail */
.rail{display:flex;gap:18px;flex-wrap:wrap;align-items:center;font-family:var(--mono);font-size:11.5px;color:var(--mut);
 border-top:1px solid var(--line);padding-top:16px}
.rail .n{display:inline-flex;align-items:center;gap:6px}
.rail .d{width:6px;height:6px;border-radius:50%;display:inline-block}
.ev{animation:fade .5s ease-out}
</style></head><body><div class="wrap">
 <div class="top">
   <div class="logo"><b>HYPER</b>SMART <span class="c">▍</span></div>
   <div class="status"><span><span class="led"></span><span id="mode">live</span></span><span id="ro" style="color:var(--green)">read_only</span><span id="fresh">…</span><span id="clk" class="num">…</span></div>
 </div>

 <div class="hero">
   <div class="hero-head">
     <div>
       <div class="pnl-big pnl-pos" id="pnl">+0.00</div>
       <div class="pnl-sub"><span id="pnl-unit">USDC</span> · equity <span id="eq" class="num">…</span> · <span id="chg" class="num">+0.00%</span></div>
     </div>
     <div class="hero-hl">METAGRAPHE · <span id="mg-span">…</span><br><span id="mg-hi"></span><br><span id="mg-lo"></span></div>
   </div>
   <div class="chart">
   <svg viewBox="0 0 1000 220" preserveAspectRatio="none">
     <defs>
       <linearGradient id="mgfill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2ce69b" stop-opacity="0.22"/><stop offset="1" stop-color="#2ce69b" stop-opacity="0"/></linearGradient>
       <filter id="glow" x="-15%" y="-40%" width="130%" height="180%"><feGaussianBlur stdDeviation="2.6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
     </defs>
     <line id="mg-base" x1="0" x2="1000" stroke="#2ce69b" stroke-width="1" stroke-dasharray="2 7" opacity="0.32"/>
     <path id="mg-area" fill="url(#mgfill)" d=""/>
     <path id="mg-line" fill="none" stroke="#2ce69b" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round" filter="url(#glow)" d=""/>
     <circle id="mg-ring" r="3.2" fill="none" stroke="#2ce69b" stroke-width="1.4" style="animation:ring 2s ease-out infinite"/>
     <circle id="mg-live" r="3.4" fill="#2ce69b" style="filter:drop-shadow(0 0 7px #2ce69b)"/>
   </svg>
   <div class="axis"><span id="mg-t0"></span><span style="color:var(--mut2)">╌ base = equity départ</span><span id="mg-t1"></span></div>
   </div>
 </div>

 <div class="strip">
   <div class="st"><div class="k">Winrate</div><div class="v" id="wr">…</div></div>
   <div class="st"><div class="k">Positions</div><div class="v" id="pos">…</div></div>
   <div class="st"><div class="k">Trades clos</div><div class="v" id="trd">…</div></div>
   <div class="st"><div class="k">Exposition</div><div class="v" id="expo">…</div></div>
 </div>

 <div class="low">
   <div class="card"><h3>Positions <span class="num" id="poslbl" style="color:var(--mut2);letter-spacing:0"></span></h3>
     <table><thead><tr><th style="width:30%">coin</th><th style="width:28%">mode</th><th style="width:20%">notl</th><th style="width:22%;text-align:right">pnl</th></tr></thead><tbody id="postb"></tbody></table></div>
   <div class="card"><h3>État</h3>
     <div class="kv"><span>moteur</span><span id="engine">…</span></div>
     <div class="kv"><span>funding · paires</span><span id="m_funding">…</span></div>
     <div class="kv"><span>modes</span><span id="modes">…</span></div>
     <div class="kv"><span>réconciliation</span><span id="recon">…</span></div>
     <div class="kv"><span>realized / unreal.</span><span id="ru">…</span></div>
   </div>
 </div>

 <div class="rail" id="wiring"></div>
</div>
<script>
function n(x,d){x=Number(x);return isNaN(x)?'—':x.toFixed(d==null?2:d)}
function col(v){return v>=0?'var(--green)':'var(--red)'}
function hhmm(ms){var d=new Date(ms);return ('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2)}
function smoothPath(pts){
  if(pts.length<2)return pts.length?('M'+pts[0][0]+' '+pts[0][1]):'';
  var d='M'+pts[0][0].toFixed(1)+' '+pts[0][1].toFixed(1);
  for(var i=0;i<pts.length-1;i++){var p0=pts[i>0?i-1:0],p1=pts[i],p2=pts[i+1],p3=pts[i+2<pts.length?i+2:i+1];
    d+=' C'+(p1[0]+(p2[0]-p0[0])/6).toFixed(1)+' '+(p1[1]+(p2[1]-p0[1])/6).toFixed(1)+','+(p2[0]-(p3[0]-p1[0])/6).toFixed(1)+' '+(p2[1]-(p3[1]-p1[1])/6).toFixed(1)+','+p2[0].toFixed(1)+' '+p2[1].toFixed(1);}
  return d;}
function drawMeta(pts){
  var W=1000,H=220,PAD=14;if(!pts.length)return;
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
  document.getElementById('mg-hi').textContent='↑ '+n(hi-pd);
  document.getElementById('mg-lo').textContent='↓ '+n(lo+pd);
  document.getElementById('mg-t0').textContent=hhmm(t0);
  document.getElementById('mg-t1').textContent=hhmm(t1)+' · '+pts.length+' pts';
  var sp=(t1-t0)/3600000;document.getElementById('mg-span').textContent=sp>=1?(sp.toFixed(1)+'h'):(Math.round((t1-t0)/60000)+'min');
  window._base=base;
}
function loadMeta(){fetch('/v2/equity_history?max=600').then(function(r){return r.json()}).then(function(d){
  var pts=(d.points||[]).map(function(p){return {t:Number(p.t),equity:Number(p.equity),pnl:Number(p.pnl)}}).filter(function(p){return p.equity>0});
  if(pts.length)drawMeta(pts);}).catch(function(){});}
function modeOf(p){var m=(p.position_mode||'').toUpperCase();
  return (m.indexOf('FUNDING')>=0||m.indexOf('ARBITRAGE')>=0||m.indexOf('TRIANGULAR')>=0||m.indexOf('DELTA')>=0||m.indexOf('EXTERNAL_GITHUB')>=0)?'GRINDER':'SNIPER';}
function tick(){
  fetch('/api/simulation/status').then(function(r){return r.json()}).then(function(d){
    document.getElementById('mode').textContent=(d.mode? 'live':'live');
    document.getElementById('ro').textContent=d.read_only?'read_only':'??';
    var pnl=Number(d.net_pnl_usdt||0),eq=Number(d.equity_usdt||0);
    var P=document.getElementById('pnl');P.textContent=(pnl>=0?'+':'')+n(pnl);P.className='pnl-big '+(pnl>=0?'pnl-pos':'pnl-neg');
    document.getElementById('eq').textContent=n(eq);
    var base=window._base||(eq-pnl)||1000;var chg=base>0?(pnl/base*100):0;
    var C=document.getElementById('chg');C.textContent=(chg>=0?'+':'')+n(chg,2)+'%';C.style.color=col(chg);
    document.getElementById('wr').textContent=n(d.winrate_pct,0)+'%';
    document.getElementById('pos').textContent=(d.open_positions||0);
    document.getElementById('trd').textContent=(d.closed_trades||0);
    document.getElementById('expo').textContent=n(d.open_exposure_usdt);
    var eqo=d.equity||{},av=Number(eqo.market_marks_available||0),mi=Number(eqo.market_marks_missing||0),fr=document.getElementById('fresh');
    if(mi>0&&av===0){fr.textContent='marks ⚠';fr.style.color='var(--red)';}else if(mi>0){fr.textContent='marks '+av+'/'+(av+mi);fr.style.color='#ffce5b';}else{fr.textContent='marks ✓';fr.style.color='var(--mut)';}
    var ps=(d.positions||[]),sniper=0,grinder=0;ps.forEach(function(p){if(modeOf(p)==='SNIPER')sniper++;else grinder++;});
    var fus=d.fusion_runtime||{},fa=fus.funding_arb||{};
    document.getElementById('m_funding').textContent=(fa.open_pairs!=null?fa.open_pairs:0)+(fa.enabled?'':' · off');
    document.getElementById('modes').innerHTML='<span style="color:#ffce5b">'+sniper+' sniper</span> · <span style="color:var(--green)">'+grinder+' grinder</span>';
    document.getElementById('engine').innerHTML=d.engine_running?'<span style="color:var(--green)">● actif</span>':'<span style="color:var(--red)">○ arrêté</span>';
    var pl=d.paper_ledger||{},rec=pl.reconciliation||{},gap=Math.abs(Number(rec.expected_equity_usdc||0)-Number(rec.actual_equity_usdc||0));
    document.getElementById('recon').innerHTML='<span style="color:'+(gap<0.01?'var(--green)':'var(--red)')+'">écart '+n(gap,6)+'</span>';
    document.getElementById('ru').innerHTML='<span style="color:'+col(Number(d.realized_pnl_usdt||0))+'">'+n(d.realized_pnl_usdt)+'</span> / <span style="color:'+col(Number(d.unrealized_pnl_usdt||0))+'">'+n(d.unrealized_pnl_usdt)+'</span>';
    var tb=document.getElementById('postb');tb.innerHTML='';document.getElementById('poslbl').textContent=ps.length;
    ps.slice(0,10).forEach(function(p){var g=modeOf(p),pp=Number(p.unrealized_pnl_usdc||p.pnl_usdc||0),notl=Number(p.notional_usdt||p.copied_notional_usdt||0),tr=document.createElement('tr');tr.className='ev';
      tr.innerHTML='<td>'+(p.coin||'?')+'</td><td><span class="tag '+(g==='SNIPER'?'tg-s':'tg-g')+'">'+g+'</span></td><td>'+n(notl)+'</td><td style="text-align:right;color:'+col(pp)+'">'+(pp>=0?'+':'')+n(pp)+'</td>';tb.appendChild(tr);});
    if(!ps.length)tb.innerHTML='<tr><td colspan="4" style="color:var(--mut2);border:0;padding-top:10px">— aucune position ouverte —</td></tr>';
    var sc=d.scanner||{},pe=(fus.paper_engine)||{},summ=fus.external_profile_execution_summary||{};
    function nd(ok,l,v){return '<span class="n"><span class="d" style="background:'+(ok?'var(--green)':'var(--red)')+';box-shadow:0 0 7px '+(ok?'var(--green)':'var(--red)')+'"></span>'+l+' <span style="color:var(--mut2)">'+v+'</span></span>';}
    document.getElementById('wiring').innerHTML='<span style="color:var(--mut2);letter-spacing:1px">WIRING</span>'+nd(d.engine_running,'ws',(sc.engine_running?'live':'off'))+nd((fus.status||'').indexOf('OK')>=0,'fusion',(summ.profiles_executed!=null?summ.profiles_executed:'—'))+nd(true,'paper_engine',(pe.accepted_count!=null?pe.accepted_count:'—'))+nd(gap<0.01,'ledger',(pl.open_positions_count!=null?pl.open_positions_count+' pos':'—'));
    document.getElementById('clk').textContent=new Date().toLocaleTimeString();
  }).catch(function(){document.getElementById('engine').innerHTML='<span style="color:var(--red)">✕ injoignable</span>';});
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
