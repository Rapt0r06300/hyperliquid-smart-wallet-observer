#!/usr/bin/env python3
"""TESTER LES .cmd AVEC LOGS COMPLETS — tout est capture pour le debug.

Lance chaque lanceur .cmd du projet en capturant ABSOLUMENT TOUT (stdout + stderr
fusionnes, code de sortie, duree) dans un log dedie `runtime/logs/cmd/<nom>__<ts>.log`,
detecte les erreurs (grosses ET petites) et ecrit un sommaire `_SOMMAIRE.log`.

Non destructif par defaut : les .cmd dangereux (push GitHub, installation de noeud)
ne sont PAS lances automatiquement (categorie 'danger' -> note seulement). Les .cmd
longs (collecteur/labo/moteur) tournent avec un plafond de temps puis sont arretes
proprement.

Usage :
    python tools/tester_cmds.py --categorie sur     # rapides/surs (defaut)
    python tools/tester_cmds.py --categorie long    # collecteur/labo/moteur (30 min each)
    python tools/tester_cmds.py --categorie tous
    python tools/tester_cmds.py --seul SUIVI_COFFRE  # un seul par son nom
    python tools/tester_cmds.py --categorie long --minutes 5   # plafond court pour un smoke
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
LOGDIR = RACINE / "runtime" / "logs" / "cmd"

# Registre : nom, fichier .cmd, args, timeout_s, categorie ('sur'|'long'|'danger')
# 'long' = service continu -> plafonne puis arret propre des collecteurs.
REGISTRE: list[tuple[str, str, list[str], float, str]] = [
    ("SUIVI_COFFRE",          "SUIVI_COFFRE.cmd",                  [],            45,   "sur"),
    ("RAPPORT_COLLECTEURS",   "RAPPORT-COLLECTEURS.cmd",           [],           150,   "sur"),
    ("Certificateur_data",    "Certificateur Coffre Fort.cmd",     ["--data"],   360,   "sur"),
    ("ALINA_SYNC_preflight",  "ALINA_SYNC_COMPLETE.cmd",           [],           900,   "sur"),
    ("COLLECTEUR",            "LANCER_COLLECTEURS_COPY_VAULT.cmd", [],          1800,   "long"),
    ("LABO",                  "LANCER_LAB_QUANT_COPY_VAULT.cmd",   ["once"],    1800,   "long"),
    ("MOTEUR_HYPERSMART",     "LANCER_HYPERSMART.cmd",             [],          1800,   "long"),
    # Dangereux : effets externes -> jamais en auto.
    ("POUSSER_GITHUB",        "POUSSER-GITHUB-FORCE.cmd",          [],             0,   "danger"),
    ("Installer_Noeud_HL",    "Installer Noeud HL.cmd",            [],             0,   "danger"),
    ("Noeud_HL",              "Noeud-HL.cmd",                      [],             0,   "danger"),
]

# Env : NO_PAUSE (pas de blocage) + MAX verbosite pour faire remonter un max d'erreurs.
ENV_NO_PAUSE = {
    "CV_NO_PAUSE": "1", "HYPERSMART_PUSH_NO_PAUSE": "1",
    "ALINA_QUANT_NO_PAUSE": "1", "HYPERSMART_NO_PAUSE": "1",
    "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
    "PYTHONWARNINGS": "always",   # montre TOUS les warnings python (Deprecation incluses)
    "PYTHONFAULTHANDLER": "1",    # dump sur crash natif
    "ALINA_DEBUG": "1", "ALINA_VERBOSE": "1", "CV_VERBOSE": "1",  # si les outils les respectent
}

# Motifs d'erreur AGRESSIFS (on veut le MAX : grosses ET petites). 1re categorie qui matche gagne.
MOTIFS = [
    ("CRITIQUE", re.compile(
        r"traceback|most recent call last|CRITICAL|FATAL|unhandled|segfault|core dump|panic|"
        r"n['’]est pas reconnu|is not recognized|ModuleNotFound|ImportError|SyntaxError|"
        r"NameError|AttributeError|KeyError|TypeError|ValueError|IndexError|RuntimeError|"
        r"ZeroDivision|RecursionError|MemoryError|OSError|WinError|\berrno\b|"
        r"ALINA_\w*FAIL|\bNO_GO\b|\brefus|\bassert(ion)?\b", re.I)),
    ("ERREUR", re.compile(
        r"\bERRE?URS?\b|\bERRORS?\b|\bFAIL(ED|URE|S)?\b|\bexception\b|"
        r"returncode=[1-9]|exit code [1-9]|non[- ]?zero exit|"
        r"\[ERREUR\]|\[X\]|\[KO\]|\[NO_GO\]|\bimpossible\b|echou|échou|introuvable|manquant|"
        r"cannot |can['’]t |could ?n['’]?o?t |no such |not found|denied|refused|"
        r"unauthorized|forbidden|timed out|\bexpired\b|expir[eé]e?\b|corrupt|"
        r"\binvalid\b|\binvalide\b|HTTP[\s/]*(error[\s/]*)?[45]\d\d|\bstatus[\s=:]+[45]\d\d|"
        r"JSONDecode|malformed|\brejected\b|\brejet[eé]|\baborted?\b", re.I)),
    ("AVERT", re.compile(
        r"\bWARN(ING)?\b|\bAVERT|deprecat|\bfallback\b|degraded|\bstale\b|"
        r"\[INFO\].*(absent|manquant)", re.I)),
]


def scanner(texte: str) -> tuple[dict[str, int], dict[str, list[str]]]:
    comptes = {k: 0 for k, _ in MOTIFS}
    lignes: dict[str, list[str]] = {k: [] for k, _ in MOTIFS}
    for ln in texte.splitlines():
        for k, rx in MOTIFS:
            if rx.search(ln):
                comptes[k] += 1
                if len(lignes[k]) < 40:
                    lignes[k].append(ln.rstrip())
                break
    return comptes, lignes


def scanner_logs_projet(depuis_ts: float, *, max_par_fichier: int = 60,
                        tail_octets: int = 600_000):
    """Scanne runtime/logs/*.log MODIFIES pendant le run pour un MAX d'erreurs.

    C'est la que vivent les vraies erreurs des collecteurs (pas dans le stdout).
    Lit la fin de chaque log (tail) pour rester rapide. Renvoie (trouve, comptes).
    """
    base = RACINE / "runtime" / "logs"
    trouve: dict[str, list[str]] = {}
    comptes = {k: 0 for k, _ in MOTIFS}
    if not base.exists():
        return trouve, comptes
    try:
        fichiers = list(base.rglob("*.log"))
    except OSError:
        return trouve, comptes
    propre_dir = (base / "cmd").resolve()
    # Rapports DERIVES : ils reformatent/consolident deja des lignes d'autres logs
    # (double comptage + bruit). On scanne les logs BRUTS, pas les rapports.
    derives = {"rapport_collecteurs.log"}
    for p in fichiers:
        try:
            if propre_dir in p.resolve().parents:   # ne pas scanner NOS propres logs (auto-reference)
                continue
            if p.name in derives:
                continue
            st = p.stat()
        except OSError:
            continue
        if st.st_mtime < depuis_ts - 2:   # modifie pendant ce run seulement
            continue
        try:
            with p.open("rb") as fh:
                if st.st_size > tail_octets:
                    fh.seek(-tail_octets, os.SEEK_END)
                data = fh.read().decode("utf-8", "replace")
        except OSError:
            continue
        lignes: list[str] = []
        for ln in data.splitlines():
            for k, rx in MOTIFS:
                if rx.search(ln):
                    comptes[k] += 1
                    if len(lignes) < max_par_fichier:
                        lignes.append(f"[{k}] {ln.strip()[:220]}")
                    break
        if lignes:
            try:
                nom = str(p.relative_to(RACINE))
            except ValueError:
                nom = str(p)
            trouve[nom] = lignes
    return trouve, comptes


def _arreter_collecteurs_propre() -> str:
    """Arrete proprement les collecteurs via le helper de l'ecran temps reel."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "aff", str(RACINE / "tools" / "affichage_temps_reel.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        tues = m._arreter_collecteurs(RACINE)
        return f"arret propre : {len(tues)} process tue(s)"
    except Exception as e:  # noqa
        return f"arret propre ECHEC : {e!r}"


def tester_un(nom: str, fichier: str, args: list[str], timeout: float, categorie: str) -> dict:
    LOGDIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%S")
    log = LOGDIR / f"{nom}__{ts}.log"
    cible = RACINE / fichier
    env = {**os.environ, **ENV_NO_PAUSE}

    entete = [
        "=" * 70, f"  TEST .cmd : {nom}", "=" * 70,
        f"fichier    : {cible}", f"existe     : {cible.exists()}",
        f"args       : {args}", f"categorie  : {categorie}",
        f"timeout    : {int(timeout)}s", f"debut      : {ts}", "=" * 70, "",
    ]

    if categorie == "danger":
        corps = (f"[NON LANCE] '{nom}' a des effets externes (push GitHub / installation / noeud).\n"
                 f"Il n'est jamais execute automatiquement. Lance-le manuellement, ou demande\n"
                 f"explicitement son mode sur, pour generer son log complet.\n")
        log.write_text("\n".join(entete) + corps, encoding="utf-8")
        return {"nom": nom, "log": log, "code": "SKIP", "tue": False, "duree": 0.0,
                "comptes": {"CRITIQUE": 0, "ERREUR": 0, "AVERT": 0}, "categorie": categorie}

    if not cible.exists():
        log.write_text("\n".join(entete) + f"[INTROUVABLE] {cible}\n", encoding="utf-8")
        return {"nom": nom, "log": log, "code": "ABSENT", "tue": False, "duree": 0.0,
                "comptes": {"CRITIQUE": 1, "ERREUR": 0, "AVERT": 0}, "categorie": categorie}

    buf: list[str] = []
    code = None
    tue = False
    t0 = time.time()

    def _lire(pipe) -> None:
        # Lecture CONTINUE : capture tout, meme si le process est tue (sortie non perdue).
        try:
            for ligne in iter(pipe.readline, ""):
                buf.append(ligne)
        except (OSError, ValueError):
            pass

    try:
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        # cmd /c + chemin en element de liste : list2cmdline quote correctement
        # le chemin (avec espaces) pour CreateProcess, qui ne lance pas un .cmd seul.
        p = subprocess.Popen([comspec, "/c", str(cible), *args], cwd=str(RACINE), env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace")
        th = threading.Thread(target=_lire, args=(p.stdout,), daemon=True)
        th.start()
        try:
            # On attend la FIN DU PROCESS principal, pas l'EOF du tube : une fenetre
            # GUI detachee (notepad, SUIVI) qui herite du tube ne doit pas nous bloquer.
            p.wait(timeout=timeout)
            code = p.returncode
        except subprocess.TimeoutExpired:
            tue = True
            code = None
        # Kill arbre dans tous les cas : libere les fenetres GUI detachees qui tiennent
        # le tube, et stoppe un service encore vivant (categorie long).
        try:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                           capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
        th.join(timeout=8)
        try:
            p.stdout.close()
        except OSError:
            pass
    except OSError as e:
        buf.append(f"[LANCEMENT IMPOSSIBLE] {e!r}")
    sortie = "".join(buf)
    dt = time.time() - t0

    note_arret = ""
    if categorie == "long":
        note_arret = _arreter_collecteurs_propre()

    comptes_out, lignes_out = scanner(sortie)
    logs_proj, comptes_proj = scanner_logs_projet(t0)
    comptes = {k: comptes_out[k] + comptes_proj[k] for k in comptes_out}
    pied = ["", "=" * 70,
            f"fin        : exit={code}{'  (PLAFOND TEMPS -> arret)' if tue else ''}",
            f"duree      : {dt:.0f}s",
            f"erreurs TOTAL : CRITIQUE={comptes['CRITIQUE']}  ERREUR={comptes['ERREUR']}  AVERT={comptes['AVERT']}",
            f"  detail : stdout(C={comptes_out['CRITIQUE']} E={comptes_out['ERREUR']} A={comptes_out['AVERT']})"
            f"  logs-projet(C={comptes_proj['CRITIQUE']} E={comptes_proj['ERREUR']} A={comptes_proj['AVERT']})"]
    if note_arret:
        pied.append(f"arret      : {note_arret}")
    pied.append("=" * 70)
    for k, _ in MOTIFS:
        if lignes_out[k]:
            pied.append(f"\n----- STDOUT / {k} ({comptes_out[k]}) -----")
            pied.extend("  " + x for x in lignes_out[k])
    if logs_proj:
        pied.append("\n" + "#" * 70)
        pied.append("# ERREURS DANS LES LOGS DU PROJET (fichiers touches pendant ce run)")
        pied.append("#" * 70)
        for fich, lns in sorted(logs_proj.items()):
            pied.append(f"\n--- {fich} ({len(lns)}) ---")
            pied.extend("  " + x for x in lns)
    log.write_text("\n".join(entete) + sortie + "\n".join(pied) + "\n", encoding="utf-8")
    return {"nom": nom, "log": log, "code": code, "tue": tue, "duree": dt,
            "comptes": comptes, "categorie": categorie}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--categorie", default="sur", choices=["sur", "long", "danger", "tous"])
    ap.add_argument("--seul", default=None, help="tester un seul .cmd par son nom de registre")
    ap.add_argument("--minutes", type=float, default=None, help="plafond temps (minutes) pour cette passe")
    a = ap.parse_args(argv)

    LOGDIR.mkdir(parents=True, exist_ok=True)
    choix = [r for r in REGISTRE
             if (a.seul and r[0] == a.seul) or
                (not a.seul and (a.categorie == "tous" or r[4] == a.categorie))]
    if not choix:
        print(f"Aucun .cmd ne correspond (seul={a.seul}, categorie={a.categorie}).", flush=True)
        return 2

    print(f"Logs complets -> {LOGDIR}", flush=True)
    resultats = []
    for nom, fichier, args, timeout, cat in choix:
        if a.minutes is not None and cat != "danger":
            timeout = a.minutes * 60
        print(f"\n>>> {nom} ({cat})  [timeout {int(timeout)}s]", flush=True)
        r = tester_un(nom, fichier, args, timeout, cat)
        c = r["comptes"]
        print(f"    exit={r['code']}  duree={r['duree']:.0f}s  "
              f"CRITIQUE={c['CRITIQUE']} ERREUR={c['ERREUR']} AVERT={c['AVERT']}", flush=True)
        print(f"    log: {r['log']}", flush=True)
        resultats.append(r)

    # Sommaire
    somm = LOGDIR / "_SOMMAIRE.log"
    lignes = [f"SOMMAIRE DES TESTS .cmd — {time.strftime('%Y-%m-%d %H:%M:%S')}", "=" * 70]
    for r in resultats:
        c = r["comptes"]
        etat = "OK" if (c["CRITIQUE"] == 0 and r["code"] in (0, "SKIP")) else "A VOIR"
        lignes.append(f"[{etat:6}] {r['nom']:22} exit={str(r['code']):6} "
                      f"dur={r['duree']:5.0f}s  CRIT={c['CRITIQUE']} ERR={c['ERREUR']} AVERT={c['AVERT']}"
                      f"  -> {r['log'].name}")
    with somm.open("a", encoding="utf-8") as fh:  # append : on garde l'historique
        fh.write("\n".join(lignes) + "\n\n")
    print("\n" + "\n".join(lignes), flush=True)
    print(f"\nSommaire: {somm}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
