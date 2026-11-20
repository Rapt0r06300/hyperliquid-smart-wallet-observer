"""Un appel HTTPS sans delai d'attente ne revient JAMAIS : le transport en impose un.

CE N'EST PAS UN BUG OBSERVE (20/11/2026). Les deux appelants de
``_get_with_bounded_retries`` passent bien ``timeout=DEFAULT_TIMEOUT`` (30 s a la connexion,
300 s a la lecture). Mais sa signature ``**kwargs`` laisse un futur appelant l'omettre, et un
collecteur fige ne se distingue pas d'un collecteur lent -- c'est la panne muette la plus
couteuse a diagnostiquer. Le defaut est donc pose DANS le transport, pas confie a l'appelant.
"""
from __future__ import annotations

from hl_observer.datasets import github_api_transport as transport


class _Reponse:
    status_code = 200
    headers: dict[str, str] = {}

    def close(self) -> None:
        return None


def test_le_transport_impose_un_delai_quand_l_appelant_l_oublie(monkeypatch) -> None:
    vus: list[dict] = []

    def _faux_get(url, **kwargs):
        vus.append(kwargs)
        return _Reponse()

    monkeypatch.setattr(transport.requests, "get", _faux_get)
    transport._get_with_bounded_retries("https://example.invalid/x", headers={})

    assert vus, "requests.get n'a pas ete appele"
    assert vus[0].get("timeout") == transport.DEFAULT_TIMEOUT, (
        f"appel HTTPS sans delai d'attente : {vus[0]!r}")


def test_un_delai_explicite_de_l_appelant_gagne(monkeypatch) -> None:
    """La moitie qui compte : le defaut ne doit pas ECRASER un choix explicite."""
    vus: list[dict] = []
    monkeypatch.setattr(transport.requests, "get",
                        lambda url, **kwargs: (vus.append(kwargs), _Reponse())[1])
    transport._get_with_bounded_retries(
        "https://example.invalid/x", headers={}, timeout=(1.0, 2.0))

    assert vus[0].get("timeout") == (1.0, 2.0), (
        f"le defaut a ecrase le delai demande par l'appelant : {vus[0]!r}")
