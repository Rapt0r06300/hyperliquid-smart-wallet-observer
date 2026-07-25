# Piste archive AWS (Requester-Pays) — FERMÉE par décision de Flo (2026-07-25)

> **Flo : « je ne veux absolument rien de payant. »** Piste archive Hyperliquid **fermée** :
> aucun compte AWS · aucune clé · aucun moyen de paiement · aucun téléchargement · aucun développement AWS.
> Ce n'est pas un mur technique, c'est un **CHOIX**, enregistré comme tel.

## Ce qui a été établi (savoir conservé)
- `node_fills` / `node_fills_by_block` portent l'**adresse `user`** → attribution fill→vault **possible** (schéma OK).
- MAIS l'archive officielle (`hyperliquid-archive`, `hl-mainnet-node-data`) est **requester-pays** : liste anonyme
  = **HTTP 403** (mesuré, sonde Phase 1). **Aucun miroir gratuit qualifiant** : SonarX = L2 CC0 mais **sans fills
  attribués** (partiel) ; Hydromancer Reservoir = requester-pays (payant) ; 0xArchive/Dwellir/Tardis = compte/payant.

## CONSERVÉ (réutilisable si une source VRAIMENT gratuite apparaît)
- `src/hl_observer/experimental/historical_holdout.py` + `tests/test_historical_holdout.py` (**4 verts**) —
  parseur gelé **PUR** : prend des node_fills + L2 **déjà décompressés** (aucune dépendance AWS) et applique la
  variante gelée **CONTINUATION/LATE + OFI top-5, taker, 9 bps**, mêmes règles que le live. Prouvé : décompression
  lz4, attribution vault, jointure L2, métaordres, OFI, coût, placebo, IC clusterisé, capacité, verdict.

## RETIRÉ du tree actif (récupérable via git si réouverture)
Sonde S3 (`sonde_holdout_phase1.py`), downloader micro-AWS (`holdout_micro_download.py`) + son test, lanceurs
`SONDER-HOLDOUT-PHASE1.cmd` / `LANCER-HOLDOUT-MICRO.cmd`. Supprimés au commit de fermeture ; l'historique git les garde.

## Critère de RÉOUVERTURE (seul)
Une source **réellement gratuite ET reproductible** donnant `node_fills` **avec adresse `user`** + L2 horodaté.
Alors : brancher le parseur conservé dessus, **sans aucun coût**. Sinon, on n'y revient pas.
