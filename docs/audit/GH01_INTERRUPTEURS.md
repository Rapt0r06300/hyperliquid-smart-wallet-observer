# GH-01 — Les protections existaient déjà. Elles n'étaient **jamais allumées**.

> 2026-07-13. Code : `src/hl_observer/risk/interrupteurs.py`.
> Tests : `tests/test_interrupteurs.py` (10 verts). Lanceur : `tools/start_hypersmart_simulation.ps1`.

## Ce que GH-01 demandait

Porter `global_stop` + `stop_per_pair` de freqtrade (GPL → réimplémenter, pas copier).

## Ce que j'ai trouvé

**C'était déjà fait.** `risk/protections_v26.py` implémente exactement ça :

| protection | ce qu'elle fait |
|---|---|
| **StoplossGuard** | N stops dans une fenêtre → halt. **Global OU par marché** (`SG_PER_MARKET`) — c'est `global_stop` + `stop_per_pair`. |
| **LowProfitMarket** | un marché non rentable sur N trades → blacklist temporaire |
| **WindowedMaxDrawdown** | perte de fenêtre > seuil → pause globale |

Codé. Testé. **Branché** — nourri par le ledger réel (`v26_exit_pipeline`), lu par le veto d'entrée
(`v26_entry_vetos`).

Et **`HYPERSMART_V26_PROTECTIONS` n'était posé dans aucun lanceur.** Défaut `"0"`.
**Elles ne se sont jamais déclenchées.**

## 🔴 Ce n'était pas un flag. C'était toute la pile.

| flag | module | état |
|---|---|---|
| `HYPERSMART_V26_PROTECTIONS` | protections_v26 | **éteint** |
| `HYPERSMART_V26_GRADED_HALT` | graded_halt | **éteint** |
| `HYPERSMART_V26_MARKET_QUALITY` | v26_entry_vetos | **éteint** |
| `HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE` | v26_entry_vetos | **éteint** |
| `HYPERSMART_V26_KELLY_LEADER` | kelly_leader_book | **éteint** |

**Cinq sur cinq.** Aucun dans un lanceur.

Le pire : `HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE` éteint signifie que tous les autres vétos
étaient **calculés… puis jetés**. Le coût du calcul, aucun bénéfice de la protection.
**Un véto consultatif n'est pas un véto.**

## 🚩 Et ça invalidait trois pierres tombales

`risk/tombstones.py` justifie l'enterrement de `kill_switch`, `circuit_breaker` et `loss_halts`
par : *« remplacé par `protections_v26` / `graded_halt` (**vivants**) »*.

**Un remplaçant éteint n'est pas un remplaçant.** On avait enterré les anciens garde-fous au
profit de garde-fous qui ne s'exécutaient jamais. La contradiction ne se résout pas en
déterrant les anciens — elle se résout en **allumant** les nouveaux.

## La maladie, nommée pour la septième fois

| # | ce qui était éteint | date |
|---|---|---|
| 1 | le poller de carnet L2 | 11/07 |
| 2 | la jambe de funding | 08/07 |
| 3 | le garde-fou lookahead | — |
| 4 | le verrou du copy-follow | 12/07 |
| 5 | `delta_neutral_carry` | 12/07 |
| 6 | le bus GitHub (allumé par défaut, jamais éteint) | 12/07 |
| **7** | **la pile V26 entière** | **13/07** |

T3b avait créé l'invariant sur les **modules** : *« un module ni joignable ni enterré fait
échouer la suite »*. Il a marché — il a trouvé 4 garde-fous que mon grep avait ratés.

**Mais il n'existait aucun invariant sur les INTERRUPTEURS.**

Un module peut être parfaitement branché, testé, joignable — et ne jamais s'exécuter parce que
son flag vaut `"0"` et que personne ne l'a jamais posé. **L'audit de câblage ne voit rien :**
l'import existe, l'appel existe. Seule la *valeur* du flag décide, et elle est invisible au code.

## L'invariant qui manquait

> **Un interrupteur ni allumé ni déclaré éteint fait échouer la suite.**

`risk/interrupteurs.py` — chaque `MASTER_FLAG` du code **doit** y figurer avec une décision :

- **ALLUMÉ** → le test vérifie que le **lanceur** le pose *vraiment* (se déclarer allumé dans un
  registre ne pose aucun flag).
- **ÉTEINT_VOLONTAIREMENT** → et on **écrit pourquoi**, avec un motif d'au moins 120 caractères.
  *Un motif de trois mots n'est pas un motif, c'est une excuse.*
- **ÉTEINT_PAR_OUBLI** → **banni par un test.** Cette valeur n'existe que pour être interdite.

Les flags sont **découverts** dans le code par regex, jamais listés à la main : une liste écrite
à la main expire le jour où quelqu'un ajoute un flag, et personne ne se plaint. *C'est exactement
le piège qu'on ferme.*

Et une **santé à l'exécution** (`interrupteurs.sante()`, appelée par le point de décision) : le
test vérifie le lanceur, mais un lanceur se contourne. Si un garde-fou déclaré ALLUMÉ ne l'est
pas au runtime, **on le crie** dans le contexte de décision, le journal et le dashboard.

> **Ce n'est pas l'absence de garde-fou qui fait mal. C'est le garde-fou qu'on *croit* avoir.**

## La règle de décision — de l'arithmétique, pas de la prudence

- **Un interrupteur qui ne fait que REFUSER → on l'allume.** Le pire qu'il puisse faire est de
  refuser un trade. Or Q1 et Q3 ont **mesuré** qu'il n'y a pas d'edge à capturer : le coût d'un
  refus de trop est **nul**, le coût d'une perte évitée est **réel**. L'asymétrie est écrasante.
- **Un interrupteur qui change la TAILLE ou le SENS → on le mesure d'abord.** Il change le PnL.

D'où : 4 allumés, **Kelly reste éteint**.

### Pourquoi Kelly reste éteint (et c'est écrit dans le code)

Kelly **dimensionne**. Il suppose un edge **positif connu**. Or Q1 et Q3 ont mesuré que l'edge du
copy-trading est **nul**. Kelly sur un edge nul dit « ne mise rien » ; Kelly sur un edge **mal
estimé** dit n'importe quoi — et il le dit **en augmentant la taille**.

L'allumer sur un signal sans edge, c'est **amplifier une perte**. On le mesure d'abord, on
l'allume ensuite. Jamais l'inverse.

## Résultat

95 tests verts (10 invariant + 47 cliquet de câblage + 38 non-régression). Le cliquet passe :
le nouveau module est **branché**, pas mort — l'invariant T3b l'a d'ailleurs attrapé quand il ne
l'était pas encore.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
