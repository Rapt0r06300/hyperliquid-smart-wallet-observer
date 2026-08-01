"""mega_cablage — CÂBLAGE de bout en bout des pépites 201-300 (jusque-là des primitives PURES isolées, testées
une par une mais composées nulle part). Ce paquet les thread dans le CHEMIN RÉEL :

    données live/replay → Copy / Cross-Venue → netting / routing → PaperEngine (fills) → ledger → PnL

Chaque étage est un petit module composable qui appelle les VRAIES primitives existantes (copy_vault,
execution_core, routing, arbitrage, data_contract, feed_integrity, risk_gates) et la VRAIE queue de PnL
(simulation.paper_ledger.PaperLedger + simulation.orderbook_execution_simulator). Aucun ordre réel, aucun
`/exchange`, aucune signature : uniquement de la simulation paper locale. Règle dure conservée à chaque étage :
donnée manquante / incohérente → NO_TRADE honnête (jamais un fill fabriqué), et le PnL final se réconcilie
au ledger (identité equity = start + realized + unrealized − fees + funding).

Étages :
  - event_admission      : porte d'intégrité à l'ingestion (data_contract + feed_integrity)
  - copy_stage           : fill leader → intention de copie mise à l'échelle de notre equity (copy_vault)
  - cross_venue_stage    : intention de hedge cross-venue optionnelle (arbitrage), seulement si edge mesuré
  - netting_routing_stage: netting global + self-trade prevention + priorité + routing + candidat canonique
  - risk_stage           : garde-fous pretrade (risk_gates)
  - fill_ledger_stage    : simulation de fill + PaperLedger + PnL réconcilié
  - pipeline             : orchestrateur qui thread le tout par tick et produit une trace + un PnL
"""
