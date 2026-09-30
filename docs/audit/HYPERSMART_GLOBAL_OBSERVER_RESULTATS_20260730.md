# Global Wallet Observer — premiers résultats réels (2026-07-30)

Le compteur est passé de **0 wallet indexé** à un dataset mesurable. Ce document donne les chiffres bruts,
puis ce qu'ils veulent dire — y compris quand ils ne disent rien de bon.

---

## 1. Sources réellement ingérées

| Fichier | Source déclarée | Verdict | Taux normalisable | `start_pos` |
|---|---|---|---|---|
| `vault_fills.jsonl` | `vault_fills` | **VALIDE** | 1,00 | **oui** |
| `vault_fills_live.jsonl` | `vault_fills_live` | **VALIDE** | 1,00 | non |
| `leader_fills_bruts.jsonl` | `node_fills_by_block` | AUCUN_FILL_EXPLOITABLE | 0,00 | — |
| `fills_journal.jsonl` | — | AUCUN_FILL_EXPLOITABLE | 0,00 | — |

`leader_fills_bruts` ne contient ni taille ni prix — c'est un journal d'observation, pas des fills.
`fills_journal` est un journal de décisions. Les compter comme « données » aurait gonflé le chiffre sans
rien apporter : ils sont rejetés avec leur motif.

**`node_fills_by_block` officiel n'a pas été ingéré** : l'archive S3 Hyperliquid reste **requester-pays** et
refuse sans identifiants AWS. Aucun miroir public vérifiable n'a été retenu — une source dont on ne peut pas
prouver la provenance est cadrée `autoritative=False` par le code et **ne peut pas alimenter le scoring**.

## 2. Ingestion et reconstruction

| Mesure | Valeur |
|---|---|
| Fills ingérés | **24 908** |
| Fills refusés | 0 |
| Doublons écartés | **17 439** (les deux sources se recouvrent largement) |
| Cycles reconstruits | **7 469** |
| — dont OPEN / ADD / REDUCE / FLIP / CLOSE | 189 / 3 553 / 3 618 / 38 / 71 |
| TWAP identifiés | **0** (aucun `twapId` dans ces sources) |
| Wallets vus | **14** |
| Wallets en **DESYNC** | **6** |
| Wallets fiables | **8** |

6 wallets sur 14 sont en DESYNC : leur `start_pos` déclaré par l'exchange ne colle pas à notre accumulateur,
donc **il manque des fills**. Ils sont exclus du scoring, pas « corrigés ». C'est le gate qui empêche de
noter un wallet sur des positions imaginaires.

## 3. Couverture des markouts — le déblocage

La bande BBO synchronisée ne porte que 6 majors ; les wallets suivis tradent des alts. Résultat initial :
**0,11 % de couverture**. En branchant la bande **allMids** (format large, tous les coins) :

| | Avant | Après |
|---|---:|---:|
| Couverture markout | 0,11 % | **61,5 %** |
| Coins couverts | 6 | **99** |
| Wallets scorables | 0 | **5** |

## 4. Mesure économique — sans embellissement

Horizon 5 s, coût aller-retour 9 bps.

| Wallet | n mesurables | Score copiable | PF | Concentration | Éligible CORE |
|---|---:|---:|---:|---:|---|
| `0x07fd99…` | **3 686** | **−9,45 bps** | 0,053 | 0,003 | non |
| `0x9114a5…` | 69 | −8,77 bps | 0,005 | 0,024 | non |
| `0x77fee2…` | 67 | −9,13 bps | 0,000 | 0,045 | non |
| `0x00ae7d…` | 33 | −8,34 bps | 0,007 | 0,033 | non |
| `0x115849…` | 22 | −8,46 bps | 0,000 | 0,056 | non |

**Les cinq sont négatifs**, et groupés entre −8,3 et −9,5 bps — c'est-à-dire **exactement l'ordre de grandeur
de nos coûts**. Autrement dit : le markout brut à 5 secondes est ≈ 0. Les fills de ces leaders n'ont **aucun
pouvoir prédictif** à cet horizon ; ce ne sont pas les frais qui détruisent un edge, c'est qu'il n'y en a pas.

La concentration est **faible** (0,003 → 0,056) : ce n'est pas un mauvais trade isolé qui plombe la moyenne,
c'est **systématique**. Et l'échantillon principal fait **3 686 épisodes** — ce n'est pas du bruit.

C'est une **confirmation indépendante** de la loi déjà établie du projet (copy global négatif), obtenue sur
un pipeline neuf et un dataset neuf.

## 5. Shortlist 8 + 2

**CORE : vide.** Aucun wallet n'a d'edge copiable positif après nos coûts — la règle est respectée à la
lettre : une place CORE exige un edge **mesuré et positif**, pas un classement relatif des moins mauvais.

**CHALLENGERS : 2** wallets non mesurés, qui occupent les slots d'exploration — leur raison d'être.

Remplir les 8 places CORE avec les « meilleurs » de cette liste reviendrait à copier des wallets dont on a
mesuré qu'ils perdent.

## 6. Dette restante

| Sujet | État |
|---|---|
| `node_fills_by_block` officiel | **bloqué** — S3 requester-pays, décision AWS |
| 101 orphelins / 372 testés-non-branchés | non classifiés |
| HS-070 → HS-100 | `A_REVALIDER` en bloc |
| `experimental_paper_v2` | absent (pas de producteur ⇒ pas de ledger fabriqué) |
| Profil CORE du runtime | inchangé (non validable sans Windows) |
| dYdX second univers | non commencé |
| Recette Windows | non exécutée (sandbox Linux, Python 3.10) |

## 7. Prochain goulot

Ce n'est plus le code, et ce n'est plus la couverture prix. C'est **la population de wallets** : 14 wallets
observés, dont 8 exploitables, tous issus de vaults déjà sélectionnés — donc un échantillon biaisé par la
sélection précédente. Pour trouver un edge copiable, il faut **découvrir des wallets qu'on n'a pas choisis**,
et cela passe par l'ingestion globale `node_fills_by_block`, aujourd'hui bloquée sur un compte AWS.

Deuxième goulot, moins coûteux : **0 TWAP identifié** dans ces sources. Les analyses TWAP/métaordres
(ALPHA-7) resteront sans matière tant que `userTwapSliceFills` n'est pas collecté avec ses `twapId`.

---

`Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.`
