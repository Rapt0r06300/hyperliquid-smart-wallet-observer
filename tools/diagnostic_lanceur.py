#!/usr/bin/env python3
"""Diagnostic LECTURE SEULE de la chaine de lancement HyperSmart.

SECURITE : 0 ordre reel, 0 argent reel, 0 cle privee, 0 seed, 0 signature,
0 depot/retrait, 0 appel d'API privee. Ce script n'ecrit AUCUN fichier dans
runtime/, n'ouvre AUCUNE socket, et se contente d'importer des modules pour
verifier que l'interpreteur portable peut les charger.

Sortie strictement ASCII (le lanceur cmd.exe peut etre en cp850/cp1252).
Code retour : 0 si la chaine est saine, 1 si au moins une sonde a echoue.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import traceback
from pathlib import Path

# Deny-by-default defensif : meme un import accidentel ne peut rien declencher.
os.environ.setdefault("HL_ENV", "paper")
os.environ["HL_ENABLE_MAINNET_EXECUTION"] = "0"
os.environ["HL_ENABLE_TESTNET_EXECUTION"] = "0"
os.environ["REAL_MAINNET_TRADING"] = "false"
os.environ["TESTNET_ONLY"] = "true"

LARGEUR = 74

# (module, a quoi il sert dans les lanceurs)
MODULES_LANCEURS = [
    ("hl_observer", "paquet racine (src/hl_observer)"),
    ("hl_observer.ops.verrou_lanceur", "LANCER_HYPERSMART - verrou d'instance"),
    ("hl_observer.ops.premier_lancement", "LANCER_HYPERSMART - prevol PC neuf"),
    ("hl_observer.ops.superviseur_collecteurs", "LANCER_HYPERSMART - collecteurs"),
    ("hl_observer.ops.registre_pids", "LANCER_HYPERSMART - arret propre"),
    ("hl_observer.ops.analyser_session", "ANALYSER - porte d'entree session"),
    ("hl_observer.ops.lab_alpha", "ANALYSER - laboratoire alpha"),
    ("hl_observer.ops.portable_smoke", "ANALYSER - smoke portable"),
    ("hl_observer.ops.historical_analysis_suite", "ANALYSER - plan d'etapes"),
    ("hl_observer.ops.recette_lanceur", "RECETTE-LANCEUR"),
]

# Dependances tierces reellement importees par src/hl_observer.
TIERS = [
    "certifi", "click", "fastapi", "httpx", "lz4", "numpy", "pandas",
    "psutil", "pydantic", "requests", "rich", "scipy", "sqlalchemy",
    "typer", "uvicorn", "websocket", "websockets", "yaml",
]


def titre(texte: str) -> None:
    print("")
    print("-" * LARGEUR)
    print("  " + texte)
    print("-" * LARGEUR)


def ok(texte: str) -> None:
    print("  [OK]      " + texte)


def echec(texte: str) -> None:
    print("  [ECHEC]   " + texte)


def info(texte: str) -> None:
    print("  [INFO]    " + texte)


def alerte(texte: str) -> None:
    print("  [ALERTE]  " + texte)


def _version(module) -> str:
    for attribut in ("__version__", "VERSION", "version"):
        valeur = getattr(module, attribut, None)
        if isinstance(valeur, str):
            return valeur
    return "?"


def sonder_interpreteur(racine: Path) -> list[str]:
    problemes: list[str] = []
    titre("1. INTERPRETEUR PORTABLE")
    info("executable : " + sys.executable)
    info("version    : " + sys.version.split()[0] + " (" + sys.platform + ")")
    info("prefix     : " + sys.prefix)

    attendu = racine / "tools" / "python" / "python.exe"
    try:
        meme = Path(sys.executable).resolve() == attendu.resolve()
    except OSError:
        meme = False
    if meme:
        ok("c'est bien tools\\python\\python.exe (aucun repli systeme)")
    else:
        alerte("l'interpreteur n'est PAS tools\\python\\python.exe")
        alerte("attendu : " + str(attendu))
        problemes.append("interpreteur non portable")
    return problemes


def sonder_sys_path(racine: Path) -> list[str]:
    problemes: list[str] = []
    titre("2. SYS.PATH (pilote par python314._pth, PYTHONPATH est IGNORE)")
    for entree in sys.path:
        marque = "existe" if entree and Path(entree).exists() else "INTROUVABLE"
        print("  - [" + marque + "] " + (entree or "(chaine vide)"))

    besoins = {
        "src": racine / "src",
        "racine du projet": racine,
        "tools": racine / "tools",
        "site-packages": racine / "tools" / "python" / "Lib" / "site-packages",
    }
    resolus = set()
    for entree in sys.path:
        if not entree:
            continue
        try:
            resolus.add(Path(entree).resolve())
        except OSError:
            continue
    print("")
    for nom, chemin in besoins.items():
        try:
            present = chemin.resolve() in resolus
        except OSError:
            present = False
        if present:
            ok(nom + " est sur sys.path")
        else:
            echec(nom + " MANQUE sur sys.path -> " + str(chemin))
            problemes.append("sys.path sans " + nom)
    return problemes


def sonder_modules() -> tuple[list[str], list[tuple[str, str, str]]]:
    problemes: list[str] = []
    traces: list[tuple[str, str, str]] = []
    titre("3. MODULES APPELES PAR LES DEUX LANCEURS")
    for nom, role in MODULES_LANCEURS:
        try:
            importlib.import_module(nom)
        except BaseException:  # noqa: BLE001 - on veut TOUT capturer, meme SystemExit
            echec(nom + "  (" + role + ")")
            traces.append((nom, role, traceback.format_exc()))
            problemes.append("import impossible : " + nom)
        else:
            ok(nom + "  (" + role + ")")
    return problemes, traces


def sonder_tiers() -> list[str]:
    problemes: list[str] = []
    titre("4. DEPENDANCES TIERCES")
    for nom in TIERS:
        try:
            module = importlib.import_module(nom)
        except BaseException:  # noqa: BLE001
            echec(nom + " : ABSENT ou casse")
            problemes.append("dependance manquante : " + nom)
        else:
            ok(nom + " " + _version(module))

    # Verification ciblee : l'API websockets a change de facon incompatible
    # entre la v10 (pin historique de requirements.txt) et la v14+.
    try:
        import websockets  # noqa: PLC0415
    except BaseException:  # noqa: BLE001
        return problemes
    version = _version(websockets)
    majeure = 0
    try:
        majeure = int(version.split(".")[0])
    except (ValueError, IndexError):
        pass
    if majeure >= 14:
        alerte("websockets " + version + " : l'ancienne API (websockets.legacy,")
        alerte("  extra_headers=..., WebSocketClientProtocol) a ete retiree.")
        alerte("  requirements.txt epingle encore websockets>=10,<11 : si un")
        alerte("  collecteur utilise l'ancienne API, il casse a l'execution.")
    for chemin in ("legacy", "asyncio.client"):
        try:
            importlib.import_module("websockets." + chemin)
        except BaseException:  # noqa: BLE001
            info("websockets." + chemin + " : absent")
        else:
            info("websockets." + chemin + " : present")
    return problemes


def sonder_securite(racine: Path) -> None:
    titre("5. CONFIRMATION SECURITE (lecture seule)")
    for cle, attendu in (
        ("HL_ENABLE_MAINNET_EXECUTION", "0"),
        ("HL_ENABLE_TESTNET_EXECUTION", "0"),
        ("REAL_MAINNET_TRADING", "false"),
        ("TESTNET_ONLY", "true"),
    ):
        valeur = os.environ.get(cle, "(non defini)")
        etat = "OK" if valeur == attendu else "A VERIFIER"
        print("  [" + etat + "] " + cle + " = " + valeur)
    env = racine / ".env"
    if env.exists():
        alerte(".env present a la racine : ce diagnostic ne l'a PAS lu.")
    else:
        ok("aucun .env a la racine")
    ok("ce diagnostic n'a passe aucun ordre et n'a signe aucune transaction")


def main() -> int:
    parseur = argparse.ArgumentParser(description="Diagnostic lecture seule des lanceurs.")
    parseur.add_argument("--root", default=".", help="racine du projet")
    arguments = parseur.parse_args()
    racine = Path(arguments.root).resolve()

    print("=" * LARGEUR)
    print("  DIAGNOSTIC PYTHON DE LA CHAINE DE LANCEMENT - LECTURE SEULE")
    print("  racine : " + str(racine))
    print("=" * LARGEUR)

    problemes: list[str] = []
    problemes += sonder_interpreteur(racine)
    problemes += sonder_sys_path(racine)
    problemes_modules, traces = sonder_modules()
    problemes += problemes_modules
    problemes += sonder_tiers()
    sonder_securite(racine)

    if traces:
        titre("6. PREMIERE CAUSE RACINE (trace complete)")
        nom, role, trace = traces[0]
        print("  Module     : " + nom)
        print("  Utilise par: " + role)
        print("")
        for ligne in trace.splitlines():
            print("  | " + ligne)
        if len(traces) > 1:
            print("")
            info(str(len(traces) - 1) + " autre(s) module(s) en echec (souvent la meme cause).")

    titre("VERDICT")
    if problemes:
        echec(str(len(problemes)) + " probleme(s) bloquant(s) :")
        for probleme in problemes:
            print("            - " + probleme)
        return 1
    ok("chaine Python saine : les deux lanceurs peuvent importer tout ce")
    ok("qu'ils appellent. Si une fenetre se ferme quand meme, la cause est")
    ok("dans le .cmd lui-meme (voir les etapes 1 a 3 du rapport cmd).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
