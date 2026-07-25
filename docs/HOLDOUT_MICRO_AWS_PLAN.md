# HISTORICAL_HOLDOUT_V1 — Plan micro-AWS (one-click, borné) — 2026-07-25

> **Rien n'est téléchargé et aucun compte n'est créé sans autorisation explicite de Flo.**
> Le live RAW/OOS continue inchangé. Aucun ordre réel.

## 0. Où on en est
- **Gate node_fills → vault : OK** (schéma) — `node_fills` / `node_fills_by_block` portent l'adresse `user`,
  format = API `userFills`. L'attribution fill→vault est donc possible.
- **Accès gratuit : IMPOSSIBLE** — sonde Phase 1 : liste anonyme **HTTP 403** sur `hl-mainnet-node-data` **et**
  `hyperliquid-archive`. L'archive exige des **identifiants AWS + requester-pays**.
- **Miroir gratuit qualifiant : AUCUN** — Reservoir/Hydromancer = requester-pays (payant) ; SonarX = L2 CC0
  gratuit **mais sans node_fills attribués** (partiel, HIP-3) ; 0xArchive = compte requis/limité ;
  Dwellir/Tardis/HolySheep = payants. Aucun ne donne **node_fills(user) + L2 horodaté**, gratuit et reproductible.
- **Parseur gelé : PRÊT et PROUVÉ** — `src/hl_observer/experimental/historical_holdout.py`
  (`tests/test_historical_holdout.py`, 4 verts) : décompression lz4, attribution vault, jointure temporelle L2,
  métaordres+stades, OFI top-5, coût exécutable L2, placebo, IC clusterisé, capacité, verdict (aucune promotion
  si IC bas ≤ 0). Il ne dépend d'aucune donnée réelle pour être valide ; il ne demande que les octets décompressés.

## 1. Setup profil AWS — étapes minimales (Flo les fait ; je ne touche à aucune clé)
Profil **dédié, lecture S3 uniquement**. Aucune clé dans le dépôt, les logs ou la conversation.
1. **AWS Console → IAM → Users → Create user** : nom `hl-holdout-ro`, **sans accès console**.
2. **Permissions → attach policy → `AmazonS3ReadOnlyAccess`** (lecture seule : ce profil ne peut RIEN
   écrire/supprimer/trader). *(Plus strict, optionnel : policy inline `s3:GetObject`+`s3:ListBucket` limitée à
   `hl-mainnet-node-data` et `hyperliquid-archive`.)*
3. **User → Security credentials → Create access key → « Application running outside AWS »** → copier
   **Access key ID** + **Secret**.
4. Sur Windows, les mettre dans un **profil dédié HORS dépôt** — créer `%USERPROFILE%\.aws\credentials` :
   ```
   [hl-holdout-ro]
   aws_access_key_id = AKIA...
   aws_secret_access_key = ...
   ```
   ⚠️ **Jamais** ces clés dans la conversation, un fichier du dépôt ou un log. Le script les lit via le profil
   et ne les **affiche jamais**. (`~/.aws/` est ton dossier personnel, pas le repo.)
5. `pip install boto3` (paquet Python gratuit pour signer le requester-pays — **pas** un compte/paiement).
6. Me dire **« profil prêt »** → je te donne le feu vert pour lancer `LANCER-HOLDOUT-MICRO.cmd` (que **tu**
   lances). Sans profil, le script **REFUSE** (deny-by-default) ; il ne dépasse jamais les plafonds §2.

## 2. Objets ciblés (exacts) — micro-échantillon
- **Étape méta (≤ 30 requêtes LIST, signées, ~0 €)** : lister les dates de `node_fills_by_block/` et de
  `market_data/…/l2Book/` → calculer le **chevauchement** → choisir **2 fenêtres disjointes** (voir §3).
- **Étape échantillon (≤ 6 GET)** : pour **1 date + 1 heure** du chevauchement, télécharger :
  - `s3://hyperliquid-archive/market_data/<date>/<hour>/l2Book/<COIN>.lz4` pour **1–2 coins** que nos vaults
    tradent (ex. le coin le plus actif) ;
  - le(s) objet(s) `s3://hl-mainnet-node-data/node_fills_by_block/…` couvrant la **même date/heure**.
- **Plafonds DURS (abandon si dépassé)** : **≤ 50 Mo cumulés** (compteur d'octets), **≤ ~36 requêtes** (30 LIST +
  ~6 GET), **coût ≤ 1 €** (garde-fou ; l'egress réel de 50 Mo ≈ **< 0,01 €**). `RequestPayer=requester` explicite.

## 3. Fenêtres holdout (figées AVANT lecture des résultats)
- Choisies **uniquement** d'après la disponibilité réelle (dates listées à l'étape méta) : **2 fenêtres
  disjointes**, hors période de développement live, avec activité des vaults suivis.
- Dès qu'elles sont choisies : **pré-registration immuable** (dates, coins, règles, modèle, frais 9 bps, horizon,
  gates, `checkpoint_hash`) — même mécanique que `preregistration.json` de l'OOS. **Aucun retuning** après lecture.

## 4. Gate réel (Phase 3) — décision KILL / CONTINUER
Sur l'échantillon décompressé, `historical_holdout.executer(...)` doit prouver :
1. **attribution** : ≥ 1 vault suivi a des fills identifiés dans l'échantillon ;
2. **jointure L2** : ≥ 1 slice CONTINUATION/LATE a un carnet L2 synchronisé (postérieur au fill) ;
3. **décompression** : les `.lz4` se décompressent proprement ;
4. **couverture suffisante** : `pct_l2_sync` non nul, trous comptés et annoncés.
- **Si le gate échoue → on ARRÊTE la piste archive proprement** (aucune approximation).
- **Si le gate réussit → je chiffre le volume total et le coût MAX des 2 fenêtres complètes**, puis je
  **redemande une autorisation explicite** avant tout téléchargement supplémentaire.

## 5. Estimation de coût (à confirmer par l'étape méta)
- Egress S3 ≈ **0,09 $/Go**. Micro-échantillon ≤ 50 Mo → **≈ 0,004 € d'egress** + requêtes négligeables.
- Fenêtres complètes (ordre de grandeur, **estimation**, non mesuré car 403) : ~quelques Go → **egress < ~0,5 €**.
- **Le coût monétaire est négligeable (centimes)** ; le vrai « coût » est l'**ouverture du compte AWS**. Chiffres
  exacts finalisés par l'étape méta (≤ 30 LIST) une fois les clés présentes.

## 6. One-click — CONSTRUIT (ne s'exécute qu'au feu vert)
- `tools/holdout_micro_download.py` (+ `tests/test_holdout_micro_download.py`, **3 verts**) — client S3 **borné**
  (30 LIST, 6 GET, **compteur d'octets 50 Mo**, **garde 1 €**), `RequestPayer=requester`, **refuse sans profil**
  (deny-by-default), **ne logge aucune clé**. Règle déterministe : dates node_fills ∩ L2 → **médiane** = date
  holdout, heure 12, objets L2 {coin, BTC} + node_fills de la date → **pré-registration figée AVANT lecture**
  (`holdout_micro_preregistration.json` + `prereg_hash`). **Arrêt AUTO immédiat** si taille/coût/format/attribution
  vault/jointure L2 échoue. Rapport **GO/NO-GO** (`holdout_micro_go_nogo.json`) : verdict, couverture, objets,
  octets, requêtes, coût max.
- `LANCER-HOLDOUT-MICRO.cmd` — lanceur Windows (tu le lances après le setup §1 + mon feu vert).
- **Rien n'est téléchargé tant que le profil n'existe pas ET que je n'ai pas donné le feu vert.** Aucun
  téléchargement au-delà de l'échantillon sans nouvelle autorisation explicite.
