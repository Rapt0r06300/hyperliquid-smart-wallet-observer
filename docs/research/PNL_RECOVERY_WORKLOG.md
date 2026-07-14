# Journal de bord — récupération du PnL

Mis à jour à chaque phase. **Aucune promesse de PnL. On mesure d'abord.**

---

## PHASE 0 — Protéger et cartographier · ✅ FAIT

**Serveur live : non touché.** Aucun redémarrage, aucune modification de configuration en cours
d'exécution. Le ledger est lu **en lecture seule**, avec un décodeur tolérant aux fichiers en cours
d'écriture (`load_events`) — plutôt que de tuer le serveur pour figer une copie.

### 🔴 DÉCOUVERTE MAJEURE — les deux moteurs n'existent pas

Le brief part du principe que le bot a deux moteurs. **Vérification faite : c'est faux.**

- Le mot **« sniper » n'apparaît nulle part** dans le moteur. Il n'existe que dans **une ligne de
  JavaScript du dashboard** (`dashboard_v2.py`, fonction `modeOf`) qui devine le mode d'après le nom
  de la stratégie, **côté navigateur** :
  ```js
  return (m.indexOf('FUNDING')>=0 || m.indexOf('ARBITRAGE')>=0 || ...)?'GRINDER':'SNIPER';
  ```
- **Aucun champ `strategy_mode`** dans le ledger, dans les décisions, dans les positions.
- **Tous les trades passent par le même chemin** : fusion runtime → PaperEngine → adaptateur.

**Le Grinder et le Sniper sont une intention de conception, pas une implémentation.**
C'est pourquoi tous les audits précédents mélangeaient les deux : *il n'y avait rien à séparer.*

**Conséquence** : la piste n° 11 (« ajouter `strategy_mode` sur chaque décision ») n'est pas une
amélioration parmi d'autres — **c'est le prérequis de tout le reste**.

---

## PHASE 1 — Audit forensique · ✅ FAIT

Livré : **`tools/analyze_trading_pnl.py`** (lecture seule) →
`data/reports/trades_enriched.{csv,json}`, `pnl_forensics.json`, `grinder_vs_sniper.csv`,
`docs/research/PNL_FORENSIC_AUDIT.md`.

Il **recalcule le PnL depuis les prix et les tailles**, sans faire confiance au chiffre stocké.

### Résultat central

| | |
|---|---|
| PnL **brut** (le trading seul) | **−1,81 $** |
| **Frais** | **6,50 $** |
| PnL net | **−7,81 $** |

> **Les frais représentent 83 % de la perte.**
> Mouvement brut : **−3,6 bps** par trade (quasi nul — aucun edge).
> Frais : **+13,0 bps** par trade. **C'est le tueur.**

### Réconciliation

Le PnL **brut** se réconcilie à **0,0001 $ près** → la formule est **juste**.
L'écart résiduel est **entièrement** dû à un **bug comptable** :

> **Les frais d'ENTRÉE (0,05 $/trade) ne sont déduits nulle part.**
> `net_stocké = brut − frais de SORTIE` seulement.
> ⚠️ **Ne PAS « corriger » en les soustrayant** : ils doivent être *dans le prix d'entrée*.
> Les soustraire en plus serait un **double comptage**.

### Attribution des moteurs (sur la session en cours)

| moteur | trades | PnL net | verdict |
|---|---|---|---|
| **SNIPER** | 10 | −7,81 $ | tout le trading est du copy-trading |
| **GRINDER** | **0** | — | **le Grinder ne trade pas du tout** |

---

## PHASE 2 — Frais réels Hyperliquid · ✅ FAIT

**Bug trouvé grâce au chiffre fourni dans le brief.** Notre modèle croyait qu'un fill **maker
rapporte** 1 bps (`maker_rebate_bps = 1.0` → coût **négatif** : le bot était *payé* pour entrer, et
rempli à un prix **meilleur que le marché**).

**Tarif réel Hyperliquid** : taker **0,045 % = 4,5 bps**, maker **0,015 % = 1,5 bps** — **le maker
COÛTE**. Le rebate n'existe qu'aux paliers de volume élevés.

Erreur de **2,5 bps par exécution, dans le sens favorable**. Toute validation de la piste
« maker-first Post Only » (n° 22) aurait reposé sur une **illusion**.

**Corrigé** : `maker_fee_bps = 1.5`, `maker_rebate_bps = 0.0` (opt-in explicite).
Un test existant **affirmait le contraire** — il mentait, il est corrigé.
**Aller-retour taker = 9 bps**, exactement le chiffre du brief.

---

## Fichiers livrés à ce stade

| fichier | rôle |
|---|---|
| `src/hl_observer/strategies/strategy_mode.py` | attribution GRINDER/SNIPER (+ 11 tests) |
| `tools/analyze_trading_pnl.py` | audit forensique, lecture seule |
| `src/hl_observer/paper_trading/exec_model.py` | frais Hyperliquid réels |
| `src/hl_observer/risk/directional_exposure.py` | exposition nette + concentration (+ 15 tests) |
| `docs/research/PNL_FORENSIC_AUDIT.md` | rapport de l'audit |

**Commande de reproduction :**
```
python tools/analyze_trading_pnl.py
```

---

## PHASE 3 — `strategy_mode` posé à la SOURCE (piste 11) · ✅ FAIT

Le champ est désormais écrit **par le code qui ouvre et ferme réellement les positions**, et non
plus deviné après coup à l'analyse :

| chemin | ce qui est estampillé |
|---|---|
| entrée copie (`routes.py`) | position + événement `OPEN`/`INCREASE` |
| entrée directe (`fusion_persistent_adapter`) | position + événement `OPEN` |
| **funding-arb** (le Grinder) | `GRINDER` sur `OPEN`/`ACCRUAL`/`CLOSE` |
| SL/TP, auto-unstuck, halt rouge, close/reduce | **hérité de l'entrée** |

**Règle verrouillée par test** : *une sortie hérite du moteur de son entrée.* Reclasser une sortie
d'après son propre motif (`CATASTROPHIC_STOP`, `GRADED_HALT…`) ferait **fuir le PnL d'un moteur vers
l'autre** — exactement ce qu'on cherche à mesurer. Une position ouverte avant ce correctif est
marquée `UNKNOWN_LEGACY` : on ne l'invente pas.

---

## PHASE 4 — Pourquoi le Grinder ne trade pas · ✅ FAIT (2 causes)

### 🔴 Mon propre outil était aveugle au Grinder

Le funding-arb n'écrit **pas** des `OPEN`/`CLOSE` : il écrit `FUNDING_ARB_OPEN` / `ACCRUAL` /
`CLOSE`. Mon audit ne pairait que `OPEN`/`CLOSE` → **il n'aurait jamais vu un trade Grinder, même
s'il y en avait eu.** Conclure « 0 trade Grinder » avec un outil aveugle au Grinder n'est pas une
mesure. **Corrigé** — et re-mesuré proprement : **0 événement `FUNDING_ARB_*`** dans le ledger. La
conclusion tenait, la méthode non.

### Cause A — le Grinder était éteint hors du `.cmd`

`HYPERSMART_FUNDING_ARB_PAPER` et le poller n'existaient que dans `LANCER_HYPERSMART.cmd`.
Or **le `.ps1` est l'autorité**. Lancé directement, le Grinder était **purement éteint**.
Même famille que la double source de vérité déjà corrigée. → **flags alignés dans le `.ps1`.**

### Cause B — un seuil d'entrée peut-être MORT (non mesuré)

```
min_entry_edge_bps_per_hour = 2.5     # « ~20 bps/8h (repo 32 : minEdge 20) »
```

Le repo d'origine visait une place où le funding tombe **toutes les 8 heures**. Hyperliquid paie
**toutes les heures**. Si le funding horaire réel reste très en dessous de 2,5 bps, c'est un
**VERROU MORT** : 0 trade garanti par construction — la même signature que le plafond de dégradation
à 12 bps posé sous un coût plancher de 14,2.

> ⚠️ **Je n'ai pas pu le mesurer** : pas d'accès réseau depuis mon environnement.
> **Je n'ai donc rien changé.** Baisser un seuil sans la donnée serait exactement la faute que je
> reproche au code. → outil livré : `python tools/measure_funding_gate.py` (à lancer sur ta machine).

---

## PHASE 5 — §1 Vérité du PnL · ✅ FAIT — **et je m'étais trompé**

### 🔴 Le « bug comptable » que j'avais annoncé n'existe pas

J'avais écrit : *« les frais d'entrée ne sont déduits nulle part »*. **C'était faux.**

Le prix d'entrée stocké **EST** le prix de fill : `paper_engine.py` pose
`entry_price = exec_result.fill_price` et le déclare noir sur blanc
(`embedded_cost_model = "fill_price_includes_spread_slippage_fee_latency"`). Le coût d'entrée est
donc **déjà dans le prix** — il ronge le brut. Le champ `fee_cost_usdc` de l'OPEN n'est qu'un
**report**, pas une seconde ponction. Le bot ne débite jamais `realized` à l'ouverture, et
`status_routes` passait déjà `fees_paid_usdc=0.0` — *« to avoid subtracting them twice »*.

**C'est mon outil qui comptait deux fois**, et qui **noircissait** le PnL de 0,50 $ sur 10 trades.
*Noircir un PnL est aussi malhonnête que le flatter.* Corrigé + verrouillé
(`tests/test_pnl_no_double_counting.py`) + drapeau `fee_already_embedded_in_entry_price` posé sur
chaque OPEN pour que plus personne ne retombe dedans.

### La deuxième fausse alerte

Les « 7 positions jamais fermées » n'étaient pas des orphelines : le serveur **tourne**, ce sont
des positions **ouvertes**. Crier à l'anomalie sur un état normal noie les vraies anomalies.

**Après correction : écart de réconciliation 0,0013 $, ZÉRO anomalie comptable.**
**Le ledger était juste.** C'est l'audit qui inventait des bugs.

---

## PHASE 6 — §2 Deux moteurs, deux PnL · ✅ FAIT

`src/hl_observer/strategies/engine_pnl.py` (+ 15 tests) : PnL net, brut, frais, funding, winrate,
**profit factor** et courbe d'équité — **par moteur**. Câblé dans le rapport de statut, donc visible
au dashboard et à l'audit (`tests/test_engine_pnl_wired.py` : un module orphelin ne sert à rien).

Trois garde-fous qui comptent :

- **La sortie hérite de l'entrée** — y compris dans le ledger historique. Une clôture SL/TP ne
  porte aucune trace du moteur ; la classer sur son propre texte renverrait `UNKNOWN` partout.
- **Un moteur inactif est NOMMÉ** (`moteurs_inactifs`), jamais absent en silence. *C'est exactement
  ainsi que le Grinder est resté éteint sans que personne le voie.*
- **`frais_en_part_du_brut`** — le diagnostic du Grinder en un chiffre. Au-dessus de 1, les frais
  dévorent tout le mouvement : aucun réglage de signal ne peut sauver ça.

### Mesure sur le ledger live réel

| moteur | trades | net | brut | frais | WR | PF | frais/brut |
|---|---|---|---|---|---|---|---|
| **GRINDER** | **0** | — | — | — | — | — | — |
| SNIPER | 10 | −7,81 $ | −1,81 $ | 6,00 $ | 20 % | 0,42 | **3,3×** |

> **Les frais valent 3,3× le mouvement brut.** 10 trades ne prouvent rien statistiquement — mais ce
> ratio, lui, est structurel, pas un accident d'échantillon.

---

## Prochaines étapes

1. **Relancer** — le nouveau code n'est actif qu'au redémarrage (`LANCER_HYPERSMART.cmd`).
   Au démarrage : `strategy_mode` posé, PnL séparé par moteur, carnet L2 + funding enregistrés,
   Grinder allumé.
2. **`python tools/measure_funding_gate.py`** — verdict sur le seuil : verrou mort, ou pas ?
3. Seulement ensuite : ajuster le seuil **sur la donnée**, puis les expériences contrôlées (§3-§9,
   qui restent `DATA_MISSING` tant que le carnet L2 et le funding ne sont pas enregistrés).

---

## Limites et honnêteté

- La session analysée ne compte que **10 aller-retours** : **aucune conclusion statistique** n'est
  possible sur cet échantillon. Les chiffres décrivent *cette* session, ils ne prouvent rien.
- Les pistes nécessitant le **carnet L2**, le **funding historique** ou les **timestamps de
  décision/ordre/fill** sont marquées `DATA_MISSING` — le bot ne les enregistre pas encore.
- **Aucune recherche web n'a été effectuée dans cette phase** (Phase 5 non entamée) :
  `SOURCE_INACCESSIBLE` serait mensonger, `NON_ENTAMÉ` est exact.

*Simulation paper uniquement. Aucun ordre réel, aucun argent réel.*
