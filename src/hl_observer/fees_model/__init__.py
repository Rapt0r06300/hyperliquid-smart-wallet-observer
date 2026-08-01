"""fees_model — primitives PURES de correction des frais (lot2).

Recalcul des frais sur les fills réconciliés (pas seulement l'intention), frais spécifiques au compte/tier
plutôt que barème public, et invalidation du cache de frais au changement de tier/volume. 0 réseau, 0 ordre réel.
"""
