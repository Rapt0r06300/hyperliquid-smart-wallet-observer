# 19/07/2026 — Autopsie complète des pertes paper, et les réparations

Mission de Flo : « Trouve toutes les causes de perte d'argent, analyse tout, répare tout. »
Méthode : partir du **ledger** (pas des impressions), remonter chaque dollar à sa cause,
ne réparer que ce qui est prouvé. Aucune promesse de PnL — des causes éteintes, c'est tout.

## Où est parti chaque dollar (mesuré, pas estimé)

| Époque | Perte | Cause racine | État |
|---|---|---|---|
| 08–10/07 | **−103,68 $** au pire intraday, fin à −63,68 $ | **Copy-trading sans edge** (loi du 11/07 : −7,97 bps OOS sur 24 133 signaux, leader contrarien) | **ÉTEINTE le 11/07** — portes montées (MIN_EDGE 16 bps, consensus 2 wallets, sniper à 9999). Vérifié aujourd'hui : equity **plate 8 jours de suite**, plus un centime perdu en copy. |
| 18–19/07 12:33 | **−5,07 $** (96 % de l'époque) | **Churn carry** : 29 fermetures `COIN_PLUS_DANS_SHORTLIST` à ~17,5 cts l'aller-retour, sans jamais laisser le funding rembourser l'entrée | **ÉTEINTE le 19/07 13:29** (anti-churn A1–A5 câblé : runtime → store → lifecycle → `filtrer_sortie`). Preuve temporelle : dernier churn 12:33, commit 13:29, zéro depuis. |
| 18–19/07 | **−0,33 $** | **Collecteurs morts** → `DONNEE_ABSENTE_PROLONGEE` ×2 (fermetures forcées faute de données) | **RÉPARÉE aujourd'hui** — superviseur (voir ci-dessous). |
| 19/07 15:27→ | 0 $ réalisé, mais **bot affamé** | Les 4 collecteurs morts ensemble en 35 s → inputs périmés en 15 min → `INPUTS_SPOT_PERIMES_NO_TRADE` en boucle | **RÉPARÉE** — le refus était CORRECT ; c'est l'alimentation qu'il fallait ressusciter automatiquement. |

Vérité importante : **le bot ne perd plus d'argent depuis le 11/07 sur le copy et depuis le
19/07 13:29 sur le churn.** La perte historique a des causes nommées, datées, et éteintes —
pas maquillées : les chiffres ci-dessus restent dans le ledger.

## Réparations de cette session

### 1. Bug d'unité ×30 sur `gain_net_24h_bps` (delta_neutral_carry)
Le champ publiait le gain **cumulé sur 30 jours** sous un nom de taux journalier.
PURR affichait « +49,7 bps/24h » avec un funding au plancher qui rend ~3 bps/24h BRUTS.
Conséquence sournoise : la **rotation A7** compare des taux journaliers à un coût one-shot
(22 bps) — elle voyait des surplus ×30 et justifiait des rotations qui ne pouvaient
mathématiquement pas se payer. C'est un des moteurs des 29 rotations du churn.
Correctif : `gain_net_24h_bps` = vrai net moyen par 24 h ; le cumul vit dans
`gain_net_horizon_bps` (nouveau champ). Le verdict `viable` (cumul > 0 sur l'horizon)
est **inchangé** — aucune décision d'ouverture modifiée, seulement la vérité des unités.
Même famille que le « 38 % APR » du 13/07 et le piège 1h/8h : **une unité fausse fabrique
une pépite imaginaire.**

### 2. Superviseur des collecteurs (`ops/superviseur_collecteurs.py`, câblé)
L'alarme existait (VERIFIER-TOUT section 5) mais personne ne la regardait pendant que le
bot tournait. Désormais le runtime carry — le processus qui a PROUVÉ qu'il survit —
constate un log de collecteur muet (registre = les 4 lignes du lanceur, avec canari
anti-dérive) et **relance** via la même commande que LANCER (chemins relatifs, zéro
guillemet). Cooldown 10 min, journal `runtime/data/superviseur_collecteurs.json`,
jamais d'exception vers le moteur, interrupteur `HYPERSMART_SUPERVISEUR_COLLECTEURS`.
Relance réelle sous Windows uniquement.

### 3. Un test qui prescrivait le churn, réécrit
`test_etape2_shortlist_ferme_seulement_le_coin_qui_sort` exigeait la fermeture immédiate
d'un coin sorti de la shortlist — exactement le comportement à −5 $. Réécrit en 3 actes :
non-amorti ⇒ on GARDE ; absence prolongée (>3 passes ET >45 min) ⇒ fermeture unique
`DONNEE_ABSENTE_PROLONGEE`, sélective (l'autre coin ne bouge pas).

### 4. (Matin) Provenance des compteurs (`log_metrics`, commit 7bd5b43)
Le panneau Hyperliquid lisait le log du moteur dYdX legacy dès que les fichiers HL étaient
vides. `AUTORISER_DYDX_LEGACY=False` + péremption 30 min. 10 tests.

## Ce qui reste (honnêteté sur les limites)

* **Pourquoi** les 4 collecteurs meurent ensemble reste non élucidé (morts en sommeil,
  code 0, moteur principal intact). Le superviseur rend la panne auto-réparable et
  JOURNALISÉE : si ça se reproduit, `superviseur_collecteurs.json` le dira.
* Le PnL futur n'est promis par personne. Au plancher de funding, le carry honnête rend
  ~1,7 bps/24h sur PURR — petit, positif, réel. Les spikes de funding (z-score A4) et la
  convergence de base (A5) restent les vrais moteurs de gain.
* Vérité finale = suite complète sous Windows (`TEST-AUDIT-complet.cmd`), pas le sandbox.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
