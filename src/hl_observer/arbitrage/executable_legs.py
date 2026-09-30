"""Q2 -- L'ARBITRAGE SE JUGE SUR DES JAMBES EXECUTABLES. JAMAIS SUR LE MID.

    Le mid est un prix auquel PERSONNE ne trade.

C'est la moyenne de deux prix qu'on ne peut pas avoir : on achete a l'ASK, on vend au BID.
Un ecart de mid entre deux venues n'est donc pas un profit -- c'est une illusion d'optique,
et on peut chiffrer EXACTEMENT de combien elle ment.

LE THEOREME (demontre, et teste dans `tests/test_executable_legs.py`)
---------------------------------------------------------------------
Pour un aller-retour « acheter sur A, vendre sur B » :

    edge_mid  = mid_B  - mid_A
    edge_reel = bid_B  - ask_A

    edge_mid - edge_reel = (ask_B - bid_B)/2 + (ask_A - bid_A)/2
                         = demi_spread_B + demi_spread_A

**Le mid surestime tout arbitrage d'exactement un demi-spread PAR JAMBE.** Toujours. Sans
exception. Ce n'est pas une approximation prudente : c'est une identite algebrique.

Consequence concrete : deux venues affichant 20 bps d'ecart de mid, avec 12 bps de spread
chacune, offrent en realite 20 - 12 = **8 bps** avant meme le premier centime de frais. Et notre
detecteur, lui, laissait passer les 20.

CE QU'ON REFUSE ICI, ET POURQUOI
--------------------------------
1. **Le mid.** Voir ci-dessus. On calcule sur bid/ask, ou on ne calcule pas.

2. **La liquidite INVENTEE.** Traverser un carnet, c'est manger les niveaux un par un. Si le
   notionnel demande depasse ce que le carnet VISIBLE contient, la reponse honnete est
   « ce trade n'est pas executable » -- surtout pas « supposons que le dernier niveau se
   repete a l'infini ». C'etait le bug de `compute_book_costs` : il extrapolait au prix du
   dernier niveau, ce qui SOUS-ESTIME le slippage exactement dans le cas ou le slippage
   compte, c'est-a-dire quand le carnet est mince.

3. **Le meilleur prix comme prix moyen.** Meme quand le carnet est assez profond, on ne
   remplit pas tout au top-of-book. Le prix qui compte est le **VWAP des niveaux traverses**.

Module PUR : aucune I/O, aucun reseau, aucun ordre. Simulation paper uniquement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------- sens

ACHAT = "ACHAT"   # on traverse les ASKS (on subit le cote vendeur)
VENTE = "VENTE"   # on traverse les BIDS (on subit le cote acheteur)

# --------------------------------------------------------------------------- refus

JAMBE_OK = "JAMBE_EXECUTABLE"
JAMBE_CARNET_VIDE = "JAMBE_CARNET_VIDE"
JAMBE_PRIX_INVALIDE = "JAMBE_PRIX_INVALIDE"
JAMBE_PROFONDEUR_INSUFFISANTE = "JAMBE_PROFONDEUR_INSUFFISANTE"
JAMBE_SENS_INCONNU = "JAMBE_SENS_INCONNU"
JAMBE_NOTIONAL_INVALIDE = "JAMBE_NOTIONAL_INVALIDE"

ARB_OK = "ARBITRAGE_EXECUTABLE"
ARB_AUCUN_SENS_EXECUTABLE = "ARBITRAGE_AUCUN_SENS_EXECUTABLE"
ARB_MEME_SOURCE = "ARBITRAGE_UNE_SEULE_SOURCE"
ARB_EDGE_NEGATIF = "ARBITRAGE_EDGE_NET_NEGATIF_APRES_COUTS"
ARB_MID_SEULEMENT = "ARBITRAGE_VISIBLE_SUR_LE_MID_MAIS_PAS_EXECUTABLE"


# --------------------------------------------------------------------------- une jambe


@dataclass(frozen=True, slots=True)
class Jambe:
    """Une jambe REELLE : ce qu'on obtient vraiment en traversant le carnet."""

    executable: bool
    sens: str
    raison: str
    prix_moyen: float | None = None          # VWAP des niveaux REELLEMENT traverses
    meilleur_prix: float | None = None       # top-of-book (pour mesurer le slippage)
    slippage_bps: float | None = None        # ecart VWAP vs top-of-book, en bps
    notional_demande_usd: float = 0.0
    notional_disponible_usd: float = 0.0     # ce que le carnet VISIBLE peut absorber
    niveaux_traverses: int = 0
    quantite: float | None = None

    def as_dict(self) -> dict:
        return {
            "executable": self.executable,
            "sens": self.sens,
            "raison": self.raison,
            "prix_moyen": self.prix_moyen,
            "meilleur_prix": self.meilleur_prix,
            "slippage_bps": self.slippage_bps,
            "notional_demande_usd": self.notional_demande_usd,
            "notional_disponible_usd": self.notional_disponible_usd,
            "niveaux_traverses": self.niveaux_traverses,
        }


def _refus_jambe(sens: str, raison: str, notional: float = 0.0) -> Jambe:
    return Jambe(executable=False, sens=sens, raison=raison, notional_demande_usd=notional)


def profondeur_disponible_usd(niveaux: list[tuple[float, float]] | None) -> float:
    """Combien de dollars le carnet VISIBLE peut reellement absorber."""
    total = 0.0
    for px, sz in niveaux or ():
        try:
            p, s = float(px), float(sz)
        except (TypeError, ValueError):
            continue
        if p > 0.0 and s > 0.0:
            total += p * s
    return total


def jambe_executable(
    niveaux: list[tuple[float, float]] | None,
    *,
    sens: str,
    notional_usd: float,
) -> Jambe:
    """Traverse le carnet pour `notional_usd` et rend le prix VRAIMENT obtenu.

    `niveaux` = [(prix, taille), ...] dans l'ordre ou on les mange :
      * ACHAT -> les ASKS, du moins cher au plus cher ;
      * VENTE -> les BIDS, du plus cher au moins cher.

    🚩 NE JAMAIS EXTRAPOLER. Si le carnet visible ne contient pas assez de liquidite pour le
    notionnel demande, la jambe est REFUSEE (`JAMBE_PROFONDEUR_INSUFFISANTE`). Prolonger le
    dernier niveau a l'infini -- ce que faisait `compute_book_costs` -- revient a inventer de
    la liquidite, et a sous-estimer le slippage PRECISEMENT quand le carnet est mince, donc
    precisement quand ca compte.
    """
    sens = (sens or "").strip().upper()
    if sens not in (ACHAT, VENTE):
        return _refus_jambe(sens, JAMBE_SENS_INCONNU)

    try:
        cible = float(notional_usd)
    except (TypeError, ValueError):
        return _refus_jambe(sens, JAMBE_NOTIONAL_INVALIDE)
    if not (cible > 0.0) or cible != cible or cible in (float("inf"), float("-inf")):
        return _refus_jambe(sens, JAMBE_NOTIONAL_INVALIDE, cible if cible == cible else 0.0)

    propres: list[tuple[float, float]] = []
    for px, sz in niveaux or ():
        try:
            p, s = float(px), float(sz)
        except (TypeError, ValueError):
            continue
        if p > 0.0 and s > 0.0 and p == p and s == s:
            propres.append((p, s))
    if not propres:
        return _refus_jambe(sens, JAMBE_CARNET_VIDE, cible)

    # L'ordre de traversee est impose par le sens -- on ne fait PAS confiance a l'appelant.
    propres.sort(key=lambda lv: lv[0], reverse=(sens == VENTE))
    meilleur = propres[0][0]
    if meilleur <= 0.0:
        return _refus_jambe(sens, JAMBE_PRIX_INVALIDE, cible)

    dispo = profondeur_disponible_usd(propres)
    if dispo + 1e-9 < cible:
        return Jambe(
            executable=False,
            sens=sens,
            raison=JAMBE_PROFONDEUR_INSUFFISANTE,
            meilleur_prix=meilleur,
            notional_demande_usd=cible,
            notional_disponible_usd=round(dispo, 8),
            niveaux_traverses=len(propres),
        )

    reste = cible
    quantite = 0.0
    traverses = 0
    for px, sz in propres:
        if reste <= 1e-12:
            break
        pris_usd = min(reste, px * sz)
        quantite += pris_usd / px
        reste -= pris_usd
        traverses += 1

    if quantite <= 0.0:
        return _refus_jambe(sens, JAMBE_PRIX_INVALIDE, cible)

    vwap = cible / quantite
    # ACHAT : payer PLUS cher que le top = slippage positif.
    # VENTE : encaisser MOINS = slippage positif aussi. Le slippage est toujours un COUT.
    brut = (vwap - meilleur) if sens == ACHAT else (meilleur - vwap)
    slip_bps = max(0.0, brut / meilleur * 10_000.0)

    return Jambe(
        executable=True,
        sens=sens,
        raison=JAMBE_OK,
        prix_moyen=vwap,
        meilleur_prix=meilleur,
        slippage_bps=round(slip_bps, 6),
        notional_demande_usd=cible,
        notional_disponible_usd=round(dispo, 8),
        niveaux_traverses=traverses,
        quantite=quantite,
    )


# --------------------------------------------------------------------------- le theoreme


def edge_mid_bps(*, a_bid: float, a_ask: float, b_bid: float, b_ask: float) -> float:
    """Ce que le detecteur AFFICHAIT : l'ecart de mid. Un chiffre qu'on ne peut pas encaisser."""
    mid_a = (float(a_bid) + float(a_ask)) / 2.0
    mid_b = (float(b_bid) + float(b_ask)) / 2.0
    ref = (mid_a + mid_b) / 2.0
    if ref <= 0.0:
        return 0.0
    return (mid_b - mid_a) / ref * 10_000.0


def edge_top_of_book_bps(*, a_ask: float, b_bid: float, reference: float | None = None) -> float:
    """Ce qu'on peut VRAIMENT prendre au top-of-book : acheter A a l'ask, vendre B au bid."""
    ask, bid = float(a_ask), float(b_bid)
    ref = float(reference) if reference else (ask + bid) / 2.0
    if ref <= 0.0 or ask <= 0.0:
        return 0.0
    return (bid - ask) / ref * 10_000.0


def surestimation_du_mid_bps(*, a_bid: float, a_ask: float, b_bid: float, b_ask: float) -> float:
    """De combien le mid MENT, en bps. Identite : (spread_A + spread_B) / 2.

    Ce n'est pas une estimation. C'est exact, et c'est TOUJOURS >= 0 : le mid ne peut jamais
    SOUS-estimer un arbitrage. Il ne se trompe que dans un sens -- le sens qui fait trader.
    """
    mid_a = (float(a_bid) + float(a_ask)) / 2.0
    mid_b = (float(b_bid) + float(b_ask)) / 2.0
    ref = (mid_a + mid_b) / 2.0
    if ref <= 0.0:
        return 0.0
    demi_a = (float(a_ask) - float(a_bid)) / 2.0
    demi_b = (float(b_ask) - float(b_bid)) / 2.0
    return max(0.0, (demi_a + demi_b) / ref * 10_000.0)


# --------------------------------------------------------------------------- l'arbitrage


@dataclass(frozen=True, slots=True)
class ArbitrageExecutable:
    executable: bool
    coin: str
    raison: str
    source_achat: str = ""
    source_vente: str = ""
    prix_achat: float | None = None          # VWAP paye
    prix_vente: float | None = None          # VWAP encaisse
    notional_usd: float = 0.0
    edge_brut_bps: float | None = None       # sur les JAMBES, pas sur le mid
    frais_bps: float = 0.0
    edge_net_bps: float | None = None
    edge_sur_le_mid_bps: float | None = None      # le chiffre MENSONGER, pour comparaison
    surestimation_du_mid_bps: float | None = None  # de combien il ment
    jambe_achat: Jambe | None = None
    jambe_vente: Jambe | None = None
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def paper_only(self) -> bool:
        return True

    def as_dict(self) -> dict:
        return {
            "executable": self.executable,
            "coin": self.coin,
            "raison": self.raison,
            "source_achat": self.source_achat,
            "source_vente": self.source_vente,
            "prix_achat": self.prix_achat,
            "prix_vente": self.prix_vente,
            "notional_usd": self.notional_usd,
            "edge_brut_bps": self.edge_brut_bps,
            "frais_bps": self.frais_bps,
            "edge_net_bps": self.edge_net_bps,
            "edge_sur_le_mid_bps": self.edge_sur_le_mid_bps,
            "surestimation_du_mid_bps": self.surestimation_du_mid_bps,
            "jambe_achat": self.jambe_achat.as_dict() if self.jambe_achat else None,
            "jambe_vente": self.jambe_vente.as_dict() if self.jambe_vente else None,
            "paper_only": True,
            "real_execution": False,
        }


def _sens_unique(
    *,
    coin: str,
    source_achat: str,
    asks_achat: list[tuple[float, float]] | None,
    source_vente: str,
    bids_vente: list[tuple[float, float]] | None,
    notional_usd: float,
    frais_bps: float,
) -> ArbitrageExecutable:
    ja = jambe_executable(asks_achat, sens=ACHAT, notional_usd=notional_usd)
    jv = jambe_executable(bids_vente, sens=VENTE, notional_usd=notional_usd)

    if not ja.executable or not jv.executable:
        raisons = tuple(r for r in (ja.raison if not ja.executable else None,
                                    jv.raison if not jv.executable else None) if r)
        return ArbitrageExecutable(
            executable=False, coin=coin, raison=raisons[0] if raisons else ARB_AUCUN_SENS_EXECUTABLE,
            source_achat=source_achat, source_vente=source_vente, notional_usd=float(notional_usd),
            frais_bps=float(frais_bps), jambe_achat=ja, jambe_vente=jv, reason_codes=raisons,
        )

    pa = float(ja.prix_moyen or 0.0)
    pv = float(jv.prix_moyen or 0.0)
    ref = (pa + pv) / 2.0
    brut = (pv - pa) / ref * 10_000.0 if ref > 0.0 else 0.0
    net = brut - max(0.0, float(frais_bps))

    return ArbitrageExecutable(
        executable=True, coin=coin, raison=ARB_OK,
        source_achat=source_achat, source_vente=source_vente,
        prix_achat=pa, prix_vente=pv, notional_usd=float(notional_usd),
        edge_brut_bps=round(brut, 6), frais_bps=round(max(0.0, float(frais_bps)), 6),
        edge_net_bps=round(net, 6),
        jambe_achat=ja, jambe_vente=jv,
    )


def arbitrage_executable(
    *,
    coin: str,
    source_a: str,
    bids_a: list[tuple[float, float]] | None,
    asks_a: list[tuple[float, float]] | None,
    source_b: str,
    bids_b: list[tuple[float, float]] | None,
    asks_b: list[tuple[float, float]] | None,
    notional_usd: float,
    frais_bps: float = 0.0,
    min_edge_net_bps: float = 0.0,
) -> ArbitrageExecutable:
    """Les DEUX sens sont essayes ; on garde le meilleur qui soit REELLEMENT executable.

    Le resultat porte AUSSI le chiffre qu'aurait donne le mid, et l'ecart entre les deux --
    pour qu'on ne puisse plus jamais confondre « visible » et « encaissable ».
    """
    coin = (coin or "").strip().upper()
    if (source_a or "").strip().lower() == (source_b or "").strip().lower():
        return ArbitrageExecutable(
            executable=False, coin=coin, raison=ARB_MEME_SOURCE,
            source_achat=source_a, source_vente=source_b, notional_usd=float(notional_usd),
            reason_codes=(ARB_MEME_SOURCE,),
        )

    # sens 1 : acheter A (traverser ses asks), vendre B (traverser ses bids)
    ab = _sens_unique(coin=coin, source_achat=source_a, asks_achat=asks_a,
                      source_vente=source_b, bids_vente=bids_b,
                      notional_usd=notional_usd, frais_bps=frais_bps)
    # sens 2 : acheter B, vendre A
    ba = _sens_unique(coin=coin, source_achat=source_b, asks_achat=asks_b,
                      source_vente=source_a, bids_vente=bids_a,
                      notional_usd=notional_usd, frais_bps=frais_bps)

    candidats = [r for r in (ab, ba) if r.executable]
    if not candidats:
        pire = ab if ab.reason_codes else ba
        return ArbitrageExecutable(
            executable=False, coin=coin, raison=pire.raison or ARB_AUCUN_SENS_EXECUTABLE,
            source_achat=pire.source_achat, source_vente=pire.source_vente,
            notional_usd=float(notional_usd), frais_bps=float(frais_bps),
            jambe_achat=pire.jambe_achat, jambe_vente=pire.jambe_vente,
            reason_codes=pire.reason_codes or (ARB_AUCUN_SENS_EXECUTABLE,),
        )

    meilleur = max(candidats, key=lambda r: float(r.edge_net_bps or 0.0))

    # Le chiffre MENSONGER, calcule sur les MEMES carnets, pour comparaison.
    mid_bps: float | None = None
    surest: float | None = None
    if bids_a and asks_a and bids_b and asks_b:
        a_bid, a_ask = float(bids_a[0][0]), float(asks_a[0][0])
        b_bid, b_ask = float(bids_b[0][0]), float(asks_b[0][0])
        if meilleur.source_achat == source_a:
            mid_bps = edge_mid_bps(a_bid=a_bid, a_ask=a_ask, b_bid=b_bid, b_ask=b_ask)
        else:
            mid_bps = edge_mid_bps(a_bid=b_bid, a_ask=b_ask, b_bid=a_bid, b_ask=a_ask)
        surest = surestimation_du_mid_bps(a_bid=a_bid, a_ask=a_ask, b_bid=b_bid, b_ask=b_ask)

    net = float(meilleur.edge_net_bps or 0.0)
    accepte = net >= float(min_edge_net_bps)
    raison = ARB_OK if accepte else ARB_EDGE_NEGATIF
    if not accepte and mid_bps is not None and mid_bps >= float(min_edge_net_bps):
        # LE cas qui nous interesse : le mid criait « opportunite », la realite dit non.
        raison = ARB_MID_SEULEMENT

    return ArbitrageExecutable(
        executable=accepte,
        coin=coin,
        raison=raison,
        source_achat=meilleur.source_achat,
        source_vente=meilleur.source_vente,
        prix_achat=meilleur.prix_achat,
        prix_vente=meilleur.prix_vente,
        notional_usd=float(notional_usd),
        edge_brut_bps=meilleur.edge_brut_bps,
        frais_bps=meilleur.frais_bps,
        edge_net_bps=meilleur.edge_net_bps,
        edge_sur_le_mid_bps=round(mid_bps, 6) if mid_bps is not None else None,
        surestimation_du_mid_bps=round(surest, 6) if surest is not None else None,
        jambe_achat=meilleur.jambe_achat,
        jambe_vente=meilleur.jambe_vente,
        reason_codes=() if accepte else (raison,),
    )


__all__ = [
    "ACHAT", "VENTE",
    "JAMBE_OK", "JAMBE_CARNET_VIDE", "JAMBE_PRIX_INVALIDE",
    "JAMBE_PROFONDEUR_INSUFFISANTE", "JAMBE_SENS_INCONNU", "JAMBE_NOTIONAL_INVALIDE",
    "ARB_OK", "ARB_AUCUN_SENS_EXECUTABLE", "ARB_MEME_SOURCE", "ARB_EDGE_NEGATIF",
    "ARB_MID_SEULEMENT",
    "Jambe", "ArbitrageExecutable",
    "jambe_executable", "arbitrage_executable", "profondeur_disponible_usd",
    "edge_mid_bps", "edge_top_of_book_bps", "surestimation_du_mid_bps",
]
