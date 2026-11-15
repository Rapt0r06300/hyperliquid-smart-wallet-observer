# PREENREGISTREMENT — l'objectif de 5 USD/jour sur 350 USD

**Gele le 14/11/2026, AVANT tout regard sur la fenetre de la campagne (13-19/11).**

## Pourquoi ce document existe

La mission est « 5 USD/jour **prouve** ». Or le mot *prouve* n'a plus de sens sur les donnees qui
ont servi a construire la strategie. J'ai consulte la seconde moitie de l'historique (juillet-
novembre) pour choisir **l'horizon de detention, `k`, la ponderation, le taux de couverture et le
nombre de tranches**. A force de regards, un echantillon de test devient un echantillon
d'entrainement : c'est exactement le mecanisme qui produit un PBO de 0,81.

Le seul temoin encore intact est la **fenetre de la campagne du 13 au 19/11**, que je n'ai jamais
examinee pour cet usage. Ce document fixe la configuration AVANT de la regarder, pour que la mesure
du 19/11 soit un **jugement** et non une recherche.

**Regle absolue : aucun parametre ci-dessous ne peut etre modifie apres la premiere lecture des
donnees de campagne. Si le resultat decoit, le resultat decoit.**

## La configuration, gelee

| Parametre | Valeur | Pourquoi cette valeur |
|---|---|---|
| Signal de classement | `funding` brut | Le momentum direct est refute (-44,2 %) ; la variation aussi ; le demoyennage transversal ne change aucun rang (vide par construction) |
| Sens du livre | **inverse** : long le funding haut, short le funding bas | Le carry est refute (-41,3 %/an) une fois le prix compte |
| `k` par jambe | **3** | Retenu pour sa **STABILITE** : positif sur les trois tiers (+106,6 %, +91,4 %, +63,3 %), ecart-type 17,9 contre 94,4 pour k=1. **Pas pour son sommet.** |
| Detention | **96 h** | Plus faible ecart train/test du balayage d'horizon (1,4 point contre 53,5 a 24 h) ; critere enonce avant de regarder les USD |
| Fenetre de classement | **96 h** | Convention ; le balayage de fenetre s'est revele BRUITE (motif qui alterne), donc aucun gagnant n'y a ete elu |
| Tranches | **8**, une entree toutes les **12 h** | Le decoupage ne change pas le rendement moyen, seulement le moment d'entree ; gain x2,4 stable en train, en test et sous deux hypotheses de cout |
| Taux de couverture | **100 %** (dollar-neutre) | Balayage monotone : la couverture complete gagne APRES dimensionnement, meme si la jambe longue perd -9,2 % seule |
| Ponderation | **egale en dollars** | 1/volatilite est refute partout (+24,3 % contre +64,6 %) : l'edge vit dans les coins volatils |
| `mmr` | **5 %** (palier alt 10x) | Le palier le plus contraignant du livre decide, jamais la moyenne |
| Facteur de securite | **4,0** | Choix de RISQUE, pas d'optimisation. Liquidation si le livre perd 30,0 % |
| Cout retenu | **17,7 bps** par jambe et par aller-retour (taker) | 4,5 de frais + **4,36 de slippage MESURE** sur 60 000 carnets. **L'hypothese maker (5,9 bps) n'est PAS retenue** : le taux de remplissage passif a l'echelle de l'heure n'est pas mesure |

## Ce qui sera mesure le 19/11, et rien d'autre

1. **Le PnL en USD/jour** de cette configuration exacte sur la fenetre 13-19/11.
2. **Le taux de remplissage passif a l'echelle de l'HEURE** — jamais mesure (seules 30 s l'ont ete).
   S'il est eleve, le cout tombe a 5,9 bps et le resultat monte ; sinon l'hypothese taker reste.
3. **Le signal de positionnement des leaders** (`position`, `szi` signe, 46 vaults, 179 coins) en
   remplacement du funding, a 24 h de detention. Hypothese : le funding mesure l'**encombrement**
   (c'est pourquoi le momentum direct echoue), et les positions des leaders le mesurent
   **directement**, donc en moins bruite.

## Attentes chiffrees, ecrites d'avance

| Hypothese de brut | Au facteur 4 | Verdict si atteint |
|---|---|---|
| Tiers le plus faible, +63,3 %/an | **2,03 USD/jour** | la cible n'est pas tenue, mais la strategie est reelle |
| Moyenne des trois tiers, +87,1 %/an | **2,79 USD/jour** | idem |
| Tiers le plus fort, +106,6 %/an | **3,41 USD/jour** | idem |

**Aucune de ces trois lignes n'atteint 5 USD/jour au facteur 4.** Les 5 USD/jour n'apparaissent qu'au
facteur 2 (liquidation a -17,5 %) ET avec le tiers le plus fort : **5,85 USD/jour**. Autrement dit,
**la cible exige de cumuler le dimensionnement le plus agressif et l'hypothese de rendement la plus
favorable.** C'est dit avant la mesure, pas apres.

## Ce qu'il faudrait pour que 5 USD/jour soit atteignable prudemment

| Au facteur | Brut requis | Mesure disponible | Manque |
|---|---|---|---|
| 4 | 156 %/an | 63 a 107 %/an | x1,5 a x2,5 |
| 3 | 124 %/an | 63 a 107 %/an | x1,2 a x2,0 |
| 2 | 91 %/an | 63 a 107 %/an | atteint par le haut de la fourchette |

**Les deux voies identifiees pour combler l'ecart, par ordre d'effet attendu :**
1. **Elargir l'univers de funding de 90 a plus de 200 coins.** Il y a des bougies pour 263 coins et
   la venue liste plus de 200 perps : le funding n'est collecte que sur 90. Elargir donne des queues
   plus extremes (signal plus fort) **et** plus de diversification (D plus bas) — les deux termes de
   `brut/D` dans le bon sens. **C'est un manque de COLLECTE, pas de strategie.**
2. **Le signal des leaders**, s'il mesure l'encombrement mieux que le funding.

**Et la voie qui ne depend pas de moi : le capital.** A 161 %/an sur capital, 5 USD/jour demande
**1 134 USD** au lieu de 350. C'est une decision, pas une mesure.
