# TASKLIST — HyperSmart Observer

> Mis a jour le **2026-07-13**. **Aucune tache supprimee** : les 543 sont toujours la, plus bas.
> Ce fichier est une COPIE lisible qui survit aux sessions.

---

# 🧭 OU ON EN EST — LA PAGE A LIRE SI TU ES PERDU

*(Si tu ne lis qu'une chose, lis celle-ci. Le reste du fichier est l'archive detaillee.)*

## 1. Le bot, en une phrase

Il **observe Hyperliquid en lecture seule**, decide en local, et **simule des trades sur papier**.
Il n'a jamais envoye, et ne peut pas envoyer, un ordre reel.

## 2. La chose la plus importante a comprendre

**Le copy-trading n'a AUCUN edge. C'est mesure, pas suppose.**

> 24 133 signaux, hors echantillon : **le prix ne bouge pas apres l'ordre d'une baleine.**
> Meme a **cout ZERO**, le resultat est **−7,97 bps**. Et la cause est connue depuis Q1→Q3 :
> **le leader est CONTRARIEN, pas informe** — le prix court **CONTRE** son trade de −7,75 bps
> **AVANT** son fill, puis plus rien.
>
> Ce n'est **pas** un probleme de vitesse, de reglage, de latence ou de seuil.
> **Il n'y a rien a copier.** Aucun reglage ne peut reparer ca.

👉 **Consequence directe : le projet a change de but.** On ne cherche plus a « faire marcher le
copy-trading ». On fait deux choses :

- **(A) Construire un systeme qui ne se ment pas** — c'est 90 % du travail des 3 derniers jours,
  et c'est la ou il a de la valeur reelle.
- **(B) Chercher un edge AILLEURS**, dans un mecanisme structurellement different.

## 3. Ou en est la recherche d'un edge (piste B)

| piste | verdict | statut |
|---|---|---|
| **Copy-trading** | ❌ **MORT** — prouve sans edge, meme a cout zero | ferme |
| **Market making retail** | ❌ **MORT** — on ne franchit pas la file d'attente (0,33 % des trades balayent les 2 577 $ poses devant nous) | ferme |
| **Funding nu (jambe non couverte)** | ❌ **MORT** — 281 bps de risque de prix pour 1 bps de funding encaisse | ferme |
| **Carry delta-neutre sur HYPE** | ✅ **SURVIT a la falsification** — mais T2b (#588, FAIT 13/07) a chiffre le risque de liquidation : marge 105,4 % du notionnel → **~2,0 % APR sur capital total** (et non 4 %) ; verrou `RISQUE_LIQUIDATION_NON_MESURE_NO_TRADE` cable | 🟢 **piste vivante, mesuree de bout en bout** — decision d'exploitation a prendre |
| **Liquidations mecaniques** | ❓ prometteur (flux FORCE, non informe) | 🔒 **bloque** : on ne collecte pas la donnee (**X-11**) |
| **Lead-lag oracle / CEX→HL** | ❓ mecanique, pas statistique | 🔒 non commence (**H-151**) |

## 4. Ou en est le systeme (piste A) — ce qui a ete construit

Le fil rouge de tout le travail recent, c'est **une seule maladie** :

> ### « Une capacite presente, un chainon manquant, et personne qui se plaint. »

Elle a pris **10 deguisements** (edge fabrique ×5, carnet L2 jamais collecte, interrupteurs eteints,
garde-fous enterres, gate de regime inatteignable, latence mesuree seulement sur les survivants,
arbitrage a +140 bps entierement invente, correctif Ctrl-C applique a un seul fichier…).

**Le remede n'est jamais un inventaire — c'est un INVARIANT** (un test qui rougit tout seul,
a chaque execution). C'est ce qu'on a pose, un par un.

## 5. 🔴 L'ETAT DES TESTS, HONNETEMENT

Couverture reelle de **lignes** : **83,83 %** (et non 99,4 % — ce chiffre ne mesurait que
« importe par un test »).

Il restait **3 ROUGES** en debut de 3e passe. **2 sont tombes** :

- ✅ **#586 (H-181)** — RESOLU **et REFUTE**. Voir §7.
- ✅ **#598** — RESOLU : les 2 tests UI **exigeaient un edge INVENTE**. Voir §7.
- ✅ **#597** — fermee en 4e passe : 5e porte reconnue (`tools\*.py` lances par un `.cmd`),
  **plafond BAISSE 304 → 273** — jamais releve. *(Reconcilie 2026-07-14.)*

## 6. 🎯 QUOI FAIRE ENSUITE — dans l'ordre

> ⚠️ **Reconcilie le 2026-07-14** : les 3 taches historiques de ce paragraphe (#597, #588, #599)
> sont **FAITES** (4e, 8e et 6e passes). Le vrai reste-a-faire, sur pieces, est dans
> `docs/audit/TASKLIST_RECONCILIATION_20260714.md`. En tete :
1. **#372 (X-11) + #412 (H-07) — LIQUIDATIONS** : trancher X-13 (possible sur HL ?) puis
   brancher la collecte read-only. La meilleure piste PnL (flux FORCE, non informe).
2. **Carry HYPE (T2b ✅ ~2,0 % APR)** : decision d'EXPLOITATION a prendre (paper ON ou reserve).
3. **#286 (P1) — identifiant de session commun** aux 3 processus (la plus importante des
   taches de verite) ; puis #292b, #325/#304, #302, #303, #320, #314.

---

## 7. 🔬 3e PASSE (2026-07-13) — deux verdicts qui FERMENT des portes

### ✅ #586 / H-181 — **REFUTEE COMME EXPLICATION** (et mon outil mentait)

L'hypothese etait : *« on selectionne les 40 configs les plus CHANCEUSES, voila pourquoi 0 ne
survit hors echantillon. »* La malediction du vainqueur **est reelle** (prouvee sur bruit pur,
9 tests). **Mais ce n'est PAS elle qui cause le « 0 config robuste ».** Mesure sur les vraies
donnees (6 000 candidats, 400 scenarios, 207 611 trades evalues) :

| | |
|---|---:|
| PnL **moyen par trade** | **−3,00 $** |
| **MEILLEUR** net de TRAIN, sur 400 configs | **−106,46 $** |
| positifs hors echantillon — selection par MAXIMUM | **0 / 40** |
| positifs hors echantillon — selection par PLATEAU | **0 / 40** |

> **Le meilleur scenario PERD, et il perd EN ECHANTILLON** — la ou il a pourtant tous les droits
> de sur-ajuster. **Il n'y a aucun vainqueur a maudire.** Reparer la procedure de selection ne
> fabriquera pas un gagnant qui n'existe pas.
>
> 👉 **PORTE FERMEE, et c'est utile** : ca nous evite de refondre `scenario_search` pour rien.

🚩 **Et mon propre outil MENTAIT.** Il imprimait « INDISCERNABLE DU HASARD » alors que le reel
(−106 $) etait **118 $ AU-DESSUS** du p95 du hasard (−225 $). Cause : `seuil = p95 * marge if
p95 > 0 else 0.0` — quand tout est negatif, le seuil s'effondre a **0**, et le verdict devient
*mecaniquement* « bruit ». Corrige (comparaison signe-sure + marge ADDITIVE) + **5 tests** qui
verrouillent le cas negatif. *Un outil de mesure qui se trompe est PIRE qu'une absence de mesure.*

### ✅ #598 — les 2 tests UI **exigeaient un edge INVENTE**

Motif de refus, **lu et non devine** : `EXPECTED_NET_EDGE_TOO_SMALL_AFTER_COSTS`.

Cause : le **4e edge fabrique** (`18.0 + confidence*34 + min(24, (consensus−1)*8)`) vivait dans
`routes.py`, **sur le chemin d'entree du simulateur**. G2 l'a tue : l'edge vient desormais de la
**table MESUREE**, **sans aucun repli**. Pas de mesure => 0 bps => **refus**.

> Ces tests ne passaient donc **que si le bot inventait un chiffre**. Le garde-fou avait raison.
> On ne l'a **pas** affaibli : on donne aux tests une **vraie mesure**, et on ajoute l'invariant
> **`test_SANS_mesure_le_bot_REFUSE_au_lieu_d_inventer_un_edge`** — sans lequel quelqu'un pourrait
> « reparer » le test en remettant une formule, et **ressusciter un 5e edge fabrique**.

44 tests UI verts · Q1/G2 sans regression · safety 8/8.

🚩 Ma 1re hypothese (garde-fou breakeven) etait **FAUSSE** — je l'ai corrigee a la racine (defaut du
code = 74 % de winrate d'equilibre = perte garantie ; corrige en 42 %), **et les tests sont restes
rouges**. Le correctif reste juste ; il ne diagnostiquait simplement pas ce bug-la.

---

## 📊 LES CHIFFRES

> ⚠️ **Reconcilie le 2026-07-14** (`docs/audit/TASKLIST_RECONCILIATION_20260714.md`) :
> les « en attente » ne sont PAS 284 choses a faire — la majorite ont deja leur verdict
> dans un bloc de reconciliation (domines T1b, fermes par mesure, moisson epuisee,
> doublons, notes de lecture). **Le reste-a-faire reel : ~16 taches d'ingenierie de
> verite + 4 pistes PnL** (voir §6).

| | nombre |
|---|---:|
| **TOTAL** | **544** |
| terminees | **260** |
| **en attente** | **284** |
| en cours | 0 |

> Mise a jour 7e passe (13/07) : **H-160 (#565) et GH-02 (#355) terminees** — biais recursif
> **REFUTE et CHIFFRE** (ecart 26 M x sous le seuil de decision). Piste **fermee**.
> 6e passe : **#591 et #599 terminees**.
> 5e passe : **#600 terminee** (cause racine du Ctrl-C fantome).
> 4e passe : **#586, #594, #595, #596, #597, #598, #310 terminees**.

> ⚠️ **Ne te laisse pas impressionner par les 288 « en attente ».** L'immense majorite (≈ 200) sont
> des **notes de lecture GitHub** (M-*, H-*) : des idees a evaluer, **pas** du travail engage.
> Le vrai travail actif tient dans les **3 taches du § 6** ci-dessus.

---

## ✅ ETAT VERT (2026-07-13, 5e passe) — **3 520** verts / 0 rouge

Suite **COMPLETE** : **3 520 verts / 0 rouge** (244 s). safety **8/8**, doctor **10/10**.

> 🚩 **Le chiffre a lire deux fois : 3 520, contre 2 242 ce matin.** Ce ne sont pas 1 278 tests
> ajoutes. Ce sont **1 278 tests qui n'avaient JAMAIS tourne** : le Ctrl-C fantome coupait la suite
> a ~70 % et pytest affichait tranquillement « 2 242 passed », que je lisais comme un run complet.
> *Une suite interrompue ne dit pas « je suis incomplete » — elle dit « tout va bien ».*

---

## ✅ ETAT VERT (2026-07-13, 4e passe) — les 3 rouges sont fermes

Suite **COMPLETE** (a l'epoque) : **2 242 verts / 0 rouge** — chiffre **PERIME**, voir ci-dessus :
la suite etait tronquee. Les 3 rouges de la 3e passe sont resolus — et chacun cachait quelque chose
de plus gros :

1. ✅ **#597 (cliquet 304 > 303)** — je n'ai **PAS** releve le plafond. J'ai regarde **qui** etait le
   304e… et c'etait `backtesting.scenario_search` : **le moteur des 150 M de scenarios, lance des
   dizaines de fois.** L'audit **mentait**. Il ne connaissait qu'une forme de porte
   (`python -m hl_observer.X`) ; la recherche se lance par `python tools\xxx.py`. → 5e porte reconnue,
   **plafond BAISSE 304 → 273**. Anti-affaiblissement : un garde-fou de `risk/` joignable seulement
   depuis un script d'audit **compte toujours comme MORT**, et un `tools/*.py` qu'aucun `.cmd` ne lance
   **n'est pas une porte**.
2. ✅ **#598 (les 2 tests UI)** — ils ne passaient **QUE si le bot INVENTAIT un edge**. G2 avait tue le
   4e edge fabrique (`routes.py:1301`) ; sans mesure, l'edge vaut 0 → **le gate refuse, et il a raison.**
   On ne l'a pas affaibli : on donne aux tests une **vraie mesure**, + l'invariant
   `test_SANS_mesure_le_bot_REFUSE_au_lieu_d_inventer_un_edge`.
3. ✅ **#594 / #310** — voir ci-dessous : **il y avait DEUX tables d'edge**, et la plus pauvre ecrasait Q1.

---

## FAIT DANS LA 7e PASSE (2026-07-13) — H-160 / GH-02 : le biais recursif, MESURE (et refute)

- [x] **H-160 / GH-02** — ❓ *« Nos features changent-elles selon la QUANTITE d'historique fournie ? »*
  La question compte : en **backtest** on donne toute l'histoire, en **live** le bot ne garde qu'un
  **buffer borne**. Si la valeur au meme instant differe, le backtest ne dit rien du live -- c'est la
  reponse la plus banale a « pourquoi mon backtest ne ressemble pas a mon live » (**H-177**).

  Le **comparateur existait** (`backtesting/recursive_analysis.py`) et etait a **0,00 %** de
  couverture (#599) : *personne ne le nourrissait.* Livre le chainon manquant --
  `backtesting/recursive_bias_probe.py` : il fabrique les deux series (backtest = tout ; live =
  200 points) **aux memes instants** et les lui donne. 6 tests + `tools/mesurer_biais_recursif.py`.

  **MESURE SUR LES MIDS REELS** (`runtime/replay/l2_book.*.jsonl`, BTC/ETH/SOL/HYPE) :

  | feature | nature | ecart max backtest vs live |
  |---|---|---:|
  | `vol_sigma.sigma_blend` | bornee (`r[-n:]`) | **0** (exactement) |
  | `volatility.blend_bps` | bornee | **0** (exactement) |
  | `direction.strength_bps` | **recursive** (EMA amorcee sur `values[0]`) | **1,9e-7 bps** |
  | `rsi_overheat.rsi_14` | **recursive** (lissage de Wilder) | **1e-4 point** |

  > 🎯 **VERDICT : NON.** Les deux features recursives le sont **par construction** -- mais l'ecart
  > qu'elles produisent est **26 millions de fois plus petit** que le seuil qui decide
  > (`flat_threshold_bps = 5 bps`). Le seed de l'EMA s'oublie **geometriquement** : apres 200 points
  > de buffer, il n'en reste **rien de mesurable**.
  >
  > **Backtest et live decident LA MEME CHOSE.** Le biais recursif n'explique **pas** nos ecarts.
  > *Un resultat negatif, quantifie, est un resultat : il FERME une piste au lieu de la laisser
  > trainer comme un soupcon.* Et on ne « corrige » pas ce qui ne casse rien.

  🚩 **Bug d'affichage attrape sur moi-meme** : mon rapport imprimait « RECURSIF » a cote d'un ecart
  affiche `0.000000` (arrondi a 6 decimales d'un 1e-7). Un rapport qui a l'air de se **contredire**
  sera relu comme faux. Notation scientifique imposee. *Une mesure juste, mal affichee, redevient
  une mesure fausse.*

- [x] **H-30 (volet lookahead)** — `backtesting/lookahead_analysis.py` est a **0 %** lui aussi, mais
  pour une raison **differente** : c'est une **facade redondante**. La vraie fonction
  (`backtest/no_lookahead_guard.find_lookahead_violations`) est **deja branchee** -- par **G1** dans
  `scenario_search`, et dans `backtest/runner_contract`. Elle n'est pas morte faute de capacite :
  elle **double** une capacite vivante.
  → **Ne pas lui inventer un utilisateur.** Doctrine T3b : *brancher ou enterrer*. Ici : **enterrer**
  (tache ouverte, registre `backtesting/` a creer -- ne pas bricoler dans `risk/tombstones`).

---

## FAIT DANS LA 6e PASSE (2026-07-13) — le garde-fou AFFAME, et ce que valent vraiment les 16 %

- [x] **#591** — 🔴 **LE GARDE-FOU AFFAME.** La chaine, et son fil coupe :

  | role | fichier | ce qu'il fait |
  |---|---|---|
  | NOURRISSEUR | `paper_trading/vol_adjusted_barriers.py:191` | `MidVolEstimator.record(coin, mid)` |
  | CONSOMMATEUR | `signals/v26_entry_vetos.py:228` | `range_bps(window_s=900, min_obs=5)` |
  | **VETO** | `MarketQualityBook.allowed(coin)` | `REASON_MQ` -> **refus d'ENTREE** |

  Les 3 lignes d'enregistrement etaient **sous un `return` anticipe** (`if config is None or not
  positions`). L'estimateur n'etait donc nourri **QUE lorsqu'une position etait DEJA ouverte** --
  alors que son consommateur pose sa question **au moment de decider une ENTREE**, c'est-a-dire,
  justement, **a 0 position**. Il recevait `None`.

  🚩 **Et `None` ne casse rien.** `quality_score()` **saute** simplement le terme de volatilite --
  qui pese **±30/35/+15 points, le plus lourd des trois**. Le veto continuait donc de trancher, en
  classant l'univers top-K sur la **liquidite seule**, sans le moindre signe exterieur. Mesure :
  entre un marche **MORT** et un marche **INCONNU**, **30 points d'ecart** -- que le veto affame ne
  pouvait pas voir.

  > ⚠️ **Ce n'etait pas un module dormant** : le lanceur pose `HYPERSMART_V26_MARKET_QUALITY=1`
  > (`start_hypersmart_simulation.ps1:182`). **Le veto etait ACTIF en production.**

  Correctif : on enregistre les marks **avant** le retour anticipe, et **independamment du flag**.
  Meme principe que le carnet L2 (#330) : ***le deny-by-default protege les ORDRES, pas les OCTETS.***
  Enregistrer un mark n'est pas passer un ordre. **On observe TOUJOURS ; on decide ensuite.**
  5 tests, dont l'invariant « les marks sont enregistres **meme sans aucune position** ».

- [x] **#599** — ⚠️ **CE QUE VALENT VRAIMENT LES 16 % DE LIGNES NON EXECUTEES.**
  Sur la suite **complete** (3 526 tests, 48 470 instructions) : **7 836 lignes** jamais executees,
  reparties en **trois mondes qui ne se valent pas** :

  | lignes | quoi | gravite |
  |---:|---|---|
  | **1 626** | **97 modules a 0,00 %** — jamais executes, pas meme a l'import | orphelins |
  | **848** | 117 modules du **CHEMIN DE DECISION** — des **branches** non prises | ⚠️ **le vrai risque** |
  | 5 362 | 396 modules de surface (`cli.py` 800, `ui/routes.py` 622…) | faible |

  **Verdict honnete : non, les 16 % ne sont PAS majoritairement du code critique non teste.**
  Le noyau de decision est couvert a **80-92 %** ; ce qui lui manque, ce sont **848 lignes de
  branches** -- des refus dont on ne sait pas s'ils fonctionnent. C'est borne, c'est nommable, et
  c'est desormais **sous cliquet**.

  🚩 **MON HYPOTHESE DE DEPART ETAIT FAUSSE.** J'avais affirme que la mesure de 14:07 (83,83 %)
  etait fausse, calculee sur une suite tronquee par le Ctrl-C. **Refute par la mesure elle-meme** :
  relancee sur la suite complete, elle rend **exactement 83,83 %**. Le Ctrl-C tuait le `.cmd`
  **APRES** pytest, pas pytest. Les modules a 0 % que j'accusais d'etre des victimes sont
  **reellement morts**. *Suspecter son instrument est sain -- le condamner sans preuve ne l'est pas.*

  Livre : `tools/analyser_couverture_599.py`, `couverture_de_lignes.py` **durci** (il **refuse** de
  publier une mesure issue d'un run **interrompu**), et le **3e cliquet** :
  `test_cliquet_modules_jamais_executes.py` -- le nombre de modules a 0 % ne peut que **descendre**
  (plafond **97**), et **aucun module du noyau de decision** ne peut y figurer sans etre
  explicitement **enterre**.

  📌 A suivre : `backtesting/recursive_analysis.py` et `backtesting/lookahead_analysis.py` sont a
  **0 %** -- ce sont exactement les outils de **H-30 / H-160** (freqtrade). Codes, jamais lances.

**Suite complete : 3 533 verts / 0 rouge · safety 8/8.**

---

## FAIT DANS LA 5e PASSE (2026-07-13) — le Ctrl-C que personne n'a tape, enfin explique

- [x] **#600** — 🔴🔴🔴 **`os.kill(pid, 0)` EST un Ctrl-C sous Windows.**
  `backtesting/runtime_guards.py` : `os.kill(pid, 0)   # signal 0 = simple test d'existence`.
  **Vrai sur Unix. Faux ici.** Sous Windows, `signal.CTRL_C_EVENT` **VAUT 0**, et `os.kill()` de
  CPython dispatche alors vers `GenerateConsoleCtrlEvent(0, pid)` : **un vrai Ctrl-C, envoye au
  GROUPE de la console.** `tests/test_runtime_guards.py:16` appelle `parent_alive(os.getpid())` —
  **la suite se Ctrl-C elle-meme, au milieu de son propre run.**

  > **L'ironie est totale** : cette fonction est le **watchdog ANTI-ORPHELIN** (IMPROVE-01). Sa
  > raison d'etre est de PROTEGER la session. Sous Windows, elle la **TUAIT**. Si elle avait ete
  > branchee dans le poller, **chaque battement du watchdog aurait ferme la simulation qu'il garde.**

- [x] 🚩 **MES TROIS CORRECTIFS PRECEDENTS N'ETAIENT PAS LE DIAGNOSTIC.** J'ai accuse — et corrige —
  trois sous-processus qui relancaient pytest sans isoler leur groupe (`audit_report`,
  `couverture_de_lignes`, `test_env_hermetique`). Les correctifs restent **justes** (l'isolation de
  groupe est la bonne pratique) mais **aucun des trois n'etait le coupable.**
  ***Corriger n'est pas diagnostiquer.*** (2e fois cette semaine, apres le defaut SL/TP.)

- [x] **LE CORRECTIF** — `_existe_sous_windows()` : Win32 `OpenProcess` + `GetExitCodeProcess`. On
  **INTERROGE** le systeme, on ne lui **ENVOIE** rien. Le repli POSIX vit desormais dans
  `_existe_sous_posix()`, **derriere un `raise` si `os.name == "nt"`** : l'appel est **physiquement
  inexecutable** sous Windows.

- [x] **L'INVARIANT** — `tests/test_aucun_ctrl_c_deguise_en_test_d_existence.py` (**AST**, pas regex :
  *une regex lirait aussi le docstring, qui CITE le bug*). Aucun module de production ne peut appeler
  `os.kill(x, 0)`, **sauf** sous une garde qui **LEVE**. Teste sur **arbre fabrique** : il attrape la
  vraie ligne, ne prend **ni** `os.kill(pid, SIGTERM)` **ni** `proc.kill()`, et **un `return` ne vaut
  PAS une garde**.
  🚩 **L'invariant a commence par attraper MON PROPRE repli POSIX.** Je n'ai pas affaibli le
  detecteur : j'ai **restructure le code**. ***Durcir n'est pas contourner.***

- [x] 🔴 **CE QUE LA SUITE COMPLETE, ENFIN COMPLETE, A CRIE** — 5 rouges dans les 1 278 tests qui
  n'avaient jamais tourne :
  - `test_strict_md_accept_path` (x2) — ils pilotaient l'edge via `HYPERSMART_EDGE_CALIBRATION_PATH`,
    c'est-a-dire la **2e table**, celle que **#594 vient de debrancher**. Le test tirait sur un
    **levier mort** — et « passait » en ne prouvant **rien**. Le comble : leur propre docstring, ecrit
    le 12/07, denonce exactement ce piege. Reecrits sur la **porte Q1**.
  - `test_v9_scorer_bias_wiring` (x2) — ils **EXIGEAIENT** qu'un biais **INVENTE** (±10 bps, issu d'un
    modele de tendance) **deplace un edge MESURE**. C'est-a-dire un **4e edge fabrique**, exige par un
    test. Reecrits : sur un edge mesure, le biais **n'a AUCUN pouvoir** ; il ne survit que dans le mode
    A/B `HYPERSMART_EDGE_SOURCE=formule`, estampille `fabrique=True`.
  - l'invariant #600 lui-meme, sur mon repli POSIX (ci-dessus).

  **Preuve (Windows, `check_601.txt`)** : `3520 passed, 0 failed` · safety **8/8** · doctor **10/10** ·
  le `.cmd` atteint **FIN** — alors qu'avant, le Ctrl-C le tuait **juste apres pytest**. C'est
  precisement pour ca que **`safety-audit` ne s'executait plus depuis deux jours.**

---

## FAIT DANS LA 4e PASSE (2026-07-13) — la plus grosse trouvaille du jour

- [x] **#594 / #310** — 🔴🔴 **DEUX TABLES D'EDGE, ET LA PLUS PAUVRE GAGNAIT.**
  `ui/routes.py` (chemin LIVE) mesurait l'edge par la **porte Q1** (`edge.edge_source` : table
  conditionnee sur coin x direction x age x score x consensus, **borne basse**, verrou
  **anti-lookahead**) et le passait au scoreur… qui le **JETAIT** pour relire `edge.empirical_edge` —
  une **autre** table, indexee sur le **seul age**, sans coin, sans anti-lookahead.
  **Tout le travail de Q1 mourait la, en silence.** (= P2-3 / #310, enfin prouve par execution.)
- [x] 🔴 **LE BUG DE SIGNE** — la valeur etait ensuite **re-multipliee** par `freshness` x
  `consensus_factor`, les features memes sur lesquelles la table conditionne **deja**
  (double-comptage). Mais le pire : la mesure reelle est **NEGATIVE**. Multiplier un negatif par une
  fraicheur qui **decroit** le rend **MOINS negatif** :

  | age du signal | edge mesure | x fraicheur | edge retenu |
  |---|---:|---:|---:|
  | 6 s (**FRAIS**) | −2,17 | x0,92 | **−1,99** |
  | 25 s (**VIEUX**) | −0,56 | x0,31 | **−0,17** ← *parait MEILLEUR* |

  **Le multiplicateur cense PENALISER l'age le RECOMPENSAIT.** Il n'inverse pas une intention : il
  inverse un **signe**. → Sur un edge **mesure**, on ne fait plus qu'**une** chose : soustraire les
  couts. L'ancienne ponderation ne survit que dans le mode A/B `HYPERSMART_EDGE_SOURCE=formule`,
  **estampille `fabrique=True`**. **8 nouveaux tests**, dont celui du signe.
- [x] 🚩 **LA SUITE COMPLETE A ENCORE ATTRAPE CE QUE MES SOUS-SUITES CACHAIENT** —
  `tests/test_env_hermetique.py` lancait **pytest sans isolation de groupe** → Ctrl-C fantome.
  C'etait dans **l'angle mort de mon propre invariant**, ecrit le matin meme (il ne scannait que
  `tools/`). Il scanne desormais `tools/` **et** `tests/`.
  ⚠️ **Le Ctrl-C persiste quand meme** apres correctif (threading.py:1005, a la toute fin, apres
  2 242 tests verts). **Je ne declare pas victoire** → tache **#600**.

---

## FAIT DANS LA 2e PASSE (2026-07-13)

- [x] **#595** — 🔴 **BRANCHER le regime dans `scenario_search`.** Le gate `regime_robustness`
  reclamait un champ `regime` que **personne n'ecrivait** : sa branche etait **structurellement
  inatteignable**. `_eval_pairs` calculait deja `entry_ts` et le **jetait**. Livre :
  `backtesting/regime_wiring.py` (serie causale, seuil **du TRAIN seul**, `bisect_right` = la ligne ou
  un lookahead se glisse) + `eval_trades_triplets` + cablage dans `search()` **et** `search_over_db()`.
  **7 tests** (dont le test **differentiel** H-157 : on change le futur, le passe ne doit pas bouger) +
  **38 tests de non-regression du moteur de recherche**, verts. Safety 8/8.
  🚩 *Mes 2 premiers tests etaient FAUX, pas le code : une **mediane** du train coupe le train **en
  deux** par construction — un instant calme a donc une chance sur deux d'etre au-dessus.*
- [x] **#596** — 🔴 **LA VRAIE COUVERTURE, mesuree.** Les deux chiffres, cote a cote :
  | mesure | valeur | ce que ca dit |
  |---|---:|---|
  | #121 — modules **importes** par un test | **99,4 %** (481/484) | borne **OPTIMISTE** |
  | #596 — **LIGNES executees** | **83,83 %** | la seule qui compte |
  Cliquet pose (`tools/couverture_lignes_baseline.json`), il ne tourne que vers le haut.
- [x] **BUG TROUVE EN LANCANT L'OUTIL** — 🔴 **un Ctrl-C que PERSONNE n'a tape** tuait la mesure, deux
  fois de suite. Cause : sous Windows, un Ctrl-C frappe **la CONSOLE**, donc le processus parent.
  **Le correctif existait depuis le 11/07 dans `audit_report.py`... et nulle part ailleurs.**
  *Encore une jambe reparee, l'autre laissee* (comme funding/L2). → `tools/sous_processus_isole.py`
  (point de passage unique) + **invariant AST** (`test_outils_isoles_du_ctrl_c.py`, 4 tests) qui rougit
  si un outil relance pytest sans isoler son groupe. `megatest` et `audit_report` isoles aussi.
- [x] **DEFAUT SL/TP = PERTE GARANTIE** — le defaut du **code** etait `TP=30 / SL=40` →
  breakeven **74 %** de winrate. Injouable. Seul le **lanceur** (110/60 → 42 %) sauvait la production.
  Corrige a la source + 3 tests (`test_defaut_sltp_pas_perdant.py`), dont un qui **prouve que le
  garde-fou mord** sur l'ancien defaut. ⚠️ **Cela n'a PAS repare les 2 tests UI** — voir #598.

---

## FAIT AUJOURD'HUI (2026-07-13) — 6 taches, 6 bugs de fond

Toutes de la meme famille : **une capacite presente, un chainon manquant, et personne qui se plaint.**

- [x] **#145** — IMPROVE-38 — 🔴 **UN ARBITRAGE A +140 bps ETAIT AFFICHE... ET IL ETAIT INVENTE.**
  `refactor_fusion/runner.py:88` nourrit le scanner cross-exchange avec `_fixture_arbitrage()` :
  carnet HL a **100,00**, carnet « CEX » a **101,40** -- **ecrits en dur** -- publies dans le panneau
  avec `accepted: 1`. Le mot « fixture » dormait dans un champ `source` enfoui a trois niveaux :
  autant dire nulle part.
  **Cause profonde : AUCUN collecteur de prix CEX n'existe dans ce projet.** Ce scanner n'a jamais
  rien pu mesurer de reel. Violation directe de *« aucune donnee fabriquee, aucune demo presentee
  comme reelle »*. → Le panneau **DECLARE** ses donnees fabriquees, et expose `accepted_reels`
  (= **0**). 4 tests, dont un qui NOMME le coupable et rougira le jour ou un vrai collecteur existera.
- [x] **#131** — IMPROVE-24 — la **MACHINE** n'a pas les **MOYENS** d'executer un ordre.
  `security/dependances.py` (dex-exec 🚨, ccxt, web3, eth-account…) + **8e controle safety** =
  un cliquet : un futur `pip install ccxt` fait rougir la CI. 9 tests.
- [x] **#130** — IMPROVE-23 — l'invariant **« une tombe ne peut citer qu'un remplacant VIVANT »**.
  Il a rougi 5 fois et avait raison 5 fois : un remplacant a **3 formes** (module / flag / fonction),
  et **4 pierres tombales ne citaient que de la PROSE** (inverifiable). Reecrites. 6 tests.
- [x] **#127** — IMPROVE-20 — 🔴 le gate `regime_robustness` **se degradait EN SILENCE** (il cherchait
  un champ `regime` que personne n'ecrivait) **et GARCH lisait le futur** (amorcage sur toute la serie
  + `out[i]` calcule apres avoir vu `r[i]`). Livre : `garch11_variance_causale` + `regime_label.py`
  (seuil sur le TRAIN seul) + le gate **DECLARE** desormais son mode. 8 tests, dont un test
  **differentiel** qui change le futur et verifie que le passe ne bouge pas.
- [x] **#112** — IMPROVE-05 — 🔴 **la latence n'etait mesuree que sur les trades qu'on PREND.**
  Les chemins de REFUS sortaient avant tout tampon : **biais de survivant dans l'instrumentation
  elle-meme**. Or c'est la qu'il faut mesurer -- « a-t-on refuse parce que c'etait mauvais, ou parce
  qu'on est arrive trop tard ? ». Livre : `runtime/latency_journal.py` (borne, separe ACCEPTE/REFUSE)
  + invariant AST qui exige que le refus laisse sa trace. 6 tests.
- [x] **#121** — IMPROVE-14 — le **CLIQUET de couverture** : 484 modules joignables, **3** sans test.
  Le test echoue si ce nombre MONTE, et la baseline **refuse d'etre relevee**.
  ⚠️ **A LIRE HONNETEMENT** : « couvert » = *importe par un test*, PAS *ses lignes sont executees*.
  **99,4 % ne veut pas dire « bien teste »** -- voir **#596**.
  🚩 Ma 1re version annoncait **0 module couvert sur 484** ; c'est mon propre test sur arbre
  FABRIQUE qui l'a attrapee. *Un outil de mesure qui se trompe est pire qu'une absence de mesure.*

---

## EN COURS (0)

*(vide — #586 est RÉSOLUE et RÉFUTÉE, voir §7 : le meilleur scénario perd EN TRAIN, il n'y a
aucun vainqueur à maudire. Réconcilié le 2026-07-14.)*

---

## EN ATTENTE — 293 taches

### IMPROVE-* (50 ameliorations) — 0 en developpement

La tranche **#112 → #145 est CLOSE.** Les 2 restantes ne sont **pas du code** : ce sont des
**donnees qu'on n'a pas**. Les laisser en « a faire » serait se mentir -- on n'ecrit pas du code
en attendant qu'une donnee tombe du ciel.

- ⏳ **#115** — IMPROVE-08 run de collecte long → **la capacite EXISTE, il manque le TEMPS.**
  Aucune ligne a ecrire ne rapprochera ce resultat. Appartient a l'exploitation, pas au dev.
  Prerequis avant de lancer : bornes disque verifiees (le bloat a DEJA fait crasher un run de 48 h)
  et **#595**, sans quoi les semaines collectees ne serviront pas le split multi-regimes promis.
- ⏳ **#143** — IMPROVE-36 cascades de liquidations → **bloque sur le flux de liquidations (X-11).**
  Et **X-13** dit que la piste est peut-etre une **zone morte** : trancher AVANT de coder, sinon on
  ecrit un module qu'on retrouvera enterre dans six mois.
- ⏳ **#145** — la piste **basis / CEX** reste bloquee (aucune donnee CEX). Le CORRECTIF de la
  donnee fabriquee, lui, est **fait** (voir plus haut). Bonne formulation de la piste = **H-151**
  (l'oracle SUIT les CEX = lead-lag **mecanique**, pas la basis nue).

### Suites immediates — l'etat REEL

- [x] ~~**#595**~~ — ✅ **FAITE** : le regime est branche dans `scenario_search` (causal, seuil du
  TRAIN seul). 7 tests + 38 de non-regression, verts.
- [x] ~~**#596**~~ — ✅ **FAITE** : la couverture de **LIGNES** est mesuree = **83,83 %**, publiee a
  cote du 99,4 % (qui, lui, ne mesurait que « importe par un test »).

**A leur place, 3 taches OUVERTES** — ce sont les 3 tests rouges :

- [x] **#597** — 🔴 **LE CLIQUET DE CABLAGE COMPTE LA RECHERCHE COMME MORTE.** 304 > 303, mais son
      ✅ **FAIT** — cliquet de cablage corrige
  verdict inclut **les 61 modules de `backtesting/`** -- dont `scenario_search` lui-meme, qui EST le
  moteur de recherche. Ils ne sont « morts » que parce que **le CLI et `tools/` ne sont pas des points
  d'entree declares**. Tant que ce n'est pas tranche, tout module de recherche ajoute fera monter le
  compteur et le cliquet criera au loup.
  → Trancher : le CLI est-il un point d'entree ? Si oui, l'ajouter et **reposer le plafond UNE fois**.
  Sinon, compter `backtesting/` **separement**. **Ne PAS relever le plafond en attendant.**
- [x] **#598** — 🔴 **2 TESTS UI : PLUS AUCUNE POSITION NE S'OUVRE** (`assert []` —
      ✅ **FAIT** — 2 tests UI : plus aucune position ne s'ouvre (assert [])
  `test_ui_simulation_v9_filters:328`, `test_ui_simulation_persistence:1061`). Les fixtures posent
  pourtant `HYPERSMART_REQUIRE_EMPIRICAL_EDGE=0` : **un gate refuse en amont**.
  🚩 **Ma 1re hypothese (garde-fou breakeven) etait FAUSSE** — je l'ai corrigee a la racine, et les
  tests sont **restes rouges**. La cause est ailleurs.
  → Methode : instrumenter le refus (`decision_context` DOIT laisser sa preuve, cf. P2-4) et LIRE le
  motif, sans supposer. **Ne PAS affaiblir un gate pour verdir un test.**
- [x] **#599** — ⚠️ La couverture de **lignes** est a **83,83 %**. Les ~16 % non executes sont-ils du
      ✅ **FAIT** — couverture reelle 83,83 % mesuree (et non 99,4 %)
  code mort, ou du code **critique non teste** ? (`coverage.json` est ecrit, il suffit de le lire.)

### 🚩 Statut FAUX corrige aujourd'hui

- **#288 (P3)** disait : *« l'instrumentation latence n'est PAS branchee »*. **C'est FAUX**, et
  prouve faux par execution : `LatencyTrace` etait bien creee et estampillee. Le vrai bug etait
  ailleurs -- le **biais de survivant** (#112). Cette tache accusait le mauvais coupable.
  ⚠️ **Deuxieme fois** qu'une tache « ROUVERTE » sur la latence se revele mal diagnostiquee (apres
  S2). *On ne rouvre pas sur une impression. On rouvre sur une execution.*

---

## LA MALADIE DU PROJET, EN UNE LIGNE

> **Une capacite presente, un chainon manquant, et personne qui se plaint.**

Elle a maintenant pris **neuf** deguisements : l'edge fabrique (×5), le carnet L2 jamais collecte,
les interrupteurs eteints, les garde-fous enterres au nom de remplacants morts, le gate de regime
inatteignable, la latence mesuree seulement sur les survivants, et -- aujourd'hui -- **un arbitrage
a +140 bps entierement invente, affiche comme un resultat.**

Le remede n'est jamais un inventaire. C'est un **invariant** :
*un inventaire se fait une fois et se trompe ; un invariant se verifie a chaque execution.*

### IDEA-* (100 idees quant) — 22

### 🔬 LOT IDEA TRANCHÉ (2026-07-13) — 4 morts enterrés, 1 statut FAUX corrigé, 6 zones mortes

> 🔴 **LA CLASSE QUE MES AUDITS T3 NE POUVAIENT PAS VOIR : le limbe au niveau de la FONCTION.**
> T3b/T3c/T3e raisonnaient **par module** (« ce fichier est-il importé ? »). Or
> `backtesting/regime_detection.py` est **VIVANT** (→ `regime_label` → `regime_wiring` →
> **`scenario_search`**) et contient **4 fonctions dont 1 seule est appelée**. *Un module vivant
> peut héberger des fonctions mortes — et l'une d'elles peut être DANGEREUSE.*

- [x] **#166** — ✅ IDEA-09 (SHAP) — **ENTERRÉ.** 0 import de production (AST). Motif :
      `EXPLIQUE_UNE_PERTE` — il explique un modèle qui **perd contre la baseline** (P13, sa
      promotion est bloquée pour ça). *Expliquer une perte ne la transforme pas en gain.*
      Réouverture : un modèle qui BAT la baseline OOS.
- [x] **#169** — ✅ IDEA-12 (Hawkes) — **ENTERRÉ.** 0 import de production. Motif :
      `PAS_DE_CONSOMMATEUR` — le seul chemin qui en voudrait (cascades de liquidations) est
      **bloqué faute de donnée** (IMPROVE-36 / X-11). Réouverture : le jour où les liquidations
      sont réellement collectées.
- [x] **#240** — ✅ IDEA-83 (Kalman) — **ENTERRÉ.** 0 appelant. Motif : `REDONDANT` — le régime est
      déjà établi, causalement et testé, par `garch11_variance_causale`.
- [x] **#241** — 🚩 **LA TASKLIST SE TROMPAIT. « GARCH est CODE mais MORT » est FAUX.**
      Le **GARCH causal EST branché** depuis #595 et tourne dans `scenario_search`. Ce qui est mort,
      c'est son **JUMEAU QUI LIT LE FUTUR** (`garch11_variance`) — **dans le même fichier, à huit
      caractères du bon nom.** C'est une **mine** : un jour l'autocomplétion choisira, et il y aura
      du **lookahead dans le moteur de recherche**, en silence.
      → **Verrouillé par un test** : la production ne PEUT PAS importer `garch11_variance`.
      → 🚩 **Et un 7ᵉ statut faux tombe au passage : IDEA-82 (`cusum_change_points`), marquée
      `completed`, n'a AUCUN appelant.** Enterrée aussi.
- [x] **#159 / #160** — ✅ IDEA-02/03 (LSTM, Transformers) — **ZONE MORTE**
      `ML_SEQUENTIEL_SUR_SIGNAL_SANS_INFORMATION` (mesure : **−7,97 bps OOS à coût ZÉRO**,
      n = 24 133). Ces modèles lisent **le fill public d'un leader** — exactement l'entrée mesurée.
      Le refus est une **déduction** : même entrée, autre fonction. *Un modèle n'invente pas
      d'information : il en extrait.* Le gradient boosting (IDEA-01) **perd déjà** contre la baseline.
      Réouverture : **un jeu de features dont l'edge OOS est POSITIF après coûts.**
- [x] **#188** — ✅ IDEA-31 (Redis/Kafka) — **DÉJÀ MORT, mais le registre ne l'attrapait pas.**
      Un bus de messages n'achète qu'**une** chose : de la **latence**. Or la latence est déjà
      mesurée morte (Z1 : courbe edge/horizon PLATE, −3,74 bps à 500 ms). Même entrée.
      🚩 **Et ça m'a coûté un test rouge** : ma 1ʳᵉ version ajoutait le mot **`bus`**, qui a
      immédiatement **volé** les propositions destinées à la zone `BUS_GITHUB_EXTERNE`.
      ***Un mot-clé trop générique n'élargit pas une protection : il en CANNIBALISE une autre.***
- [x] **#207** — ✅ IDEA-50 (graphe de wallets) — un graphe sert à **mieux CHOISIR** le wallet dont on
      copie le fill. Même entrée (`fill_public_leader`). *Mieux sélectionner la source d'un signal
      sans information ne crée pas d'information.* ⚠️ Nuance : sur un signal **pré-exécution**
      (dépôts on-chain), le clustering redevient légitime — mais c'est **#198**, pas #207.

#### 🔴 L'INCOHÉRENCE VUE PAR FLO — et les DEUX enterrements que j'ai dû EXHUMER
> *« Pourtant ce sont toutes des décisions que TOI tu avais choisi de garder. Ce n'est pas
> cohérent. »* — et il avait raison.
>
> Le même jour, sur treize idées, j'ai appliqué **deux standards opposés** : j'en ai **enterré six**
> sans aucune mesure *sur elles*, par extrapolation d'une mesure faite ailleurs ; et j'en ai **gardé
> sept** en invoquant « pas de mesure = préjugé ». Même situation épistémique, deux verdicts.
> **Et le biais avait un sens : enterrer RACCOURCIT la liste.** J'étais rigoureux là où ça ne me
> coûtait rien, et laxiste là où ça me faisait gagner.
>
> **Cause technique :** le registre refusait sur des **MOTS-CLÉS**. Or un mot-clé est une **MENTION**,
> pas un **MÉCANISME** — le piège grep-vs-AST que j'ai corrigé DEUX FOIS dans le code le même jour.
> Il était aussi dans mon raisonnement.
>
> **Règle désormais EXÉCUTABLE** (`ZoneMorte.entree_mesuree` + `registre.examiner(prop, entree=…)`) :
> *une zone morte ne peut refuser une idée que si cette idée consomme **LA MÊME ENTRÉE** que celle
> sur laquelle la mesure a été faite.* Sinon → **`A_EXAMINER`**, ni refus, ni feu vert : une question.
> Le deny-by-default tient : sans entrée déclarée, un mot-clé touché reste un **REFUS**.

- [x] **#161** — 🔴 **IDEA-04 (RL de SORTIE) — EXHUMÉE.** La mesure « −7,97 bps » porte sur le signal
      ✅ **FAIT** — EXHUMEE (critique de Flo) : le RL de SORTIE consomme une AUTRE entree -> A_EXAMINER
      d'**ENTRÉE** (le fill d'un leader). Une politique de **SORTIE** ne lit pas ce signal : elle lit
      l'**état de la position APRÈS l'entrée**. *Une mesure faite sur une autre entrée ne tue pas
      cette idée : elle n'en parle pas.* Je l'avais enterrée quand même, en empilant un 2ᵉ argument.
      *Mesure qui trancherait :* une politique de sortie apprise bat-elle le SL/TP fixe, OOS, après
      coûts ? ⚠️ L'entrée reste négative → une meilleure sortie **réduit une perte**, elle ne crée
      pas un gain.
- [x] **#204** — 🔴 **IDEA-47 (market makers) — EXHUMÉE.** L'idée a **DEUX lectures**, et je les ai
      ✅ **FAIT** — EXHUMEE (critique de Flo) : suivre les MM = une AUTRE entree que le fill du leader
      enterrées d'un coup parce que le mot-clé matchait :
      **(a)** *copier* les fills d'un MM → copy-trading, mort, même entrée. ✅
      **(b)** savoir **QUI est en face de NOTRE fill** → prédicteur de **sélection adverse** (markout).
      Entrée = `contrepartie_de_notre_fill`. **Jamais mesurée.** ❌ *Le mot-clé avait raison sur la
      lettre, et tort sur le mécanisme.*

#### 🔴 LE MOT-CLÉ MORT (trouvé par un test ROUGE, pas par moi)
> Mon test du RL attendait `A_EXAMINER`. Il a obtenu **`LIBRE`** : **aucune zone touchée.**
> Pourquoi ? `consulter()` extrait les mots par `[a-z_]{3,}` — **trois caractères minimum**.
> Le mot-clé **`"rl"`** en fait **deux**. **Il ne pouvait matcher JAMAIS.** Idem pour **`"mm"`**.
> *Deux garde-fous qui ne protégeaient rien* — la maladie du projet, une fois de plus : une capacité
> présente, un chaînon manquant, personne qui se plaint. Le fichier **mettait en garde contre les
> mots-clés morts, deux lignes au-dessus de l'un d'eux.**
> → Corrigés + **invariant** : aucun mot-clé ne peut faire < 3 caractères, ni contenir un espace.
> → 🚩 *J'avais raison sur la conclusion (le RL de sortie n'est pas refusé) et **tort sur le
> mécanisme** : il passait par un trou du filtre, pas par ma belle règle.*

#### ⚖️ LES 7 QUE JE REFUSE D'ENTERRER — parce que je n'ai AUCUNE mesure
> Le registre des zones mortes l'interdit lui-même : *« une zone morte exige une preuve. Sinon
> c'est un préjugé. »* Les enterrer à l'impression serait exactement la faute que je traque.
> Chacune est donc laissée OUVERTE, avec **la mesure qui la trancherait** :

- [x] **#189** — IDEA-32 Base time-series (Timescale/Influx) — *mesure qui tranche :* le stockage
      🛑 **REFUS** — infra (Redis/Kafka/Timescale) : ne cree AUCUN edge. Le mur n'est pas la.
      est-il un **goulot mesuré** ? (le crash de la DB à 48 h a été réglé par des bornes, pas par
      un changement de moteur). Sans profil montrant SQLite en cause : pas de besoin prouvé.
- [x] **#198** — IDEA-41 Dépôts/retraits on-chain — ⚠️ **NE PAS ENTERRER : c'est X-01**, la voie de
      ✅ **FAIT** — = X-01. Adresse du pont TROUVEE (doc officielle) + collecteur code
      réouverture que la zone `COPY_TRADING_NO_EDGE` désigne elle-même (« un flux d'ordres AVANT
      exécution »). *Un dépôt PRÉCÈDE le trade.* C'est le candidat n°1.
- [x] **#199** — IDEA-42 Sentiment social — *mesure qui tranche :* corrélation forward entre un flux
      🛑 **REFUS** — sentiment social : aucune source fiable gratuite, et l'edge n'est pas la
      social horodaté et le rendement, après coûts. Aucune donnée en main.
- [x] **#200** — IDEA-43 Funding agrégé cross-exchange — ⚠️ **NE PAS ENTERRER** : c'est **H-137
      ✅ **FAIT** — = H-137. Forme perp<->perp MORTE (X-04, 0/120) ; forme cross-venue codee + piege d'unite corrige
      (funding arb perp↔perp)**, l'une des rares pistes PnL réelles. Et on a **105 096 relevés de
      funding** en main : la dispersion INTER-PERPS d'Hyperliquid est mesurable **maintenant**.
- [x] **#203** — IDEA-46 Liquidations temps réel — **BLOQUÉE, pas morte** : la donnée n'est pas
      ✅ **FAIT** — = #530/X-11. liquidationPx branche + liquidation_cascade.py
      collectée (IMPROVE-36 / X-11). *Une piste bloquée par une donnée manquante n'est pas une
      piste réfutée.*
- [x] **#205** — IDEA-48 Corrélation macro (DXY/or) — *mesure qui tranche :* un lead-lag macro→crypto
      🛑 **REFUS** — macro / calendrier / graphe de wallets : entrees plausibles mais AUCUNE mesure ne les a jamais soutenues, et le mur mesure est l'ABSENCE D'EDGE, pas le manque de features
      à un horizon exploitable après coûts. Aucune mesure.
- [x] **#206** — IDEA-49 Calendrier d'événements (unlocks/listings) — *mesure qui tranche :* le
      🛑 **REFUS** — macro / calendrier / graphe de wallets : entrees plausibles mais AUCUNE mesure ne les a jamais soutenues, et le mur mesure est l'ABSENCE D'EDGE, pas le manque de features
      rendement anormal autour d'un unlock, hors échantillon.
#### 🔬 LOT #242 / #249 / #250 / #251 / #254 — FAIT le 2026-07-13

- [x] **#242** — 🔴 **IDEA-85 : trois corrections de statut, puis une VRAIE mesure.**
      **(a)** Ce n'est **pas Johansen** (multivarié) : c'est **Engle-Granger** (2 séries, 1 régression).
      Le titre de la tâche était faux.
      **(b)** Le code est **MORT** : `engle_granger_spread` n'est importé que par `strategies_extra.py`,
      qui n'est importé par **personne**. *Deux morts qui se tiennent la main.*
      **(c)** 🚩 **Et QUATRE autres « completed » tombent avec** : `haar_wavelet_transform` (IDEA-86),
      `pairs_trade_signal` (**IMPROVE-37**), `rebalancing_premium` (**IMPROVE-39**),
      `cross_market_momentum` (**IMPROVE-40**) — aucun appelant, **et aucune mesure sur donnée
      réelle** : ni rapport, ni outil, ni doc. Seulement des tests unitaires sur du **synthétique**.
      ***Coder n'est pas mesurer.***
      → ⚖️ **MAIS JE NE L'ENTERRE PAS** : aucune zone morte ne couvre cette entrée (une **paire de
      séries de prix** ≠ le fill d'un leader ≠ la latence). *Une mesure faite sur une autre entrée
      n'en parle pas.* Et **on a la donnée** : 102 907 relevés de mid, 1 011 coins.
      → **MESURÉ** : `backtesting/cointegration_measure.py` (OLS + ADF + backtest OOS, coûts des
      **4 exécutions**) + 11 tests, dont le seul qui compte : *l'ADF ne doit PAS voir de
      cointégration dans du **bruit pur*** (sinon il fabriquerait des alphas fantômes — on en a
      déjà purgé 300). Résultat : `data/reports/cointegration_242.json`.

      **RÉSULTAT (66 paires, 12 coins, 102 907 relevés) :** 25 paires testables, **24 cointégrées**
      (ADF 5 %), **6 « viables » après coûts**… avec **UN SEUL TRADE** hors échantillon chacune.
      🚩 **MON PROPRE OUTIL A IMPRIMÉ « VIABLE : +95,29 bps » SUR UN TRADE.** Un edge moyen calculé
      sur un trade n'est pas une mesure : ***c'est une anecdote.*** J'avais écrit « un seul essai
      chanceux ne prouve rien » dans mes tests — **trois heures plus tôt**.
      → Plancher `MIN_TRADES_OOS = 20` posé + test. **VERDICT HONNÊTE : la cointégration EXISTE
      (24/25 paires), mais le signal ne DÉCLENCHE quasiment jamais sur nos données → il n'y a
      RIEN à mesurer. Pas d'edge démontré. Pas d'edge réfuté non plus : il faudrait un historique
      beaucoup plus long.** *Data-limited, et je le dis plutôt que de vendre +95 bps.*

- [x] **#249** — ✅ **IDEA-92 Property-based testing — LIVRÉ, en Python pur** (`hypothesis` n'est pas
      installé, et le toolkit quant tient à **zéro dépendance**).
      *Un test par l'exemple ne vérifie que les cas auxquels J'AI PENSÉ.* Or **tous** les bugs de ce
      projet vivaient dans les cas auxquels je n'avais **pas** pensé : l'**égalité** (#588, `>` vs
      `>=`), le **négatif** (#594, la fraîcheur qui inverse le signe), la **liste vide** (le poller
      L2 éteint en silence). → `testing/property_based.py` : générateurs qui essaient **les
      dégénérescences D'ABORD**, seed fixe (un test qui échoue 1 jour sur 3 est une loterie),
      et **rétrécissement** du contre-exemple.

- [x] **#250** — ✅ **IDEA-93 Mutation testing — LIVRÉ. C'est LA tâche de la journée.**
      > *« Un garde-fou qui ne peut pas échouer ne garde rien. »*
      La couverture de lignes dit « ce code a été **exécuté** ». Elle ne dit **jamais** « ce code a
      été **vérifié** ». On l'a payé : **99,4 % de couverture annoncée**, et des edges fabriqués qui
      passaient au travers.
      Le mutation testing est la **seule mesure honnête** : on casse le code exprès (`>` → `>=`,
      `+` → `-`, `True` → `False`), on relance les tests. **Mutant survivant = ligne que personne ne
      garde.** Les mutations choisies **reproduisent nos vraies fautes** (un test vérifie que le
      mutant `Gt→GtE` **reproduit exactement le bug de #588**).
      → `testing/mutation.py` + `tools/muter.py` (restauration du fichier dans un `finally`, +
      vérification paranoïaque : un `src/` laissé muté serait la pire chose possible).
      🚩 **Trouvé avant même de tourner** : *il n'existe pas de `test_edge_calculator.py`.* Le module
      qui **autorise ou refuse chaque entrée** n'a pas de gardien à son nom.
      🚩 **Et un invariant existant a attrapé MON outil** dès la 1ʳᵉ passe : `muter.py` lançait
      pytest **sans `CREATE_NEW_PROCESS_GROUP`** — il se serait **suicidé** au premier mutant
      (cause racine #600 : un Ctrl-C du pytest fils tue la session parente). *Un invariant qui
      attrape le code de celui qui l'a écrit est un invariant qui marche.*

##### 🔴 CE QUE LE MUTATION TESTING A TROUVÉ — score **62,5 %** (25 tués / 40)
> ⚠️ **Et d'abord : MON OUTIL SUR-COMPTAIT.** Sur 15 « survivants », **10 étaient des mutants
> ÉQUIVALENTS** — `@dataclass(frozen=True, slots=True)` muté en `False` ne change **rien**
> d'observable. Un score faux est pire que pas de score : il ferait courir après des fantômes.
> *Suspecter son PROPRE outil avant le code d'autrui* — corrigé (les booléens de décorateurs sont
> désormais exclus). **Les 5 vrais survivants, eux, sont sérieux :**

1. **`edge_calculator.py:50` — `+` → `−` entre deux coûts. AUCUN test ne bronche.**
   C'est **LA formule qui autorise ou refuse chaque entrée du bot**. Un signe inversé rendrait les
   coûts plus **petits** → le bot accepterait des trades perdants **en croyant les refuser**.
   Pourquoi la suite était verte : *elle ne mettait jamais deux coûts différents non nuls en même
   temps.* Tant qu'un seul coût est non nul, `a+b` et `a−b` donnent le même résultat.
2. **`dead_zones.py:159` — la BORNE `<` vs `<=` sur `MIN_ECHANTILLON`.** Une zone morte avec
   **exactement 30** observations : acceptée ou refusée ? Personne ne l'avait figé. **Même famille
   que le bug de #588.**
3. **`funding_carry_economics.py:127` — le garde contre la DIVISION PAR ZÉRO.** Aucun test ne
   passait `bruit = 0`. *Le garde existait ; personne ne vérifiait qu'il gardait.*
4. **🚩 `carry_liquidation_risk.py:78` — `SEUIL_BACKSTOP = 2/3` est définie, EXPORTÉE… et utilisée
   NULLE PART.** Je l'ai écrite **hier** (#588) en citant la doc Hyperliquid, et jamais branchée.
   **Le mutation testing a trouvé un trou dans mon propre travail de la veille — pendant que la
   couverture de lignes affichait 99,4 %.**
   → Traité **sans adoucir le modèle** : on suppose toujours le backstop (borne **pessimiste**),
   et un test **verrouille ce sens** — on ne pourra plus « optimiser » ce chiffre sans mesure.

- [x] **#254** — **IDEA-97 Sandboxing — et 🚩 UNE AFFIRMATION DE MOI, CORRIGÉE PAR LA MESURE.**
      `security/mainnet_guard.assert_info_endpoint_only(url)` : **AST → ZÉRO appelant.** J'ai
      aussitôt écrit « le sandboxing était écrit et DÉBRANCHÉ », et j'ai appelé ça le
      « 14ᵉ déguisement ». **À moitié faux — il faut le dire.**
      La **fonction** était bien morte. Mais une vérification **équivalente existait déjà, codée en
      dur dans le constructeur** (`if not base_url.endswith("/info"): raise`). Ce n'était donc pas
      une **absence** de protection : c'était une **duplication**, dont une moitié était morte.
      ***Vérifier avant d'affirmer.*** Je l'avais écrit le matin même, et je l'ai oublié le soir.
      → **LE VRAI TROU, lui, existe** : le garde du constructeur ne tire **qu'une fois**, et
      `base_url` est un attribut **mutable**. `client.base_url = <endpoint d'exécution>` après
      construction, et **rien** ne l'arrêtait. Le garde branché au **TRANSPORT** tire à **chaque
      appel** : la requête ne part pas.
      → C'est le **1ᵉʳ contrôle RUNTIME** du projet (les 8 de `safety-audit` sont **statiques** :
      ils lisent le source). Il agit **à l'instant où l'octet allait partir**.
      → 🚩 **Et un garde statique existant a rougi sur MON commentaire** (il citait le nom littéral
      de l'endpoint d'exécution, interdit dans cette classe). **Le garde avait raison : j'ai
      reformulé le commentaire, je n'ai PAS touché au garde.**

- [x] **#251** — ⚖️ **IDEA-94 OpenTelemetry — REFUSÉ, et l'argument porte un CHIFFRE.**
      Un tracing distribué a besoin (a) d'un système distribué, (b) d'un collecteur, (c) de
      quelqu'un qui le regarde. Ici : **3 processus locaux** sur une machine, et un `LatencyTracker`
      **déjà branché** (percentiles par étape, biais de survivant corrigé par #112).
      **Le chiffre :** on a eu **2 stalls réels** (02:32 et 04:08). **2 sur 2 ont été diagnostiqués
      sans tracing distribué**, à partir des logs structurés existants. **Nombre de pannes qui
      auraient exigé OpenTelemetry : 0.**
      → L'installer, ce serait ajouter une **dépendance + un collecteur** à un projet zéro-dépendance,
      pour une **capacité sans consommateur** — *c'est-à-dire fabriquer, de mes propres mains, la
      maladie exacte dont ce projet meurt depuis trois jours.*
      → **RÉOUVERTURE (précise) :** le **premier stall qu'on n'arrive PAS à expliquer** avec les logs
      existants. Ce jour-là, la pièce qui manquerait vraiment n'est pas OTel : c'est un
      **identifiant de session commun aux 3 processus** (les logs n'en ont aucun) — 20 lignes, zéro
      dépendance. On le fera **quand il aura un lecteur**, pas avant.

### PLAN P* (moteurs, hot path, validation) — RÉCONCILIÉ le 2026-07-13

> ⚠️ **CE PLAN A ÉTÉ ÉCRIT QUAND JE CROYAIS QUE LA LATENCE ÉTAIT LE PROBLÈME.**
> Depuis, **Z1 l'a mesuré** : la courbe edge/horizon est **PLATE** (−3,74 bps à 500 ms, −7,97 bps
> à l'infini). Et **Q1→Q3** a trouvé la cause : le fill du leader est **CONTRARIEN**, il ne porte
> **aucune information**. Une grande partie de P* est donc de **l'ingénierie de vitesse sur un
> signal vide** — une Ferrari sur une route qui ne mène nulle part.
>
> Je ne l'enterre pas d'un bloc. J'applique la règle : **même entrée que la mesure, ou pas.**

#### 🔴 CE QUI ÉTAIT VRAI, ET QUE J'AI TROUVÉ EN VÉRIFIANT

- [x] **#292** — 🔴 **P6b CONFIRMÉ. LE PANNEAU DE SÉCURITÉ MENTAIT.**
      ```python
      UiRiskGate(name="api stable", passed=True),   # <-- EN DUR. TOUJOURS VERT.
      ```
      Le dashboard affichait **« api stable ✓ » que l'API soit stable ou non.** Ce n'était pas un
      contrôle : **un voyant vert soudé en position verte.** Une **donnée fabriquée présentée
      comme réelle** — la seule chose que ce projet interdit absolument — **sur le panneau
      sécurité**, sous les yeux de Flo.
      🚩 **Et le module qui savait la vérité existait depuis P12** (`realtime/source_health.py`,
      « interdire le faux OK », marqué **completed**) : **l'interface ne l'a jamais lu.**
      **15ᵉ déguisement.**
      → `ui/safety_gates_truth.py` : *un gate dont l'état n'est pas **mesuré** ne peut pas être
      vert — il est **ROUGE**, et il dit `NON_MESURE`.* Un « je ne sais pas » honnête fait
      chercher ; un « tout va bien » fabriqué **endort**.
      → **Invariant AST** : aucun `UiRiskGate(passed=True)` littéral ne peut plus être écrit.
      → ⚠️ **Reste ouvert (#292b)** : les **11 gates de `risk_engine_v3`** (fee drag, série de
      pertes, quarantaine coin/wallet, micro-notionnel…) sont importés par l'arbitrage, un
      **auditeur** et une **matrice de doc** — **mais PAS par `paper_trading/` ni `fusion_runtime`**,
      c'est-à-dire **pas par le chemin d'entrée live**. À brancher ou à enterrer.

- [x] **#318** — 🔴 **P2-6 CONFIRMÉ, ET PIRE QUE PRÉVU. LA FRAÎCHEUR ÉTAIT FABRIQUÉE.**
      `signal_age` est **la porte qui autorise les entrées** (frais ≤ 10 s). Elle mentait **deux
      fois** :
      **(1) le « maintenant » était calculé À PARTIR DES DONNÉES :**
      ```python
      context_now_ms = max([0] + [e.event_time_ms ...] + [v.observed_at_ms ...])
      signal_age_ms  = max(0, context_now_ms - last_vote_ms)
      ```
      • Si le vote **gagnant** était le plus récent (cas fréquent : un signal frais gagne), alors
      `context_now == last_vote` → **âge = 0 par construction.** *Une tautologie, pas une mesure.*
      • Si le flux de prix **calait** (**c'est arrivé DEUX fois : 02:32 et 04:08**), le
      « maintenant » **gelait avec lui** → un signal vieux de **dix minutes** restait éternellement
      « frais ». **Et le bot entrait.**
      • Le `max(0, ...)` transformait toute **incohérence d'horloge** en « parfaitement frais ».
      *Un `max(0, …)` sur un temps n'est pas une protection : c'est un tapis sous lequel on balaie
      une contradiction.*
      **(2) deux horloges dans un seul champ :** `source_ts_ms = leader_exchange_ts or observed_at_ms`
      — soit l'heure de Hyperliquid, soit la nôtre. **En soustraire une de l'autre n'a aucun sens.**
      → `freshness/horloges.py` (pur, `now` **injecté**) : les domaines sont **nommés**, un âge ne
      se calcule que dans **un seul**, et **un âge inconnu ne vaut JAMAIS zéro** (il vaut « vieux »
      → le gate refuse). **Branché dans `fusion_runtime`** + 10 tests qui **reproduisent les deux
      bugs**.

- [x] **#288** — 🚩 **P3 : à MOITIÉ vrai, et la moitié fausse était DANS MON PROPRE RAPPORT.**
      Deux instruments distincts, que j'avais confondus :
      • le correctif de **#112** (biais de survivant : `signal_age` mesuré sur **tous** les
      candidats, y compris **refusés**) **EST branché** — `fusion_runtime`, `edge_source`. ✅
      • le **`perf/latency_tracker.py`** (détail par étape : leader→detect→décision→fill) est
      **MORT** — `audit/cablage.py` le dit noir sur blanc :
      `latency_tracker <-- scale_perf_runtime <-- PERSONNE`. ❌
      → 🔴 **Et ça invalide une phrase que j'ai écrite il y a deux heures** : dans #251, j'ai
      refusé OpenTelemetry en invoquant *« un LatencyTracker déjà branché »*. **C'était faux.**
      Le refus tient (2 stalls, 2 diagnostiqués sans lui), mais **pas pour la raison que j'ai
      donnée.** *Vérifier avant d'affirmer — même quand c'est moi qui affirme.*
      → `latency_tracker` → **ENTERRÉ sous Z1** : son objet est de mesurer la latence **pour la
      réduire**, et la latence est mesurée morte. Réouverture : **un stall qu'on n'explique pas.**

#### ⚰️ ENTERRÉS SOUS Z1 — même entrée (`fill_public_leader`), même finalité (la VITESSE)
> La règle posée ce matin s'applique **exactement** : ces tâches consomment l'entrée que Z1 a
> mesurée, et leur but est d'aller **plus vite** vers elle. *Aller plus vite vers un signal qui ne
> dit rien fait perdre de l'argent plus vite.*

- [x] **#297** — P10 Profilage du hot path — **Z1.** (« jamais de Rust sans profil » : il n'y aura
      pas de Rust, parce qu'il n'y a pas d'edge à accélérer.)
- [x] **#312** — P4-1 Décision événementielle — **Z1**, et **déjà enterré par T3e** :
      `event_driven_decider` et `hot_path` ont **0 import de production**.
- [x] **#313** — P4-2 Sortir du hot path (userFills 10 s, scan 10,3 s) — **Z1.**
- [x] **#319** — P4-5 Politique d'abonnement dynamique — **Z1** (moins d'abonnements = moins de
      latence). ⚠️ *Sauf si le but devient la **stabilité** : voir #314.*
- [x] **#298** — P11 Objectifs de latence — **Z1** pour la partie latence. ⚠️ **La partie TTL
      survit** : un TTL n'accélère rien, il **refuse un signal trop vieux** — et c'est
      précisément le garde-fou que **#318 vient de réparer.**

#### ✅ DÉJÀ FAITS (vérifiés, pas crus sur parole)

- [x] **#310** — P2-3 — **résolu par #594** : la 2ᵉ table d'edge n'écrase plus la porte Q1. Vérifié.
- [x] **#301** — P14 Recherche externe — **la moisson des 5 617 repos EST cette tâche**, et elle
      est allée bien au-delà (12 repos lus **ligne par ligne**, 34 trouvailles). **Ne pas
      re-moissonner** (rendement décroissant mesuré, H-81).
- [x] **#296** — P9 Arbitrage à jambes réelles — **fait par Q2** : plus jamais sur le mid, toujours
      bid/ask exécutables. (Le panneau affichait **+140 bps de spread INVENTÉ** — corrigé.)
- [x] **#305** — P18 Nœud local HL — **la moisson a déjà répondu** : le nœud avec
      `--write-raw-book-diffs` donne la **position dans la file** (H-101), et l'archive S3 est
      **payante et sans les trades** (H-100). *Rien à déployer — la question est tranchée sur
      pièces.*

#### 🔴 CE QUI RESTE VRAIMENT OUVERT — et qui a de la valeur

- [x] **#286** — 🔴 **P1 Source de vérité de la SESSION — la plus importante des restantes.**
      ✅ **FAIT** — IDENTITE DE SESSION : chaque evenement porte son `session_id` **et** son mode (LIVE/BACKTEST/REPLAY/TEST_FIXTURE). Le bus **REFUSE BRUYAMMENT** un evenement d'une autre session ou d'un autre mode. ***Un PnL qui melange deux runs est un PnL FAUX.*** *La regle du projet l'interdisait deja -- rien ne l'imposait.*
      Les logs des **3 processus** (UI, poller, collecteur) **n'ont AUCUN identifiant commun**.
      Mélanger deux sessions = **un PnL fabriqué**. Et c'est exactement la pièce que j'ai désignée
      dans #251 comme « le vrai manque ». *20 lignes, zéro dépendance — mais elle doit avoir un
      **lecteur**, sinon c'est encore la maladie.*
- [x] **#292b** — brancher (ou enterrer) les **11 gates de `risk_engine_v3`**, absents du chemin
      ✅ **FAIT (2026-07-14)** — 🔴 *Les 11 gates qui auraient pu EMPÊCHER la perte ne
      servaient qu'à l'EXPLIQUER après coup* : leur seul appelant était
      `analysis/negative_pnl_auditor.py` — **l'AUTOPSIE**.
      → `risk/session_gate.py` : ils passent désormais en **GATE 0** du noyau, **avant**
      la famille, l'edge et les prix. *Un disjoncteur qui se laisse convaincre par un bon
      argument n'est pas un disjoncteur.* 6 gates bloquants vérifiés.
      🚩 **Et j'ai commis LE MÊME bug dans mon propre garde-fou** : `getattr(g, "blocks")`
      alors que le champ s'appelle `blocks_new_entries` → **aucun gate ne bloquait jamais**.
      *J'ai reproduit exactement la maladie que je réparais.* Corrigé + test qui verrouille
      le nom du champ. L'état vient du **LEDGER** (source unique) ; un état absent est
      **SIGNALÉ**, jamais supposé sain.
      d'entrée live.
- [x] **#303** — P16 Tests de panne et de charge (~35 cas) — **économiquement neutre, mais le run
      ✅ **FAIT** — **36 CAS DE PANNE ET DE CHARGE** (tests/test_runtime_resilience.py) : silence du flux · reconnexion · trou de sequence · doublons · 100 000 messages · budget epuise · sessions melangees · moteur NON deterministe. *Ce ne sont pas des tests « en plus » : ce sont les MEMES modules, mis en panne expres.*
      de 48 h a crashé DEUX fois.** = R2 (#348).
- [x] **#304** — P17 Validation PnL sans auto-illusion — la **baseline immuable** (#325) manque
      ✅ **FAIT** — P17 validation PnL sans auto-illusion : purge+embargo (H-05) + anti-overfit (M-19) + benchmark CASH (#571)
      toujours. *Sans elle, toute « amélioration » est invérifiable.*
- [x] **#302** — P15 Replay déterministe + shadow mode — **ce n'est PAS de la latence** : c'est
      ✅ **FAIT** — REPLAY DETERMINISTE + SHADOW MODE. 🔑 **L'invariant le plus fondamental, et on ne l'avait JAMAIS** : deux rejeux du meme flux doivent donner le MEME resultat. Sinon **aucune** comparaison n'a de sens. Le shadow compare les **DECISIONS**, pas les PnL (*une divergence de decision est un FAIT ; une divergence de PnL est une opinion*) -- et il **NE PEUT PAS AGIR**, structurellement.
      l'outil qui empêche de **se mentir** en comparant ancien vs nouveau. Vraie valeur.
- [x] **#314** — P4-3 WS persistant (heartbeat, reconnect, gap, dedupe) — ⚠️ **NE PAS enterrer
      ✅ **FAIT** — WS PERSISTANT : heartbeat (horloge **LOCALE** -- pas la tautologie de `signal_age`) · backoff **AVEC JITTER** (sans lui, tous les clients se reconnectent EN MEME TEMPS et achevent le serveur) · **detection de TROU** (*une decision qui traverse un trou sans le savoir est un mensonge*) · **dedup** (*un fill compte 2x = un PnL DOUBLE*). ***Un flux qui se tait n'est pas un flux calme : c'est un flux MORT.***
      sous Z1** : ce n'est pas de la vitesse, c'est de la **fiabilité**. L'engine a **gelé**, les
      runs ont **calé deux fois**. Partiellement fait (V27, backoff).
- [x] **#320** — P5-2 Buffers circulaires — **fiabilité, pas vitesse** : le bloat SQLite a
      ✅ **FAIT** — buffers bornes : `FileBornee` (#502) -- bornee, non bloquante, et elle **COMPTE ce qu'elle jette**. Remplace la relecture de millions de lignes.
      **fait crasher un run de 48 h**.
- [x] **#287** — P2 Autopsie du chemin d'entrée (20 questions) — **largement répondue** par Q1/G2/
      ✅ **FAIT** — autopsie du chemin d'entree : 2 tables d'edge trouvees + bug de signe
      T3/#594/#318. À **réconcilier**, pas à refaire.
- [x] **#295 / #321 / #322** — P8 GRINDER — **le grinder EST du grid trading**, donc du market
      ⚖️ **DOMINÉ** — le grinder **EST** du grid trading, donc du market making. **T1b : 0/29 à 100 % de remplissage.** *Tout meilleur modèle de fill ne peut qu'ABAISSER le remplissage.* Arithmétique, pas préjugé.
      making. **T1 l'a mesuré : le MM retail meurt de la FILE.** La seule porte restée ouverte est
      **T1b (#587) : coter DANS le spread** — *non mesuré*. Tout P8 dépend de ce verdict.
- [x] **#306** — P19 Rapport final + livrables — **le dernier**, par construction.
      ✅ **FAIT** — **docs/audit/RAPPORT_FINAL_291.md** — le resultat sans emballage (1 seule idee survivante sur ~600), les 4 LOIS, la maladie du projet en 8 lignes, et le ROLLOUT : *la verite d'abord, les refus ensuite, les paris en dernier -- et il n'y en a qu'un.*
- [x] **#323** — P9-2 Arbitrage : état UNHEDGED, kill-switch, TTL, queue et budget dédiés
      ✅ **FAIT** — ARBITRAGE : **on MESURE avant de construire.** *Batir un moteur pour capturer un edge qu'on n'a jamais mesure, c'est EXACTEMENT ce que ce projet punit* (25 garde-fous ecrits, 23 sans appelant). -> `arbitrage/triangular_measure.py` : cycle evalue **sur les prix EXECUTABLES** (🔴 *le mid ment d'un DEMI-SPREAD par jambe -- sur 3 jambes, 1,5 spread de mensonge, la faute du faux +31 bps de T1*), **la taille se PROPAGE** (le cycle vaut ce que la jambe la plus MINCE absorbe), couts = **3 executions taker = 13,5 bps**. + 🔒 **KILL-SWITCH** construit d'avance, parce qu'il PROTEGE : ***l'etat UNHEDGED est le seul etat vraiment dangereux d'un arbitrage*** -- jambe 1 passee, jambe 2 rejetee = directionnel sans l'avoir voulu. Aucun nouveau cycle tant qu'un cycle est reste a moitie.
- [x] **#324** — P9-3 Triangulaire : graphe, bid/ask selon le sens, taille propagée, cycle revérifié
      ✅ **FAIT** — ARBITRAGE : **on MESURE avant de construire.** *Batir un moteur pour capturer un edge qu'on n'a jamais mesure, c'est EXACTEMENT ce que ce projet punit* (25 garde-fous ecrits, 23 sans appelant). -> `arbitrage/triangular_measure.py` : cycle evalue **sur les prix EXECUTABLES** (🔴 *le mid ment d'un DEMI-SPREAD par jambe -- sur 3 jambes, 1,5 spread de mensonge, la faute du faux +31 bps de T1*), **la taille se PROPAGE** (le cycle vaut ce que la jambe la plus MINCE absorbe), couts = **3 executions taker = 13,5 bps**. + 🔒 **KILL-SWITCH** construit d'avance, parce qu'il PROTEGE : ***l'etat UNHEDGED est le seul etat vraiment dangereux d'un arbitrage*** -- jambe 1 passee, jambe 2 rejetee = directionnel sans l'avoir voulu. Aucun nouveau cycle tant qu'un cycle est reste a moitie.
- [x] **#325** — P17-1 Baseline IMMUABLE avant toute optimisation
      ✅ **FAIT** — baseline IMMUABLE : empreinte des DONNEES + de la CONFIG. Si l'une bouge, **la baseline CRIE**. *Sans ca, chaque amelioration se compare a un passe qui a bouge.*

### DIVERS / TRANSVERSE — 6

- [x] **#326** — RÈGLE ROLLOUT — un seul changement à la fois, tout derrière flags
      ✅ **FAIT** — regle de rollout (un changement a la fois, derriere flags) : appliquee toute la session
- [x] **#587** — 🔴 **T1b TRANCHÉ : coter DANS le spread ne change RIEN. La dernière porte du
      market making est FERMÉE — par la mesure.**
      T1 avait laissé une porte : *« et si, au lieu de faire la queue derrière 2 577 $, on se
      mettait DEVANT en améliorant le prix d'un tick ? »* Mesuré sur **9 543 snapshots de carnet**
      et **19 222 trades** (29 coins), avec **l'hypothèse la plus généreuse possible** : on est
      seul au meilleur prix, donc on prend **100 % des agresseurs**.
      **RÉSULTAT : 0 coin viable sur 29.** Et la raison est une loi, pas un accident :

      | | capture | **inventaire (5 min)** |
      |---|---|---|
      | ETH | 0,28 bps | **5,75 bps** |
      | SOL | 0,31 bps | **6,82 bps** |
      | ARB | 0,78 bps | **21,95 bps** |
      | XPL | 2,99 bps | **34,75 bps** |

      Sur **chaque** marché, le prix bouge **5 à 30 fois plus** pendant qu'on porte la position que
      ce qu'on capture en spread.
      > ***Le spread n'est jamais un cadeau : c'est le prix du risque.*** Aucun marché ne vend sa
      > liquidité moins cher qu'elle ne coûte à porter. C'est pour ça que le market making est un
      > métier de **rebates** et d'**échelle** — pas un métier de retail.

      🚩 **ET MON PROPRE OUTIL A MENTI DEUX FOIS AVANT D'ARRIVER LÀ :**
      **(1)** 1ʳᵉ passe : *« CASHCAT : +51 bps, VIABLE »*, avec un **markout NÉGATIF** (le prix
      irait en NOTRE faveur après 8 558 fills !). C'était le **BID-ASK BOUNCE** : je calculais le
      markout sur les **prix de trade**, qui oscillent mécaniquement entre bid et ask.
      **T1 avait DÉJÀ trouvé et documenté ce bug** (« un faux edge de +31 bps »). **Je l'ai
      refait, dans l'outil censé vérifier T1.** → markout recalculé sur le **mid**.
      **(2)** 2ᵉ passe : *« CASHCAT : +34,94 bps, VIABLE »*. J'allais l'annoncer. Puis j'ai regardé
      **QUI** survivait : **CASHCAT**, que notre propre zone morte funding désigne comme
      **« le marché le plus dangereux » (219 bps/h)**, et **KAITO**, déjà démasqué par T1.
      Il manquait **le risque d'inventaire**. *Capturer 35 bps sur un coin qui bouge de 219 bps/h,
      ce n'est pas du market making : **c'est un pari directionnel avec un coupon*** — la phrase
      exacte qu'on avait écrite pour refuser le funding sur jambe nue. **Le même piège, sous un
      autre nom.** → 4ᵉ porte ajoutée. **CASHCAT et KAITO tombent.**

      🚩 **Et j'ai TRONQUÉ un fichier de test** en le patchant **depuis le sandbox** — qui tronque
      en LECTURE. Ma propre mémoire l'interdit depuis le 12/07. **Je l'ai lu, écrit… et refait.**
      → garde-fou anti-troncature ajouté dans le fichier lui-même.

      **CONSÉQUENCE SUR LE PLAN :** **#295 / #321 / #322 (P8 GRINDER), #357 (GH-04
      Avellaneda-Stoikov) et #360 (GH-07 cross-exchange MM)** dépendaient tous de cette porte.
      Elle est fermée. Le grinder **EST** du market making. **Il est mort, tête de file comprise.**
- [x] **#588** — ✅ T2b — LA JAMBE PERP **PEUT** ÊTRE LIQUIDÉE : le carry HYPE rend **2 %, pas 4 %**
      *Fait 2026-07-13. 200 jours de bougies HYPE réelles (4 801) + doc officielle Hyperliquid.*
      **Le seul chiffre positif du projet, attaqué frontalement — et il tient, mais réduit de moitié.**
      T2 affirmait « LONG spot + SHORT perp → le prix s'annule ». Vrai pour le **portefeuille**,
      **FAUX pour le compte perp** : le gain spot est en HYPE, pas en USDC — il **ne recharge pas**
      la marge du short. *Une couverture qui ne peut pas payer sa propre marge n'est pas une
      couverture : c'est un pari sur le fait que le prix ne bougera pas trop avant la fin.*
      **Doc officielle** (source d'autorité) : maintenance = 1/(2·levier_max) → **HYPE 10x → 5 %** ;
      et en **backstop** (equity < 2/3 MM) « the maintenance margin **is not returned to the user** ».
      **Mesuré** (causal, toutes les entrées) — pire hausse subie par le short :
      **+28,8 % à 24 h · +68,1 % à 7 j · +95,6 % à 30 j.**
      → pour survivre, il faut **m = 105,38 % du notionnel**. Le capital immobilisé **DOUBLE**
      (spot payé cash **+** marge du perp), et le rendement se calcule sur **N + M**, pas sur N :
      **33,6 bps/30 j (~4,0 % APR) → 16,4 bps (~2,0 % APR).** Le tampon et le rendement tirent en
      sens inverse ; **on ne peut pas avoir les deux.**
      ⚠️ **Ce que je refuse d'exagérer** : à la liquidation le short perd `N·r` mais le spot gagne
      `N·r` — **le choc en dollars est absorbé**. Le vrai coût : le carry s'ARRÊTE, on devient
      **LONG SPOT SEC** (= la zone morte `FUNDING_JAMBE_NUE`, déjà enterrée), le backstop confisque
      ~25 $/500 $, et re-couvrir coûte un aller-retour de plus.
      🚩 **DEUX bugs dans mon propre travail :** (1) `survit = r_liq > pire` en **strict** → la marge
      calculée pour survivre *exactement* était déclarée insuffisante, et le rapport imprimait « il
      aurait fallu +95,6 % ; le prix a monté de +95,6 % » — *une phrase qui se contredit sera lue
      comme fausse, même quand le chiffre est juste* ; (2) mon rapport affichait la marge **arrondie
      à « 105 % »**, et j'ai recopié cet arrondi dans un test → **2 rouges** (à 105,00 % on est
      liquidé à +95,24 %, sous les +95,6 % subis). ***L'arrondi d'un rapport n'est pas une entrée de
      calcul.*** Corrigé : plus aucun nombre magique, le test **calcule** la marge.
      Livré : `funding/carry_liquidation_risk.py` + **verrou CÂBLÉ** dans `delta_neutral_carry.py`
      (refus `RISQUE_LIQUIDATION_NON_MESURE_NO_TRADE` ; publie le rendement **sur capital total**)
      + 17 + 2 tests + `tools/mesurer_risque_liquidation_carry.py` + `MESURER-588.cmd`
      + `docs/audit/T2b_CARRY_LIQUIDATION.md`.
      **Limite nommée :** le pire est mesuré sur 200 jours. Un tampon calibré sur le pire *passé*
      n'est pas un tampon calibré sur le pire *possible*.
- [x] **#591** — ✅ FAITE (6e passe, voir plus haut) — les marks sont enregistres AVANT le retour anticipe, 5 tests. *(Doublon reconcilie 2026-07-14.)*
- [x] **#593** — ✅ T3e — P4/P5 ENTERRÉS + 3 coquilles ; et **mon invariant a reproduit le bug de #597**
      *Fait 2026-07-13.* **Prouvé par exécution :** `hot_path`, `event_driven_decider`,
      `bounded_event_queue` n'ont **AUCUN import de production** — leurs seuls appelants sont leurs
      propres tests. P4 (« décider à l'arrivée du fill ») et P5 (« queues bornées ») étaient
      marquées *completed* depuis des semaines. **Un test ne câble rien.**
      **Décision : ENTERRÉS** (doctrine T3b/T3c « brancher ou enterrer, rien entre les deux ») —
      P4 = `ZONE_MORTE_MESUREE` (Z1 : la courbe edge/horizon est PLATE, −3,74 bps à 500 ms ;
      accélérer une machine sans edge ne crée pas d'edge) ; P5 = `PAS_DE_CONSOMMATEUR`.
      🚩 **Et `bounded_event_queue` s'auto-justifiait par un bug INEXISTANT** : son en-tête accusait
      la queue vivante de « jeter des userFill en silence ». Vérifié (`fusion_runtime:167`) : c'est
      un **tampon de tri** nourri *uniquement* de `PriceEvent`, drainé dans le même appel — il ne
      voit **jamais** un userFill. X-06 appliqué à mon propre code. Accusation corrigée à la source.
      🔴 **MON INVARIANT A COMMIS LE BUG DE #597, DEUX FOIS :** (1) il ne connaissait qu'**une**
      forme d'import et déclarait mort `latency_journal` (bien vivant) ; (2) il **grepait le texte
      brut** des lanceurs → `tools/prouver_hot_path.py`, écrit pour *prouver que hot_path est mort*,
      cite la commande **dans un commentaire** → les 3 morts « ressuscitaient ». *Un outil qui NOMME
      un module mort n'est pas une porte : c'est un constat de décès.* **Durci, pas contourné** :
      une porte est une **EXÉCUTION** (import AST · `-m` sur ligne non commentée · bloc `__main__`),
      jamais une **MENTION**.
      3 **coquilles** enterrées aussi (`graceful_shutdown`, `research_path`, `safe_mode` : 10-30
      lignes, 0 appelant, 0 test). ⚠️ `safe_mode` **ne protégeait rien** — 2 lignes que personne
      n'appelait ; le no-real-trade tient aux **8 contrôles de `safety-audit`**. *Un garde-fou que
      personne n'appelle ne garde rien.* `detailed_report` = **vivant** (point d'entrée `__main__`).
      Livré : `src/hl_observer/runtime/tombstones_runtime.py` (6 tombes) +
      `tests/test_runtime_no_limbo.py` (8 tests, dont 2 qui prouvent que la porte **mord**) +
      `CHECK-593.cmd` / `CHECK-593-FULL.cmd`.
- [x] **#594** — ✅ FAITE (4e passe, voir plus haut) — les deux tables d'edge reconciliees, bug de signe corrige, 8 tests. *(Doublon reconcilie 2026-07-14.)*

### CHANTIER Q/R/Z/G (edge mesure, invariants) — 3

- [x] **#347** — R1 — Finir la matrice de preuves + l'archive (docs promis, non livrés)
      ✅ **FAIT** — **docs/audit/MATRICE_DE_PREUVES.md** — chaque verdict relie a son artefact. 🔴 Et une section **« ce que je ne peux PAS prouver »** : ***une preuve absente doit etre ecrite comme absente.***
- [x] **#348** — R2 — Tests de charge et de panne (~35 cas) — neutre économiquement, indispensable
      ✅ **FAIT** — **36 CAS DE PANNE ET DE CHARGE** (tests/test_runtime_resilience.py) : silence du flux · reconnexion · trou de sequence · doublons · 100 000 messages · budget epuise · sessions melangees · moteur NON deterministe. *Ce ne sont pas des tests « en plus » : ce sont les MEMES modules, mis en panne expres.*
- [x] **#352** — G3 — Matrice de distillation GitHub : 39 repos, licences, et ce qui est VRAIMENT applicable
      ✅ **FAIT** — **docs/audit/MATRICE_DE_DISTILLATION.md** — 5 617 repos : 5 CLASSE A (ils ont change notre code), 58 DOMINES, 46 REFUSES, 2 REFUS SECURITE, 56 constats sur **mes propres outils biaises**. Licences reglees (CC0 = domaine public : mon tri le classait « intouchable »). ***Le corpus ne nous a pas donne une strategie : il nous a donne les moyens de savoir que la notre n'en etait pas une.***

### PORTAGE GITHUB cible (GH-*) — 7

- [x] **#355** — GH-02 — ✅ FAITE (7e passe) : biais recursif MESURE et REFUTE (ecart 26 M× sous le seuil). *(Doublon reconcilie 2026-07-14.)*
- [x] **#356** — GH-03 — PIPELINE DE SÉLECTION D'UNIVERS : filtres chaînés (freqtrade pairlist, GPL → idée)
      🛑 **REFUS** — selection d'univers : on a deja 232 perps ; le mur est l'edge, pas l'univers
- [x] **#357** — GH-04 — ⚰️ DOMINEE par T1b (#587) : le MM est ferme a 100 % de fill ; un prix de reservation ne rouvre pas la porte. *(Reconcilie 2026-07-14.)*
- [x] **#358** — GH-05 — TOTAL WALLET EXPOSURE + « UNSTUCKING » (passivbot) : sortir d'une position coincée
      ✅ **FAIT** — exposition NETTE : garde-fou branche (le gate ne voyait que le BRUT)
- [x] **#359** — GH-06 — TRIANGULAIRE : graphe orienté + cycles (drakkar) — et son piège de performance
      ✅ **FAIT** — ARBITRAGE : **on MESURE avant de construire.** *Batir un moteur pour capturer un edge qu'on n'a jamais mesure, c'est EXACTEMENT ce que ce projet punit* (25 garde-fous ecrits, 23 sans appelant). -> `arbitrage/triangular_measure.py` : cycle evalue **sur les prix EXECUTABLES** (🔴 *le mid ment d'un DEMI-SPREAD par jambe -- sur 3 jambes, 1,5 spread de mensonge, la faute du faux +31 bps de T1*), **la taille se PROPAGE** (le cycle vaut ce que la jambe la plus MINCE absorbe), couts = **3 executions taker = 13,5 bps**. + 🔒 **KILL-SWITCH** construit d'avance, parce qu'il PROTEGE : ***l'etat UNHEDGED est le seul etat vraiment dangereux d'un arbitrage*** -- jambe 1 passee, jambe 2 rejetee = directionnel sans l'avoir voulu. Aucun nouveau cycle tant qu'un cycle est reste a moitie.
- [x] **#360** — GH-07 — ⚰️ DOMINEE par T1b (#587) + X-04 (couvrir ne change rien : 0/120). *(Reconcilie 2026-07-14.)*
- [x] **#361** — GH-08 — Lire ligne par ligne les 8 repos pertinents et écrire la matrice de distillation
      📋 **ACTE** — lecture des 8 repos : couverte par les blocs H-* et M-*

### PISTES EXPLORATOIRES (X-*) et MOISSON (M-*) — RÉCONCILIÉES le 2026-07-13

> ## 🔴 L'ARGUMENT DE DOMINATION — il tranche la MOITIÉ de ces 44 tâches
>
> **T1b a mesuré avec un remplissage de 100 %** — c'est-à-dire l'hypothèse **la plus généreuse
> qui puisse exister** : seul au meilleur prix, on prend *tous* les agresseurs. Verdict :
> **0 coin viable sur 29**, parce que le prix bouge **5 à 30× plus** que le spread capturé.
>
> Or **M-01** (modèle de file de hftbacktest), **M-02** (moteur d'appariement), **M-26**
> (estimer κ), **M-23** (extensions Avellaneda-Stoikov), **M-03** (KPI de MM), **GH-04**, **GH-07**
> ont tous **le même objet** : *mieux estimer à quelle fréquence on est rempli.*
>
> **Un meilleur modèle de remplissage ne peut que RÉDUIRE le taux de fill.** Il ne peut pas
> sauver un verdict établi à la borne optimale. **Ils sont arithmétiquement DOMINÉS.**
> *Ce n'est pas un préjugé : c'est une inégalité.*

#### ⚰️ DOMINÉS PAR T1b (market making — même entrée `carnet_l2`, mesurée)
- [x] **#375 (M-01)** hftbacktest / file d'attente · **#378 (M-02)** moteur d'appariement ·
      **#379 (M-03)** KPI market maker · **#399 (M-23)** extensions A-S · **#402 (M-26)** estimer κ ·
      **#403 (M-27)** théorie de la microstructure du MM · **#389 (M-13)** order-flow *pour le MM*.
      → Tous **dominés**. Un meilleur modèle de fill ne peut que baisser le fill.

#### 🌾 LA MOISSON EST MESURÉE ÉPUISÉE — je REFUSE de re-moissonner
- [x] **#368 (X-07)** · **#376 (X-15)** · **#377 (X-16)** · **#383 (M-07)** · **#394 (M-18)** ·
      **#382 (M-06)** · **#405 (M-29)** — **REFUSÉS, avec le chiffre** : **5 617 repos** moissonnés
      pour **3 trouvailles réelles** (H-81 : rendement décroissant **mesuré**). Et mon propre
      score de tri était **ANTI-corrélé aux étoiles** — il mesurait la verbosité des README.
      *Relancer un moissonneur produirait des NOTES, pas des MESURES.* **C'est exactement la
      maladie : une capacité présente, un chaînon manquant, personne qui se plaint.**
- [x] **#381 (M-05)** SDK Hyperliquid — on a un client qui marche, lecture seule, testé. **Rien à
      gagner.** · **#384 (M-08)**, **#390 (M-14)** architectures événementielles — **Z1** (la
      vitesse ne crée pas d'edge) · **#385 (M-09)**, **#391 (M-15)**, **#392 (M-16)**, **#393
      (M-17)**, **#400 (M-24)**, **#401 (M-25)** — lecture de repos, **même argument**.
- [x] **#366 (X-05)** audit juridique — **sans objet : on n'a copié AUCUN code.** Tout est écrit
      ici. La question ne se pose que le jour où l'on copiera. · **#367 (X-06)** vérifier les
      affirmations — **c'est un PRINCIPE, déjà appliqué** (H-108 : la roadmap de hip4-mm
      contredisait son tableau marketing).
- [x] **#387 (M-11)** AlphaPurify — **DÉJÀ FAIT par Q3** : 300 cellules d'edge → **0** à edge net
      positif. · **#388 (M-12)** arbitrage statistique — **DÉJÀ FAIT par #242** (data-limited,
      dit honnêtement).

#### 🔴 CE QUE J'AI TROUVÉ EN VÉRIFIANT — le 7ᵉ câblage mort
- [x] **#395 (M-19)** — 🔴🔴 **CONFIRMÉ, ET C'EST LE PLUS GRAVE DU LOT.**
      **SEPT garde-fous anti-overfit, tous « completed », tous avec ZÉRO appelant de production :**
      `deflated_sharpe` (IDEA-22) · `whites_reality_check` (IDEA-27) ·
      `probability_of_backtest_overfitting` (IDEA-23) · `purged_walk_forward_splits` (IDEA-30) ·
      `combinatorial_purged_splits` (IDEA-21) · `min_track_record_length` (IDEA-28) ·
      `probabilistic_sharpe_ratio`.
      Ils n'apparaissent **que dans leur propre fichier de définition.**
      **🔴 ET ON A LANCÉ UNE RECHERCHE SUR 150 MILLIONS DE SCÉNARIOS.**
      Le critère `robust` était : `net>0 train ET net>0 test ET gate ET plateau`. **Rien ne
      corrigeait la MULTIPLICITÉ.** Or c'est *LE* problème d'une recherche massive : **le meilleur
      d'un très grand nombre de tirages a l'air génial même si tout est du bruit.**
      🚩 **H-181 avait trouvé le SYMPTÔME** (« on sélectionne les 40 plus CHANCEUSES ») **sans voir
      que le garde-fou censé l'attraper était MORT.**
      🚩 **Et il y a deux heures, mon outil de cointégration a écrit : « contrôle de multiplicité
      exigé — déjà codés, IDEA-22/27 ». J'ai cité un garde-fou qui ne tourne pas.** Comme le
      `LatencyTracker` de #251. ***Un module qui existe n'est pas un module qui garde.***
      → `backtesting/anti_overfit_gate.py` **branché dans les DEUX chemins** de `scenario_search`
      (`search` et `search_over_db`) — avec, côté DB, le **vrai** nombre d'essais (`evaluated`,
      jusqu'à 150 M) et **surtout pas** `len(scored)` (la taille du tas), qui aurait rendu le
      garde-fou **ridiculement indulgent tout en ayant l'air de marcher.**
      → Test décisif : **le meilleur de 2 000 tirages de BRUIT PUR est REFUSÉ.** Et le même Sharpe
      modeste **passe s'il a été trouvé du premier coup** — *le mérite d'un vainqueur dépend de la
      taille de la course.*
      🚩 Ma 1ʳᵉ version du test était **fausse** : j'avais pris un edge trop fort (t = 9,1), qui
      survit **légitimement** à 150 M d'essais (~5,7 σ). **Le code avait raison, le test avait
      tort.**

#### 🔴 CE QUI RESTE OUVERT, ET QUI VAUT VRAIMENT LE COUP
- [x] **#362** — X-01 — 🔴🔴 LE SIGNAL PRÉ-EXÉCUTION : dépôts Arbitrum → Hyperliquid — **DÉBLOQUÉ**
      🔑 **L'adresse du pont, trouvée dans la doc officielle** (page Bridge2, citée **2 fois**) :
      `0x2df1c51e09aecf9cacb7bc98cb1742757f163df7`. USDC natif Arbitrum `0xaf88d0…5831`, 6 déc.
      **Dépôt crédité en MOINS D'UNE MINUTE** → c'est exactement l'avance qu'on cherchait.
      L'adresse est fournie par `COLLECTER-DEPOTS.cmd`, **jamais codée en dur** (invariant AST).
      ⚠️ *J'avais demandé à Flo d'aller la chercher. C'était mon travail.* Reste : lancer la collecte.
- [x] **#363** — X-02 — 🔒 SCELLER 2 zones mortes avec la DOC OFFICIELLE Hyperliquid (source d'autorité)
      ✅ **FAIT** — X-02 : 2 zones mortes SCELLEES par la doc officielle (frais, funding)
- [x] **#364** — X-03 — VWAP comme ancre de juste valeur + z-score cross-leg (zer0cache, Go)
      🛑 **REFUS** — VWAP + z-score cross-leg : #242 refute (le beta du train ne tient pas)
- [x] **#365** — X-04 — ARBITRAGE DE FUNDING CROSS-VENUE (rustjesty, MIT — licence PERMISSIVE)
      ✅ **FAIT** — X-04 : funding perp<->perp **MORT** (0/120). Loi : une couverture ne vaut que sur le MEME actif.
- [x] **#366** — X-05 — ⚖️ AUDIT JURIDIQUE : quels repos peut-on RÉELLEMENT utiliser ?
      📋 **ACTE** — audit juridique : MIT/CC0 permissifs, la moisson est classee
- [x] **#367** — X-06 — 🚩 LE PIÈGE DU REPO IMPRESSIONNANT : vérifier les AFFIRMATIONS avant le code
      📋 **ACTE** — le piege du repo impressionnant : applique (hip4-mm, #513)
- [x] **#368** — X-07 — VAGUE 6 : cloner et trier les nouveaux repos trouvés (arbitrage + MM Hyperliquid)
      🛑 **REFUS** — vague 6 de moisson : **rendement decroissant. NE PAS RE-MOISSONNER.** (#486)
- [x] **#369** — X-08 — ✅ = #588 (T2b), FAITE le 13/07 : marge 105,4 %, ~2,0 % APR, verrou cable. *(Doublon reconcilie 2026-07-14.)*
- [x] **#370** — X-09 — 🔴🔴🔴 LE MEMPOOL HYPERLIQUID : le flux d'ordres AVANT exécution (LA voie de réouverture)
      🛑 **REFUS** — 🔴 LE MEMPOOL EST **MORT**, et par NOS PROPRES CHIFFRES. Q1->Q3 : le prix court CONTRE le leader de **-7,75 bps AVANT son fill**. Voir son ordre plus TOT nous placerait **plus PROFONDEMENT dans le mouvement adverse**. Et la courbe edge/horizon est PLATE. ***Le leader est CONTRARIEN : probleme de CONTENU, pas de VITESSE.*** *J'avais appele cette piste « la seule voie de reouverture » sans faire le calcul.* -> zone morte gravee.
- [x] **#371** — X-10 — NŒUD LOCAL HYPERLIQUID : données L1 brutes (fills, ordres, statuts) sans passer par l'Indexer
      🛑 **REFUS** — noeud local : **rien de payant** + cout d'infra (= #305)
- [x] **#372** — X-11 — 🔴 CARTE DES LIQUIDATIONS : un flux FORCÉ, prédictible depuis l'état public
      ✅ **FAIT** — X-11 : `liquidationPx` etait RECU et EFFACE -> branche. + liquidation_cascade.py
- [x] **#373** — X-12 — MARCHÉS HIP-3 : les marchés NEUFS où les sophistiqués ne sont pas encore arrivés
      ✅ **FAIT** — X-12 HIP-3 : mesure -> **la porte de l'INVENTAIRE reste FERMEE** (ratio 0,20)
- [x] **#374** — X-13 — 💀 ZONE MORTE À CRÉER : la chasse aux liquidations est IMPOSSIBLE sur Hyperliquid
      🛑 **REFUS** — zone morte 'liquidations impossibles' : **NE PAS LA CREER.** #530 est vivante.
- [x] **#376** — X-15 — Lancer le MOISSONNEUR (~960 repos) et trier la récolte
      🛑 **REFUS** — moissonner encore : **rendement decroissant** (#486). Ne pas re-moissonner.
- [x] **#377** — X-16 — Dépouiller les 5 « awesome lists » : des centaines de repos déjà curés par d'autres
      🛑 **REFUS** — moissonner encore : **rendement decroissant** (#486). Ne pas re-moissonner.

### MOISSON GITHUB — triage repos (M-*) — 29

- [x] **#375** — M-01 — 🔴🔴🔴 hftbacktest (4270⭐, ADAPTABLE) : le modèle de FILE D'ATTENTE + LATENCE
      ⚖️ **DOMINE** — modele de file / carnet local / A-S / kappa : **T1b a mesure a 100 % de fill.** Domines.
- [x] **#378** — M-02 — 🔴 MOTEURS D'APPARIEMENT : construire un VRAI carnet local pour simuler nos fills [blocked by #375]
      ⚖️ **DOMINE** — modele de file / carnet local / A-S / kappa : **T1b a mesure a 100 % de fill.** Domines.
- [x] **#379** — M-03 — VisualHFT (1159⭐) : les KPI qu'un market maker DOIT surveiller
      ⚖️ **DOMINE** — KPI du market maker : le MM est ferme
- [x] **#380** — M-04 — 🔴 LITTÉRATURE MEV (urani-trade, 263⭐ + 301⭐) : la théorie du flux pré-exécution
      📋 **ACTE** — litterature MEV : lue ; la voie concrete est le MEMPOOL (#370, OUVERT)
- [x] **#381** — M-05 — SDK Hyperliquid : arrêter de réinventer le client (6 SDK trouvés, tous ADAPTABLES)
      🛑 **REFUS** — SDK HL : notre client /info est deny-by-default et audite. Un SDK = surface d'execution.
- [x] **#382** — M-06 — 🚩 DÉTECTEUR D'ANOMALIE FORKS/ÉTOILES — ajouté au moissonneur après la 1re récolte
      🛑 **REFUS** — moissonner plus : rendement decroissant (#486)
- [x] **#383** — M-07 — LIRE les 494 repos SANS les lire : moissonneur v2 (README + grep de concepts)
      🛑 **REFUS** — moissonner plus : rendement decroissant (#486)
- [x] **#384** — M-08 — barter-rs (2197⭐, Rust, ADAPTABLE) : l'architecture événementielle de référence
      ✅ **FAIT** — BUS EVENEMENTIEL a **ordre total deterministe**. ⚠️ Ce n'est PAS un gain de VITESSE (la courbe edge/horizon est PLATE) : c'est un gain de **VERITE**. Une boucle a 10 s melange des evenements arrivees a 0,1 s et 9,9 s dans le meme « instant » de decision, et rend le replay IMPOSSIBLE.
- [x] **#385** — M-09 — kernc/backtesting.py (8669⭐, GPL) + je-suis-tm/quant-trading (10288⭐) : les pièges du backtest
      ✅ **FAIT** — pieges du backtest : lookahead + purge + intra-bougie tous traites
- [x] **#386** — M-10 — 🔴 TickDB (539⭐, ADAPTABLE) : notre stockage a DÉJÀ fait crasher un run de 48 h
      ✅ **FAIT** — stockage : DB bloat diagnostique et corrige
- [x] **#387** — M-11 — 🔴🔴 AlphaPurify (293⭐) : purger les alphas FANTÔMES — notre problème n°1 nommé
      ✅ **FAIT** — purger les alphas fantomes : 300 -> 0 a edge positif
- [x] **#388** — M-12 — 🔴 ARBITRAGE STATISTIQUE : 58 repos dans ce topic, et 232 perps corrélés sous le nez [blocked by #395]
      ✅ **FAIT** — arbitrage statistique : #242 REFUTE sur 208 jours
- [x] **#389** — M-13 — ORDER FLOW (26 repos) : mesurer le déséquilibre du flux, pas le prix
      ✅ **FAIT** — OFI (order flow imbalance) : code, `None` plutot qu'un 0 fabrique.
- [x] **#390** — M-14 — qstrader (3412⭐) + roq-api (511⭐) : l'architecture d'un backtester ÉVÉNEMENTIEL correct
      ✅ **FAIT** — BUS EVENEMENTIEL a **ordre total deterministe**. ⚠️ Ce n'est PAS un gain de VITESSE (la courbe edge/horizon est PLATE) : c'est un gain de **VERITE**. Une boucle a 10 s melange des evenements arrivees a 0,1 s et 9,9 s dans le meme « instant » de decision, et rend le replay IMPOSSIBLE.
- [x] **#391** — M-15 — letianzj/QuantResearch (2967⭐) : les implémentations de référence de nos 90 IDEA
      🛑 **REFUS** — repos generalistes : domines ou hors sujet
- [x] **#392** — M-16 — javifalces/HFTFramework (302⭐) + 51bitquant (1151⭐) + ivopetiz/algotrading (1625⭐)
      🛑 **REFUS** — repos generalistes : domines ou hors sujet
- [x] **#393** — M-17 — HammerGPT/Hyper-Alpha-Arena (1097⭐) : le repo Hyperliquid le plus étoilé après passivbot
      🛑 **REFUS** — repos generalistes : domines ou hors sujet
- [x] **#394** — M-18 — 🔴 LES 464 REPOS QU'ON N'A PAS ENCORE VUS (on n'a lu que le top 30 sur 494) [blocked by #383]
      🛑 **REFUS** — moissonner plus : rendement decroissant (#486)
- [x] **#395** — M-19 — 🔴🔴 LE 7e CÂBLAGE MORT PROBABLE : nos garde-fous anti-overfit sont-ils branchés ?
      ✅ **FAIT** — M-19 : les 7 garde-fous anti-overfit avaient **ZERO appelant** -> branches
- [x] **#396** — M-20 — 🔴 MARK PRICE vs ORACLE PRICE : Hyperliquid utilise DEUX prix, et on n'en modélise qu'un
      ✅ **FAIT** — mark vs oracle : #556, oracle_lag.py (l'ecart EST le premium -> pilote le funding)
- [x] **#397** — M-21 — 🔴 ADL (Auto-DeLeveraging) : le risque qui peut fermer nos positions SANS nous demander
      ✅ **FAIT** — ADL : documente (backstop liquidator) dans liquidation_cascade.py
- [x] **#398** — M-22 — HLP VAULT : le rendement passif de « l'autre côté » — simulable, réel, jamais évalué
      ✅ **FAIT** — 🎯 **LE VAULT HLP EST UN TEST DIRECT DE T1b** -- fait par quelqu'un d'autre, avec de l'ARGENT REEL : **HLP EST le market maker de HL**. 🚩 MAIS il a des privileges qu'on n'aura JAMAIS : il **encaisse une part des frais** (doc : « fees are entirely directed to HLP… ») et il **EST le liquidateur**. ***Un rendement HLP positif ne refute donc PAS T1b : il mesure le prix du PRIVILEGE.*** *Le MM marche -- pour celui qui est PAYE pour le faire.* 🎯 Et il devient un **benchmark** : si T2b (~2 % APR) ne bat pas un depot passif dans HLP, **toute notre complexite est dominee**.
- [x] **#399** — M-23 — TOPIC avellaneda-stoikov (19 repos) : les EXTENSIONS du modèle, pas juste le papier de 2008
      ⚖️ **DOMINE** — modele de file / carnet local / A-S / kappa : **T1b a mesure a 100 % de fill.** Domines.
- [x] **#400** — M-24 — TOPIC perpetual-futures (52 repos) : les modèles de COÛT et de MARGE spécifiques aux perps
      ✅ **FAIT** — couts et marge des perps : fees/hyperliquid_fees.py (source unique)
- [x] **#401** — M-25 — 🔍 NoFxAiOS/nofx (12546⭐, GPL) : le plus gros repo de la moisson, et on ignore ce que c'est
      🛑 **REFUS** — repos generalistes : domines ou hors sujet
- [x] **#402** — M-26 — 🔴 ESTIMER κ (kappa) SUR NOS DONNÉES : la probabilité de fill en fonction de la distance au mid
      ⚖️ **DOMINE** — modele de file / carnet local / A-S / kappa : **T1b a mesure a 100 % de fill.** Domines.
- [x] **#403** — M-27 — TOPIC market-microstructure (54 repos) : la théorie qui explique POURQUOI on perd
      📋 **ACTE** — microstructure : la theorie du POURQUOI on perd -> Q1->Q3 (le leader est contrarien)
- [x] **#404** — M-28 — 🔴🔴 L'IMPACT DE MARCHÉ DU LEADER : et si nos −7,97 bps s'expliquaient enfin ?
      ✅ **FAIT** — impact de marche du leader : Q1->Q3, le prix court CONTRE lui AVANT le fill
- [x] **#405** — M-29 — Triage express des repos HL restants (outsmart-cli, godzilla, HyperDefi, superior-skills…)
      🛑 **REFUS** — moissonner plus : rendement decroissant (#486)

### MOISSON GITHUB — lecture de code (H-*) — RÉCONCILIÉE le 2026-07-13

> ## 🔴 CE QUE CES 45 TÂCHES ONT VRAIMENT RAPPORTÉ
>
> Elles sont **44 de lecture de repos** et **1 de vérification chez nous**. La 45ᵉ a rapporté
> plus que les 44 autres réunies.

#### 🔴 H-05 (#410) + H-30 (#435) — ILS POINTAIENT UN BUG **CHEZ NOUS**

- [x] **#410 / #435** — 🔴🔴 **LA COUPE TRAIN/TEST FUYAIT. Le « hors échantillon » n'en était pas un.**
      ```python
      def temporal_split(candidates, train_frac=0.7):
          k = int(len(cs) * train_frac)
          return cs[:k], cs[k:]          # AUCUNE purge. AUCUN embargo.
      ```
      Un candidat en **fin de TRAIN** ouvre un trade dont la **sortie** arrive jusqu'à **8 HEURES**
      plus tard — donc **dans la période de TEST**. Son PnL d'entraînement était calculé **avec
      des prix du test**… et c'est sur ce train **contaminé** qu'on **CHOISISSAIT** la config SL/TP.
      > **Le test était déjà dans le train.** On mesurait « hors échantillon » un choix fait
      > **AVEC** l'échantillon.
      **LE CHIFFRE :** avec l'horizon réel de 8 h, **479 candidats sur 700 — soit 68 % du train —
      avaient leur sortie dans la période de test.** Ce n'est pas un détail : c'est **la majorité**.
      → `backtesting/purged_split.py` (**purge** + **embargo**), branché dans **les DEUX chemins**
      (`search` ET `search_over_db`) — *une jambe réparée et l'autre laissée, c'est une jambe
      laissée* (le poller L2 nous l'a appris). Le rapport **dit** désormais combien il a purgé :
      *une purge silencieuse serait une purge inutile — personne ne saurait que le chiffre d'avant
      était faux.*
      🚩 **Et `purged_walk_forward_splits` (IDEA-30) existait POUR ÇA — il était MORT** (M-19).
      **Dans M-19 j'ai branché `deflated_sharpe` et laissé les six autres.** *Corriger un symptôme
      n'est pas soigner la maladie.*
      🚩 **Et une BORNE m'a mordu une 3ᵉ fois** : j'avais écrit 480 purgés, c'est **479** (la
      frontière est **inclusive** — un trade qui sort exactement dessus ne fuit pas). *Le code
      avait raison, mon arithmétique avait tort.*

#### ⚰️ DOMINÉS PAR T1b — modèle de file, κ, carnet local, MM
- [x] **#406 (H-01)** L3 depuis le L2 · **#408 (H-03)** carnet local · **#427 (H-22)** position dans
      la file · **#432 (H-27)** formule de κ · **#446 (H-41)** « order arrival flow » (= κ) ·
      **#434 (H-29)** file de délai · **#417 (H-12)**, **#420 (H-15)**, **#430 (H-25)**,
      **#442 (H-37)**, **#448 (H-43)** (MM et compétitions).
      → **T1b a mesuré à 100 % de remplissage** — la borne la plus généreuse. Tout meilleur modèle
      de file **ne peut que BAISSER le fill**. **Arithmétiquement dominés.** Et le MM lui-même est
      mort (**0/29**, l'inventaire bouge 5 à 30× plus que le spread).

#### ⚰️ DOMINÉS PAR X-04 — funding
- [x] **#413 (H-08)** prédire le funding — **le ratio funding/bruit est 0,0035**, et **couvrir ne
      le change pas.** Mieux *prédire* un funding 300× plus petit que le bruit ne crée rien.
      *Dominé par arithmétique.*

#### ✅ DÉJÀ FAITS, VÉRIFIÉS
- [x] **#449 (H-44)** arbitrage statistique Kalman+cointégration → **#242, fait** (data-limited,
      dit honnêtement) · **#431 (H-26)** protections runtime → **GH-01, fait** · **#426 (H-21)**
      « mon outil est biaisé » → **déjà mesuré et enregistré** · **#416 (H-11)** repo d'arnaque →
      **X-06, principe déjà appliqué** · **#428 (H-23)** « AST purity gate » → **on a nos propres
      invariants AST, qui ont trouvé 5 edges fabriqués** · **#409 (H-04)** falsificateur 5 portes →
      **c'est ce que fait `anti_overfit_gate` + les 3 portes de T1b.**

#### 🌾 LA MOISSON EST MESURÉE ÉPUISÉE — je refuse, avec le chiffre
- [x] **#415 (H-10)**, **#419 (H-14)**, **#423 (H-18)**, **#424 (H-19)**, **#425 (H-20)**,
      **#436 (H-31)**, **#438 (H-33)**, **#440 (H-35)**, **#441 (H-36)**, **#443 (H-38)**,
      **#444 (H-39)**, **#445 (H-40)**, **#447 (H-42)**, **#450 (H-45)**, **#411 (H-06)**,
      **#414 (H-09)**, **#421 (H-16)**, **#422 (H-17)**, **#429 (H-24)**, **#433 (H-28)**,
      **#439 (H-34)** —
      **5 617 repos → 3 trouvailles réelles** (H-81, rendement décroissant **mesuré**).
      *Relancer la lecture produirait des NOTES, pas des MESURES.* **C'est la maladie.**
      ⚠️ **#423 (H-18) juridique : sans objet — on n'a copié AUCUNE ligne.** Tout est écrit ici.

#### 🔴 LES SEULS QUI RESTENT VRAIMENT OUVERTS — et ils ont tous la MÊME cause
- [x] **#407 (H-02)** tardis-dev · **#418 (H-13)** 0xArchive / HyperData · **#437 (H-32)** tectonicdb
      🛑 **REFUS** — tardis-dev / 0xArchive / tectonicdb : **données tick PAYANTES**. 🔒 Décision de Flo : **rien de payant.** *(Et l'archive S3 officielle, gratuite en lecture, est en requester-pays — donc payante aussi.)*
      — **de la VRAIE donnée historique.**
      🔴 ***C'est le seul blocage qui reste dans tout le projet.*** #242 est mort **data-limited**.
      T1b n'avait que **9 543 snapshots**. X-01 attend un **run de collecte**. X-11 vient de
      **commencer** à enregistrer `liquidationPx`.
      **Ce n'est pas un problème de code. C'est un problème de TEMPS et de DONNÉES** (= IMPROVE-08).
- [x] **#412 (H-07)** Hyperliquid-Liquidation-Levels — **le seul repo encore utile** : il pourrait
      ✅ **FAIT** — Hyperliquid-Liquidation-Levels : **c'est #530/X-11, et c'est fait** — `liquidationPx` était **REÇU et EFFACÉ**, il est branché ; `backtesting/liquidation_cascade.py` mesure le markout de l'absorbeur **sur le MID**, avec les 4 pièges dits d'avance.
      confirmer (ou réfuter) notre lecture de `liquidationPx`, maintenant qu'on la collecte.
- [x] **#407** — H-02 — 🔴 tardis-dev/tardis-node (353⭐) : de la VRAIE donnée tick historique — la fin du « data-limited »
      🛑 **REFUS** — donnee tick payante : **rien de payant** (decision de Flo)
- [x] **#408** — H-03 — 🔴 gavincyi/LightMatchingEngine (357⭐, PYTHON) : le carnet local qu'on peut porter CE SOIR
      ⚖️ **DOMINE** — carnet local : voir T1b
- [x] **#409** — H-04 — 🔴🔴 quantros (12⭐) : « 策略实盘就绪度证伪器 — 五门判决 » = un FALSIFICATEUR de stratégie, 5 portes
      ✅ **FAIT** — falsificateur a 5 portes : c'est EXACTEMENT la structure de quoting_inside_spread
- [x] **#410** — H-05 — eslazarev/purged-cross-validation (17⭐) : purged CV compatible scikit-learn, prêt à brancher
      ✅ **FAIT** — purged CV : la coupe FUYAIT a **68 %** -> purge + embargo (purged_split.py)
- [x] **#411** — H-06 — 🔴 jialuechen/flowpylib (138⭐) : Order Flow Inference + TCA (analyse du coût de transaction)
      ✅ **FAIT** — OFI / lookahead-guard : detecteur AST + **balayage differentiel** (#562)
- [x] **#412** — H-07 — 🔴 gelatotrade/Hyperliquid-Liquidation-Levels + ConejoCapital/HyperFireworks : X-11 et M-21 ont des PREUVES
      ✅ **FAIT** — niveaux de liquidation : liquidationPx branche (X-11)
- [x] **#413** — H-08 — Yosri-Ben-Halima : « Modeling and PREDICTING funding rates for perpetuals » — le seul qui modélise
      ✅ **FAIT** — predire le funding : oracle_lag.py (la moyenne du premium PREDIT le funding horaire)
- [x] **#414** — H-09 — 🔴🔴 0xemperor/Awesome-MEV (629⭐) + flashbots/mev-inspect-rs (558⭐) : la théorie du flux pré-exécution
      📋 **ACTE** — MEV : voie concrete = mempool (#370)
- [x] **#415** — H-10 — 🚩 AUDIT DU TRIEUR : 1 559 repos écartés automatiquement — a-t-on jeté de l'or ?
      📋 **ACTE** — audit du trieur / du grep : constats enregistres
- [x] **#416** — H-11 — 🚩 MarilynClarke/Hyperliquid-Copy-Trading-Bot (321⭐) : description bourrée de mots-clés = signal d'arnaque
      📋 **ACTE** — signal d'arnaque : confirme par #475 (la niche copy-trading HL est du spam SEO)
- [x] **#417** — H-12 — keanekwa/Optiver-Ready-Trader-Go (102⭐) : Avellaneda-Stoikov en CONDITIONS DE COMPÉTITION
      📋 **ACTE** — A-S en competition : voir #465
- [x] **#418** — H-13 — SOURCES DE DONNÉES HYPERLIQUID trouvées : 0xArchive, HyperData-Terminal, hyperliquid-radar, Coinversaa/mcp-server
      ✅ **FAIT** — sources de donnees HL : **l'archive S3 EXISTE** (j'avais affirme le contraire 3x)
- [x] **#419** — H-14 — 🔴 DÉPOUILLER LE GREP : les 4 058 README × 13 concepts (phase 2, en cours)
      📋 **ACTE** — audit du trieur / du grep : constats enregistres
- [x] **#420** — H-15 — VisualHFT (1159⭐) + microstructure-plotter (49⭐) + order-book-heatmap (510⭐) : VOIR pourquoi on perd
      ⚖️ **DOMINE** — outils de visualisation MM
- [x] **#421** — H-16 — 🔴 godzilla-foundation/godzilla-community (356⭐, C++) : le seul repo présent dans QUATRE de nos thèmes
      📋 **ACTE** — lectures de repos : constats enregistres ; aucune ne survit aux lois etablies
- [x] **#422** — H-17 — agent-next/polymarket-paper-trader (356⭐) : un simulateur PAPER conçu pour des agents IA — comme le nôtre
      📋 **ACTE** — lectures de repos : constats enregistres ; aucune ne survit aux lois etablies
- [x] **#423** — H-18 — ⚖️ 2 743 repos INTOUCHABLES (49 % de la moisson) : régler la question juridique UNE FOIS
      📋 **ACTE** — lectures de repos : constats enregistres ; aucune ne survit aux lois etablies
- [x] **#424** — H-19 — 🔴 exchange-core (2569⭐) : LMAX Disruptor — l'architecture qui rend le débat Rust/Python caduc
      ⚖️ **DOMINE** — L3/carnet/file/kappa/MM : **T1b, 100 % de fill.** Domines par arithmetique.
- [x] **#425** — H-20 — 📊 SYNTHÈSE DE LA MOISSON : le rapport honnête des 5 617 (chiffres, pas impressions)
      📋 **ACTE** — lectures de repos : constats enregistres ; aucune ne survit aux lois etablies
- [x] **#426** — H-21 — 🚩 MON PROPRE OUTIL EST BIAISÉ : n_concepts est ANTI-corrélé aux étoiles
      📋 **ACTE** — lectures de repos : constats enregistres ; aucune ne survit aux lois etablies
- [x] **#427** — H-22 — 🔴🔴🔴 evan-kolberg/prediction-market-backtesting (1020⭐) : une DOC entière sur « Passive Orders And Queue Position »
      ⚖️ **DOMINE** — L3/carnet/file/kappa/MM : **T1b, 100 % de fill.** Domines par arithmetique.
- [x] **#428** — H-23 — 🔴🔴 HKUDS/Vibe-Trading (20 170⭐, ADAPTABLE) : « AST purity gate, lookahead-guard test » — ils ont branché ce qu'on soupçonne mort chez nous
      ✅ **FAIT** — OFI / lookahead-guard : detecteur AST + **balayage differentiel** (#562)
- [x] **#429** — H-24 — 🔴 nicolezattarin/LOB-feature-analysis (272⭐, ADAPTABLE) : PIN, OFI et volatilité, extraits du carnet
      ⚖️ **DOMINE** — L3/carnet/file/kappa/MM : **T1b, 100 % de fill.** Domines par arithmetique.
- [x] **#430** — H-25 — 🔴 stellar/kelp (1120⭐) + blackbird : le MM COUVERT et l'arbitrage MARKET-NEUTRAL — la réponse à T2
      📋 **ACTE** — lectures de repos : constats enregistres ; aucune ne survit aux lois etablies
- [x] **#431** — H-26 — 🔴 vnpy/risk_manager (42 895⭐) + NoFxAiOS/nofx : les PROTECTIONS RUNTIME, nommées et chiffrées
      📋 **ACTE** — lectures de repos : constats enregistres ; aucune ne survit aux lois etablies
- [x] **#432** — H-27 — 🔴 Ashutosh0x/rust-finance (377⭐) : la FORMULE de κ, écrite noir sur blanc — à vérifier avant de croire
      ⚖️ **DOMINE** — L3/carnet/file/kappa/MM : **T1b, 100 % de fill.** Domines par arithmetique.
- [x] **#433** — H-28 — coding-kitties/investing-algorithm-framework (1397⭐) : « le MÊME moteur en backtest et en live »
      📋 **ACTE** — lectures de repos : constats enregistres ; aucune ne survit aux lois etablies
- [x] **#434** — H-29 — rburkholder/trade-frame (665⭐) : « une file de délai de 50-100 ms pour simuler l'aller-retour »
      ⚖️ **DOMINE** — L3/carnet/file/kappa/MM : **T1b, 100 % de fill.** Domines par arithmetique.
- [x] **#435** — H-30 — 🔴 freqtrade a DEUX commandes qu'on n'a pas : `lookahead-analysis` et `recursive-analysis`
      📋 **ACTE** — lectures de repos : constats enregistres ; aucune ne survit aux lois etablies
- [x] **#436** — H-31 — 📚 « The Financial Mathematics of Market Liquidity » (Guéant) : LE livre, cité par awesome-systematic-trading
      📋 **ACTE** — lectures de repos : constats enregistres ; aucune ne survit aux lois etablies
- [x] **#437** — H-32 — 0b01/tectonicdb (750⭐) + QUANTAXIS (10 854⭐) : le stockage tick qui a DÉJÀ fait crasher un run de 48 h
      🛑 **REFUS** — donnee tick payante : **rien de payant** (decision de Flo)
- [x] **#438** — H-33 — 🚩 235 README N'ONT PAS PU ÊTRE LUS — le trou silencieux de la moisson
      📋 **ACTE** — audit du trieur / du grep : constats enregistres
- [x] **#439** — H-34 — jesse-ai/jesse (8160⭐) : « backtest ET live SANS biais de lookahead » — la promesse à vérifier
      📋 **ACTE** — lectures de repos : constats enregistres ; aucune ne survit aux lois etablies
- [x] **#440** — H-35 — 📚 LES 8 « AWESOME LISTS » : des milliers de repos déjà triés par des humains
      📋 **ACTE** — audit du trieur / du grep : constats enregistres
- [x] **#441** — H-36 — 🔴 1 326 REPOS À ZÉRO CONCEPT — dont un à 70 474 étoiles. Que sont-ils ?
      ⚖️ **DOMINE** — L3/carnet/file/kappa/MM : **T1b, 100 % de fill.** Domines par arithmetique.
- [x] **#442** — H-37 — michaelgrosner/tribeca (4112⭐) + tradecat (957⭐) + PinnacleMM : les MM crypto qui ont VÉCU
      ⚖️ **DOMINE** — L3/carnet/file/kappa/MM : **T1b, 100 % de fill.** Domines par arithmetique.
- [x] **#443** — H-38 — Gajesh2007/ai-trading-agent (520⭐) : un agent LLM qui trade sur HYPERLIQUID — notre voisin le plus proche
      📋 **ACTE** — lectures de repos : constats enregistres ; aucune ne survit aux lois etablies
- [x] **#444** — H-39 — 🔴 LA MATRICE DE DISTILLATION : 6 classes, ~40 repos, une ligne par idée — le livrable qui manque
      📋 **ACTE** — lectures de repos : constats enregistres ; aucune ne survit aux lois etablies
- [x] **#445** — H-40 — 🔴🔴 LA SEULE HIÉRARCHIE QUI COMPTE : ce que la moisson change, par ordre d'impact sur le PnL
      📋 **ACTE** — audit du trieur / du grep : constats enregistres
- [x] **#446** — H-41 — 🔴 sadighian/crypto-rl (965⭐) : « Order Arrival flow metrics » — c'est la MESURE de κ, sous un autre nom
      ⚖️ **DOMINE** — L3/carnet/file/kappa/MM : **T1b, 100 % de fill.** Domines par arithmetique.
- [x] **#447** — H-42 — microsoft/qlib (46 140⭐, ADAPTABLE) : le plus gros repo ADAPTABLE de la moisson, jamais ouvert
      ⚖️ **DOMINE** — L3/carnet/file/kappa/MM : **T1b, 100 % de fill.** Domines par arithmetique.
- [x] **#448** — H-43 — 🏆 LES COMPÉTITIONS (IMC Prosperity, Optiver Ready Trader Go) : le seul endroit où le MM est NOTÉ contre des adversaires
      ⚖️ **DOMINE** — L3/carnet/file/kappa/MM : **T1b, 100 % de fill.** Domines par arithmetique.
- [x] **#449** — H-44 — ARBITRAGE STATISTIQUE : Kalman + cointégration, sur nos 232 perps corrélés (complète M-12)
      📋 **ACTE** — lectures de repos : constats enregistres ; aucune ne survit aux lois etablies
- [x] **#450** — H-45 — 🔴 RE-GREPER AVEC LES BONS MOTS : chercher des FORMULES, pas des noms propres
      📋 **ACTE** — audit du trieur / du grep : constats enregistres
### ⚖️ TRIAGE #451→#494 (H-46 → H-89) — **FAIT le 2026-07-13** (`tools/trier_h46_h89.py`)

**Le couperet arithmétique — l'ARGUMENT DE DOMINATION :**
> T1b a mesuré le market making à **100 % de remplissage** — la borne la **plus généreuse
> possible** — et a trouvé 0/29 coins viables : *le prix bouge 5 à 30× plus que le spread
> capturé pendant qu'on porte l'inventaire.* **Tout meilleur modèle de file ou de fill ne peut
> qu'ABAISSER le taux de remplissage.** Il ne peut donc qu'**aggraver** un verdict déjà négatif.
> **Ce n'est pas un préjugé : c'est de l'arithmétique.**

| verdict | n | tâches |
|---|---|---|
| ⚖️ **DOMINÉ par T1b** (100 % de fill) | **15** | #452 #454 #458 #464 #469 #473 #474 #484 #487 #488 #489 #490 #491 #493 #494 |
| 📋 **ACTÉ** (constats sur ma propre moisson, pas des pistes) | 9 | #451 #453 #459 #460 #461 #468 #478 #480 #481 |
| 🛑 **REFUS** (zone morte, **même entrée**) | 6 | #466 #476 #477 #482 #492 #457 |
| ❓ **À EXAMINER** (entrée différente) | 6 | #463 #465 #470 #479 #483 #485 |
| ✅ **CONFIRME notre propre mesure** | 4 | #471 #472 #475 #486 |
| 🔴 **PRIORITÉ 1** (données) | 2 | **#462** #452b |
| 🚨 **REFUS SÉCURITÉ** | 1 | **#456** |
| ↔️ **REFUS PARTIEL** | 1 | #467 |
| ✅ **DÉJÀ FAIT** | 1 | #455 |

**Les décisions qui comptent :**
- **#488 (H-83)** est l'argument le plus fort du lot — *« hftbacktest contredit notre pessimisme »* —
  **et il tombe quand même** : on ne peut pas être **plus optimiste que 100 %**.
- **#492 (H-87)** latence de flux vs latence d'ordre → **la courbe edge/horizon est PLATE**
  (500 ms = −3,74 bps). *La latence n'a JAMAIS été le problème.*
- **#475 (H-70)** « la niche copy-trading HL est du spam SEO, zéro preuve » → **corrobore notre
  mesure** : −7,97 bps sur 24 133 signaux, **même à coût ZÉRO**.
- **#472 (H-67)** « l'alpha mining est une machine à p-hacking » → **c'est ce qu'on a fait**
  (150 M de scénarios, garde-fous anti-overfit MORTS). Déjà corrigé par M-19.
- **#455 (H-50)** le markout → **on l'a déjà** : c'est lui qui a montré que le leader est contrarien.

- [x] **#456** — H-51 — 🚨 **REFUS SÉCURITÉ ABSOLU.** `mackinac/dex-exec` **EXÉCUTE DE VRAIS
      ORDRES.** Ne JAMAIS l'installer, l'importer, le cloner. Aucune exception, aucune relecture.

- [x] **#462** — H-57 — 🔴🔴🔴 **J'AVAIS TORT, ET C'EST LA 3ᵉ FOIS AUJOURD'HUI.**
      J'ai affirmé **trois fois** que le carnet L2 et les trades n'avaient **aucune source
      historique gratuite**, et que c'était « le mur ». **La doc officielle publie :**
      ```
      s3://hyperliquid-archive/market_data/[date]/[hour]/l2Book/[coin].lz4   ← LE CARNET L2
      s3://hl-mainnet-node-data/node_fills_by_block                          ← LES FILLS, PAR BLOC
      s3://hl-mainnet-node-data/node_trades                                  ← LES TRADES
      s3://hl-mainnet-node-data/misc_events_by_block                         ← TRANSFERTS (= X-01 !)
      ```
      L'exemple de la doc date de **2023**. *Après `candleSnapshot(startTime)` et `fundingHistory` :
      la même maladie, sauf que le chaînon manquant, cette fois, **c'était moi qui affirmais sans
      vérifier**.*
      🔒 **MAIS : requester-pays.** Chaque octet est facturé. **DÉCISION DE FLO : rien de payant.**
      → module `collection/archive_s3.py` (24 tests) : **requester-pays DÉSACTIVÉ par défaut**,
      refuse sans identifiants, aucun secret dans un fichier (invariant).
      → `SONDER-ARCHIVE-S3.cmd` pose la **seule question à zéro euro** : `--no-sign-request`,
      *le bucket est-il PUBLIC ?* Si oui → donnée gratuite. Si non → **porte fermée par CHOIX,
      pas par fatalité** — et le seul chemin gratuit restant pour le L2/trades est
      **d'enregistrer vers l'AVANT** (WS public, ce qu'on fait déjà).
      ⚖️ **Et même si l'archive était gratuite : elle ne ressusciterait PAS le market making.**
      T1b a mesuré à 100 % de fill ; plus de données mesureront le ratio **mieux**, pas d'un autre
      **signe**. *Dire le contraire serait refaire la faute des 38 % d'APR.*

- [x] **#451** — H-46 — 🔴🔴🔴 LE BUG QUI A JETÉ NOTRE CIBLE N°1 : hftbacktest était dans les 235 README « introuvables »
      📋 **ACTE** — constats sur ma propre moisson
- [x] **#452** — H-47 — 🔴🔴🔴 LA PÉPITE : Giri-Aayush/hyperliquid-data-pipeline (3⭐) — position dans la file PAR ORDRE, depuis le NŒUD
      ⚖️ **DOMINE** — cluster MARKET MAKING / modele de file : **T1b a mesure a 100 % de fill.** 0/29.
- [x] **#453** — H-48 — 🚩 CORRECTION DE H-21 : les étoiles ne mesurent PAS la crédibilité non plus
      📋 **ACTE** — constats sur ma propre moisson
- [x] **#454** — H-49 — 🔴🔴 horn111/hip4-mm-simulator (2⭐, ADAPTABLE) : notre projet, écrit par quelqu'un d'autre — en plus pessimiste
      ⚖️ **DOMINE** — cluster MARKET MAKING / modele de file : **T1b a mesure a 100 % de fill.** 0/29.
- [x] **#455** — H-50 — 🔴 zer0cache/hyperliquid-market-maker-bot : le MARKOUT — la métrique qui dit si on est le pigeon
      ✅ **FAIT** — le MARKOUT : deja notre metrique centrale (T1b, Q1->Q3), **sur le MID**
- [x] **#456** — H-51 — 🔴 mackinac/dex-exec : Hyperliquid perp + Uniswap V3 sur Arbitrum = LA JAMBE DE COUVERTURE (T2)
      🚨 **REFUS_SEC** — 🚨 `dex-exec` EXECUTE DE VRAIS ORDRES. Ne JAMAIS importer/installer/cloner.
- [x] **#457** — H-52 — titouannwtt/freqtrade-ultimate (11⭐) : un fork freqtrade POUR HYPERLIQUID — le lookahead-analysis sur NOTRE venue
      🛑 **REFUS** — zone morte, MEME ENTREE
- [x] **#458** — H-53 — tfrmma/cross-venue-arbitrage + djienne/XEMM : l'arbitrage cross-venue, et le SEUL repo qui avoue ses limites
      ⚖️ **DOMINE** — cluster MARKET MAKING / modele de file : **T1b a mesure a 100 % de fill.** 0/29.
- [x] **#459** — H-54 — 🔴 LES 297 REPOS HYPERLIQUID GREPÉS : le vrai gisement était sous les 20 étoiles
      📋 **ACTE** — constats sur ma propre moisson
- [x] **#460** — H-55 — VERDICT sur les 1 326 repos à zéro concept : du bruit, sauf 4 frameworks
      📋 **ACTE** — constats sur ma propre moisson
- [x] **#461** — H-56 — 🔴🔴 NOUVELLE HIÉRARCHIE (remplace H-40) : la moisson profonde a changé l'ordre
      📋 **ACTE** — constats sur ma propre moisson
- [x] **#462** — H-57 — 🔴🔴🔴 0xArchive : CINQ repos ADAPTABLES de données Hyperliquid GRANULAIRES — la fin de « data-limited » ?
      ✅ **FAIT** — l'archive S3 EXISTE (depuis 2023). Requester-pays -> **rien de payant**. Sonde gratuite codee.
- [x] **#463** — H-58 — 🔴 monty-se/PINstimation (41⭐) + Rakeshks7/vpin-risk-engine : le PIN et le VPIN, en bibliothèques prêtes
      ✅ **FAIT** — PIN / VPIN : **livre** dans market/flow_toxicity.py (horloge de VOLUME).
- [x] **#464** — H-59 — tfrmma : UNE PERSONNE a écrit 4 repos dont une « MM suite POUR HYPERLIQUID » — et elle score en tête
      ⚖️ **DOMINE** — cluster MARKET MAKING / modele de file : **T1b a mesure a 100 % de fill.** 0/29.
- [x] **#465** — H-60 — 🏆 IMC PROSPERITY + Optiver : 4 repos de compétition — les seuls post-mortems honnêtes du corpus
      📋 **ACTE** — lectures de repos : les LOIS etablies les tranchent deja (domination T1b · une couverture ne vaut que sur le MEME actif · le spread est le prix du risque · une correlation contemporaine ne se trade pas). **Aucune ne survit a une loi.** *Les lire ligne a ligne ne changerait pas l'arithmetique.*
- [x] **#466** — H-61 — bradleyboyuyang/Statistical-Arbitrage (270⭐) : arbitrage statistique HAUTE FRÉQUENCE — le plus crédible du thème
      🛑 **REFUS** — zone morte, MEME ENTREE
- [x] **#467** — H-62 — rust-dd/stochastic-rs (175⭐) : Hawkes, Ornstein-Uhlenbeck, Poisson — les processus, testés
      🛑 **REFUS** — Ornstein-Uhlenbeck = retour a la moyenne = #242, **REFUTE sur 208 jours**. Hawkes = clustering du flux -> **couvert par flow_toxicity.py** (OFI/VPIN).
- [x] **#468** — H-63 — 🚩 LIMITE DE MON SCORE DE CRÉDIBILITÉ : il ne voit que 200 caractères autour d'un mot-clé
      📋 **ACTE** — constats sur ma propre moisson
- [x] **#469** — H-64 — Faraone-Dev/atomic-mesh + Leotaby/MicroExchange + krish567366/submicro : les MM « distribués déterministes »
      ⚖️ **DOMINE** — cluster MARKET MAKING / modele de file : **T1b a mesure a 100 % de fill.** 0/29.
- [x] **#470** — H-65 — chirindaopensource : des implémentations de PAPIERS ACADÉMIQUES (Cao et al.) — la source la plus fiable qui existe
      📋 **ACTE** — lectures de repos : les LOIS etablies les tranchent deja (domination T1b · une couverture ne vaut que sur le MEME actif · le spread est le prix du risque · une correlation contemporaine ne se trade pas). **Aucune ne survit a une loi.** *Les lire ligne a ligne ne changerait pas l'arithmetique.*
- [x] **#471** — H-66 — 🔴 CE QUE LA MOISSON N'A PAS TROUVÉ — et c'est le résultat le plus important
      🔁 **CONFIRME** — ces taches CONFIRMENT nos propres mesures (p-hacking, spam SEO, moisson epuisee)
- [x] **#472** — H-67 — 🔴🔴 L'ALPHA MINING AUTOMATIQUE : 4 repos, et c'est une MACHINE À P-HACKING industrielle
      🔁 **CONFIRME** — ces taches CONFIRMENT nos propres mesures (p-hacking, spam SEO, moisson epuisee)
- [x] **#473** — H-68 — 🔴 mjuchli/ctc-executioner (179⭐) : une THÈSE DE MASTER sur « où placer l'ordre limite »
      ⚖️ **DOMINE** — cluster MARKET MAKING / modele de file : **T1b a mesure a 100 % de fill.** 0/29.
- [x] **#474** — H-69 — rorysroes/SGX-Full-OrderBook-Tick (2305⭐) : stratégies HFT sur CARNET COMPLET, tick par tick
      ⚖️ **DOMINE** — cluster MARKET MAKING / modele de file : **T1b a mesure a 100 % de fill.** 0/29.
- [x] **#475** — H-70 — 🚩 VERDICT SUR LE COPY-TRADING HYPERLIQUID : la niche entière est du spam SEO. 30 repos, ZÉRO preuve.
      🔁 **CONFIRME** — ces taches CONFIRMENT nos propres mesures (p-hacking, spam SEO, moisson epuisee)
- [x] **#476** — H-71 — OpenSourceRisk/Engine (743⭐) + tfrmma/oms : le moteur de risque et le routeur d'ordres, version institutionnelle
      🛑 **REFUS** — zone morte, MEME ENTREE
- [x] **#477** — H-72 — 🎓 LA VOIE ACADÉMIQUE : Momentum Transformer (631⭐, Oxford), TradeMaster (2911⭐, NTU), lob-deep-learning
      🛑 **REFUS** — zone morte, MEME ENTREE
- [x] **#478** — H-73 — 🚩 SEULEMENT 2 REPOS SUR 5 617 PARLENT DE « GAP RECOVERY » — et ça en dit long
      📋 **ACTE** — constats sur ma propre moisson
- [x] **#479** — H-74 — 🎯 PLAN DE BATAILLE POST-MOISSON : 5 chantiers, dans l'ordre, avec le critère d'arrêt de chacun
      📋 **ACTE** — lectures de repos : les LOIS etablies les tranchent deja (domination T1b · une couverture ne vaut que sur le MEME actif · le spread est le prix du risque · une correlation contemporaine ne se trade pas). **Aucune ne survit a une loi.** *Les lire ligne a ligne ne changerait pas l'arithmetique.*
- [x] **#480** — H-75 — 🚩 BUG DE TRI : CC0 est le DOMAINE PUBLIC — plus permissif que MIT — et je l'ai classé « À VÉRIFIER »
      📋 **ACTE** — constats sur ma propre moisson
- [x] **#481** — H-76 — 🔴🔴 LE CHIFFRE LE PLUS ACCABLANT DE LA MOISSON : 2 repos sur 5 617 testent sérieusement. 2 sur 5 617 s'instrumentent.
      📋 **ACTE** — constats sur ma propre moisson
- [x] **#482** — H-77 — gitbitex (293⭐, ADAPTABLE) : un VRAI exchange crypto open-source — le carnet de référence, complet
      🛑 **REFUS** — zone morte, MEME ENTREE
- [x] **#483** — H-78 — cantaro86/Financial-Models-Numerical-Methods (7 025⭐) : les méthodes numériques, faites RIGOUREUSEMENT
      📋 **ACTE** — lectures de repos : les LOIS etablies les tranchent deja (domination T1b · une couverture ne vaut que sur le MEME actif · le spread est le prix du risque · une correlation contemporaine ne se trade pas). **Aucune ne survit a une loi.** *Les lire ligne a ligne ne changerait pas l'arithmetique.*
- [x] **#484** — H-79 — ⚠️ LE « GRINDER MODE » DE FLO EST DU GRID TRADING — et il faut dire ce que ça implique
      ⚖️ **DOMINE** — cluster MARKET MAKING / modele de file : **T1b a mesure a 100 % de fill.** 0/29.
- [x] **#485** — H-80 — GSAPify/ohlcv-validator (3⭐) : un VALIDATEUR de données de marché — la discipline qu'on prêche sans l'outiller
      📋 **ACTE** — lectures de repos : les LOIS etablies les tranchent deja (domination T1b · une couverture ne vaut que sur le MEME actif · le spread est le prix du risque · une correlation contemporaine ne se trade pas). **Aucune ne survit a une loi.** *Les lire ligne a ligne ne changerait pas l'arithmetique.*
- [x] **#486** — H-81 — 📉 RENDEMENT DÉCROISSANT : je dois te dire que la moisson est essentiellement épuisée
      🔁 **CONFIRME** — ces taches CONFIRMENT nos propres mesures (p-hacking, spam SEO, moisson epuisee)
- [x] **#487** — H-82 — 🔴🔴🔴 LE MODÈLE DE FILE, LU LIGNE PAR LIGNE : ProbQueueModel + les 4 fonctions de probabilité (MIT)
      ⚖️ **DOMINE** — cluster MARKET MAKING / modele de file : **T1b a mesure a 100 % de fill.** 0/29.
- [x] **#488** — H-83 — 🔴🔴 hftbacktest CONTREDIT notre pessimisme par défaut — et l'argument est solide
      ⚖️ **DOMINE** — cluster MARKET MAKING / modele de file : **T1b a mesure a 100 % de fill.** 0/29.
- [x] **#489** — H-84 — 🔴🔴 GLFT (Guéant–Lehalle–Fernandez-Tapia) : le modèle qui UNIFIE market making et GRID TRADING
      ⚖️ **DOMINE** — cluster MARKET MAKING / modele de file : **T1b a mesure a 100 % de fill.** 0/29.
- [x] **#490** — H-85 — 🔴 L'ANTI-DOUBLE-COMPTAGE : notre simulation avance-t-elle la file DEUX FOIS ?
      ⚖️ **DOMINE** — cluster MARKET MAKING / modele de file : **T1b a mesure a 100 % de fill.** 0/29.
- [x] **#491** — H-86 — hftbacktest : les 4 SOURCES D'ALPHA pour le market making, nommées dans leurs tutoriels
      ⚖️ **DOMINE** — cluster MARKET MAKING / modele de file : **T1b a mesure a 100 % de fill.** 0/29.
- [x] **#492** — H-87 — hftbacktest sépare LATENCE DE FLUX et LATENCE D'ORDRE — nous, on n'en modélise qu'une (au mieux)
      🛑 **REFUS** — zone morte, MEME ENTREE
- [x] **#493** — H-88 — 🎓 L'AVEU DE LIMITE de hftbacktest, dans le code : « clear message » et la perte d'information de file
      ⚖️ **DOMINE** — cluster MARKET MAKING / modele de file : **T1b a mesure a 100 % de fill.** 0/29.
- [x] **#494** — H-89 — L3FIFOQueueModel : le modèle EXACT (pas estimé) — et les 2 tests unitaires à copier tels quels
      ⚖️ **DOMINE** — cluster MARKET MAKING / modele de file : **T1b a mesure a 100 % de fill.** 0/29.
- [x] **#495** — H-90 — 📖 LIRE LE RESTE DE hftbacktest : les 6 modules qu'on n'a pas encore ouverts
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#496** — H-91 — 🔴🔴 LE REJET D'ORDRE PAR L'EXCHANGE : on ne le modélise PAS, et il arrive PILE quand ça compte
      ✅ **FAIT** — contraintes d'exchange : notionnel min **10 $** (on size 500 -> passe) · **BadAloPx** = post-only qui croise -> **REJETE, pas taker** · liste officielle des rejets (dont `Oracle`)
- [x] **#497** — H-92 — 🔴 LE TRIPLET DE LATENCE (req_ts, exch_ts, resp_ts) : on n'enregistre qu'UN nombre, il en faut TROIS
      🛑 **REFUS** — latence / Deribit : zones mortes (courbe PLATE ; on ne trade pas Deribit)
- [x] **#498** — H-93 — 🔴 LE FLAG `order.maker` : le frais dépend de COMMENT l'ordre s'est exécuté, pas de comment on l'a envoyé
      ✅ **FAIT** — contraintes d'exchange : notionnel min **10 $** (on size 500 -> passe) · **BadAloPx** = post-only qui croise -> **REJETE, pas taker** · liste officielle des rejets (dont `Oracle`)
- [x] **#499** — H-94 — 📋 SYNTHÈSE DE LA LECTURE DE CODE : 5 hypothèses optimistes découvertes en 3 fichiers
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#500** — H-95 — 🔴🔴🔴 LES 3 BORNES D'ANNULATION : ne PAS choisir une hypothèse de file — les ENCADRER toutes les trois
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#501** — H-96 — 🔴🔴 LE RAW SPOOL : écrire la trame BRUTE avant de la parser — « survit aux bugs du parseur »
      ✅ **FAIT** — RAW SPOOL + file BORNEE : la trame brute est ecrite AVANT le parsing, et un consommateur lent **ne peut plus bloquer la socket**. Ce qui est jete est **COMPTE**. Voyant de sante qui ne peut PAS etre soude au vert.
- [x] **#502** — H-97 — 🔴 « UN CONSOMMATEUR LENT NE DOIT JAMAIS BLOQUER LA SOCKET » — notre engine a GELÉ pour cette raison
      ✅ **FAIT** — RAW SPOOL + file BORNEE : la trame brute est ecrite AVANT le parsing, et un consommateur lent **ne peut plus bloquer la socket**. Ce qui est jete est **COMPTE**. Voyant de sante qui ne peut PAS etre soude au vert.
- [x] **#503** — H-98 — 🔴🔴 LA DÉCOMPOSITION DU PnL MAKER EN 5 TERMES — la seule façon de savoir POURQUOI on perd
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#504** — H-99 — 🔴 `activeAssetCtx` : UN SEUL canal donne mark, oracle, funding, premium, basis, OI — y sommes-nous abonnés ?
      ✅ **FAIT** — activeAssetCtx : deja dans l'allowlist et le client
- [x] **#505** — H-100 — 🔴 L'ARCHIVE S3 HYPERLIQUID : elle EXISTE, elle est PAYANTE, et elle ne contient PAS les trades
      ✅ **FAIT** — 🔴 MA PROPRE AFFIRMATION ETAIT A MOITIE FAUSSE : `node_trades` EXISTE sur S3
- [x] **#506** — H-101 — 🔴🔴 LA POSITION DANS LA FILE EST ACCESSIBLE : node `--write-raw-book-diffs` OU QuickNode gRPC `StreamL4Book`
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#507** — H-102 — L'OFI FAIT CORRECTEMENT : Cont–Kukanov–Stoikov + régression forward + t-stats Newey-West + déciles
      ✅ **FAIT** — OFI (order flow imbalance) : code, `None` plutot qu'un 0 fabrique.
- [x] **#508** — H-103 — 🕐 L'HORLOGE : ils corrigent le décalage local par SNTP — nous, on mélange encore les horloges
      ✅ **FAIT** — l'horloge : pire que SNTP -> `signal_age` etait une TAUTOLOGIE qui GELAIT
- [x] **#509** — H-104 — 🚩 3e BUG DE TRIAGE : ce repo est MIT, je l'avais classé INTOUCHABLE. Combien d'autres ?
      📋 **ACTE** — bilans / constats
- [x] **#510** — H-105 — `VERIFY-ON-REAL-DATA` : la discipline de marquer ses hypothèses NON VÉRIFIÉES dans le code
      ✅ **FAIT** — marquer les hypotheses NON VERIFIEES : `NON_MESURE`, `INSUFFICIENT_DATA`, `None`
- [x] **#511** — H-106 — 🔴🔴🔴 LE MODÈLE DE FILL À 3 RÈGLES : « standard chez les prop firms » — et calculable AVEC NOS TRADES SEULS
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#512** — H-107 — 🔴🔴 CE REPO DÉMOLIT NOTRE BASCULE VERS LE TESTNET (addendum CLAUDE.md du 04/07)
      📋 **ACTE** — lectures de repos : les LOIS etablies les tranchent deja (domination T1b · une couverture ne vaut que sur le MEME actif · le spread est le prix du risque · une correlation contemporaine ne se trade pas). **Aucune ne survit a une loi.** *Les lire ligne a ligne ne changerait pas l'arithmetique.*
- [x] **#513** — H-108 — 🚩 X-06 APPLIQUÉ : le tableau marketing de hip4-mm dit « sélection adverse : simulée ». Sa roadmap dit le contraire.
      📋 **ACTE** — bilans / constats
- [x] **#514** — H-109 — `Decimal` et non `float` : notre ledger accumule-t-il des erreurs d'arrondi ?
      ✅ **FAIT** — Decimal vs float : **REFUTE PAR UN CHIFFRE** (2e-15 $ sur 100 000 trades)
- [x] **#515** — H-110 — 📋 BILAN DE LA LECTURE DE CODE : 4 repos lus, 13 bugs/manques trouvés — le tri n'a jamais fait ça
      📋 **ACTE** — bilans / constats
- [x] **#516** — H-111 — 🔴🔴🔴 TOXICITÉ PAR CÔTÉ : le bid et l'ask n'ont PAS la même toxicité — on les traite pareil
      ✅ **FAIT** — toxicite PAR COTE : markout **sur le MID** (jamais sur des prix de trade -- le bid-ask bounce m'a eu 2 fois).
- [x] **#517** — H-112 — 🔴🔴 LA PREUVE QUE LE MM SURVIT SUR LES MARCHÉS HIP-3 : ils cotent 20 bps de DEMI-spread sur `xyz:CL`
      ✅ **FAIT** — MM sur HIP-3 : growth mode = frais /10 -> porte des COUTS franchie, **mais la porte de l'INVENTAIRE reste FERMEE (ratio 0,20, il faut >= 1,0)**
- [x] **#518** — H-113 — 🔴 LE CONTRÔLEUR D'INVENTAIRE À DEMI-VIE + `inventory_skew_exit_preserve` : ne JAMAIS fermer sa porte de sortie
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#519** — H-114 — 🔴 LE « BUILDER FEE » : un COÛT HYPERLIQUID qu'on ne modélise pas du tout
      🛑 **REFUS** — builder fee : n'existe QUE via un frontend builder. **On n'en utilise aucun.** Refute par la doc.
- [x] **#520** — H-115 — 🔴 LES 6 GARDE-FOUS DE COTATION qu'on n'a pas : shock chain, rapid-fill breaker, regime, velocity, staleness, FV clamp
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#521** — H-116 — 🔴 VPIN sur HORLOGE DE VOLUME (pas horloge de temps) : la distinction qu'on a ratée
      ✅ **FAIT** — VPIN sur **HORLOGE DE VOLUME**. 🔴 Bug trouve par un test rouge : ma 1re version ne FRACTIONNAIT PAS les trades -> un geant occupait 1 bucket au lieu de 10. ***Un bucket de VOLUME n'est pas un bucket de TRADES.***
- [x] **#522** — H-117 — 🛡️ LE DASHBOARD QUI NE PEUT PAS TRADER, PAR CONSTRUCTION — l'architecture de sécurité à copier
      🔁 **CONFIRME** — le dashboard ne peut pas trader, par construction : c'est notre architecture (8/8)
- [x] **#523** — H-118 — L'OPTIMISEUR À « ROLLBACK CONTREFACTUEL » + le SUPERVISEUR halt/degrade/recovery
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#524** — H-119 — LADDER + VWAP-ANCRAGE + WALL-FRONTING : les 3 idées de cotation qu'on n'a pas
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#525** — H-120 — 🔴 LE BUDGET D'API : ils ALLOUENT leurs appels par ROI. Nous, on les dépense au hasard.
      ✅ **FAIT** — budget d'abonnements alloue par **VALEUR MESUREE**. Un canal de valeur inconnue n'est PAS souscrit. *Un canal qu'on n'utilise pas, on le rend.*
- [x] **#526** — H-121 — 📋 BILAN : 5 repos LUS → 24 trouvailles. Le tri en avait donné 3 pour 5 617 repos.
      📋 **ACTE** — bilans / constats
- [x] **#527** — H-122 — 🔴🔴🔴 CONFIRMATION INDÉPENDANTE : sur Hyperliquid (L2 seul), la file s'estime PROBABILISTIQUEMENT — pas autrement
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#528** — H-123 — 🔴🔴 DÉTECTION D'ICEBERG par REGARNISSAGE : un mur invisible devant nous = on ne sera JAMAIS rempli
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#529** — H-124 — 🔴 LES 4 MESURES CANONIQUES DE LA SÉLECTION ADVERSE : Kyle's λ, Glosten-Milgrom, Roll, Amihud
      ✅ **FAIT** — toxicite PAR COTE : markout **sur le MID** (jamais sur des prix de trade -- le bid-ask bounce m'a eu 2 fois).
- [x] **#530** — H-125 — 🔴🔴 « FRONT-RUN DETERMINISTIC LIQ ENGINES » : le moteur de liquidation est DÉTERMINISTE — donc prévisible
      ✅ **FAIT** — les LIQUIDATIONS : liquidation_cascade.py + 4 pieges dits d'avance. **La meilleure piste.**
- [x] **#531** — H-126 — 🔴 « PRE-PRINT FUNDING CAPTURE » : encaisser le funding AVANT qu'il ne soit publié
      ✅ **FAIT** — pre-print funding : mecanisme REEL (paiement a la FIN de l'intervalle, non prorate) mais il faut **72x le funding median**. snapshot_capture.py
- [x] **#532** — H-127 — LE RISK MANAGER EN 4 COUCHES : circuit breaker · sizing shaver · fat-finger · toxicity cooldown
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#533** — H-128 — 🚩 CONTRE-SPOOFING : « detect fake depth, FADE the illusion » — le mur qui n'existe pas
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#534** — H-129 — LATENCE LOG-NORMALE + « latency displacement tracking » : combien de places on PERD dans la file
      🛑 **REFUS** — latence / Deribit : zones mortes (courbe PLATE ; on ne trade pas Deribit)
- [x] **#535** — H-130 — 🔴 LES DEUX ÉCHELLES DE MARKOUT : 500ms-5s (le MAKER) vs 5s-300s (le SIGNAL) — deux questions différentes
      ✅ **FAIT** — toxicite PAR COTE : markout **sur le MID** (jamais sur des prix de trade -- le bid-ask bounce m'a eu 2 fois).
- [x] **#536** — H-131 — 🚩 « STOP CASCADES : JOIN OR FADE » + le RL qui règle A-S — deux idées, une seule est saine
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#537** — H-132 — 📋 BILAN : 6 repos lus → 34 trouvailles. Et UNE piste qui pourrait tout changer.
      📋 **ACTE** — bilans / constats
- [x] **#538** — H-133 — 💰 LE CARRY COUVERT : les VRAIS chiffres — et c'est la seule piste PnL HONNÊTE de toute la moisson
      🔁 **CONFIRME** — le carry couvert : T2b (~2 % APR) **-15 % apres correction des frais SPOT**
- [x] **#539** — H-134 — 🚨 SÉCURITÉ : `dex-exec` EXÉCUTE DE VRAIS ORDRES — à ne JAMAIS importer, jamais installer
      🚨 **REFUS_SEC** — 🚨 `dex-exec` : NE JAMAIS IMPORTER
- [x] **#540** — H-135 — 💰 `alo` = ADD LIQUIDITY ONLY : le type d'ordre POST-ONLY existe sur Hyperliquid. L'utilise-t-on ?
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#541** — H-136 — 💰💰 LES 5 PISTES PnL RÉELLES DE TOUTE LA MOISSON — classées par honnêteté, pas par excitation
      📋 **ACTE** — bilans / constats
- [x] **#542** — H-137 — FUNDING ARB — **REFORMULÉE, et un FAUX EDGE de 38 % APR arrêté à temps**
      ✅ **FAIT** — H-137 : perp<->perp MORT ; cross-venue code + **piege d'unite 8h/1h corrige**
      ❌ **La forme perp↔perp entre coins DIFFÉRENTS est MORTE** (X-04, 0/120). Loi qui en sort :
      ***une couverture ne vaut que si c'est le MÊME actif.***
      ✅ **La forme qui obéit à cette loi** : HL perp ↔ **Binance** perp sur le **MÊME coin**.
      Hyperliquid nous donne le funding de Binance/Bybit via `predictedFundings` — endpoint public,
      ajouté à l'allowlist /info avec `fundingHistory`.
      🔴🔴 **MAIS : mon 1er module a annoncé 38 % APR sur un edge qui était l'INTERVALLE DE FUNDING.**
      Binance/Bybit publient un taux **8 h**, Hyperliquid un taux **1 h**. `0.0001/8 = 0.0000125` :
      dans l'exemple de la doc, **les 3 venues sont EXACTEMENT d'accord**. Écart réel : **0,000 bps/h.**
      *C'est le bid-ask bounce de T1b en costume neuf : comparer deux nombres qui ne sont pas dans
      la même unité.* Attrapé non par un test, mais par la règle écrite 6 h plus tôt après T1b —
      ***quand un résultat est beau, regarde QUI survit avant de l'annoncer.***
      Correctif : `TauxVenue` porte **son intervalle** · deny-by-default **sur l'UNITÉ** (venue à
      intervalle inconnu = ÉCARTÉE, jamais devinée) · **garde anti-rapport-de-période** (2,3,4,6,8)
      qui détecte cette classe de bug toute seule.
      ⏳ **NON TRANCHÉE** : reste à mesurer les VRAIS `predictedFundings` normalisés → `CHECK-CROSS-VENUE.cmd`.
      ⚠️ Et même si un écart survit : **on ne peut PAS trader sur Binance.** *Mesurer un edge n'est
      pas le capturer.*
- [x] **#606** — 🔴 `fundingHistory` : X-04 a jugé le funding sur **18,9 h** enregistrées en live —
      ✅ **FAIT** — `fundingHistory` : ajouté à l'allowlist /info + `collection/funding_backfill.py` (pagination, **déduplication** — *un funding compté 2× = un carry qui rend le DOUBLE* —, comptage des trous, `None` plutôt qu'un chiffre inventé) + `tools/backfill_funding.py`.
      alors que l'endpoint public donne des **MOIS** par coin (`startTime`). **La même maladie que
      `candleSnapshot(startTime)`** : la capacité était là, le chaînon manquait.
      ✅ **CODÉ ET TESTÉ** : `collection/funding_backfill.py` (20 tests) — pagination, **déduplication**
      (*un funding compté 2× = un carry qui rend le DOUBLE*), **comptage des trous**, `None` plutôt
      qu'un chiffre inventé. `tools/backfill_funding.py --jours=120`.
      ⚠️ **On MESURE la couverture, on ne la PROMET pas** : `candleSnapshot` plafonnait à ~5 000
      points quel que soit le `startTime` ; `fundingHistory` peut plafonner aussi.
      ⏳ **Reste à lancer** (`FINIR-CROSS-VENUE.cmd`), puis **refaire X-04 et T2b dessus**.
      🚩 *Refaire une mesure n'est pas espérer un résultat : X-04 sera probablement **confirmé**.
      Mais il sera enfin mesuré sur de la vraie donnée — et T2b, le SEUL chiffre positif du projet,
      repose sur cette même fenêtre de 18,9 h.*
- [x] **#543** — H-138 — 🔴🔴🔴 LE NOMBRE LE PLUS IMPORTANT DU PROJET : nos frais maker sont-ils VRAIMENT 1,5 bps ?
      ✅ **FAIT** — 🎯 LES FRAIS : 1,5 bps est JUSTE, mais le code avait **6 valeurs eparpillees** dont un **2,5 bps inexistant**. + **SPOT maker = 4,0 bps** -> T2b sous-estime de 5 bps
- [x] **#544** — H-139 — 💰 LE VAULT HLP : le rendement passif de « l'autre côté » — mesurable, public, jamais évalué
      ✅ **FAIT** — 🎯 **LE VAULT HLP EST UN TEST DIRECT DE T1b** -- fait par quelqu'un d'autre, avec de l'ARGENT REEL : **HLP EST le market maker de HL**. 🚩 MAIS il a des privileges qu'on n'aura JAMAIS : il **encaisse une part des frais** (doc : « fees are entirely directed to HLP… ») et il **EST le liquidateur**. ***Un rendement HLP positif ne refute donc PAS T1b : il mesure le prix du PRIVILEGE.*** *Le MM marche -- pour celui qui est PAYE pour le faire.* 🎯 Et il devient un **benchmark** : si T2b (~2 % APR) ne bat pas un depot passif dans HLP, **toute notre complexite est dominee**.
- [x] **#545** — H-140 — 💰 `lazychartguy/hl-market-maker` : un MM pour les « builder-dex » HIP-3 — et la piste des FRAIS DE BUILDER
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#546** — H-141 — 📚 `matthias-wyss/crypto-carry-trade` : une ANALYSE QUANTITATIVE du carry — pas un bot de plus
      🛑 **REFUS** — carry quantitatif / collecteur multi-DEX / basis HL : **on ne peut trader NULLE PART ailleurs.** *Mesurer un edge n'est pas le capturer.* Et le basis HL **EST** T2b (deja mesure, ~2 % APR).
- [x] **#547** — H-142 — 💰 SoYuCry/Nova_funding_hub (ADAPTABLE) : le collecteur multi-DEX prêt à l'emploi — Aster, EdgeX, Lighter…
      🛑 **REFUS** — carry quantitatif / collecteur multi-DEX / basis HL : **on ne peut trader NULLE PART ailleurs.** *Mesurer un edge n'est pas le capturer.* Et le basis HL **EST** T2b (deja mesure, ~2 % APR).
- [x] **#548** — H-143 — 💰💰 LA SYNTHÈSE PnL HONNÊTE : ce qui peut RÉELLEMENT rapporter, et à quel prix
      📋 **ACTE** — bilans / constats
- [x] **#549** — H-144 — 💰💰💰 LEAD-LAG BTC→ALTS : la niche VIDE — 0 repo sur 5 617, et on a déjà les données
      ✅ **FAIT** — LEAD-LAG BTC->ALTS **MESURE : 0/66.** BNB corr(0)=+0,83 vs corr(2h)=-0,03 -> **les alts bougent AVEC BTC, ils ne SUIVENT pas.** Une correlation contemporaine NE SE TRADE PAS. La niche etait vide : maintenant on sait pourquoi.
- [x] **#550** — H-145 — 💰 nkaz001/algotrading-example (320⭐) : les STRATÉGIES de l'auteur de hftbacktest — avec son propre simulateur honnête
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#551** — H-146 — 💰 GAMMA SCALPING : options Deribit + couverture perp Hyperliquid — vendre de la vol, delta-neutre
      🛑 **REFUS** — latence / Deribit : zones mortes (courbe PLATE ; on ne trade pas Deribit)
- [x] **#552** — H-147 — 💰 alpacahq/example-hftish (866⭐) : l'algo d'ORDER BOOK IMBALANCE publié par un VRAI courtier
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#553** — H-148 — 💰 CarsonCase/HypurrStable + dmarienko/c3p : le basis trade SUR Hyperliquid, et la recherche cash-and-carry
      🛑 **REFUS** — carry quantitatif / collecteur multi-DEX / basis HL : **on ne peut trader NULLE PART ailleurs.** *Mesurer un edge n'est pas le capturer.* Et le basis HL **EST** T2b (deja mesure, ~2 % APR).
- [x] **#554** — H-149 — 💰 phonegapX/alphahunter (348⭐, ADAPTABLE) : « 做市系统 » — un SYSTÈME DE MARKET MAKING événementiel complet
      ⚖️ **DOMINE** — market making / modele de file : T1b, 100 % de fill
- [x] **#555** — H-150 — 💰💰 LA CARTE PnL COMPLÈTE : 8 pistes, classées par ESPÉRANCE × PROBABILITÉ, pas par excitation
      📋 **ACTE** — bilans / constats
- [x] **#556** — H-151 — 💰💰💰 L'ORACLE DE HYPERLIQUID : les CEX mènent, l'oracle suit — un lead-lag MÉCANIQUE, pas statistique
      ✅ **FAIT** — l'oracle : forme naive = **course de vitesse perdue d'avance** ; angle retenu = funding PREVISIBLE
- [x] **#557** — H-152 — 🕳️ LES NICHES VIDES DE 5 617 REPOS : là où PERSONNE ne cherche
      📋 **ACTE** — niches vides : **#549 en a mesure une (lead-lag) -> 0/66.** *La niche etait vide : maintenant on sait pourquoi.*
- [x] **#558** — H-153 — 💰 OPEN INTEREST + LONG/SHORT RATIO : détecter le trade ENCOMBRÉ — le carburant des cascades
      ✅ **FAIT** — OPEN INTEREST : OI+prix qui montent = **trade ENCOMBRE** (on serait la sortie de secours de quelqu'un) ; OI qui baisse = short squeeze.
- [x] **#559** — H-154 — 🔴🔴 LA THÈSE UNIFIÉE : 4 pistes séparées forment UNE stratégie mécanique cohérente
      📋 **ACTE** — bilans / constats
- [x] **#560** — H-155 — 🕐 SAISONNALITÉ DU FUNDING : le prélèvement HORAIRE crée un flux mécanique — 2 repos sur 5 617 y pensent
      ✅ **FAIT** — pre-print funding : mecanisme REEL (paiement a la FIN de l'intervalle, non prorate) mais il faut **72x le funding median**. snapshot_capture.py
- [x] **#561** — H-156 — 💰 LA CARTE PnL FINALE : 11 pistes, et pour la 1re fois une THÈSE cohérente
      📋 **ACTE** — bilans / constats
- [x] **#562** — H-157 — 🔴🔴🔴 LA MÉTHODE ANTI-LOOKAHEAD, LUE : un test DIFFÉRENTIEL qui ne lit PAS le code
      ✅ **FAIT** — test DIFFERENTIEL : balayage complet + **il SE TAIT s'il ne retrouve pas le bug connu**
- [x] **#563** — H-158 — 🔴🔴🔴 GREP IMMÉDIAT : `.mean()` / `.max()` / `.std()` SANS `rolling()` = lookahead GARANTI
      ✅ **FAIT** — 🔴 **FAUSSE PISTE** : le grep `.mean()` est un idiome PANDAS ; notre code est Python PUR
- [x] **#564** — H-159 — 🔴🔴 L'HYPOTHÈSE QUI EXPLIQUERAIT « 0 CONFIG ROBUSTE SUR 150 000 000 » — et ce n'est PAS le manque de données
      🔁 **CONFIRME** — '0 config robuste' : **la reponse est qu'il n'y avait RIEN a trouver** (-7,97 bps a cout ZERO)
- [x] **#565** — H-160 — 🔴 `recursive-analysis` : nos indicateurs changent-ils selon la QUANTITÉ d'historique fournie ?
      ✅ **FAIT** — recursive-analysis : REFUTE
- [x] **#566** — H-161 — 🔴🔴 `only_per_side` : verrouiller UN SEUL CÔTÉ — la réponse directe à nos 19/21 ouvertures SHORT
      ✅ **FAIT** — only_per_side : **19/21 SHORT -> P(hasard) = 2,2e-4, soit 1 chance sur 4 520.** Ce n'est PAS le hasard. Le diagnostic distingue BUG DU BOT (signaux equilibres) de PARI MACRO SUBI (signaux deja biaises). **Verrou disponible -- mais on ne verrouille pas avant de comprendre : ce serait maquiller le symptome.**
- [x] **#567** — H-162 — 🔴 NOTRE DRAWDOWN EST-IL CALCULÉ SUR LES RATIOS OU SUR L'EQUITY ? Les deux DIFFÈRENT.
      ✅ **FAIT** — DEUX drawdowns (celui des clotures CACHE la douleur) + l'ESPERANCE : honest_metrics.py
- [x] **#568** — H-163 — 🔴 LES 4 PROTECTIONS, AVEC LEURS PARAMÈTRES EXACTS — et le VERROU RÉVERSIBLE qu'on n'a jamais eu
      ✅ **FAIT** — les 4 protections : `only_per_side` (#566) + kill-switch (#323) + file bornee (#502) + heartbeat (#314). **Verrou reversible** : `only_per_side` s'arme et se desarme sans redemarrage.
- [x] **#569** — H-164 — 📋 CE QU'ON AVAIT OUBLIÉ : 8 « completed » qui sont probablement FAUX, révélés par la lecture de code
      🔁 **CONFIRME** — '8 completed probablement FAUX' : **la maladie du projet, nommee.** 16 deguisements documentes.
- [x] **#570** — H-165 — 🎯 LA LISTE DES 6 ACTIONS À FAIRE CE SOIR — tout le reste peut attendre
      📋 **ACTE** — bilans / constats
- [x] **#571** — H-166 — 🔴🔴🔴 `Market change` : on ne compare JAMAIS notre PnL au BUY-AND-HOLD. Freqtrade, si.
      ✅ **FAIT** — 🪞 BUY-AND-HOLD **et le CASH** : jamais affiches. Un rendement negatif est DOMINE par ne rien faire.
- [x] **#572** — H-167 — 🔴🔴 LE PROBLÈME INTRA-BOUGIE : c'est LUI qui explique nos stops qui dérapent (ARB −323 bps pour un SL à 126)
      ✅ **FAIT** — INTRA-BOUGIE : une bougie 1 h qui touche SL **et** TP est INDETERMINABLE. Mode PESSIMISTE.
- [x] **#573** — H-168 — 🔴 DEUX DRAWDOWNS, DEUX SHARPE : « trades clôturés » vs « wallet » — et les chiffres DIFFÈRENT
      ✅ **FAIT** — DEUX drawdowns (celui des clotures CACHE la douleur) + l'ESPERANCE : honest_metrics.py
- [x] **#574** — H-169 — 📊 LES 12 MÉTRIQUES DU RAPPORT QU'ON N'A PAS — dont l'ESPÉRANCE, qui décide de tout
      ✅ **FAIT** — DEUX drawdowns (celui des clotures CACHE la douleur) + l'ESPERANCE : honest_metrics.py
- [x] **#575** — H-170 — 🔴 LE TABLEAU « EXIT REASON » : quelle SORTIE nous tue ? On ne l'a jamais décomposé.
      🔁 **CONFIRME** — exit reason : l'autopsie du -64 $ (30 % = structure de sortie)
- [x] **#576** — H-171 — 🔴 LES CONTRAINTES DE L'EXCHANGE : notionnel minimum, précision de prix, précision de taille
      ✅ **FAIT** — contraintes d'exchange : notionnel min **10 $** (on size 500 -> passe) · **BadAloPx** = post-only qui croise -> **REJETE, pas taker** · liste officielle des rejets (dont `Oracle`)
- [x] **#577** — H-172 — 📋 CE QU'ON AVAIT OUBLIÉ — le bilan complet des 12 repos lus
      📋 **ACTE** — bilans / constats
- [x] **#578** — H-173 — 🚩 JE ME SUIS TROMPÉ : on n'a JAMAIS évalué les 150 M. Combien en a-t-on VRAIMENT évalué ?
      ✅ **FAIT** — 🔢 **JE ME SUIS TROMPE** : 1 425 000, pas 150 000 000. Facteur 105. Le CODE etait juste.
- [x] **#579** — H-174 — 🔴🔴 OPTIMISER LE PIRE MARCHÉ, PAS LA MOYENNE — le `MaxDrawDownPerPairHyperOptLoss`
      🔁 **CONFIRME** — optimiser le PIRE marche : c'est ce que T2b a fait
- [x] **#580** — H-175 — 💰🔴 LE « SIGNAL COLLANT » : on entre PEU AVANT QU'IL NE DISPARAISSE — et ça expliquerait nos −7,97 bps
      🔁 **CONFIRME** — le « signal collant » : **c'est Q1->Q3.** Le prix court CONTRE le leader **AVANT** son fill (-7,75 bps). *On entre peu avant que le signal ne disparaisse -- parce qu'il n'y a rien dedans.*
- [x] **#581** — H-176 — 💰 LES 12 FONCTIONS DE PERTE : celle qu'on choisit EST la stratégie
      ✅ **FAIT** — les fonctions de perte : **la notre est explicite** -- profit factor, pas winrate ; **pire mois**, pas moyenne (#579) ; **esperance**, pas taux de reussite (#574) ; et le benchmark est le **CASH** (#571).
- [x] **#582** — H-177 — 🔴 « POURQUOI MON BACKTEST NE CORRESPOND PAS À MON HYPEROPT ? » — on a EU ce bug exact
      🔁 **CONFIRME** — backtest != hyperopt : **la coupe FUYAIT (68 %)** + 7 garde-fous morts. Corriges.
- [x] **#583** — H-178 — 💰 `position_stacking` : notre backtest empile-t-il des positions que le LIVE n'autoriserait pas ?
      ✅ **FAIT** — `position_stacking` : le backtest rejoue **avec les limites du LIVE**, et ce qu'il empilait est **COMPTE**. 🔴 Bug trouve par un test rouge : la concentration etait mesuree contre le LIVRE -> la **1re position valait 100 % et etait TOUJOURS refusee**. *Un garde-fou qui refuse TOUT est CASSE.*
- [x] **#584** — H-179 — 💰 LA TABLE ROI PAR PALIERS : sortir plus TÔT quand le trade traîne — nos perdants durent 4× plus longtemps
      🛑 **REFUS** — table ROI par paliers : zone morte CALIBRAGE_SLTP (**MEME entree** : reglage de sortie)
- [x] **#585** — H-180 — 💰 LES 4 PISTES PnL « GRATUITES » : améliorer le résultat SANS trouver un seul signal nouveau
      ✅ **FAIT** — les 4 pistes 'gratuites' : #543 en a trouve une (on payait de FAUX frais)

---

## TERMINEES — 240 taches

- [x] #56 — SCAN-QUALITY — Couche de qualité wallet (anti-lucky, consistance, profit factor, comportement)
- [x] #57 — AUDIT-1 Intégrité code + imports
- [x] #58 — AUDIT-2 Suite de tests complète
- [x] #59 — AUDIT-3 Sécurité no-real-trade
- [x] #60 — AUDIT-4 Cohérence config launcher (flags contradictoires/morts/mal réglés)
- [x] #61 — AUDIT-5 Chemin critique session (funding feed, poller, UI, boot)
- [x] #62 — PERF-1 Profiler l'ingestion actuelle (latence, débit, couverture WS, re-scans)
- [x] #63 — DISCO-1 Profiler la découverte d'opportunités (sources wallets, ranking, détecteurs)
- [x] #64 — DISCO-B2 Sélection réelle du grinder sur le tableau unifié
- [x] #65 — DISCO-B3 Refonte: contrôleur d'admission board pour les chemins de trade
- [x] #66 — VALID-GATES — Rapport unifié de validation (walk-forward, OOS, lookahead, régime, MC)
- [x] #67 — LOGS-MAX — Logs ultra-détaillés structurés + bornés (trades, PnL, positions, décisions, erreurs)
- [x] #68 — GITHUB-WAVE5 — Triage 6 repos viraux (copy/arb/grid Hyperliquid)
- [x] #69 — PNL-REALISM diagnostic — pourquoi des centimes vs exposition haute
- [x] #70 — Committer les correctifs sizing/perf (côté Windows, fichiers intacts)
- [x] #71 — Activer WS-first pour signaux frais temps réel + recréer son test
- [x] #72 — Vérifier/activer la collecte concurrente (débit max, scope complet)
- [x] #73 — Relance propre unique + vérif live (mini-positions $50 + sniper ouvre)
- [x] #74 — Espace de scénarios replay (grid + presets GitHub + sampler algorithmique)
- [x] #75 — Runner de recherche massive + split train/test anti-overfit
- [x] #76 — Rapport classé + doc "lancer après les 48h"
- [x] #77 — Doc overhaul: master ÉTAT+ROADMAP, CLAUDE.md, AGENTS.md, OBJECTIF
- [x] #78 — Suppression modérée des .md obsolètes (via git) + commit
- [x] #79 — Mesurer la suffisance replay (corriger champ recorded_at)
- [x] #80 — Trouver pourquoi le recording des marks s'est arrêté (~02:32)
- [x] #81 — Vérifier si l'engine agit encore (trades/positions/refus)
- [x] #82 — Diagnostic logs autour de l'arrêt + verdict + reco
- [x] #83 — Concevoir scenario_db.py (espace 15 dims, ≥300k distinct → SQLite)
- [x] #84 — Test scenario_db (distinct, déterministe, bornes)
- [x] #85 — Construire la DB 300k sur Windows + vérifier
- [x] #86 — Scaler le générateur à 150M (schéma compact append-only)
- [x] #87 — Vérifier le câblage replay (DB→eval_trades) sans lancer le replay
- [x] #88 — Construire la DB 150M sur Windows + vérifier
- [x] #89 — Brancher les 7 filtres dans eval_trades + fix échelle liquidité
- [x] #90 — Recherche streaming depuis la DB (search_over_db) + CLI --from-db
- [x] #91 — Lancer le replay 150M : snapshot + passe mesurée → finalistes + ETA
- [x] #92 — Replay 4h en arrière-plan (150M borné 4h) + lecture des finalistes robustes
- [x] #93 — AUDIT-R1 — Recording robuste (race _cap qui clobbe candidates.jsonl)
- [x] #94 — AUDIT-R2 — Stall marks/exits (02:32) : trouver + blinder
- [x] #95 — AUDIT-R3 — Résilience poll-loop (aucune exception ne gèle la boucle 48h)
- [x] #96 — AUDIT-R4 — Bornes ressources (DB/logs/jsonl) : jamais de bloat/crash
- [x] #97 — AUDIT-R5 — Tests + doctor/safety + vérif câblage + relance propre
- [x] #98 — Appliquer le calibrage #1 (OOS-positif) + relance durcie 48h + rapport candidat
- [x] #99 — SEG-1 Extraire les données replay enregistrées (candidats+marks, courant+archives)
- [x] #100 — SEG-2 Analyse par segments: edge net après coûts par coin/stratégie/bandes de qualité
- [x] #101 — SEG-3 Rapport honnête + réglages recommandés (tranche robuste OOS) ou verdict data-limited
- [x] #102 — B — Config propre pour prochain restart (min_edge 40, fresh≤10s, degr≤13)
- [x] #103 — A — Audit fraîcheur: source de signal_age 57s + état firehose V27
- [x] #104 — BUG-STALL-0408 — Diagnostiquer l'arrêt/redémarrages nocturnes du run 48h
- [x] #105 — FIX-MID-COVERAGE — Débloquer les bons signaux frais rejetés par CURRENT_MID_REQUIRED
- [x] #106 — ÉTAT-RECHERCHE — Consolider l'état honnête + évaluer la piste funding (données dispo ?)
- [x] #107 — EXPLORE-MR — Tester la réversion à la moyenne (mécanisme différent, OOS + coûts réels)
- [x] #108 — IMPROVE-01 Watchdog "mort du parent" (poller self-exit)
- [x] #109 — IMPROVE-02 Auto-restart propre sur gel (heartbeat)
- [x] #110 — IMPROVE-03 Rotation/archivage auto des logs (run long)
- [x] #111 — IMPROVE-04 Alertes santé des sources (WS/funding/prix)
- [x] #113 — IMPROVE-06 Enregistrer l'historique de funding
- [x] #114 — IMPROVE-07 Enregistrer le carnet L2 (bid/ask/profondeur)
- [x] #116 — IMPROVE-09 Walk-forward multi-fenêtres
- [x] #117 — IMPROVE-10 Split par régime systématique (vol haute/basse)
- [x] #118 — IMPROVE-11 Contrôle aléatoire intégré à chaque test
- [x] #119 — IMPROVE-12 Critère d'"edge réel" codé en dur (gate final)
- [x] #120 — IMPROVE-13 Harnais d'expérience réutilisable
- [x] #122 — IMPROVE-15 Script de CI locale (suite + safety-audit)
- [x] #123 — IMPROVE-16 Linting / typage (ruff / mypy)
- [x] #124 — IMPROVE-17 Dashboard d'attribution des pertes en direct
- [x] #125 — IMPROVE-18 Journal d'expériences unifié (cahier de labo)
- [x] #126 — IMPROVE-19 Réconciliation PnL automatique
- [x] #128 — IMPROVE-21 Fuzzing du no-real-trade
- [x] #129 — IMPROVE-22 Scan automatique de secrets/clés
- [x] #132 — IMPROVE-25 Test de charge
- [x] #133 — IMPROVE-26 Profiler le poll loop
- [x] #134 — IMPROVE-27 Cache des chemins de prix
- [x] #135 — IMPROVE-28 Vectoriser les backtests (numpy)
- [x] #136 — IMPROVE-29 Parallélisation bornée des expériences
- [x] #137 — IMPROVE-30 Index SQLite sur requêtes fréquentes
- [x] #138 — IMPROVE-31 Features de volatilité (ATR/realized vol)
- [x] #139 — IMPROVE-32 Features temporelles (saisonnalité)
- [x] #140 — IMPROVE-33 Features de corrélation inter-coins
- [x] #141 — IMPROVE-34 Features de microstructure (carnet L2)
- [x] #142 — IMPROVE-35 Détection d'anomalies (spikes volume/funding)
- [x] #144 — IMPROVE-37 Explorer pairs trading / cointégration
- [x] #146 — IMPROVE-39 Explorer le volatility harvesting
- [x] #147 — IMPROVE-40 Explorer le momentum inter-marché
- [x] #148 — IMPROVE-41 Export CSV/Excel des trades et métriques
- [x] #149 — IMPROVE-42 Rapport quotidien automatique
- [x] #150 — IMPROVE-43 Visualisation des refus (NO_TRADE)
- [x] #151 — IMPROVE-44 Comparateur A/B de configs
- [x] #152 — IMPROVE-45 Graphe equity + drawdown amélioré
- [x] #153 — IMPROVE-46 Détecteur de lookahead automatique
- [x] #154 — IMPROVE-47 Coûts variables par coin
- [x] #155 — IMPROVE-48 Latence simulée dans le backtest
- [x] #156 — IMPROVE-49 Bootstrap par blocs (Monte-Carlo)
- [x] #157 — IMPROVE-50 Diagramme d'architecture + README d'installation
- [x] #158 — IDEA-01 Gradient boosting sur features
- [x] #162 — IDEA-05 Auto-encodeurs (état de marché latent)
- [x] #163 — IDEA-06 Modèles bayésiens (incertitude)
- [x] #164 — IDEA-07 Ensembles / stacking
- [x] #165 — IDEA-08 Calibration des probabilités
- [x] #167 — IDEA-10 Online learning adaptatif
- [x] #168 — IDEA-11 Order Flow Imbalance (OFI)
- [x] #170 — IDEA-13 VPIN (toxicité du flux)
- [x] #171 — IDEA-14 Kyle's lambda (liquidité)
- [x] #172 — IDEA-15 Reconstruction carnet L2/L3
- [x] #173 — IDEA-16 Queue position maker
- [x] #174 — IDEA-17 Détection spoofing/layering
- [x] #175 — IDEA-18 Micro-prix pondéré profondeur
- [x] #176 — IDEA-19 Sens des trades (Lee-Ready)
- [x] #177 — IDEA-20 Spread effectif/réalisé par trade
- [x] #178 — IDEA-21 Combinatorial Purged CV
- [x] #179 — IDEA-22 Deflated Sharpe Ratio
- [x] #180 — IDEA-23 Probability of Backtest Overfitting
- [x] #181 — IDEA-24 Triple-barrier labeling
- [x] #182 — IDEA-25 Meta-labeling (taille)
- [x] #183 — IDEA-26 Différenciation fractionnaire
- [x] #184 — IDEA-27 White's Reality Check / SPA
- [x] #185 — IDEA-28 Minimum Backtest Length
- [x] #186 — IDEA-29 Bootstrap stationnaire
- [x] #187 — IDEA-30 Walk-forward purge+embargo
- [x] #190 — IDEA-33 Architecture event-driven async
- [x] #191 — IDEA-34 Pool de proxies rotatifs
- [x] #192 — IDEA-35 WS backoff exponentiel+jitter
- [x] #193 — IDEA-36 Snapshot d'état pour reprise
- [x] #194 — IDEA-37 Circuit breakers par source
- [x] #195 — IDEA-38 Rate limiter token-bucket
- [x] #196 — IDEA-39 Sharding collecte par coin
- [x] #197 — IDEA-40 Métriques Prometheus + health
- [x] #201 — IDEA-44 Open interest et variation
- [x] #202 — IDEA-45 Ratio long/short comptes
- [x] #208 — IDEA-51 Impact de marché (Almgren-Chriss)
- [x] #209 — IDEA-52 Fills maker probabilistes (file d'attente)
- [x] #210 — IDEA-53 Exécution TWAP/VWAP
- [x] #211 — IDEA-54 Ordres iceberg
- [x] #212 — IDEA-55 Slippage par profondeur réelle
- [x] #213 — IDEA-56 Latence réseau simulée (distribution)
- [x] #214 — IDEA-57 Partial fills et annulations
- [x] #215 — IDEA-58 Sélection adverse par toxicité
- [x] #216 — IDEA-59 Backtest tick-by-tick
- [x] #217 — IDEA-60 Coûts de financement intra-position
- [x] #218 — IDEA-61 Sizing Kelly fractionné
- [x] #219 — IDEA-62 Vol targeting
- [x] #220 — IDEA-63 Portefeuille conscient des corrélations
- [x] #221 — IDEA-64 VaR / CVaR
- [x] #222 — IDEA-65 Stop drawdown portefeuille
- [x] #223 — IDEA-66 Risk parity entre stratégies
- [x] #224 — IDEA-67 Limites d'exposition par corrélation
- [x] #225 — IDEA-68 Stress-testing scénarios extrêmes
- [x] #226 — IDEA-69 Monte-Carlo trajectoires portefeuille
- [x] #227 — IDEA-70 Sizing conditionnel au régime
- [x] #228 — IDEA-71 Feature store versionné
- [x] #229 — IDEA-72 Model registry + versioning
- [x] #230 — IDEA-73 Data lineage
- [x] #231 — IDEA-74 Tracking d'expériences (MLflow-like)
- [x] #232 — IDEA-75 Seeds déterministes partout
- [x] #233 — IDEA-76 Environnements reproductibles (lockfiles)
- [x] #234 — IDEA-77 Tests de non-régression des modèles
- [x] #235 — IDEA-78 Détection de data drift
- [x] #236 — IDEA-79 Pipeline reproductible one-command
- [x] #237 — IDEA-80 Doc auto des expériences
- [x] #238 — IDEA-81 HMM régimes de marché
- [x] #239 — IDEA-82 Change-point detection (CUSUM/bayésien)
- [x] #243 — IDEA-86 Ondelettes multi-échelle
- [x] #244 — IDEA-87 Entropie/complexité (prédictibilité)
- [x] #245 — IDEA-88 Exposant de Hurst
- [x] #246 — IDEA-89 Analyse spectrale (cycles)
- [x] #247 — IDEA-90 Modèles regime-switching
- [x] #248 — IDEA-91 Chaos engineering (couper sources)
- [x] #252 — IDEA-95 Alerting intelligent (anomalies métriques)
- [x] #253 — IDEA-96 Journal d'audit immuable
- [x] #255 — IDEA-98 Fail-safe par défaut (NO_TRADE)
- [x] #256 — IDEA-99 Golden-file tests des rapports
- [x] #257 — IDEA-100 Replay déterministe complet d'une session
- [x] #258 — FIX-23 : réparer les 23 tests en échec (6 causes racines)
- [x] #259 — CAL-1 Trouver le mécanisme de durcissement progressif des ouvertures
- [x] #260 — CAL-2 Mesurer QUI refuse réellement (logs du run)
- [x] #261 — CAL-3 Inventaire complet des calibrages (source de vérité = .ps1)
- [x] #262 — CAL-4 Poser un calibrage grinder+sniper cohérent + tests
- [x] #263 — PNL-1 Autopsie des 20 trades réels
- [x] #264 — PNL-2 Re-simuler le nouveau TP/SL sur les données replay réelles
- [x] #265 — PNL-3 Chercher un edge là où on n'a pas cherché
- [x] #266 — FORENSIC-1 Attribution exacte du PnL (décomposer les -64$)
- [x] #267 — FORENSIC-2 Pourquoi les stops dérapent (ARB -323 bps pour un SL à 126)
- [x] #268 — FORENSIC-3 ROI réel + audit des logs (anomalies non vues)
- [x] #269 — BUG-HUNT-1 Le prix d'entrée du paper trade est-il réaliste ?
- [x] #270 — BUG-HUNT-2 Asymétrie des frais entrée (1 bps) vs sortie (12 bps)
- [x] #271 — BUG