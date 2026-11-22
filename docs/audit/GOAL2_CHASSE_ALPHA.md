# /GOAL 2 — Chasse à l'alpha CopyVault : journal de recherche

> Ouvert le 22/11/2026. Un seul agent, PAPER / READ-ONLY / FAIL-CLOSED, capital paper canonique
> 100 USD. Ce journal trace **tous** les essais, y compris les échecs et mes propres erreurs.
> Statuts admis : `PROVEN` / `PROMISING` / `MORE_DATA` / `UNMEASURABLE` / `REJECTED`.
> **Aucun backtest ne vaut `PROVEN`** : la preuve prospective (forward-paper) est obligatoire, et
> elle exige une collecte qui est éteinte sur consigne de l'opérateur.

## 0. Point de départ — ce que la mémoire et le dépôt établissent déjà

| fait mesuré | valeur | source |
|---|---|---|
| copie naïve, suivi rapide | **REJECTED**, même à spread nul (dérive ≤ 3,1 bps après observation, contre 9 bps de frais) | run du 12/11, `lois_mesurees.py` |
| retard d'observation du poll | médiane 98 s ; un fill taker gagne ~6 bps en 15 s, **avant** observation | étude de copiabilité du 11/11 |
| copie miroir | nette −12 bps ; 47 % des épisodes déjà clos quand l'ouverture devient observable | idem |
| persistance de compétence | IC +0,016 [−0,032 ; +0,059] sur 2 345 vaults, 87 dates | mission du 17/11 |
| « meilleur leader » +18,85 USD/j | **bruit** : placebo moyen +19,16, p95 +34,63 | idem |
| détention réelle des leaders | médiane **46,6 min** ; 160/163 comptes > 300 s | idem |
| réplication lente 350 USD | −0,185 USD/j, IC95 [−1,31 ; +0,81], 5 jours → `MORE_DATA` | idem |
| 2 candidats TRAIN à LCB corrigée positive | +1,48 USD/j (19 trades, 30 min) et +0,68 USD/j (47 trades, 15 min), déséquilibre de carnet favorable | 19/11 — **TRAIN seul, pas une preuve** |
| médiane de tous les essais du corpus | **−1,10 USD/j** ; ×6 de trades = ×3 de pertes | 19/11 |
| grille d'horizons du labo | 30 s … **1 h** — rien au-delà n'a jamais été exploré | `_PARAMETER_DOMAINS` |

Trois causes structurelles nommées le 12/11 : (1) les coûts taker (~9 bps aller-retour + spread)
dominent la dérive ; (2) le délai d'observation laisse partir l'essentiel avant l'entrée ; (3) la
sélection aide, mais pas assez. **Conséquence directe : chercher là où le coût pèse peu devant
le mouvement — horizons longs — ou là où le retard devient un avantage.**

## 1. Ce que le coffre certifié contient (inventaire du 22/11, tier LOCAL)

| famille | fenêtre | usage pour la recherche |
|---|---|---|
| `fills_backfill` (`leader_fills_backfill`, `vault_episodes`) | 26/04 → 19/11 (≈ 7 mois) | signal : fills de leaders avec `start_position` |
| `fills_forward` / `vault_fills_poll` | — → 21/11, 1,9 Go | **`closedPnl`, `crossed`, `fee`, `startPosition`, `liquidation`** par fill |
| `candle` (`candles_5m`, `1h`, `4h`, `1d` + 1 m en direct) | depuis 2020 | prix sur longue période (exploration) |
| `bbo` | 26/10 → 21/11, 6,3 Go | **exécution observée** pour 100 USD (meilleure limite) |
| `funding_history` | 11/11/2023 → 20/11/2026 | portage, régime |
| `position`, `vault_portfolio`, `leader_orders` | 11/11 → 21/11 | positions réelles, PnL latent, ordres en attente |
| `liquidation`, `vault_ledger`, `asset_ctx`, `micro_*` | variables | contexte |

⚠️ **Biais de survie assumé** : les cibles du backfill sont choisies **par score** en novembre 2026
(plus 10 « témoins » non sélectionnés). Leur historique de mai à octobre est donc flatté.
Règle adoptée : l'historique biaisé sert à trouver des structures **conditionnelles** (X contre
non-X chez le même leader) ; toute affirmation de rentabilité **absolue** ne vaut que sur des
données postérieures à la sélection, puis en forward-paper.

## 2. Recherche externe (Exa + Tavily + TinyFish, 22/11) — ce qui survit au tri

Marketing écarté. Sources retenues : études chiffrées avec méthode, préprints, analyses datées.

| source | résultat utile | conséquence pour nous |
|---|---|---|
| JoinEm research (10/2026), > 1 000 wallets HL rejoués point-in-time | ~50 % des profitables à 90 j le restent le mois suivant ; ~90 % du mois d'un trader vient d'**un seul trade** ; coût aller-retour d'une copie ≈ 0,29 % ; **rejoindre une position quand le trader est en PERTE fait mieux que quand il gagne** (−10 % ou pire : +16,7 %, 68 % gagnants ; ≥ +5 % : la plupart des copies tardives perdent) ; traders détenant ≥ 1 jour : résultat conservé même à 50 bps de slippage ; stops serrés nuisibles ; top-3/top-5 = les plus chanceux, pas les meilleurs | **piste L1** — entrer à meilleur prix que le leader, quand il est sous l'eau et tient encore |
| Rodríguez Vargas, SSRN 7684880 (2026), 22 comptes HL, délai 10 s | copie d'épisode entier : **−6,96 bps** nets ; miroir +5,4 bps/turnover mais porté par 2 comptes ; « ne valide pas une stratégie rentable à capital fixe » | confirme notre `REJECTED` sur la copie rapide |
| Event Horizon Labs, 825 000 adresses, 365 jours | 23,4 % profitables ; PnL brut ≈ 0, la perte = les frais ; persistance : ρ = 0,23 entre moitiés d'année, **marche d'escalier tout en haut** (top-100 : 70 % restent profitables ; déciles 1–8 indistinguables) ; les perdants persistent aussi (décile du bas) | la persistance existe **aux extrêmes seulement** — et des deux côtés |
| QuantumFlow (11/2026), 1 M de wallets | positionnement des baleines : ne prédit rien ; copier le top-100 du mois : **−13,6 %** en 14 mois ; nouvelle position ≥ 500 k$ : +0,6 bp à 1 h ; markout du meilleur décile : +31 bps en échantillon → **+2,3 bps** hors échantillon ; **seule piste : petits comptes surchargés d'un côté → −62,7 bps à 24 h** (mais meilleur de 36 essais, p = 0,21) | la compétence « markout » ne paie pas un taker ; le contrarien de foule est fragile et exige la population entière (que nous n'avons pas) |
| Albers et al., arXiv 2611.05218 ; Baruch, arXiv 2608.04373 | l'identité du wallet prédit à 1–30 **secondes** (ρ = 0,52 entre fenêtres de 10 jours ; +3,1 bps top ventile) | réel mais sous les frais taker : utile comme **filtre**, pas comme stratégie |
| Barone & Lillo, arXiv 2606.15715 | 4,3 M de méta-ordres ; les TWAP **visibles** coûtent moins cher que les méta-ordres cachés (le marché leur fournit de la liquidité) | **suivre un TWAP public ne paie pas** — hypothèse retirée (et nos leaders n'en font presque pas : 0 sur 20 000 fills sondés) |
| « Who Loses and Why? », AFT 2026 | l'impact post-trade s'organise par **motif** : les clôtures qui **réalisent une perte** suivent le mouvement récent **puis reviennent**, pour tous les groupes ; une liquidation ressemble à une clôture en perte, en bien plus grand | **piste L2** — prendre le contre-pied des clôtures en perte agressives |
| Botsfolio, 9 470 vaults | top-10 par rendement 30 j : −4 % à 30 j, −19 % à 90 j, −49 % à un an | courir après la performance récente d'un vault est **négatif** |
| vike.io | des étiquettes de cohorte **non point-in-time inversent le signe** du résultat | toute étiquette de leader doit être calculée avec le seul passé |

## 3. Hypothèses, classées par (PnL potentiel × faisabilité ÷ coût)

| # | hypothèse | mécanisme | données | statut |
|---|---|---|---|---|
| **L1** | entrer dans la position d'un leader lent **quand elle est en perte latente et qu'il la tient** | le suiveur entre à **meilleur prix** que le leader : le retard devient un avantage ; la tenue révèle la conviction | fills 7 mois (`startPosition`) + bougies ; `position` 11–21/11 | à tester → **REJECTED** (essais 11–12) |
| **L2** | contre-pied des **clôtures en perte agressives** (stop, capitulation, liquidation) | vente forcée → dépassement → retour | `closedPnl` + `crossed` + `liquidation` + bougies | à tester → **REJECTED** (essais 1 et 15) |
| **L3** | copie lente à horizon **multi-heures** (au-delà de la grille du labo) | flux informé persistant ; coûts faibles devant le mouvement | fills + bougies, puis BBO | à tester → **REJECTED** (essais 3–7) |
| **L4** | sélection par règles de **copiabilité** (détention ≥ 1 j, courbe marquée au marché, levier bas), pas par profit | la persistance n'existe qu'aux extrêmes ; le profit passé récompense la chance | fills 7 mois | à tester, en marche avant stricte → **UNMEASURABLE** (puissance) |
| L5 | TWAP publics des leaders | flux annoncé | quasi absent chez nos leaders ; littérature défavorable | **retirée avant test** |
| L6 | contrarien de foule (petits comptes) | — | exige la population entière | **non testable** avec le coffre |

## 4. Protocole (figé AVANT tout résultat)

1. **Exploration** : 26/04 → 31/08/2026. Seul segment où l'on cherche.
2. **Validation en marche avant** : 01/09 → 25/10/2026. Consultée **une fois par hypothèse figée**.
3. **Exécution observée** : 26/10 → 12/11/2026, prix d'exécution au BBO réellement collecté.
4. **OOS final verrouillé** : ≥ 13/11/2026 — **jamais ouvert pendant la recherche.** Les journées
   13–15/11 ont déjà servi de TRAIN au labo (149 000 essais) : elles ne sont pas vierges pour les
   stratégies à déséquilibre de carnet ; 16–21/11 l'est.
5. Coûts : frais taker 4,5 bps par côté (palier de base Hyperliquid), spread observé quand le
   BBO existe, sinon hypothèse **pessimiste** déclarée ; funding horaire observé, signé.
6. Latence : sur l'historique rattrapé, l'instant d'observation est **modélisé** (fill + 120 s,
   au-dessus de la médiane mesurée de 98 s) et dit comme tel ; sur `fills_forward`, on utilise
   l'instant **réellement** observé.
7. Chaque essai est compté : le nombre total d'essais corrige la significativité (DSR).

## 5. Registre des essais

### Essais 1 à 7 — étude d'événements sur les leaders lents (exploration, 26/04 → 31/08)

*(titre corrigé le 22/11 : il annonçait « 1 à 8 », le registre chaîné en compte 7 pour ce bloc.)*

Outils : `tools/goal2_construire_cache.py` (cache colonnes, 71 s), `goal2_commun.py` (segments
figés, registre chaîné), `goal2_etude_evenements.py`, `goal2_robustesse.py`.
Données : 110 690 fills de 33 leaders → 7 478 événements (leader, coin, heure) ≥ 1 000 USD.
Entrée à l'ouverture de la première bougie horaire ≥ dernier fill + 120 s. Coût retenu : 15 bps
(9 de frais + 6 d'écart **supposé**).

| # | hypothèse | résultat brut | après épreuves | statut |
|---|---|---|---|---|
| 1 | L2 — rebond après clôture en perte **agressive** | +9,2 bps à 1 h, IC [0,5 ; 17,9] ; rien à 4 h | l'effet existe (conforme à AFT 2026) mais reste **sous les 15 bps de coût** | **REJECTED** (taker) |
| 2 | continuation après clôture en perte **passive** | −148 bps à 72 h, IC [−260 ; −24] | ajusté du marché : −84 [−207 ; +44] ; **un seul leader** porte tout (sans lui : −4) ; 8/13 leaders du même signe ; 1ʳᵉ moitié de signe **inverse** | **REJECTED** |
| 3–6 | L3 — dérive à 72 h après ouvertures / prises de profit | +55 à +85 bps bruts | longs +133 à +167, shorts de signe **opposé** → le coin monte **dans les deux cas** : pas de l'information directionnelle | voir 7 |
| 7 | contrôle : dérive propre de chaque coin retirée | ouvertures agressives longues +115,8 → **+16,2** [−141 ; +174] ; toutes les familles ≈ 0 | les leaders ne *timent* pas à 24–72 h ; on voyait leurs coins monter sur la période | **L3 REJECTED** sur le timing ; « choix du coin » **UNMEASURABLE** (confondu avec la survie) |
| — | dérive à 1–4 h après ouverture | +3,5 / +4,8 bps (1 h), −0,4 / +6,5 (4 h) | nulle **même** dans un échantillon de gagnants | L3 intrajournalier **REJECTED** |

**Deux erreurs d'analyse évitées de justesse, à retenir :**

1. un « ajustement du marché » par indice **équipondéré** de 263 coins fabrique un faux alpha
   pour quiconque traite des majeurs (l'indice est plombé par les petits alts) ;
2. un effet « significatif » sur 24 cellules testées est attendu par hasard (≈ 1,2 faux positif).
   Le seul qui tenait reposait sur **un** leader.

**Ce que ça dit de l'univers :** 33 leaders en exploration (la médiane des 86 n'a que **17 jours**
d'historique — l'API ne rend que les 10 000 derniers fills), 25/33 gagnants nets, top-3 = 58 %
des gains. L'échantillon est petit, concentré et biaisé : aucune stratégie de **direction** à
horizon de jours n'y est mesurable honnêtement.

### Essais 8 à 13 — participation, position en perte, consensus (exploration)

Outils : `goal2_etude_participation.py`, `goal2_etude_position_en_perte.py`,
`goal2_placebo_position_en_perte.py`, `goal2_etude_consensus.py`.

| # | hypothèse | résultat | épreuve | statut |
|---|---|---|---|---|
| 8 | **L8** — le flux d'un leader qui pèse lourd dans le volume du coin continue (méta-ordre) | 9 652 heures-leader-coin ; aucune tranche de participation (0–1 % … ≥ 40 %) n'a un IC excluant zéro, à 1, 4 ou 24 h | dérive propre retirée d'emblée | **REJECTED** |
| 9 | L1 — entrer dans une position en perte latente et tenue | +41 bps à 4 h | ⚠ **mesure invalide** : prix d'entrée connu sur 13 % des fills seulement (voir défaut ci-dessous) | **PÉRIMÉ** (remplacé par 11) |
| 10 | placebo de 9 | — | même défaut | **PÉRIMÉ** (remplacé par 12) |
| 11 | **L1**, reconstruction corrigée | 1 082 événements, 32 leaders : **+22,7 bps à 4 h** [4,1 ; 42,5] sous −100 bps ; +29,8 [2,4 ; 59,2] sous −300. Symétrique côté gain : −33,5 [−63,7 ; −3,1] | la symétrie trahit un simple retour du prix | voir 12 |
| 12 | placebo : **jumeaux sans leader** (même coin, même mouvement passé, à plus de 24 h) | le jumeau rebondit autant : excès **+1,8 bps** [−16,3 ; +20,9] à 4 h ; à 24 h l'excès est **négatif** (−39 [−84 ; +2,5]) | appariement sur 1 h puis 4 h : même lecture | **L1 REJECTED** — tenir une position perdante n'est pas une conviction informée |
| 13 | **L9** — consensus de ≥ 2, 3, 4 leaders sur un coin en 24 h | ≥ 3 leaders : +244 bps à 72 h [10 ; 505]… | …mais 50 % des événements sont **HYPE**, 149 longs sur 156, et le jumeau sans leader fait +153 : excès +90 [−150 ; +355] | **REJECTED** |

**Défaut trouvé dans MON outil (essais 9–10), corrigé :** dans une même milliseconde un ordre
agressif produit plusieurs fills ; je les triais par `tid`, qui **n'est pas** l'ordre d'exécution.
Résultat : 60 953 faux « trous » de position sur 112 032 fills, prix d'entrée connu sur 13 %.
L'ordre vrai est la chaîne `start_position` (croissante pour des achats, décroissante pour des
ventes) : 1 129 trous restants (1 %), prix d'entrée connu sur 61 %. C'est la ligne de **qualité**
imprimée en tête de sortie qui l'a révélé — un essai sans elle aurait été cru.

### Pré-enregistrement L10 (22/11, écrit AVANT sa mesure)

**Origine déclarée : hypothèse née des données** (essais 11–12) — donc suspecte par construction.
Observation : une position en perte latente **et tenue** fait *moins bien* que son jumeau sans
leader à 24 h (excès −39 et −55 bps, IC frôlant zéro), et les positions profondément sous l'eau
continuent de perdre à 72 h (−113 et −186 bps bruts). Le biais de survie joue ici **contre**
l'observation (les perdants des survivants se sont, par sélection, mieux rétablis).

- **Règle** : premier passage de la perte latente sous **−600 bps** (principal ; −1000 secondaire)
  sur une position tenue ; prendre le **côté opposé** ; sortie à **72 h** (24 h secondaire).
- **Épreuve préalable, en exploration** : excès contre un jumeau apparié sur le mouvement des
  **72 h** (et 24 h) précédentes — car « ce qui a chuté 6 % continue » serait de la tendance
  générique, pas de l'information sur le leader.
- **Critère d'arrêt** : si l'excès n'a pas un IC95 excluant zéro **ou** s'il tient à un seul
  leader → `REJECTED`, la validation **n'est pas consultée**. Sinon, règle figée telle quelle et
  validation consultée une seule fois.

### Essai 14 — L10 mesurée (exploration) : critère d'arrêt atteint

Excès du **leader** contre un jumeau apparié sur les 72 h précédentes, à 72 h (sens de la
position du leader ; le contre-pied gagne l'opposé) :

| seuil | n | événement | jumeau | excès | IC95 | leaders du même signe | sans le leader le plus favorable |
|---|---|---|---|---|---|---|---|
| ≤ −600 bps | 322 | −143,7 | −6,0 | **−137,7** | [−363,0 ; **+64,6**] | 11/15 | −71,1 |
| ≤ −1000 bps | 204 | −241,3 | −12,4 | **−228,9** | [−488,1 ; **+33,6**] | 7/11 | −158,9 |

L'ampleur est grande et la tendance générique ne l'explique pas (jumeau ≈ −6 à −12), mais
**l'IC95 contient zéro** : le critère pré-enregistré s'applique → **non promue, validation non
consultée** (`REJECTED` au sens du pré-enregistrement). Lecture honnête : *non établie*, pas
*mesurée nulle*. C'est la première chose à re-mesurer sur des données **neuves**.

### Témoin positif — le pipeline voit-il clair ? (contrôle, hors registre)

Tricherie volontaire : entrée **1 h avant** le fill (`--latence-s -3600`). Rendement à 1 h :

| famille | à 1 h, en trichant | à 1 h, causal |
|---|---|---|
| ouverture agressive | **+18,4** [5,8 ; 31,2] | +3,5 |
| ouverture passive | **−66,0** [−78,3 ; −52,6] | +4,8 |
| clôture en gain passive | **+85,9** [69,6 ; 103,0] | −2,8 |
| clôture en perte agressive | **−42,7** [−56,5 ; −29,3] | +9,2 |

Les signes sont ceux de la mécanique (un ordre passif est rempli quand le prix vient à lui, un
stop saute quand le prix part). **L'outil détecte donc un effet quand il y en a un** ; les zéros
des essais 1–14 ne sont pas un défaut d'instrument. Et la conclusion est nette : **toute
l'information d'un fill de leader est consommée dans l'heure du fill.**

### L4 — sélection par règles de copiabilité : `UNMEASURABLE` (puissance, sans lire un résultat)

Leaders ayant ≥ 30 jours d'historique et encore actifs à chaque date de formation : 19 (01/06),
27 (01/07), 27 (01/08), 29 (01/09), 33 (01/10), 34 (26/10). Profondeur médiane d'historique des
80 comptes : **14 jours** (l'API ne rend que les 10 000 derniers fills ; rien ne se rattrape).
Avec ~27 comptes, l'erreur-type d'un IC de rang vaut ≈ 0,19 par date, ≈ 0,09 sur 5 dates : un IC
de l'ordre de celui déjà mesuré sur 2 345 vaults (+0,016) est **indétectable** (il faudrait
> 0,17). Aucun essai n'a été lancé : il n'aurait rien pu conclure.

### Ordres en attente des leaders : `MORE_DATA`

Seule famille dont le mécanisme n'est pas réfuté (un ordre posé est une intention **avant** le
fill : le retard cesse d'être un handicap). Données avant le verrou du 13/11 : **9 shards, 500
instantanés, 8 leaders avec ordres**. Les 302 autres shards sont dans l'OOS final. Je n'ai **pas**
amendé le protocole pour les ouvrir : 4–5 jours = un seul régime de marché, et l'OOS serait brûlé
pour un résultat sans puissance.

## 6. Verdict au 22/11/2026 — 14 essais, aucun edge *(15 avec la section 7, même verdict)*

| hypothèse | statut | la phrase |
|---|---|---|
| L1 entrer dans la position en perte tenue | **REJECTED** | le rebond est celui du prix, pas du leader (excès +1,8 bps) |
| L2 contre-pied des clôtures en perte agressives | **REJECTED** | +9,2 bps à 1 h, réel mais sous le coût de 15 bps |
| L3 copie lente multi-heures / multi-jours | **REJECTED** | la « dérive » était celle du coin, pas un timing |
| L4 sélection par copiabilité | **UNMEASURABLE** | ~27 comptes : puissance nulle |
| L5 TWAP publics | retirée avant test | littérature défavorable, quasi absents |
| L6 contrarien de foule | non testable | exige la population entière |
| L8 participation dans le volume | **REJECTED** | aucune tranche ne se détache |
| L9 consensus de leaders | **REJECTED** | c'est HYPE qui monte, avec ou sans eux |
| L10 contre-pied du perdant tenu | **REJECTED** (critère) | −138 à −229 bps d'excès, IC contenant zéro |
| ordres en attente | **MORE_DATA** | 9 shards exploitables |

**Aucun statut `PROVEN` ni `PROMISING`.** La validation (01/09 → 25/10), le segment d'exécution
(26/10 → 12/11) et l'OOS final (≥ 13/11) n'ont **pas été consultés** : ils restent vierges pour
la suite. Trois erreurs d'analyse auraient chacune fabriqué un faux alpha (indice équipondéré,
effet porté par un seul leader, rebond générique pris pour de l'information) ; une quatrième
était un défaut de mon outil.

**Écart déclaré à la consigne « SAFE certifié exclusivement ».** Les 14 essais ont lu le tier
**LOCAL** du coffre certifié (`runtime/coffre_certifie/local/shards`), pas le SAFE-cloud : celui-ci
ne porte que 5 shards de fills, dernier tag du 18/10 (feuille de route, chantier 12). Sur SAFE
strict, **toutes** ces hypothèses seraient `UNMEASURABLE`. Conséquence assumée : tout ce document
est de l'**exploration** ; aucun chiffre n'y est une preuve de PnL. Les rejets valent comme
mesures exploratoires ; un résultat positif aurait dû être rejoué sur SAFE avant tout statut
`PROMISING`. Aucune promotion n'en dépend, puisqu'il n'y en a aucune.

**Ce que la mesure dit de CopyVault, en une phrase :** sur 7 mois et 33 leaders lents, *suivre*
un leader — vite, lentement, quand il perd, quand il pèse, à plusieurs — ne rapporte rien après
son fill ; son information est dans l'heure du fill, et elle est déjà payée.

*(PÉRIMÉ pour le point 1 : la section 8 lui donne un a priori faible.)*

**Ce qui changerait le verdict (par ordre de valeur) :**

1. **Collecter les ordres en attente en continu, ≥ 30 jours** — la seule information *antérieure*
   au fill. Collecte actuellement éteinte sur décision de l'utilisateur.
2. **Re-mesurer L10 sur données neuves** (règle déjà figée ci-dessus) : c'est l'unique effet
   d'ampleur supérieure aux coûts, et le biais de survie joue contre lui.
3. **Élargir l'univers** : 80 comptes dont la moitié avec moins de 14 jours ne permettent aucune
   sélection ; il faut des centaines de comptes suivis *avant* de connaître leur résultat.

## 7. Suite — L2-fin, pré-enregistrée le 22/11 (écrite AVANT toute lecture du segment d'exécution)

**Pourquoi rouvrir L2.** C'est le seul effet du bon signe dont l'IC exclut zéro (+9,2 bps à 1 h
[0,5 ; 17,9]) — mais mesuré depuis l'ouverture de l'heure **suivante**, soit ~30 min après le
stop en moyenne. Un rebond de capitulation est rapide : il a pu être plus fort dans les premières
minutes, ou déjà fini. Les bougies horaires ne peuvent pas le dire ; les bougies 5 min le
peuvent, et elles n'existent que sur le segment d'exécution.

- **Découpe figée** du segment d'exécution, aucun résultat vu : **A = 26/10 → 03/11** (on y
  cherche l'horizon), **B = 04/11 → 12/11** (confirmation, consultée **une** fois, **un** horizon).
- **Événement** : par (leader, coin, fenêtre de 5 min), clôtures dont le PnL réalisé est négatif,
  part agressive ≥ 50 %, notionnel ≥ 1 000 USD.
- **Entrée** : ouverture de la première bougie 5 min ≥ dernier fill + 120 s. **Sens** : celui de la
  position fermée (contre le flux du stop). **Horizons** : 5, 15, 30, 60 min.
- **Coût** : 9 bps de frais + 6 d'écart supposé = **15 bps** (BBO observé seulement si un candidat
  sort).
- **Critère sur A** : une moyenne brute **> 15 bps** à un horizon, avec une borne basse d'IC95
  **> 0**. Sinon `REJECTED`, **B n'est pas consultée**.
- **Critère sur B** (si A passe) : même horizon, moyenne > 15 bps et borne basse > 0.
- Limite dite d'avance : A ne compte que 9 jours → 9 blocs de bootstrap, intervalles grossiers.

### Essai 15 — L2-fin mesurée sur la moitié A (26/10 → 03/11) : `REJECTED`

45 leaders, 4 635 événements de clôture ≥ 1 000 USD ; outil `tools/goal2_etude_cloture_fine.py`.
Rendement en bps dans le sens de la position fermée, [IC95 par blocs de jours] :

| famille | n | 5 min | 15 min | 30 min | 60 min |
|---|---|---|---|---|---|
| **clôture en perte agressive** (pré-enregistrée) | 396 | −0,7 [−1,5 ; 0,3] | −3,2 [−5,9 ; −0,5] | −4,2 [−11,1 ; 2,4] | −7,1 [−11,8 ; −0,4] |
| clôture en perte passive | 1 495 | −1,2 | −1,4 | −3,0 | −2,0 |
| clôture en gain agressive | 434 | +0,1 | −3,1 | −3,9 | +1,7 |
| clôture en gain passive | 2 308 | −1,5 | −1,0 | −2,7 | −1,6 |

**Aucun rebond à la minute** — le signe est même inverse (légère continuation). Critère non
atteint (il fallait > 15 bps avec une borne basse > 0) : **la moitié B n'est pas consultée**, elle
reste vierge. Le « +9,2 bps à 1 h » de l'essai 1 ne se retrouve pas sur une autre période à
meilleure résolution : sa borne basse était à 0,5 — c'était vraisemblablement du bruit.

**Verdict mis à jour : 15 essais, aucun edge.** Segments encore vierges : validation
(01/09 → 25/10), moitié B de l'exécution (04/11 → 12/11), OOS final (≥ 13/11). La moitié A de
l'exécution a été consultée **une fois**, pour L2-fin seulement.

## 8. Recherche externe, second passage (22/11, Exa + Tavily + TinyFish) — la piste « ordres en attente » pesée

Question posée : l'identité d'un compte, visible sur ses ordres **avant** exécution, prédit-elle
le prix ? Trois travaux récents sur Hyperliquid, lus sur leurs résumés et tableaux (non
reproduits : ils exigent le flux L4 ordre par ordre et un horodatage à la milliseconde, que le
coffre n'a pas — pour nous, `UNMEASURABLE`).

| source | ce qui est mesuré | ce que ça implique pour un suiveur de 100 USD à ~98 s de retard |
|---|---|---|
| Zhai, *Public Trader Identity* (arXiv 2608.04373) ; Ding & Zhai, ICAIF 2026 (arXiv 2611.05218) — 17,1 Md de messages, 147 113 wallets, juillet 2026 | le classement des wallets par *markout* à 10 s **persiste** (ρ = 0,52 entre fenêtres de 10 jours) ; il ajoute +13 % de R² à **1 s** (ridge) ; le gain relatif tombe à +3 % à **30 s** et, face au modèle le plus fort (arbres), n'y est plus distinguable de zéro (t = 1,6) ; au-delà les auteurs cessent de rapporter ; markout à 10 s, ajusté, du meilleur vingtile : **3,11 bps** | l'information d'identité existe, mais elle vit **moins de 30 secondes** et pèse **~3 bps** : trois fois moins que les frais taker, et finie avant même que notre poll la voie |
| Albers et al., *The price impact of nothing* (SSRN 6250378) | les ordres **rejetés** prédisent les rendements (connu par la citation qu'en font Ding & Zhai ; article non lu) | donnée du flux L4, que nous ne collectons pas |
| Barone & Lillo, *Trading in the Sunshine or in the Shade* (arXiv 2606.15715) | 4,3 M de méta-ordres cachés contre 465 000 TWAP visibles : les TWAP annoncés coûtent **moins** et laissent **moins** d'impact permanent | confirme le retrait de L5 : suivre un TWAP annoncé, c'est arriver après ceux qui lui fournissent la liquidité |

**Conséquence, contre ma propre recommandation du § 6.** J'y plaçais la collecte des ordres en
attente en tête de ce qui pourrait débloquer un edge. La littérature dit que l'information
portée par l'identité est un signal de **teneur de marché à la seconde**, pas de suiveur à la
minute — exactement ce que nos 15 essais mesurent à l'autre bout de l'échelle (zéro dès 5 min).
La piste reste `MORE_DATA`, mais son a priori est **faible** ; la seule variante que ces travaux
ne tranchent pas est celle des gros ordres posés **loin** du marché, lus comme des niveaux à
l'horizon de l'heure. Elle ne justifie pas, à elle seule, de rallumer la collecte.

**Lecture d'ensemble.** Mesures internes et externes convergent : sur Hyperliquid, l'avantage
d'information d'un compte se monnaie en secondes et en quelques points de base. Un compte de
100 USD qui paie 9 bps de frais et observe avec ~98 s de retard est structurellement du mauvais
côté de cet ordre de grandeur. **Ce n'est pas un manque de données : c'est l'économie du
produit.** Un edge CopyVault, s'il existe, ne viendra pas d'un meilleur signal de suivi mais
d'un changement de classe : frais maker réellement obtenus (réfuté le 19/11 par le taux de
remplissage), latence inférieure à la seconde (hors du périmètre poll/cloud), ou une famille
autre que la copie (hors du périmètre fixé).

## 9. Nouvelle famille V — l'allocation par **dépôt** dans les vaults (pré-enregistrée le 22/11, AVANT toute mesure de rendement)

**Pourquoi cette famille.** Les 15 essais précédents butent tous sur la même économie : 9 bps de
frais taker et ~98 s de retard. Le dépôt natif dans un vault n'a **ni l'un ni l'autre** : le
déposant reçoit exactement le résultat du vault, au prorata. C'est la forme de copie que le
produit prévoit lui-même. Elle a ses propres frictions, lues dans la documentation officielle
(pages « For vault depositors / leaders (legacy) », 22/11) :

- **10 % des profits** du déposant vont au leader, prélevés au retrait ;
- **blocage d'un jour** après dépôt (4 jours pour HLP, qui ne prélève rien) ;
- au retrait, si la marge manque, des positions sont fermées : **glissement possible, non chiffré** ;
- le leader garde ≥ 5 % du vault ; un vault ne traite que les perps opérés par les validateurs.

**Ce qui a déjà été mesuré sur ces courbes** (17/11, `etude_copiabilite --persistance`) : le
classement passé ne prédit pas le rendement suivant (IC +0,016 [−0,032 ; +0,059]) ; « copier tous
les vaults » rendait **+4,49 bps/jour** brut, sans intervalle ni coût de dépôt ; un modèle appris
trouvait des signes stables pour l'**ancienneté** (+, 100 % des dates), la **taille** (+, 94 %) et
la **volatilité** (−, 85 %), sans IC global. Personne n'a simulé le **déposant** (frais de 10 %,
pas de coût de transaction), ni séparé ce rendement du simple bêta de marché.

**Données.** Famille `vault_portfolio` du coffre LOCAL certifié : 2 346 vaults, points
hebdomadaires, médiane 673 jours. Univers = vaults ouverts ≥ 1 000 USD au 11–19/11/2026 **et**
vaults fermés dont le PnL cumulé a dépassé 1 000 USD en valeur absolue (1 864 fermés au 17/11).
Rendement hebdomadaire = ΔPnL / capital moyen (Dietz), module `copy_vault_persistence` réutilisé.

**Biais déclarés avant mesure.**
1. *Survie résiduelle* : un vault resté **ouvert mais vidé** (< 1 000 USD aujourd'hui) est absent.
   Biais vers le haut, de taille inconnue ; à borner par la liste publique si un candidat sort.
2. *Éligibilité* : le module écartait un vault dont le capital **moyen de la semaine** passait
   sous le seuil — une condition connue seulement après coup. Ici l'éligibilité est jugée sur la
   valeur en **début** de semaine (≥ 10 000 USD) ; les rendements indéfinis parmi les éligibles
   sont **comptés**, et une variante pessimiste les met à −100 %.
3. *Contamination* : l'étude du 17/11 a lu toutes les semaines jusqu'au 17/11 **en agrégat**. Pour
   les règles de sélection (V2, V4), la validation n'est donc pas strictement vierge. Dit ici.

**Segments (bornes inchangées).** Exploration : semaines closes avant le **01/09/2026** (depuis
2025). Validation : 01/09 → 25/10/2026, **une** lecture, pour la seule stratégie primaire qui
passerait. Au-delà du 26/10 : **rien n'est chargé** (le cache est tronqué à la source).

**Stratégies, toutes rééquilibrées chaque semaine, paramètres figés :**

| # | stratégie | règle (information connue en début de semaine) |
|---|---|---|
| V0 | panier égal | tous les vaults éligibles, poids égaux = espérance d'un dépôt au hasard |
| V1 | panier pondéré par la taille | poids ∝ valeur du vault = rendement du dollar moyen déposé |
| V2 | qualité (**primaire** de sélection) | ≥ 26 semaines d'historique ; moyenne des rangs de l'ancienneté (+), de la taille (+) et de la volatilité des 12 dernières semaines (−) ; quintile de tête |
| V3 | anti-qualité (témoin) | quintile de queue de la même note |
| V4 | extrêmes persistants | décile de tête du Sharpe des 26 dernières semaines (≥ 26 semaines observées) |

**Net du déposant.** Brut − 10 % de **chaque** semaine positive, sans compensation des pertes :
c'est une borne **haute** des frais réels (prélevés une fois, sur le profit net). Glissement au
retrait non modélisé, dit comme tel.

**Mesures.** Moyenne hebdomadaire et annualisée, volatilité, Sharpe, part de semaines positives,
repli maximal ; IC95 par bootstrap de **blocs de 4 semaines** ; excès contre V0 (apparié) ;
**alpha et bêta contre BTC** (régression hebdomadaire) ; deux moitiés de la période.

**Critères, écrits avant de regarder.**
- *V0, V1 (passifs)* : `PROMISING` seulement si le net a une borne basse d'IC95 > 0, **et** si
  l'alpha après bêta BTC a aussi une borne basse > 0, **et** si les deux moitiés sont positives.
  Un rendement positif expliqué par le bêta = « exposition de marché », pas un edge → `REJECTED`
  comme alpha, noté comme tel.
- *V2, V4 (sélection)* : il faut un **excès contre V0** de borne basse > 0, et que le témoin V3
  ne fasse pas aussi bien. Sinon `REJECTED`.
- Une seule stratégie, la mieux fondée, va en validation ; les autres n'y vont pas.

### Amendement V-1 (22/11) — imposé par la forme des données, **avant toute lecture d'un rendement**

Je n'ai regardé que des **horodatages**. Constats : les points tombent dans les 6 heures qui
précèdent le jeudi 00:00 UTC (84 %) — la grille hebdomadaire est donc bien calée — mais **31 % des
pas font 14 jours**, sur une parité propre à chaque vault. Une grille de 7 jours ne connaît alors
que 17 % des cellules (médiane 104 vaults par semaine sur 2 346).

- **Grille de 28 jours**, valeur à une borne = dernier point connu, vieux d'au plus **7,5 jours**
  (toutes les séries, hebdomadaires ou bimensuelles, y ont un point). Le rendement d'une période
  va du dernier point connu à une borne au dernier point connu à la suivante : rien de postérieur
  à la borne n'y entre. **Rééquilibrage toutes les 4 semaines** au lieu d'une.
- Paramètres transposés, pas choisis sur un résultat : historique ≥ **6 périodes** (≈ 24 semaines) ;
  volatilité sur les **6** dernières périodes (V2, V3) ; Sharpe sur les **6** dernières (V4).
- **Période de clôture.** Les 1 864 vaults fermés gardent leur série jusqu'à la collecte, à valeur
  nulle : la perte finale est donc **observable**, elle n'est pas perdue. Mais la formule de Dietz
  se déforme quand tout le capital sort (une perte de 20 % y devient −33 %). Quand la valeur de
  fin tombe sous 1 % de celle de début, le rendement est ΔPnL / valeur de **début**. Écart
  déclaré au module du dépôt, testé.
- Le net du déposant prélève 10 % de chaque **période** positive (toujours une borne haute).

### Essais 16 à 19 — famille V mesurée en exploration (34 périodes de 28 j, 18/01/2024 → 27/08/2026)

Outils : `tools/goal2_vaults_matrice.py`, `tools/goal2_depot_vaults.py` ; gardes :
`tests/test_goal2_depot_vaults.py` (15 tests, 14 injections rouges). Les tests ont trouvé un
défaut **avant** la première lecture : la dernière période de chaque série était perdue.

**Essai 16 — mesure primaire (rendements bruts de Dietz).** Net du déposant, bps par période :

| | vaults | net | IC95 | net/an | alpha vs BTC [IC95] | bêta |
|---|---|---|---|---|---|---|
| V0 panier égal | 138 | −160,5 | [−612 ; +314] | −21 % | −320 [−736 ; +89] | 0,55 |
| V1 pondéré par la taille | 138 | −284,6 | [−848 ; +274] | −37 % | −444 [−985 ; +53] | 0,54 |
| V2 qualité | 10 | −352,6 | [−718 ; +2] | −46 % | **−395 [−770 ; −84]** | 0,32 |
| V3 anti-qualité | 10 | +164,7 | [−924 ; +1 646] | +22 % | +184 [−1 067 ; +1 766] | −0,15 |
| V4 extrêmes persistants | 5 | −130,3 | [−570 ; +271] | −17 % | −152 [−581 ; +242] | 0,16 |

Aucun critère pré-enregistré n'est atteint : **V0, V1, V2, V4 `REJECTED`**. La validation n'est
pas consultée.

**Ce que la mesure a révélé, et qui corrige une référence du dépôt.** Le « copier tous les
vaults : +4,49 bps/jour » du 17/11 excluait les semaines où le capital moyen passait sous le
seuil — donc, mécaniquement, **la période où un vault se vide et ferme**. Ici ces 435 périodes
de clôture sont mesurées (le PnL cumulé reste constant après la fermeture dans 99,8 % des cas :
la perte finale est bien réelle) : rendement moyen **−23,5 %**, médian −8,2 %. Sans elles, V0
brut = **+319 bps** par période ; avec elles, **−22**. Tout le rendement « moyen » des vaults
était un biais de survie *à l'intérieur* des séries.

**Essais 17–19 — robustesse, décidée APRÈS la mesure primaire et dite comme telle.** La formule
de Dietz rend des rendements impossibles sous de gros flux (46 cellules sous −100 %, 80
au-dessus de +100 %, jusqu'à +4 801 %). Bornés à [−100 % ; +100 %] — un déposant ne perd pas plus
que sa mise :

| variante | V0 net | IC95 | alpha vs BTC [IC95] | V2 net | V4 net |
|---|---|---|---|---|---|
| bornés | **−436** | **[−823 ; −61]** | **−584 [−932 ; −272]** | −308 | −116 |
| bornés, flux > 50 % écartés | −572 | [−987 ; −182] | −715 [−1 105 ; −371] | +22 [−176 ; +238] | −266 |
| bornés, vaults ≥ 100 000 USD | −277 | [−680 ; +65] | −268 [−644 ; +21] | −544 [−977 ; −138] | −247 |

Dans les trois, le déposant moyen **perd**, et dans les deux premières l'intervalle exclut zéro
— alors même que BTC montait de 293 bps par période et que les vaults en portent la moitié
(bêta ≈ 0,5). Aucune stratégie de sélection n'a un net positif d'intervalle excluant zéro.

**Limite de l'ampleur (pas du signe).** Les vaults fermés n'entrent dans l'univers que si leur
PnL cumulé a dépassé 1 000 USD en valeur absolue : ceux qui ont fermé « sans histoire » manquent,
et ils dilueraient la moyenne vers zéro. Le signe négatif tient ; le −57 %/an est une borne
pessimiste.

**Verdict de la famille V : `REJECTED`.** Déposer dans les vaults d'utilisateurs a une espérance
négative pour le déposant ; l'ancienneté, la taille et le calme n'y changent rien. C'est la
contrepartie exacte du constat sur les fills : le leader moyen n'a pas d'avantage à transmettre.

## 10. V5 — le vault du protocole (HLP), pré-enregistré le 22/11 AVANT lecture

HLP est **exclu** du coffre (`VAULTS_EXCLUS`, vault de tenue de marché). C'est pourtant le seul
dépôt que le dépôt lui-même tient pour gagnant (`hlp_benchmark` : « 15 à 30 % APR » d'après une
donnée publique jamais reproduite ici). Conditions officielles : **aucune part de profit**,
blocage de **4 jours**.

- **Donnée** : une lecture de `vaultDetails` (API officielle, lecture seule, adresse publique
  de HLP) → courbe valeur / PnL. Hors coffre certifié : **exploratoire par construction**, à
  re-collecter et certifier avant tout statut au-dessus de `PROMISING`. Tronquée au 26/10/2026.
- **Mesure** : même grille de 28 jours, même Dietz, mêmes bornes ; net = brut (pas de frais).
- **Critères (ceux des paniers passifs, inchangés)** : borne basse d'IC95 du rendement > 0,
  **et** borne basse de l'alpha après bêta BTC > 0, **et** deux moitiés positives → `PROMISING`.
  Sinon `REJECTED` (ou « exposition de marché » si le bêta explique tout).
- **Ce que ce serait, même en cas de succès** : une prime de teneur de marché, **pas** un alpha
  de copie ; risque de queue réel (HLP porte l'inventaire et les liquidations).

### Essais 20 et 21 — V5 mesurée : le dépôt dans HLP, **`PROMISING`**

Outil : `tools/goal2_hlp.py` (une lecture de `vaultDetails` le 22/11, réponse brute conservée
dans le cache ; même grille, même Dietz, même troncature au 26/10 que la famille V).
43 périodes de 28 jours en exploration, du 11/05/2023 au 27/08/2026.

| mesure | valeur |
|---|---|
| rendement par période | **+229,9 bps**, IC95 **[112,7 ; 372,8]** → 30,0 %/an |
| volatilité · Sharpe | 454 bps · **1,83** |
| périodes positives · pire période · repli maximal | 86 % · −3,6 % · **−3,7 %** |
| contre BTC | alpha **+239,4 bps [104,7 ; 399,6]** · bêta **−0,03** · corrélation −0,09 |
| deux moitiés | +364,9 / +100,9 bps |
| par année | 2023 : +40,9 % · 2024 : +36,2 % · 2025 : +15,3 % · 2026 (8 périodes) : +6,5 % |
| 26 dernières périodes | +110,4 bps [42,6 ; 202,2] → **14,4 %/an [5,6 ; 26,4]** |
| 13 dernières périodes | +116,5 bps [−7,5 ; 290,1] → 15,2 %/an [−1,0 ; 37,8] |

**Critère pré-enregistré atteint** (IC > 0, alpha après bêta > 0, deux moitiés > 0).
**Validation, lue une fois** (essai 21) : 27/08 → 24/09 : **+54,6 bps** ; 24/09 → 22/10 :
**+28,8 bps**. Deux périodes positives, mais au rythme de ~5 %/an seulement.

**Ce que ce résultat est, et n'est pas.**
- C'est le **seul** objet de toute la mission dont le rendement net est positif, d'intervalle
  excluant zéro, neutre au marché, copiable par un compte de 100 USD (dépôt, blocage 4 jours,
  aucune part de profit) et reproductible par une lecture publique.
- Ce **n'est pas** un alpha de copie : c'est la prime de teneur de marché et de liquidateur du
  protocole. Elle **décroît** nettement (41 % → 36 % → 15 % → ~10 %/an, puis ~5 %/an sur la
  validation) à mesure que le vault grossit (de 82 000 à 560 millions de USD).
- Ordre de grandeur honnête aujourd'hui : **5 à 15 %/an**, soit **0,014 à 0,04 USD par jour** sur
  100 USD — à comparer au taux sans risque du moment, que je n'ai pas mesuré.
- Risque de queue réel et non visible dans un repli de −3,7 % : HLP porte l'inventaire et
  reprend les positions liquidées ; un seul épisode peut coûter plus que des mois de prime.
- Donnée **hors coffre certifié** → exploratoire ; `PROMISING` est le plafond tant qu'elle n'est
  pas collectée et certifiée, puis confirmée en prospectif.

**Preuve prospective : outillée, pas encore obtenue.** `tools/goal2_hlp.py --lire --segment
prospectif` ne compte que les périodes **commencées après le gel de la règle** (22/11/2026 ;
première période : 17/12/2026 → 14/01/2027), refuse tout verdict sous 6 périodes, et rend
aujourd'hui `MORE_DATA` (0 période). Elle ne demande **aucun collecteur** : une lecture publique
par mois suffit. La période 22/10 → 17/12 reste **verrouillée et non consultée**.

## 11. Verdict au 22/11/2026, soir — 21 essais

| famille | statut | la phrase |
|---|---|---|
| Copier les **trades** des leaders (L1–L4, L8–L10, L2-fin) | `REJECTED` / `UNMEASURABLE` | l'information d'un fill est consommée en moins de 30 s ; 9 bps de frais et ~98 s de retard n'en laissent rien |
| Ordres en attente des leaders | `MORE_DATA`, a priori faible | signal de teneur de marché à la seconde |
| **Déposer** dans les vaults d'utilisateurs (V0–V4) | `REJECTED` | espérance **négative** : −436 bps par 28 jours [−823 ; −61], aucune règle de sélection ne sauve |
| **Déposer dans HLP** (V5) | **`PROMISING`** | +230 bps par 28 jours [113 ; 373], bêta nul, mais prime décroissante (5–15 %/an aujourd'hui) |

**Aucun `PROVEN`.** Un seul `PROMISING`, et ce n'est pas un alpha de copie. Segments encore
vierges : validation pour les fills (01/09 → 25/10), moitié B de l'exécution, OOS final (≥ 13/11).

### Dépôt PAPIER dans HLP ouvert le 22/11/2026 (forward-paper)

`tools/goal2_hlp.py --lire --segment papier` : 100 USD papier déposés au dernier point connu
(22/11/2026 14:48 UTC), registre chaîné `runtime/reports/copy_vault_quant_lab/goal2/HLP_PAPIER.ndjson`.
Chaque lecture ajoute une marque calculée **uniquement** sur les points postérieurs à la précédente
(Dietz : le dépôt d'un tiers n'est pas un gain). Rien n'est jamais recalculé sur le passé.
Aujourd'hui : 100,0000 USD, 0 jour. C'est le seul moyen honnête d'obtenir la preuve prospective :
laisser le temps passer et relire.

*(alimenté au fil de l'eau)*

## 12. L11 — le portage dans le sens du leader (pré-enregistré le 22/11/2026 au soir, AVANT toute mesure)

**Origine.** L3 (copie lente) est rejetée sur la dérive de PRIX seule : la « dérive » était celle du
coin. Le funding n'y était pas compté. Or un suiveur lent qui TIENT la position encaisse (ou paie)
le funding horaire. Hypothèse : copier une ouverture seulement quand le funding observé paie le côté
du leader, et tenir H heures, rapporte prix + funding au-delà des frais — et le leader y AJOUTE
quelque chose par rapport à un simple portage sur le même coin.

**Règle (figée ici).**
- Événement : ouverture (`Open Long` / `Open Short`) agrégée par (leader, coin, heure), notionnel
  ≥ 1 000 USD (mêmes règles que les essais 1–7).
- Condition, connue à l'entrée : le DERNIER taux de funding horaire publié avant l'instant d'entrée
  paie le côté du leader (`−sens × funding > 0`). Aucun taux postérieur n'est lu.
- Entrée : ouverture de la première bougie 1 h ≥ dernier fill + 120 s. Sortie à **72 h** (24 h en
  secondaire). Rendement = `sens × Δprix` + funding encaissé sur les heures tenues (`−sens × Σ taux`).
- Coût : frais taker aller-retour de la source unique + 6 bps d'écart supposé, affichés à part.
- **Jumeau** : même coin, heure à ≥ 24 h de l'événement, MÊME condition de portage favorable pour le
  même sens, mouvement des 72 h précédentes à ± max(20 bps, 25 %) ; même calcul prix + funding.
- Segment : **exploration** seule (26/04 → 31/08), données du tier LOCAL — écart déjà déclaré au §6.

**Critère d'arrêt (figé ici).** `REJECTED` si (a) le net après coûts n'a pas un IC95 (blocs de jours)
au-dessus de zéro, OU (b) l'excès sur le jumeau n'a pas un IC95 excluant zéro, OU (c) l'effet tient à
un seul leader (retrait du plus favorable). Si (a) seul passe : c'est un portage générique, pas un
alpha de copie — statut `REJECTED` pour la famille copie (noté comme piste de portage). Sinon : règle
figée telle quelle, validation consultée UNE fois.

### Essai 22 — L11 mesurée (exploration) : `REJECTED`

`tools/goal2_portage_leader.py` (signes, causalité et refus des fenêtres trouées vérifiés d'abord sur
données synthétiques : `tests/test_goal2_portage_leader.py`, 4 tests). 3 938 ouvertures ≥ 1 000 USD,
1 393 éligibles (funding connu favorable), 31 leaders, 101 coins ; coût aller-retour 15,0 bps.

| horizon | prix | funding encaissé | net après coûts | excès sur le jumeau | sans le meilleur leader |
|---|---|---|---|---|---|
| 72 h | +15,9 [−103 ; +129] | **+7,2 [5,7 ; 8,9]** | +8,1 [−110 ; +121] | +38,2 [−92 ; +172] | +27,6 [−105 ; +144] |
| 24 h | −41,2 [−105 ; +16] | +3,1 [2,5 ; 3,9] | −53,1 [−116 ; +4] | −20,7 [−90 ; +44] | −27,0 [−96 ; +35] |

**Lecture.** Le funding est la seule composante mesurée avec certitude : +7,2 bps en 72 h, réel mais
**la moitié du coût d'un aller-retour**. Le prix, ±100 bps, noie tout ; le leader n'ajoute rien de
mesurable au jumeau. Critère pré-enregistré atteint : non promue, validation non consultée. Ce que
ça dit de la piste « portage » : à 2,4 bps par jour, un portage ne paie ses frais qu'au-delà de
~6 jours de détention, et seulement si le prix n'est pas tiré par le risque directionnel — c'est une
stratégie de base (carry couvert), pas une copie.

**Bilan : 22 essais, aucun alpha de copie.** Segments vierges inchangés (validation des fills,
moitié B de l'exécution, OOS final).

## 13. Passage du labo CopyVault sur la moitié A du segment d'exécution (pré-enregistré le 22/11, 19:15)

**Décision prise seule, sur consigne de l'utilisateur** (« prends toujours toi les bonnes décisions,
ne bloque jamais ») : faute de corpus SAFE après le 18/10, le labo tourne sur le tier **LOCAL**,
étiqueté comme tel — exploration, jamais preuve.

**Pourquoi cette fenêtre et pas une autre.** Les carnets liés aux signaux n'existent que sur 19 jours.
Depuis le 13/11 = OOS final (verrouillé) ; 04/11 → 12/11 = moitié B, VIERGE (réservée à la
confirmation) ; reste la moitié A (26/10 → 03/11), déjà consultée une fois pour L2-fin, dont seuls
le **26, le 27 et le 28/10** ont des points de contrôle. Le plan est donc 26/10 00:00 → 29/10 00:00,
tranches de 2 h. Le plan précédent (`plan_tranches.json`, 13/11 → 20/11) couvrait l'OOS : il n'est
pas réutilisé.

**Règle.** Labo tel qu'il est (`tools/labo_deux_phases.py`, recherche Halton, cliquet LCB ajusté
de la multiplicité, `--max-trials 128`, raccord L2 éteint : une variable à la fois).
**Critère.** Un candidat n'est retenu que si son LCB OOS interne est > 0 après coûts ; il serait
alors figé et confirmé UNE fois sur la moitié B. Sinon `REJECTED`. Le passage compte comme l'essai 23.

### Amendement 13-1 (22/11, 19:20) — écrit AVANT tout résultat du labo, imposé par la forme des données

Premier lot du passage pré-enregistré : **0 fill causal** le 26/10 entre 00 h et 02 h. Mesure du
coffre : les fills OBSERVÉS EN DIRECT (`fills_forward`) font 10 575 le 26/10 puis ~0 jusqu'au 07/11 ;
les ~55 000 fills par jour du rattrapage REST ne sont pas causaux (observés après coup) et le labo a
raison de les ignorer. Les données exécutables commencent le **07/11**. Le passage sur 26–28/10
mesurera donc ~rien : il est conservé tel quel (essai compté), sans interprétation.

Constat de protocole : le plan existant `plan_tranches.json` (13/11 → 20/11) prouve que le labo a
**déjà cherché** sur cette période le 20/11, avant la mission 2. Pour le labo, 13–20/11 n'est donc pas
vierge. La moitié B (04/11 → 12/11) l'est, et sa seule réservation (confirmer L2-fin) est tombée avec
le rejet de L2-fin.

**Nouvelle règle, figée ici :**
1. **Recherche** : labo sur 13/11 → 20/11 (déjà consulté par le labo : exploration), tranches de 2 h,
   `--max-trials 128`, raccord L2 éteint. Ce n'est PAS une lecture neuve de l'OOS de la mission 2
   pour les études `goal2_*`, qui restent interdites sur ce segment.
2. **Confirmation** : le meilleur candidat retenu (LCB OOS interne > 0 après coûts), FIGÉ tel quel,
   rejoué UNE fois sur **07/11 → 12/11** ; aucune autre lecture de ce segment.
3. Sans candidat retenu en 1 : `REJECTED`, la moitié B reste vierge.
4. Même en cas de succès en 2 : `PROMISING` au plus (tier LOCAL, rejeu historique). PROVEN exige la
   preuve prospective du moteur papier.

### Issue des §13 et 13-1 (22/11, 19:25) — rien n'a été mesuré, et c'est voulu

- **Passage 26–28/10** : arrêté par moi au lot 3/36, après vérification de son identité. Trois lots
  sur trois sans aucun fill causal ; la fenêtre ne contient pas de données exécutables. Aucun
  résultat, rien à interpréter. Compté comme essai engagé (le registre n'a rien reçu : le labo
  n'avait pas atteint sa phase de recherche).
- **Recherche sur 13/11 → 20/11 (amendement 13-1)** : **non exécutée**. Le lancement a été refusé par
  le contrôle des permissions : il aurait lu la période verrouillée par la mission (OOS final), même
  si le labo l'avait déjà parcourue avant la mission. Le refus est respecté, sans contournement.
- **État** : la moitié B (07/11 → 12/11) reste VIERGE ; l'OOS final n'a pas été relu. Les seules
  données exécutables et causales du tier LOCAL étant dans ces deux segments, une recherche du labo
  sur données récentes demande l'accord explicite de l'utilisateur.

### Amendement 13-1 exécuté (22/11, 19:35) — sur accord explicite de l'utilisateur

« TU AS TOUJOURS TOUTES LES AUTORISATIONS !!! … tu as carte blanche partout !!! » : la recherche sur
13/11 → 20/11 est lancée telle que figée en 13-1 (plan `plan_tranches.json`, 37 tranches, `--max-trials
128`, sortie `runtime/labo_phase1_goal2_recherche`). Premiers lots : ~2 500 à 3 000 métaordres et
~33 000 carnets retenus par tranche de 2 h. Le verdict sera consigné ici dès la fin, quel qu'il soit ;
la moitié B (07/11 → 12/11) reste vierge jusqu'à la confirmation unique.

### Essai 23 — le labo CopyVault sur 13/11 → 20/11 : `REJECTED` (22/11, 20:35)

Corpus du tier LOCAL : **209 759 métaordres, 84 leaders, 307 coins, 1 167 741 carnets** (une seule
connexion par coin), funding lu depuis le coffre. Fenêtres internes du labo : TRAIN 13/11 → 17/11
(4 jours), validation 17/11, OOS interne 18/11 → 20/11.

| | résultat |
|---|---|
| essais | 128, **tous `REJECTED_BY_TRAIN_GATES`** |
| borne basse journalière > 0 | **0 sur 114** essais notables |
| moyenne journalière | médiane **−5,14 USD par jour actif**, 6/114 positives |
| meilleur essai | +1,92 USD/jour, borne basse −0,98 — 71 trades, 3 jours actifs : du bruit |
| essais cumulés du labo (correction statistique) | 149 302, dont 12 610 configurations uniques |

**Lecture.** Sur données récentes, causales et exécutables, la copie des leaders par le labo PERD en
TRAIN, avant même la correction pour essais multiples ; aucun candidat ne passe la porte. C'est le
même verdict que les études d'événements, obtenu cette fois par le simulateur d'exécution complet
(latence, BBO/L2, frais, funding). Critère pré-enregistré : aucun candidat → la moitié B (07/11 →
12/11) n'est **pas** lue et reste vierge. Limite : 4 jours de TRAIN, c'est court ; plus de jours de
collecte élargiraient l'échantillon, sans raison de croire que le signe change.

**Bilan : 23 essais, aucun alpha de copie.**

## 14. Pourquoi on ne trouve pas — diagnostic (22/11, soir) et L12 pré-enregistrée

**Mesure 1 — les leaders gagnent-ils ?** Oui : exploration, 33 leaders, 231 M USD de notionnel,
PnL réalisé +1,50 M, frais 62 k, **net +62 bps du notionnel**, 25 leaders sur 33 positifs (biais de
survie : ils ont été retenus en novembre parce qu'ils gagnaient). Clôtures agressives +159 bps,
passives +98 bps.

**Mesure 2 — la latence mange-t-elle l'avance ?** Non (moitié A, 30 421 ouvertures, 43 leaders) : du
prix du leader au prix accessible 2 min après, **+1,7 bps** seulement. Puis, pour un suiveur à horizon
fixe : +3,4 bps à 1 h, **+13 bps à 4 h**, **−52 bps à 24 h**.

**Conclusion provisoire** : l'edge du leader n'est ni dans l'entrée (le suiveur entre au même prix à
2 bps près) ni dans une dérive durable ; il est dans la **SORTIE** — il ferme avant le retournement.
Presque tous nos essais tenaient un horizon FIXE : ils mesuraient la mauvaise chose.

### L12 — la sortie miroir (pré-enregistrée ici, AVANT la mesure)
- Entrée : ouverture (`Open Long/Short`) d'un leader, notionnel ≥ 1 000 USD ; le suiveur entre à
  l'ouverture de la première bougie 5 min ≥ fill + 120 s.
- Sortie : au PREMIER fill de clôture (`Close` du même côté) du même leader sur le même coin après
  son ouverture, à l'ouverture de la première bougie 5 min ≥ ce fill + 120 s. Plafond de détention
  7 jours (au-delà : sortie forcée, comptée).
- Coût : frais taker aller-retour + 6 bps d'écart.
- **Jumeau** : même coin, même sens, MÊME durée de détention, entrée tirée à ≥ 24 h de l'événement ;
  moyenne de ≥ 20 jumeaux. Il mesure si le TIMING du leader compte, au-delà du coin et de la durée.
- Segment : moitié A (26/10 → 03/11, déjà consultée), sorties bornées au 04/11 + 7 j de bougies
  sans lire de SIGNAL dans la moitié B.
- **Critère** : `REJECTED` si le net n'a pas un IC95 (blocs de jours) > 0, ou si l'excès sur le jumeau
  n'a pas un IC95 > 0, ou si l'effet tient au seul leader le plus favorable. Sinon : figée, puis
  confirmée UNE fois sur la moitié B.

### Essai 24 — L12 sortie miroir (moitié A) — **PÉRIMÉ** (biais de sélection, voir essais 26–27)

`tools/goal2_sortie_miroir.py` (appariement et signes vérifiés d'abord : `tests/test_goal2_sortie_miroir.py`).
11 139 ouvertures ≥ 1 000 USD → 8 236 mesurées, 39 leaders ; détention médiane **0,5 h**, aucune
sortie forcée ; coût 15,0 bps (frais taker aller-retour + 6 bps d'écart supposé).

| | bps | IC95 (blocs de jours) |
|---|---|---|
| rendement brut | **+21,4** | [11,7 ; 40,7] |
| net après coûts | +6,4 | [**−3,3** ; 25,7] |
| excès sur le jumeau (même coin, sens, durée) | **+18,5** | [6,3 ; 42,6] |
| excès sans le leader le plus favorable | +16,1 | [2,6 ; 42,4] |

**Lecture.** Pour la première fois en 24 essais, le leader apporte une information mesurable : le
MOMENT où il sort vaut ~18 bps au-delà d'une détention de même durée au hasard, et ce n'est pas un
seul leader. Mais 15 bps de coûts n'en laissent pas assez : borne basse du net négative → critère
pré-enregistré non atteint, `REJECTED`, moitié B non lue. **Le coût ne sera pas abaissé après coup.**

**Suite légitime (à pré-enregistrer AVANT toute nouvelle lecture)** : le levier est le coût, pas le
signal. Une variante dont le coût est MESURÉ (écart réel au BBO à l'entrée et à la sortie) au lieu
de supposé, ou restreinte à des coins liquides définis sur des données ANTÉRIEURES, serait un nouvel
essai compté, confirmé une seule fois sur la moitié B.

### L12b — sortie miroir au coût MESURÉ (pré-enregistrée le 22/11 au soir, AVANT la mesure)
- Règle identique à L12 (entrée 2 min après l'ouverture, sortie 2 min après la première clôture du
  même côté, jumeau de même durée).
- **Coût par coin = frais taker aller-retour + l'écart achat-vente MÉDIAN observé** sur ce coin dans
  les carnets du coffre de la moitié A (`goal2_cache/ecart_bbo_execution_a.json`, 11 893 carnets).
  L'écart est une donnée de marché, pas une issue de stratégie : aucune fuite du résultat.
- **Univers = les seuls coins dont l'écart est mesuré** (10 coins) ; les autres sont REFUSÉS, jamais
  crédités d'un écart favorable.
- Critère : identique à L12. Si atteint : règle figée et confirmée UNE fois sur la moitié B (07/11 →
  12/11), dont les carnets servent alors à mesurer l'écart de la même façon.

### Essai 25 — L12b sortie miroir au coût mesuré — **PÉRIMÉ** (biais de sélection, voir essai 27)

3 646 événements sur 8 236 ont un écart mesuré (7 coins, 30 leaders) ; coût médian **9,1 bps**.
Brut +22,4 [14,2 ; 36,6] ; **net +13,2 [5,0 ; 27,4]** (premier net à borne basse positive) ;
excès sur le jumeau +13,4 [**−0,6** ; 34,2] ; sans le meilleur leader +6,5 [−8,0 ; 17,1]. Critère non
atteint : le net positif peut venir de la dérive de ces 7 coins sur la période, pas du leader.

### Correction pour essais multiples (25 essais, Bonferroni 99,8 %), recalculée sur L12 / L12b

L12 excès sur le jumeau [2,3 ; 63,2] ; L12 net à 15 bps [−6,3 ; 45,1] ; **L12b net au coût mesuré
[2,1 ; 41,6]**. Deux bornes basses restent positives après correction — mais sur **10 jours
indépendants** seulement : un quantile à 99,8 % sur 10 blocs est fragile. D'où une confirmation.

## 15. L12c — CONFIRMATION UNIQUE sur la moitié B (figée ici, AVANT toute lecture de la moitié B)

- **Règle, figée** : L12b à l'identique — entrée 2 min après l'ouverture d'un leader (≥ 1 000 USD),
  sortie 2 min après sa première clôture du même côté sur ce coin (plafond 7 jours) ; coût par coin =
  frais taker aller-retour + écart médian MESURÉ sur ce coin dans les carnets du coffre de la
  moitié B ; coins sans écart mesuré REFUSÉS.
- **Segment** : moitié B, 04/11 → 12/11, lue UNE seule fois ; bougies et clôtures bornées par la
  barrière de l'OOS final (13/11) — une position non close avant est comptée sortie forcée.
- **Critère principal** : net moyen après coûts, IC95 par blocs de jours, borne basse > 0.
- **Critère secondaire** (rapporté, ne sauve pas un échec du principal) : excès sur le jumeau > 0.
- **Issue** : principal atteint → `PROMISING` (rejeu historique, tier LOCAL) ; PROVEN exigera la
  preuve prospective du moteur papier, qui applique déjà la sortie miroir (`LEADER_A_CLOS`).
  Principal manqué → `REJECTED`, sans nouvel essai sur ce segment.

### Essais 26–27 — L12 et L12b CORRIGÉES : le « premier signal » venait d'une erreur de mon outil

**L'erreur** : `mesurer()` sautait en silence toute position dont la sortie tombait après la dernière
bougie disponible. Ce sont les positions que le leader GARDE longtemps — surtout des perdantes.
Exclure une ligne selon son ISSUE, c'est fabriquer un résultat. Corrigé : sortie forcée à la dernière
bougie, comptée et affichée.

| moitié A | avant (biaisé) | corrigé |
|---|---|---|
| L12, tous coins, 15 bps | brut +21,4, net +6,4, excès +18,5 [6,3 ; 42,6] | **brut −21,1 [−65,5 ; 28,6]**, net −36,1, excès +3,1 [−28,1 ; 40,2] — sorties forcées 5 % |
| L12b, 7 coins, coût mesuré | net +13,2 [5,0 ; 27,4] | net +8,5 [3,1 ; 17,5], excès +12,4 [−1,3 ; 32,7] |

Le « premier signal réel » de L12 était ENTIÈREMENT cet artefact. `REJECTED` (essai 26 et 27).

### Essai 28 — L12c, confirmation UNIQUE sur la moitié B (vierge) : `REJECTED` au critère principal

67 747 copies mesurées (74 leaders, 193 coins à écart mesuré, coût médian 9,5 bps, sorties forcées
5 %, détention médiane 0,3 h).

| | bps | IC95 |
|---|---|---|
| brut | +11,8 | [−0,1 ; 20,2] |
| **net (critère principal)** | **+1,7** | [**−10,1** ; 10,0] |
| excès sur le jumeau (secondaire) | **+14,5** | [**6,2** ; 20,4] |
| excès sans le meilleur leader | +10,8 | [5,4 ; 14,4] |

**Lecture.** Le critère principal échoue : la sortie miroir n'est PAS rentable aux coûts actuels.
Mais, sur des données vierges et 8 fois plus nombreuses, le moment où le leader sort vaut ~11 à
15 bps de mieux qu'une détention de même durée au hasard, et pas grâce à un seul leader : **une
information du leader existe, confirmée hors échantillon, plus petite que le coût de la copier.**
Pour la monétiser il faudrait réduire le coût (entrées passives, palier de frais) — à tester comme
un essai neuf, pas en retouchant celui-ci. La moitié B est désormais CONSULTÉE.

## 16. Mes erreurs, et ce que j'en change (22/11, soir)

1. **Exclure des lignes selon leur issue** (essais 24–25) : un faux signal de +21 bps, attrapé
   seulement parce que j'ai modifié le code pour la moitié B. → Toute ligne écartée doit être COMPTÉE
   avec son motif, et une mesure qui écarte une part dépendant de l'issue est refusée.
2. **J'ai mis 23 essais à poser la première question** : d'où vient le PnL des leaders ? La
   décomposition (entrée, latence, détention, sortie) aurait dû précéder tout essai : elle montre que
   la latence ne coûte que ~2 bps et que l'information est dans la sortie.
3. **Horizons fixes** dans presque tous les essais : on mesurait la mauvaise chose.
4. **Un coût supposé de 6 bps pour tous les coins** : l'écart mesuré va de 0,2 à 11 bps (médiane 1,5
   sur la moitié A, 4,1 sur la moitié B). Une seule source de coût, mesurée, partout.
5. **Aucune correction pour essais multiples** pendant 25 essais. Désormais rapportée (Bonferroni
   sur le registre).
6. **Recherche lancée sur une chaîne de données qui perdait des preuves en silence** (points de
   contrôle, frais des fills, références invérifiables). Il fallait un témoin positif de bout en
   bout AVANT de chercher.
7. **Faible puissance prise pour un rejet** : 10 jours indépendants ne disent souvent « rien »,
   pas « non ».
8. **Protocole mal tenu** : j'ai déclaré l'OOS du 13/11 vierge alors que le labo l'avait lu le 20/11.
9. **Des heures fausses écrites dans ce journal**, corrigées ensuite.
10. **Trop de réponses « j'attends votre décision »** au lieu de trancher ce qui était interne.

**Où en est la question « pourquoi on ne trouve pas »** : les leaders gagnent (62 bps net, avec biais
de survie) ; leur information est réelle mais elle sert surtout au moment de SORTIR, et elle vaut
moins que le coût d'une copie taker. Ce n'est pas l'absence d'edge ; c'est un edge plus petit que le
coût. Le moteur papier, qui sort déjà comme le leader (`LEADER_A_CLOS`), en donnera la mesure
prospective une fois relancé.

## 17. La preuve prospective démarre (22/11/2026, 21:27)

Aucun rejeu historique ne peut plus prouver quoi que ce soit : toutes les données exécutables ont été
consultées (moitié B pour L12c, 13/11 → 20/11 par le labo). La seule preuve restante est PROSPECTIVE.
L'apprentissage parallèle (45 variantes de la règle du bac à sable, cycles fantômes, voir
AVANCEMENT_OBJECTIF) tourne désormais en processus autonome (`tools/apprentissage_en_continu.py`,
journal `runtime/logs/apprentissage_en_continu.log`) : **début de la preuve le 22/11 à 21:27**, seuls
les fills postérieurs comptent. Règle figée dans le code : championne = borne basse > 0 corrigée
(variantes × jours regardés), ≥ 5 jours, ≥ 50 cycles ; elle seule arme le bac à sable en papier réel,
puis l'échelle PROBE → ALPHA juge les cycles réels. **Statut à ce jour : MORE_DATA** — aucune
variante n'a encore les jours requis ; le premier verdict possible est le 27/11 au plus tôt.

## 18. H14 — la fermeture de RÉALLOCATION (pré-enregistrée le 22/11, 21:50, AVANT toute mesure)

**Source externe.** von Beschwitz, Lunghi & Schmidt (Federal Reserve FEDS 2021-022, 21 fonds long-short,
10 ans) : des gérants habiles ferment TROP TÔT quand leur capital est réalloué ailleurs ; après ces
fermetures le prix continue dans le sens de la position fermée (~0,9 % d'alpha laissé, un tiers du
potentiel). Nos essais n'ont jamais séparé une fermeture de réallocation d'une fermeture « informée ».

**Hypothèse.** Quand un leader ferme (`Close …`) une position ET ouvre (`Open …`) une position sur un
AUTRE coin dans la même fenêtre, la fermeture est une réallocation : le prix du coin fermé continue
dans le sens de la position fermée. Le suiveur la REPREND (long si le leader fermait un long).

**Règle (figée).**
- Événement : fermeture agrégée par (leader, coin, heure), notionnel ≥ 1 000 USD (règles des essais 1–7).
- Réallocation : le même leader a une ouverture ≥ 1 000 USD sur un autre coin dans [−1 h, +1 h] de la
  fermeture. Entrée : première bougie 1 h ≥ max(dernier fill de fermeture, fill d'ouverture) + 120 s —
  la classification n'utilise rien d'inconnu à l'entrée.
- Rendement dans le sens de la position fermée, horizons 24 h (principal) et 72 h (secondaire).
- Jumeau : même coin, même sens, mouvement des 72 h précédentes comparable, ≥ 24 h de l'événement.
- Coût affiché : frais taker aller-retour + 6 bps d'écart.
- Témoin interne : les fermetures SANS réallocation, même calcul.

**Critère (figé).** Exploration (26/04 → 31/08) : excès sur le jumeau à 24 h, IC95 (blocs de jours)
> 0, ET net après coûts > 0, ET effet hors du leader le plus favorable > 0. Sinon `REJECTED`.
Si atteint : règle figée telle quelle, **validation (01/09 → 25/10, jamais lue pour les fills)
consultée UNE fois**, même critère.

### Essai 29 — H14 mesurée (exploration) : `REJECTED`

3 540 fermetures ≥ 1 000 USD, dont 1 312 de réallocation (entrée après avoir VU l'ouverture ailleurs).
Réallocation à 24 h : brut +4,3 [−54,8 ; 64,9], net −10,7, **excès sur le jumeau −14,2 [−64,0 ; 38,2]** ;
à 72 h : excès −15,6 [−105,2 ; 84,5]. Témoin sans réallocation : excès −24,2 à 24 h. Le mécanisme des
fonds actions (fermer trop tôt pour réallouer) ne se retrouve pas chez nos leaders. Critère non atteint :
**validation non lue, toujours vierge**.

## 19. H15 — persistance de l'informativité des leaders à NOS horizons (pré-enregistrée le 22/11 au soir, AVANT toute mesure (heure non relevée ; corrigée : j'avais écrit une heure inventée))

**Source.** Zhai (arXiv 2608.04373, 2026) : sur Hyperliquid, le classement des wallets par markout de
leurs ordres agressifs à 10 s est persistant d'une fenêtre de 10 jours à la suivante (Spearman 0,52),
et le haut du classement prédit les rendements à 1 s. Inutilisable tel quel (nous copions à ~2 min,
9 bps de frais) ; la question transposable : **la qualité d'un leader est-elle persistante aux horizons
où nous agissons ?** L4 (sélection par copiabilité au niveau du compte) était `UNMEASURABLE` faute de
puissance ; un score au niveau du TRADE, comme dans l'article, en a beaucoup plus.

**Règle (figée).**
- Événements : ouvertures (`Open …`) agrégées par (leader, coin, heure), notionnel ≥ 1 000 USD.
- Entrée : première bougie 1 h ≥ dernier fill + 120 s. Markout à H = sens × rendement de l'ouverture
  d'entrée à l'ouverture H heures plus tard, MOINS le rendement équipondéré du marché sur le même
  intervalle (`goal2_robustesse.rendement_du_marche`).
- Fenêtres successives de 10 jours. Score d'un leader à la fin d'une fenêtre = moyenne pondérée par le
  notionnel des markouts de ses événements dont l'étiquette est CONNUE avant la fin (entrée + H < fin).
  Au moins 10 événements, sinon non classé.
- Évaluation sur la fenêtre SUIVANTE : événements des leaders classés du tiers supérieur (« top ») contre
  tous les leaders classés (« tous »).
- Horizons 1 h, 4 h, 24 h ; **principal : 4 h**.
- Placebo : 200 tirages d'un tiers au hasard parmi les leaders classés, même nombre de leaders.

**Critère (figé), exploration (26/04 → 31/08).** `CANDIDAT_VALIDATION` seulement si, à 4 h :
(a) écart top − tous, IC95 par blocs de jours > 0 ; (b) top, brut − coût (frais taker aller-retour +
6 bps) > 0, IC95 > 0 ; (c) l'écart dépasse 95 % des 200 tirages placebo ; (d) persistance : Spearman
moyen des scores entre fenêtres consécutives > 0. Sinon `REJECTED`. Si atteint : règle figée, validation
(01/09 → 25/10, vierge pour les fills) lue UNE fois.

### Essai 30 — H15 mesurée (exploration) : `REJECTED` au critère principal (4 h)

3 938 ouvertures, 32 leaders, coût 15 bps. Écart « tiers supérieur − tous » (markouts ajustés du marché) :
1 h +4,2 [−4,2 ; 12,1], placebo 88 % ; **4 h +11,0 [−8,2 ; 29,9], placebo 86 %** (critère principal non
atteint) ; 24 h **+44,8 [−0,3 ; 91,6], placebo 98 %**, Spearman moyen 0,25 ± 0,13 (6 paires), net du top
+31,1 [−55,0 ; 139,0]. Persistance faible à 1 h (0,05), modeste à 24 h (0,25 ; l'article mesure 0,52 à 10 s).

### H15b — la même règle à 24 h, HYPOTHÈSE NÉE DES DONNÉES (pré-enregistrée le 22/11 au soir, AVANT la validation (heure non relevée ; corrigée : j'avais écrit une heure inventée))

Le 24 h est le résultat le plus suggestif de la mission, mais c'était un horizon SECONDAIRE : le choisir
après coup serait un choix d'horizon qui arrange. Il est donc figé ici et confronté **une seule fois** au
segment de validation (01/09 → 25/10, vierge pour les fills), qui sera ensuite CONSOMMÉ.
- Règle : celle de H15, à l'identique (fenêtres de 10 jours, score causal, tiers supérieur, 200 tirages),
  horizon **24 h**.
- Critère : écart top − tous, IC95 > 0 ; ET net du top (brut − 15 bps), IC95 > 0 ; ET placebo > 95 %.
- Issue : atteint → `PROMISING` (historique, tier LOCAL ; preuve prospective requise ensuite) ; sinon `REJECTED`.

### Essai 31 — H15b, confirmation UNIQUE sur la validation : `REJECTED`

5 345 ouvertures, 35 leaders. À 24 h : écart top − tous **−28,7 [−77,4 ; 16,4]**, placebo **57 %**, Spearman
−0,03 ± 0,14 ; à 4 h : +1,5 [−10,2 ; 12,1], placebo 50 %. Le 24 h de l'exploration était du bruit : la
persistance de l'informativité des leaders ne se retrouve pas sur données neuves. **La validation des
fills (01/09 → 25/10) est désormais CONSOMMÉE.** Il ne reste plus aucun segment historique vierge : toute
preuve passe par le prospectif.

## 20. Les cinq pistes publiées du 22/11 — bilan (22/11 au soir (heure non relevée ; corrigée : j'avais écrit une heure inventée))

| piste | ce que dit la source | ce que nous avons fait | verdict |
|---|---|---|---|
| A. Informativité des wallets (Zhai 2026) | classement par markout à 10 s persistant (Spearman 0,52) | H15 à NOS horizons, puis H15b à 24 h confirmée une fois sur la validation | `REJECTED` (essais 30–31) ; validation CONSOMMÉE |
| B. TWAP / métaordres | flux résiduel des TWAP publics | mesuré : 15 ordres TWAP, 0,19 % des fills de nos leaders | trop rare pour un signal (confirme L5) |
| C. Toxicité et refus d'exécution | quand ne pas copier | ne peut se juger que sur carnets récents, tous consultés → PRÉPARÉ en prospectif : chaque cycle fantôme enregistre désormais l'absorption (prix déjà bougé depuis le fill) et la latence, sans changer la règle ni les gains | à juger sur données neuves |
| D. Herding ou course (Bai 2026) | κ ≈ 0,75 sur un carnet on-chain = course au prix de Binance | κ sur nos leaders : **médiane 0,02** sur 44 coins ; part des paires du même compte 0,86 | leurs flux sont du DÉCOUPAGE propre à chacun, pas une course commune : explique l'échec du consensus (L9) |
| E. Données Level 4 (Albers et al., Zenodo) | ordres, rejets, diffs de carnet | métadonnées seulement : déc. 2025, BTC/ETH/SOL, ~215 Go ; aucun chevauchement avec nos leaders (depuis avril 2026) ; rejets non observables par notre moteur | non utilisable comme signal causal ; rien téléchargé |

**32 essais au registre. Plus aucun segment historique vierge pour les fills** : la preuve ne peut plus
venir que du prospectif (apprentissage parallèle depuis le 22/11 21:27, premier verdict possible le 27/11).

## 21. Où est l'argent — carte des mécanismes (22/11, ~21:55 heure de Paris, relevée par l'horloge système) et seule voie de preuve restante

**Ce que dit la littérature, croisée avec nos mesures.** Jia, Moallemi, Wang & Zeng (AFT 2026, Hyperliquid,
mars 2025 → juin 2026, 729 540 wallets) : les **teneurs de marché gagnent +208 M$**, les **preneurs
algorithmiques sont à peu près à l'équilibre**, les traders d'interface perdent 1,11 Md$ par trois canaux :
immédiateté, sorties forcées, frais. Un copieur qui exécute en taker EST un preneur algorithmique : son
espérance avant frais est ~0, et les frais le rendent négatif. C'est exactement Q3 (juillet) : le prix bouge
AVANT le fill du leader (−7,75 bps sur 5 min, contre lui) puis reste plat (+0,6 bps à 5 min) face à 12 bps.

| mécanisme (qui paie ?) | nos essais | cause du rejet | reste à tester |
|---|---|---|---|
| information du leader (le non-informé paie) | L1, L8, L9, H15/H15b, κ | **absence de signal** après réception, non persistant | rien d'historique : segments consommés |
| pression temporaire, contre-pied (l'impatient paie) | L2, robustesse ×5, H14 | signal ≤ coût | — |
| portage, funding (le levier paie) | L11 | coût / pas de signal | — |
| sortie / gestion de position | L12–L12c | excès réel (+14,5) **< coût** (~9,5 bps) | exécution maker = réfutée (labo) |
| **fourniture de liquidité (le preneur paie)** | V5 dépôt HLP | **seul PROMISING** (+230 bps/28 j) | preuve prospective dès le 17/12 |
| sorties forcées / liquidations | — | **inmesurable** : pas de marqueur dans les trades publics, nos leaders ne sont jamais liquidés (0 fill `Liquidated` sur 111 000) ; une stratégie autonome sortirait du périmètre CopyVault | collecte dédiée seulement si une source causale publique existe |
| TWAP résiduel | — | 0,19 % des fills | — |
| données L4 / rejets | — | hors période, non observables en temps réel | — |

**Conclusion honnête.** L'argent de ce marché va à la fourniture de liquidité. Dans le périmètre CopyVault,
la seule façon de s'y placer est le dépôt dans HLP (déjà PROMISING). Copier un leader en taker, c'est se
mettre du côté qui paie. Il reste un levier pour la copie : **refuser les copies perdantes** (§5 du prompt),
qui ne peut se juger que sur des données neuves.

### H16 — refus prospectifs des copies perdantes (pré-enregistrée le 22/11 vers 21:55 heure de Paris, AVANT toute donnée jugée ; gel à 23:30 heure de Paris)

- **Données** : fills du journal reçus APRÈS le gel `2026-11-22T22:30:00Z` (aucun n'a été vu par une règle).
- **Règle de base** (milieu de la grille, choisie d'avance) : déclenchement à 0,2 % de la TVL, stop 40 bps,
  horizon 1 h, coût 12 bps, 20 USD par trade (`cycles_fantomes.simuler`).
- **Filtres figés** (chacun = un refus, mécanisme dit d'avance) :
  F1 `absorption ≥ +5 bps` : le prix a déjà bougé dans le sens du leader avant notre entrée, l'info est payée ;
  F2 `latence > 60 s` : signal trop vieux ; F3 `notionnel du leader < 5 000 USD` : petit fill, bruit ou
  rééquilibrage ; F4 = union.
- **Mesure** : PnL total de base contre filtré, pertes évitées, profits abandonnés, couverture ; gain du filtre
  par jour = −(somme des cycles refusés), bootstrap par jours, **IC à 98,75 %** (Bonferroni sur 4 filtres).
- **Critère** : `PROMISING` si ≥ 5 jours, ≥ 50 cycles refusés, couverture ≥ 30 %, borne basse du gain > 0
  ET borne basse du PnL filtré > 0 ; `REJECTED` si ≥ 5 jours et l'une des bornes ≤ 0 ; sinon `MORE_DATA`.
  Un filtre qui garde moins de 30 % des cycles ne peut pas réussir, même s'il « gagne ».
- **Ne touche pas** à l'apprenant ni à sa campagne : outil de lecture séparé, `tools/goal2_refus_prospectif.py`.

