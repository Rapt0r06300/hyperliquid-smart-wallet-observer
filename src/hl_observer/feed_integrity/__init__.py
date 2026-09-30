"""feed_integrity — primitives PURES d'intégrité des flux de données de marché (lot2).

Chunking des subscriptions, sharding des connexions, re-snapshot périodique, checksum de carnet, validation
stricte des sequence numbers, détection d'updates manqués, clear-and-reseed à la reconnexion, watchdog de
socket idle. On valide/détecte : un flux douteux devient INVALID (fail-closed). 0 réseau, 0 ordre réel.
"""
