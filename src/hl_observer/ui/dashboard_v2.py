"""Dashboard v2 — thème hacker (UI-1..6, spec docs/design/DASHBOARD_V2_MOCKUP.html).

Router FastAPI SÉPARÉ monté à /v2. Ne touche jamais le gros routes.py. Read-only
strict: interroge /api/simulation/status (ledger canonique) + /v2/equity_history
(courbe d'equity réelle persistante, pour le metagraphe). L'ancienne UI reste à /.
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
<title>HYPERSMART::observer_v2</title>
<style>
:root{--bg:#070b07;--pnl:#4ade80;--amber:#fbbf24;--cyan:#22d3ee;--red:#f87171;--dim:#5c705c;--txt:#d1e7d1;--grid:#132013}
*{box-sizing:border-box}
body{background:#050805;margin:0;padding:16px;font-family:ui-monospace,Consolas,monospace;color:var(--txt)}
@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
@keyframes ring{0%{r:3;opacity:.9}100%{r:11;opacity:0}}
@keyframes fadein{from{opacity:0;transform:translateY(-2px)}to{opacity:1;transform:none}}
.wrap{background:var(--bg);border:1px solid #1c2a1c;border-radius:8px;padding:14px 16px;max-width:1040px;margin:auto}
.hd{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid #162216;padding-bottom:8px;margin-bottom:10px;flex-wrap:wrap;gap:4px}
.hd .t{color:var(--pnl);font-size:14px;letter-spacing:1px}.hd .s{font-size:11px;color:var(--dim)}
.num{font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dot{animation:pulse 2s infinite}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));gap:8px;margin-bottom:10px}
.cell{background:#0c140c;padding:7px 9px;min-width:0}.cell .l{font-size:10px;color:var(--dim);letter-spacing:1px}.cell .v{font-size:17px}
.panel{background:#0c140c;padding:10px;margin-bottom:10px}.lbl{font-size:10px;color:var(--dim);letter-spacing:1px;margin-bottom:6px;display:flex;justify-content:space-between}
table{width:100%;font-size:11px;border-collapse:collapse;table-layout:fixed}th{font-weight:400;color:var(--dim);text-align:left}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:8px;margin-bottom:10px}
.three{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-bottom:10px}
.ev{animation:fadein .5s ease-out;line-height:1.8}
.fresh-ok{color:var(--pnl)}.fresh-warn{color:var(--amber)}.fresh-bad{color:var(--red)}
.mg-wrap{position:relative}
.mg-legend{position:absolute;top:2px;right:6px;font-size:10px;color:var(--dim);text-align:right;line-height:1.5}
</style></head><body><div class="wrap">
<div class="hd"><div class="t">┌─[ <span style="color:#a7f3d0">HYPERSMART</span><span style="color:var(--dim)">::observer_v2</span> ]<span style="animation:blink 1.1s infinite">▮</span></div>
<div class="s num"><span id="mode">…</span> │ <span id="ro">read_only</span> │ marks <span class="dot" id="freshdot">●</span> <span id="fresh">…</span> │ <span id="clk">…</span></div></div>
<div class="grid">
<div class="cell" style="border-left:2px solid var(--pnl)"><div class="l">PNL_NET</div><div class="v num" id="pnl">…</div></div>
<div class="cell" style="border-left:2px solid var(--dim)"><div class="l">EQUITY</div><div class="v num" id="eq">…</div></div>
<div class="cell" style="border-left:2px solid var(--amber)"><div class="l">WINRATE</div><div class="v num" id="wr">…</div></div>
<div class="cell" style="border-left:2px solid var(--dim)"><div class="l">POS</div><div class="v num" id="pos">…</div></div>
<div class="cell" style="border-left:2px solid var(--cyan)"><div class="l">EXPO_USDT</div><div class="v num" id="expo">…</div></div>
<div class="cell" style="border-left:2px solid var(--dim)"><div class="l">TRADES</div><div class="v num" id="trd">…</div></div>
</div>
<div class="panel mg-wrap"><div class="lbl"><span>┌ METAGRAPHE <span style="color:var(--dim)">equity · session complète</span></span><span id="mg-span" style="color:var(--dim)"></span></div>
<svg id="mg" viewBox="0 0 1000 200" preserveAspectRatio="none" style="width:100%;height:200px;display:block">
  <line id="mg-base" x1="0" x2="1000" stroke="#365936" stroke-width="1" stroke-dasharray="4 4" opacity="0.6"/>
  <path id="mg-area" fill="#4ade80" fill-opacity="0.06" d=""/>
  <path id="mg-line" fill="none" stroke="#4ade80" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" d="" style="filter:none"/>
  <circle id="mg-live" r="3" fill="#4ade80"/>
  <circle id="mg-ring" r="3" fill="none" stroke="#4ade80" stroke-width="1.5" style="animation:ring 1.8s ease-out infinite"/>
</svg>
<div class="mg-legend"><span id="mg-hi"></span><br><span id="mg-lo"></span></div>
<div class="num" style="display:flex;justify-content:space-between;font-size:10px;color:var(--dim);margin-top:2px"><span id="mg-t0"></span><span style="color:#365936">— — base = equity départ</span><span id="mg-t1"></span></div>
</div>
<div class="three">
<div class="cell" style="border-left:2px solid var(--amber)"><div class="l">SNIPER</div><div class="v num" id="m_sniper">—</div></div>
<div class="cell" style="border-left:2px solid var(--cyan)"><div class="l">GRINDER</div><div class="v num" id="m_grinder">—</div></div>
<div class="cell" style="border-left:2px solid var(--pnl)"><div class="l">FUNDING·paires</div><div class="v num" id="m_funding">—</div></div>
</div>
<div class="two">
<div class="panel"><div class="lbl"><span>┌ POSITIONS <span class="num" id="poslbl" style="color:var(--dim)"></span></span></div>
<table><thead><tr><th style="width:26%">coin</th><th style="width:26%">mode</th><th style="width:22%">notl</th><th style="width:26%;text-align:right">pnl</th></tr></thead><tbody id="postb"></tbody></table></div>
<div class="panel"><div class="lbl"><span>┌ SANTÉ <span style="color:var(--dim)">ledger·réconciliation</span></span></div>
<div class="num" id="health" style="font-size:11px;color:#8fa58f;line-height:2"></div></div>
</div>
<div class="panel"><div class="lbl"><span>┌ WIRING <span style="color:var(--dim)">source→ledger (compteurs live)</span></span></div>
<div id="wiring" class="num" style="font-size:11px;color:var(--txt);display:flex;gap:6px;flex-wrap:wrap;align-items:center"></div></div>
<div class="panel"><div class="lbl"><span>┌ ÉTAT <span style="color:var(--dim)">moteur / fusion</span></span></div>
<div id="state" class="num" style="font-size:11px;color:#8fa58f;line-height:2"></div></div>
</div>
<script>
function n(x,d){x=Number(x);return isNaN(x)?'—':x.toFixed(d==null?2:d)}
function col(v){return v>=0?'var(--pnl)':'var(--red)'}
function hhmm(ms){var d=new Date(ms);return ('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2)}
// ---- METAGRAPHE: courbe lissée (Catmull-Rom -> Bézier) sur l'historique réel ----
function smoothPath(pts){
  if(pts.length<2) return pts.length?('M'+pts[0][0]+' '+pts[0][1]):'';
  var d='M'+pts[0][0].toFixed(1)+' '+pts[0][1].toFixed(1);
  for(var i=0;i<pts.length-1;i++){
    var p0=pts[i>0?i-1:0],p1=pts[i],p2=pts[i+1],p3=pts[i+2<pts.length?i+2:i+1];
    var c1x=p1[0]+(p2[0]-p0[0])/6, c1y=p1[1]+(p2[1]-p0[1])/6;
    var c2x=p2[0]-(p3[0]-p1[0])/6, c2y=p2[1]-(p3[1]-p1[1])/6;
    d+=' C'+c1x.toFixed(1)+' '+c1y.toFixed(1)+','+c2x.toFixed(1)+' '+c2y.toFixed(1)+','+p2[0].toFixed(1)+' '+p2[1].toFixed(1);
  }
  return d;
}
function drawMeta(pts){
  var W=1000,H=200,PAD=10;
  if(!pts.length){return}
  var eqs=pts.map(function(p){return p.equity});
  var base=pts[0].equity;
  var lo=Math.min.apply(null,eqs.concat([base])), hi=Math.max.apply(null,eqs.concat([base]));
  var rng=(hi-lo)||1; var pad=rng*0.12; lo-=pad; hi+=pad; rng=hi-lo;
  var t0=pts[0].t, t1=pts[pts.length-1].t, tspan=(t1-t0)||1;
  function X(t){return PAD+(W-2*PAD)*(t-t0)/tspan}
  function Y(e){return PAD+(H-2*PAD)*(1-(e-lo)/rng)}
  var xy=pts.map(function(p){return [X(p.t),Y(p.equity)]});
  var line=smoothPath(xy);
  var last=pts[pts.length-1];
  var up=last.equity>=base;
  var color=up?'#4ade80':'#f87171';
  document.getElementById('mg-line').setAttribute('d',line);
  document.getElementById('mg-line').setAttribute('stroke',color);
  var area=line+' L'+xy[xy.length-1][0].toFixed(1)+' '+(H-PAD)+' L'+xy[0][0].toFixed(1)+' '+(H-PAD)+' Z';
  document.getElementById('mg-area').setAttribute('d',area);
  document.getElementById('mg-area').setAttribute('fill',color);
  var by=Y(base);
  var bl=document.getElementById('mg-base'); bl.setAttribute('y1',by); bl.setAttribute('y2',by);
  var lx=xy[xy.length-1][0], ly=xy[xy.length-1][1];
  ['mg-live','mg-ring'].forEach(function(id){var c=document.getElementById(id);c.setAttribute('cx',lx);c.setAttribute('cy',ly);c.setAttribute(id==='mg-live'?'fill':'stroke',color);});
  document.getElementById('mg-hi').textContent='▲ '+n(hi-pad);
  document.getElementById('mg-lo').textContent='▼ '+n(lo+pad);
  document.getElementById('mg-t0').textContent=hhmm(t0);
  document.getElementById('mg-t1').textContent=hhmm(t1)+' · '+pts.length+' pts';
  var span=(t1-t0)/3600000;
  document.getElementById('mg-span').textContent=span>=1?(span.toFixed(1)+'h'):(Math.round((t1-t0)/60000)+'min');
}
function loadMeta(){
  fetch('/v2/equity_history?max=600').then(function(r){return r.json()}).then(function(d){
    var pts=(d.points||[]).map(function(p){return {t:Number(p.t),equity:Number(p.equity),pnl:Number(p.pnl)}}).filter(function(p){return p.equity>0});
    if(pts.length) drawMeta(pts);
  }).catch(function(){});
}
function modeOf(p){var m=(p.position_mode||'').toUpperCase();
  if(m.indexOf('FUNDING')>=0||m.indexOf('ARBITRAGE')>=0||m.indexOf('TRIANGULAR')>=0||m.indexOf('DELTA')>=0||m.indexOf('EXTERNAL_GITHUB')>=0)return 'GRINDER';
  return 'SNIPER';}
function tick(){
  fetch('/api/simulation/status').then(function(r){return r.json()}).then(function(d){
    document.getElementById('mode').textContent=(d.mode||'').slice(0,30);
    document.getElementById('ro').textContent=d.read_only?'read_only':'??';
    var pnl=Number(d.net_pnl_usdt||0);var e=document.getElementById('pnl');e.textContent=(pnl>=0?'+':'')+n(pnl);e.style.color=col(pnl);
    document.getElementById('eq').textContent=n(d.equity_usdt);
    document.getElementById('wr').textContent=n(d.winrate_pct,0)+'%';
    document.getElementById('pos').textContent=(d.open_positions||0);
    document.getElementById('expo').textContent=n(d.open_exposure_usdt);
    document.getElementById('trd').textContent=(d.closed_trades||0);
    var eqo=d.equity||{};var av=Number(eqo.market_marks_available||0),mi=Number(eqo.market_marks_missing||0);
    var fd=document.getElementById('freshdot'),fr=document.getElementById('fresh');
    if(mi>0&&av===0){fd.className='dot fresh-bad';fr.textContent='marks manquants';fr.className='num fresh-bad';}
    else if(mi>0){fd.className='dot fresh-warn';fr.textContent=av+'ok/'+mi+'miss';fr.className='num fresh-warn';}
    else{fd.className='dot fresh-ok';fr.textContent=av+' ok';fr.className='num fresh-ok';}
    var ps=(d.positions||[]);var sniper={n:0,p:0},grinder={n:0,p:0};
    ps.forEach(function(p){var g=modeOf(p);var pp=Number(p.unrealized_pnl_usdc||p.pnl_usdc||0);if(g==='SNIPER'){sniper.n++;sniper.p+=pp;}else{grinder.n++;grinder.p+=pp;}});
    document.getElementById('m_sniper').innerHTML=sniper.n+' <span style="font-size:11px;color:'+col(sniper.p)+'">'+(sniper.p>=0?'+':'')+n(sniper.p)+'</span>';
    document.getElementById('m_grinder').innerHTML=grinder.n+' <span style="font-size:11px;color:'+col(grinder.p)+'">'+(grinder.p>=0?'+':'')+n(grinder.p)+'</span>';
    var fus=d.fusion_runtime||{};var fa=fus.funding_arb||{};
    document.getElementById('m_funding').textContent=(fa.open_pairs!=null?fa.open_pairs:0)+(fa.enabled?'':' (off)');
    var tb=document.getElementById('postb');tb.innerHTML='';
    document.getElementById('poslbl').textContent=ps.length+' ouvertes';
    ps.slice(0,12).forEach(function(p){var g=modeOf(p);var pp=Number(p.unrealized_pnl_usdc||p.pnl_usdc||0);var notl=Number(p.notional_usdt||p.copied_notional_usdt||0);var tr=document.createElement('tr');
      tr.innerHTML='<td>'+(p.coin||'?')+'</td><td style="color:'+(g==='SNIPER'?'var(--amber)':'var(--cyan)')+'">'+g+'</td><td class="num">'+n(notl)+'</td><td class="num" style="text-align:right;color:'+col(pp)+'">'+(pp>=0?'+':'')+n(pp)+'</td>';tb.appendChild(tr);});
    if(!ps.length)tb.innerHTML='<tr><td colspan="4" style="color:var(--dim)">aucune position ouverte</td></tr>';
    var pl=d.paper_ledger||{};var rec=pl.reconciliation||{};var exp=Number(rec.expected_equity_usdc||0),act=Number(rec.actual_equity_usdc||0),gap=Math.abs(exp-act);
    document.getElementById('health').innerHTML='realized <span style="color:'+col(Number(d.realized_pnl_usdt||0))+'">'+n(d.realized_pnl_usdt)+'</span> · unrealized <span style="color:'+col(Number(d.unrealized_pnl_usdt||0))+'">'+n(d.unrealized_pnl_usdt)+'</span><br>réconciliation <span style="color:'+(gap<0.01?'var(--pnl)':'var(--red)')+'">écart '+n(gap,6)+'</span> · '+(d.winning_trades||0)+'W/'+(d.losing_trades||0)+'L';
    var sc=d.scanner||{};var pe=(fus.paper_engine)||{};var summ=fus.external_profile_execution_summary||{};
    function node(ok,label,val){return '<span class="dot" style="color:'+(ok?'var(--pnl)':'var(--red)')+'">●</span>'+label+' <span style="color:var(--dim)">'+val+'</span>';}
    document.getElementById('wiring').innerHTML=[node(d.engine_running,'ws_scan',(sc.engine_running?'live':'off')),node((fus.status||'').indexOf('OK')>=0,'fusion',(fus.status||'—').slice(0,14)),node(true,'profils',(summ.profiles_executed!=null?summ.profiles_executed:'—')),node(true,'paper_engine',(pe.accepted_count!=null?pe.accepted_count:'—')),node(gap<0.01,'ledger',(pl.open_positions_count!=null?pl.open_positions_count+' pos':'—'))].join(' <span style="color:var(--dim)">━▶</span> ');
    document.getElementById('state').innerHTML='moteur <span class="dot" style="color:'+(d.engine_running?'var(--pnl)':'var(--red)')+'">●</span> '+(d.engine_running?'actif':'arrêté')+' │ serveur '+(d.server_running?'●':'○')+' │ fusion '+((fus.status)||'—');
    document.getElementById('clk').textContent=new Date().toLocaleTimeString();
  }).catch(function(){document.getElementById('state').textContent='serveur injoignable — /api/simulation/status';});
}
tick();setInterval(tick,2000);
loadMeta();setInterval(loadMeta,10000);
</script></body></html>"""


def create_dashboard_v2_router() -> APIRouter:
    router = APIRouter()

    @router.get("/v2", response_class=HTMLResponse)
    def dashboard_v2() -> HTMLResponse:
        return HTMLResponse(_PAGE)

    @router.get("/v2/equity_history")
    def equity_history(request: Request, max: int = 600) -> JSONResponse:
        """Courbe d'equity réelle et persistante (read-only) pour le metagraphe."""
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
