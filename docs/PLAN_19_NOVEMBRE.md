# Plan du 19 novembre — ce que la fin de collecte debloque

**Ecrit le 14/11.** Le resultat obeit a une seule identite :

```
USD/jour = capital x brut / (D x facteur + mmr) / 365
```

Chaque idee ci-dessous dit **quel terme elle attaque**. Une idee qui monte le brut en gonflant D ne
sert a rien : c'est la lecon de la jambe short seule (+95,5 % de brut, -42,7 % de repli, et un
resultat INFERIEUR apres dimensionnement).

**Etat au 14/11** (univers 94 coins, facteur 4) : brut 73,8 %/an, D 2,79 %, mmr **12,32 % mesure**,
levier 4,26x -> **+3,02 USD/jour sur 350 USD**. Borne dure : avec un repli nul, le mmr seul plafonne
a 5,74 USD/jour en taker.

**14 familles sur 22 n'ont jamais ete ouvertes**, soit ~2,8 Go. Voici ce qu'elles valent.

---

## A. Attaquer le BRUT (le signal)

### A1. Positionnement des leaders — `position`, 15 Mo *(priorite 1)*
**Ce n'est pas un espoir, c'est une deduction d'une mesure.** Le momentum direct PERD (-44,2 %)
alors que le funding GAGNE : le funding ne mesure donc pas la performance passee, il mesure
**l'encombrement du positionnement**. Or `position` porte le `szi` signe de 46 vaults sur 179 coins :
**l'encombrement DIRECTEMENT OBSERVE**, sans le proxy bruite qu'est le taux de funding.
*Signal propose* : part signee du notionnel par coin, `somme(szi x px) / somme|szi x px|`, dans
[-1, 1] — sans echelle, donc comparable d'un coin a l'autre. Livre inverse : long les coins ou les
leaders sont le plus nets-longs, exactement l'analogue de « long le funding haut ».
*Jugeable le 19* : 192 h d'historique -> horizon 24 h, departs /6 h, ~28 observations. Le balayage a
deja trouve 24 h rentable.
*Si le signal est 1,5x plus propre* : brut 73,8 % -> ~110 %, et la borne dure change.

### A2. Ordres en attente des leaders — `leader_orders`, 3 Mo *(priorite 2)*
Le funding reflete des positions **deja prises**. `leader_orders` porte le `notionnel_par_coin` des
deux cotes : c'est l'encombrement **AVANT** qu'il devienne une position. Si l'encombrement predit,
l'encombrement *anticipe* devrait predire mieux — et plus tot, donc avec moins de coins deja
chers. **C'est le seul signal de la liste qui soit en AVANCE sur le funding.**
*Piege a eviter* : un ordre affiche peut etre annule. Il faut mesurer le taux d'annulation avant de
croire au signal, sinon on classe sur du bluff.

### A3. Encombrement normalise par l'interet ouvert — `asset_ctx.oi`, 88 Mo
Le funding brut melange « ce coin est encombre » et « ce coin est petit ». `oi` permet de normaliser
le positionnement par la taille du marche. Mesure directe, aucune nouvelle collecte.

### A4. Ecart de funding entre venues — `venue_dispersion` + `venue_book`, 58 Mo *(MESURE le 14/11 : NON CONCLUANT)*
**La famille est plus riche que prevu** : elle porte `hl_bps_h` **et** `bin_bps_h` — les taux de
funding horaires des DEUX venues — plus `ecart_prix_bps`. L'edge etait donc mesurable
immediatement, et je l'ai fait : **914 784 releves, 208 coins, mais seulement 90 heures
(3,8 jours)**.

```
HL paie plus que Binance : 59,6 % des releves   (l'etude publiee : 65-72 %)
ecart MOYEN  : -0,0384 bps/h  ->  -3,36 %/an
ecart MEDIAN : +0,0625 bps/h  ->  +5,48 %/an
```

**La moyenne et la mediane sont de SIGNES OPPOSES.** Signature d'une queue gauche epaisse : HL paie
plus la plupart du temps, mais les episodes inverses sont assez gros pour renverser la moyenne — et
**c'est la moyenne qu'un PnL accumule, pas la mediane**. Une strategie calibree sur la mediane
paraitrait rentable et perdrait de l'argent.
**Conclusion : avec 3,8 jours contre deux ans dans l'etude, rien n'est concluable. C'est un chantier
de COLLECTE, pas de mesure du 19.** A reprendre quand la famille aura plusieurs mois.

### A4-bis. Ce que l'etude publiee disait, et qu'il faut garder sous les yeux
L'etude lue le 14/11 mesure que **la venue on-chain paie plus que la centralisee 65-72 % des heures,
pour 8,5-11,4 % annualises**, avec un controle a zero entre deux venues de meme type. **C'est un
SECOND edge, independant du premier** — et deux edges independants baissent D exactement comme les
cinq horizons l'ont fait (x2,07). Double effet : brut ET D.
La regle a seuil sur cet ecart finit a **-9 a -15 % net** (l'execution consomme 3x le brut) ; seule
la regle patiente a 30 jours gagne (+2,7 a +5,4 %). Le niveau mean-reverte en **1,5-3,5 h** alors
qu'un aller-retour demande **100-135 h** pour se rembourser : « la direction du signal est un regime
de plusieurs mois, son niveau est du bruit horaire ». Et la marge d'erreur est mince : la regle
patiente supporte un cout de 250 bps, la regle active meurt au-dela de 8 bps.

### A5. L'univers elargi — 94 -> 261 coins
Deja en cours (budget funding porte a 7 200 s). Des queues plus extremes **et** plus de
diversification : les deux termes. **Simple relance de l'outil officiel, aucun code.**

### A6. Un vrai z-score transversal
Mon test de demoyennage etait **vide par construction** : retirer la moyenne transversale a une
heure donnee enleve la meme constante a tous les coins, donc ne change aucun rang. Diviser par la
**DISPERSION** transversale, elle, change les rangs. Non teste.

---

## B. Attaquer D (le repli, donc le levier)

### B1. Les cascades de liquidation — `liquidation`, 1 Mo *(priorite 1 du RISQUE)*
**J'ai passe la journee a avertir que ce livre est « long la foule, donc le combustible d'une
cascade » — sans jamais le mesurer.** La venue en a connu une qui a detruit 7,4 Md USD d'interet
ouvert et liquide plus de 1 000 comptes. `liquidation` porte les evenements reels : on peut enfin
mesurer **ce que le livre fait PENDANT** une cascade mesuree.
*Deux issues, toutes deux utiles* : s'il traverse, le facteur 4 est peut-etre trop prudent et le
levier monte ; s'il casse, le facteur doit monter et le chiffre baisse. **Dans les deux cas on
cesse de deviner.**

### B2. Combiner des edges independants
Si l'edge inter-venues (A4) est decorrele de l'edge de funding, les faire tourner ensemble baisse D
sans toucher au brut moyen — le mecanisme exact qui a double le resultat avec les cinq horizons.
**C'est le levier le plus fiable de toute la liste, parce qu'il ne depend d'aucune prediction.**

### B3. `overshoot`, 2 Mo — **ouvert le 14/11, et ce n'est PAS ce que je croyais**
J'avais suppose « une mesure d'impact ou de reversion ». La famille porte en realite
`mid_at_event` **et `mid_fwd_15s / 30s / 60s / 120s`**, plus `mark_px` et `oracle_px` : **des mids
FUTURS autour d'evenements**, donc une serie de markout deja constituee. Utilisable directement
pour le markout et pour mesurer la reversion apres un choc — sans refaire la jointure couteuse que
`mesurer_maker_coffre` effectue a la main.
*Lecon de methode* : ouvrir une famille coute une minute, theoriser sur son nom coute une erreur.

---

## C. Attaquer le COUT

### C1. Le remplissage passif a l'echelle de l'HEURE *(priorite 2)*
Le seul chiffre qui decide si le plafond maker (+3,76) est une estimation ou un reve. Les 66,2 %
mesures portaient sur **30 secondes** ; un signal a 96 h peut attendre des heures. Mesurable sur
`book_l2` + `micro_trades` sur de longues fenetres.
*Enjeu chiffre* : cout 17,3 -> 5,9 bps par jambe, soit **+24 % de brut**.

### C2. Le spread par coin et par heure — `bbo` (847 Mo) + `trades_marche` (627 Mo)
Je retiens **un seul** chiffre de slippage (4,17 bps) pour 94 coins. Or il va de 2,8 a plus de 21 bps
selon le coin et l'heure. Un modele de cout par coin permettrait d'eviter les coins chers **a signal
egal** — et c'est le seul filtre qui n'ampute pas le signal, contrairement au filtre par palier de
levier qui l'a INVERSE (-44,9 %).

---

## INVENTAIRE DU 15/11 : six classes JAMAIS testees, et pourquoi

**« A-t-on assez de strategies pour ces donnees ? » NON — mais le goulot n'est pas le manque
d'idees : les familles riches ne sont collectees qu'a 3-9 %.**

```
famille            profondeur   collecte    classe de strategie possible
funding_history     1 059 j      8,9 %      carry transversal        -> REFUTE
candle 1d           2 279 j      8 % (21/261) momentum / reversion mensuels
asset_ctx             4,6 j      vivante    base (premium_bps), OI, liquidite
position              2,9 j      vivante    encombrement des leaders (H1)
leader_orders         2,9 j      vivante    encombrement ANTICIPE (H2)
liquidation           2,8 j      vivante    fade de cascade
overshoot             vivante    vivante    reversion apres choc (mid_fwd 15-120 s)
fills_forward         1,3 Go     OK         les 8 % de fills AGRESSIFS seulement
```

**Ce que chaque classe apporte et que le funding n'a pas :**

* **La base (`premium_bps`)** — la dislocation INSTANTANEE, quand le funding est le taux DEJA
  REGLE. Mesure du 15/11 : mediane **-7,6 bps**, p5 -31,5, **p95 +165,2** (tres asymetrique a
  droite ; +165 bps = un perp a 1,65 % au-dessus de son oracle). Classe documentee depuis des
  decennies. **Jamais essayee ici.**
* **Le fade de cascade (`liquidation`)** — evenementiel donc RARE : les frais s'amortissent sur un
  gros mouvement au lieu d'etre payes en continu. **La seule classe ou le cout n'est pas le probleme
  principal** — tout le reste de ce labo est mort par les frais.
* **Les fills AGRESSIFS des leaders** — j'ai etabli que **92 % de leurs fills sont PASSIFS**, donc
  sans information (le marche est venu a eux). **Les 8 % agressifs n'ont jamais ete isoles ni
  testes** : dix fois moins nombreux, mais potentiellement les seuls informatifs.
* **`overshoot`** — porte deja `mid_fwd_15/30/60/120s`, soit une serie de markout constituee.

**L'ERREUR DE METHODE QUE CET INVENTAIRE A REVELEE.** J'ai teste le momentum a **24-336 heures** et
l'ai declare refute (-44,2 %). La litterature le documente a **1-12 MOIS**. Et les bougies
JOURNALIERES couvrent **2 279 jours** (aout 2020) : je ne les utilisais que comme RESULTAT, jamais
comme SIGNAL. Premier test mensuel lance sur ce qui existait — **21 coins seulement** — momentum et
reversion entre `t = -1,45` et `+1,34`, non concluants car **la section etait dix fois trop
etroite**. A refaire a 261 coins. Tendance a noter sans y croire : la **reversion** battait le
momentum a 30-90 jours, l'inverse du cas actions et coherent avec un univers d'altcoins.

**PRIORITE DE COLLECTE RECALCULEE : LES BOUGIES JOURNALIERES PASSENT DEVANT TOUT.** Une page de
`candleSnapshot` rend 5 000 bougies, donc **2 280 jours tiennent en UNE page par coin**. Les
240 coins manquants demandent **1,8 h**, contre **94 h** pour le funding — **quarante fois moins
cher, pour la fenetre mesurable la plus large du projet** (248 jours aujourd'hui, jusqu'a 2 279).

## D. Les pieges — a ne PAS faire

### D1. Choisir les leaders sur leur PnL passe — `vault_portfolio`, `vault_ledger`
`apr_affiche` et l'historique de PnL sont la tentation evidente. **C'est le mecanisme meme du PBO de
0,81** : selectionner sur la performance passee d'un echantillon. Si ces donnees servent, ce doit
etre comme **caracteristique causale testee**, jamais comme critere de selection.

### D2. Copier les fills des leaders — `fills_backfill`, 348 Mo
C'est ce que faisait `fast_follow`, **rejete a tous les horizons <= 300 s meme a spread nul**, donc
tue par les frais et non par l'execution. Et 92 % des fills des leaders sont PASSIFS : le marche est
venu a eux, il n'y a pas de signal a copier. Ne pas y revenir sans raison nouvelle.

### D3. Baisser le facteur de securite pour atteindre la cible
Le facteur 1,5 affiche +5,24 USD/jour en maker. Mais c'est un **choix de risque deguise en
resultat** : la liquidation tombe a -16,5 % alors que le pire repli mesure est de 2,79 % sur
211 jours d'UN SEUL regime. Si le facteur doit baisser, que ce soit une decision assumee, pas une
facon d'atteindre un chiffre.

---

## Ordre d'execution propose pour le 19

| # | Action | Terme | Cout |
|---|---|---|---|
| 1 | Relancer l'outil officiel sur l'univers elargi | brut + D | aucun code |
| 2 | Ouvrir `liquidation` et mesurer le livre pendant les cascades | **D** | petit |
| 3 | Signal de positionnement des leaders (`position`) a 24 h | **brut** | moyen |
| 4 | Taux de remplissage passif horaire | cout | moyen |
| 5 | Ordres en attente (`leader_orders`) + taux d'annulation | brut | moyen |
| 6 | `overshoot` : mids futurs deja constitues, pour le markout | cout + D | petit |

**Retire de la liste du 19** : l'ecart inter-venues (A4). Mesure le 14/11, il n'a que 3,8 jours
d'historique et sa moyenne et sa mediane sont de signes opposes. Il revient quand la collecte aura
plusieurs mois — pas avant.

**Regle qui tient sur tout** : chaque idee se juge sur `brut/(D x facteur + mmr)` **apres**
dimensionnement, jamais sur le brut. Et tout nouveau signal retenu change la configuration, donc
**exige un nouveau preenregistrement sur une fenetre jamais regardee** — exactement comme la v2 a
remplace la v1.
