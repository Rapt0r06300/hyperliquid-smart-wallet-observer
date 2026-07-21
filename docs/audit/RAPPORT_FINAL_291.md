# RAPPORT FINAL — les 291 tâches (#306 / P19)

**2026-07-14** · HyperSmart Observer · *paper-only, read-only, testnet-locked*

---

## 1. Le résultat, sans emballage

> **Sur ~600 idées produites, **UNE SEULE** a survécu à la falsification :**
> **le carry HYPE (T2b) — et il rapporte ~2 % APR, réduit à ~1,7 % après correction des frais spot.**

Tout le reste est mort. Et c'est **le vrai résultat** — pas un échec.

**Je ne promets aucun PnL. Je n'en ai jamais promis. Ce document n'existe pas pour vendre un
espoir, mais pour dire ce qui est vrai.**

---

## 2. Les quatre lois qui ont tué des dizaines d'idées

Elles ne sont pas des opinions. Chacune est **une mesure**.

### ⚖️ LA DOMINATION
T1b a mesuré le market making à **100 % de remplissage** — la borne la plus généreuse possible.
**0/29 coins viables.** Le prix bouge **5 à 30× plus** que le spread capturé pendant qu'on porte
l'inventaire.

> **Tout meilleur modèle de file ne peut qu'ABAISSER le remplissage. Il ne peut donc qu'aggraver
> un verdict déjà négatif.** *Ce n'est pas un préjugé : c'est de l'arithmétique.*

**58 tâches tombent avec.** Y compris #488, l'argument le plus fort du lot (*« hftbacktest dit
qu'on est trop pessimiste sur le fill »*) — **on ne peut pas être plus optimiste que 100 %**.

### 🔗 UNE COUVERTURE NE VAUT QUE SI C'EST LE MÊME ACTIF
Trouvée **deux fois indépendamment** (X-04 : 0/120 · #242 : réfuté sur 208 jours). Couvrir avec un
*autre* actif réduit le bruit **et** le rendement **ensemble** — le ratio ne bouge pas.

### 💵 LE SPREAD N'EST JAMAIS UN CADEAU : C'EST LE PRIX DU RISQUE
Un spread large ne se ramasse pas : il **compense** une volatilité qu'on va subir.

### 🪞 TOUTE STRATÉGIE À RENDEMENT NÉGATIF EST DOMINÉE PAR LE CASH
Sur les **deux** dimensions. **Et notre edge de copy-trading est de −7,97 bps, à coût ZÉRO.**

---

## 3. Ce que le copy-trading est vraiment

**24 133 signaux hors-échantillon. −7,97 bps même à coût ZÉRO.**

La cause, mesurée (Q1→Q3) : **le prix court CONTRE le leader de −7,75 bps AVANT son fill**, puis
plus rien.

> ***Le leader est CONTRARIEN, pas informé. C'est un problème de CONTENU, pas de VITESSE.***

C'est ce qui a tué **#370 (le mempool)** — que j'avais moi-même appelée « la seule voie de
réouverture ». **Voir son ordre plus tôt nous mettrait plus PROFONDÉMENT dans le mouvement
adverse.** *Être plus rapide sur un signal vide ne le remplit pas.*

Et la moisson de **5 617 repos** l'a confirmé de l'extérieur : **la niche du copy-trading
Hyperliquid est du spam SEO. Zéro preuve, nulle part.**

---

## 4. La maladie du projet — et c'est le vrai produit de ces deux jours

> ***Une capacité présente, un chaînon manquant, personne qui se plaint.***

**Seize déguisements documentés.** Les plus chers :

| # | ce qui existait | ce qui manquait |
|---|---|---|
| 1 | `candleSnapshot(startTime)`, **déjà écrit, déjà autorisé** | personne ne l'appelait → **« data-limited » était AUTO-INFLIGÉ** (18,9 h → **208 jours**) |
| 2 | `fee_tiers.py` avec les **bons** frais | 6 fichiers codaient **4 valeurs différentes**, dont un **2,5 bps inexistant** |
| 3 | 7 garde-fous anti-overfit | **zéro appelant** — on a cherché dans 1,4 M de scénarios **sans correction** |
| 4 | 25 garde-fous de risque | **23 enterrés** |
| 5 | `liquidationPx` **reçu** de l'API | **effacé** au parsing |
| 6 | un panneau SÉCURITÉ | **voyant vert SOUDÉ** |
| 7 | `signal_age` | une **tautologie** qui **GELAIT** quand le flux calait → le bot entrait sur du vieux |
| 8 | `temporal_split` | **ni purge ni embargo** → **68 % du train** avait sa sortie dans le test |

**Chacune de ces huit lignes aurait pu, seule, invalider un résultat positif.**

---

## 5. Ce qui a été construit (et qui, lui, tient)

**Les outils de VÉRITÉ** — c'est là qu'est la valeur réelle du système :

- **Le balayage différentiel du lookahead** — il ne lit pas le code, **et il SE TAIT s'il ne
  retrouve pas le bug connu**. *Un outil muet vaut mieux qu'un outil qui certifie à tort.*
- **Le registre des zones mortes** — une idée n'est refusée que si elle consomme **la même
  entrée** que la mesure qui l'a tuée. *(Correction imposée par Flo : je pratiquais deux
  standards.)*
- **Le replay déterministe** — *deux rejeux du même flux doivent donner le même résultat.*
  **L'invariant le plus fondamental, et on ne l'avait jamais.**
- **L'identité de session** — un événement d'une autre session est **refusé bruyamment**.
  *Un PnL qui mélange deux runs est un PnL faux.*
- **Le mutation testing** — la couverture dit « exécuté », **jamais « vérifié »**.
- **Le benchmark CASH** — *on n'avait jamais comparé notre PnL au fait de ne rien faire.*

---

## 6. Le rollout — derrière des flags, un changement à la fois

**Aucun module de ce lot n'est allumé par défaut.** Chacun est importable, testé, et **inerte**
tant qu'un flag ne l'active pas.

**L'ordre imposé** (et il n'est pas négociable) :

1. **La vérité d'abord** : replay déterministe · identité de session · heartbeat · raw spool.
   *Tant que le moteur n'est pas rejouable, aucune mesure ne vaut rien.*
2. **Les refus ensuite** : `only_per_side` · VPIN · kill-switch · file bornée.
   *Ils réduisent les pertes ; ils ne créent aucun gain.*
3. **Les paris en dernier** — **et il n'y en a qu'un** : le carry HYPE.

> **Règle : un seul changement à la fois. Tout derrière un flag. Et la baseline (#325) est
> SCELLÉE avant : si les données ou la config bougent, elle CRIE.**

---

## 7. Les trois pistes qui restent — et leur état honnête

| piste | état |
|---|---|
| 💰 **#530 — les liquidations** | *Le liquidé ne choisit pas de vendre : il est VENDU.* Un flux **forcé** est **non informé**. **La meilleure piste qui reste.** 4 pièges dits d'avance (le couteau qui tombe · notre carte est **borgne** · le backstop liquidator absorbe hors carnet · la concurrence). **À MESURER.** |
| 🔒 **#517 — le MM sur HIP-3** | Le growth mode divise les frais par **10** → la porte des **coûts** est franchie. **Mais la porte de l'INVENTAIRE reste FERMÉE** (ratio 0,20 ; il faut ≥ 1,0). *Diviser les frais par dix ne touche pas le terme qui tue.* |
| ⚠️ **#556 — l'oracle** | La forme naïve est une **course de vitesse qu'on perd**. L'angle retenu : le **funding prévisible** (une heure pour agir). *Prédire un revenu minuscule reste un revenu minuscule.* |

Et un **benchmark** qui les juge toutes : **#544, le vault HLP.** *Si notre meilleure piste ne bat
pas un dépôt passif chez le market maker officiel, toute notre complexité est dominée.*

---

## 8. Sécurité — inchangée, non négociable

**0 ordre réel · 0 argent réel · 0 clé privée · 0 seed · 0 signature · 0 dépôt/retrait ·
0 wallet-connect pour agir · 0 dépense.**

Le module en shadow **ne peut pas agir**, structurellement. `dex-exec` — qui exécute de vrais
ordres — est en **refus absolu**, sans exception ni relecture.

---

## 9. La phrase que je ne veux pas qu'on oublie

> **Le système ne vaut pas par son PnL. Il vaut parce qu'il est devenu très difficile de lui
> faire dire une chose fausse.**

*C'est le seul actif qu'on ait construit. Et c'est le seul qui ne se périme pas.*
