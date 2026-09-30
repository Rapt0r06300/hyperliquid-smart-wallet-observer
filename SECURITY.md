# Politique de sécurité — Alina Smart Flow

Dernière mise à jour : **2026-09-27**.

Alina Smart Flow (anciennement HyperSmart) est un moteur de recherche quantitative et de simulation **strictement paper/read-only**. La sécurité du projet ne consiste pas seulement à protéger des secrets : elle protège aussi l'intégrité des données, la causalité des replays et l'impossibilité d'atteindre une exécution réelle.

## 1. Invariants non négociables

Le runtime canonique doit rester :

**PAPER / READ-ONLY / FAIL-CLOSED**

Interdictions absolues :

- aucun ordre réel ;
- aucun ordre testnet ;
- aucun endpoint `/exchange` opérationnel ;
- aucune signature de transaction ;
- aucune clé privée ;
- aucun seed / mnemonic ;
- aucun dépôt ;
- aucun retrait ;
- aucun transfert ;
- aucune activation d'un SDK ou adaptateur permettant d'ordonner ;
- aucun secret ajouté pour rendre une exécution réelle possible.

Doctrine runtime :

`HL_ENABLE_MAINNET_EXECUTION=0`

`HL_ENABLE_TESTNET_EXECUTION=0`

et tout garde-fou équivalent présent au HEAD doit rester fail-closed.

Le fait qu'un module historique, un test ou un ancien adaptateur contienne du code lié à testnet/exchange ne l'autorise pas à être câblé dans le runtime officiel.

## 2. Périmètre d'exécution

Le runtime actif est :

`src/hl_observer/`

`hyper_smart_observer/` est legacy/compatibilité/audit et ne doit pas devenir une nouvelle surface d'exécution.

Les chemins autorisés lisent des données publiques ou des données de recherche déjà stockées.

Pour Hyperliquid :

- `/info` et les WebSockets read-only peuvent être utilisés pour observer ;
- `/exchange` correspond au chemin d'interaction/trading et reste interdit à Alina.

## 3. Cloud : aucun PC utilisateur

Pour ChatGPT Work, GitHub Actions et toute automatisation cloud :

- **GitHub-hosted uniquement** ;
- aucun self-hosted runner ;
- ne jamais réveiller le PC utilisateur ;
- ne jamais utiliser le PC comme worker ;
- aucun SSH/tunnel vers le PC ;
- aucun service local utilisateur requis ;
- aucun fichier local utilisateur requis ;
- aucun secret local utilisateur attendu par un workflow cloud.

Les anciens workflows dont le nom ou le contenu mentionne self-hosted/PC sont des artefacts historiques. Les versions inspectées au moment de cette mise à jour sont hard-disabled. Ils ne doivent jamais être réactivés ni servir de modèle à une nouvelle chaîne.

## 4. Secrets et credentials

Le repository ne doit jamais contenir :

- private keys ;
- seed phrases ;
- mnemonic ;
- exchange secrets ;
- API credentials privés ;
- tokens personnels GitHub ;
- cookies/session tokens ;
- credentials cloud ;
- fichiers `.env` contenant des secrets ;
- dumps ou logs contenant des secrets.

Un secret réel découvert dans l'historique doit être considéré comme **compromis** : ne pas simplement le supprimer du HEAD et continuer comme s'il restait sûr.

Les workflows doivent utiliser les permissions minimales nécessaires.

Ne jamais élargir `GITHUB_TOKEN` ou ajouter un PAT uniquement pour contourner un garde-fou ou déclencher plus facilement une chaîne.

## 5. Données personnelles et wallets

Alina peut observer des adresses/wallets publics nécessaires à la recherche.

Ne jamais stocker comme preuve publique :

- clé privée ;
- seed ;
- donnée permettant de signer ;
- secret d'authentification ;
- donnée privée inutile au research contract.

Une adresse publique n'autorise jamais à rechercher, inférer ou stocker des secrets associés.

## 6. Intégrité des données = sécurité

Une falsification de données ou de provenance est une vulnérabilité économique.

Interdit :

- donnée synthétique présentée comme réelle ;
- timestamp inventé ;
- receive time reconstruit sans provenance explicite ;
- valeur manquante transformée silencieusement en zéro ;
- shard modifié après publication sans nouvelle identité/hash ;
- manifest incohérent avec son asset ;
- hash ignoré ou remplacé ;
- compteur exact obtenu par extrapolation ;
- duplication silencieuse d'événements/fills ;
- contamination temporelle volontaire ou accidentelle présentée comme OOS.

**Missing != 0. Unknown != healthy.**

## 7. Intégrité économique = sécurité

Les garde-fous économiques ne doivent jamais être relâchés pour fabriquer un résultat positif.

Interdit notamment :

- diminuer artificiellement fees/spread/slippage ;
- supprimer latency ;
- convertir missed fills en fills ;
- ignorer partial fills ;
- utiliser le mid comme exécution lorsque la preuve requiert BBO/L2/VWAP ;
- retirer capacity/depth constraints ;
- mélanger TRAIN et OOS ;
- observer OOS/forward puis le présenter encore comme untouched après retuning ;
- compenser l'échec d'une famille par le profit d'une autre ;
- transformer `MORE_DATA` ou `UNMEASURABLE` en `PROVEN` sans preuve.

La cible **>= +4 USD NET/jour** par famille n'a jamais priorité sur l'intégrité de la preuve.

## 8. Sécurité des trois familles actives

Familles actives :

- Copy-Vault
- Lead-Lag
- Cross-Venue Dislocation

`Carry / Funding Carry = DISABLED_BY_SCOPE`.

### Copy-Vault

Le système copie uniquement en simulation paper.

Aucune fonctionnalité de “copy execution” ne doit :

- signer ;
- construire un ordre transmissible ;
- soumettre un ordre ;
- disposer d'une clé ;
- contourner reduce-only/fail-closed.

### Lead-Lag

La sécurité inclut l'ordre temporel :

- no-lookahead ;
- horloges/provenance ;
- données stale refusées ;
- missed fills conservés ;
- coût réel appliqué.

### Cross-Venue

Deux venues observées ne donnent jamais le droit d'ordonner sur aucune.

Les deux jambes restent simulées. La non-atomicité doit être modélisée, jamais résolue en ajoutant une vraie capacité d'exécution.

## 9. Event Intelligence

Les événements externes sont des **features/contextes de recherche**, pas une autorité d'ordre.

Interdit de convertir directement :

- news ;
- geopolitical event ;
- prediction-market signal ;
- score IA ;
- macro event ;

en exécution réelle.

Le sous-système doit préserver provenance, retrieval/ingest time, révisions et causalité nécessaires à un replay honnête.

## 10. GitHub Actions et workflows

Toute nouvelle chaîne canonique doit :

- utiliser un runner GitHub-hosted ;
- définir les permissions minimales ;
- rester bounded/resumable pour les travaux longs ;
- persister l'état durable hors du disque éphémère du runner ;
- vérifier les SHA/IDs/hashes nécessaires ;
- rester idempotente ;
- éviter les boucles de dispatch.

Ne jamais supposer qu'un simple `push` produit par un workflow via `GITHUB_TOKEN` déclenchera une nouvelle chaîne. Utiliser des dispatch explicites lorsque le contrat l'exige.

Les schedules sont des watchdogs, pas une horloge exacte.

## 11. Cross-repo security

Repositories canoniques :

- `Rapt0r06300/hyperliquid-smart-wallet-observer`
- `Rapt0r06300/alina-smartflow-datasets-v2`

Un dispatch cross-repo doit être lié autant que nécessaire à :

- source repository ;
- source SHA ;
- phase ;
- phase epoch ;
- request/campaign ID ;
- config/work-plan hash ;
- dataset generation/selection ;
- receipt terminal.

Ne jamais accepter comme “même campagne” deux états mutables contradictoires.

Le split-brain est un défaut de sécurité/intégrité.

## 12. Dépendances et outils tiers

Ne pas introduire une dépendance uniquement parce qu'elle facilite le trading réel.

Exemple : CCXT reste isolé dans l'extra de **discovery** et ne doit pas être utilisé comme hot path d'ordre.

Avant d'ajouter une dépendance capable d'effectuer une action externe sensible :

- vérifier qu'elle est réellement nécessaire ;
- limiter son usage à la surface read-only requise ;
- ne jamais lui fournir de secret de trading ;
- conserver les garde-fous applicatifs fail-closed.

## 13. Fail-closed attendu

En cas de doute sur :

- sécurité ;
- qualité de données ;
- source health ;
- horloge ;
- identité d'événement ;
- phase ;
- campaign state ;
- receipt ;
- coût ;
- exécution simulée ;

le système doit choisir le refus, la quarantaine ou l'état inconnu plutôt que poursuivre optimistement.

## 14. Tests de sécurité

Les tests de sécurité doivent protéger au minimum :

- exécution réelle inatteignable ;
- mainnet/testnet execution flags désactivés ;
- absence de secret ;
- garde-fous `/exchange` ;
- self-hosted interdit sur les chemins canoniques ;
- fail-closed ;
- idempotency cross-repo ;
- no-lookahead/causalité lorsque cela protège la preuve ;
- provenance et hash des assets critiques.

Ne jamais supprimer, skip ou xfail un test de sécurité simplement pour rendre la CI verte.

## 15. Incident / vulnérabilité bloquante

Sont notamment bloquants :

- chemin permettant une exécution réelle ou testnet ;
- exposition d'une clé/seed/token ;
- workflow capable de réveiller/utiliser le PC utilisateur ;
- self-hosted réactivé ;
- contournement d'un fail-closed ;
- falsification de provenance ;
- possibilité de présenter une donnée synthétique comme preuve réelle ;
- contamination OOS/forward non détectée pouvant produire un faux `PROVEN` ;
- corruption/split-brain d'un campaign state ;
- modification d'un asset prétendument immuable sans changement d'identité.

Une vulnérabilité bloquante doit empêcher une fermeture `DONE`.

## 16. Signaler une vulnérabilité

**Ne publiez jamais de détails sensibles dans une issue, discussion ou PR publique.**

Si GitHub **Private Vulnerability Reporting** est activé pour le repository, utilisez :

`Security -> Report a vulnerability`

Sinon, ouvrez seulement une issue publique demandant un **canal de contact sécurité**, sans décrire la vulnérabilité, puis poursuivez le signalement en privé.

Les mainteneurs disposant des permissions adéquates peuvent créer un **draft repository security advisory** pour traiter le problème de manière privée.

Le rapport doit idéalement fournir :

1. surface/fichier concerné ;
2. SHA/version ;
3. préconditions ;
4. impact ;
5. étapes de reproduction minimales ;
6. preuve de concept sûre si possible ;
7. proposition de mitigation éventuelle.

La reproduction ne doit jamais nécessiter :

- argent réel ;
- clé privée réelle ;
- secret réel ;
- ordre mainnet/testnet.

## 17. Traitement d'une vulnérabilité

Avant de déclarer une vulnérabilité corrigée :

- corriger la cause, pas seulement le symptôme ;
- ajouter une non-régression adaptée ;
- vérifier que le garde-fou reste fail-closed ;
- vérifier les surfaces voisines ;
- vérifier le diff réel ;
- vérifier que le correctif n'introduit pas une autre voie d'exécution ;
- vérifier le HEAD final.

Pour une fuite de secret, rotation/révocation est requise en plus de la correction du code.

## 18. Références normatives

Spec canonique :

`docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`

Instructions agent :

`AGENTS.md`

Architecture générale :

`README.md`

Documentation GitHub sur le signalement privé :

`https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-a-vulnerability/privately-reporting-a-security-vulnerability`

Documentation GitHub sur les advisories :

`https://docs.github.com/en/code-security/concepts/vulnerability-reporting-and-management/repository-security-advisories`

Documentation Hyperliquid :

`https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers`

## Principe final

**La sécurité d'Alina signifie qu'elle peut observer, mesurer, rejouer et simuler — jamais agir avec de l'argent réel.**

Une preuve économique n'est valide que si elle est obtenue sans contourner cette frontière.
