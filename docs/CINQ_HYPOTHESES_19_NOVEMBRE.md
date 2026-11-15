# Les cinq hypotheses gelees pour le 19 novembre

**Ecrit le 15/11, avant que la fenetre de jugement n'existe.**

## Pourquoi CINQ et pas quatre cents

Le 14/11 j'ai balaye environ **450 configurations** (5 horizons x 5 valeurs de `k` x 3 signaux x
2 ponderations x 3 taux de couverture). Resultat : la porte de promotion exige un `t` de **3,86**,
et **plus aucun candidat ne peut le franchir**. En cherchant partout, j'ai rendu la porte
infranchissable pour mon propre travail.

```
nombre d'hypotheses gelees  ->  t requis (Bonferroni)
                         1  ->  1,96
                         3  ->  2,39
                         5  ->  2,58
                        10  ->  2,81
                       450  ->  3,86
```

**Mon meilleur `t` honnete mesure est 2,21** (horizon 24 h, 106 detentions disjointes). A cinq
hypotheses il manque **0,37** — un ecart franchissable si le signal des leaders est un peu meilleur
que le funding. A quatre cents, l'ecart est de 1,65 et rien ne passe.

## Ce qui compte comme hypothese, et ce qui n'y compte pas

**Compte** : tout candidat qu'on pourrait CHOISIR a la place d'un autre. C'est la selection qui
coute, pas le calcul.

**Ne compte pas** : une MESURE sans alternative — le taux de remplissage passif, le `mmr` reel, le
slippage par coin. Il n'y a rien a y elire, donc rien a corriger. Ces mesures sont a faire sans
retenue : elles n'ont aucun effet sur le seuil.

## Convention commune aux cinq

| Parametre | Valeur | Pourquoi |
|---|---|---|
| Detention | **24 h** | Le SEUL horizon ou cette quantite de donnees peut parler : 106 observations disjointes contre 26 a 96 h, et le meilleur `t` honnete (2,21 contre 1,04) |
| Depart | toutes les **6 h** | 4 tranches : diversifie le moment d'entree sans multiplier les positions |
| `k` par jambe | **3** | Retenu le 14/11 sur sa STABILITE (trois tiers positifs, ecart-type 17,9 contre 94,4 pour `k=1`), pas sur son sommet |
| Couverture | **100 %** dollar-neutre | Balayage monotone : la jambe longue perd -9,2 % seule mais divise le repli par 3,5 |
| Cout | **taker mesure** | 4,5 bps de frais + slippage mesure et persiste (~4,2 bps). Le scenario maker reste un PLAFOND tant que le remplissage horaire n'est pas mesure |
| `mmr` | **mesure, pondere** | 12,32 % et non 5 % suppose — l'edge vit dans les coins a 3x, et la venue leur donne la marge la plus haute |
| Critere | **`t` >= 2,58** | Bonferroni pour 5 hypotheses. **Pas la part positive** : l'edge vient de l'ASYMETRIE (0,58 de reussite seulement) |

---

## H1 — Positionnement net des leaders *(priorite 1)*

**Signal** : part signee du notionnel par coin, `somme(szi x px) / somme|szi x px|` sur les
46 vaults, dans [-1, 1]. Livre inverse : long les coins ou les leaders sont le plus nets-longs.

**Motivation, et ce n'est pas un espoir** : le momentum direct a ete mesure a **-44,2 %** alors que
le funding gagne. Le funding ne mesure donc PAS la performance passee — il mesure
**l'ENCOMBREMENT DU POSITIONNEMENT**. Or `position` donne cet encombrement **directement**, sans le
proxy bruite qu'est le taux de funding.

**Donnees** : `position` (15 Mo, 46 vaults, 179 coins). 45 h au 14/11 -> **~192 h le 19/11**, soit
environ 28 observations a 24 h de detention.

**Ce qui la refuterait** : un `t` sous 2,58, ou un signal qui ne bat pas H3 (le funding) alors
qu'il mesure la meme chose en mieux.

## H2 — Ordres en attente des leaders

**Signal** : `notionnel_par_coin` des deux cotes, dans `leader_orders`.

**Motivation** : le funding et les positions refletent l'encombrement **deja constitue**. Les ordres
en attente le montrent **AVANT**. C'est la seule hypothese de la liste qui soit **en avance** sur le
signal qui marche.

**Prerequis a lever D'ABORD** : le taux d'annulation. Un ordre affiche peut n'etre qu'un bluff ;
classer sur du bluff ne produirait rien. **Cette mesure prealable ne compte pas comme une
hypothese** (il n'y a rien a y choisir).

## H3 — Funding a 24 h, le livre actuel *(le temoin)*

**Signal** : funding brut, livre inverse — exactement la configuration du 14/11, mais a 24 h.

**Motivation** : c'est le **temoin**. Sans lui, impossible de dire si H1 et H2 apportent quelque
chose ou si l'on mesure seulement l'effet du changement d'horizon. Son `t` honnete est deja connu :
**2,21**.

## H4 — Encombrement normalise par l'interet ouvert

**Signal** : positionnement des leaders (H1) divise par `oi` (`asset_ctx`).

**Motivation** : le funding brut melange « ce coin est encombre » et « ce coin est petit ». `oi`
separe les deux. Mesure directe, aucune nouvelle collecte.

## H5 — Proximite de liquidation comme filtre de RISQUE

**Signal** : non pas un signal d'entree mais un **filtre** : ecarter les coins dont la densite de
liquidations proches est la plus forte.

**Motivation** : j'ai averti toute la session que ce livre est « long la foule, donc le combustible
d'une cascade » **sans jamais le mesurer**. La venue en a connu une qui a detruit 7,4 Md USD
d'interet ouvert. Cette hypothese attaque le **REPLI**, donc le levier — et les deux issues sont
utiles : si le livre traverse, le facteur 4 est trop prudent ; s'il casse, il doit monter.

**Donnees** : `liquidation` (1 Mo, jamais ouverte).

---

## CE QUI A CHANGE LE 15/11 : l'historique passe de 211 a ~1 100 jours

**La question etait : « comment avoir plus de donnees sur la duree de detention ? »** Le nombre
d'observations independantes vaut `historique / duree_de_detention`. A detention fixee, il faut donc
plus d'historique — et il y en avait, non collecte.

`PROFONDEUR_FUNDING_MS` etait calee sur `CAP_CANDLES` (5 000 bougies 1 h = **208 jours**) « par
symetrie ». **C'etait une borne inventee** : `candleSnapshot` plafonne a 5 000 points, mais
`fundingHistory` est pagine par 500 et ne plafonne pas la.

**Sonde du 15/11 sur BTC** (une requete par palier) : l'endpoint rend 500 points a 211, 365, 550,
730 **et 1 095 jours** en arriere, et plus rien a 1 460. La profondeur reelle est d'environ
**trois ans**.

```
avant : 208 jours collectes   ->  26 observations independantes a 96 h de detention
apres : 1 100 jours           ->  x5,3 d'historique, donc x2,3 sur le `t`
```

**Le labo ne manquait donc pas de donnees : il en jetait 80 %.** C'est la vraie raison pour laquelle
rien ne franchissait la porte.

**LA RESERVE, ET ELLE COMPTE** : plus d'historique couvre **plus de REGIMES**. L'effet mesure sur
avril-novembre 2026 peut etre plus faible, nul ou inverse en 2024. **Plus d'historique ne garantit
pas un verdict positif — il donne le POUVOIR DE TRANCHER**, ce qui est precisement ce qui manquait.
Un `t` qui s'effondre sur trois ans serait une refutation, et une refutation est un resultat.

**A FAIRE AVANT LE 19** : laisser le collecteur rattraper les ~890 jours manquants. A 100 de poids
par minute et ~10 pages par coin, cela prend du temps : le rattrapage est la priorite de la
collecte, devant l'elargissement de l'univers.

## Les mesures a faire en plus, qui ne coutent RIEN au seuil

1. **Taux de remplissage passif a l'echelle de l'HEURE** — decide si le plafond maker (+24 % de
   brut) est une estimation ou un reve. Jamais mesure : seules 30 s l'ont ete.
2. **Slippage par coin et par heure** (`bbo`, `trades_marche`) — je retiens UN chiffre pour
   94 coins qui vont de 2,8 a 21 bps.
3. **L'univers elargi** — 114 coins au 15/11, cible 261. Simple relance de l'outil officiel.

## Les pieges, ecrits pour ne pas y ceder

* **Ne pas rebalayer.** Chaque configuration essayee en plus monte le seuil pour toutes les autres.
  Si les cinq echouent, **la reponse est « refute », pas « cherchons une sixieme ».**
* **Ne pas choisir les leaders sur leur PnL passe** (`vault_portfolio.apr_affiche`) : c'est le
  mecanisme meme du PBO de 0,81.
* **Ne pas lire le `t` sur des fenetres chevauchantes.** Mesure du 15/11 : l'horizon 336 h affichait
  **5,09** en chevauchant contre **1,62** en disjoint — un facteur trois d'illusion.
* **Ne pas baisser le facteur de securite** pour atteindre un chiffre : ce serait un choix de risque
  deguise en resultat.
