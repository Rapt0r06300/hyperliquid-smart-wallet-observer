"""#362 / X-01 — les dépôts Arbitrum → Hyperliquid : le SEUL signal PRÉ-exécution.

`COPY_TRADING_NO_EDGE` designe elle-meme sa sortie : *« un acces au flux d'ordres AVANT
execution, pas apres »*. **Un depot precede le trade.**

🔴 ET CE FICHIER VERROUILLE LE REFUS D'INVENTER L'ADRESSE DU PONT. Lire les depots du MAUVAIS
contrat produirait un signal parfaitement faux -- et parfaitement silencieux.

Aucun ordre reel. Lecture on-chain seule.
"""
from __future__ import annotations

import pytest

from hl_observer.collection.arbitrum_deposits import (
    MIN_DEPOT_USD,
    TOPIC_TRANSFER,
    AdresseDuPontNonVerifiee,
    etat_de_la_piste,
    parser_logs,
    requete_logs,
    valider_adresse_du_pont,
)

PONT = "0x" + "ab" * 20            # une adresse de TEST, jamais utilisee en vrai
AUTRE = "0x" + "cd" * 20


def _topic_addr(a: str) -> str:
    return "0x" + "0" * 24 + a[2:]


def _log(depuis: str, vers: str, montant_brut: int, *, bloc: int = 100, tx: str = "0xdead"):
    return {
        "topics": [TOPIC_TRANSFER, _topic_addr(depuis), _topic_addr(vers)],
        "data": hex(montant_brut),
        "blockNumber": hex(bloc),
        "transactionHash": tx,
    }


# ============================================================ 1. 🔴 LE REFUS D'INVENTER


@pytest.mark.parametrize("mauvaise", [None, "", "   ", "pas une adresse", "0x123", "0x" + "zz" * 20])
def test_SANS_adresse_VERIFIEE_le_module_REFUSE_de_collecter(mauvaise):
    """🔴 LE POINT LE PLUS IMPORTANT DE CE FICHIER.

    Je n'ai **pas** verifie l'adresse du pont Hyperliquid sur Arbitrum. L'ecrire « de memoire »
    serait une **donnee fabriquee presentee comme reelle** -- et elle ferait lire les depots du
    MAUVAIS contrat, produisant un signal faux **et silencieux**.

    *Une adresse non verifiee est PIRE qu'aucune adresse.*
    """
    with pytest.raises(AdresseDuPontNonVerifiee):
        valider_adresse_du_pont(mauvaise)


def test_aucune_adresse_de_pont_n_est_CODEE_EN_DUR_dans_le_module():
    """L'invariant : personne ne pourra glisser une adresse « par defaut » plus tard.

    Une valeur par defaut ici serait le pire des deux mondes : ca marcherait **silencieusement**,
    sur le mauvais contrat.
    """
    import inspect

    from hl_observer.collection import arbitrum_deposits as mod

    src = inspect.getsource(mod)
    # on cherche des litteraux 0x + 40 hex qui ne soient PAS le topic Transfer (32 octets)
    import re
    adresses = [
        m for m in re.findall(r"0x[0-9a-fA-F]{40}\b", src)
        if not TOPIC_TRANSFER.startswith(m)
    ]
    assert not adresses, (
        "🔴 une adresse est codee en dur dans le module : %s. On ne collecte JAMAIS depuis une "
        "adresse qu'on n'a pas verifiee." % adresses
    )


def test_une_adresse_BIEN_FORMEE_est_acceptee():
    assert valider_adresse_du_pont(PONT) == PONT.lower()


# ============================================================ 2. LE PARSING


def test_on_garde_les_depots_VERS_LE_PONT_et_RIEN_D_AUTRE():
    logs = [
        _log("0x" + "11" * 20, PONT, 50_000_000_000),      # 50 000 USDC -> GARDE
        _log("0x" + "22" * 20, AUTRE, 90_000_000_000),     # vers un AUTRE contrat -> ignore
    ]
    d = parser_logs(logs, adresse_du_pont=PONT)
    assert len(d) == 1
    assert d[0].montant_usd == pytest.approx(50_000.0)
    assert d[0].deposant == "0x" + "11" * 20


def test_la_POUSSIERE_est_ecartee_elle_n_annonce_aucun_trade():
    logs = [_log("0x" + "11" * 20, PONT, 5_000_000)]       # 5 USDC
    assert parser_logs(logs, adresse_du_pont=PONT) == []
    assert MIN_DEPOT_USD >= 1000.0


def test_un_log_CASSE_est_ECARTE_pas_devine():
    """*Un log qu'on ne comprend pas ne devient pas un depot de 0 $.*"""
    casses = [
        {},
        {"topics": []},
        {"topics": [TOPIC_TRANSFER]},                                     # pas assez de topics
        {"topics": ["0xautre_event", _topic_addr(PONT), _topic_addr(PONT)]},
        {"topics": [TOPIC_TRANSFER, _topic_addr("0x" + "11" * 20), _topic_addr(PONT)],
         "data": "PAS DU HEX"},
        "pas un dict",
    ]
    assert parser_logs(casses, adresse_du_pont=PONT) == []


def test_la_requete_RPC_est_CONSTRUITE_mais_JAMAIS_ENVOYEE():
    """Separer la CONSTRUCTION de l'ENVOI garantit qu'aucun appel reseau ne part d'un module de
    parsing -- et rend la requete verifiable."""
    r = requete_logs(PONT, du_bloc=100, au_bloc=200)
    assert r["method"] == "eth_getLogs"
    assert r["params"][0]["fromBlock"] == hex(100)
    assert r["params"][0]["topics"][0] == TOPIC_TRANSFER
    assert PONT[2:] in r["params"][0]["topics"][2]


def test_la_requete_REFUSE_AUSSI_une_adresse_non_verifiee():
    with pytest.raises(AdresseDuPontNonVerifiee):
        requete_logs("", du_bloc=1, au_bloc=2)


# ============================================================ 3. L'ETAT HONNETE


def test_l_etat_de_la_piste_DIT_que_la_mesure_N_EST_PAS_FAITE():
    """⚠️ L'instrument est ecrit. **La mesure ne l'est pas.** Un module qui laisserait croire le
    contraire serait une promesse de PnL. Interdit."""
    e = etat_de_la_piste([])
    assert e["mesure_faite"] is False
    assert "markout" in e["mesure_qui_trancherait"]
    assert "adresse du pont" in e["bloquant"]
    assert "aucun historique" in e["bloquant"].lower()
    assert e["real_execution"] is False
