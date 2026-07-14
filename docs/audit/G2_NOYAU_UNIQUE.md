# G2 — Le noyau unique. Et les **trois** edges fabriqués qu'il a trouvés.

> 2026-07-13. Code : `src/hl_observer/decision_engine/noyau_unique.py`.
> Tests : `tests/test_noyau_unique.py` (17 verts). Lanceur : `G2-NOYAU.cmd` → `g2_noyau.txt`.

## Le trou, trouvé en lisant `local_engine.py`

```python
risk_context = RiskContext(..., edge_remaining_bps=candidate.edge_remaining_bps, ...)
risk_decision = RiskEngine(self.settings).evaluate(risk_context)
```

Le juge prenait l'edge **tel que l'appelant le lui donnait**. Il notait ensuite ce nombre avec une
arithmétique impeccable — sur une valeur dont il n'avait **jamais** questionné la provenance.

> **PERSONNE NE POSSÉDAIT L'EDGE.**

Chaque moteur (copie, fraîche opportunité, arbitrage, funding, vote de leaders) calculait le sien
et le passait au juge. Le juge jugeait le **chiffre**, pas sa **provenance**. C'est exactement par
là que des edges **fabriqués** sont entrés — et y sont restés des mois.

## Ce que fait le noyau

Quatre questions, **dans cet ordre**. Le premier NON l'emporte.

| # | question | verrou | refus |
|---|---|---|---|
| 1 | **D'où vient l'information ?** | Q3 · `signal_taxonomy` | `NOYAU_SIGNAL_DANS_UNE_ZONE_MORTE_PROUVEE` |
| 2 | **Quel est l'edge MESURÉ ?** | Q1 · `edge_source` (`formule_de_secours=None`) | `NOYAU_EDGE_NON_MESURE` / `..._FABRIQUE_PAR_UNE_FORMULE` |
| 3 | **Les prix sont-ils EXÉCUTABLES ?** | Q2 · `jambe_executable` | `NOYAU_PRIX_NON_EXECUTABLE` |
| 4 | **L'edge NET tient-il après coûts ?** | frais + slippage réel + dégradation | `NOYAU_EDGE_NET_INSUFFISANT_APRES_COUTS` |

Et la règle qui change tout :

> **Le noyau REFUSE l'edge que l'appelant lui apporte.**

Si un moteur passe `edge_fourni_bps=999`, le noyau ne l'utilise pas : il va chercher la mesure,
et si les deux divergent il **l'écrit** (`EDGE_FOURNI_PAR_L_APPELANT_CONTREDIT_LA_MESURE`). Un
appelant ne peut plus s'auto-autoriser en apportant son propre chiffre.

**Il ne garde QUE les entrées.** Jamais les sorties : bloquer une sortie, ce serait **piéger** une
position ouverte. Un garde-fou qui empêche de sortir n'est pas un garde-fou.

## 🔴 Ce que l'invariant a trouvé — et que Q1 avait raté

Q1 disait avoir remplacé les **trois** edges fabriqués connus. `test_AUCUN_module_de_production_ne_FABRIQUE_un_edge_d_entree`
découvre les formules **par AST**, sans liste écrite à la main. Il en a trouvé **trois de plus** :

| fichier | ce qui y vivait | verdict |
|---|---|---|
| `ui/routes.py:1301` | `18.0 + confidence*34.0 + min(24.0, (n-1)*8.0)` | 🔴 **4e edge fabriqué — sur le chemin d'entrée du simulateur LIVE** |
| `strategies/fusion_runtime.py:707` | `min(120.0, score_margin*8.0 + (n-1)*6.0)` | 🔴 **5e edge fabriqué** — « un point de vote vaut 8 bps » |
| `copying/realtime_magic_score.py:224` | base **mesurée** × freshness × consensus | 🚩 pas fabriqué, mais **double-compte** (voir plus bas) |
| `ui/routes.py:1205` | `min_edge + 10.0` | ✅ faux positif : c'est un **SEUIL**, pas une valeur d'edge |

Les deux premiers sont corrigés : l'edge vient de la table mesurée, `formule_de_secours=None`,
non mesuré ⇒ `0.0` ⇒ refusé par le plancher. **Deny-by-default.**

### Ce que ça dit de Q1

**Q1 était incomplet, et je l'avais déclaré fini.** Le chemin d'entrée du simulateur *live*
(`ui/routes.py`) n'importait même pas `edge_source`. C'est **P2-3 (#310) prouvé par exécution** :
les deux chemins d'edge coexistaient bel et bien.

> Ce n'est pas mon *inventaire* qui l'a trouvé. C'est l'**invariant**.
> Un inventaire se fait une fois et se trompe. Un invariant se vérifie à chaque exécution.

## 🔴 Le bug de la cellule « large » : un marché jamais mesuré héritait de l'edge d'un autre

`measured_edge_table` a deux niveaux de clé : la **fine** (`STRAT|BTC|age|score|cons`) et la
**large** (`STRAT|*|age|score|cons`), pour ne pas laisser 232 marchés × 5 bandes de buckets vides.

Un test l'a pris en flagrant délit : un coin **jamais vu** (`INCONNU_XYZ`) recevait un edge…
celui de BTC, via la cellule large. Or si cette cellule n'a été nourrie **que par BTC**, elle ne
généralise rien : **c'est BTC qui porte un masque.**

C'est la maladie de P2-2 (des coûts constants d'un marché à l'autre) qui revenait par la porte de
l'**edge**. Correctif : `MIN_COINS_POUR_LARGE = 5` — une cellule large nourrie par moins de cinq
marchés **distincts** n'est plus émise. L'interrogation retombe sur un refus.

## Le marqueur d'exemption — et pourquoi il ne peut pas devenir un blanc-seing

Deux lignes survivent au détecteur pour de bonnes raisons. Elles portent un marqueur
`# EDGE_NON_FABRIQUE: <raison>`, **à la ligne**, jamais dans une liste centrale (une liste
s'éloigne du code et finit par mentir). Et le test exige une raison **d'au moins 60 caractères** :
`test_le_MARQUEUR_d_exemption_n_est_PAS_un_blanc_seing` vérifie qu'un marqueur nu, ou de trois
mots, **n'exempte rien**.

## 🚩 Ce qui reste ouvert (et que je ne masque pas)

**`realtime_magic_score` double-compte.** La table est déjà indexée par *(âge, score, consensus)*.
La remultiplier par `freshness` et `consensus_factor` applique **deux fois** les mêmes features.
Ce n'est pas une fabrication — la base est mesurée — mais c'est faux. Tâche ouverte, écrite dans
le code, pas cachée sous le tapis.

## La conséquence, dite franchement

Trois des quatre moteurs de G2 — **Grinder, Sniper, CopyWallet** — retombent sur la **même**
famille : `DISCRETIONNAIRE_PUBLIC`. La zone morte prouvée (24 133 signaux OOS ; le prix court
**contre** le trade de −7,75 bps *avant* le fill, puis plus rien).

> **Les fusionner ne les ressuscite pas. Ça rend leur mort visible depuis un seul endroit au lieu de trois.**

Concrètement : avec le noyau autoritaire (défaut), **le chemin copy n'ouvre plus rien**. Ce n'est
pas une panne — c'est la conclusion de Q1 et Q3 enfin *appliquée* au lieu d'être seulement écrite
dans un rapport.

## L'interrupteur

`HYPERSMART_NOYAU_AUTORITAIRE` — déclaré **ALLUMÉ** au registre GH-01, posé par
`tools/start_hypersmart_simulation.ps1`. Règle GH-01 : *un interrupteur qui ne fait que REFUSER →
on l'allume* (le coût d'un refus de trop est nul ; le coût d'une perte évitée est réel).
Le paquet `decision_engine` a été **ajouté aux paquets surveillés** : le point de décision est
précisément l'endroit où un interrupteur éteint fait le plus de dégâts.

Éteint (`0`), le noyau devient **consultatif** : il calcule son verdict, l'écrit dans la preuve
(`NOYAU_CONSULTATIF_VERDICT_IGNORE`), et on l'ignore — mais **la trace reste**. Un verdict qu'on
ignore doit laisser une trace, sinon personne ne saura jamais qu'on l'a ignoré.

## Résultat

146 tests verts (17 noyau · 13 câblage · 57 cliquet + interrupteurs · 59 non-régression Q1/Q2/Q3/G1/H-181).

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
