# IMPROVE-23 & IMPROVE-24 — deux verrous, une même maladie (2026-07-13)

## La maladie, pour la 8e fois

> **Une capacité présente, un interrupteur éteint, et personne qui se plaint.**

Elle a pris sept déguisements. Cette page en ferme deux de plus.

---

## IMPROVE-24 (#131) — la MACHINE n'a pas les MOYENS

Tous nos garde-fous empêchent le **code** de décider de trader.
Celui-ci empêche la **machine** d'en avoir les **moyens**.

`src/hl_observer/security/dependances.py` refuse trois familles de paquets :

| Famille | Exemples | Pourquoi |
|---|---|---|
| `CLIENT_D_EXECUTION` | 🚨 `dex-exec`, `ccxt`, `hyperliquid-python-sdk`, `python-binance` | envoient de vrais ordres |
| `SIGNATURE_OU_CLE` | `eth-account`, `web3`, `mnemonic`, `bip-utils` | sans signature, aucune transaction |
| `PORTEFEUILLE` | `walletconnect`, `metamask` | connecter un wallet pour agir |

Les noms sont **normalisés** comme PyPI le fait (`Eth_Account` == `eth-account`), sinon la
capacité rentrerait par la porte de la casse.

`auditer()` est **pure** : on peut lui demander « et si quelqu'un installait ccxt demain ? »
sans installer ccxt. *Un garde-fou qu'on ne peut pas éprouver ne garde rien.*

**Câblé** dans `safety_audit` → 8e contrôle `no_real_execution_capable_package`.
C'est un **cliquet** : un futur `pip install ccxt` fait rougir la CI.

**Vérifié sur la machine réelle : aucun de ces paquets n'est installé.**

---

## IMPROVE-23 (#130) — une tombe ne peut citer qu'un remplaçant VIVANT

### L'histoire en trois temps

1. **T3b (12/07)** enterre `kill_switch`, `circuit_breaker`, `loss_halts`.
   Motif écrit sur chaque tombe : *« remplacé par `protections_v26` / `graded_halt` (vivants) »*.
2. **GH-01 (13/07)** découvre que ces deux « vivants » avaient du code joignable…
   mais que **leurs interrupteurs n'étaient posés par aucun lanceur**.
   → **Un remplaçant éteint n'est pas un remplaçant.** On avait, pour de vrai, *aucun kill-switch*,
   et un registre qui affirmait le contraire.
3. **Ici**, l'invariant qui ferme le trou : `tests/test_tombes_remplacants_vivants.py`.

> T3b gardait les **modules**. GH-01 gardait les **interrupteurs**.
> **Rien ne gardait le LIEN entre les deux** — et la contradiction vivait précisément là.

### Ce que le test a trouvé (il a rougi 5 fois, et chaque fois il avait raison)

Un remplaçant a **trois formes vérifiables**, et il a fallu trois échecs pour que je les voie
toutes : un **module** (joignable + allumé), un **flag** (posé par un lanceur), une **fonction**
(appelée par un module joignable).

Puis il a trouvé le vrai problème : **quatre tombes ne citaient que de la PROSE.**

| Tombe | Citait | Cite maintenant |
|---|---|---|
| `stale_data_guard` | « signal_age, CURRENT_MID_REQUIRED » | `risk.exec_gates` + `signals.v26_entry_vetos` + `signals.fill_admission` + `signals.copy_decision` |
| `journal` | « le PAPER LEDGER » | `simulation.paper_ledger` + `paper_trading.paper_engine` |
| `leader_exit_monitor` | `copy_wallet/wallet_mirror_runtime` (slash) | `copy_wallet.wallet_mirror_runtime` |
| `max_chase_guard` | « le cap de dégradation de copie » | `signals.v26_entry_vetos.apply_v26_entry_vetos` |

**Une tombe qui cite un remplaçant invérifiable ne vaut pas mieux qu'une tombe qui ne cite
personne** : dans les deux cas, on ne peut pas prouver que le travail est fait.

### Là où j'ai refusé d'élargir

Le détecteur a fini par accuser `config()` et `reconciliation()` — des **mots français** de la
prose qui existent aussi comme `def` quelque part. J'aurais pu ajouter une 4e forme (« le champ »)
et faire passer le test. **Je ne l'ai pas fait** : « ce champ existe quelque part » ne prouve rien —
un champ ne refuse pas une entrée, un module le fait.

Règle retenue : **un identifiant de code porte un `_`. Le français, non.**
Et la correction est allée dans la **donnée**, pas dans le détecteur. C'est un **durcissement**,
pas un contournement — et savoir tenir cette distinction quand un de mes propres tests rougit est
tout l'enjeu.

### Verdict sur #130

`protections_v26` et `graded_halt` sont **joignables ET allumés** (GH-01).
→ La tombe du `kill_switch` est **valide**. Le halt existe réellement.

---

## Résultat

```
tests/test_dependances_execution.py ......... 9 passed
tests/test_tombes_remplacants_vivants.py .... 6 passed
safety-audit ................................ 8/8 ok
```

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
