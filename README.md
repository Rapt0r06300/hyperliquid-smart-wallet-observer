# HyperSmart Observer

HyperSmart Observer est un logiciel local de surveillance, d'analyse et de
simulation paper autour de Hyperliquid.

Objectif actuel: reproduire la partie mesurable du "smart wallet observer" en
mode safe:

- observer les donnees publiques Hyperliquid;
- decouvrir des wallets et clusters interessants;
- detecter ouvertures, additions, reductions et fermetures;
- calculer edge, fraicheur, couts et risque;
- refuser ce qui est vieux, incomplet ou non mesurable;
- simuler localement un portefeuille fictif de 1000 USDT;
- expliquer chaque decision dans des logs exportables;
- ne jamais executer d'ordre reel.

Le runtime officiel est **Hyperliquid-first**. Les modules dYdX historiques sont
conserves comme legacy/mockable, mais ils ne doivent pas etre lances par le
launcher principal ni montes dans l'UI Hyperliquid.

> **Doc maître** (état, méthode, architecture, config, roadmap) : `docs/ETAT_ET_FEUILLE_DE_ROUTE.md`.
> Règles agent : `CLAUDE.md` et `AGENTS.md`. Objectif condensé : `OBJECTIF.md`.

## 🏆 Objectif & état d'esprit : GAGNANT

**Le but est un PnL paper POSITIF et un ROI POSITIF, réels et tenus.** On y croit, on pousse fort,
on explore toutes les pistes, on ne se résigne jamais. « Tout est possible. »

**Tous les droits sont donnés à l'agent — SAUF une seule barrière : aucune exécution réelle.**
Scraping public agressif, collecte 24/7, univers large, backtests, IA, toute analyse : autorisé,
encouragé. La seule ligne rouge (`no-real-trade`) n'est pas une contrainte contre l'objectif —
c'est ce qui le protège : elle garantit qu'aucun chiffre n'est un faux et qu'aucun argent réel
n'est en jeu. **Un vrai gagnant refuse de se mentir :** on ne garde un edge que s'il survit aux
coûts réels et bat l'alternative (cash/HLP), mesuré sur données vraies. La discipline EST le chemin
vers un PnL positif qui se répète.

---

## Où en est le bot (22/07/2026)

**Un moteur en production paper (Carry), un en guet (Arbitrage), un verrouillé (Copy), une
mesure en cours (Cross-venue funding), un suspendu (Liquidations).** Chacun avec son verdict
mesuré — un moteur qui n'ouvre pas le DIT et explique pourquoi.

> **Mesures fraîches du 22/07 (données réelles, pas d'estimation) :**
> - **Carry** : sur **206 coins** et 71,7 h, le funding bat le seuil HLP **0,00 %** du temps → le
>   carry au plancher est **dominé** ; ce n'est pas un problème d'univers, il n'y a pas de demande
>   à capter. Élargir l'univers (levier 1) était nécessaire mais ne suffit pas.
> - **Arbitrage** : le +0,54 $ était mesuré au **mid** ; au **prix exécutable** (modèle
>   conservateur) il perd **−2,7 $**, et **35 %** des signaux étaient des appariements aberrants
>   (écartés). Verdict : illusion d'exécution. Le carnet réel (bid/ask) est désormais collecté
>   (`tools/collecter_carnet.py`, auto-démarré) pour trancher pour de vrai.
> - **Liquidations** : le ciblage vise désormais les comptes à **fort levier** (le vrai flux
>   forcé) ; verdict à l'accumulation (~50 événements distincts requis).
>
> Nouveaux instruments de décision : **BOT-READY** (score de maturité + autonomie), **PBO**
> (anti-sur-ajustement de la recherche), **cervelle diagnostic** (écrite dans le RECAP). Détail :
> `AGENTS.md` §Instruments.

> Compté au ledger (21/07) : **Carry 54 OPEN / 42 CLOSE**, **Arbitrage 1 OPEN**, les trois
> autres n'ont jamais ouvert. Vérité complète : `docs/research/PROJECT_GROUND_TRUTH_2026.md`.

| Module | État | Pourquoi |
|---|---|---|
| **Carry delta-neutre** | 🟢 **actif** — le seul moteur à taux positif (**+0,35 $/j** mesuré ; le **cumul** reste à **−5,73 $**, dette de l'ère churn du 19/07 en cours de remboursement) | Long spot + short perp, funding encaissé. Univers étendu aux tokens Unit (UBTC→BTC…) : 8 → 20 coins scannés, ~7 viables. Marge dynamique (capital réel / positions visées), sortie prise-de-profit dès +0,05 $ net. |
| **Copy-trading** | 🔒 **verrouillé, en réhabilitation** | Loi mesurée : **−7,97 bps** sur 24 133 signaux OOS à coût zéro (leader contrarien) ; le laboratoire l'a reconfirmé sur 441 000 candidats. La whitelist C12 (markout forward **par leader**) enregistre les fills depuis le 21/07 : le copy reviendra par la preuve individuelle, jamais par l'espoir. |
| **Arbitrage de dislocation** | 🟡 **en guet** | Écart de prix du même perp HL↔Binance ; ouvre à ≥ **15 bps** (8 de coûts **2 jambes** + 7 de marge). Les 22 bps annoncés jusqu'au 20/07 supposaient 4 jambes : une dislocation se ferme sur 2. **Convergence mesurée sur 912 écarts : −2,26 bps à 30 min (64,9 % des cas) — soit MOINS que les 8 bps de coûts.** Verdict `LIMITE` : seuls les écarts extrêmes paient. Il attend, et dit pourquoi. |
| **Cross-venue funding** | 🕐 **en mesure** | Protocole 72 h, barres pré-écrites. Verdict à échéance, jamais avant. |
| Liquidations | ⏸️ suspendu | **231 grappes enregistrées** sur 31,6 h — la collecte marche. Ce qui manque est un **mécanisme de décision** : les wallets suivis sont trop peu leveragés pour produire un signal exploitable. Décision produit à prendre (`docs/research/LIQUIDATION_ENGINE_PRODUCT_DECISION.md`). |

### Le laboratoire — `RECHERCHE-SCENARIO-REPLAY.cmd`

Le chercheur de réglages, en 4 étapes lisibles : **rassemble** les données (438 k+ candidats,
355 k marks, archives incluses) → **audite leur qualité** → **cherche module par module**
(~600 combinaisons × 4 sous-populations, crible multi-fidélité, raffinage grossier→fin,
folds purgés CPCV) → **écrit les rapports**.

Portes anti-mensonge (jamais assouplies) : deux moitiés temporelles disjointes avec embargo,
coûts stressés ×1,5, plateau des voisins, ≥ 30 trades par moitié. Une config promue est
classée **OR** (net > 0 sur ≥ 3/4 des époques) ou **ARGENT**.

Sorties dans `runtime/replay/` :

- `RESULTATS_RECHERCHE.md` — le rapport complet, une **recommandation en français par
  module** (« FAIS ÇA… », « ARRÊTE DE CHERCHER ICI… », « PATIENCE… ») + bloc JSON ;
- `PEPITES.md` — le résumé court ;
- `QUALITE_DONNEES.md` — santé des données (étiquetage, horodatage, **couverture** = cause
  n°1 des « 0 trade », résolution, doublons, prix aberrants).

Ctrl-C = **pause sans perte** : chaque essai jugé est sauvegardé, la reprise est automatique.

### Le rapport du matin — `RAPPORT-DU-JOUR.cmd`

Régénéré automatiquement toutes les 6 h dans `rapports/RAPPORT_DU_JOUR.md` (+ archive datée) :
PnL 24 h par motif, positions et leur **économie** ($/jour, amortissement), santé des
collecteurs, mesures en cours, refus dominants, leçons du ledger, PnL des refus (hebdo),
univers du scan **avec le verrou de chaque coin**, et la liste À FAIRE du jour.

### Ce que l'écran montre

**PnL stable = réalisé + funding RÉGLÉ.** Hyperliquid paie le funding au **sommet de chaque
heure** : seuls les sommets réellement franchis comptent comme encaissés. Deux quantités sont
donc affichées **à part, et ne se mélangent jamais** :

- **funding estimé (en cours)** — la fraction d'heure non encore réglée. Une estimation.
- **latent de base** — réversible, marqué au MID.

Jusqu'au 21/07, ce README appelait l'accrual complet « l'encaissé, stable » : c'était
l'interpolation linéaire d'une fonction en escalier présentée comme un fait comptable.
Corrigé (`paper_trading/funding_settlement.py`). Le ticker anime l'**estimé** — le réglé, lui,
saute d'un cran à chaque heure, il ne s'anime pas.

> Sizing : marge dynamique (capital réel ÷ positions visées, réserve 20 %, plafond 40 % par
> coin) ; levier choisi en risk-parity selon la pire hausse observée sur 200 jours.

---

## Doctrine

```text
OBSERVE FIRST
SCORE SECOND
SIMULATE LOCALLY THIRD
READ ONLY
PAPER ONLY
SIMULATION ONLY
DENY BY DEFAULT
SCORE IS NOT SIGNAL
PAPER TRADE IS NOT ORDER
HISTORICAL PNL IS NOT FUTURE PROFIT
NO GUARANTEED PROFIT
```

HyperSmart peut ouvrir et fermer des **positions virtuelles** en simulation, mais
il ne place jamais d'ordre reel, ne signe rien et ne demande aucune cle.

---

## Regles de securite

Interdit:

- mainnet execution;
- `/exchange` operationnel;
- signature;
- private key, seed phrase, wallet connect;
- bouton buy/sell/trade/execute/copy trade;
- testnet executor actif;
- LLM dans le hot path decisionnel;
- faux PnL ou graphe synthetique presente comme reel;
- promesse de gain.

Autorise:

- scraping public + pool de proxies/rotation (datacenter/residentiel/mobile) pour la collecte a grande echelle (cf. AGENTS.md et V9 §8);
- REST Hyperliquid `/info` read-only;
- WebSocket Hyperliquid read-only;
- imports CSV/JSON/TXT;
- SQLite local runtime;
- paper simulation;
- backtesting/replay;
- dashboard local read-only;
- logs detailles dans `logs/logs a envoyer`.

---

## Architecture 3 jobs

### Job A - Discovery / Leaderboard

- importer ou decouvrir des wallets publics;
- valider uniquement les adresses completes;
- refuser les adresses tronquees;
- scorer historique, consistency, drawdown, one-big-win, pnl concentration,
  copyability, activite recente et qualite d'execution;
- produire une shortlist locale.

### Job B - Copy loop read-only / simulation

- lire la shortlist;
- collecter `allMids`, `l2Book`, `clearinghouseState`, `userFills`,
  `userFillsByTime`, `openOrders`, `frontendOpenOrders`;
- dedupliquer les fills;
- comparer les snapshots precedents et courants;
- produire `LeaderDelta` et `SignalCandidate`;
- calculer `edge_remaining_bps`;
- creer une decision `NO_TRADE` ou une intention paper locale;
- ne jamais appeler `/exchange`.

### Job C - Reports / Dashboard

- afficher le solde fictif, positions virtuelles, decisions recentes, etat scan,
  logs et raisons de refus;
- exporter JSON/CSV/Markdown/HTML quand disponible;
- montrer uniquement des donnees reelles collectees ou un etat vide explicite.

---

## Lanceur principal

Le point d'entree utilisateur est:

```text
LANCER_HYPERSMART.cmd
```

Il lance le serveur local et le poller de simulation en mode visible. Fermer
proprement avec la commande affichee dans la fenetre du lanceur.

URL locale par defaut:

```text
http://127.0.0.1:8794/v2
```

La session repart a 1000 USDT fictifs au lancement. Pendant la session, le solde
doit suivre les gains/pertes paper realises et latents issus des positions
virtuelles.

---

## Modules principaux

```text
src/hl_observer/            # RUNTIME ACTIF : CLI/UI, collecte, edge, paper, risk, backtest
```

Détail de l'architecture active : `docs/ETAT_ET_FEUILLE_DE_ROUTE.md` (§5).

Legacy conserve (non lance par le runtime Hyperliquid, ne pas etendre) :

```text
hyper_smart_observer/            # legacy/compat isole
hyper_smart_observer/dydx_v4/    # dYdX v4 dormant/comparatif
```

Le legacy dYdX ne doit pas etre importe par le runtime Hyperliquid par defaut.

---

## Fusion des idees GitHub

Les repos externes sont utilises comme sources d'idees, pas comme code a copier.

Classification:

- KEEP: dashboard, logs, health, backtest, scoring, microstructure, exports.
- ADAPT_TO_HYPERLIQUID: WS-first, REST reconcile, adapter/risk layer, wallet
  scoring, source health, feature rows.
- DEFER: microservices lourds, RAG, orchestration multi-venue.
- BAN: ordre reel, CLOB runtime, private key, signature, wallet connect, live
  toggle, executor service, faux PnL, promesse de profit.

Les repos externes vivent dans `runtime/research/github_repos_v24/`. La methode de
portage (`COPY_DIRECT` / `COPY_ADAPTED` / `PORT_BEHAVIOR` / `INSPIRE_ONLY` /
`SKIP_WITH_REASON` / `DEFERRED_WITH_PLAN`) est decrite dans `CLAUDE.md` et
`docs/ETAT_ET_FEUILLE_DE_ROUTE.md`.

---

## Logs a envoyer

Les logs de diagnostic partageables doivent aller ici:

```text
logs/logs a envoyer/
```

Ils doivent expliquer:

- quelle opportunite a ete observee;
- pourquoi le bot a refuse ou accepte en paper;
- quelle donnee etait absente ou trop vieille;
- quel edge et quels couts ont ete calcules;
- comment le PnL paper a evolue.

Ces logs servent a ameliorer le moteur sans inventer de gains.

---

## Commandes utiles

Tests runtime Hyperliquid-only:

```powershell
python -m pytest -q tests/test_hyperliquid_runtime_does_not_import_dydx_by_default.py
python -m pytest -q tests/test_dydx_is_secondary_mockable_not_runtime.py
```

Tests ciblés HyperSmart:

```powershell
python -m pytest -q tests/test_hypersmart_*.py
```

Suite complete:

```powershell
python -m pytest -q
```

CLI locale:

```powershell
python -m hl_observer --help
python -m hl_observer ui
```

---

## Limite importante

Un PnL positif ne peut pas etre garanti. HyperSmart doit chercher a reduire les
mauvaises decisions, mieux filtrer les signaux et expliquer les pertes, mais ne
doit jamais tricher sur le graphe, le solde ou les logs.

Si une donnee manque, le logiciel doit l'afficher comme absente.
Si une action est ambigue, elle doit rester `UNKNOWN`.
Si l'edge est absent ou negatif, la decision doit etre `NO_TRADE`.
