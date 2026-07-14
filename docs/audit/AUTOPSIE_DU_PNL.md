# Autopsie du PnL — pourquoi le run a perdu 64,02 $

**Flo avait raison d'insister. La perte n'était pas normale : elle était en grande partie
programmée.** Et l'audit `TEST-AUDIT-complet.cmd` aurait dû le voir — il ne le voyait pas, parce
qu'il vérifiait que le code *tourne*, pas qu'il soit **économiquement sain**. C'est corrigé aussi.

---

## Les 7 bugs trouvés

### 1. La structure de sortie exigeait 87 % de winrate

Le facteur de volatilité (médiane **0,71**) **rabotait** les barrières :

| | posé | effectif ×0,71 | après frais (13 bps) |
|---|---|---|---|
| Take-profit | 40 bps | **28 bps** | **+15 bps de gain** |
| Stop-loss | 126 bps | **90 bps** | **−103 bps de perte** |

**Ratio 1 : 6,65 → 86,9 % de winrate nécessaires.** Réalisé : 50 %.
*Même avec un signal parfaitement neutre, la perte était certaine.*
→ **Plancher de TP à 45 bps** (3,5 × les frais). Un TP ne peut plus être rongé par les frais.

### 2. Le stop catastrophique ne fermait rien

Affiché à 180 bps, il ne servait qu'à **contourner un délai d'attente**. Aucune sortie.
Quand la volatilité gonflait le SL à 315 bps, la perte courait : ARB **−323 bps**, ZEC **−321 bps**.
**Ces 2 trades = 46 % de toute la perte.**
→ C'est désormais un **vrai plafond de perte** qui ferme.

### 3. Le prix d'entrée était celui du leader

`entry_price == leader_price` sur **20 trades / 20**. Dans **8 cas sur 20**, le bot entrait à un
prix **meilleur que le marché** — physiquement impossible : on copie avec **57 s de retard**.

### 4. La latence de copie coûtait ZÉRO

`latency_cost_bps_per_sec = 0.0`, et `PaperEngine` ne transmettait même pas l'âge du signal au
modèle d'exécution. Copier un leader 57 secondes plus tard était **gratuit**.
→ Latence facturée (0,20 bps/s, plafonnée). Un aller-retour passe de **11,2 → 22,6 bps**, enfin
cohérent avec les ~21 bps que le *gate* facture déjà pour décider.

**Conséquence des points 3 et 4 : le PnL affiché (−64,02 $) était OPTIMISTE d'environ 19 $. La
vraie perte était plus proche de −83 $.** C'est exactement ce que la règle « le PnL paper n'est
jamais maquillé » interdit.

### 5. Aucun timeout de position

Le bot **décide** sur quelques minutes (TP à 28 bps) et **tenait** ses positions **1,3 h en
médiane, jusqu'à 8,4 h**. Or l'edge du signal est mesuré **nul dès 5 minutes** : au-delà, ce n'est
plus une position de copie, c'est une **exposition nue au marché**. C'est ce qui a tué les shorts.
→ **Timeout de 30 min.** Rejeu des 20 trades réels : **−39 $ → −23 $**.

### 6. Le funding n'était jamais facturé

**42,6 heures** de positions cumulées, **zéro centime** de financement déduit. Sur Hyperliquid il
se paie **chaque heure**.
→ Facturé (un LONG paie un funding positif, un SHORT le reçoit). **Sans donnée : on ne facture
rien et on le dit** (`funding_cost_usdc: None`) — jamais de chiffre inventé.

### 7. Les cliquets de session se déclenchaient sur du bruit

Un coin banni dès **−2 $**, un leader dès **−1,40 $**, la session entière arrêtée à **−10 $** —
alors qu'une perte normale vaut 3 à 6 $. Irréversibles. *(détaillé dans le rapport de calibrage)*

---

## Une fausse piste — que je dois signaler

J'ai d'abord cru que le **demi-spread n'était jamais payé**. **C'était faux** :
`estimate_slippage_bps` le contient déjà. J'allais le compter **deux fois**.
C'est un test existant (`test_taker_costs_fee_plus_slippage`) qui a attrapé mon erreur.
**Pessimiser un PnL est aussi malhonnête que le flatter.**

---

## Attribution finale des −64,02 $

```
gains des 10 TP        :  +18,48 $
pertes des 10 SL       :  −70,40 $    dont −32,20 $ sur les 2 trades sans filet (46 %)
frais                  :  −13,10 $
                          ─────────
                          −64,02 $     ROI : −6,40 %
```

- **~30 % = bugs de structure** → corrigés (rejeu réel : −55 $ → −39 $, puis −23 $ avec le timeout)
- **~70 % = absence d'edge + coûts + biais short** → incompressible avec cette stratégie
  (voir `PREUVE_ABSENCE_EDGE_COPYTRADING.md` : à coût **zéro**, l'espérance reste **−7,97 bps**)

**Corriger ces bugs ne rend pas le copy-trading rentable. Cela supprime une perte *mécanique* qui
s'ajoutait à l'absence d'edge — et cela rend enfin les mesures futures interprétables.** Jusqu'ici
on ne pouvait pas distinguer « le signal est mauvais » de « la sortie est cassée ».

---

## L'audit lui-même a été réparé

`TEST-AUDIT-complet.cmd` vérifiait la mécanique (imports, tests, sécurité) et les fonctions de
**laboratoire**. Il ne testait pas le **moteur réel**. **9 contrôles « SANTÉ ÉCONOMIQUE »** ont été
ajoutés :

le ratio TP/SL n'exige pas un winrate impossible · la volatilité ne peut pas raboter le TP sous les
frais · le plafond de dégradation est franchissable · le plancher single-wallet est atteignable ·
entrer coûte toujours · à prix constant un aller-retour perd **exactement** les coûts · les
cliquets ne se déclenchent pas sur du bruit · le stop catastrophique ferme réellement · les coûts
du *gate* et ceux du *PnL* sont cohérents.

**Vérifié dans les deux sens : sur le code et la config qui ont perdu 64 $, 8 de ces 9 contrôles
échouent.** L'audit t'aurait dit, avant même de lancer le bot :
> *« STRUCTURE PERDANTE : il faut 92 % de winrate pour rentrer dans tes frais. »*

---
*Simulation paper uniquement. Aucun ordre réel, aucun argent réel. Aucune promesse de PnL.*
