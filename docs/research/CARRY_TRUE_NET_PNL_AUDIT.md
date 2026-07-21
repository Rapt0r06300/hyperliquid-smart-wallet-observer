# CARRY — AUDIT DU PnL NET RÉEL (2026-07-21)

> Statut global : **`PROMISING_NEEDS_MORE_DATA`**, pas `VERIFIED_POSITIVE_NET`.
> Données : `data/reports/carry_position_economics.csv` (12 positions),
> `data/reports/carry_coin_scorecard.json`.

## 1. Le résultat qui compte, et il n'est pas celui qu'on annonçait

| grandeur | valeur mesurée |
|---|---|
| réalisé cumulé (ledger) | **−6,05 $** |
| funding **réglé** (sommets d'heure franchis) | **+0,3226 $** |
| funding **estimé** (heure en cours, non réglé) | +0,0025 $ |
| **PnL stable = réalisé + réglé** | **−5,73 $** |
| latent de base (réversible, affiché à part) | non inclus, par construction |
| taux courant | ~**+0,35 $/jour** |

Le README disait « la seule source de PnL positif ». **Exact comme taux, faux comme cumul.**
Le cumul porte encore la dette de l'ère churn du 19/07 (32 ouvertures / 31 fermetures du même
coin en 22,3 h, ≈ −5 $). Le carry rembourse cette dette, il ne l'a pas encore remboursée.
Reformulé dans le README.

## 2. Les 12 positions : aucune n'a encore amorti son entrée

Verdict par coin (`carry_coin_scorecard.json`) : **12 × `POSITIVE_BEFORE_COSTS_ONLY`**,
**0 × `CARRY_PROVEN_POSITIVE`**.

Autrement dit : chaque position produit un revenu journalier positif, mais **aucune n'a
encore encaissé assez de funding pour rembourser son aller-retour** (entrée 6-29 bps +
sortie 11 bps). Au funding plancher (0,125 bps/h), l'amortissement demande 90 à 320 heures
selon le coin.

**Conséquence directe, honnête** : à cet instant, fermer le portefeuille réaliserait une
perte. Le carry n'est « positif » que si on le **tient**. C'est cohérent avec la règle
anti-churn (A3) mais ça doit être dit, pas sous-entendu.

## 3. Réponses aux 15 questions de la mission

| # | question | réponse | statut |
|---|---|---|---|
| 1 | delta-neutre réellement ? | `build_delta_neutral_position` **refuse** toute position déséquilibrée : long spot = short perp **par construction**. Mais c'est un **modèle**, jamais une mesure sur quantités réelles. | `PARTIALLY_PROVEN` |
| 2 | dérive du hedge ratio ? | **non mesurée** — le schéma de position ne stocke pas les quantités par jambe | `DATA_MISSING` |
| 3 | exposition directionnelle résiduelle ? | 0 par construction, non vérifiée | `DATA_MISSING` |
| 4 | quels coins produisent du funding positif net ? | **aucun encore** : tous sous leur seuil d'amortissement | `PROVEN_BY_RUNTIME` |
| 5 | quels coins ne sont positifs que par le latent ? | le latent est **exclu** du PnL stable depuis le 20/07, la question ne peut plus se poser à l'insu | `PROVEN_BY_CODE` |
| 6 | frais d'entrée et de sortie intégrés ? | **oui** : `cout_entree_bps` (2 jambes maker + base subie) et 11 bps de sortie sont dans `pnl_realise` | `PROVEN_BY_TEST` |
| 7 | le seuil +0,05 $ est-il au-dessus du bruit ? | **non mesuré**. Le bruit d'accrual vaut ~0,0147 $/h à notre notionnel → le seuil vaut ~3,4 h de bruit. Marginal. | `TODO` (P1-8) |
| 8 | ferme-t-il trop tôt ? | l'anti-churn (A3) annule toute sortie non urgente avant amortissement — le défaut du 19/07 est corrigé | `PROVEN_BY_TEST` |
| 9 | ferme-t-il trop tard ? | âge max 336 h ; 12 positions à 4-43 h, aucune proche | `PROVEN_BY_RUNTIME` |
| 10 | capital bloqué trop longtemps ? | rendement mesuré par $ de marge et par jour, colonne du CSV | `PROVEN_BY_RUNTIME` |
| 11 | les 20 coins sont-ils bien remappés ? | **non** : mapping par préfixe de nom, refus `base aberrante ×141` (BERA), `×3511` (TRUMP) | `CONTRADICTED` (P1-4) |
| 12 | les 7 viables le restent-ils ? | 7 passes enregistrées, il en faut ≥ 12 pour trancher | `BLOCKED_DATA` (P1-11) |
| 13 | dépendance à une période exceptionnelle ? | fenêtre unique de funding **au plancher protocolaire** : régime le moins favorable, donc pas de biais optimiste — mais pas de preuve de robustesse non plus | `INCONCLUSIVE` |
| 14 | les coûts stressés détruisent-ils l'edge ? | non testé sur le carry (le stress ×1,5 existe dans le laboratoire replay, pas ici) | `TODO` |
| 15 | rendement par $ de marge et par jour ? | calculé par position dans le CSV | `PROVEN_BY_RUNTIME` |

## 4. Ce qui manque pour passer à `VERIFIED_POSITIVE_NET`

1. **Enrichir le schéma de position** : quantités par jambe, frais spot et perp séparés,
   spread et slippage par jambe, coût de rééquilibrage. Sans ça, cinq des quinze questions
   restent sans réponse mesurée (P1-1).
2. **Mesurer le hedge ratio réel**, pas le modéliser (P1-2).
3. **Attendre l'amortissement d'au moins une position** pour observer un
   `CARRY_PROVEN_POSITIVE`.
4. **Mapping Unit depuis les métadonnées officielles** (P1-4).

## 5. Avertissement statistique

Aucun rendement annualisé n'est publié ici. Extrapoler +0,35 $/jour sur un an à partir d'une
fenêtre de deux jours, à funding plancher, avec zéro position amortie, produirait un nombre
impressionnant et **sans contenu**. Il ne sera calculé qu'après ≥ 30 fermetures réelles.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
