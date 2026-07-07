# HyperSmart — Contrats de données internes (tâche 54)

_Généré 2026-07-01. Read-only / paper-only. Objets communs qui circulent dans le flux._

Ces objets sont les « contrats » stables entre étages du pipeline (cf. `docs/ARCHITECTURE_FLOW.md`).
Ils existent déjà dans le runtime ; ce document les recense et fige leur emplacement.

| Contrat | Rôle | Classe / emplacement réel |
|---|---|---|
| SignalCandidate | Signal brut normalisé (leader → candidat) | `hyperliquid/schemas.py` (`class SignalCandidate`) |
| MirrorCandidate | Candidat de copie (mirror d'un leader) | `copy_mode/wallet_mirror_runtime.py` |
| PaperIntent | Intention paper avant risque (jamais un ordre) | `strategies/models.py` (`class PaperIntent`) |
| PaperFill | Remplissage paper simulé | `storage/models.py` (`class PaperFill`) |
| PaperPosition | Position paper reconstruite | `copying/v9_paper_pipeline.py` (`class PaperPosition`) |
| PaperLedgerEvent | Événement du ledger (vérité PnL) | ledger paper + `dashboard_truth/metric_provenance.py` |
| NoTradeDecision | Refus codé (taxonomie NO_TRADE) | reason codes `signals/` + `agent_tools/readonly_inspectors.py` |
| SourceHealth | Santé/fraîcheur d'une source | `sources/models.py` (`SourceHealthSnapshot`) + `storage/models.py` |
| MarketFeatures | Vecteur microstructure | `features/market.py`, `features/microstructure.py` |
| CrossExchangeOpportunity | Opportunité d'arbitrage inter-venues | `arbitrage/hyperliquid_cex_spread_scanner.py` |
| FundingOpportunity | Opportunité de funding/carry | `funding/funding_rate_scanner.py` |

## Règle de provenance (tâche 56)
Chaque objet transportant de la donnée doit porter :
`source` ∈ {live, snapshot, fixture, mock, derived}, `timestamp`, `freshness_ms`,
`evidence_refs`. Donnée manquante/vieille ⇒ `INSUFFICIENT_DATA` / `NO_TRADE`.
Présent dans le runtime : `evidence_refs`/`evidence_hash`, `INSUFFICIENT_DATA`,
horodatage + fraîcheur (agent_tools/readonly_inspectors, dashboard_truth/metric_provenance).

## Definition of Done (tâche 62)
Un module n'est **fini** que s'il est : branché dans un flux réel + testé + documenté +
visible dans CLI/dashboard/audit/report. Sinon il est marqué **PARTIAL_NOT_WIRED**.

## Statut
- **54 (contrats)** : DONE (recensement + emplacements figés).
- **56 (provenance)** : DONE (primitives présentes) ; à durcir : uniformiser `freshness_ms`
  sur tous les contrats (certains utilisent `age_ms`/`stale_ms`).
- **62 (DoD)** : DONE (règle écrite, appliquée aux statuts du progress).
- Reste (64) : tests de sérialisation round-trip par contrat — à écrire côté Windows.
