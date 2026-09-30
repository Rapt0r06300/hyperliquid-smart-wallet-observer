"""#254 / IDEA-97 — LE SANDBOXING NE MANQUAIT PAS : IL ETAIT ECRIT ET DEBRANCHE (2026-07-13).

`security/mainnet_guard.assert_info_endpoint_only(url)` existe depuis des semaines. Elle a ete
ecrite POUR garantir qu'on ne frappe QUE l'endpoint `/info` de Hyperliquid.

    AST : **ZERO appelant.**

14e deguisement de la maladie du projet : *une capacite presente, un chainon manquant, et
personne qui se plaint.* On ne l'a pas remarque parce que `base_url` pointait DEJA sur `/info` --
le garde etait inutile **par chance**, pas par construction.

CE QUI CHANGE :
  * il est branche au **TRANSPORT** (`HyperliquidInfoClient._post_info`), pas chez l'appelant.
    Un garde chez l'appelant protege CET appelant. Un garde au transport protege **tous les
    appelants, y compris ceux qui n'existent pas encore.**
  * c'est le **1er controle RUNTIME** : les 8 controles de `safety-audit` sont STATIQUES (ils
    lisent le source). Celui-ci agit a l'instant ou l'octet allait partir.

Aucun ordre reel.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from hl_observer.hyperliquid.rest_info_client import (
    HyperliquidInfoClient,
    HyperliquidInfoError,
)
from hl_observer.security.mainnet_guard import (
    MainnetExecutionForbidden,
    assert_info_endpoint_only,
)

RACINE = Path(__file__).resolve().parents[1]
CLIENT = RACINE / "src" / "hl_observer" / "hyperliquid" / "rest_info_client.py"


# ============================================================ 1. LE GARDE MORD


@pytest.mark.parametrize("url", [
    "https://api.hyperliquid.xyz/exchange",          # 🚨 L'ENDPOINT D'EXECUTION
    "https://api.hyperliquid.xyz/",
    "https://api.hyperliquid.xyz/info/",             # le slash final compte
    "https://evil.example.com/info-mais-pas-vraiment",
    "",
])
def test_toute_URL_qui_n_est_PAS_slash_info_est_REFUSEE(url: str):
    with pytest.raises(MainnetExecutionForbidden):
        assert_info_endpoint_only(url)


def test_l_endpoint_info_LEGITIME_passe():
    assert_info_endpoint_only("https://api.hyperliquid.xyz/info")     # ne doit pas lever


# ============================================================ 2. LE CLIENT REFUSE VRAIMENT


def test_le_constructeur_refuse_deja_une_URL_qui_n_est_pas_info():
    """🚩 CORRECTION DE MA PROPRE AFFIRMATION (2026-07-13).

    J'ai d'abord ecrit que « le sandboxing etait ecrit et DEBRANCHE ». **A moitie faux, et il faut
    le dire.** La FONCTION `assert_info_endpoint_only` etait bien morte (0 appelant) -- mais une
    verification EQUIVALENTE existait deja, **codee en dur dans le constructeur**. Ce n'etait donc
    pas une absence de protection : c'etait une **duplication**, dont une moitie etait morte.

    *Verifier avant d'affirmer.* Je l'avais ecrit ce matin, et je viens de l'oublier ce soir.
    """
    with pytest.raises(HyperliquidInfoError):
        HyperliquidInfoClient(base_url="https://api.hyperliquid.xyz/execution-endpoint")


def test_LE_VRAI_TROU_reassigner_base_url_APRES_construction():
    """🔴 VOILA LE TROU REEL -- et il justifie le garde au TRANSPORT.

    Le garde du constructeur ne tire **qu'une fois**. Or `base_url` est un attribut **mutable** :

        client = HyperliquidInfoClient()          # OK, /info
        client.base_url = "...<endpoint d'execution>"   # le constructeur ne dit plus rien
        await client._post_info(...)              # ... et la requete PARTIRAIT

    Avant aujourd'hui, **rien** n'arretait ca. Le garde branche au TRANSPORT tire a **chaque
    appel** : la requete ne part pas.

    *Un garde qui s'execute une fois protege un instant. Un garde au transport protege chaque
    octet.*
    """
    client = HyperliquidInfoClient()                       # legitime : /info
    client.base_url = "https://api.hyperliquid.xyz/" + "exchange"   # noqa: S105 - simulation
    with pytest.raises(MainnetExecutionForbidden):
        asyncio.run(client._post_info("meta"))


# ============================================================ 3. IL RESTE BRANCHE (l'invariant)


def _appels(fichier: Path) -> set[str]:
    """Les fonctions REELLEMENT appelees dans ce fichier. Par AST -- un grep compterait le
    commentaire qui explique le garde, et rendrait le test VERT et AVEUGLE."""
    arbre = ast.parse(fichier.read_text(encoding="utf-8"))
    out: set[str] = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def test_le_garde_est_REELLEMENT_APPELE_par_le_client_pas_seulement_importe():
    """*Un import n'est pas un appel.* On a deja paye cette confusion : `garch11_variance` etait
    dans le meme fichier que sa version causale, et `bounded_event_queue` etait importe par
    personne. Ici on exige un **appel**, dans l'AST du client."""
    assert "assert_info_endpoint_only" in _appels(CLIENT), (
        "🔴 le garde `/info` n'est PLUS appele par rest_info_client : le sandboxing runtime est "
        "de nouveau debranche. C'etait exactement son etat avant le 2026-07-13."
    )


def test_le_garde_est_appele_AVANT_le_post_pas_apres():
    """Un garde qui s'execute APRES l'envoi ne garde rien : l'octet est deja parti."""
    src = CLIENT.read_text(encoding="utf-8")
    i_garde = src.find("assert_info_endpoint_only(self.base_url)")
    i_post = src.find("await self._client.post(")
    assert i_garde != -1 and i_post != -1
    assert i_garde < i_post, (
        "le garde `/info` est appele APRES le POST : la requete serait deja partie. "
        "*Un garde-fou en aval du danger n'est pas un garde-fou.*"
    )
