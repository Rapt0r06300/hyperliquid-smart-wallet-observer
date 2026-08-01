"""copy_vault — primitives PURES de réplication paper d'un wallet/vault leader (COPY-VAULT).

Réplication de taille (equity/exposure ratio, plafonds), idempotence du flux source (exactly-once,
anti-replay, curseur), et sémantique correcte de position (delta-copy, reduce-only, flip, close
directionnel). Aucune exécution réelle, 0 réseau : ces modules calculent/valident, ils n'agissent pas.
"""
