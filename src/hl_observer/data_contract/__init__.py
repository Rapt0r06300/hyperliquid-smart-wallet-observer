"""data_contract — primitives PURES du contrat de données (pépites 255-259, 266-267).

Détection de drift de schéma (champ disparu / type changé / enum nouveau → quarantaine, jamais coercition
silencieuse), validation d'unité de timestamp (s/ms/µs/ns), contrat de sérialisation fixed-point (jamais de
float réintroduit), parité de schéma historique/live, suite de conformité des adaptateurs, autorité de source
par champ (aucun fallback opaque). Donnée douteuse → fail-closed, jamais coercée. 0 réseau, 0 ordre réel.
"""
