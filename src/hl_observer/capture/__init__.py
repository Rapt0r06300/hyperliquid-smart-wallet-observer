"""capture — primitives PURES du pipeline de capture temps réel (pépites 272-277, 279).

Files critiques bornées avec métrique d'occupation, overflow critique = fail-closed (plus de trade jusqu'au
resync), shedding des flux research non essentiels d'abord (jamais hedge/BBO/execution), budget de writer-lag
(event_received → durable_write), journal write-ahead du brut avant projections critiques, checkpoint atomique
(offset + state hash + dataset position), manifest des versions SDK/parser/schema. 0 réseau, 0 ordre réel.
"""
