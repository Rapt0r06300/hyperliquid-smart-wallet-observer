# RUNBOOK — Collecter les données, puis mesurer (liquidations + replay + carry)

**But :** on est arrivés au point où le prochain gain n'est plus du code, mais de la **donnée**.
Ce runbook explique, en clair, comment faire tourner le bot pour accumuler les données, puis
lancer les mesures honnêtes (#3 liquidations, replay A/B, carry). **100 % simulation, 0 ordre réel.**

---

## Étape 1 — Lancer le bot (accumule décisions + replay + liquidations)

Double-clique **`LANCER_HYPERSMART.cmd`**. Il démarre l'observation Hyperliquid en lecture seule,
le paper-trading, et l'enregistrement :

- les **liquidations** vont dans `runtime/data/liquidation_map.sqlite3` (table `grappe_snapshots`) ;
- le **replay** (candidats + marks de prix) va dans `runtime/replay/` (shards par-PID) —
  **pense à mettre `HYPERSMART_V26_RECORD_CANDIDATES=1`** pour que les marks s'enregistrent ;
- les décisions et le PnL paper vont au **ledger** (source unique).

Laisse la fenêtre **ouverte**. Plus ça tourne longtemps, plus les mesures seront fiables.

## Étape 2 — Lancer le feeder carry (en parallèle)

Double-clique **`ALIMENTER-CARRY-AUTO.cmd`**. Toutes les 10 min il mesure les 8 coins perp∩spot et
écrit `runtime/data/carry_spot_inputs.json`. Aujourd'hui il affiche souvent **0 VIABLE** — c'est
**honnête** : le funding est au plancher. Le carry s'activera au prochain pic (le z-score A4 le
capte). Depuis peu, l'exclusion « base aberrante » est **auditable** : elle montre le spot matché
et l'écart de prix (tu vois que c'est l'absence de vrai spot, pas un bug).

## Étape 3 — Combien de temps ?

Ordre de grandeur honnête : **quelques jours** de fonctionnement continu. Les repères concrets :

- **Liquidations** : vise **≥ 50 événements mesurables** (sinon la mesure #3 dit `INSUFFISANT`).
- **Replay** : vise **≥ 200 candidats et ≥ 500 marks** (seuils du docteur replay).

## Étape 4 — Vérifier la santé des données AVANT de conclure

```
REM  Santé du replay (candidats/marks agrégés, couverture)
python -c "from hl_observer.backtesting.replay_doctor import diagnostiquer_base, format_rapport; print(format_rapport(diagnostiquer_base('runtime/replay')))"

REM  Combien de liquidations a-t-on ?
python -m hl_observer.market.liquidation_recorder --root .
```

Tant que c'est `INSUFFISANT`, on **ne conclut pas** — on laisse tourner. (Règle dure : un résultat
sur des données absentes est un mensonge — c'est ce qui avait produit le faux « 1 sur 1M ».)

## Étape 5 — Mesurer (quand les données sont suffisantes)

```
REM  #3 — la dernière piste non testée : y a-t-il un edge à fader les liquidations ?
python tools\mesurer_edge_liquidation.py --root . --horizon-s 1800 --cout-bps 12

REM  Replay A/B — l'effet réel des filtres V26 (le docteur refuse si données insuffisantes)
python -m hl_observer.backtesting.ab_flag_replay --candidates runtime\replay\_merged\candidates.jsonl --marks runtime\replay\_merged\marks.jsonl
REM  (produire d'abord _merged/ : python -m hl_observer.runtime.replay_recorder --base runtime\replay)
```

Verdicts possibles de la mesure #3, tous **honnêtes** :
- `EDGE_NET_POSITIF` (net moyen > 0 **et** profit factor > 1 **et** ≥ 50 événements) → piste à creuser sérieusement ;
- `PAS_D_EDGE` → on l'enterre proprement, comme copy-trading et market-making ;
- `INSUFFISANT` → pas assez de données, on continue de collecter.

## Étape 6 — La vérité complète = Windows

La suite de tests complète tourne sous Windows : **`TEST-AUDIT-complet.cmd`** (le sandbox n'a ni
réseau ni UTF-8 fiable). Lance-la après chaque session de mesure pour t'assurer que rien n'a régressé.

---

### Ce qu'on saura à la fin

Soit les liquidations donnent un **edge net réel** (et on aura une 2ᵉ piste positive à côté du
carry), soit **non** (et on l'enterre honnêtement). Dans les deux cas, on aura **la vérité mesurée**,
pas une promesse. C'est ça qui protège l'argent de tes parents.

*Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.*
