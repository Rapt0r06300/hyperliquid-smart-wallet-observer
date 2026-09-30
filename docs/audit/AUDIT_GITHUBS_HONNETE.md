# Audit honnête des GitHubs — ont-ils vraiment un PnL positif prouvé ? (2026-07-10)

> Question de Flo : « les repos sont déjà accomplis (PnL positif, fort grinder), pourquoi pas nous ?
> a-t-on loupé quelque chose ? » — Réponse **avec preuves**, relecture des 39 repos + de leurs claims.

## Verdict : AUCUN repo n'a de preuve de PnL réel soutenu

J'ai cherché dans les 39 repos des **résultats live audités** (equity, track record, backtest gagnant
vérifiable). Trouvé : **rien** — sauf, ironiquement, des docs `equity_hard_stop_loss` (= comment
*limiter les pertes*). Ce que les repos ont vraiment, par catégorie :

**1. Des frameworks (freqtrade #22, octobot #23, hummingbot #33, passivbot #35).**
Ce sont des *outils* pour faire tourner des stratégies — ils ne fournissent **aucune stratégie
gagnante**. Avoir freqtrade ≠ être rentable, comme avoir Photoshop ≠ être peintre.

**2. Le "grinder" = grid/martingale (passivbot #35). C'est LUI que tu as vu comme "fort grinder".**
Sa propre doc le décrit : *« inspiré de la martingale, le robot fait une petite entrée et **double la
mise sur ses positions perdantes** »*. Il grince plein de petits gains en marché *range* → courbe
d'equity magnifique et lisse… **jusqu'à ce qu'une tendance rende une position "stuck"** : il double
dans la perte et prend un drawdown catastrophique (d'où ses multiples docs `equity_hard_stop_loss` :
le mode d'échec, c'est vider le compte). Et ses "configs optimales" viennent d'un *« optimiseur
évolutionnaire sur des milliers de backtests »* = **exactement le surapprentissage** qu'on a prouvé
(robust=0). Le backtest est superbe, le live déçoit. C'est **ramasser des pièces devant un rouleau
compresseur** : le PnL lisse est réel mais *emprunté au futur*.

**3. Copy-trading (#15–21) = frameworks + démos.** Le fameux « $41,200 PnL » de #17 est une **image
GIF de démo** (« Live Mirror Execution *Sample* ») — **aucun fichier de résultat réel** dans le repo.
« Not mocked » parle du *format* de l'UI, pas d'un gain réellement encaissé. Marketing.

**4. Arbitrage (#28–31, #34, #36, #37) = détection, pas profit.** #28/#29 le disent noir sur blanc :
*« real-time arbitrage **detection and monitoring** system, **not a guaranteed profit engine** »*.
#30 (« professional-grade ») : *« **operating the bot with real funds is highly discouraged**… you use
this software entirely at your own risk »*. L'arb « sans risque » en théorie est une **course à la
latence** que les pros gagnent ; les écarts sont minuscules et fugaces.

**5. Prediction markets (Polymarket, #01–27) = autre domaine.** Arb binaire (YES+NO < $1) à
**$0.01–0.03 la part**, qui exige d'être plus rapide que les autres. Rien à voir avec notre copy HL.

## Donc : on n'a rien "loupé" — on est plus honnête que leurs READMEs

Notre `robust=0` **est** ce que ces stratégies donnent quand on les teste en **hors-échantillon avec
coûts réels** — ce que leurs backtests optimisés évitent soigneusement de faire. Ils montrent le
train (le passé ajusté) ; nous, on a regardé le test (le futur). C'est toute la différence.

## La seule ouverture honnête

Le **market-making / grid** (l'archétype passivbot) est une **classe de stratégie différente** du
copy-trading — c'est le vrai "grinder". Il n'est pas *faux* : il grince réellement. Mais son edge est
petit, **dépendant du régime** (meurt en tendance) et porte un **risque de queue** que la courbe lisse
cache. Si tu veux l'explorer, on peut le tester dans notre cadre paper **avec le tail-risk modélisé
honnêtement** (pas son backtest optimisé). **Zéro promesse** — le résultat honnête pourrait être
« gagne en range, explose en tendance, ≈ neutre après le risque de queue ».

## Sécurité
✅ 0 ordre réel · 0 argent · 0 clé · 0 signature. Lecture seule.
