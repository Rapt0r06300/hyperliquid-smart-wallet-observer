# PROJECT GROUND TRUTH — HyperSmart Observer (2026-07-21)

> **Ce document ne recopie aucune affirmation.** Chaque ligne a été confrontée au code, au
> runtime, aux logs ou aux tests, et porte son statut de preuve. Quand la doc et le code se
> contredisent, **le code gagne** et la contradiction est écrite noir sur blanc.
>
> Commandes de reproduction en fin de document.

## Légende des statuts

`PROVEN_BY_CODE` · `PROVEN_BY_RUNTIME` · `PROVEN_BY_LOGS` · `PROVEN_BY_TEST` ·
`PROVEN_BY_REPLAY` · `DOC_ONLY` · `CONTRADICTED` · `PARTIALLY_PROVEN` · `DATA_MISSING` ·
`OBSOLETE`

---

## 1. Identité et doctrine

| Affirmation (README) | Statut | Preuve |
|---|---|---|
| Local, read-only, paper-only, simulation-only, deny-by-default | `PROVEN_BY_TEST` | `tests/test_no_real_trade_foundations.py` (32 verts), `python -m hl_observer safety-audit` |
| Aucun ordre réel, aucune signature, aucune clé privée | `PROVEN_BY_TEST` | idem + aucun endpoint `/exchange` opérationnel dans `src/` |
| Aucun exécuteur mainnet **ou testnet** actif | `PROVEN_BY_CODE` | aucun `TestnetExchangeAdapter` instancié sur un chemin de production |
| Pas de LLM dans le hot path décisionnel | `PROVEN_BY_CODE` | `research/local_llm_explainer.py` hors chemin de décision |
| Runtime principal = `src/hl_observer/` | `PROVEN_BY_RUNTIME` | c'est ce que lance `LANCER_HYPERSMART.cmd` |
| `hyper_smart_observer/` + `dydx_v4/` = legacy non lancés | `PROVEN_BY_TEST` | `tests/test_hyperliquid_runtime_does_not_import_dydx_by_default.py` |
| Launcher officiel `LANCER_HYPERSMART.cmd` | `PROVEN_BY_RUNTIME` | présent, référence le port 8794 |
| UI locale `http://127.0.0.1:8794/v2` | `PROVEN_BY_CODE` | port 8794 dans le launcher ; route `/v2` dans `ui/dashboard_v2.py` |

**Rien à corriger sur la doctrine.** Elle est tenue par des tests, pas par une promesse.

---

## 2. Le nombre de modules — `CONTRADICTED`

Le README écrit « **Quatre modules** » puis liste **cinq** lignes (Carry, Copy, Arbitrage,
Cross-venue, Liquidations).

**Vérité mesurée** : cinq mécanismes existent, dont **un seul ouvre des positions** :

| mécanisme | ouvre des positions ? | preuve |
|---|---|---|
| Carry delta-neutre | **oui** | 54 OPEN / 42 CLOSE au ledger |
| Arbitrage de dislocation | **oui, 1 fois** | 1 OPEN au ledger, 0 CLOSE |
| Copy-trading | non (verrouillé) | 0 ligne au ledger |
| Cross-venue funding | non (mesure) | aucune position par construction |
| Liquidations | non (suspendu) | 231 grappes observées, 0 décision |

Formulation exacte à retenir : **« un moteur en production paper (Carry), un moteur en guet
qui a ouvert une fois (Arbitrage), un moteur verrouillé (Copy), une mesure en cours
(Cross-venue funding), un moteur suspendu (Liquidations). »**

---

## 3. Carry delta-neutre

| Affirmation | Statut | Mesure |
|---|---|---|
| Actif, seule source de PnL positif | `PARTIALLY_PROVEN` | 11 positions vivantes ; **réalisé cumulé −6,05 $** (dette de l'ère churn, 19/07) ; funding couru +0,32 $. Le **taux** est positif (+0,35 $/j), le **cumul** ne l'est pas encore. Le README dit « seule source de PnL positif » : vrai comme *taux courant*, faux comme *cumul*. À reformuler. |
| ~20 coins scannés | `PROVEN_BY_RUNTIME` | journal de scans : **20 coins**, 7 passes |
| ~7 viables | `PROVEN_BY_RUNTIME` | shortlist live : **8** viables à l'instant de la mesure (7 à la passe précédente) — fourchette 6-8, varie par passe |
| Réserve 20 %, plafond 40 %/coin | `PROVEN_BY_CODE` | `RESERVE_FRAC_DEFAUT=0.2`, `PART_MAX_PAR_COIN=0.4` |
| Prise de profit à +0,05 $ net | `PROVEN_BY_CODE` | `SEUIL_PRISE_PROFIT_USD=0.05` |
| Levier selon risque observé | `PROVEN_BY_CODE` | `_meilleur_levier` × `SECURITE_LIQUIDATION=1.5` sur la pire hausse 200 j |
| Univers étendu aux tokens Unit | `PROVEN_BY_CODE` | `_apparier_spots` (préfixe ≥ 3 lettres) — **mais mapping heuristique, non issu des métadonnées officielles** → voir §7 |

**Non encore mesuré à ce jour** (exigé par la mission, `DATA_MISSING`) : hedge ratio réel et
sa dérive, delta résiduel USD, frais spot/perp séparés, spread par jambe, slippage par jambe,
coût de rééquilibrage, basis d'entrée/sortie par position, drawdown, rendement par dollar de
marge et par jour, stabilité par régime.

---

## 4. Copy-trading

| Affirmation | Statut | Mesure |
|---|---|---|
| Verrouillé | `PROVEN_BY_RUNTIME` | 0 ligne copy au ledger |
| −7,97 bps sur 24 133 signaux OOS | `PROVEN_BY_REPLAY` | loi `copy_global`, `docs/LOIS_MESUREES.md` |
| Leader moyen contrarien | `PROVEN_BY_REPLAY` | loi `copy_leader_contrarien` : −7,75 bps **avant** le fill |
| Collecte C12 active depuis le 21/07 | `PROVEN_BY_RUNTIME` | `leader_fills_bruts.jsonl` : 3 947 lignes / 6,8 h ; 173 forward-marqués ; 12 leaders évalués |
| Réactivation sur preuve individuelle | `PROVEN_BY_CODE` | `ecrire_copy_whitelist.py` → deny-by-default, liste vide = verrou |
| « laboratoire confirmé sur 441 000 candidats » | `PARTIALLY_PROVEN` | le corpus fait **443 783** candidats ; le chiffre du README est arrondi vers le bas, pas faux |

**Scorecard produit** (`data/reports/copy_leader_forward_markouts.csv`) :

| leader | fills mesurés | markout forward | statut |
|---|---:|---:|---|
| `0xf5d81a135f756c…` | **96** | **−4,09 bps** | `LOCKED_NEGATIVE_EDGE` |
| `0x71d0e11ebb6150…` | **27** | **−34,06 bps** | `LOCKED_NEGATIVE_EDGE` |
| `0x5323b92268b4e1…` | 8 | +43,96 bps | `LOCKED_NO_DATA` |
| 9 autres | 1-11 | — | `LOCKED_NO_DATA` |

Seuil interne : **20 fills** (`MIN_EVENEMENTS`), pas 30 — correction d'une affirmation
antérieure de ce document. **Deux leaders sont désormais qualifiés, et tous deux sont
NÉGATIFS.** Le seul markout positif notable (+43,96) repose sur 8 fills : un seul mouvement
suffit à le produire. Gardes retenus : **0 / 12** → whitelist vide → copy verrouillé.

🔴 **Défaut d'intégrité trouvé et corrigé** : 3 fixtures de test (`ts_ms=0`, adresses
`0x1111…`) polluaient `leader_fills_bruts.jsonl` et faisaient annoncer **495 734 h**
d'étendue. Un leader fabriqué aurait pu entrer dans la whitelist. Garde posée + test.
Étendue réelle : **7,4 h**.

Restent `DATA_MISSING` : edge NET après coûts, stabilité temporelle, copyability,
dégradation fill→détection, LONG/SHORT, dépendance à un gros gain.

---

## 5. Arbitrage de dislocation — `CONTRADICTED` (le README a un jour de retard)

| README | Code réel | Statut |
|---|---|---|
| seuil 35 bps | `SEUIL_OUVERTURE_BPS = 15.0` | `CONTRADICTED` |
| 22 bps de coûts | `COUT_AR_BPS = 8.0` | `CONTRADICTED` |
| 13 bps de marge | 7 bps implicites (15 − 8) | `CONTRADICTED` |
| « aucun trade sous le seuil » | 1 OPEN au ledger, 0 CLOSE | `PARTIALLY_PROVEN` |

**Origine de la correction (21/07)** : les 22 bps supposaient **4 jambes** (aller-retour sur
deux venues). Une dislocation se ferme sur **2 jambes** → 8 bps. Le README décrit l'état
d'avant cette correction.

**Mesure de convergence sur 912 écarts réels** : |écart| se réduit de **−2,26 bps à 30 min**
(64,9 % des cas) — donc **moins que les 8 bps de coûts**. Verdict `LIMITE` : seuls les écarts
extrêmes paient. À 8 bps d'ouverture : 19 entrées, capture moyenne 8,53 bps.

**Défaut structurel confirmé, non corrigé à ce jour** : l'écart est calculé sur **deux mids**
(`hl_px` vs `bin_px`), pas sur des prix exécutables. Aucun `best_bid`/`best_ask`, aucune
taille, aucun âge de quote. → `DATA_MISSING` pour la décomposition exigée en §7 de la mission.

---

## 6. Cross-venue funding

| Affirmation | Statut | Mesure |
|---|---|---|
| Protocole 72 h en cours | `PROVEN_BY_RUNTIME` | série `dispersion_venues.jsonl` : **48,5 h** couvertes |
| Critères pré-écrits | `PARTIALLY_PROVEN` | le protocole existe en doc ; l'horodatage exact de début n'est pas tracé dans un fichier de protocole dédié → à figer |
| Aucune conclusion avant échéance | `PROVEN_BY_CODE` | aucun code n'agit sur ce signal |

**Échéance restante : ~23,5 h.** Aucun verdict ne doit être écrit avant. Le fichier
`docs/research/CROSS_VENUE_FUNDING_72H_VERDICT.md` est créé **en état d'attente**, sans
conclusion, avec les critères figés maintenant pour empêcher toute réécriture a posteriori.

---

## 7. Liquidations

| Affirmation | Statut | Mesure |
|---|---|---|
| Suspendu | `PROVEN_BY_CODE` | aucun chemin de décision ne le consomme |
| 0 événement utile | `PARTIALLY_PROVEN` | `liquidation_map.sqlite3` : **231 grappes** enregistrées sur 31,6 h — donc la collecte marche ; c'est l'**exploitation** qui n'a produit aucune décision |

Le README dit « 0 événement » : inexact. 231 observations existent. Ce qui manque, c'est un
mécanisme de décision — pas la donnée.

---

## 8. Grinder / Sniper — mesuré, pas supposé

Recherche exhaustive de `GRINDER`, `SNIPER`, `SCALP`, `MOMENTUM`, `MEAN_REVERSION`,
`MICROSTRUCTURE`, `WALLET_CLUSTER`, `FAST_SIGNAL`, `COPY_SIGNAL` dans `src/`, `tools/`,
`tests/`, `docs/`, les `.cmd` et le dashboard.

| Terme | Existe ? | Nature réelle | Statut |
|---|---|---|---|
| **SNIPER** | oui, 1 module | `backtesting/sniper_horizon_curve.py` — **outil de MESURE** de la courbe edge/horizon (100 ms → 5 min) pour les signaux copy. CLI `tools/mesurer_courbe_sniper.py`, tests présents. **Ne trade pas.** | `EXPERIMENTAL` (instrument de recherche, pas un moteur) |
| **GRINDER** | non comme moteur | apparaît comme **mot-clé** dans `agent/dead_zones_hypersmart.py` (zones mortes) et se rattache à `backtesting/grid_market_maker.py`, lié au market-making **réfuté 0/29** | `LEGACY` / concept mort avec T1b |
| SCALP, MOMENTUM, MEAN_REVERSION, MICROSTRUCTURE, WALLET_CLUSTER, FAST_SIGNAL, COPY_SIGNAL | **aucun** | 0 occurrence | `NOT_FOUND` |

**Aucun PnL séparé** : le ledger ne contient que `carry` (96 lignes) et `arbitrage` (1 ligne).

**Conclusion** : ni Grinder ni Sniper ne sont des moteurs actifs. Toute doc qui les présente
comme tels est fausse. Détail : `docs/research/GRINDER_SNIPER_REAL_STATUS.md`.

---

## 9. 🔴 P0 — funding COURU présenté comme funding ENCAISSÉ (`CONTRADICTED`)

Le README écrit : « PnL unifié = **réalisé + funding couru (l'encaissé, stable)** ».

**Les deux mots ne peuvent pas désigner la même chose, et le code fait le premier :**

```python
# carry_position_lifecycle.accruer()
dt_h = (now_ms - last_accrual_ts_ms) / 3.6e6          # fraction d'heure
fp = compute_funding_payment(..., intervals=dt_h)      # prorata LINÉAIRE
p["funding_accrued_usdt"] += fp.pnl_usdt
```

Sur Hyperliquid, le funding est **réglé au sommet de chaque heure**, sur la position tenue à
cet instant précis. Notre modèle crédite un **prorata continu**. Une position ouverte depuis
20 minutes se voit créditer 1/3 d'heure de funding, alors qu'en réalité elle a reçu **soit un
paiement horaire entier, soit rien**.

Donc `funding_accrued_usdt` est une **ESTIMATION**, pas un encaissement. La qualifier de
« stable » est doublement faux : c'est l'interpolation linéaire d'une fonction en escalier.

**Ordre de grandeur mesuré** : 1 175 $ de notionnel × 0,125 bps/h = **0,0147 $/h** d'incertitude
maximale à tout instant, contre 0,32 $ d'accru affiché → jusqu'à **~4,6 %** du chiffre.
Faible en valeur, mais c'est une **erreur de catégorie** : une estimation présentée comme un
encaissement.

**Corrigé dans cette passe** — voir §12 et `docs/research/UNIFIED_PNL_SOURCE_OF_TRUTH.md`.

---

## 10. Mapping Unit — `PARTIALLY_PROVEN`, fragilité réelle

Le mapping perp↔spot repose sur `_apparier_spots` : correspondance **par préfixe de nom**
(≥ 3 lettres) puis choix de la paire dont le **prix** est le plus proche du perp.

C'est un **dictionnaire heuristique**, pas les métadonnées officielles. Preuve que ça casse :
le scan produit encore des refus `base aberrante: perp 0.1879$ vs spot @117 0.001335$ (×141)`
sur BERA et TRUMP — le nom matche, l'actif non.

Les champs exigés par la mission (`hypercore_token_name`, `spot_pair_index`,
`base_token_index`, `quote_token_index`, `canonical_mapping`, `mapping_source`,
`mapping_timestamp`) **ne sont pas conservés**. → `DATA_MISSING`, tâche P1 ouverte.

---

## 11. Laboratoire replay — portes anti-mensonge

| Porte annoncée | Statut | Preuve |
|---|---|---|
| Deux moitiés temporelles disjointes | `PROVEN_BY_CODE` | `recherche_scenario` : `moitie_1` / `moitie_2` |
| Embargo | `PROVEN_BY_CODE` | `folds_purges()` |
| Coûts stressés ×1,5 | `PROVEN_BY_CODE` | clé `stress` dans les nets |
| ≥ 30 trades par moitié | `PROVEN_BY_CODE` | seuil dans `rang_pepite()` |
| Plateau des voisins | `PROVEN_BY_CODE` | `rang_pepite()` OR/ARGENT |
| Reprise après Ctrl-C | `PROVEN_BY_CODE` | essais sauvegardés en continu |

**Non vérifié** : qu'un test **échoue** si une porte est contournée. Les portes existent ;
l'invariant qui interdit de les désactiver n'existe pas encore. → tâche P0-3.

---

## 12. Corrections appliquées dans cette passe

1. **P0 funding** : séparation `net_funding_settled` (heures de règlement réellement franchies)
   et `funding_accrual_estimate` (fraction d'heure en cours). Le PnL stable n'utilise plus que
   le premier. Module `paper_trading/funding_settlement.py`, testé et branché.
2. **README** : les cinq contradictions prouvées ci-dessus corrigées (nombre de modules, seuil
   d'arbitrage, coûts, « encaissé », liquidations).
3. **Tasklist** reconstruite : `docs/TASKLIST_ACTIVE.md` (par preuve, priorités P0-P10),
   `docs/TASKLIST_EVIDENCE_MATRIX.md`, `docs/archive/TASKLIST_DONE_ARCHIVE.md`.

## 13. Ce qui reste `DATA_MISSING` (honnêtement non fait dans cette passe)

Économie complète par position carry · décomposition exécutable de l'arbitrage (carnet, tailles,
âge de quote) · scorecard par leader copy · décision produit Liquidations · métriques de
fraîcheur p50/p95/p99 par source · invariants anti-contournement du replay · benchmarks
avant/après. Chacun a sa tâche datée dans `docs/TASKLIST_ACTIVE.md`.

---

## Reproduction

```powershell
set PYTHONPATH=src
python -m hl_observer safety-audit
python -c "from hl_observer.funding.arb_dislocation_paper import SEUIL_OUVERTURE_BPS, COUT_AR_BPS; print(SEUIL_OUVERTURE_BPS, COUT_AR_BPS)"
python -c "from hl_observer.backtesting.carry_scan_recorder import resume; print(resume('.'))"
python -c "from hl_observer.funding.carry_positions_store import etat_carry; print(etat_carry('.'))"
python tools/backtest_carry_cli.py .
python -m pytest -q tests/test_no_real_trade_foundations.py tests/test_lois_mesurees.py
```

---

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
