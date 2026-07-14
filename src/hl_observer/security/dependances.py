"""IMPROVE-24 (#131) -- L'AUDIT DES DEPENDANCES. Mais pas celui qu'on croit.

L'audit de dependances "classique" cherche des CVE. Ici, la question est autre, et elle est
BEAUCOUP plus importante pour ce projet :

    >>> UNE BIBLIOTHEQUE CAPABLE D'ENVOYER UN ORDRE REEL EST-ELLE INSTALLEE ? <<<

Parce que la ligne dure du projet n'est pas « on n'ecrit pas de code d'execution ». Elle est
« l'execution reelle est IMPOSSIBLE ». Or on ne peut pas signer une transaction sans une
bibliotheque de signature, ni frapper `/exchange` sans un client. **Tant qu'aucune de ces
bibliotheques n'est presente, un ordre reel est physiquement hors de portee -- meme si quelqu'un
ecrivait le code pour, meme par accident, meme sous pression.**

C'est un garde-fou d'un genre different de tous les autres du projet : les autres empechent le
code de DECIDER de trader. Celui-ci empeche la machine d'en avoir les MOYENS.

    Un audit de secrets protege les CLES.
    Un audit de code protege les APPELS.
    Cet audit-ci protege la CAPACITE.

🚨 `mackinac/dex-exec` (trouve dans la moisson, H-134) EXECUTE DE VRAIS ORDRES. Il est nomme ici
explicitement, pour que personne -- humain ou agent -- ne l'installe « juste pour regarder ».

Module PUR : `auditer` ne touche ni le disque ni le reseau. On lui PASSE la liste des paquets.
C'est ce qui le rend testable sans dependre de l'environnement reel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# CE QUI DONNE LA CAPACITE D'EXECUTER. Trois familles, trois raisons distinctes.
# ---------------------------------------------------------------------------

#: Clients qui parlent a un exchange et savent lui envoyer un ORDRE.
CLIENTS_D_EXECUTION: dict[str, str] = {
    "dex-exec": "🚨 EXECUTE DE VRAIS ORDRES (Hyperliquid perp + Uniswap V3). Jamais, sous aucun pretexte.",
    "dexec": "🚨 alias/module de dex-exec.",
    "hyperliquid-python-sdk": "SDK officiel : il porte `exchange.order(...)`, donc la capacite d'ordre reel.",
    "ccxt": "Client multi-exchange : `create_order` sur ~100 venues.",
    "ccxt-pro": "Idem, version temps reel.",
    "python-binance": "Client d'execution Binance.",
    "pybit": "Client d'execution Bybit.",
    "krakenex": "Client d'execution Kraken.",
}

#: Bibliotheques de SIGNATURE. Sans elles, aucune transaction ne peut etre signee.
SIGNATURE_ET_CLES: dict[str, str] = {
    "eth-account": "Signe des transactions Ethereum/Arbitrum a partir d'une cle privee.",
    "eth-keys": "Manipulation de cles privees secp256k1.",
    "web3": "Envoi de transactions on-chain (`send_raw_transaction`).",
    "mnemonic": "Derivation de seed BIP-39 -- donc reconstitution d'une cle privee.",
    "bip-utils": "Idem (BIP-32/39/44).",
    "hdwallet": "Derivation de portefeuilles hierarchiques.",
}

#: Portefeuilles / custody.
PORTEFEUILLES: dict[str, str] = {
    "walletconnect": "Connexion d'un vrai portefeuille pour AGIR.",
    "metamask": "Idem.",
}

INTERDITS: dict[str, str] = {**CLIENTS_D_EXECUTION, **SIGNATURE_ET_CLES, **PORTEFEUILLES}

MOTIF_REFUS = "PAQUET_CAPABLE_D_EXECUTER_UN_ORDRE_REEL"


@dataclass(frozen=True, slots=True)
class Trouvaille:
    paquet: str
    famille: str
    motif: str


@dataclass(frozen=True, slots=True)
class VerdictDependances:
    ok: bool
    n_paquets: int
    trouvailles: tuple[Trouvaille, ...] = field(default_factory=tuple)

    @property
    def alerte(self) -> str:
        if self.ok:
            return ""
        return (
            "%s : %d paquet(s) installe(s) donnent la CAPACITE d'executer un ordre reel :\n  %s"
            % (
                MOTIF_REFUS,
                len(self.trouvailles),
                "\n  ".join("%s -- %s" % (t.paquet, t.motif) for t in self.trouvailles),
            )
        )

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "n_paquets": self.n_paquets,
            "interdits_presents": [t.paquet for t in self.trouvailles],
            "alerte": self.alerte,
        }


def _normaliser(nom: str) -> str:
    """PyPI considere `-` et `_` equivalents, et la casse indifferente.

    Sans ca, `Eth_Account` passerait a travers un test sur `eth-account`. C'est exactement le
    genre de trou par lequel une capacite interdite rentre sans que personne ne s'en apercoive.
    """
    return str(nom or "").strip().lower().replace("_", "-")


def _famille(paquet: str) -> str:
    if paquet in CLIENTS_D_EXECUTION:
        return "CLIENT_D_EXECUTION"
    if paquet in SIGNATURE_ET_CLES:
        return "SIGNATURE_OU_CLE"
    if paquet in PORTEFEUILLES:
        return "PORTEFEUILLE"
    return "?"


def auditer(paquets: list[str] | tuple[str, ...]) -> VerdictDependances:
    """Fonction PURE. On lui donne les noms de paquets ; elle rend un verdict.

    Aucun acces disque, aucun reseau : c'est ce qui permet de la tester avec un environnement
    FABRIQUE (« et si quelqu'un installait ccxt demain ? ») sans avoir a l'installer pour de vrai.
    """
    vus = {_normaliser(p) for p in paquets}
    trouvailles = tuple(
        Trouvaille(paquet=p, famille=_famille(p), motif=motif)
        for p, motif in sorted(INTERDITS.items())
        if p in vus
    )
    return VerdictDependances(ok=not trouvailles, n_paquets=len(vus), trouvailles=trouvailles)


def paquets_installes() -> list[str]:
    """La SEULE fonction impure du module. Isolee pour que tout le reste reste testable."""
    try:
        from importlib.metadata import distributions
    except Exception:  # pragma: no cover
        return []
    noms: list[str] = []
    for d in distributions():
        try:
            nom = d.metadata["Name"]
        except Exception:  # pragma: no cover
            nom = None
        if nom:
            noms.append(_normaliser(nom))
    return sorted(set(noms))


def auditer_l_environnement() -> VerdictDependances:
    """Le verdict sur l'environnement REEL. Appele par `safety-audit`."""
    return auditer(paquets_installes())


__all__ = [
    "CLIENTS_D_EXECUTION",
    "SIGNATURE_ET_CLES",
    "PORTEFEUILLES",
    "INTERDITS",
    "MOTIF_REFUS",
    "Trouvaille",
    "VerdictDependances",
    "auditer",
    "auditer_l_environnement",
    "paquets_installes",
]
