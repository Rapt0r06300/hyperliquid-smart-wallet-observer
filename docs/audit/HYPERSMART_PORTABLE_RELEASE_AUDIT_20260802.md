# Audit de release portable HyperSmart - 2026-08-02

## Verdict

`RELEASE_READY=false` au HEAD `6a4317a45dd6bc90ea1ee853ab179b3d81a2cca1`.

La chaine portable est fonctionnelle et reproductible, mais une release officielle ne doit pas
etre publiee tant que la suite globale du produit n'est pas verte et que le HEAD exact n'a pas une
preuve CI Windows verte. Le bouton applique bien ce refus : il ne conserve aucun ZIP final et
n'affiche jamais `[OK]` lorsque ces portes ne sont pas satisfaites.

## Preuves obtenues

- Clone de validation propre, distinct du dossier de travail utilisateur.
- Runtime impose : `tools/python/python.exe`, Python `3.14.2` x64.
- Runtime embarque : `12 223` fichiers ; aucun import requis manquant ; aucune fuite vers un Python
  externe.
- Wheelhouse : `71` wheels verifiees, aucune wheel absente, divergente, incompatible ou interdite.
- Tests archive/runtime/release : `115 passed in 16.96s`.
- Tests de la suite complete : `8 807 passed`, `50 failed`, `8 skipped`, en `879.48s`.
- `LANCER_HYPERSMART.cmd portable-check` : code `0`, marqueur
  `PORTABLE_LAUNCHER_CHECK_OK` present.
- `ANALYSER_BACKTESTS_REPLAYS.cmd portable-smoke` : code `0`, session `COMPLETE`, ledger
  reconcilie (`diff_usdc=0`), aucune execution reelle et aucun reseau.
- `--safety-check` : `OK`.
- `--audit-safety` : toutes les portes affichees `OK`, aucun endpoint `/exchange` operationnel.
- Deux constructions independantes : `14 230` fichiers chacune, `216 423 144` octets chacune.
- SHA-256 A et B :
  `7a517d2a3717d7fe75700bb5d01d2a05f89d3fd9bf209d31bc2f454939e75fb3`.
- Comparaison octet par octet : identique (`true`).
- Base SQLite : copie read-only par l'API Backup vers le staging, puis `integrity_check` ; aucune
  mutation de la source.

## Comportement reel du bouton

Sur le dossier de travail actuel, le depot est dirty. L'appel reel de
`CREER_ARCHIVE_PORTABLE.cmd` a donc retourne un code non nul, affiche `[REFUSE]`, ecrit un
`RELEASE_FAILED.json` avec `stage=git_state`, et conserve exactement `0` ZIP. Ce comportement est
conforme au cahier des charges : l'etat local non commite ne peut pas etre silencieusement presente
comme une release reproductible.

## Portes encore rouges

La suite complete presente 50 regressions. Elles concernent notamment :

- provenance/manifeste et CI ;
- carry/side-lock/carnets spot et couts d'execution ;
- coherence dashboard/ledger/metagraphe ;
- cablage, flags morts, cycles d'import et dette d'architecture ;
- laboratoire/recherche continue et comportement Ctrl+C ;
- replay/backtest V12 sans lookahead ;
- anciennes routes de fusion GitHub desactivees ;
- lanceurs racine et invariants Windows.

Les tests archive eux-memes sont verts. Ces echecs sont neanmoins bloquants pour une archive
qualifiee de "fonctionnelle parfaitement", puisque la validation extraite exige la suite complete.

## Semantique de "clone portable"

L'archive reproduit l'application fonctionnelle versionnee : code, modules, tests, fixtures,
ressources, UI, configurations, migrations, runtime Python, dependances et sessions terminees
selectionnees. Elle ne copie volontairement pas les processus, PID, locks, caches, bases actives,
secrets, fichiers machine, anciens ZIP ni sessions inachevees. Une copie byte-for-byte de ces
elements serait non portable et potentiellement dangereuse.

## Prochaine porte exacte

Corriger les 50 regressions globales sur un HEAD propre, pousser ce HEAD, obtenir la CI Windows
verte, puis relancer `CREER_ARCHIVE_PORTABLE.cmd`. Le pipeline construira de nouveau deux archives,
executera la validation hermetique depuis les extractions et ne publiera le ZIP final que si
`RELEASE_READY=true`.

Securite : 0 ordre reel, 0 argent reel, 0 cle privee, 0 signature, 0 depot/retrait.
