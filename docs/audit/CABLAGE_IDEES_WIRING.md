# LOT WIRING — les 91 idées branchées dans le run réel

Base : HEAD `909bfc0`. Paper-only, read-only. Suite : `tests/test_cablage_idees.py` (**14 tests**).

Avant ce lot, les 16 modules livrés (IDEA-1..91) étaient **`PARTIAL_NOT_WIRED`** : écrits, testés, jamais
appelés. Ils sont maintenant **exécutés par le cycle**.

## Architecture du câblage

`tools/cablage_idees.py` est la **couture unique** entre les modules et le laboratoire. Toutes ses fonctions
sont **défensives** : si un module manque ou lève, le cycle continue et l'incident est journalisé. Le câblage
ne doit jamais casser une campagne en cours (prouvé par `test_le_cablage_ne_casse_jamais_le_cycle`).

| Point d'ancrage (`recherche_continue`) | Fonction | Idées activées |
|---|---|---|
| `_maturer_live` (ingestion) | `normaliser_et_dedupliquer` | **1, 2, 4, 9, 10** — RAW→CANONICAL (3 horloges, provenance, drapeaux qualité), dédup **durable** (survit au crash), doublons **journalisés** |
| `_scanner_nouveautes` | `verdict_ingestion` | **79** — panne de collecte ⇒ santé **ROUGE** + promotion interdite ; marché calme ⇒ VERTE |
| `_promouvoir_pass_live` | `controler_verite` | **11, 36, 80** — **verrou global** : ledger corrompu, chaîne PnL incohérente ou verdict synthétique ⇒ **aucune promotion** |
| `_enrichir_etat_dashboard` | `incidents` | **10, 85** — incidents réels au dashboard + scénarios de stress rejouables |
| `finaliser` (manifeste) | `manifeste` | **78** — provenance (Git HEAD, arbre **dirty**, Python, config éco) jointe au manifeste SHA |

## Preuves (tests sur le VRAI cycle, pas des mocks)

| Test | Ce qu'il prouve |
|---|---|
| `test_cycle_reel_normalise_et_deduplique` | Après un cycle réel : `maturation.json` porte `normalisation.actif=True`, `n_canoniques>0`, et `dedup/dedup_journal.jsonl` **existe sur disque** |
| `test_dedup_durable_active_dans_le_cablage` | Le même événement au 2ᵉ passage ⇒ `n_doublons=1`, retiré du flux **et** journalisé `DUPLICATE` |
| `test_cycle_reel_publie_l_etat_d_ingestion` | `_scanner_nouveautes` porte désormais `ingestion.sante` |
| `test_promotion_bloquee_par_le_verrou_de_verite` | Ledger strict corrompu ⇒ `promotion_bloquee=True`, et le verdict **reste** `PASS_PRE_FORWARD` (aucune promotion n'a eu lieu) |
| `test_controle_verite_bloque_sur_pnl_untrusted` | Dashboard divergent ⇒ `PNL_UNTRUSTED` ⇒ promotion refusée |
| `test_controle_verite_bloque_une_promotion_synthetique` | `SYNTHETIC` + `PASS_FORWARD_PAPER` ⇒ corrigé en `SHADOW_SYNTHETIQUE` |
| `test_manifeste_final_porte_la_provenance` | `SHA256_MANIFEST_FINAL.json` contient `provenance` |
| `test_le_cablage_ne_casse_jamais_le_cycle` | Deux hooks qui **lèvent** ⇒ le run produit quand même son état |

Non-régression : `test_labo_continu_absolute` (29), `fix`, `final`, `prod_truth`, `ultimate`,
`data_complete_18h` — **tous verts** après modification de `recherche_continue.py`.

## Ce qui reste NON câblé (honnête)

Ces modules restent des **outils d'analyse appelables**, pas des étapes automatiques du cycle — les brancher
demanderait de modifier le moteur d'exécution et le pipeline 18h, qui portent des modifications locales en
cours :

- `execution_realiste` (14-18, 22-26), `couts_verite` (19-21) — le moteur actuel (`moteur_execution_prod`)
  calcule déjà prix exécutable, VWAP et coûts ; y injecter les fills partiels/maker/markouts change le PnL
  et mérite son propre lot mesuré ;
- `forward_causal` (27-32) — le forward existant est déjà stateful ; la machine d'état explicite viendrait
  le remplacer, pas le compléter ;
- `regimes_marche`, `flux_microstructure`, `leaders_entites`, `exits_risque`, `rigueur_recherche` —
  ce sont des instruments de **recherche** : ils servent à analyser des campagnes, pas à tourner en boucle ;
- `pnl_verite` — `scanner_ledger` est câblé (via `controler_verite`) ; `valider_operation`, `roi_explicite`,
  `SuiviDrawdown` ne le sont pas encore.

## Effet réel attendu

Ce lot ne crée **aucun edge**. Il rend le laboratoire **plus difficile à tromper** : données canoniques et
dédupliquées, panne visible, promotion verrouillée par trois contrôles de vérité, provenance tracée. Autrement
dit, il augmente la probabilité qu'un PnL positif observé soit **vrai** — pas la probabilité d'en observer un.

## Sécurité

0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait. Test de sécurité ciblant
l'endpoint réel (`"/exchange"`, `requests.get`, `import websocket`, `eth_account`…) et non des sous-chaînes :
`coin/exchange_ts` est un nom de champ, pas une route d'exécution.
