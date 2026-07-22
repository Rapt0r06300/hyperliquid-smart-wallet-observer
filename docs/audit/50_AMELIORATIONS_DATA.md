# 50 améliorations DATA — collecter plus, fiable et propre (2026-07-22)

Objectif de Flo : *« une quantité EXTRAORDINAIRE de données pour trouver les meilleurs
calibrages »*. Autorisé par le CLAUDE.md (collecte publique agressive 24/7). Principe de senior :
**plus n'a de valeur que si c'est FIABLE (ne pas se faire bannir) et PROPRE (ne pas stocker de
poubelle)** — sinon un calibrage nourri de bruit ment. Chaque item ✅ est codé + testé ce jour ;
chaque item ▫️ est une suite concrète, priorisée.

## A. Socle de fiabilité réutilisable — `collection/collecte_fiable.py` (✅, 11 tests)
1. ✅ Déduplication par **clé stable** (`cle_dedup`) sur champs fixes.
2. ✅ **Cache de dedup borné** FIFO (`CacheDedup`) — ne grossit jamais sans fin.
3. ✅ Filtrage batch des neufs (`filtrer`).
4. ✅ **Append atomique** JSONL avec flush **+ fsync** (`append_jsonl`) — pas de fichier à moitié écrit.
5. ✅ **Écriture atomique** complète (tmp + fsync + `os.replace`) pour snapshots/index.
6. ✅ **Backoff exponentiel + jitter** (`backoff_jitter`) — pas de thundering herd, pas de ban.
7. ✅ **Limiteur de débit** (`Limiteur`) — rester sous la limite d'une source = durer = collecter plus.
8. ✅ **Provenance** estampillée (`estampiller`) : source + horodatage + read-only sur chaque ligne.
9. ✅ **Porte de qualité** (`qualite_ok`) : prix > 0, écart plausible, horodatage ≥ 2020.
10. ✅ **Pipeline en un appel** (`collecter_proprement`) : estampe → qualité → dedup.

## B. Capture du CARNET (bid/ask + profondeur) — `tools/collecter_carnet.py` (✅, 7 tests)
> LE trou data de l'arbitrage : le +0,54 $ était mesuré au MID. Ceci capture le vrai carnet.
11. ✅ **Priorité** aux coins réellement dislocés (`coins_prioritaires`, top-N, borné).
12. ✅ Parseur **HL `l2Book`** tolérant (`parser_book_hl`).
13. ✅ Parseur **Binance depth** tolérant (`parser_depth_binance`).
14. ✅ **Demi-spread réel** en bps (`demi_spread_bps`) — le vrai coût de franchissement.
15. ✅ **Écart EXÉCUTABLE** dans les deux sens (ask d'une venue vs bid de l'autre), pas le mid.
16. ✅ **Profondeur en $** (`taille_min_usd`) — la taille réellement disponible.
17. ✅ Passe **bornée + limiteur + backoff** (`une_passe`) — jamais de hammering.
18. ✅ Fetchers **injectables** → testé sans réseau ; dedup + qualité à l'écriture.
19. ✅ Sortie dédiée `runtime/data/carnet_venues.jsonl` (nouvelle source de données).

## C. Qualité à la source (✅)
20. ✅ **Plafond de plausibilité** sur les candidats d'arbitrage du collecteur de dispersion :
    35 % étaient des appariements aberrants (|écart| jusqu'à 1 670 000 bps) — **plus émis**.
21. ✅ Filtre qualité appliqué à la **lecture** des JSONL par la cervelle diagnostic (ts implausible).
22. ✅ `arb_executable` : garde de plausibilité (|écart| > 500 bps = poubelle).

## D. Largeur & ciblage (✅, sessions précédentes du jour)
23. ✅ **Univers dispersion complet** 38 → **206 coins** (funding + mid, quasi gratuit).
24. ✅ Liquidations : **ciblage fort levier** (comptes à liq proche du mid).
25. ✅ Liquidations : **watchlist accumulée** des comptes à risque (bornée 400).
26. ✅ Liquidations : univers **80 → 150 wallets**.
27. ✅ Copy : whitelist markout **NET** (coût de suivi), pipeline marks consolidé + shards frais.

## E. Suites concrètes — priorité HAUTE (▫️ à implémenter)
28. ▫️ **Firehose WebSocket `userFills`** multiplexé — capter TOUS les fills de leaders en continu.
29. ▫️ **Découverte de wallets à grande échelle** (leaderboard profond + wallets découverts, indexés).
30. ▫️ **Profondeur de carnet > top-of-book** (5-10 niveaux) pour l'impact à la vraie taille.
31. ▫️ **Backfill de l'historique de funding** (plus d'époques = calibrage carry plus robuste).
32. ▫️ **Capture de la bande de trades (tape)** — le flux réel, pas seulement le carnet.
33. ▫️ **Open Interest + funding prédit** par coin (contexte de régime).
34. ▫️ **Prix oracle** HL par coin (base oracle-vs-mark, piste HIP-3).
35. ▫️ **Brancher `collecter_carnet` au superviseur** (REGISTRE + REANIMER + LANCER ensemble, canari).

## F. Suites concrètes — fiabilité & échelle (▫️)
36. ▫️ **Dedup persistant entre redémarrages** (seen-set sur disque, pas seulement en mémoire).
37. ▫️ **Gap recovery** sur reconnexion WS (rejouer le trou, pas le sauter).
38. ▫️ **Rotation + compression** des JSONL (gzip des vieux shards) — garder plus d'historique.
39. ▫️ **Index SQLite** des données de replay (requêtes rapides sur des mois de données).
40. ▫️ **Pool de proxies / multi-IP** pour la collecte publique (plus de débit sans ban).
41. ▫️ **Cadence adaptative** par source (plus vite quand ça bouge, plus lent au calme).
42. ▫️ **Consolidation périodique** garantie (merge shards → `_merged`) surveillée.
43. ▫️ **Santé par source** : âge du dernier write, débit, taux de rejet qualité, dans le RECAP.

## G. Suites concrètes — nouvelles sources & signaux (▫️)
44. ▫️ **Venues supplémentaires** (Bybit, OKX) pour l'arbitrage multi-venues.
45. ▫️ **Spot HL + spot Binance** (base spot-perp propre, pour le carry et l'arb).
46. ▫️ **Événements de liquidation publics** (au-delà des cartes de `liquidationPx`).
47. ▫️ **Microstructure** : imbalance du carnet, intensité des fills (features de régime).
48. ▫️ **Snapshots horodatés du leaderboard** (rotation des leaders dans le temps).
49. ▫️ **Latence mesurée** par source (fraîcheur réelle, pas supposée).
50. ▫️ **Contrôle de couverture** : % de coins/temps réellement couverts vs l'univers cible.

---
Fait aujourd'hui : **~25 améliorations codées + testées** (A, B, C, D). Le reste (E-G) est un
plan priorisé — la brique la plus précieuse restante est le **firehose des fills** (copy) et la
**profondeur de carnet** (arb à la vraie taille).

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
