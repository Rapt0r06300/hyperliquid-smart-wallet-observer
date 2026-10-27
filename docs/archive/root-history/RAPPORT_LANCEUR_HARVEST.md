# Rapport actuel — `LANCER_HYPERSMART.cmd` / profil HARVEST

> **Source de vérité actuelle : le code et les tests du dépôt.** Ce document remplace les anciennes affirmations historiques selon lesquelles `dydx-live` était auto-démarré dans HARVEST.

## 1. Périmètre runtime officiel

Le double-clic sur `LANCER_HYPERSMART.cmd` lance le runtime officiel en **paper / lecture seule** :

- `HL_ENABLE_MAINNET_EXECUTION=0` ;
- `HL_ENABLE_TESTNET_EXECUTION=0` ;
- aucun ordre réel ;
- aucune clé privée ;
- aucune signature ;
- aucun appel opérationnel à `/exchange`.

Le profil officiel **HARVEST est Hyperliquid-only**. dYdX reste disponible comme connecteur secondaire/legacy de recherche dans le registre et dans les profils `research` / `all`, mais **il n'est pas auto-démarré par HARVEST et n'est pas CORE**.

Cette séparation est volontaire : une ancienne version du rapport documentait un auto-démarrage dYdX qui n'est plus la doctrine du lanceur actuel. Il ne faut pas réactiver dYdX uniquement pour faire correspondre le code à cette ancienne documentation.

## 2. Collecteurs HARVEST actuels

Le registre canonique du superviseur sélectionne pour HARVEST le socle CORE plus la récolte dense utile :

| Collecteur | Source / rôle | Requis CORE |
|---|---|---:|
| `allmids-collector` | `allMids` Hyperliquid | oui |
| `bbo-collector` | BBO Hyperliquid + référence Binance read-only | oui |
| `userfills-live` | `userFills` des leaders suivis | oui |
| `carnet-collector` | carnet/L2 pour coûts et exécution paper | non |
| `marks-collector` | marks | non |
| `liq-collector` | liquidations | non |
| `venues-collector` | dispersion multi-venues de référence | non |
| `overshoot-collector` | overshoots | non |
| `vault-collector` | découverte de vaults | non |
| `scorer-vaults` | scoring de vaults | non |
| `backfill-fills` | historique fills | non |
| `backfill-candles-vaults` | historique candles | non |

`experimental-paper` n'entre dans HARVEST que si son flag explicite est demandé ; il ne devient jamais une source CORE.

## 3. dYdX : état exact

`dydx-live` existe encore dans `REGISTRE` pour la recherche/compatibilité historique. Il est :

- read-only ;
- non CORE ;
- hors `COLLECTEURS_HARVEST` ;
- dormant par défaut dans le lanceur officiel ;
- utilisable séparément dans un contexte de recherche contrôlé.

Les anciennes mentions « Auto-démarrage dYdX dans HARVEST — FAIT » sont donc **historiques et obsolètes**. La vérité actuelle est l'inverse : HARVEST reste centré sur Hyperliquid afin de réduire le nombre de dépendances runtime et les ambiguïtés de santé des sources.

## 4. Démarrage, readiness et santé

Le lanceur :

1. prépare l'environnement portable ;
2. force les drapeaux paper/read-only ;
3. acquiert le verrou d'instance ;
4. effectue le preflight ;
5. démarre les collecteurs via le superviseur ;
6. exige la preuve de vie des sources CORE avant READY ;
7. ouvre la session HARVEST canonique ;
8. démarre le moniteur de santé ;
9. démarre UI/poller paper ;
10. effectue un arrêt ciblé avec registres PID et preuves de fin de session.

Le moniteur de santé est un rôle indépendant et ne doit jamais être considéré comme un ancien process générique à tuer lors du démarrage du wrapper PowerShell.

## 5. Portabilité et propriété des processus

Une instance HyperSmart ne doit gérer que les processus appartenant à **son checkout courant**. Une deuxième copie portable du projet sur le même PC ne doit jamais être arrêtée par correspondance large sur `python`, `hl_observer` ou `boucle_collecteur`.

La propriété doit être prouvée par la racine du projet et/ou les PID connus. Le propriétaire du port UI n'est arrêté que s'il est identifié comme l'UI HyperSmart du checkout courant.

## 6. Sessions et analyse

`ANALYSER_BACKTESTS_REPLAYS.cmd` consomme uniquement les sessions HARVEST vérifiées et complètes. Une session ne doit être déclarée `COMPLETE` qu'après preuve que les writers du checkout courant sont arrêtés et que les artefacts attendus sont cohérents.

## 7. Lead-Lag

Deux voies Lead-Lag existent et doivent rester comptablement distinctes :

- `LEAD_LAG_STRICT_EVENT` : voie événementielle stricte, basée sur la preuve gelée et l'exécution paper causale ;
- `LEAD_LAG_EXP_CALIBRATION` : voie expérimentale/calibration, isolée du PnL de la voie stricte.

La couverture BBO automatique doit inclure les coins présents dans la configuration Lead-Lag gelée valide, en plus des majors et des coins issus des liquidations, afin qu'un coin promu ne soit pas silencieusement privé de données de marché.

## 8. Garde-fous maintenus

- Paper/read-only uniquement.
- Carry hors périmètre actif du lanceur officiel.
- Copy-Vault, Lead-Lag et Cross-Venue restent les familles actives du projet.
- Aucun PnL n'est considéré robuste sans coûts, causalité, replay/forward et preuves OOS/forward adaptées.
- Une absence de donnée produit un refus/no-trade ou un état non mesurable, jamais une donnée inventée.

## 9. Note historique

Les SHA et comptes de tests des premières versions de ce rapport décrivaient l'état du dépôt à leurs dates respectives. Ils ne doivent pas être utilisés comme preuve de l'état actuel. Pour toute validation, utiliser le HEAD courant, les workflows GitHub Actions associés au même SHA et les tests actuels du dépôt.
