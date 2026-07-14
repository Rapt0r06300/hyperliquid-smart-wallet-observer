from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from hl_observer.hyperliquid.rest_info_client import HyperliquidInfoClient
from hl_observer.market.liquidation_map import construire_carte, parser_positions, resume
from hl_observer.testnet.models import unix_ms


@dataclass(frozen=True, slots=True)
class MainnetObservation:
    source: str
    all_mids: dict[str, float]
    l2_books: dict[str, dict[str, Any]] = field(default_factory=dict)
    wallet_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    wallet_fills: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    # #372 / X-11 : OU le flux FORCE tombera. (Il DIT ou, pas si c'est rentable -- voir le
    # champ `avertissement` du resume.)
    carte_liquidations: dict[str, Any] = field(default_factory=dict)
    observed_at_ms: int = field(default_factory=unix_ms)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MainnetReadOnlyObserver:
    """Reads Hyperliquid mainnet public/read-only data only."""

    def __init__(self, client: HyperliquidInfoClient | None = None) -> None:
        self.client = client or HyperliquidInfoClient()

    async def observe(
        self,
        *,
        coins: list[str] | None = None,
        wallets: list[str] | None = None,
        include_l2: bool = True,
        include_wallet_fills: bool = False,
    ) -> MainnetObservation:
        errors: list[str] = []
        mids: dict[str, float] = {}
        l2_books: dict[str, dict[str, Any]] = {}
        wallet_states: dict[str, dict[str, Any]] = {}
        wallet_fills: dict[str, list[dict[str, Any]]] = {}

        try:
            raw_mids = await self.client.all_mids()
            mids = {str(coin).upper(): float(price) for coin, price in raw_mids.items()}
        except Exception as exc:  # noqa: BLE001 - observer must return honest partial state.
            errors.append(f"all_mids_failed:{exc}")

        selected_coins = [coin.upper() for coin in (coins or list(mids.keys())[:5])]
        if include_l2:
            for coin in selected_coins:
                try:
                    l2_books[coin] = await self.client.l2_book(coin)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"l2_book_failed:{coin}:{exc}")

        # 🔴 #372 / X-11 -- LA DONNEE QU'ON RECEVAIT ET QU'ON EFFACAIT (branche le 2026-07-13).
        #
        # J'ai ecrit TROIS FOIS que la carte des liquidations etait « bloquee sur une donnee qu'on
        # ne collecte pas ». **FAUX.** `clearinghouseState` -- l'appel juste au-dessus -- rend
        # `liquidationPx` pour chaque position. Et ce mot n'apparaissait NULLE PART dans le code :
        # `snapshot_service` ne gardait que `coin / szi / entryPx`.
        #
        # *Ce n'etait pas une donnee manquante. C'etait une donnee RECUE ET EFFACEE.*
        #
        # Un liquide ne SAIT rien : il SUBIT. Son flux est donc **NON INFORME** -- l'exact inverse
        # du fill d'un leader (contrarien, mesure a -7,97 bps). C'est la seule autre famille de
        # signal hors zone morte.
        positions_forcees: list = []

        for wallet in wallets or []:
            try:
                etat = await self.client.clearinghouse_state(wallet)
                wallet_states[wallet] = etat
                positions_forcees.extend(parser_positions(wallet, etat))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"clearinghouse_state_failed:{wallet}:{exc}")
            if include_wallet_fills:
                try:
                    wallet_fills[wallet] = await self.client.user_fills(wallet)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"user_fills_failed:{wallet}:{exc}")

        # La carte : OU le flux force tombera, et pour combien.
        # ⚠️ Elle dit OU -- **pas** si c'est rentable de le prendre. Ce test-la (le depassement
        # domine-t-il l'inventaire ?) est EXACTEMENT celui qui a tue le market making (T1b), et
        # **il n'est pas fait** : on n'a aucun historique de liquidationPx. Il commence
        # maintenant.
        try:
            prix = {c.upper(): float(v) for c, v in mids.items()}
        except (TypeError, ValueError):
            prix = {}
        grappes = construire_carte(positions_forcees, prix) if positions_forcees else []

        # X-11: PERSISTER le snapshot. Sans historique, la mesure (liquidation_cascade)
        # est impossible pour toujours. L'enregistrement n'a JAMAIS le droit de casser
        # l'observation -- et n'enregistre que ce qu'on VOIT (carte borgne, borne basse).
        if grappes:
            try:
                from hl_observer.market.liquidation_recorder import enregistrer_grappes
                from hl_observer.runtime.session_identity import session_courante
                enregistrer_grappes(grappes, ts_ms=unix_ms(), session_id=session_courante())
            except Exception:  # noqa: BLE001
                pass

        return MainnetObservation(
            source="hyperliquid_mainnet_readonly",
            all_mids=mids,
            l2_books=l2_books,
            wallet_states=wallet_states,
            wallet_fills=wallet_fills,
            errors=errors,
            carte_liquidations=resume(grappes),
        )
