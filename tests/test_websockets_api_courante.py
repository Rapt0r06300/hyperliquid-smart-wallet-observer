"""Aucun appel ne doit passer un argument RETIRE a websockets.connect.

LE DEFAUT (20/11/2026). `src/hl_observer/collection/gate_market_data.py` passait
`extra_headers={"X-Gate-Size-Decimal": "1"}`. Or cet argument a ete **retire en websockets 14+**,
et l'environnement installe est en **17.0.1**. Mesure sur la bibliotheque reelle :

    extra_headers      -> TypeError: BaseEventLoop.create_connection() got an unexpected
                          keyword argument 'extra_headers'
    additional_headers -> accepte

La signature de `connect` porte un `**kwargs`, donc rien n'est rejete a l'appel : l'argument
voyage jusqu'a asyncio avant de lever. Et ce site vit dans un `while True` avec compteur de
tentatives -- le collecteur reessayait donc **a l'infini sur une erreur permanente**.

`requirements.txt` demandait encore `websockets>=10,<11`, alors que `requirements-portable.txt`
epingle `17.0.1` : les workflows qui installent le premier testaient une API differente de celle
qui tourne. `tools/diagnostic_lanceur.py` denoncait deja ce pin perime. La borne est alignee.

CE QUE CE TEST TIENT. Les deux bouts : plus aucun argument retire dans le code, et la
bibliotheque installee accepte bien le nom moderne. Si l'un des deux bouge, on le sait ici.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import websockets

RACINE = Path(__file__).resolve().parents[1]

#: Noms retires en websockets 14+ (l'ancienne implementation `legacy` a disparu).
ARGUMENTS_RETIRES = ("extra_headers=", "WebSocketClientProtocol", "websockets.legacy")

#: Le diagnostic du projet CITE ces noms pour en parler : ce n'est pas un usage.
FICHIERS_QUI_EN_PARLENT = ("tools/diagnostic_lanceur.py",)


def _sources() -> list[Path]:
    fichiers: list[Path] = []
    for dossier in ("src", "tools"):
        base = RACINE / dossier
        if base.is_dir():
            fichiers.extend(p for p in base.rglob("*.py")
                            if p.is_file() and "site-packages" not in p.parts
                            and "__pycache__" not in p.parts)
    return fichiers


def test_aucun_argument_retire_de_websockets_dans_le_code() -> None:
    fichiers = _sources()
    assert len(fichiers) > 2000, f"{len(fichiers)} source(s) : le balayage ne couvre plus le projet"
    fautifs: list[str] = []
    for chemin in fichiers:
        relatif = chemin.relative_to(RACINE).as_posix()
        if relatif in FICHIERS_QUI_EN_PARLENT:
            continue
        for numero, ligne in enumerate(
                chemin.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            nu = ligne.strip()
            if nu.startswith("#"):
                continue
            for mort in ARGUMENTS_RETIRES:
                if mort in nu:
                    fautifs.append(f"{relatif}:{numero} -> {nu[:84]}")
    assert not fautifs, (
        "argument(s) retire(s) en websockets 14+ encore utilises : ils remontent jusqu a "
        "asyncio et levent TypeError a CHAQUE tentative de connexion :\n  "
        + "\n  ".join(fautifs))


def test_la_bibliotheque_installee_accepte_le_nom_moderne() -> None:
    """La moitie qui compte : sans ceci, le test ci-dessus passerait meme si `connect`
    n'acceptait AUCUN en-tete -- et le collecteur Gate a besoin de `X-Gate-Size-Decimal`."""
    parametres = inspect.signature(websockets.connect).parameters
    assert "additional_headers" in parametres, (
        f"websockets {websockets.__version__} n'accepte pas `additional_headers` : la borne de "
        "requirements.txt et le code ne sont plus d'accord")
    assert "extra_headers" not in parametres, (
        "`extra_headers` est revenu : verifier quelle version est installee avant de conclure")
