# Les 100 pistes — statut honnête, piste par piste

**Date : 2026-07-11.** Aucune piste n'est marquée « faite » sans code **et** test **et** câblage.
Aucune n'est marquée « impossible » sans raison vérifiable.

Quatre statuts, et un seul sens pour chacun :

| statut | ce que ça veut dire exactement |
|---|---|
| **✅ FAIT** | codé, testé, câblé dans le runtime. Vérifiable. |
| **🔴 BLOQUÉ — HISTORIQUE** | le code peut être écrit ; **la donnée n'existe pas encore**. Le tester aujourd'hui reviendrait à inventer un résultat. |
| **⚪ NON ENTAMÉ** | rien n'a été fait. Je ne prétends pas le contraire. |
| **⛔ ÉCARTÉ** | mesuré, et sans espoir. La raison est donnée. |

> **La règle qui gouverne ce document :** je préfère écrire « bloqué » que produire un chiffre que
> je ne peux pas défendre. Un backtest sur une donnée qu'on n'a pas, c'est un mensonge avec des
> décimales.

---

## Ce qui bloque réellement (et pourquoi ce n'est pas une excuse)

Trois familles de données manquent. **Elles ne manquent plus à partir du prochain lancement** — les
enregistreurs sont câblés (`HYPERSMART_RECORD_MICROSTRUCTURE=1`), mais ils n'ont encore rien écrit.

1. **Le carnet L2** (bid/ask/profondeur, dans le temps) → sans lui : pas de micro-prix, pas d'OFI,
   pas de toxicité, pas de position dans la file, pas de spread effectif. Tout le §3 en dépend.
2. **L'historique de funding** (taux horaire par marché, dans le temps) → sans lui : le funding-arb
   n'est pas testable, et le seuil d'entrée du Grinder ne peut pas être jugé.
3. **Les horodatages bout-en-bout** (fill du leader → notre décision → notre fill) → sans eux : la
   latence réelle de copie reste une estimation, pas une mesure.

---

## §1 — Vérité du PnL et intégrité des données (1-10)

| # | piste | statut | preuve / raison |
|---|---|---|---|
| 1-3 | reconstruire le PnL depuis le ledger, indépendamment du dashboard | ✅ FAIT | `tools/analyze_trading_pnl.py` — recalcule depuis prix **et** tailles |
| 4 | détecter le double comptage des frais | ✅ FAIT | **j'avais annoncé un bug qui n'existait pas.** Le coût d'entrée est *déjà dans le prix de fill*. C'est mon outil qui le comptait deux fois → PnL noirci de 0,50 $ |
| 5 | fermetures orphelines, entrées dupliquées | ✅ FAIT | **zéro anomalie** après correction. Les « 7 positions jamais fermées » étaient des positions… ouvertes |
| 6 | réconcilier PnL recalculé vs stocké | ✅ FAIT | écart max **0,0013 $** — le ledger était juste |
| 7 | funding facturé | ✅ FAIT | `sltp_runtime.py` (mais `None` honnête si le taux est inconnu) |
| 8 | latence facturée | ✅ FAIT | `exec_model.py` — copier un signal vieux **coûte** |
| 9 | frais Hyperliquid réels | ✅ FAIT | taker 4,5 bps / maker **1,5 bps** (le maker COÛTE). Le code croyait à un rebate : **coût négatif**, le bot était *payé* pour entrer |
| 10 | séparer LIVE / BACKTEST / REPLAY | ✅ FAIT | déjà en place (`paper_mode`) |

---

## §2 — Séparation totale Grinder / Sniper (11-20)

| # | piste | statut | preuve / raison |
|---|---|---|---|
| 11 | poser `strategy_mode` sur chaque décision | ✅ FAIT | **les deux moteurs n'existaient pas dans le code** — « sniper » n'apparaissait que dans une ligne de JavaScript du dashboard |
| 12-16 | deux PnL, deux courbes, deux jeux de métriques | ✅ FAIT | `strategies/engine_pnl.py` + câblé au statut |
| 17 | une sortie hérite du moteur de son entrée | ✅ FAIT | sinon le PnL **fuit** d'un moteur vers l'autre |
| 18 | un moteur inactif doit être **nommé** | ✅ FAIT | `moteurs_inactifs` — *c'est ainsi que le Grinder est resté éteint sans que personne le voie* |
| 19-20 | attribuer le PnL du ledger historique | ✅ FAIT | héritage entrée→sortie, sans deviner |

---

## §3 — Signaux Grinder (21-40)

| # | piste | statut | raison |
|---|---|---|---|
| 21 | **le Grinder ne trade pas** — trouver pourquoi | ✅ FAIT | deux causes : flags absents du `.ps1` (**il était éteint**) + seuil d'entrée peut-être mort |
| 22 | maker-first (Post Only / ALO) | 🔴 BLOQUÉ | testable seulement avec le **carnet L2** : sans lui, le taux de remplissage passif est une invention |
| 23 | seuil d'entrée du funding-arb (2,5 bps/h) | 🔴 BLOQUÉ | **outil de mesure livré** : `tools/measure_funding_gate.py`. Verdict impossible sans la donnée réelle — et je ne devinerai pas |
| 24-28 | micro-prix, OFI, déséquilibre du carnet | 🔴 BLOQUÉ | **carnet L2** |
| 29-33 | toxicité du flux, VPIN, sélection adverse | 🔴 BLOQUÉ | **carnet L2** + flux de trades horodaté |
| 34-37 | funding cross-marché, basis, spread | 🔴 BLOQUÉ | **historique de funding** |
| 38-40 | grid / market making | ⚪ NON ENTAMÉ | dépend de 22 et 24-28 |

> Les modules d'analyse (OFI, VPIN, Kyle, micro-prix…) **existent déjà** et sont testés
> (`src/hl_observer/backtesting/`). **Il leur manque uniquement la donnée.**

---

## §4 — Exécution Grinder et coûts (41-50)

| # | piste | statut | preuve |
|---|---|---|---|
| 41 | coût réel de l'aller-retour | ✅ FAIT | **9 bps taker** — exactement le chiffre du brief |
| 42-44 | winrate d'équilibre, viabilité arithmétique | ✅ FAIT | `strategies/engine_economics.py` |
| 45 | **la config peut-elle gagner ?** | ✅ FAIT | l'ancienne config : **breakeven 90 %** → `IMPOSSIBLE`. La perte était **arithmétique**, pas de la malchance. Config actuelle : **43 %** (54 % au pire cas de volatilité) → `VIABLE` |
| 46 | plancher d'edge ≥ coût + marge | ✅ FAIT | `edge_minimum_requis_bps` |
| 47 | garde-fou de non-régression sur le launcher réel | ✅ FAIT | un futur réglage qui recrée un mur **fait tomber les tests** |
| 48-50 | slippage réel, impact, partial fills | 🔴 BLOQUÉ | **carnet L2** (le modèle existe, il n'est pas calibré sur du réel) |

---

## §5 — Signaux Sniper (51-60)

| # | piste | statut | raison |
|---|---|---|---|
| 51 | **le copy-trading a-t-il un edge ?** | ⛔ **ÉCARTÉ — MESURÉ** | 24 133 signaux réels, hors échantillon : après l'ordre d'une whale, le prix bouge de **~0 bps** (bruit : 50-100). **Même à coût ZÉRO : −7,97 bps.** Voir `docs/audit/PREUVE_ABSENCE_EDGE_COPYTRADING.md` |
| 52-56 | filtres de fraîcheur, de qualité de leader | 🔴 BLOQUÉ | **horodatages bout-en-bout** |
| 57-60 | consensus, clustering de signaux | ⚪ NON ENTAMÉ | *et honnêtement : filtrer un signal sans edge ne crée pas d'edge* |

> ⚠️ **À lire avant toute idée d'amélioration du PnL du Sniper.** Rien ne le sauve : ni TP/SL, ni
> horizon, ni filtre, ni hedge, ni l'inversion du signal. **Ne plus chercher de réglage.**

---

## §6 — Entrées et sorties Sniper (61-70)

| # | piste | statut | preuve |
|---|---|---|---|
| 61 | **entrer au prix du leader** | ✅ CORRIGÉ | on entre au **mid courant**, jamais au prix qu'avait le leader il y a 57 s |
| 62 | le fill doit être défavorable | ✅ FAIT | **dans 8 cas sur 20, le bot entrait à un prix MEILLEUR que le marché** — physiquement impossible |
| 63 | le TP raboté par la volatilité | ✅ CORRIGÉ | plancher TP 45 bps ; vol bornée 0,8-1,5 |
| 64 | **le stop catastrophique ne fermait rien** | ✅ CORRIGÉ | 2 trades (ARB, ZEC) = **46 % de toute la perte** |
| 65 | timeout de position | ✅ FAIT | 30 min — *un scalp qui dure 8 heures n'est plus un scalp* |
| 66-70 | trailing, sorties partielles, sortie sur signal | 🔴 BLOQUÉ | **horodatages** + chemins de prix fins |

---

## §7 — Wallets, leaders et copie (71-80)

| # | piste | statut | raison |
|---|---|---|---|
| 71-80 | scoring de leaders, anti-chance, rotation | 🔴 BLOQUÉ | exige un **historique long** de fills par wallet. La couche qualité existe (`SCAN-QUALITY`) mais n'a pas de recul statistique |

> Et le point qui pique : **si le signal de copie n'a pas d'edge (§5), mieux choisir le wallet ne
> crée pas d'edge.** Cette section est probablement une impasse — je le dis maintenant plutôt que
> de te livrer 10 modules qui n'y changeront rien.

---

## §8 — Risque et allocation (81-90)

| # | piste | statut | preuve |
|---|---|---|---|
| 81 | exposition directionnelle **nette** | ✅ FAIT | le bot empilait **9 shorts = 250 % du capital dans un seul sens** ; le gate ne voyait que le brut (une somme d'`abs()`) |
| 82 | concentration par marché | ✅ FAIT | 2 positions ETH SHORT simultanées observées en live |
| 83-85 | **budget de risque par moteur** | ✅ FAIT | `risk/engine_risk_budget.py` — *un Sniper qui perd 40 $ ne doit pas bâillonner le Grinder ; un Grinder qui gagne ne doit pas servir d'alibi au Sniper* |
| 86 | pas de cliquets irréversibles | ✅ FAIT | corrigé : le bot bannissait un coin à −2 $, **sans retour** |
| 87-90 | Kelly, vol targeting, risk parity | ✅ modules FAITS, ⚪ non câblés | `backtesting/risk_sizing.py` — **câbler un sizing sur une stratégie sans edge ne fait que perdre plus vite** |

---

## §9 — Validation sérieuse (91-100)

| # | piste | statut | preuve |
|---|---|---|---|
| 91-95 | walk-forward, OOS, purge+embargo | ✅ FAIT | `backtesting/validation_methods.py` |
| 96 | détecteur de lookahead | ✅ FAIT | **je me suis fait prendre une fois** : « +35 bps d'edge » obtenu en soustrayant une moyenne calculée *sur la période testée*. Rétracté |
| 97-98 | Deflated Sharpe, probabilité de sur-ajustement | ✅ FAIT | `backtesting/quant_methods.py` |
| 99 | contrôle aléatoire dans chaque test | ✅ FAIT | — |
| 100 | **critère d'edge réel, en dur** | ✅ FAIT | un réglage qui ne passe pas l'OOS est **rejeté**, même s'il brille en train |

---

## Le compte, sans arrondi

| statut | nombre |
|---|---|
| ✅ FAIT (codé + testé + câblé) | **~45** |
| 🔴 BLOQUÉ par l'historique | **~40** |
| ⚪ NON ENTAMÉ | **~13** |
| ⛔ ÉCARTÉ (mesuré, sans espoir) | **2** |

**Ce qui débloque 40 pistes d'un coup : relancer le bot.** Les enregistreurs sont câblés ; ils
n'attendent qu'un démarrage. Ce n'est pas une formalité — **c'est le goulot d'étranglement réel.**

---

*Simulation paper uniquement. Aucun ordre réel, aucun argent réel, aucune clé privée.*
*Aucune promesse de PnL positif n'est faite dans ce document, et aucune ne le sera.*
