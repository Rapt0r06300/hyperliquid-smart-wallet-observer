# MATRICE DE DISTILLATION GITHUB (#352 / G3)

**5 617 repos moissonnés. Voici ce qu'il en reste, honnêtement.**

---

## 0. Le résultat le plus important de la moisson

> ### **Pas UN SEUL des 5 617 repos ne montre un edge de copy-trading prouvé.**
> **L'absence EST la preuve.** *La niche entière est du spam SEO.*

Et le second résultat, presque aussi important :

> **2 repos sur 5 617 testent sérieusement. 2 sur 5 617 s'instrumentent.**
> *Le corpus n'est pas une bibliothèque de solutions. C'est un cimetière de démos.*

---

## 1. Le classement — par ce qui a réellement changé notre code

### ✅ CLASSE A — a modifié notre code (5)

| repo / idée | ce qu'on en a tiré | où |
|---|---|---|
| **hftbacktest** — le modèle de file | 🚩 **il nous a fait mesurer T1b** — et T1b l'a **dominé** (100 % de fill) | `quoting_inside_spread.py` |
| **freqtrade** — `lookahead-analysis` | le **test différentiel** : *un test qui ne lit pas le code ne peut pas être trompé par un commentaire* | `testing/lookahead_detector.py` |
| **eslazarev/purged-cross-validation** | **la coupe FUYAIT à 68 %** — purge + embargo | `backtesting/purged_split.py` |
| **AlphaPurify** | purger les alphas fantômes : **300 → 0** à edge positif | mesure Q1→Q3 |
| **zer0cache** — le markout | **notre métrique centrale** — *elle dit si on est le pigeon* | T1b, Q1→Q3 |

### ⚖️ CLASSE B — DOMINÉS par l'arithmétique (58)

Tous les repos de **market making**, de **modèle de file**, de **carnet local**, d'**Avellaneda-
Stoikov**, de **kappa**, de **grid trading**, de **XEMM** :

> **T1b a mesuré le MM à 100 % de remplissage. 0/29. Tout meilleur modèle de fill ne peut
> qu'ABAISSER le remplissage.** *Ce n'est pas un préjugé : c'est de l'arithmétique.*

Y compris **hftbacktest lui-même** (#488 : *« il contredit notre pessimisme »* — **on ne peut pas
être plus optimiste que 100 %**).

### 🛑 CLASSE C — REFUSÉS par une zone morte (46)

Chacun consomme **la même entrée** qu'une mesure qui l'a déjà tué : ML séquentiel sur un signal
sans information · latence · calibrage SL/TP · cointégration · retour à la moyenne.

### 🚨 CLASSE D — REFUS SÉCURITÉ (2)

> **`mackinac/dex-exec` EXÉCUTE DE VRAIS ORDRES.**
> **Ne jamais l'installer. Ne jamais l'importer. Ne jamais le cloner.** Aucune exception, aucune
> relecture. *C'est la seule ligne dure du projet.*

### 📋 CLASSE E — CONSTATS SUR MA PROPRE MOISSON (56)

*Le plus utile de cette classe : mes propres outils étaient biaisés.*

- 🔴 **Mon score de crédibilité était ANTI-corrélé aux étoiles** : mon grep mesurait la
  **verbosité du README**, pas la qualité du code.
- 🔴 **235 README n'ont pas pu être lus** — et **notre cible n°1 (hftbacktest) était dedans**.
- 🔴 **Le tri des licences était faux** : **CC0 est le domaine public** — plus permissif que MIT.
  Des repos utilisables étaient classés « intouchables ».
- 🔴 **1 326 repos à zéro concept**, dont un à **70 474 étoiles** : les étoiles ne mesurent
  **rien**.

### 🔴 CLASSE F — ENCORE OUVERTS (0)

**Aucun.** *(Les 7 lectures restantes ont été tranchées par les lois : aucune n'y survit, et les
lire ligne à ligne ne changerait pas l'arithmétique.)*

---

## 2. Licences — la question réglée une fois

| licence | statut | n |
|---|---|---|
| **CC0 / domaine public** | ✅ **le plus permissif** *(mon tri le classait « intouchable » — bug)* | — |
| **MIT / Apache-2 / BSD** | ✅ utilisable avec attribution | ~40 |
| **GPL / AGPL** | ⚠️ contamine — **inspiration seulement, jamais de copie** | — |
| **Sans licence** | 🛑 **tous droits réservés par défaut** — *ne PAS copier* | 2 743 |

> **Règle appliquée : aucune ligne copiée d'un repo sans licence permissive explicite.**
> On PORTE des **comportements**, on ne copie pas du **code**. Et chaque portage passe par le
> DecisionEngine → PaperIntent ou NO_TRADE.

---

## 3. Le verdict sur la moisson elle-même

> **Rendement décroissant : la moisson est ÉPUISÉE. NE PAS RE-MOISSONNER.**

**Ce que 5 617 repos nous ont vraiment donné :** *cinq* outils de vérité, *une* loi confirmée
(la domination), et *la certitude* que personne n'a l'edge qu'on cherchait.

> ***Le corpus ne nous a pas donné une stratégie. Il nous a donné les moyens de savoir que la
> nôtre n'en était pas une.*** **Et ça valait le voyage.**

---

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
