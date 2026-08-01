"""risk_gates — primitives PURES de garde-fous de risque pré-trade (lot2 #90-92, 99-100).

Reduce-only vérifié contre la position (pas le cash), notional réel des tailles en quote, blocage si mark
manquant, pack de risque front-end (débits/ordres actifs/annulations), MaxDrawdown equity + cooldown.
Donnée manquante → blocage (fail-closed). 0 réseau, 0 ordre réel.
"""
