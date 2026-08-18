# HyperSmart — progression technique canonique vers 775

## Verdict courant

**Progression honnête : 545 / 775.**

La provenance littérale reste inchangée : les formulations historiques originales
321→775 ne sont pas récupérées et ne sont pas inventées. Le faux verdict 775/775
reste retiré : une présence de fichiers ne vaut jamais une preuve spécifique.

## Ce qui est réellement verrouillé

- **1→320** : suites exécutables préexistantes conservées ;
- **321→395** : Copy-Vault, 15 exigences × 5 facettes = 75 preuves ;
- **396→465** : Lead-Lag, 14 exigences × 5 facettes = 70 preuves ;
- **466→545** : Cross-Venue, 16 exigences × 5 facettes = 80 preuves ;
- **546→775** : encore incomplets jusqu'à leur évaluateur spécifique.

Les cinq facettes obligatoires restent `CONTRACT`, `POSITIVE_PATH`,
`NEGATIVE_FAIL_CLOSED`, `DETERMINISM_CAUSALITY` et `EVIDENCE_PROVENANCE`.

## Cross-Venue 466→545

Le bloc spécifique est `src/hl_observer/ops/pre_run_cross_venue_466_545.py`.

Il couvre : synchronisation/skew, fraîcheur BBO, profondeur/VWAP, mapping exact,
entrée deux jambes, sortie deux jambes, quatre fills, frais, latence
inter-jambes, jambe nue, fills partiels, jambe manquée, convergence, durée max,
panne de venue et rejet spread/profondeur/mapping non exécutables.

### Corrections de vérité

`tools/collecter_carnet.py` ne construit plus le symbole Binance avec un simple
`coin + USDT`. Le mapping canonique est centralisé dans
`src/hl_observer/config/cross_venue_instruments.py`. Un instrument non mappable
est refusé.

Le collecteur conserve maintenant :
- les top-5 HL et Binance bruts ;
- le symbole Binance exact ;
- l'heure locale de réception de chaque venue ;
- le skew mesuré entre les deux réponses ;
- un identifiant d'observation ;
- le mode de source certifiable ou non.

Les anciennes lignes de `carnet_venues.jsonl` restent intactes. Elles ne sont
jamais requalifiées rétroactivement : sans mapping exact, deux timestamps de
réception, skew borné et profondeur brute, elles restent diagnostic uniquement.

### Quatre fills et risque de jambe nue

`src/hl_observer/backtesting/cross_venue_certified.py` implémente le contrat
`cross_four_fill_aon_v1` :
- entrée HL + Binance ;
- sortie HL + Binance ;
- VWAP calculé depuis la profondeur observée ;
- fill partiel explicitement mesuré ;
- aucune jambe manquante transformée en fill complet ;
- aucun PnL économique si le cycle n'a pas quatre fills complets ;
- frais explicites ;
- durée maximale et causalité de sortie ;
- skew inter-jambes présenté comme skew d'observation, jamais comme fausse
  latence d'ordre physique.

Le garde économique commun est fail-closed : un rapport Cross-Venue ne peut pas
être éligible au +4 USD sans source certifiée v2, mapping exact, skew prouvé,
snapshots certifiés et contrat quatre fills.

## Règle de progression

`src/hl_observer/ops/pre_run_guard_321_775.py` ne compte que les catégories avec
un évaluateur spécifique vert. Le prochain identifiant est **546**, début du
bloc **Anti-overfit**.

## Sécurité

Toujours paper/read-only. Mainnet/testnet execution désactivés, aucune clé privée
ou signature, aucun test supprimé pour masquer un rouge.
`PREPARER_PC_ALINA.cmd` reste non lancé et le runner self-hosted reste non
installé tant que `GO_SELF_HOSTED = TRUE` n'est pas explicitement autorisé.
