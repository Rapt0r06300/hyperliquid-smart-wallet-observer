"""LE LANCEUR DE TOUT-TESTER — en Python, parce que le batch n'était pas testable (21/07).

POURQUOI CE FICHIER EXISTE
--------------------------
J'ai écrit les 40 améliorations du lanceur directement dans `TOUT-TESTER.cmd` — 365 lignes de
batch — depuis un sandbox Linux où **je ne pouvais pas les exécuter**. Résultat au premier
lancement chez Flo : plantage immédiat, et deux fichiers parasites vides à la racine du projet.

    3.10   <- REM ... ^>= 3.10 ...            : dans cmd, `=` est un DELIMITEUR de token,
    (3     <- python -c "... version_info>=(3,10) ..."   donc `>=` redirige vers le token
                                                          suivant : `3.10`, puis `(3`.

Le script est mort **avant** d'avoir créé `logs-audit/` : aucune trace, aucun RECAP. Les
garde-fous de traçabilité que j'avais écrits n'ont servi à rien parce qu'ils étaient en aval
du plantage.

LA LEÇON, QUI EST UNE RÈGLE DU PROJET
-------------------------------------
« La vérité c'est Windows, pas le sandbox. » Du code que je ne peux pas exécuter ne doit pas
porter de logique. Le `.cmd` redevient donc un lanceur minimal — quelques lignes sans
parenthèse, sans `for /f`, sans redirection dans un commentaire — et **toute** la logique
vit ici, où chaque règle a son test.

LES 40 AMÉLIORATIONS, PAR FAMILLE
---------------------------------
  PRÉ-VOL 01-10        python, version, arborescence, disque, verrou, chemin, OneDrive
  SÉCURITÉ 11-15       interrupteurs d'exécution réelle, clés, READ_ONLY, bannière, empreinte
  TRAÇABILITÉ 16-25    session, log, archive du RECAP, git, durée, taille, péremption, purge
  ERGONOMIE 26-35      options, verdict, titre
  ROBUSTESSE 36-40     encodage, buffering, .pyc, Ctrl-C, code de sortie

PAPER only : lancer un audit en lecture seule n'est pas passer un ordre.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
RECAP = RACINE / "RECAP-COMPLET.md"
LOGDIR = RACINE / "logs-audit"
VERROU = RACINE / ".tout-tester.lock"

#: 01/02 — le code du projet utilise la syntaxe `X | None` (PEP 604).
VERSION_MIN = (3, 10)
#: 05 — en dessous, l'audit (RECAP + logs + rapports) risque de manquer de place.
DISQUE_MIN_GO = 1.0
#: 06 — un verrou plus vieux que ça appartient à un run mort : on ne bloque pas pour toujours.
VERROU_PERIME_S = 4 * 3600.0
#: 24 — on garde, mais on ne noie pas le dossier.
LOGS_CONSERVES = 30

#: 11 — un seul de ces interrupteurs armé et on refuse de démarrer.
INTERRUPTEURS_REELS = ("REAL_MAINNET_TRADING", "HYPERSMART_REAL_TRADING",
                       "ENABLE_REAL_ORDERS", "LIVE_TRADING")
#: 12 — ce projet n'utilise JAMAIS de clé. Une clé présente est une anomalie, pas un détail.
SECRETS = ("PRIVATE_KEY", "HL_PRIVATE_KEY", "MNEMONIC", "SEED_PHRASE", "WALLET_SECRET",
           "HYPERLIQUID_PRIVATE_KEY")

#: options consommées ICI ; tout le reste part au driver, qui possède la liste de référence.
OPTIONS_LANCEUR = {"--sans-pause": "ne pas attendre une touche a la fin",
                   "--ouvrir": "ouvrir le RECAP a la fin",
                   "--forcer": "ignorer un verrou existant"}

CODE_PREVOL, CODE_VERROU, CODE_SECURITE = 3, 4, 5


class Echec(Exception):
    """Un refus de démarrer, avec son code de sortie. Nommé : on ne meurt pas en silence."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


# ─────────────────────────────── PRÉ-VOL (01-10) ───────────────────────────────

def prevol(racine: Path = RACINE) -> list[str]:
    """Vérifie que l'environnement peut porter une heure de calcul. Lève `Echec` sinon."""
    lignes: list[str] = []
    if sys.version_info[:2] < VERSION_MIN:                                   # 01/02
        raise Echec("Python %s est trop ancien : il faut %d.%d ou plus."
                    % (".".join(map(str, sys.version_info[:3])), *VERSION_MIN), CODE_PREVOL)
    lignes.append("python %s" % ".".join(map(str, sys.version_info[:3])))
    for rel in ("tools/tout_tester.py", "src"):                              # 03/04
        if not (racine / rel).exists():
            raise Echec("%s introuvable sous %s — le lanceur a-t-il ete deplace ?"
                        % (rel, racine), CODE_PREVOL)
    try:                                                                     # 05
        libre_go = shutil.disk_usage(racine).free / 1e9
        lignes.append("espace libre %.1f Go" % libre_go)
        if libre_go < DISQUE_MIN_GO:
            raise Echec("seulement %.1f Go libres : l'audit ecrit RECAP, logs et rapports."
                        % libre_go, CODE_PREVOL)
    except OSError:
        lignes.append("espace libre : inconnu")
    p = str(racine)                                                          # 09
    if "onedrive" in p.lower():
        lignes.append("ATTENTION : projet sous OneDrive — la synchro peut modifier des "
                      "fichiers PENDANT l'audit")
    if p.startswith("\\\\"):
        lignes.append("ATTENTION : chemin reseau — l'audit sera lent et fragile")
    return lignes


def prendre_verrou(racine: Path = RACINE, *, forcer: bool = False) -> None:
    """06 — deux audits en parallèle se marchent dessus. Un verrou périmé est ignoré : sinon
    un crash bloquerait tous les lancements suivants, ce qui serait pire que le mal."""
    v = racine / VERROU.name
    try:
        age = time.time() - v.stat().st_mtime
    except OSError:
        age = None
    if age is not None and age < VERROU_PERIME_S and not forcer:
        raise Echec("un audit tourne deja (verrou pose il y a %.0f min). Relance avec "
                    "--forcer si c'est faux, ou supprime %s" % (age / 60, v.name), CODE_VERROU)
    try:
        v.write_text("%d %s" % (os.getpid(), time.strftime("%Y-%m-%d %H:%M:%S")),
                     encoding="utf-8")
    except OSError:
        pass


def liberer_verrou(racine: Path = RACINE) -> None:
    try:
        (racine / VERROU.name).unlink()
    except OSError:
        pass


# ─────────────────────────────── SÉCURITÉ (11-15) ───────────────────────────────

def controle_securite(env: dict[str, str] | None = None) -> str:
    """11/12 — TOUT-TESTER est un outil de LECTURE SEULE et refuse de tourner à côté d'un
    interrupteur d'exécution réelle ou d'une clé privée. Lève `Echec` sinon."""
    e = dict(os.environ if env is None else env)
    for var in INTERRUPTEURS_REELS:
        if str(e.get(var, "")).strip().lower() in ("1", "true", "yes", "on"):
            raise Echec("la variable %s est ARMEE dans cet environnement. Un outil de lecture "
                        "seule ne tourne pas a cote d'un interrupteur d'execution reelle."
                        % var, CODE_SECURITE)
    for var in SECRETS:
        if str(e.get(var, "")).strip():
            raise Echec("%s est presente dans l'environnement. Ce projet n'utilise JAMAIS de "
                        "cle : retire-la avant de lancer quoi que ce soit." % var,
                        CODE_SECURITE)
    return "aucun interrupteur d'execution reelle, aucune cle"


def environnement_fils(racine: Path = RACINE) -> dict[str, str]:
    """13/36/37/38 — ce qu'on impose au processus qui fait le travail."""
    e = dict(os.environ)
    e["PYTHONPATH"] = os.pathsep.join([str(racine / "src"), e.get("PYTHONPATH", "")])
    e["PYTHONIOENCODING"] = "utf-8"
    e["PYTHONDONTWRITEBYTECODE"] = "1"      # les .pyc periment a travers le mount
    e["PYTHONUNBUFFERED"] = "1"             # la progression s'affiche en direct
    e["HYPERSMART_READ_ONLY"] = "1"
    e["HYPERSMART_PAPER_ONLY"] = "1"
    return e


# ─────────────────────────────── TRAÇABILITÉ (16-25) ───────────────────────────────

def etat_git(racine: Path = RACINE) -> str:
    """19 — 5 jours de travail non commité avaient été découverts le 14/07 parce que personne
    ne regardait. L'audit juge le DISQUE ; il doit dire ce que le disque a de plus que git."""
    def _git(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=racine, capture_output=True, text=True,
                                  timeout=15, encoding="utf-8", errors="replace").stdout.strip()
        except Exception:  # noqa: BLE001
            return ""
    tete, branche = _git("rev-parse", "--short", "HEAD"), _git("rev-parse", "--abbrev-ref", "HEAD")
    if not tete:
        return "git indisponible"
    sales = [l for l in _git("status", "--porcelain").splitlines() if l.strip()]
    s = "%s @ %s — %d fichier(s) non commite(s)" % (branche or "?", tete, len(sales))
    return s + ("  (l'audit juge le DISQUE, pas le dernier commit)" if sales else "")


def archiver_recap(racine: Path = RACINE, *, session: str) -> str:
    """18 — le RECAP précédent est ARCHIVÉ, jamais écrasé."""
    src = racine / RECAP.name
    if not src.exists():
        return ""
    dest = racine / LOGDIR.name / "recaps"
    try:
        dest.mkdir(parents=True, exist_ok=True)
        cible = dest / ("RECAP-%s.md" % session)
        shutil.copy2(src, cible)
        return str(cible.relative_to(racine))
    except OSError:
        return ""


def purger_logs(racine: Path = RACINE, *, garder: int = LOGS_CONSERVES) -> int:
    """24 — on garde, mais on ne noie pas le dossier."""
    d = racine / LOGDIR.name
    try:
        logs = sorted(d.glob("tout-tester-*.log"), key=lambda p: p.stat().st_mtime,
                      reverse=True)
    except OSError:
        return 0
    n = 0
    for vieux in logs[max(0, int(garder)):]:
        try:
            vieux.unlink()
            n += 1
        except OSError:
            pass
    return n


def verdict_recap(racine: Path = RACINE, *, debut_ts: float) -> dict[str, Any]:
    """22/25 — le RECAP existe-t-il, n'est-il pas vide, et vient-il bien de CE run ?

    Le pire échec silencieux : le run plante, le RECAP d'hier reste en place, et on le lit en
    croyant lire celui d'aujourd'hui.
    """
    p = racine / RECAP.name
    try:
        st = p.stat()
    except OSError:
        return {"present": False, "vide": True, "perime": False,
                "message": "RECAP ABSENT : envoie la fenetre a Claude."}
    if st.st_size == 0:
        return {"present": True, "vide": True, "perime": False, "octets": 0,
                "message": "RECAP VIDE (0 octet) : envoie la fenetre a Claude."}
    perime = st.st_mtime < debut_ts
    return {"present": True, "vide": False, "perime": perime, "octets": st.st_size,
            "message": ("RECAP NON REECRIT par ce run : tu lirais les resultats du run "
                        "PRECEDENT." if perime
                        else "RECAP ecrit (%d octets) — c'est CE fichier a envoyer a Claude."
                             % st.st_size)}


# ─────────────────────────────── LE RUN ───────────────────────────────

def lancer(argv: list[str] | None = None, racine: Path = RACINE) -> int:
    brut = list(sys.argv[1:] if argv is None else argv)
    pause = "--sans-pause" not in brut
    ouvrir = "--ouvrir" in brut
    forcer = "--forcer" in brut
    args = [a for a in brut if a not in OPTIONS_LANCEUR]

    session = time.strftime("%Y%m%d-%H%M%S")
    debut = time.time()
    (racine / LOGDIR.name).mkdir(parents=True, exist_ok=True)
    log = racine / LOGDIR.name / ("tout-tester-%s.log" % session)
    trace: list[str] = []

    def dire(s: str = "") -> None:
        print(s, flush=True)
        trace.append(s)

    dire("")
    dire("  ============================================================")
    dire("    TOUT-TESTER : securite, tests, cablage, donnees,")
    dire("    recherche de pepites, sante live.")
    dire("  ============================================================")
    dire("    LECTURE SEULE — 0 ordre reel, 0 argent reel, 0 cle privee.")   # 14
    dire("    session %s" % session)
    dire("")

    code = 0
    try:
        for l in prevol(racine):                                             # 01-10
            dire("  [PRE-VOL] %s" % l)
        dire("  [SECURITE] %s" % controle_securite())                        # 11/12
        prendre_verrou(racine, forcer=forcer)                                # 06
    except Echec as exc:
        dire("")
        dire("  ARRET : %s" % exc)
        dire("")
        _ecrire_log(log, session, racine, trace, debut, exc.code)
        if pause:
            _pause()
        return exc.code

    try:
        dire("  [GIT] %s" % etat_git(racine))                                # 19
        arch = archiver_recap(racine, session=session)                       # 18
        if arch:
            dire("  [ARCHIVE] RECAP precedent conserve : %s" % arch)
        dire("")
        dire("  --- lancement : tools/tout_tester.py %s ---" % " ".join(args))
        dire("")
        # ISOLATION DU GROUPE (invariant test_outils_isoles_du_ctrl_c) : tout sous-processus
        # qui touche a pytest recoit son PROPRE groupe. Sans `creationflags`, un Ctrl-C console
        # tuerait tout_tester.py AVANT qu'il n'ecrive le RECAP — le bug du 11/07 (audit_report)
        # et du 13/07 (couverture). On NE capture PAS la sortie de l'orchestrateur : le lanceur
        # STREAME sa progression en direct (run_isole capturerait, on ne l'utilise donc pas ici).
        from tools.sous_processus_isole import creationflags as _cflags
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pytest-timeout"],
                           cwd=racine, capture_output=True, timeout=120,
                           creationflags=_cflags())                          # 07
        except Exception:  # noqa: BLE001
            pass
        p = subprocess.run([sys.executable, str(racine / "tools" / "tout_tester.py"), *args],
                           cwd=racine, env=environnement_fils(racine),
                           creationflags=_cflags())
        code = p.returncode
    except KeyboardInterrupt:                                                # 39
        code = 130
        dire("")
        dire("  INTERROMPU (Ctrl-C) — le RECAP couvre les etapes deja faites.")
    finally:
        liberer_verrou(racine)

    duree = time.time() - debut                                              # 20/21
    dire("")
    dire("  ============================================================")
    dire("    duree : %s   | session %s" % (_hms(duree), session))
    v = verdict_recap(racine, debut_ts=debut)                                # 22/25
    dire("    %s" % v["message"])
    dire("    %s" % _verdict(code))                                          # 33
    dire("  ============================================================")
    n = purger_logs(racine)                                                  # 24
    if n:
        dire("    %d vieux log(s) purge(s) (on garde les %d derniers)" % (n, LOGS_CONSERVES))
    dire("    log de session : %s" % log.relative_to(racine))
    _ecrire_log(log, session, racine, trace, debut, code)                    # 17/23
    if ouvrir and v.get("present") and not v.get("vide"):                    # 31
        _ouvrir(racine / RECAP.name)
    if pause:                                                                # 30
        _pause()
    return code                                                              # 40


def _verdict(code: int) -> str:
    return {0: "TOUT EST VERT.",
            2: "OPTION INCONNUE — rien n'a ete lance.  TOUT-TESTER.cmd --aide",
            130: "INTERROMPU."}.get(
        code, "Des etapes ont ECHOUE (code %d) — le detail est dans le RECAP." % code)


def _hms(s: float) -> str:
    s = int(max(0.0, s))
    return "%02d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60)


def _ecrire_log(log: Path, session: str, racine: Path, trace: list[str],
                debut: float, code: int) -> None:
    """15/17/23 — l'empreinte de sécurité en tête, la trace, le code de sortie."""
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        entete = [
            "TOUT-TESTER — session %s" % session,
            "projet   : %s" % racine,
            "debut    : %s" % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(debut)),
            "securite : READ_ONLY=1 PAPER_ONLY=1 · 0 ordre reel · 0 cle · 0 signature",
            "duree    : %s" % _hms(time.time() - debut),
            "code     : %d" % code,
            "",
        ]
        log.write_text("\n".join(entete + trace) + "\n", encoding="utf-8")
    except OSError:
        pass


def _ouvrir(p: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))                       # noqa: S606 — ouverture d'un .md local
        else:
            subprocess.run(["xdg-open", str(p)], capture_output=True, timeout=10)
    except Exception:  # noqa: BLE001
        pass


def _pause() -> None:
    try:
        input("\n  Appuie sur Entree pour fermer...")
    except (EOFError, KeyboardInterrupt):
        pass


def etat_json(racine: Path = RACINE) -> str:
    """Diagnostic machine-lisible, pour les tests et pour TOUT-TESTER lui-meme."""
    return json.dumps({"racine": str(racine), "python": sys.version.split()[0],
                       "recap": (racine / RECAP.name).exists(),
                       "verrou": (racine / VERROU.name).exists(),
                       "real_execution": False}, ensure_ascii=False)


def point_d_entree(argv: list[str] | None = None) -> int:
    """LE FILET DE SÉCURITÉ. Une fenêtre qui se ferme sans rien dire est le pire mode
    d'échec possible : Flo n'a alors AUCUNE information à me transmettre.

    Le `.cmd` ne peut plus rien garantir (il n'a plus ni `goto` ni bloc, précisément parce
    que ces constructions le faisaient mourir en silence). C'est donc ici, en Python, que
    l'on garantit qu'une erreur — même une exception jamais prévue, même une erreur à
    l'import — s'AFFICHE et attende une touche avant de disparaître.
    """
    try:
        return lancer(argv)
    except Echec as exc:                       # refus de démarrer : déjà lisible
        print("\n  ARRET : %s\n" % exc, flush=True)
        _pause()
        return exc.code
    except KeyboardInterrupt:
        print("\n  INTERROMPU (Ctrl-C).\n", flush=True)
        return 130
    except BaseException:                      # noqa: BLE001 — y compris SystemExit imprévu
        import traceback
        print("\n" + "=" * 62, flush=True)
        print("  LE LANCEUR A PLANTE. Copie ce qui suit et envoie-le a Claude :", flush=True)
        print("=" * 62, flush=True)
        # sur STDOUT, pas stderr : Flo copie une fenetre, pas deux flux. Deux flux
        # s'entrelacent et la traceback se retrouve coupee en morceaux illisibles.
        traceback.print_exc(file=sys.stdout)
        print("=" * 62, flush=True)
        _pause()
        return 1


if __name__ == "__main__":
    raise SystemExit(point_d_entree())
