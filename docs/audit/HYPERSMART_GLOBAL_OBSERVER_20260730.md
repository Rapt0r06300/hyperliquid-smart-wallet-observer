# Global Wallet Observer — état réel au 2026-07-30

Réponse honnête au mandat en 8 points. Ce document sépare **ce qui est livré et prouvé** de **ce qui est
bloqué**, et nomme le bloqueur à chaque fois. Aucun chiffre n'est extrapolé.

---

## 1. Ce qui a été livré dans ce run

| Bloc | SHA | Capacité réelle |
|---|---|---|
| Reconstruction du cycle de vie wallet | `4130bdc` | `OPEN/ADD/REDUCE/CLOSE/FLIP` + TWAP pour **n'importe quel** wallet, depuis n'importe quelle source de fills |
| Scoring point-in-time + rotation des slots | `7b95805` | Score = **edge copiable après nos coûts**, 8 CORE + 2 CHALLENGERS, hystérésis |
| Protections IDEA portées hors legacy | `9cce4a2` | 7 gardes désormais dans `src/hl_observer/runtime/` |

### L'invariant qui compte : `DESYNC`

`start_pos` (la position **avant** le fill, vue par l'exchange) fait autorité ; notre accumulateur sert de
contrôle. S'ils divergent, **il manque des fills**, et l'épisode est marqué `DESYNC` avec `fiable=false`.

C'est le cœur du module : un cycle de vie reconstruit à partir de fills incomplets a **exactement la même
tête** qu'un cycle correct. Sans ce contrôle, on scorerait des wallets sur des positions imaginaires en toute
confiance.

### L'autre invariant : on ne classe pas sur le PnL du leader

Un wallet à +5 bps de markout avec 9 bps de coûts vaut **−4 bps pour nous**. Son PnL ne nous appartient pas.
Le score est le markout net après **notre** latence et **nos** coûts — c'est la seule quantité qui nous
concerne, et c'est testé.

---

## 2. Ce qui est BLOQUÉ, et par quoi

| Objectif | Bloqueur | Décision qui débloque |
|---|---|---|
| **Ingestion globale L1 / `node_fills_by_block`** | L'archive S3 Hyperliquid est **requester-pays** : sans identifiants AWS, `archive_s3.py` refuse (`AUCUN_IDENTIFIANT_AWS_REQUESTER_PAYS_IMPOSSIBLE`) | Un compte AWS + un budget (estimé ≤ 1 € pour un échantillon borné). **Ta décision, pas la mienne.** |
| Recette Windows (`self-test`, `pytest -q`, `ANALYSER full`) | Je tourne dans un sandbox Linux, Python 3.10 | Toi, sur ta machine |
| Suite pytest complète (6 383 tests) | Plafond ~44 s par appel sandbox ; 25 fichiers le dépassent déjà | Windows |
| CORE lançant les producteurs Copy-Vault/lead-lag | Modifier le profil CORE sans pouvoir le valider sous Windows serait irresponsable | Windows |

**Nombre de wallets globalement indexés à ce jour : 0.** Le moteur de reconstruction existe et est testé sur
fixtures ; la source massive n'est pas accessible. Annoncer « des milliers de wallets » serait exactement le
faux chiffre que ce projet refuse.

---

## 3. Ce qui n'a PAS été fait dans ce run

- **`experimental_paper_v2`** : le ledger n'existe pas. Le créer sans moteur qui l'alimente produirait un
  fichier vide présenté comme une capacité — je ne le fais pas.
- **Classification des 101 orphelins et 372 testés-non-branchés** : non traitée. Le chiffre reste celui de
  l'audit précédent.
- **Revalidation individuelle HS-070→HS-100** : toujours `A_REVALIDER` en bloc.
- **dYdX comme second univers de wallets** (point 7) : non commencé.
- **Features du point 8** (TWAP stages, crowding, edge decay par wallet, capacité maximale) : les
  instruments existent (ALPHA-5/7/8), le **dataset** manque — c'est le point 6 qui les débloque, pas du code.

---

## 4. Le goulot d'étranglement, en une phrase

**Tout le reste attend la donnée.** Les instruments de mesure sont construits, testés et honnêtes ; les trois
campagnes déjà lancées sont ressorties `SHADOW_DONNEES_INSUFFISANTES` non par défaut de méthode mais par
manque d'événements. Le prochain gain réel ne viendra pas d'un module de plus : il viendra d'un **accès à
l'historique global des fills** (S3 requester-pays) et d'une **campagne de collecte simultanée** carnets +
BBO + sonde.

---

## 5. Sécurité

`0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.`
Aucun des modules livrés n'ouvre de position : reconstruction et scoring sont des calculateurs purs, les
protections ne savent que refuser.
