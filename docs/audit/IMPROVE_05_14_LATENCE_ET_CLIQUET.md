# IMPROVE-05 (#112) & IMPROVE-14 (#121) — le biais de survivant, et le cliquet (2026-07-13)

## #112 — on ne mesurait la latence que des trades qu'on PREND

P3 (#288) affirmait : *« l'instrumentation latence n'est PAS branchée »*. **C'était faux.**
`LatencyTrace` est bien créée et estampillée dans `fusion_paper_engine_adapter` (features → score
→ gates → decision), et son `as_dict()` atterrit dans le `decision_context`.

Le vrai bug était ailleurs, et plus vicieux :

> **Le `decision_context` n'existe que pour une décision qui ABOUTIT.**

Les chemins de refus — `CONSENSUS_TOO_WEAK`, `STALE_SIGNAL`, `decision != FOLLOW` — sortaient
**avant tout tampon**. Résultat : la latence n'était enregistrée que sur les trades pris.

C'est un **biais de survivant dans l'instrumentation elle-même**. Et il rendait inrépondable la
seule question qui compte vraiment ici :

> *« A-t-on refusé ce signal parce qu'il était mauvais — ou parce qu'on est arrivé trop tard ? »*

Sans latence sur les refus, cette question n'a **aucune** réponse possible.

Accessoirement, `resumer()` (p50/p95/p99) n'était appelée par **personne** : on accumulait des
traces une par une sans jamais pouvoir répondre à « quelle est notre latence ? ».

### Le correctif

`runtime/latency_journal.py` — journal **borné** (5 000 entrées ; le bloat de stockage a déjà fait
crasher un run de 48 h), **thread-safe**, qui enregistre **toutes** les traces avec leur **issue**
(`ACCEPTE` / `REFUSE`) et le **motif** du refus. `resume()` sépare les deux populations.

> Si les refus sont systématiquement plus **lents** que les acceptations, ce n'est pas le hasard :
> c'est qu'on arrive trop tard, et qu'on refuse *ensuite*.

Cette comparaison était **impossible** jusqu'ici. Elle ne l'est plus.

### L'invariant

`test_INVARIANT_le_chemin_de_REFUS_du_runtime_journalise_sa_latence` relit le **code** (AST) de
l'adaptateur et exige **au moins deux** appels à `enregistrer(...)` — le refus et l'aboutissement.
Un commentaire ne suffit pas. Le refus ne peut plus redevenir muet en silence.

⚠️ Rappel de la zone morte **Z1** : la courbe edge/horizon est **plate** (500 ms = −3,74 bps).
On mesure la latence pour **savoir**, pas pour espérer que ça améliore le PnL. Ça ne l'améliorera pas.

---

## #121 — le cliquet de couverture

« Étendre la couverture de tests » est un **vœu**. Un vœu ne garde rien.

| | |
|---|---:|
| modules **joignables** (peuvent s'exécuter en prod) | **484** |
| couverts par un test | **481** |
| **non testés** | **3** |

Les trois : `hl_observer.__main__`, `collection.run_collect_all`, `ui.wallet_mirror_panel`.

Le test `test_le_CLIQUET_tient` **échoue si ce nombre augmente**. Et `ecrire_baseline` **refuse**
de relever la barre :

> Un cliquet qui se relâche tout seul n'est pas un cliquet : c'est une décoration.

### ⚠️ Ce chiffre ne dit PAS ce qu'on aimerait qu'il dise

**« Couvert » ici = « un test l'importe, directement ou transitivement ».**
PAS « ses lignes sont exécutées ».

C'est une borne **optimiste** : un module importé par un test qui ne l'appelle jamais compte comme
couvert. **99,4 % ne signifie donc pas « bien testé »** — et je préfère l'écrire noir sur blanc
plutôt que de laisser un joli pourcentage faire son travail de flatterie.

Le cliquet reste utile : il interdit d'ajouter du code qu'**aucun** test ne touche.
La vraie mesure (couverture de **lignes**) est la tâche **#596**, et les deux chiffres devront être
publiés **côte à côte** — pour qu'aucun des deux ne puisse mentir tout seul.

### 🚩 Et mon propre outil s'est trompé

Ma première version annonçait **0 module couvert sur 484**. Un chiffre absurde — que j'aurais pu
inscrire tel quel dans la baseline, où il aurait dormi pour toujours.

Cause : je passais `tests.test_xxx` comme point de départ à `modules_atteignables`, qui ne parcourt
que le graphe des modules `hl_observer.*`. Zéro correspondance, zéro couverture.

C'est le **test sur arbre fabriqué** — celui dont je connaissais la réponse d'avance — qui l'a
attrapé immédiatement.

> **Un outil de mesure qui se trompe est pire qu'une absence de mesure : on lui fait confiance.**

C'est exactement la leçon du 12/07 (l'audit qui contaminait ses propres tests), et c'est pour ça
que tout outil d'audit de ce projet doit rester **pur** et être **éprouvé sur des entrées connues**.

---

## Résultat

```
poser_baseline_couverture ......... 484 joignables · 481 couverts · 3 non testés
test_couverture_cliquet ........... 3 passed
test_latency_journal + trace ...... 17 passed
non-régression chemin vivant ...... 6 passed
safety-audit ...................... 8/8 ok
```

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
