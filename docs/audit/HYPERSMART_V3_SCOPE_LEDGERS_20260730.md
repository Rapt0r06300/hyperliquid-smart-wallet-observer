# V3 §4.6 / §4.7 — statut des ledgers legacy et de scope (2026-07-30)

## §4.5 — équity canonique

`src/hl_observer/ops/equity_canonique.py` : une seule courbe
`capital + realized + unrealized_liquidatable − fees − slippage`, avec anti-double-comptage par construction.
Chaque coût porte `included_in_price` ; le spread traversé (déjà dans le prix ask→bid) est **rapporté mais
jamais re-déduit**. Le mid est informatif, il n'entre pas dans l'équity liquidable. Une brique manquante
(coût non mesuré, position non liquidable) rend `statut=PARTIELLE` — jamais un faux net. 9 tests.

## §4.6 — carry historique : LEGACY_UNMEASURABLE, et il reste hors scope

Flo a confirmé : **le carry a été arrêté**. État vérifié dans `LANCER_HYPERSMART.cmd` :
`HYPERSMART_CARRY_DISABLED=1`, `HYPERSMART_CARRY_HYPE_PAPER=0`, budget 0, aucune ouverture.

- Les 190 lignes `carry_paper_ledger.jsonl` sans prix sont **irrécupérables** : la revalidation §4.3 les
  classe désormais `ORPHELINE_ET_SANS_PRIX` (90) et `OUVERTURE_SANS_PRIX_OU_NOTIONNEL` — elles ne sont
  **pas** « réparées » par interpolation.
- Les **nouveaux** événements carry porteraient prix/notionnel/frais (correctif E1 `1fc005a`), mais le
  producteur est coupé : il n'en écrit plus.
- **Le carry n'est pas remis dans le scope stratégique.** Il reste SHADOW/OFF. Aucune pollution du runtime.

## §4.7 — `experimental_paper_v2` : DISABLED_BY_SCOPE, aucun ledger vide créé

Le ledger `runtime/data/experimental_paper_V2_ledger.jsonl` **n'existe pas** sur le disque. La revalidation
le rapporte honnêtement `LEDGER_ABSENT`.

La règle du fichier V3 est explicite : « Jamais de ledger vide créé pour cocher une case. » Je ne le crée
donc pas. Statut retenu : **`DISABLED_BY_SCOPE`** — la stratégie n'a pas de producteur vivant qui l'alimente
via le moteur canonique, donc pas de ledger. Le jour où un vrai producteur passe par `PaperIntent` →
moteur canonique, le ledger apparaîtra de lui-même.

---

`Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.`
