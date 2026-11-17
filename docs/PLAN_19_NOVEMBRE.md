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

---

# AJOUT DU 15/11 (soir) — LA PROFONDEUR ETAIT GELEE, ET LA PRIME DORMAIT DANS LE FUNDING

Quatre trouvailles de la soiree, dont deux changent le plan ci-dessus.

## T1. Le funding ne pouvait PLUS JAMAIS s'approfondir (defaut, repare)

`passe_funding` ne connaissait qu'un front : l'horodatage le plus RECENT par coin, et elle ne savait
qu'AVANCER (`a = max(now - PROFONDEUR, dernier + 1)`). Pour un coin deja tenu a jour sous l'ancien
plafond de 208 jours, `dernier` vaut ~maintenant, donc `a` vaut ~maintenant, donc le coin etait
declare « a jour »... **a 211 jours de profondeur**.

Etat mesure du coffre ce soir-la : **118 coins avec du funding, profondeur mediane 211 jours, et 3
coins seulement a 1 100 jours** — exactement les trois partis de zero. Porter
`PROFONDEUR_FUNDING_JOURS` de 208 a 1 100 le 15/11 au matin n'avait donc servi qu'aux coins neufs,
et la fenetre mesurable du livre (l'INTERSECTION des historiques) etait condamnee a rester a
211 jours quoi qu'on collecte.

**Repare** : un second front (`funding_ancien`), qui CREUSE page par page vers le passe, se
reconstruit du ruban au premier passage, et s'arrete sur une sonde quand le coin est au bout de son
histoire. Verrouille par `tests/test_funding_profondeur_deux_fronts.py` (9 tests).

## T2. Le creusage se fait EN RONDES, et c'est ce qui le rend utile

L'ancienne boucle vidait un coin entierement avant de passer au suivant : **41 minutes pour 2 coins
sur 261**. Or ce qu'une strategie transversale peut mesurer est l'INTERSECTION des historiques de
son livre : trois coins parfaits et 258 coins pauvres laissent la fenetre **inchangee**. Les
41 minutes n'avaient donc rien rapporte de mesurable.

Une page par coin et par ronde fait monter le plancher commun **des la premiere ronde**, et un arret
a n'importe quel moment laisse une profondeur UNIFORME. Meme cout total, valeur immediate.

## T3. La PRIME (`premium_bps`) a la meme profondeur que le funding — pas 4,6 jours

**C'est la trouvaille qui change le plan du 19.** Le test de la base (`premium_bps`) etait repousse
au 19/11 « faute d'historique », parce que je le lisais depuis `asset_ctx` (4,6 jours de collecte).

Or `fundingHistory` rend `premium` **dans la meme reponse que le taux**, et le collecteur l'ecrit
depuis toujours : verifie ce soir, **100 000 lignes sur 100 000 de `funding_1h.jsonl` portent un
`premium` non nul**. La base est donc deja mesurable sur **211 jours x 118 coins** aujourd'hui, et
sur ~1 100 jours quand T1 aura creuse.

| | avant | reellement disponible |
|---|---|---|
| source | `asset_ctx_tape` | `funding_1h.jsonl` (champ `premium`) |
| profondeur | 4,6 jours | **211 j (mediane), 1 100 j a terme** |
| coins | 72 liquides | 118, puis 263 |
| `t` possible | 0,15-0,58 | a mesurer — l'echantillon est x46 |

**Action** : remonter le test de la base en tete de liste du 19 ; il ne depend plus de la collecte.
Le `t` croit en racine de `n` : x46 d'echantillon, c'est **x6,8 sur le `t`** si l'effet tient.

## T4. Le pas 4 h existait et n'etait pas collecte (833 jours)

Le plafond de `candleSnapshot` est de **5 000 BOUGIES**, donc il depend du pas. Il manquait le pas
intermediaire entre l'horaire (208 j) et le journalier (1 101 j) : **4 h = 833 jours a 6 points par
jour**. Le journalier est profond mais grossier — un horizon de 96 h n'y tient que 4 points et
l'HEURE d'entree y disparait. Le 4 h garde l'heure sur ~2,3 ans.

Ajoute partout (collecteur, certificateur, contrat de couverture, campagne) : **219 167 jours-coins
manquants pour 4,5 h de requetes**, le meilleur rendement du plan de rattrapage.

## Ce qui est branche pour y arriver

* `tools/rattrapage_complet.py` — le rattrapage COMPLET en une commande, appele par le
  **certificateur** (etape 1/2 : completer ; etape 2/2 : sceller). Ordre calcule en **jours-coins
  gagnes par seconde de requete**, precedences respectees (un funding sans prix ne mesure rien),
  **une tache a la fois**, garde memoire active, une ligne par coin a l'ecran.
* `src/hl_observer/ops/rattrapage_plan.py` — le plan, pur et teste (18 tests).
* `src/hl_observer/collection/debit_adaptatif.py` — le debit n'est plus fige a 10 % du plafond : il
  monte par paliers tant que la venue ne refuse pas, et se divise sur un refus (AIMD, 11 tests).
  **112 h de requetes a 100 u/min deviennent ~19 h a 600 u/min.**
* Univers suivi : un coin dont l'historique est commence **reste suivi** meme apres l'archivage de
  session, qui faisait tomber l'univers de 261 a 216 coins en silence.

---

# 16/11/2026 — LE COFFRE EST LE MAGASIN PRINCIPAL, ET IL MANQUAIT UNE PORTE

## T5. Le rattrapage ecrivait a cote du coffre quand la campagne etait fermee

Le labo et le moteur ne lisent QUE le coffre certifie : une donnee ecrite dans `runtime/history`
et non scellee leur est **invisible**, quelle que soit sa taille. La certification tournait bien
toutes les 30 min — mais comme **collecteur de la campagne** (`coffre-certificateur`), donc
seulement pendant qu'elle tourne. Un rattrapage lance collecteurs fermes, ou dont la fenetre se
ferme en cours de route (15/11 21 h 32), laissait ses milliers de jours-coins dehors jusqu'a ce que
quelqu'un relance la campagne.

**Fait** : `tools/rattrapage_complet.py` scelle lui-meme a la fin de son passage
(`sceller_le_coffre`, `decider_scellement`), et l'avancement porte le resultat
(`scellement.fait`). `--sans-scellement` existe pour « Certificateur Coffre Fort.cmd », qui scelle
de toute facon a son etape 2/2. Un scellage qui echoue est **dit** : « ces donnees restent HORS du
coffre, donc invisibles pour le labo ».

## T6. Deux scelleurs, un seul registre d'octets

Consequence immediate du T5 : le scellage du rattrapage et le periodique peuvent tomber ensemble.
Ils ecrivent le MEME `SOURCES_TRAITEES.json`, qui porte pour chaque ruban le dernier octet scelle.
Le dernier a ecrire efface les decalages de l'autre : la donnee survit, le **registre de ce qui est
scelle** non — et c'est lui qui dit au labo ce qu'il peut lire. `sceller_coffre_local.py` n'avait
aucun verrou.

**Fait** : `src/hl_observer/ops/verrou_pid.py` (verrou PID partage, Windows-safe : `os.kill(pid,0)`
TUERAIT le processus, `tasklist` se lit en OCTETS sur un Windows francais). Le scelleur le prend
dans `_point_d_entree`, et **rend 0** s'il est deja pris : rien n'a echoue, un autre passage couvre
les memes octets, et rougir ferait croire a une panne du coffre a chaque superposition. 12 tests
(`tests/test_scellement_rattrapage.py`), dont « le verrou est rendu meme si la passe echoue ».

## T7. La fermeture accidentelle du 15/11 : le trou MESURE

Mesure sur le ruban `micro_bbo_1794776458794933400.jsonl.gz`, qui couvre 21 h 17 -> 22 h 00 :

| minute | messages | | minute | messages |
|---|---|---|---|---|
| 21:30 | 4 832 | | 21:38 | 3 896 |
| 21:31 | 5 369 | | 21:39 | 3 495 |
| 21:32 | **1 603** (partielle) | | 21:40 | 3 608 |
| 21:33 -> 21:37 | **absentes** | | 21:41 | 4 601 |

**Trou = 5 minutes et quelques secondes, et rien d'autre.** Jours scelles au coffre :
13/11 **27 671 328**, 14/11 **23 353 989**, 15/11 **22 062 757**, 16/11 **11 117 722** — 20
familles chaque jour, sur 150 522 571 enregistrements et 2 282 jours distincts au total.

## T8. Le correctif du battement de microstructure est SUR LE DISQUE, pas EN VIE

`heartbeats/lab-microstructure.json` est fige depuis 16,9 h avec `n_ecrites_cumul = 0`, alors que
le collecteur ecrit normalement (5,7 M messages, 93,9 msg/s, fichiers touches a la seconde).
Pourquoi : `tools/collecter_lab_microstructure.py` a ete corrige a **21 h 43** le 15/11, et le
processus qui tourne a demarre a **21 h 37** — six minutes avant le correctif. Il ne se relance pas
tout seul tant qu'il vit.

**Reste a faire** : relancer CE collecteur (quelques secondes de microstructure perdues) pour que
la detection de mort fonctionne jusqu'au 19/11. Decision de Florent : on ne touche pas a une
collecte autorisee en cours sans son mot.

## T9. `lab-ctx` : un battement ORPHELIN qui fait un faux mort

`heartbeats/lab-ctx.json` est fige depuis 112 jours — mais `lab-ctx` **n'est pas au registre des
collecteurs**. Ce n'est pas un collecteur mort, c'est un fichier laisse par un collecteur retire.
Un controle qui lit tout le dossier `heartbeats/` le compte comme une panne. A nettoyer ou a
ignorer explicitement, sinon le signal de sante contient un faux positif permanent.

## T10. Ctrl+C sur le rattrapage : la garantie est maintenant TENUE et DITE

Exigence de Florent (16/11) : « le rattrapage doit pouvoir etre ferme via Ctrl+C sans perdre
aucune donnee ». Ce qui etait deja vrai : chaque page s'ecrit en **lignes entieres** sur le ruban
avant la suivante (`_ecrire_funding` ferme son `with`, donc vide son tampon), et l'etat du backfill
est remplace **atomiquement** (`tmp` par PID puis `os.replace`), apres chaque page.

Ce qui etait FAUX : aucun des deux outils n'attrapait `KeyboardInterrupt`. Ctrl+C remontait une
pile d'erreur et sautait l'ecriture du bilan — le fichier d'avancement restait sur `EN_COURS`
**pour toujours**. Les donnees etaient saines, l'etat MENTAIT.

**Fait** : `rattrapage_complet.py` attrape le Ctrl+C, ecrit `etat: CTRL_C`, rend le verrou
(sinon six heures de blocage), rend **130** pour que le lanceur le distingue d'un succes, et ne
lance PAS de scellage — on ne fait pas attendre plusieurs minutes celui qui vient d'interrompre ;
il est DIT ou en sont les donnees. `backfill_candles_vaults.py` a son propre point d'entree propre.
`RATTRAPAGE.cmd` reconnait le code 130. 6 tests, dont un bout en bout qui interrompt une tache et
verifie l'etat ecrit, le verrou rendu et le code de sortie.

## T11. Battement de microstructure : le correctif tourne enfin

Diagnostic du jour : le correctif etait **sur le disque** (fichier modifie a 21 h 43 le 15/11) mais
le processus tournait depuis 21 h 37 — six minutes avant. Il ne se relance pas tant qu'il vit.

Chaine verifiee avant de toucher a quoi que ce soit : `watch_economic_collectors.py` ->
`run_bounded_collector.py --name lab-microstructure` -> le collecteur. Le wrapper est une boucle
infinie qui relance l'enfant 30 s apres sa mort, avec le code du disque. Donc tuer l'ENFANT suffit
— et une assertion sur l'identite du parent a d'ailleurs arrete une premiere tentative qui visait
le mauvais PID.

**Resultat mesure** : enfant 97320 arrete a 14:43:45, relance en 57024 a 14:44:15, puis 4
battements canoniques distincts a 20 s d'intervalle, ecritures 0 -> 2 928 -> 5 148 -> 7 296, `ack
True`, horodatage d'echange present, 0 reconnexion. C'est exactement ce que `preuve_de_vie` exige.

## T12. PIEGE : un bail qui « expire dans 90 secondes » est l'etat NORMAL

Je me suis alarme a tort, et ca valait d'etre ecrit. `economic_collection_lease.json` montrait
`expires_at_ms` a deux minutes devant, et `issued_at_ms` dix-sept heures en arriere : lu comme une
photo, ca ressemble a une campagne qui meurt dans la minute. C'est l'inverse.

Le watcher passe `--lease-duration-s 120` : **TTL de 2 minutes, renouvele toutes les 30 s**. C'est
la SECURITE : les collecteurs s'arretent d'eux-memes peu apres la fermeture de la fenetre — c'est
precisement ce qui a arrete la collecte a 21 h 32 le 15/11. `renew_bounded_collection_lease` ne
touche que `expires_at_ms` et laisse `issued_at_ms` fige : le delta entre les deux ne mesure donc
RIEN.

**Ce qu'il faut lire a la place** : `lease_renewal` dans `runtime/logs/economic-collector-watchdog.jsonl`
(`OK` = le bail roule). Toute alarme batie sur `expires_at_ms` seul sera un faux positif permanent.

## T13. Le rapport collecteurs crie au loup : 163 lignes CRITIQUE sur une campagne saine

`RAPPORT-COLLECTEURS.cmd` classe en `[CRITIQUE]` 136 `ConnectionResetError` de `native-venues` et
une trentaine de `ResourceWarning`, pendant que ce collecteur a 2,78 M d'ecritures et un battement
de 26 s. Une reconnexion WebSocket n'est pas une panne : c'est le fonctionnement normal d'un flux
public. A re-etiqueter (AVERT, avec un seuil par minute), sinon le signal critique ne veut plus
rien dire — et c'est ce bruit qui fait rater une vraie panne.

## T14. `lab-ctx` : range, pas supprime — et correction de ce que j'ai ecrit en T9

Correction d'abord : en T9 j'ai ecrit qu'un controle comptant ce battement le prenait pour une
panne. Verifie depuis : **`preuve_de_vie` ne balaie PAS le dossier**, il lit une liste EXPLICITE de
sources (`lire_heartbeats_reels(root, sources)`). Il n'etait donc pas trompe. Ce qui l'etait : ma
propre sonde ad hoc — et surtout, le rapport collecteurs n'avait **aucune** vue des battements.

`lab-ctx` est un vrai collecteur (`tools/collecter_lab_ctx.py`), mais d'un AUTRE lanceur
(`tools/launchers/LANCER-RECHERCHE-14H.cmd`) ; il n'est pas dans les 26 noms du registre, et son
role dans la campagne copy-vault est tenu par `contexte-leaders`.

**Fait** : le fichier est deplace dans `runtime/research_lab/heartbeats/inactifs/` avec un
`LISEZ-MOI.txt` qui dit d'ou il vient (rien n'est supprime), et le rapport porte desormais une
section BATTEMENTS qui **ne juge que les collecteurs declares au registre** et range les autres
sous « HORS REGISTRE — PAS des pannes ». Si le registre est illisible, aucun verdict n'est rendu :
on ne declare pas mort ce qu'on ne sait pas lire.

## T15. Le rapport ne crie plus au loup — et il a aussitot deterre une VRAIE panne

Trois defauts mesures, trois corrections dans `tools/rapport_collecteurs.py` :

1. **Aucune fenetre de temps.** Il balayait tout `runtime/logs` en `rglob`, donc un journal du
   **12/11** remontait en tete de « A CORRIGER EN PRIORITE » le 16/11. Desormais `--depuis-h`
   (defaut 24 h) ; au-dela, le journal passe en section ARCHIVES avec ses compteurs, hors priorites.
2. **Un avertissement n'est pas un plantage.** `MOTIF_GRAVE` attrapait `ResourceWarning` par le mot
   « traceback » present dans son propre texte, et `ConnectionResetError` par `[a-z]+error`.
   Nouvelle classe **ROUTINE** (`MOTIF_ROUTINE`), evaluee AVANT « grave » : de-escalade voulue,
   avec sa propre section et un seuil — au-dela de **200** lignes de routine sur un journal recent,
   c'est signale, parce qu'une tempete de reconnexions EST un symptome.
3. **Le resume console mentait.** Il comptait `contenu.count("\n  [")`, soit toutes les lignes
   commencant par un crochet — routine et archives comprises : « ~120 erreurs » sur une campagne
   saine. Il lit maintenant les compteurs reellement ecrits dans le rapport.

**Resultat sur les memes journaux : 163 lignes critiques -> 8 erreurs graves.** Et parmi ces 8,
celle-ci, qui etait enterree :

```
PermissionError: [WinError 5] Acces refuse:
  runtime\data\backfill_candles_etat.json.85588.tmp -> runtime\data\backfill_candles_etat.json
```

## T16. L'etat du backfill ne tue plus la passe (la panne que T15 a deterree)

Windows refuse `os.replace` quand la **cible** est ouverte, meme en lecture seule (pas de
`FILE_SHARE_DELETE` sur un `open()` Python). Or les deux passes de backfill — celle de la campagne
toutes les 4 h et celle du rattrapage — lisent ce meme etat au debut de leur propre `sauver_etat`.
Collision de quelques millisecondes, `PermissionError`, et la passe **mourait** : des heures de
budget de requetes perdues pour une page d'etat.

Le brouillon porte deja le PID (15/11) : la concurrence est un choix ASSUME, je ne reviens pas
dessus. **Fait** : `remplacer_avec_patience` retente 6 fois avec une attente croissante, puis rend
`False` en le DISANT plutot que de lever. Perdre un etat n'est pas perdre des donnees — les lignes
sont deja sur le ruban, completes, et la page suivante resauve. 3 tests.

## T17. Le rapport, suite : cinq faux positifs de plus, et un VRAI trou

En rejouant le rapport apres chaque correction, quatre autres sources de bruit sont tombees — et
un defaut qui, lui, cachait de vraies pannes :

1. **`429 restantes` lu comme un HTTP 429.** Les lignes de progression du rattrapage disent
   « 19 min ecoulees, **429** restantes » : le motif `429` NU les comptait en signaux et
   declenchait meme la recommandation « reduire le debit du poll » — sur une campagne qui n'avait
   encaisse AUCUN refus. Le `429` exige desormais un contexte HTTP (`status=429`, `429 too many
   requests`, `erreur 429`...).
2. **Les compteurs a ZERO comptes comme alertes.** « 0 reconnexions », « (echecs 0) », « 0 refus
   encaisse(s) » : 458 « petits signaux » etaient en majorite des lignes de BONNE SANTE. Compter
   les bonnes nouvelles comme des alertes fait le meme mal que crier au loup.
3. **`status="SUCCESS"` classe GRAVE** a cause du mot « critical » dans
   `operation="python-version-dependencies-critical"`. Un succes n'est pas une panne.
4. **Journaux CUMULATIFS.** `ALL_LAUNCHERS.log` est append-only : son mtime est de ce matin, son
   contenu remonte au 12/11. Une fenetre par FICHIER n'y peut rien. Les lignes de lanceur portent
   `timestamp_local="JJ/MM/AAAA HH:MM:SS"` : la fenetre se lit donc **par ligne** quand la ligne
   porte sa date. Piege dans le piege : avant 10 h, l'heure est **cadree par un espace**
   (« 14/11/2026  1:18:44 »), et un `\d{2}` ne la reconnait pas — la ligne retombait sur le mtime
   du fichier et repassait en priorite deux jours plus tard.
5. **TROU PREEXISTANT, l'inverse du bruit** : une ligne `status="FAILURE"` n'etait attrapee par
   AUCUN motif (« failure » n'est ni « failed » ni « error »). Un echec de lanceur passait donc
   totalement inapercu. Ajoute — mais sur le STATUT, pas sur le mot : `run_id="runtime-audit-
   failure-2"` n'est pas un echec.

**Bilan mesure, sur les memes journaux : 163 lignes critiques -> 4 formes / 5 lignes graves.**
Et les quatre sont explicables : `HTTPError` de meta sur l'explorer (transitoire), le
`PermissionError` du backfill (corrige en T16), et un traceback de `coffre_session.log` qui s'est
revele etre un **`KeyboardInterrupt`** du 12/11 — quelqu'un avait interrompu un scellage. Le
scelleur attrape maintenant le Ctrl+C sur sa passe unique comme sur sa boucle : il DIT que tout ce
qui etait scelle le reste, et rend 130. 21 tests (`tests/test_rapport_sans_crier_au_loup.py`).
