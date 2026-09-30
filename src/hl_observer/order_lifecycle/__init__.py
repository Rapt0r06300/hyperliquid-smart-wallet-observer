"""order_lifecycle — primitives PURES du cycle de vie des ordres paper (lot2).

Chemin d'exécution WS, amend in-place préservant la file, TIF (IOC/FOK/GTD/post-only) par venue,
batch-cancel, dead-man switch, états CANCEL_PENDING/UNKNOWN et récupération de submit ambigu, recovery
par fill WS, statut d'instrument canonique. Tout est simulé/validé en paper : 0 réseau, 0 ordre réel.
"""
