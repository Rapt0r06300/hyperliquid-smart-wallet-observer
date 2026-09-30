"""api_governance — primitives PURES de gouvernance des appels API (lot2).

Rate limiter pondéré par endpoint, quota réservé cancel/reconcile/hedge, une instance connexion/rate-limiter
par venue, QoS des requêtes, throttle des queries de réconciliation. Calcul/validation seulement : 0 réseau.
"""
