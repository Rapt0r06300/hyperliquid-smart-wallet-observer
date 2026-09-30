# Audit PnL — moteur SNIPER

## Verdict : **c'est le SEUL moteur qui trade — et il perd.**

| | valeur |
|---|---|
| trades | 10 |
| PnL net | **−7,81 $** |
| PnL **brut** | **−1,81 $** |
| frais | **6,50 $** |
| winrate | 20 % |
| profit factor | **0,42** |
| durée médiane | 0,51 h |

## La question du brief : *signal sans edge, ou signal bon mais exécuté trop tard ?*

**Réponse mesurée : les deux — mais surtout l'absence d'edge.**

### 1. Le signal ne prédit rien

Mesure indépendante sur **24 133 signaux réels** (prix à la seconde, hors échantillon) :
après un ordre de whale, le prix bouge de **−0,7 à +0,8 bps** en moyenne, dans un bruit de
50 à 100 bps. **Même à coût ZÉRO, l'espérance est de −7,97 bps.**
Voir `docs/audit/PREUVE_ABSENCE_EDGE_COPYTRADING.md`.

Sur la session en cours, le mouvement brut moyen est de **−3,6 bps** par trade : cohérent avec
« aucun edge », pas avec « bon signal mal exécuté ».

### 2. Mais l'exécution aggravait tout

- Le **prix d'entrée était celui du leader** (20 trades sur 20), alors qu'on copie avec un retard
  médian de **57 secondes**. Dans **8 cas sur 20**, l'entrée se faisait à un prix **meilleur que le
  marché** — physiquement impossible. *(corrigé)*
- La **latence coûtait ZÉRO**. *(corrigé : 0,20 bps/s, plafonnée)*
- **Aucun timeout** : le bot décidait sur quelques minutes et tenait ses positions **jusqu'à
  8,4 heures**. *(corrigé : 30 min)*

## Ce qui manque pour aller plus loin

Les pistes 51 à 70 (taxonomie des signaux, consensus multi-wallets, fill réel vs ordre ouvert,
seuils de fraîcheur par type) exigent des **timestamps de bout en bout** :
`observation → collecte → normalisation → scoring → décision → envoi → fill`.

**Le bot n'enregistre aujourd'hui qu'un seul `signal_age_ms` agrégé.**
On ne peut donc **pas** attribuer le retard à une étape précise.

**Verdict : `DATA_MISSING` sur la décomposition de la latence.**

---
*Aucune promesse de PnL. Simulation paper uniquement.*
