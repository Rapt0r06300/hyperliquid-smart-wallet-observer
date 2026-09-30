# SOURCE DE VÉRITÉ UNIQUE DU PnL (2026-07-21)

## 1. La couche faisant autorité

**`runtime/data/carry_paper_ledger.jsonl`** — journal append-only d'événements
(`OPEN` / `CLOSE` / `RENFORT`), une ligne par action, jamais réécrite.

`carry_positions_store.resume_depuis_ledger()` est la **seule** fonction qui agrège le
réalisé. Dashboard, rapport quotidien, backtests et audits l'appellent tous. Aucun compteur
parallèle n'a le droit d'exister.

## 2. Les six quantités, et pourquoi elles ne se mélangent jamais

| champ | nature | entre dans le PnL stable ? |
|---|---|---|
| `realized_net_pnl_usdc` | comptable — sorti des `CLOSE`, frais d'entrée + sortie + correction de base inclus | **oui** |
| `net_funding_settled` | comptable — sommets d'heure **réellement franchis** | **oui** |
| `funding_accrual_estimate` | **estimation** — fraction d'heure non encore réglée | **non** |
| `base_mtm_usd` (latent de base) | **réversible** — marqué au MID | **non** |
| `notional_ouvert_usdt` / `marge_ouverte_usdt` | exposition, pas un résultat | non |
| `renforts` / `notional_renforce_usdt` | action sans réalisation | non |

```
stable_net_pnl = realized_net_pnl_usdc + net_funding_settled
```

## 3. Le défaut corrigé (P0)

`accruer()` crédite un **prorata linéaire** : `funding_bps_h × Δt`. Hyperliquid règle au
**sommet de chaque heure**, sur la position tenue à cet instant. Une position ouverte depuis
20 minutes se voyait créditer 1/3 d'heure de funding, alors qu'elle a reçu **soit un paiement
entier, soit rien**.

`paper_trading/funding_settlement.py` découpe désormais l'accru en **réglé** et **estimé**.
La somme des deux vaut **exactement** l'accru historique — la migration est neutre, aucune
valeur créée ni détruite (test `test_la_somme_est_CONSERVEE_la_migration_est_neutre`).

Effet mesuré sur le portefeuille vivant : sur **+0,3247 $** d'accru affiché, **+0,3226 $**
étaient réglés et **+0,0025 $** ne l'étaient pas — soit **0,8 %**. Faible en valeur, mais
c'était une **erreur de catégorie** : une estimation présentée comme un fait comptable, et
l'erreur croît avec le notionnel.

## 4. Le dashboard ne recalcule plus

- endpoint `/v2/carry` : expose `net_funding_settled`, `funding_accrual_estimate`,
  `stable_net_pnl` — tous produits par `etat_carry`, aucun recalcul côté navigateur ;
- deux cases distinctes à l'écran (« funding encaissé (réglé) », « funding estimé (en cours) ») ;
- le **ticker anime l'estimé** — le réglé saute d'un cran à chaque sommet d'heure, il ne
  s'anime pas. Une valeur qui coule en continu ne peut pas être un règlement discret.

Un test de non-régression interdit désormais au net stable de réabsorber l'accrual
(`test_la_chaine_MID_est_cablee_feeder_entree_endpoint_et_poll`, durci v3 → v4).

## 5. Reste à faire

- `P0-2` : le MtM de base est encore composé **dans l'endpoint**. Il doit descendre dans une
  couche commune pour que rapport et dashboard partagent le même code, pas seulement la même
  source.
- `P0-4` : 8 scénarios de PnL manquants (hedge insuffisant, fermeture partielle, mapping
  UBTC/BTC, arbitrage 2 jambes, copy LONG/SHORT, fill dupliqué, snapshot répété, donnée absente).

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
