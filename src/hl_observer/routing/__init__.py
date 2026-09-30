"""routing — primitives PURES de routage d'exécution cross-venue (pépites 231-236, 241-243).

Route graph {venue, instrument, side, exec type}, route primaire + secours paper, prévalidation du fallback,
score par shortfall p95 / timeout p99, warm-state de route, coût de switching, ledger de regret, comparateur
shadow. On compare le coût EXECUTABLE complet, jamais les seuls frais affichés. 0 réseau, 0 ordre réel.
"""
