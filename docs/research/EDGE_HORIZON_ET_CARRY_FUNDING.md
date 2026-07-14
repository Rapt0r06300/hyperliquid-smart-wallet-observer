# Les deux dernières hypothèses, mesurées — 2026-07-11

Ce document ne contient aucune projection, aucune estimation, aucun réglage suggéré. Uniquement
ce que les données du bot ont répondu à deux questions qui restaient ouvertes.

Aucun ordre réel. Aucune clé. Aucune signature. Lecture seule.

---

## 1. La courbe edge/horizon du Sniper — l'hypothèse sub-seconde

### Pourquoi cette mesure existait

La conclusion établie (24 133 signaux, OOS) était que le copy-trading n'a pas d'edge : après un
ordre de whale, le prix bouge d'environ 0 bps pour un coût de 21 bps. Mais cette mesure portait sur
des signaux dont l'âge médian était de **57 secondes**, testés sur des horizons en secondes et en
minutes. Les horizons **inférieurs à la seconde n'avaient jamais été testés — la donnée n'existait
pas.** C'était la seule raison honnête de continuer d'espérer.

Le bot enregistre maintenant `candidates` (signaux) et `marks` (chemin de prix). L'hypothèse est
donc testable.

### Ce qui a été mesuré

Outil : `tools/mesurer_courbe_sniper.py` (lecture seule). Source : `runtime/replay/`, archive
`run_20260709_152414` — **80 591 prix relevés, 93 609 signaux, 15 571 signaux exploitables**.
Méthode : pour chaque signal, on ne regarde **que les prix postérieurs** (zéro lookahead), et on
mesure le mouvement dans le sens du leader.

| horizon | n | edge médian | écart-type | signal/bruit | statut |
|---|---|---|---|---|---|
| 100 ms | 1 | −2,98 bps | — | — | échantillon trop petit |
| 250 ms | 6 | −1,10 bps | 5,57 | 0,197 | échantillon trop petit |
| **500 ms** | **43** | **−3,74 bps** | 4,94 | 0,756 | échantillon trop petit |
| 1 s | 28 | −0,64 bps | 7,63 | 0,084 | échantillon trop petit |
| 2 s | 48 | −0,86 bps | 4,79 | 0,179 | échantillon trop petit |
| 5 s | 121 | −0,29 bps | 7,26 | 0,040 | échantillon trop petit |
| **10 s** | **254** | **−0,72 bps** | 8,30 | 0,087 | **mesuré** |
| **30 s** | **764** | **−0,86 bps** | 6,89 | 0,125 | **mesuré** |
| **60 s** | **1 412** | **+0,40 bps** | 12,09 | 0,033 | **mesuré** |

Coût aller-retour réel : **13 bps**.

### Verdict

**Aucun horizon ne sort du bruit.** Pas un seul. Le mouvement qui suit un fill de leader est
indiscernable du hasard, à toutes les échelles que la donnée couvre — y compris, pour ce qu'on en
voit, en sub-seconde.

La dernière hypothèse est close. **Le problème n'était jamais la latence.** Aller plus vite vers un
signal qui ne dit rien fait juste perdre de l'argent plus vite.

### Limite honnête

À 100-500 ms les échantillons sont trop petits (1, 6, 43) pour être concluants **seuls**. Mais ils
sont **négatifs**, pas prometteurs, et les horizons bien échantillonnés (n = 254 à 1 412) sont dans
le bruit. Rien ici n'invite à insister.

---

## 2. Le carry de funding — le premier signal réel du projet

### Ce que la mesure a trouvé

232 marchés Hyperliquid, 9 512 relevés, fenêtre 1,34 h (`runtime/replay/funding*.jsonl`).

**Le funding a une structure réelle.** Son autocorrélation :

| horizon | persistance |
|---|---|
| 15 min | **+0,894** |
| 30 min | **+0,816** |
| 1 h | **+0,703** |

À comparer au rapport signal/bruit du copy-trading : **0,03**. Le funding est, pour la première
fois dans ce projet, une grandeur **prévisible**. Ce n'est pas rien, et il faut le dire.

### Et pourquoi il est quand même inexploitable — tel que le code le prend

| | valeur mesurée |
|---|---|
| \|funding\| médian | **0,125 bps/h** |
| marchés payant ≥ 1 bps/h | **1 sur 232** (0,4 %) |
| \|mouvement de prix\| médian sur 1 h | **~35 bps** |
| **ratio médian funding / bruit de prix** | **0,0036** |

**Pour 1 bps de funding encaissé, une jambe nue subit environ 281 bps de mouvement de prix.**

Prévoir un revenu de 0,125 bps/h en encaissant 35 bps de bruit, ce n'est pas un arbitrage : c'est
un pari directionnel avec un coupon. Le coupon ne change rien à l'issue.

### Le piège, et il est vicieux

Le gate historique exigeait ≥ 2,5 bps/h. Il ne laissait passer **qu'un seul marché : CASHCAT.**

CASHCAT bouge de **219 bps par heure.**

Le funding y est élevé **précisément parce que** le risque y est extrême. **Le gate ne filtrait pas
le risque : il sélectionnait le marché le plus dangereux de la plateforme.** Monter le seuil ne
rend pas le carry plus sûr — il le concentre sur les marchés qui vont vous tuer.

C'est mesurable et c'est testé : `test_raising_the_funding_threshold_CONCENTRATES_the_risk`.

### Ce qu'on a fait

`src/hl_observer/funding/funding_arb_paper.py` ouvrait une position dite « paire delta-neutre »
qui n'a **qu'une seule jambe** — le code l'avouait lui-même : *« il n'y a pas de couverture : juste
un frais forfaitaire qui fait SEMBLANT d'en avoir une »*.

Désormais, **cette ouverture est refusée par défaut** :

    NO_TRADE  FUNDING_LEG_UNHEDGED_PRICE_RISK_DOMINATES

Le flag `HYPERSMART_FUNDING_ALLOW_UNHEDGED_LEG` (défaut `0`) n'existe que pour l'A/B et les tests
de mécanique. Le module `funding_carry_economics.py` pose la règle, adossée aux chiffres ci-dessus.

### Ce qui reste vrai, et c'est la seule piste ouverte

Le funding est **persistant**. Couvert (jambe opposée réelle qui annule le prix), il redevient du
portage pur. Le module accepte ce cas — il ne refuse pas par principe, il refuse par arithmétique.

Mais : à 0,125 bps/h médian, il faut **plus de 100 heures** pour seulement amortir 13 bps de coûts,
et à ce moment-là le funding s'est évaporé (persistance 0,70/h ⇒ il n'en reste rien après 24 h).
Cela ne devient intéressant que sur les rares marchés qui paient vraiment, **et** avec une vraie
jambe de couverture — que le système **n'a pas**.

**Aucune promesse. Aucun PnL positif annoncé.** C'est une piste, pas une solution.

---

## Ce que ces deux mesures disent ensemble

Le Sniper n'a pas d'edge, à aucun horizon. Le Grinder, tel qu'il est codé, prend un risque de prix
281 fois plus gros que le revenu qu'il vise, et son gate le pousse vers le pire marché possible.

Ce n'est pas un échec de réglage. **Aucune valeur de seuil ne corrige l'un ou l'autre.**

---

## 3. Le carnet L2 n'a JAMAIS été collecté — et personne ne s'en est plaint

### Le constat

`runtime/replay/` contient `candidates.jsonl`, `marks.jsonl`, `funding.jsonl` (2,4 Mo, en train
d'être écrit). **Il n'y a aucun `l2_book.jsonl`. Il n'y en a jamais eu.**

Pourtant : le flag `HYPERSMART_V26_BOOK_POLLER=1` est allumé, `HYPERSMART_RECORD_MICROSTRUCTURE=1`
aussi (c'est prouvé — le funding, qui dépend du même flag, s'enregistre), le poller est câblé, et
le code d'enregistrement existe et est appelé.

### La cause

Le poller de carnet ne sondait **qu'une seule liste de coins** :

```python
coins = DEFAULT_EDGE_TREND_RECORDER.coins()[:limite]
if coins:
    poll_once(coins)      # <-- si la liste est vide, on ne sonde RIEN, en silence
```

Cette liste s'est trouvée vide. **Une liste vide ne fait pas de bruit.** Le `if coins:` a éteint
la collecte sans un log, sans une alerte, sans un compteur.

### Ce que ça a neutralisé, en cascade

| conséquence | effet réel |
|---|---|
| aucun carnet L2 récupéré | — |
| `live_costs_for(coin)` ne trouve jamais rien | tous les coûts retombent sur des **constantes** |
| spread = 6 bps, slippage = 6 bps, profondeur = 50 000 $ | **identiques pour BTC et pour un meme coin illiquide** |
| aucune donnée de carnet enregistrée | **le market making est intestable** |

Le correctif « lire le vrai carnet » (P2-2) était donc **annulé par une liste vide**, alors que son
flag était allumé.

### Honnêteté sur mon diagnostic

J'ai d'abord affirmé que `record_edge_observation()` n'était appelée nulle part. **C'était faux** :
le recorder est bien alimenté, via `rec.record(...)` à l'intérieur de `apply_v26_entry_vetos`, qui
est bien dans le chemin actif. J'avais grepé le mauvais nom et conclu trop vite.

Je n'ai donc **pas** la certitude de *pourquoi* la liste était vide au moment du run. Plutôt que
d'inventer une explication, j'ai rendu la collecte **incapable de s'éteindre en silence.**

### Le correctif

- `src/hl_observer/collection/coin_universe.py` — registre explicite des marchés d'intérêt,
  alimenté là où un signal réel existe (`fusion_paper_engine_adapter`), borné, avec TTL, et qui
  **sait dire qu'il est vide** (`health()` nomme la conséquence).
- `l2_snapshot_cache.coins_a_sonder()` — sélection **pure et testée**, à trois niveaux :
  marchés observés → recorder d'edge → **socle par défaut (jamais vide)**.
- 16 tests, dont `test_the_book_poller_NEVER_polls_nothing`.

**Principe posé : le deny-by-default protège les ORDRES, pas les OCTETS.** Refuser d'ouvrir une
position sur une donnée absente est une règle de survie. Refuser de *collecter* une donnée parce
qu'une liste est vide n'est qu'un bug qui se déguise en prudence.
