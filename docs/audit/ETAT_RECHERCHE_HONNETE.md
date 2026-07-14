# État de recherche honnête — HyperSmart Observer (2026-07-10)

> Résumé honnête de ce qu'on a testé, mesuré et appris. **Aucune promesse de PnL, aucun chiffre
> maquillé.** Tout est paper / lecture seule : 0 ordre réel, 0 argent, 0 clé, 0 signature.

## 1. La question de départ
Peut-on générer un PnL paper positif réaliste en **copiant les smart-money wallets d'Hyperliquid** ?

## 2. Verdict MESURÉ : non, pas avec ces signaux (copy-trading)

| Test | Méthode | Résultat |
|---|---|---|
| Calibrage | 1 425 000 scénarios, split OOS + gate + plateau | **robust = 0** |
| Segments | 18 tranches × 4 sorties, hors-échantillon | **0 tranche positive OOS** |
| Maker | fills sur vrais chemins de prix | 16 % de fill, **sélection adverse**, −$117 (pire que taker) |
| Monte-Carlo | bootstrap 3000× | le quasi-breakeven **chevauche zéro** = bruit |

**Cause structurelle** (pas un bug) : on voit le trade du leader avec ~quelques secondes de retard →
dégradation de copie **~13 bps** à chaque trade. Après frais + spread + cette dégradation, l'edge net
médian est **négatif**. Aucune astuce de calibrage ou d'exécution ne crée un edge qui n'existe pas.

## 3. Ce qui a été RÉELLEMENT construit (le vrai livrable)

Un système de recherche quant complet et honnête :
- collecte Hyperliquid **read-only** + firehose WS + recording replay incassable (par-process, atomique) ;
- moteur de **replay** (15 dimensions, DB jusqu'à 150M scénarios, streaming borné mémoire/temps) ;
- **validation anti-surapprentissage** : split temporel OOS, gate de déploiement, plateau, Monte-Carlo ;
- modélisation de **coûts réels** (frais, spread, slippage, dégradation de copie) + **maker-fill** sur vrais prix ;
- **garde-fous no-real-trade** vérifiés par test (aucun ordre réel possible) ;
- robustesse : fermeture propre (tree-kill), anti-orphelins, fix mid-coverage.

C'est une vraie compétence d'ingénieur quant — un système qui **refuse de se mentir**. C'est ça, le
livrable à valoriser (portfolio, apprentissage), indépendamment du PnL.

## 4. La seule piste structurellement DIFFÉRENTE : funding (delta-neutral)

La machinerie existe déjà et elle est honnête (`funding/funding_arb_paper.py`, `funding_edge.py`) :
encaisser le **funding** d'un perp en étant **couvert** (delta-neutral) — tu n'as **pas** à battre
quelqu'un à la course, tu es *payé pour tenir*.

**Économie honnête** : `net = |taux/h| × heures_détention − coûts_aller-retour (2 jambes)`.
- Break-even ≈ funding **> ~0.5–0.75 bps/h** soutenu (pour couvrir ~6 bps de coûts sur ~8 h).
- Or le funding Hyperliquid est souvent **trop faible** (~0.1–0.3 bps/h) → le modèle refuse (NO_TRADE).
- Il devient net-positif **seulement** quand le funding est élevé (marché déséquilibré) — **épisodique
  et compétitif**. Structurellement plus sain que le copy-trading, mais **marge fine, zéro promesse**.

**Blocage actuel** : **aucune donnée funding n'est enregistrée** → impossible de backtester
aujourd'hui. Pour l'évaluer *honnêtement* : (1) enregistrer l'historique des taux de funding sur un
run propre, (2) le rejouer avec `funding_arb_paper`, (3) juger en OOS comme pour le reste.

## 5. Recommandations honnêtes

1. **Ne mets pas d'argent réel dans ce bot.** C'est la conclusion la plus importante — elle te protège.
2. **Le vrai livrable, c'est le système + ces conclusions.** Montre-le pour ce que c'est.
3. Si tu veux continuer à *construire* : la seule avenue honnête restante est **funding** — mais il
   faut d'abord **collecter les données**, puis mesurer, sans rien promettre.
4. Faire une **pause** est parfaitement légitime.

## Sécurité (inchangée)
✅ 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait. Read-only + paper-only.
