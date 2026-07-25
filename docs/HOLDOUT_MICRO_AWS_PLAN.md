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

## 1. Prérequis (action de Flo — je ne manipule ni clé ni paiement)
1. Ouvrir un compte AWS (gratuit à l'ouverture ; on ne paie que l'usage).
2. Placer `AWS_ACCESS_KEY_ID` et `AWS_SECRET_ACCESS_KEY` **dans l'environnement** (jamais dans un fichier du repo).
3. Me dire « autorisé, micro-échantillon » → je lance le one-click **borné** ci-dessous. Sans ces clés, le
   script **refuse** (deny-by-default).

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

## 6. One-click (à construire au feu vert)
`LANCER-HOLDOUT-MICRO.cmd` → `tools/holdout_micro_download.py` : refuse sans clés ; LIST bornée ; sélection des
objets pré-enregistrés ; download avec **compteur d'octets 50 Mo + compteur de requêtes + garde 1 €** (abandon
immédiat au dépassement) ; décompression ; `historical_holdout.executer` → PASS/FAIL + couverture. **Aucun**
téléchargement au-delà de l'échantillon sans nouvelle autorisation. *(Non construit tant que Flo n'a pas autorisé
— pour ne pas livrer du code non exécutable/non testé, et respecter « aucun compte/download sans accord ».)*
