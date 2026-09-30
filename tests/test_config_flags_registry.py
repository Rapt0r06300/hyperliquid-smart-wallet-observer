"""AUDIT-C : le generateur de registre de flags produit un markdown coherent.

🚩 CES DEUX TESTS ETAIENT ROUGES DEPUIS T3, ET PERSONNE NE L'AVAIT VU (trouve le 13/07 par G2,
en lancant enfin la suite COMPLETE).

`tools/gen_config_flags.py` a ete REECRIT lors de T3 pour s'appuyer sur la meme source de verite
que l'audit de cablage (`hl_observer.audit.cablage.auditer_les_interrupteurs`) -- il prend
desormais une liste d'`Interrupteur`, plus un dict `{"code": ..., "launcher": ...}`. Les tests,
eux, sont restes sur l'ANCIENNE API : ils appelaient `gen.scan()`, qui n'existe plus.

La lecon est la meme que partout ailleurs ce soir : **un test qu'on ne lance pas ne teste rien.**
Un outil et son test se reecrivent dans le meme mouvement, jamais l'un sans l'autre.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from hl_observer.audit.cablage import Interrupteur

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("gen_config_flags", ROOT / "tools" / "gen_config_flags.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)


def _i(nom: str, *, defaut: str | None, lu_par: tuple[str, ...], pose_par: tuple[str, ...]) -> Interrupteur:
    return Interrupteur(nom=nom, defaut=defaut, lu_par=lu_par, pose_par=pose_par)


def test_build_markdown_marque_les_flags_MORTS():
    """MORT = lu avec un defaut ETEINT, et pose par PERSONNE. La capacite existe et ne tourne pas.

    C'est la maladie du projet, trouvee sept fois : le poller L2, la jambe de funding, le verrou
    du copy-follow, la pile V26 entiere... Le generateur doit la CRIER, pas la ranger.
    """
    inters = [
        _i("HYPERSMART_VIVANT", defaut="0", lu_par=("hl_observer.a",), pose_par=("start.ps1",)),
        _i("HYPERSMART_MORT", defaut="0", lu_par=("hl_observer.b",), pose_par=()),
    ]
    md = gen.build_markdown(inters)

    assert "HYPERSMART_VIVANT" in md
    assert "HYPERSMART_MORT" in md
    assert "MORT" in md
    assert "`HYPERSMART_MORT`" in md


def test_un_flag_ALLUME_par_defaut_n_est_PAS_mort_meme_sans_lanceur():
    """Un defaut ALLUME (`1`) qui n'est pose par personne n'est pas mort : il tourne deja.

    La distinction n'est pas academique -- c'est exactement le piege du bus GitHub (12/07) :
    allume par defaut, jamais eteint nulle part, et tout le monde le croyait inactif.
    """
    inters = [_i("HYPERSMART_DEJA_ON", defaut="1", lu_par=("hl_observer.c",), pose_par=())]
    morts = [i for i in inters if i.mort]
    assert morts == [], "un flag dont le defaut est ALLUME n'est pas un flag mort"


def test_le_registre_REEL_n_a_aucun_flag_mort():
    """La verite sur le DEPOT, pas sur un jeu de donnees fabrique. Si ce test rougit, c'est
    qu'une capacite est codee, lue, eteinte par defaut... et posee par aucun lanceur.

    C'est la 8e occurrence potentielle de la maladie -- et cette fois un test la bloque.
    """
    py = gen._collecter(("src/**/*.py", "hyper_smart_observer/**/*.py", "tests/**/*.py"))
    lanceurs = gen._collecter(
        (
            "*.cmd", "*.ps1", "*.sh",
            "tools/**/*.cmd", "tools/**/*.ps1", "tools/**/*.sh",
            "config/**/*.yaml", "config/**/*.yml",
        )
    )
    inters = gen.auditer_les_interrupteurs(py, lanceurs, prefixes=gen.PREFIXES)
    morts = sorted(i.nom for i in inters if i.mort)
    assert morts == [], (
        "Flag(s) MORT(S) : capacite presente, interrupteur eteint, aucun lanceur ne l'allume :\n  "
        + "\n  ".join(morts)
    )
