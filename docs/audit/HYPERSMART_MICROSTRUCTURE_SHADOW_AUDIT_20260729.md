# Audit microstructure SHADOW - 2026-07-29

## Perimetre

Le bloc 15 etend le tape L2 existant sans creer un second moteur de decision.
Toutes les donnees proviennent du prefixe causal deja observable par
`metaorder_shadow`. Le resultat reste en recherche read-only et ne materialise
aucun ordre, aucune position paper et aucun PnL canonique.

## Mesures branchees

| Mesure | Source | Regle de verite |
|---|---|---|
| OFI L1/L3/L5 | snapshots L2 precedent/courant | `None` sans paire causale |
| OFI integre | memes niveaux L2 | normalise par profondeur courante |
| Microprice | BBO et tailles top-level | refuse BBO croise ou invalide |
| Queue depletion | meme niveau de prix avant/apres | non mesurable si le prix change |
| Forme de profondeur | tailles top-5 | aucune reconstruction MBO |
| Flux agressif | trades publics avec cote | inconnu exclu du calcul |
| ADD/CANCEL | evenements explicitement types | jamais infere de snapshots |
| Spread regime | spread BBO mesure | `UNMEASURABLE` si absent |

## Gate et ablation

`microstructure_timing_gate` est deny-by-default. Il s'abstient sur cote
inconnue, BBO absent/croise, spread trop large, OFI absent ou flux oppose. Une
decision favorable vaut uniquement `ALLOW_SHADOW`.

`ablation_microstructure` compare le PnL net moyen du signal de base a celui
du sous-ensemble autorise. La promotion statistique exige au moins 30 lignes
dans chaque groupe, une amelioration positive et une moyenne autorisee
positive. Meme dans ce cas, le statut reste `SHADOW_ABLATION_ONLY`.

## Preuves

- tests unitaires OFI multi-niveaux, microprice, depletion, profondeur et flux;
- tests d'abstention sur donnees absentes et microstructure opposee;
- test d'ablation avec taille d'echantillon et gain net;
- test d'integration du bundle dans le runner metaorder;
- drapeaux `shadow=true` et `real_execution=false` verifies.

## Limites honnetes

- les snapshots L2 ne donnent pas la position exacte dans une file MBO;
- l'imbalance ADD/CANCEL reste absente sans evenements explicites;
- l'ablation locale n'est pas une validation OOS ni une garantie de PnL;
- aucune activation de strategie n'est effectuee par ce bloc.

**Securite : 0 ordre reel, 0 argent reel, 0 cle privee, 0 signature.**
