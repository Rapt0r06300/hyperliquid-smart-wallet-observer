"""Dashboard v2 — thème "hacker" (UI-1 validée, spec docs/design/DASHBOARD_V2_MOCKUP.html).

Router FastAPI SÉPARÉ, monté à /v2. Ne touche jamais le très gros routes.py.
Read-only strict: la page n'expose AUCUNE action, elle interroge seulement
/api/simulation/status (source = ledger canonique, règle UI-4 vérité). L'ancienne
UI reste disponible à / (aucune suppression). Chiffres bruts arrondis côté client.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

_PAGE = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HYPERSMART::observer_v2</title>
<style>
:root{--bg:#070b07;--pnl:#4ade80;--amber:#fbbf24;--cyan:#22d3ee;--red:#f87171;--dim:#5c705c;--txt:#d1e7d1}
*{box-sizing:border-box}
body{background:#050805;margin:0;padding:16px;font-family:ui-monospace,Consolas,monospace;color:var(--txt)}
@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
@keyframes fadein{from{opacity:0;transform:translateY(-2px)}to{opacity:1;transform:none}}
.wrap{background:var(--bg);border:1px solid #1c2a1c;border-radius:8px;padding:14px 16px;max-width:1000px;margin:auto}
.hd{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid #162216;padding-bottom:8px;margin-bottom:10px;flex-wrap:wrap;gap:4px}
.hd .t{color:var(--pnl);font-size:14px;letter-spacing:1px}.hd .s{font-size:11px;color:var(--dim)}
.num{font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dot{animation:pulse 2s infinite}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));gap:8px;margin-bottom:10px}
.cell{background:#0c140c;padding:7px 9px;min-width:0}.cell .l{font-size:10px;color:var(--dim);letter-spacing:1px}.cell .v{font-size:17px}
.panel{background:#0c140c;padding:10px;margin-bottom:10px}.lbl{font-size:10px;color:var(--dim);letter-spacing:1px;margin-bottom:6px}
table{width:100%;font-size:11px;border-collapse:collapse;table-layout:fixed}th{font-weight:400;color:var(--dim);text-align:left}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:8px;margin-bottom:10px}
svg{width:100%;height:84px;display:block}
.ev{animation:fadein .5s ease-out;line-height:1.8}
.fresh-ok{color:var(--pnl)}.fresh-warn{color:var(--amber)}.fresh-bad{color:var(--red)}
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
<div class="panel"><div class="lbl">┌ METAGRAPHE <span style="color:var(--dim)">equity·session live</span></div>
<svg id="mg" viewBox="0 0 620 84" preserveAspectRatio="none"><polyline id="mgline" fill="none" stroke="#4ade80" stroke-width="2" points=""/></svg></div>
<div class="two">
<div class="panel"><div class="lbl">┌ POSITIONS <span class="num" id="poslbl" style="color:var(--dim)"></span></div>
<table><thead><tr><th style="width:30%">coin</th><th style="width:22%">side</th><th style="width:24%">notional</th><th style="width:24%;text-align:right">pnl</th></tr></thead><tbody id="postb"></tbody></table></div>
<div class="panel"><div class="lbl">┌ SANTÉ <span style="color:var(--dim)">ledger·réconciliation</span></div>
<div class="num" id="health" style="font-size:11px;color:#8fa58f;line-height:2"></div></div>
</div>
<div class="panel"><div class="lbl">┌ ÉTAT <span style="color:var(--dim)">moteur / sources</span></div>
<div id="state" class="num" style="font-size:11px;color:#8fa58f;line-height:2"></div></div>
</div>
<script>
var hist=[];
function n(x,d){x=Number(x);return isNaN(x)?'—':x.toFixed(d==null?2:d)}
function col(v){return v>=0?'var(--pnl)':'var(--red)'}
function pad(x){return (x<10?'0':'')+x}
function draw(){
  if(hist.length<2){return}
  var lo=Math.min.apply(null,hist),hi=Math.max.apply(null,hist),rng=(hi-lo)||1;
  var pts=hist.map(function(v,i){var x=620*i/(hist.length-1);var y=78-72*(v-lo)/rng;return x.toFixed(1)+','+y.toFixed(1)}).join(' ');
  document.getElementById('mgline').setAttribute('points',pts);
}
function tick(){
  fetch('/api/simulation/status').then(function(r){return r.json()}).then(function(d){
    document.getElementById('mode').textContent=(d.mode||'').slice(0,34);
    document.getElementById('ro').textContent=d.read_only?'read_only':'??';
    var pnl=Number(d.net_pnl_usdt||0);
    var e=document.getElementById('pnl');e.textContent=(pnl>=0?'+':'')+n(pnl);e.style.color=col(pnl);
    document.getElementById('eq').textContent=n(d.equity_usdt);
    document.getElementById('wr').textContent=n(d.winrate_pct,0)+'%';
    document.getElementById('pos').textContent=(d.open_positions||0);
    document.getElementById('expo').textContent=n(d.open_exposure_usdt);
    document.getElementById('trd').textContent=(d.closed_trades||0);
    var eq=Number(d.equity_usdt||0);if(eq>0){hist.push(eq);if(hist.length>120)hist.shift();draw();}
    var eqo=d.equity||{};var av=Number(eqo.market_marks_available||0),mi=Number(eqo.market_marks_missing||0);
    var fd=document.getElementById('freshdot'),fr=document.getElementById('fresh');
    if(mi>0&&av===0){fd.className='dot fresh-bad';fr.textContent='marks manquants';fr.className='num fresh-bad';}
    else if(mi>0){fd.className='dot fresh-warn';fr.textContent=av+'ok/'+mi+'miss';fr.className='num fresh-warn';}
    else{fd.className='dot fresh-ok';fr.textContent=av+' ok';fr.className='num fresh-ok';}
    var tb=document.getElementById('postb');tb.innerHTML='';
    var ps=(d.positions||[]).slice(0,12);
    document.getElementById('poslbl').textContent=ps.length+' ouvertes';
    ps.forEach(function(p){
      var side=(p.side||p.direction||'').toUpperCase();
      var pp=Number(p.unrealized_pnl_usdc||p.pnl_usdc||0);
      var notl=Number(p.notional_usdt||p.copied_notional_usdt||0);
      var tr=document.createElement('tr');
      tr.innerHTML='<td>'+(p.coin||'?')+'</td><td style="color:'+(side==='LONG'?'var(--cyan)':'var(--amber)')+'">'+side+'</td><td class="num">'+n(notl)+'</td><td class="num" style="text-align:right;color:'+col(pp)+'">'+(pp>=0?'+':'')+n(pp)+'</td>';
      tb.appendChild(tr);
    });
    if(!ps.length){tb.innerHTML='<tr><td colspan="4" style="color:var(--dim)">aucune position ouverte</td></tr>';}
    var pl=d.paper_ledger||{};var rec=(pl.reconciliation)||{};
    var exp=Number(rec.expected_equity_usdc||0),act=Number(rec.actual_equity_usdc||0),gap=Math.abs(exp-act);
    document.getElementById('health').innerHTML=
      'realized <span style="color:'+col(Number(d.realized_pnl_usdt||0))+'">'+n(d.realized_pnl_usdt)+'</span><br>'+
      'unrealized <span style="color:'+col(Number(d.unrealized_pnl_usdt||0))+'">'+n(d.unrealized_pnl_usdt)+'</span><br>'+
      'réconciliation <span style="color:'+(gap<0.01?'var(--pnl)':'var(--red)')+'">écart '+n(gap,6)+'</span><br>'+
      'winrate '+n(d.winrate_pct,0)+'% ('+(d.winning_trades||0)+'W/'+(d.losing_trades||0)+'L)';
    var sc=d.scanner||{};
    document.getElementById('state').innerHTML=
      'moteur <span class="dot" style="color:'+(d.engine_running?'var(--pnl)':'var(--red)')+'">●</span> '+(d.engine_running?'actif':'arrêté')+
      ' │ serveur '+(d.server_running?'●':'○')+
      ' │ fusion '+((d.fusion_runtime||{}).status||'—');
    document.getElementById('clk').textContent=new Date().toLocaleTimeString();
  }).catch(function(){document.getElementById('state').textContent='serveur injoignable — /api/simulation/status';});
}
tick();setInterval(tick,2000);
</script></body></html>"""


def create_dashboard_v2_router() -> APIRouter:
    router = APIRouter()

    @router.get("/v2", response_class=HTMLResponse)
    def dashboard_v2() -> HTMLResponse:
        return HTMLResponse(_PAGE)

    return router


__all__ = ["create_dashboard_v2_router"]
