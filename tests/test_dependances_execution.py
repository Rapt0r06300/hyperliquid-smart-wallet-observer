"""IMPROVE-24 (#131) -- un paquet CAPABLE d'executer ne doit jamais etre installe.

La difference avec tous les autres garde-fous du projet :

    les autres empechent le CODE de decider de trader ;
    celui-ci empeche la MACHINE d'en avoir les MOYENS.

On teste sur un environnement FABRIQUE. C'est tout l'interet d'avoir isole `auditer()` en
fonction pure : on peut demander « et si quelqu'un installait ccxt demain ? » sans installer
ccxt pour de vrai. Un garde-fou qu'on ne peut pas eprouver ne garde rien.
"""

from __future__ import annotations

from hl_observer.security.dependances import (
    INTERDITS,
    MOTIF_REFUS,
    auditer,
    auditer_l_environnement,
    paquets_installes,
)


def test_un_environnement_PROPRE_passe():
    """Ce qu'on utilise VRAIMENT : lire, parser, tester. Rien de tout ca ne signe quoi que ce soit."""
    v = auditer(["requests", "websockets", "pydantic", "fastapi", "numpy", "pytest", "sqlalchemy"])
    assert v.ok
    assert v.trouvailles == ()
    assert v.alerte == ""


def test_dex_exec_est_ATTRAPE():
    """🚨 `mackinac/dex-exec` EXECUTE DE VRAIS ORDRES (H-134). C'est LE paquet a ne jamais voir."""
    v = auditer(["requests", "dex-exec"])
    assert not v.ok
    assert [t.paquet for t in v.trouvailles] == ["dex-exec"]
    assert MOTIF_REFUS in v.alerte
    assert "EXECUTE DE VRAIS ORDRES" in v.alerte


def test_ccxt_est_ATTRAPE_meme_si_personne_ne_l_appelle():
    """Un client d'execution INSTALLE mais jamais importe reste une CAPACITE presente.

    C'est la lecon des sept interrupteurs eteints, prise a l'envers : ici ce n'est pas une
    capacite qu'on croit avoir et qui dort, c'est une capacite qu'on croit ne pas avoir... et
    qui est la, a portee d'un seul `import`.
    """
    v = auditer(["numpy", "ccxt"])
    assert not v.ok
    assert v.trouvailles[0].famille == "CLIENT_D_EXECUTION"


def test_une_bibliotheque_de_SIGNATURE_est_ATTRAPEE():
    """Sans signature, aucune transaction. `eth-account` suffit a franchir cette ligne."""
    v = auditer(["eth-account"])
    assert not v.ok
    assert v.trouvailles[0].famille == "SIGNATURE_OU_CLE"


def test_le_nom_est_NORMALISE_avant_comparaison():
    """PyPI traite `-`/`_` et la casse comme equivalents. Sans ca, `Eth_Account` passerait.

    C'est exactement le genre de trou par lequel une capacite interdite rentre sans bruit.
    """
    for variante in ("Eth_Account", "ETH-ACCOUNT", "eth_account", "  eth-account  "):
        v = auditer([variante])
        assert not v.ok, "la variante %r echappe au controle" % variante


def test_TOUS_les_interdits_sont_effectivement_attrapes():
    """Un a un. Une liste dont un element ne declenche rien est une liste decorative."""
    rates = [p for p in INTERDITS if auditer([p]).ok]
    assert rates == [], "ces paquets sont declares INTERDITS mais ne declenchent rien : %s" % rates


def test_L_ENVIRONNEMENT_REEL_n_a_AUCUN_paquet_capable_d_executer():
    """🔴 LE TEST QUI COMPTE. Il porte sur la machine, ici, maintenant.

    S'il rougit un jour, ce sera qu'un `pip install` a rendu l'execution reelle POSSIBLE.
    C'est un cliquet : la capacite ne peut pas revenir en douce.
    """
    v = auditer_l_environnement()
    assert v.n_paquets > 0, "aucun paquet detecte : l'audit ne mesure rien, donc il ne garde rien"
    assert v.ok, v.alerte


def test_l_audit_de_l_environnement_LIT_vraiment_quelque_chose():
    """Un audit qui ne trouve aucun paquet ne peut pas echouer -- donc il ne garde rien."""
    paquets = paquets_installes()
    assert len(paquets) > 20, "seulement %d paquets vus : l'audit tourne a vide" % len(paquets)
    assert all(p == p.lower() for p in paquets), "les noms doivent etre normalises"


def test_le_verrou_est_BRANCHE_dans_safety_audit():
    """Un controle non branche est un controle mort. On verifie l'IMPORT et le CHAMP.

    (T3b, T3c, GH-01 : la maladie du projet est la capacite presente et jamais appelee.
    Ce test existe pour qu'elle ne se reproduise pas une huitieme fois.)
    """
    import ast
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1]
        / "src" / "hl_observer" / "security" / "safety_audit.py"
    ).read_text(encoding="utf-8")

    arbre = ast.parse(src)
    importes = {n.module for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.module}
    assert "hl_observer.security.dependances" in importes, (
        "safety_audit n'importe PAS l'audit de dependances : le verrou est mort"
    )
    assert "no_real_execution_capable_package" in src, (
        "le controle n'est pas pose dans `checks` : il ne fera jamais echouer l'audit"
    )
