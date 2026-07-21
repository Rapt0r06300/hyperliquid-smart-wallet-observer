# RÉALIGNEMENT README ↔ RUNTIME + PLAN MOTEURS (2026-07-21)

## 1. Ce qui a été RÉALIGNÉ (5 contradictions prouvées)

| # | affirmation README | réalité mesurée | action |
|---|---|---|---|
| 1 | « Quatre modules » + 5 lignes dans le tableau | 1 moteur en production (Carry, 54 OPEN), 1 en guet (Arbitrage, 1 OPEN), 1 verrouillé, 1 mesure, 1 suspendu | formulation dérivée du **ledger** |
| 2 | Arbitrage « 35 bps (22 de coûts + 13 de marge) » | code : **15 bps / 8 bps**. Les 22 bps supposaient **4 jambes** ; une dislocation se ferme sur **2** | corrigé + convergence mesurée citée |
| 3 | « funding couru (**l'encaissé**, stable) » | prorata **linéaire** d'un règlement **horaire** → une **estimation** | les deux quantités séparées, code + écran |
| 4 | Liquidations « 0 événement » | **231 grappes** enregistrées sur 31,6 h | corrigé : c'est la **décision** qui manque, pas la donnée |
| 5 | Carry « la seule source de PnL **positif** » | taux **+0,35 $/j** mais **cumul −5,73 $** (dette de l'ère churn) | nuancé : taux vs cumul |

## 2. Plan par moteur — dérivé des mesures, pas des intentions

### Carry — `PROMISING_NEEDS_MORE_DATA`
Le seul qui ouvre. **12 positions, toutes `POSITIVE_BEFORE_COSTS_ONLY`** : aucune n'a encore
amorti son aller-retour. Priorité : **prouver**, pas étendre.
1. enrichir le schéma de position (quantités par jambe, frais séparés) → P1-1 ;
2. mesurer le hedge ratio réel au lieu de le modéliser → P1-2 ;
3. mapping Unit depuis les métadonnées officielles → P1-4 ;
4. attendre ≥ 12 passes de scan pour juger la stabilité des viables → P1-11.
**Ne pas** toucher simultanément univers / sizing / sorties / hedge / seuils.

### Arbitrage — `LIMITE`
La convergence existe (−2,26 bps à 30 min, 64,9 %) mais **sous les 8 bps de coûts**.
1. prix **exécutables** (best bid/ask, tailles, âge de quote) au lieu de deux mids → P4-1 ;
2. décomposer le coût all-in, puis seuil **dynamique** → P4-2/P4-3 ;
3. **ne pas** descendre le seuil à 8 bps sur 19 entrées → attendre ≥ 5 000 écarts (P4-6).

### Copy — `LOCKED_BY_EVIDENCE`
−7,97 bps sur 24 133 signaux, leader contrarien. Réhabilitation **uniquement** individuelle :
173 fills marqués, 12 leaders, **aucun n'atteint 30 fills**. Première réactivation en
**shadow paper**, jamais dans le moteur principal (P5-4).

### Cross-venue funding — `MEASUREMENT_IN_PROGRESS`
48,5 h / 72 h. Critères **figés** avant l'échéance. Aucun verdict avant ~23,5 h.

### Liquidations — `SUSPENDED`
231 grappes existent. Trois options à trancher (arrêter / changer d'univers de wallets /
détecter depuis le marché) ; aucune réactivation sans méthode mesurable (P6-1).

### Grinder / Sniper — `NOT_FOUND` / `EXPERIMENTAL`
Aucun n'est un moteur. **Sniper** = instrument de mesure de la courbe edge/horizon.
**Grinder** = concept mort avec le market-making (0/29). 7 autres termes : 0 occurrence.
Ne rien construire sans hypothèse économique mesurable et baseline.

## 3. Statuts finaux de cette passe

| objet | statut |
|---|---|
| No-real-trade | `NON_REGRESSION_VALIDATED` |
| Vérité du PnL (funding réglé/estimé) | `VERIFIED_POSITIVE_NET` **du correctif** (somme conservée, testée) |
| Carry | `PROMISING_NEEDS_MORE_DATA` |
| Arbitrage | `POSITIVE_BEFORE_COSTS_ONLY` |
| Copy | `LOCKED_BY_EVIDENCE` |
| Cross-venue funding | `MEASUREMENT_IN_PROGRESS` |
| Liquidations | `SUSPENDED` |
| Grinder / Sniper | `REJECTED` (comme moteurs) |

**Aucun PnL futur n'est promis.**

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
