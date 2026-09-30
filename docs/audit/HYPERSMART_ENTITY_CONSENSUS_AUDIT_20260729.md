# Audit consensus normalise par entite - 2026-07-29

## Cause corrigee

Deux implementations divergeaient:

- le scoring historique assimilait un unique groupe temporel a une entite;
- le detecteur d'opportunites comptait encore toutes les adresses brutes.

Un seul fill simultane ne prouve pourtant ni une independance, ni un operateur
commun. Le bloc 16 ajoute une inference canonique SHADOW et expose les memes
mesures aux selecteurs et au detecteur d'opportunites.

## Preuves publiques acceptees

Le clustering utilise uniquement le prefixe fourni et des champs publics:

- identifiant d'entite on-chain public explicite, lorsqu'il existe;
- fills repetes sur le meme coin et le meme sens;
- synchronisation dans une fenetre bornee;
- ratio de taille persistant;
- cadence/TWAP observable;
- profils publics de funding ou de hedge.

Il n'utilise ni PnL futur, ni resultat du trade, ni donnee privee. Un seul
evenement coincident ne fusionne pas deux wallets.

## Contrat du gate

Le gate expose:

- `wallet_count`;
- `entity_cluster_count`;
- `effective_independent_votes`;
- `independence_measurable`;
- `confidence_penalty`;
- clusters, preuves par paire et avertissements.

Si toutes les paires sont mesurables, le mode strict exige le quorum par
entites. Sinon, les votes sont penalises de 50 % et le gate s'abstient si le
quorum effectif n'est plus atteint. Le mode runtime historique reste non
strict tant qu'une validation OOS n'a pas autorise sa promotion.

## Preuve runtime locale

Appel read-only sur les 5 000 derniers `position_deltas` de
`data/hl_observer.sqlite3`:

| Mesure | Valeur |
|---|---:|
| lignes lues | 5 000 |
| wallets | 4 |
| clusters d'entites | 4 |
| votes independants effectifs | 4.0 |
| paires mesurables | 6 / 6 |
| clusters lies | 0 |
| plus grand cluster | 1 wallet |

Cette observation ne prouve aucun alpha. Elle prouve que le code consomme les
donnees locales reelles, produit un effet mesurable et ne fabrique pas de
liaison lorsque les preuves comportementales ne la justifient pas.

## Tests de regression

- labels publics identiques et distincts;
- synchronisation repetee avec ratio de taille persistant;
- evenement unique insuffisant;
- mode strict mesurable et non mesurable;
- determinisme par permutation;
- troncature `as_of_ms` sans fuite du futur;
- integration selection leaders, opportunity detector et PaperEngine adapter.

**Securite : 0 ordre reel, 0 argent reel, 0 cle privee, 0 signature.**
