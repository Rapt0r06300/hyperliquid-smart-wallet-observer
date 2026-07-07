# Fusion #14 — tradingview/lightweight-charts

**Repo:** https://github.com/tradingview/lightweight-charts — librairie de graphiques financiers HTML5 canvas, ~35KB, Apache-2.0, très populaire (TradingView). Pur frontend.
**Rôle:** visualisation. **Aucune** capacité de trading — c'est une lib de rendu.

## Ce que c'est
- Rendu canvas haute performance de séries financières: candlestick, bar, line, area, baseline, histogram.
- Time scale, price scale, crosshair, markers, lignes de prix, watermarks.
- **Temps réel** via `series.update(point)` (push tick par tick) et `series.setData([...])` (snapshot).
- API impérative légère, pas de dépendance lourde (pas de React requis), thème clair/sombre.

## KEEP (dashboard read-only, données RÉELLES uniquement)
1. **Remplacer/compléter notre rendu de graphes par lightweight-charts** dans le dashboard:
   - Courbe d'**equity paper** et **drawdown** dans le temps (depuis PaperEngine).
   - **Candlesticks du marché réel** (depuis `candleSnapshot` dYdX Indexer) avec **markers** aux instants de nos paper-entries/exits → on *voit* si la copie a ouvert au bon moment vs le marché réel.
   - Histogramme de volume / RVOL sous le prix.
2. **`series.update()` pour le live**: alimenté par notre tick read-only `/api/simulation/status` (déjà léger). Push incrémental = pas de re-fetch lourd → règle direct le souci "écran qui saute / overview lent".
3. **Markers d'évènements lifecycle** (OPEN/ADD/REDUCE/CLOSE) posés sur la série de prix réelle: lecture immédiate de la cohérence du lifecycle.
4. **Price lines** pour entry/avg/liquidation paper → lecture du risque simulé.

## ADAPT
- Brancher la source de données sur l'Indexer dYdX (candles réelles) + état paper local. **Jamais de données synthétiques**: si pas de candles, série vide + état honnête "données indisponibles" (notre règle no-demo).

## BAN
- Rien à bannir niveau sécurité (lib de rendu, pas d'I/O réseau de trading). Seule discipline: **ne jamais inventer de points** pour "remplir" un graphe vide.

## DEFER
- Plugins avancés (séries custom, primitives) → plus tard si besoin.

## OR OUBLIÉ (pépites V9)
- **Markers superposés prix-réel × évènements-paper** = l'outil de débogage visuel le plus puissant pour valider "la simulation reflète-t-elle le marché réel ?". On *voit* le lag de copie, les entrées sur spread large, les closes orphelins.
- **Update incrémental (`series.update`) au lieu de re-render complet** = pattern anti-jank qui s'aligne avec nos corrections front (self-chaining refresh, tick léger). À généraliser à tout le dashboard temps réel.
- Rendu canvas (pas DOM) → tient des milliers de points sans ramer → permet d'afficher tout l'historique backtest/replay sans pagination visuelle.
