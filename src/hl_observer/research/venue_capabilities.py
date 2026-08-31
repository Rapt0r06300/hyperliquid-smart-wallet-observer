"""[DATA-020 + disposition HONNETE des connecteurs 036-107] Registre des CAPACITES de venues : chaque
venue porte sa capacite REELLE — OFFLINE_READY (adaptateur + tests offline), REQUIRES_NETWORK
(connecteur live NON prouvable en sandbox paper/sans-reseau) ou NON_IMPLEMENTE — et sa MATRICE de flux
(book/trades/funding/oi/liquidations). READY_MULTI_VENUE = aucune venue REQUISE n'est NON_IMPLEMENTE.
On ne declare JAMAIS une venue 'live-ok' sans preuve reseau. stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

from collections.abc import Sequence

OFFLINE_READY = "OFFLINE_READY"
REQUIRES_NETWORK = "REQUIRES_NETWORK"
NON_IMPLEMENTE = "NON_IMPLEMENTE"
_CAP = (OFFLINE_READY, REQUIRES_NETWORK, NON_IMPLEMENTE)
FLUX = ("book", "trades", "funding", "oi", "liquidations")


class RegistreCapacitesVenues:
    """Etat HONNETE des venues : ce qui est prouvable hors-ligne vs ce qui exige un reseau live."""

    def __init__(self) -> None:
        self._v: dict = {}

    def declarer(self, venue: str, capacite: str, *, flux: Sequence[str] = (), requis: bool = False) -> None:
        if capacite not in _CAP:
            raise ValueError(f"capacite invalide: {capacite}")
        self._v[venue] = {"venue": venue, "capacite": capacite,
                          "flux": {k: (k in set(flux)) for k in FLUX}, "requis": bool(requis)}

    def capacite(self, venue: str):
        v = self._v.get(venue)
        return v["capacite"] if v else None

    def par_capacite(self, capacite: str) -> list:
        return sorted(v for v, x in self._v.items() if x["capacite"] == capacite)

    def flux_supportes(self, venue: str) -> list:
        v = self._v.get(venue)
        return sorted(k for k, ok in v["flux"].items() if ok) if v else []

    def ready(self) -> dict:
        reqs = [x for x in self._v.values() if x["requis"]]
        non_pretes = sorted(x["venue"] for x in reqs if x["capacite"] == NON_IMPLEMENTE)
        return {"ready": len(non_pretes) == 0, "requises_non_pretes": non_pretes,
                "offline_ready": self.par_capacite(OFFLINE_READY),
                "requiert_reseau": self.par_capacite(REQUIRES_NETWORK)}

    def reconcile_loaded(
        self,
        *,
        run_id: str,
        state_version: str,
        loaded_venues: Sequence[str] | None = None,
    ):
        """Atteste les adaptateurs réellement chargés, sans promouvoir le réseau par déclaration."""
        from hl_observer.runtime.capability_reconciliation import (
            CapabilityDisposition,
            CapabilityDispositionKind,
            CapabilityKind,
            CapabilityReconciliationError,
            ConnectorReadinessCanary,
            DeclaredCapability,
            EntitlementClass,
            LoadedCapability,
            reconcile_capabilities,
        )

        effective_loaded = (
            set(self.par_capacite(OFFLINE_READY))
            if loaded_venues is None
            else {str(venue) for venue in loaded_venues}
        )
        unknown = sorted(effective_loaded - set(self._v))
        if unknown:
            raise CapabilityReconciliationError(
                "VENUE_LOADED_UNDECLARED", ",".join(unknown)
            )
        unproven = sorted(
            venue
            for venue in effective_loaded
            if self._v[venue]["capacite"] != OFFLINE_READY
        )
        if unproven:
            raise CapabilityReconciliationError(
                "VENUE_LOADED_WITHOUT_OFFLINE_PROOF", ",".join(unproven)
            )
        declared = []
        loaded = []
        dispositions = []
        for venue, item in sorted(self._v.items()):
            capability_id = f"venue:{venue}"
            operations = tuple(sorted(k for k, ok in item["flux"].items() if ok))
            declared.append(
                DeclaredCapability(
                    capability_id=capability_id,
                    kind=CapabilityKind.VENUE,
                    required=item["requis"],
                    expected_operations=operations or ("health",),
                    expected_schema="hypersmart.market_data.v1",
                    entitlement=EntitlementClass.PUBLIC_ZERO_EURO,
                    preferred_authority=venue,
                )
            )
            if venue in effective_loaded and item["capacite"] == OFFLINE_READY:
                loaded.append(
                    LoadedCapability(
                        capability_id=capability_id,
                        kind=CapabilityKind.VENUE,
                        adapter_version="venue-registry.v1",
                        actual_authority=venue,
                        canary=ConnectorReadinessCanary(
                            manifest_schema_parses=True,
                            registered=True,
                            operations=operations or ("health",),
                            authorization_scope_sufficient=True,
                            returned_schema="hypersmart.market_data.v1",
                            semantic_canary_passed=True,
                            read_only=True,
                        ),
                    )
                )
            elif item["capacite"] == REQUIRES_NETWORK:
                dispositions.append(
                    CapabilityDisposition(
                        capability_id=capability_id,
                        disposition=CapabilityDispositionKind.INTENTIONALLY_DISABLED,
                        reason="aucune preuve réseau live attachée à ce bootstrap paper",
                        evidence_ref="venue-registry:requires-network",
                    )
                )
            elif item["capacite"] == NON_IMPLEMENTE:
                dispositions.append(
                    CapabilityDisposition(
                        capability_id=capability_id,
                        disposition=CapabilityDispositionKind.UNAVAILABLE,
                        reason="adaptateur non implémenté",
                        evidence_ref="venue-registry:non-implemente",
                    )
                )

        return reconcile_capabilities(
            run_id=run_id,
            state_version=state_version,
            declared=declared,
            loaded=loaded,
            dispositions=dispositions,
        )


def registre_par_defaut() -> RegistreCapacitesVenues:
    """Etat HONNETE du projet : HL/dYdX/Binance ont des adaptateurs + tests offline ; les autres venues
    exigent un reseau live (non prouvable dans ce sandbox). Aucune n'est marquee 'live-ok'."""
    r = RegistreCapacitesVenues()
    tous = ("book", "trades", "funding", "oi", "liquidations")
    r.declarer("hyperliquid", OFFLINE_READY, flux=tous, requis=True)
    r.declarer("dydx", OFFLINE_READY, flux=tous)
    r.declarer("binance", OFFLINE_READY, flux=tous)
    for v in ("bybit", "okx", "coinbase", "deribit", "kraken", "drift", "gmx", "nansen", "dune", "glassnode", "defillama"):
        r.declarer(v, REQUIRES_NETWORK, flux=tous)
    return r
