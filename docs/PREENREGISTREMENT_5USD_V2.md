# PREENREGISTREMENT v2 — 5 USD/jour sur 350 USD, portefeuille MULTI-HORIZONS

**Gele le 14/11/2026. REMPLACE la v1** (`PREENREGISTREMENT_5USD.md`), qui portait sur un seul
horizon de 96 h et sur un univers de 90 coins.

## Pourquoi une v2, et pourquoi la v1 ne doit plus etre jugee

La v1 a ete gelee, puis **deux changements materiels** sont intervenus le meme jour :

1. **La diversification par horizon.** Le livre tourne desormais sur **cinq horizons simultanes**
   (24, 48, 96, 168, 336 h), equiponderes. Le repli du portefeuille tombe de **6,35 % a 2,79 %**
   pendant que le brut reste identique (+68,8 % -> +70,5 %), ce qui **double le levier autorise**.
   Gain stable sur toutes les periodes : **x1,52 a x2,27, jamais moins**.
2. **L'elargissement de l'univers de funding**, de 90 vers 261 coins (en cours de collecte).

**Je l'avais ecrit dans la v1 : « si l'elargissement change le resultat, c'est un NOUVEAU protocole
a juger sur une fenetre encore jamais regardee ».** C'est le cas, et la regle s'applique a moi.
La v1 reste au depot comme trace de ce qui a ete promis avant de mesurer ; elle ne doit plus servir
de reference.

## La configuration, gelee

Identique a la v1 sauf les lignes marquees **NOUVEAU**.

| Parametre | Valeur | Pourquoi |
|---|---|---|
| Signal | `funding` brut, livre **inverse** | Le carry est refute (-41,3 %/an) ; le momentum direct (-44,2 %) ; la variation du funding aussi |
| `k` par jambe | **3** | Stabilite sur les trois tiers (ecart-type 17,9 contre 94,4 pour k=1), **pas** le sommet |
| **Horizons** | **NOUVEAU : 24, 48, 96, 168, 336 h, equiponderes** | Tous positifs au balayage, donc cinq livres imparfaitement correles. **Aucune selection** : le meilleur sous-ensemble trie a la main ne fait que 3 % de mieux |
| Tranches | **8**, une entree toutes les **12 h** | Diversifie le MOMENT d'entree ; x2,4, a rendement moyen inchange |
| Couverture | **100 %** (dollar-neutre) | La jambe longue perd -9,2 % seule mais divise le repli par 3,5 : elle se paie en RISQUE |
| Ponderation | **egale en dollars** | 1/volatilite refute partout : l'edge vit dans les coins volatils |
| `mmr` | **5 %** (palier alt 10x) | Le palier le plus contraignant decide, jamais la moyenne |
| Facteur de securite | **4,0** | Choix de RISQUE. Liquidation si le livre perd **16,1 %** |
| Cout | **taker, slippage MESURE et PERSISTE** (`runtime/data/slippage_mesure.json`) | 4,5 bps de frais + ~4,2 bps mesures sur 80 000 cas. **Le scenario maker n'est PAS retenu** : le remplissage passif a l'echelle de l'heure n'est pas mesure |
| **Repli de dimensionnement** | **NOUVEAU : calcule sur TOUTE l'histoire, impose a chaque periode** | Sans cela une periode courte et chanceuse gagne du levier par hasard. Piege rencontre **trois fois** dans la session |

## Attentes chiffrees, ecrites d'avance

Sur l'historique disponible au 14/11 (90 coins, 211 jours), outil `tools/mesurer_strategie.py` :

| Periode | taker (retenu) | maker (plafond) |
|---|---|---|
| Pire tiers (**borne basse honnete**) | **+3,78 USD/jour** | +4,89 |
| Hors echantillon (TEST) | **+4,56 USD/jour** | +5,69 |
| Meilleur tiers | +5,19 USD/jour | +6,34 |

**La cible de 5 USD/jour est donc ATTEINTE dans le meilleur tiers et dans le scenario maker, et
MANQUEE de 9 % dans le cas de reference.** C'est dit avant la mesure de jugement, pas apres.

## Ce qui sera juge, et la date reelle

La fenetre de jugement commence **apres le 14/11**, la seule qui n'ait jamais ete regardee. Une
fenetre complete exige la fenetre de classement **plus** l'horizon le plus long (336 h = 14 jours),
et 8 tranches : **le premier verdict n'est donc pas avant le 1er decembre** environ. Le funding
s'accumule seul tant que le collecteur tourne.

Seront mesures, et rien d'autre :
1. **Les USD/jour** de cette configuration sur la fenetre postérieure au gel.
2. **Le taux de remplissage passif a l'echelle de l'HEURE** — jamais mesure (seules 30 s l'ont ete).
   C'est lui qui decide si le plafond maker devient une estimation.
3. **Le signal de positionnement des leaders** en remplacement du funding. Hypothese fondee sur une
   mesure : le momentum direct echoue (-44,2 %) alors que le funding reussit, donc **le funding
   mesure l'ENCOMBREMENT et non la performance passee** — et les positions des leaders mesurent cet
   encombrement **directement**, donc en moins bruite.

## Calendrier des verdicts, preenregistre

**Cet ajout est ecrit le 14/11, AVANT qu'une seule fenetre de jugement n'existe** (l'outil de
jugement en compte zero a cette date). Il ne change aucun parametre : il declare QUAND regarder,
pour qu'un verdict partiel soit une etape annoncee et non un coup d'oeil opportuniste.

Trois contraintes s'enchainent. Le gel est le 14/11, donc la premiere decision propre est le 15.
Il faut 8 tranches, soit 8 decisions a 12 h d'intervalle : la 8e tombe le 18 a midi. Et un resultat
n'est jugeable que COMPLET : decision + horizon.

| Horizon | 8e decision | Resultat complet | Ce qui est juge |
|---|---|---|---|
| 24 h | 18/11 12h | **19/11 12h** | verdict partiel : l'horizon court seul |
| 48 h | 18/11 12h | **20/11 12h** | verdict partiel |
| 96 h | 18/11 12h | **22/11 12h** | verdict partiel : l'horizon de la v1 |
| 168 h | 18/11 12h | **25/11 12h** | verdict partiel |
| 336 h | 18/11 12h | **02/12 12h** | **le portefeuille COMPLET** |

**REGLE QUI REND CES VERDICTS PARTIELS LEGITIMES** : ils sont **rapportes, jamais utilises pour
re-choisir**. Si le 24 h decoit le 19/11 et que j'en retirais le 24 h de la configuration, je
reprendrais la selection sur des donnees de jugement — exactement ce que ce document existe pour
empecher. Un verdict partiel decevant est une information sur la strategie, pas une invitation a
la modifier.

**Ce que chaque verdict partiel vaut** : un horizon seul porte un repli bien plus eleve que le
portefeuille (6,35 % pour le 96 h contre 2,79 % pour les cinq), donc **moins de levier et moins de
USD/jour**. Un partiel faible n'infirme donc PAS le portefeuille complet, et un partiel fort ne le
confirme pas : seul le 2 decembre juge la configuration retenue.

**Regle absolue, inchangee : aucun parametre ci-dessus ne bouge apres la premiere lecture des
donnees de jugement. Si le resultat decoit, le resultat decoit.**
