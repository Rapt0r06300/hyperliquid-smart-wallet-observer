# MOTEUR LIQUIDATIONS — DÉCISION PRODUIT (2026-07-21)

> **Verdict : `RESEARCH_NEW_UNIVERSE`** — ne pas retirer le moteur, ne pas le réactiver.
> Changer la population observée, puis re-mesurer.

## 1. L'état réel, contre ce que disait le README

Le README annonçait « **0 événement** ». C'est faux : `runtime/data/liquidation_map.sqlite3`
contient **231 grappes** enregistrées sur **31,6 h** (table `grappe_snapshots` :
`ts_ms, session_id, coin, prix, sens, notionnel_usd, n_wallets`).

**La collecte fonctionne.** Ce qui manque est un **mécanisme de décision** : aucune de ces
231 observations n'a jamais alimenté une porte. C'est un module `WIRED_NOT_USED`, pas un
module aveugle.

## 2. Pourquoi il ne produit rien : la population observée

Les wallets suivis viennent de la découverte « smart money » — des comptes **peu leveragés**.
Or une liquidation exige du **levier élevé**. On observe la mauvaise population : on cherche
des chutes chez des gens qui ne montent pas sur l'échelle.

## 3. Les trois options, évaluées

### A — Arrêter la recherche · `RETIRE_ENGINE`
- **données requises** : aucune · **coût** : nul · **edge théorique** : nul
- **risque** : perdre la seule piste où *le vendeur ne choisit pas de vendre* — un liquidé
  est **forcé**. C'est structurellement la source d'edge la plus propre du marché.
- **verdict** : rejeté. Le coût de garder la collecte est quasi nul (231 lignes / 31,6 h).

### B — Changer l'univers de wallets · `RESEARCH_NEW_UNIVERSE` ✅
- **données requises** : découvrir des comptes à **fort levier** (ratio marge/notionnel via
  `clearinghouseState`, déjà collecté par notre pipeline) au lieu de comptes performants ;
- **taux d'événement attendu** : inconnu, mais **structurellement supérieur** — c'est
  précisément la variable qu'on ne filtrait pas ;
- **coût de collecte** : faible, on réutilise la boucle existante en changeant le critère ;
- **qualité de la donnée** : bonne (positions publiques, prix de liquidation calculable) ;
- **capacité de validation** : on peut mesurer le markout après liquidation, comme pour le
  copy — méthodologie déjà en place ;
- **risque** : le signal peut être déjà arbitré par des acteurs plus rapides. La loi `latence`
  dit que la vitesse ne nous a jamais servi ; il faudra donc mesurer si l'edge survit à des
  horizons où nous existons.

### C — Détecter depuis le marché, sans wallets · `REDESIGN_ENGINE`
- détecter les **conditions** de liquidation (cascade de prix, pic de volume, mèche) plutôt
  que les comptes ;
- **données requises** : L2 + trades haute fréquence, déjà partiellement collectés ;
- **avantage** : aucune découverte de wallets nécessaire ;
- **inconvénient** : on détecte l'événement **pendant** qu'il se produit — donc on arrive
  après ceux qui l'ont anticipé. Ça ressemble beaucoup au problème du copy contrarien.
- **verdict** : à garder en second, après B.

## 4. Décision

**`RESEARCH_NEW_UNIVERSE`.** Trois étapes, dans l'ordre, aucune réactivation avant la fin :

1. **découvrir** une population à fort levier (critère : marge/notionnel), sans rien changer
   au moteur ;
2. **mesurer** le taux d'événement réel sur cette population pendant ≥ 7 jours ;
3. **mesurer le markout** après liquidation aux horizons où nous pouvons agir. Si l'edge net
   après coûts n'est pas positif, le moteur passe `RETIRE_ENGINE` et devient une loi mesurée.

**Condition de réactivation, écrite maintenant** : ≥ 50 événements de liquidation observés
**et** un markout net positif hors échantillon. En dessous, le moteur reste suspendu — quel
que soit l'enthousiasme du moment.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
