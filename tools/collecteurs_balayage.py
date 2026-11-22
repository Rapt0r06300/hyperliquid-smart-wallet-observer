"""Sélection PURE des processus de collecte du projet — partagée, pas dupliquée.

EXTRAIT de `tools/affichage_temps_reel.py` le 21/11/2026, code inchangé, noms publiés.

POURQUOI (mesure du jour) : le chemin d'arrêt du watchdog
(`watch_economic_collectors.arreter_campagne_immediatement`) ne tuait que les PID
**listés** dans l'état de campagne. Or 20 PID y étaient listés pendant que ~30 ouvriers
`tools/run_bounded_collector.py` tournaient : un ouvrier né après l'écriture de cet état
n'était arrêté par personne. Le balayage par ligne de commande existait déjà — mais
seulement dans l'écran temps réel, donc inaccessible au watchdog.

Et il est extrait plutôt qu'importé depuis l'écran : un chemin d'ARRÊT ne doit pas
dépendre d'un module d'AFFICHAGE. Si cet écran gagne un jour une dépendance lourde,
l'arrêt des collecteurs tomberait avec elle.
"""
from __future__ import annotations

import os
import subprocess

# Marqueurs identifiant un process COLLECTEUR du projet (à arrêter sur stop).
MARQUEURS_COLLECTEUR = (
    "watch_economic_collectors", "collecter_", "explorer_autonome",
    "poll_leaders", "_run_supervisor", "_run_poll", "_run_explorer", "_run_asset_ctx",
    # MESURE DU 21/11/2026 -- ANGLE MORT TROUVE EN CONDITIONS REELLES. 20 familles
    # etaient actives, portees par ~30 processus `tools/run_bounded_collector.py`
    # (lances par `ops/bounded_collection.py`, qui les reconnait lui-meme sous ce
    # nom). AUCUN marqueur de cette liste ne matchait : le `taskkill` de dernier
    # recours voyait zero collecteur. Ils se sont arretes grace a l'invalidation du
    # bail, pas grace a ce balayage -- donc un ouvrier sourd au bail, ou un bail
    # recree, n'aurait ete arrete par rien.
    "run_bounded_collector",
)
# Jamais tuer ceci même si le chemin projet matche (pas des collecteurs) :
# l'écran lui-même, le scellage détaché, la sync, le labo.
MARQUEURS_EXCLUS = (
    "affichage_temps_reel", "sceller_coffre_local", "archiver_tapes",
    "rapport_collecteurs", "sync_complete_clone", "alina_git_code_sync",
    "pousser-github", "alina_quant_lab", "alina_sync_complete",
    # 22/11/2026 -- FAUX « DEJA EN COURS » EN CONDITIONS REELLES. Les marqueurs ci-dessus sont des
    # SOUS-CHAINES : une suite de tests dont la ligne de commande citait
    # `tests/test_run_bounded_collector.py` et `tests/test_watch_economic_collectors.py` a ete
    # comptee comme un collecteur vivant, et le lanceur a refuse de demarrer. Le meme balayage
    # l'aurait TUEE sur un `--stop`. Un processus de test ou de verification n'est jamais un
    # collecteur, quels que soient les fichiers qu'il nomme. Marqueurs PRECIS : le seul mot
    # « pytest » se trouve aussi dans les dossiers temporaires (`pytest-of-<user>`), et l'utiliser
    # aurait rendu invisibles de vrais collecteurs lances depuis un tel dossier.
    "-m pytest", "pytest.exe", "py.test", "preflight_collecteurs",
)


def pids_collecteurs_a_tuer(processus, *, self_pid, racine) -> list[int]:
    """Sélectionne les PID de collecteurs du projet à arrêter — FONCTION PURE.

    ``processus`` : itérable de ``(pid:int, cmdline:str)``. On ne retient qu'un
    process dont la ligne de commande référence ``racine`` ET un marqueur
    collecteur ; jamais le process courant (``self_pid``) ni un marqueur exclu
    (écran, scellage, sync, labo). Indépendant de l'état de campagne (qui peut
    ne lister aucun pid). Insensible à la casse et au sens des slashes.
    """
    racine_norm = str(racine).replace("\\", "/").casefold().rstrip("/")
    a_tuer: set[int] = set()
    for pid, cmd in processus:
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        if pid <= 0 or pid == int(self_pid):
            continue
        c = (cmd or "").replace("\\", "/").casefold()
        if racine_norm and racine_norm not in c:
            continue
        if any(x in c for x in MARQUEURS_EXCLUS):
            continue
        if any(m in c for m in MARQUEURS_COLLECTEUR):
            a_tuer.add(pid)
    return sorted(a_tuer)


def lister_processus_projet(timeout: float = 30) -> list[tuple[int, str]]:
    """[(pid, cmdline)] des python/cmd (Windows) ; [] ailleurs ou en cas d'erreur."""
    if os.name != "nt":
        return []
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='py.exe' "
        "or Name='cmd.exe'\" | ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"
    )
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return []
    res: list[tuple[int, str]] = []
    for ligne in (done.stdout or "").splitlines():
        pid, _, cmd = ligne.partition("\t")
        pid = pid.strip()
        if pid.isdigit():
            res.append((int(pid), cmd))
    return res

# =============================================================================
# IDENTITE AVANT ARRET — 22/11/2026
#
# `LANCER_COLLECTEURS_COPY_VAULT.cmd` arretait les collecteurs de deux facons, toutes
# deux dangereuses :
#
#     taskkill /PID %%P /T /F                      <- PID lu dans un .pid, zero controle
#     taskkill /FI "WINDOWTITLE eq ALINA-POLL-*"   <- un TITRE n'est pas une identite
#
# Windows RECYCLE les PID : un `.pid` perime pointe un jour vers un innocent, et `/T /F`
# emporte tout son arbre. Pendant cette mission, douze `python.exe` tournaient sur le PC.
# Le titre de fenetre est pire : il n'appartient a personne.
#
# Ce qui suit refuse d'arreter ce qui ne s'identifie pas, et le DIT. Un refus compte ;
# il n'est ni avale, ni ignore.
# =============================================================================

MOTIF_IDENTIFIE = "IDENTIFIE"


def _pid_lisible(valeur) -> int | None:
    """Un PID entier strictement positif, ou `None`. Ne leve jamais : un `.pid` corrompu
    ne doit ni tuer quelqu'un, ni faire tomber le lanceur."""
    try:
        pid = int(str(valeur).strip())
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def identifier_pid(pid, *, processus, racine, proprietaire: str | None = None) -> dict:
    """Ce PID est-il VRAIMENT un collecteur de ce projet ? Rend un verdict MOTIVE.

    `processus` : iterable de dicts `{pid, cmdline, owner}` ou de couples `(pid, cmdline)`.
    Les motifs possibles : `PID_ILLISIBLE`, `INTROUVABLE`, `HORS_PROJET`,
    `PAS_UN_COLLECTEUR`, `EXCLU`, `AUTRE_PROPRIETAIRE`, `IDENTIFIE`.

    On exige TROIS choses, pas une : la ligne de commande reference la racine du projet,
    elle porte un marqueur de collecteur, et elle ne porte aucun marqueur exclu (ecran,
    scelleur, sync, labo). Le proprietaire s'ajoute quand l'appelant le demande.
    """
    numero = _pid_lisible(pid)
    if numero is None:
        return {"pid": pid, "identifie": False, "motif": "PID_ILLISIBLE", "marqueurs": []}

    trouve = None
    for entree in processus or ():
        if isinstance(entree, dict):
            courant, ligne = _pid_lisible(entree.get("pid")), entree.get("cmdline") or ""
            proprio = entree.get("owner")
        else:
            courant, ligne = _pid_lisible(entree[0]), (entree[1] or "")
            proprio = None
        if courant == numero:
            trouve = (ligne, proprio)
            break
    if trouve is None:
        return {"pid": numero, "identifie": False, "motif": "INTROUVABLE", "marqueurs": []}

    ligne, proprio = trouve
    c = ligne.replace("\\", "/").casefold()
    racine_norm = str(racine).replace("\\", "/").casefold().rstrip("/")
    base = {"pid": numero, "commande": ligne[:200], "proprietaire": proprio}
    if racine_norm and racine_norm not in c:
        return {**base, "identifie": False, "motif": "HORS_PROJET", "marqueurs": []}
    exclus = [m for m in MARQUEURS_EXCLUS if m in c]
    marqueurs = [m for m in MARQUEURS_COLLECTEUR if m in c]
    if exclus:
        return {**base, "identifie": False, "motif": "EXCLU", "marqueurs": exclus}
    if not marqueurs:
        return {**base, "identifie": False, "motif": "PAS_UN_COLLECTEUR", "marqueurs": []}
    if proprietaire is not None and str(proprio or "").casefold() != str(proprietaire).casefold():
        return {**base, "identifie": False, "motif": "AUTRE_PROPRIETAIRE",
                "marqueurs": marqueurs}
    return {**base, "identifie": True, "motif": MOTIF_IDENTIFIE, "marqueurs": marqueurs}


def arreter_surement(pids, *, processus, racine, tuer, proprietaire: str | None = None,
                     self_pid: int | None = None) -> dict:
    """Arrete UNIQUEMENT les PID identifies. Rend `{arretes, refuses, echecs}`.

    `tuer` est injecte : ce module ne decide pas COMMENT on arrete (signal, terminate,
    taskkill), seulement SI on a le droit. Cela le rend testable sans tuer personne.

    Un echec d'arret (droits, course) est RAPPORTE : un lanceur qui croit avoir arrete un
    collecteur encore vivant lancerait une seconde campagne par-dessus la premiere.
    """
    import os

    moi = int(self_pid) if self_pid is not None else os.getpid()
    arretes: list[int] = []
    refuses: list[dict] = []
    echecs: list[dict] = []
    for pid in pids or ():
        numero = _pid_lisible(pid)
        if numero is not None and numero == moi:
            refuses.append({"pid": numero, "motif": "PROCESS_COURANT"})
            continue
        verdict = identifier_pid(pid, processus=processus, racine=racine,
                                 proprietaire=proprietaire)
        if not verdict["identifie"]:
            refuses.append({"pid": verdict["pid"], "motif": verdict["motif"]})
            continue
        try:
            tuer(verdict["pid"])
        except Exception as erreur:          # noqa: BLE001 - tout echec doit etre RAPPORTE
            echecs.append({"pid": verdict["pid"],
                           "erreur": f"{type(erreur).__name__}: {erreur}"})
            continue
        arretes.append(verdict["pid"])
    return {"arretes": arretes, "refuses": refuses, "echecs": echecs}


#: Preambule du verrou : il rend le format RECONNAISSABLE, donc l'ancien format
#: (`%RANDOM%%RANDOM%`) identifiable comme tel au lieu d'etre lu comme un PID.
VERROU_ENTETE = "alina.collecteurs.verrou.v1"


def ecrire_verrou(chemin, *, pid: int, commande: str, horodatage_ms: int) -> None:
    """Ecrit un verrou qui porte une IDENTITE : PID, commande, instant de depart.

    L'ancien verrou contenait `%RANDOM%%RANDOM%` sous un commentaire annoncant << PID du
    cmd courant >>. Le code contredisait son commentaire, et personne ne pouvait savoir
    qui detenait le verrou -- donc ni le valider, ni le liberer en connaissance de cause.
    """
    import json
    from pathlib import Path

    destination = Path(chemin)
    destination.parent.mkdir(parents=True, exist_ok=True)
    charge = {"schema": VERROU_ENTETE, "pid": int(pid), "commande": str(commande),
              "horodatage_ms": int(horodatage_ms)}
    destination.write_text(json.dumps(charge, ensure_ascii=False) + "\n", encoding="utf-8")


def lire_verrou(chemin) -> dict:
    """Rend `{pid, commande, horodatage_ms, motif}`. `pid=None` + motif quand on ne sait pas.

    `ABSENT` et `FORMAT_ANCIEN_OU_ILLISIBLE` sont DISTINGUES : << pas de campagne >> et
    << je ne sais pas qui tient le verrou >> ne commandent pas la meme decision.
    """
    import json
    from pathlib import Path

    source = Path(chemin)
    if not source.is_file():
        return {"pid": None, "commande": None, "horodatage_ms": None, "motif": "ABSENT"}
    try:
        charge = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"pid": None, "commande": None, "horodatage_ms": None,
                "motif": "FORMAT_ANCIEN_OU_ILLISIBLE"}
    if not isinstance(charge, dict) or charge.get("schema") != VERROU_ENTETE:
        return {"pid": None, "commande": None, "horodatage_ms": None,
                "motif": "FORMAT_ANCIEN_OU_ILLISIBLE"}
    pid = _pid_lisible(charge.get("pid"))
    if pid is None:
        return {"pid": None, "commande": charge.get("commande"), "horodatage_ms": None,
                "motif": "FORMAT_ANCIEN_OU_ILLISIBLE"}
    return {"pid": pid, "commande": charge.get("commande"),
            "horodatage_ms": charge.get("horodatage_ms"), "motif": MOTIF_IDENTIFIE}

def lister_processus_detailles(timeout: float = 30) -> list[dict]:
    """`[{pid, cmdline, owner}]` des python/cmd — le PROPRIETAIRE en plus.

    `lister_processus_projet` reste la forme historique `(pid, cmdline)` et delegue ici :
    une seule interrogation du systeme, deux formes de lecture, aucune duplication.
    """
    import json
    import subprocess as sp

    if os.name != "nt":
        return []
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='py.exe' "
        "or Name='cmd.exe'\" | ForEach-Object { "
        "  $o = ''; try { $o = (Invoke-CimMethod -InputObject $_ "
        "    -MethodName GetOwner -ErrorAction Stop).User } catch { $o = '' }; "
        "  [pscustomobject]@{pid=$_.ProcessId; cmdline=$_.CommandLine; owner=$o} "
        "} | ConvertTo-Json -Compress"
    )
    try:
        done = sp.run(["powershell", "-NoProfile", "-Command", ps],
                      capture_output=True, text=True, timeout=timeout)
    except (OSError, sp.SubprocessError):
        return []
    try:
        charge = json.loads(done.stdout or "null")
    except ValueError:
        return []
    if isinstance(charge, dict):
        charge = [charge]
    sortie: list[dict] = []
    for ligne in charge or ():
        if not isinstance(ligne, dict):
            continue
        pid = _pid_lisible(ligne.get("pid"))
        if pid is None:
            continue
        sortie.append({"pid": pid, "cmdline": ligne.get("cmdline") or "",
                       "owner": ligne.get("owner") or ""})
    return sortie


def main(argv: list[str] | None = None) -> int:
    """Porte d'entree pour `LANCER_COLLECTEURS_COPY_VAULT.cmd`.

    `--lister`  : dit ce qui tourne (lecture seule, aucun arret).
    `--arreter` : arrete les collecteurs IDENTIFIES ; refuse et motive le reste.
    `--pid-de`  : ajoute les PID lus dans ces fichiers `.pid` aux candidats -- ils sont
                  verifies comme les autres, jamais crus sur parole.

    Code de sortie : 0 si tout s'est bien passe, 3 si un arret a ECHOUE (le lanceur doit
    alors refuser de demarrer une seconde campagne par-dessus), 2 sur usage invalide.
    """
    import argparse
    import json
    import sys
    import time

    p = argparse.ArgumentParser(description="Arret des collecteurs a identite verifiee.")
    p.add_argument("--racine", default=".")
    p.add_argument("--lister", action="store_true")
    p.add_argument("--compter", action="store_true",
                   help="n ecrit QUE le nombre de collecteurs identifies (pour le .cmd)")
    p.add_argument("--arreter", action="store_true")
    p.add_argument("--pid-de", action="append", default=[])
    p.add_argument("--proprietaire", default=None)
    p.add_argument("--verrou", default=None)
    args = p.parse_args(argv)

    flux = sys.stdout
    try:  # noqa: SIM105
        flux.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    racine = os.path.abspath(args.racine)
    processus = lister_processus_detailles()
    vivants = pids_collecteurs_a_tuer(
        [(x["pid"], x["cmdline"]) for x in processus], self_pid=os.getpid(), racine=racine)

    candidats = list(vivants)
    for chemin in args.pid_de:
        try:
            with open(chemin, encoding="utf-8", errors="replace") as fh:
                for ligne in fh:
                    pid = _pid_lisible(ligne)
                    if pid is not None and pid not in candidats:
                        candidats.append(pid)
        except OSError:
            continue

    if args.verrou:
        etat = lire_verrou(args.verrou)
        print(f"[VERROU] {etat['motif']} pid={etat['pid']}")

    if args.compter:
        # Une seule valeur, sans decor : le .cmd la lit par `set /p`. Un compteur lu par
        # une backquote coupait le chemin de python.exe au premier espace (mesure du
        # 22/11/2026), donc un zero obtenu PAR ECHEC, qui ressemblait a une mesure.
        print(len(vivants))
        return 0
    if args.lister or not args.arreter:
        print(f"[COLLECTEURS] {len(vivants)} identifie(s) par leur ligne de commande")
        for pid in vivants:
            verdict = identifier_pid(pid, processus=processus, racine=racine)
            print(f"   PID {pid} {','.join(verdict['marqueurs'])}")
        if not args.arreter:
            return 0

    bilan = arreter_surement(candidats, processus=processus, racine=racine,
                             tuer=_tuer_par_pid, proprietaire=args.proprietaire)
    print("[ARRET] " + json.dumps(
        {"arretes": bilan["arretes"],
         "refuses": [f"{r['pid']}:{r['motif']}" for r in bilan["refuses"]],
         "echecs": bilan["echecs"],
         "horodatage_ms": int(time.time() * 1000)}, ensure_ascii=False))
    return 3 if bilan["echecs"] else 0


def _tuer_par_pid(pid: int) -> None:
    """Arret REEL d'un PID deja identifie. Separe de la decision, pour que la decision
    puisse se tester sans tuer personne."""
    import signal as _signal

    try:
        import psutil
    except ImportError:
        os.kill(int(pid), getattr(_signal, "SIGTERM", 15))
        return
    proc = psutil.Process(int(pid))
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except psutil.TimeoutExpired:
        proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
