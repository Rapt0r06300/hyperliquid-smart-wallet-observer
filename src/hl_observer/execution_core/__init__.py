"""execution_core — primitives PURES d'architecture d'exécution transverses ([ALL]).

Séparation controller/executor, OrderCandidate canonique, budget central, cycle de vie explicite,
taxonomie de clôture, comptabilité incrémentale flip-aware, PositionHold persistant, réconciliation
au redémarrage, retry sûr (lectures seules), verrous anti loss-burst / par côté, stress de slippage
volume-share, et contrat FillModel enfichable. Aucune exécution réelle, 0 réseau : on calcule/valide.
"""
