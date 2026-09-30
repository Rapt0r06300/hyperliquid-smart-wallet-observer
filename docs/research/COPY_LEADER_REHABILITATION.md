# COPY — RÉHABILITATION INDIVIDUELLE PAR LEADER (2026-07-21)

> Statut global : **`LOCKED_BY_EVIDENCE`**. Aucun leader débloqué, et **deux d'entre eux ont
> désormais assez de données pour être refusés sur preuve, pas par défaut.**
> Données : `data/reports/copy_leader_forward_markouts.csv`, `copyability_scorecard.json`.

## 1. La loi de départ, et pourquoi elle n'interdit pas de chercher

Le copy **global** est réfuté : **−7,97 bps sur 24 133 signaux** hors échantillon, **même à
coût zéro**, cause identifiée (le leader moyen est **contrarien** : le prix court contre lui
de −7,75 bps **avant** son fill).

Mais une moyenne négative n'interdit pas l'existence d'une queue positive. La réhabilitation
est donc **individuelle**, et **jamais** un abaissement de seuil.

## 2. État de la collecte C12 (seuil interne : 20 fills mesurés par leader)

| adresse | fills mesurés | markout forward | statut |
|---|---:|---:|---|
| `0xf5d81a135f756c…` | **96** | **−4,09 bps** | `LOCKED_NEGATIVE_EDGE` |
| `0x71d0e11ebb6150…` | **27** | **−34,06 bps** | `LOCKED_NEGATIVE_EDGE` |
| `0x31dea2516beee9…` | 11 | −23,66 bps | `LOCKED_NO_DATA` |
| `0x5323b92268b4e1…` | 8 | **+43,96 bps** | `LOCKED_NO_DATA` |
| `0xecb63caa47c7c4…` | 6 | +8,75 bps | `LOCKED_NO_DATA` |
| `0x7b7f72a28fe109…` | 5 | −21,38 bps | `LOCKED_NO_DATA` |
| `0x57002993f7e693…` | 5 | −25,30 bps | `LOCKED_NO_DATA` |
| `0xf9109ada2f73c6…` | 5 | −83,65 bps | `LOCKED_NO_DATA` |
| 4 autres | 1-4 | — | `LOCKED_NO_DATA` |

**Gardes retenus : 0 / 12.** La whitelist reste vide, donc le copy reste verrouillé
(deny-by-default : liste vide = verrou, jamais ouverture).

## 3. Ce que ces chiffres disent — et ce qu'ils ne disent pas

**Les deux leaders qualifiés sont NÉGATIFS.** Le mieux fourni (96 fills) est à −4,09 bps :
moins mauvais que la moyenne globale (−7,97), mais toujours du mauvais côté de zéro. Le
second est franchement destructeur (−34 bps).

**Le seul markout positif notable (+43,96 bps) repose sur 8 fills.** À ce volume, un seul
gros mouvement suffit à produire ce chiffre. Le prendre pour un signal serait exactement
l'erreur que la loi `copy_global` a coûté cher à établir. Il est `LOCKED_NO_DATA`, et il le
restera jusqu'à 20 fills — **pas un de moins**.

## 4. 🔴 Défaut d'intégrité trouvé et corrigé

L'audit de fraîcheur a mesuré **495 734 h d'étendue** (56 ans) sur `leader_fills_bruts.jsonl`.
Cause : **3 lignes de fixtures de test dans la donnée live** — `ts_ms = 0`, adresses
`0x1111…`, `0x2222…`, `0x3333…`.

Risque réel : un leader **fabriqué** accumulant assez de fills aurait pu entrer dans la
whitelist, c'est-à-dire **déverrouiller le copy sur de la donnée inventée**. C'est la règle
n°1 du projet qui tombait.

Corrigé dans `tools/ecrire_copy_whitelist.py` : tout fill dont l'horodatage sort d'une fenêtre
plausible, ou dont l'adresse suit un motif synthétique, est **écarté et compté**. Test dédié.
Étendue réelle après filtrage : **7,4 h**.

## 5. Ce qui manque avant qu'un leader puisse passer `SILVER_CANDIDATE`

Les six critères, tous obligatoires, **aucun n'est mesuré aujourd'hui** :

1. **edge brut positif** sur ≥ 20 fills — le seul critère actuellement calculé ;
2. **edge net** après coûts (frais, spread, slippage, dégradation de copie) ;
3. **stabilité temporelle** — positif sur deux moitiés séparées de son propre historique ;
4. **copyability** — taille des positions, comportement maker/taker, faisabilité du suivi ;
5. **dégradation entre son fill et notre détection** — mesurable, non mesurée ;
6. **indépendance à un gros gain** — un leader porté par un seul trade n'est pas un leader.

## 6. Protocole de réhabilitation (à respecter, sans exception)

`LOCKED_*` → `OBSERVE_MORE` (≥ 20 fills) → `SILVER_CANDIDATE` (6 critères) →
`ELIGIBLE_FOR_SHADOW_PAPER` → **shadow paper uniquement** → jamais le moteur principal avant
un edge net positif prouvé hors échantillon en shadow.

**Aucun raccourci.** Baisser le seuil de fills serait remplacer une preuve par une envie.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
