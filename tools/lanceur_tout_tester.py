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
#: 41 (22/07) — FILET ANTI-BLOCAGE. Le run complet dure ~1 h 15 ; ce plafond très large (4 h)
#: n'ampute jamais un run légitime mais garantit qu'un sous-processus figé (réseau bloqué, pytest
#: coincé) NE FAIT PAS tourner l'audit à l'infini. Sans lui, « ça ne finit jamais » = un plantage
#: silencieux d'un autre genre. Réglable par env pour les cas extrêmes.
try:
    BUDGET_TOTAL_S = float(os.environ.get("TOUT_TESTER_BUDGET_S", "") or 4 * 3600.0)
except (TypeError, ValueError):
    BUDGET_TOTAL_S = 4 * 3600.0

#: 11 — un seul de ces interrupteurs armé et on refuse de démarrer.
INTERRUPTEURS_REELS = ("REAL_MAINNET_TRADING", "HYPERSMART_REAL_TRADING",
                       "ENABLE_REAL_ORDERS", "LIVE_TRADING")
#: 12 — ce projet n'utilise JAMAIS de clé. Une clé présente est une anomalie, pas un détail.
SECRETS = ("PRIVATE_KEY", "HL_PRIVATE_KEY", "MNEMONIC", "SEED_PHRASE", "WALLET_SECRET",
           "HYPERLIQUID_PRIVATE_KEY")

#: options consommées ICI ; tout le reste part au driver, qui possède la liste de référence.
OPTIONS_LANCEUR = {"--sans-pause": "ne pas attendre une touche a la fin",
                   "--ouvrir": "ouvrir le RECAP a la fin",
                   "--forcer": "ignorer un verrou existant",
                   "--derniers-echecs": "afficher les echecs du DERNIER run, sans relancer",
                   "--sans-triage": "ne pas afficher le triage des echecs a la fin"}

CODE_PREVOL, CODE_VERROU, CODE_SECURITE = 3, 4, 5

#: où l'on garde la liste des échecs du run précédent, pour dire ce qui est NOUVEAU / RÉPARÉ.
ETAT_ECHECS = LOGDIR / "derniers_echecs.json"


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


def _cflags() -> int:
    """`creationflags` pour isoler le groupe de process (un Ctrl-C console ne doit pas tuer
    l'orchestrateur AVANT qu'il n'écrive le RECAP — bug du 11/07).

    🔴 22/07 — IMPORT ROBUSTE. `tools/` n'a pas d'`__init__.py` : selon la façon dont le lanceur
    démarre, le module d'isolation est importable en direct (`python tools/x.py` -> `tools/` est
    sur sys.path) OU via `tools.` (racine sur sys.path, cas des tests). L'ancien code n'essayait
    QUE `from tools.sous_processus_isole import` : dans l'invocation réelle, cet import lève
    `ModuleNotFoundError` -> le run ratait. On tente les deux formes, puis 0 (aucune isolation) —
    un run SANS isolation vaut infiniment mieux qu'un run qui plante à l'import."""
    d = str(RACINE / "tools")
    if d not in sys.path:
        sys.path.insert(0, d)
    for nom in ("sous_processus_isole", "tools.sous_processus_isole"):
        try:
            mod = __import__(nom, fromlist=["creationflags"])
            return int(mod.creationflags())
        except Exception:  # noqa: BLE001 — un import fragile ne doit JAMAIS faire échouer l'audit
            continue
    return 0


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

# ─────────────────────────────── TRIAGE DES ÉCHECS (nouveau) ───────────────────────────────
# Le pire moment d'un audit rate, c'est celui ou l'on SCROLLE la fenetre pour lire les 53 lignes
# FAILED a la main (exactement ce que Flo a fait 3 fois le 21/07). Le RECAP les contient deja,
# dans ses blocs `<details>`. Le lanceur les EXTRAIT et te les met sous les yeux, avec le diff
# vs la fois d'avant : ce qui est NOUVEAU (= une regression, la seule chose vraiment urgente) et
# ce qui est REPARE. Un audit qui te fait chercher ses propres resultats fait la moitie du travail.

def resumer_echecs_du_recap(recap: str | Path = RECAP) -> dict[str, Any]:
    """Extrait du RECAP : la ligne de resume pytest et la LISTE des tests FAILED.

    Lecture seule, tolerante : un RECAP absent ou tronque -> un resume vide, jamais une
    exception. On ne fait pas tomber le lanceur pour afficher un bonus.
    """
    import re
    out: dict[str, Any] = {"failed": [], "resume": "", "n_failed": 0, "n_passed": 0,
                           "present": False}
    try:
        txt = Path(recap).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    out["present"] = True
    # les noms de tests : `FAILED tests/xxx.py::test_yyy` (pytest) ou `tests/xxx.py::test_yyy FAILED`
    vus: set[str] = set()
    for m in re.finditer(r"(tests/[\w/]+\.py::[\w\[\]./-]+)", txt):
        nom = m.group(1)
        # ne garder que ceux marques FAILED sur la meme ligne (evite d'attraper des noms cites)
        ligne = txt[txt.rfind("\n", 0, m.start()) + 1: txt.find("\n", m.end())]
        if "FAILED" in ligne and nom not in vus:
            vus.add(nom)
            out["failed"].append(nom)
    for m in re.finditer(r"(\d+)\s+failed", txt):
        out["n_failed"] = max(out["n_failed"], int(m.group(1)))
    for m in re.finditer(r"(\d+)\s+passed", txt):
        out["n_passed"] = max(out["n_passed"], int(m.group(1)))
    ligne_resume = ""
    for l in txt.splitlines():
        if ("passed" in l or "failed" in l) and re.search(r"\d+\s+(passed|failed)", l):
            ligne_resume = l.strip().strip("`= ").strip()
    out["resume"] = ligne_resume
    out["failed"] = sorted(out["failed"])
    return out


def comparer_aux_echecs_precedents(failed: list[str], racine: Path = RACINE) -> dict[str, Any]:
    """{nouveaux, repares, persistants} vs le run precedent, puis MEMORISE le run courant.

    « Nouveaux » = regressions : les seuls echecs vraiment urgents (le reste est deja connu).
    L'etat precedent illisible -> tout est considere « persistant » (aucun faux « nouveau »).
    """
    chemin = racine / ETAT_ECHECS.relative_to(RACINE)
    courant = set(failed or [])
    avant: set[str] = set()
    a_un_precedent = False
    try:
        avant = set(json.loads(chemin.read_text(encoding="utf-8")).get("failed") or [])
        a_un_precedent = chemin.exists()
    except (OSError, ValueError):
        avant, a_un_precedent = set(), False    # base illisible = PAS de base fiable
    if not a_un_precedent:
        # sans base fiable, on ne CRIE PAS « regression » : tout est « deja connu » par defaut.
        # Une fausse regression envoie chasser un bug qui n'en est pas un.
        diff = {"nouveaux": [], "repares": [], "persistants": sorted(courant),
                "avait_un_precedent": False}
    else:
        diff = {"nouveaux": sorted(courant - avant), "repares": sorted(avant - courant),
                "persistants": sorted(courant & avant), "avait_un_precedent": True}
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps({"failed": sorted(courant),
                                      "ts": time.time()}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return diff


def lignes_de_triage(resume: dict[str, Any], diff: dict[str, Any] | None = None) -> list[str]:
    """Le bloc lisible affiché en fin de run (et par `--derniers-echecs`)."""
    failed = resume.get("failed") or []
    if not failed and not resume.get("n_failed"):
        return ["  ✅ aucun test en echec dans le RECAP."]
    out = ["  ─────────────────────────────────────────────────────────",
           "  ÉCHECS (%d) — les voici, tu n'as PAS a ouvrir le RECAP :" % (
               resume.get("n_failed") or len(failed))]
    for nom in failed[:60]:
        marque = "  🆕" if diff and nom in (diff.get("nouveaux") or []) else "    "
        out.append("%s %s" % (marque, nom))
    if len(failed) > 60:
        out.append("    … et %d autre(s) — voir le RECAP." % (len(failed) - 60))
    if diff and diff.get("avait_un_precedent"):
        out.append("  ── depuis la derniere fois : %d nouveau(x) (🆕 = REGRESSION, le plus urgent) "
                   "· %d repare(s)" % (len(diff.get("nouveaux") or []),
                                       len(diff.get("repares") or [])))
        for nom in (diff.get("repares") or [])[:8]:
            out.append("    ✅ repare : %s" % nom)
    out.append("  → copie ce bloc a Claude : il sait quoi en faire.")
    out.append("  ─────────────────────────────────────────────────────────")
    return out


def lancer(argv: list[str] | None = None, racine: Path = RACINE) -> int:
    brut = list(sys.argv[1:] if argv is None else argv)
    pause = "--sans-pause" not in brut
    ouvrir = "--ouvrir" in brut
    forcer = "--forcer" in brut
    triage = "--sans-triage" not in brut
    args = [a for a in brut if a not in OPTIONS_LANCEUR]

    # --derniers-echecs : triage INSTANTANE du dernier RECAP, sans rien relancer (~0 s).
    if "--derniers-echecs" in brut:
        resume = resumer_echecs_du_recap(racine / RECAP.name)
        if not resume["present"]:
            print("  aucun RECAP-COMPLET.md — lance d'abord TOUT-TESTER.cmd.", flush=True)
        else:
            print("  dernier run : %s" % (resume["resume"] or "resume introuvable"), flush=True)
            for l in lignes_de_triage(resume):
                print(l, flush=True)
        if pause:
            _pause()
        return 0 if not resume.get("n_failed") else 1

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
        # 07 — outils pytest : timeout (cap par test) + xdist (parallélisme = suite plus rapide).
        # 22/07 : on n'installe QUE ce qui MANQUE — une fois en place, plus aucun aller-retour pip
        # (gain de temps + aucun blocage réseau à chaque lancement).
        import importlib.util as _iu
        _manque = [pkg for pkg, mod in (("pytest-timeout", "pytest_timeout"),
                                        ("pytest-xdist", "xdist")) if _iu.find_spec(mod) is None]
        if _manque:
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", "-q", *_manque],
                               cwd=racine, capture_output=True, timeout=180,
                               creationflags=_cflags())                      # 07
            except Exception:  # noqa: BLE001
                pass
        # 22/07 — Popen (pas subprocess.run) pour pouvoir TUER L'ARBRE au timeout : run() ne tuerait
        # que tout_tester.py et laisserait la recherche + workers orphelins (le bug vécu par Flo).
        # start_new_session : groupe POSIX pour killpg ; _cflags() : groupe Windows pour taskkill /T.
        proc = subprocess.Popen(
            [sys.executable, str(racine / "tools" / "tout_tester.py"), *args],
            cwd=racine, env=environnement_fils(racine),
            creationflags=_cflags(), start_new_session=True)
        try:
            code = proc.wait(timeout=BUDGET_TOTAL_S)                          # 41 filet anti-blocage
        except subprocess.TimeoutExpired:
            _tuer_arbre(proc)                        # TOUT l'arbre, sinon workers orphelins
            try:
                proc.wait(timeout=30)
            except Exception:  # noqa: BLE001
                pass
            raise
    except KeyboardInterrupt:                                                # 39
        code = 130
        _tuer_arbre(locals().get("proc"))           # 22/07 : Ctrl-C coupe l'arbre -> la fenetre se libere
        dire("")
        dire("  INTERROMPU (Ctrl-C) — arret propre, recherche et workers coupes. Relance pour un RECAP complet.")
    except subprocess.TimeoutExpired:                                        # 41
        code = 124
        dire("")
        dire("  BUDGET DE TEMPS DEPASSE (%s) : un sous-processus s'est FIGE. L'audit s'arrete"
             % _hms(BUDGET_TOTAL_S))
        dire("  proprement (TOUT l'arbre a ete coupe, aucun orphelin). Le RECAP couvre les etapes faites.")
    except Exception as _exc:  # noqa: BLE001 — 22/07 : plus AUCUNE exception du run ne fuit sans trace
        code = 1
        dire("")
        dire("  ERREUR PENDANT LE RUN : %s" % str(_exc)[:200])
        dire("  (le filet Python l'a capturee — la fenetre reste ouverte, envoie ce bloc a Claude)")
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
    # 🔴 21/07 — TRIAGE DES ÉCHECS, sous les yeux, sans scroller. Le RECAP contient les lignes
    # FAILED ; on les extrait et on dit ce qui est NOUVEAU (regression) vs REPARE depuis la fois
    # d'avant. C'est CE bloc que Flo copie a Claude — plus besoin d'une capture d'ecran.
    if triage and code not in (0, 2, 130):
        try:
            resume = resumer_echecs_du_recap(racine / RECAP.name)
            diff = comparer_aux_echecs_precedents(resume.get("failed") or [], racine)
            for l in lignes_de_triage(resume, diff):
                dire(l)
        except Exception as exc:  # noqa: BLE001 — un bonus d'affichage ne fait jamais echouer le run
            dire("    (triage des echecs indisponible : %s)" % str(exc)[:80])
    elif triage and code == 0:
        # run vert : on MEMORISE l'ensemble vide, pour que le prochain diff soit juste.
        comparer_aux_echecs_precedents([], racine)
    # 22/07 — BOT-READY (score de maturite + niveau d'autonomie SUR) + CERVELLE (« comprendre le
    # PnL & trouver l'edge »). Affiches a l'ecran ET ecrits DANS le RECAP.md : Flo (« le fichier
    # .md doit etre ULTRA riche pour Claude, analyse mot par mot ») veut que le .md qu'il m'envoie
    # contienne TOUT — le score, la synthese edge, la prochaine action. Sinon je pilote a l'aveugle.
    # Try/except partout : un bonus d'analyse ne fait JAMAIS echouer l'audit.
    _enrichissement: list[str] = []
    try:
        if str(racine / "src") not in sys.path:
            sys.path.insert(0, str(racine / "src"))
        from hl_observer.ops import loop_readiness as _LR
        _bloc = _LR.markdown(_LR.depuis_le_recap(racine))
        for _l in _bloc.splitlines():
            dire(_l)
        _enrichissement.append(_bloc)
    except Exception as _exc:  # noqa: BLE001 — jamais fatal
        dire("    (BOT-READY indisponible : %s)" % str(_exc)[:80])
    try:
        if str(racine / "src") not in sys.path:
            sys.path.insert(0, str(racine / "src"))
        from hl_observer.ops import diagnostic_pnl as _DPNL
        _bloc = _DPNL.construire(racine)
        dire("")
        for _l in _bloc.splitlines():
            dire(_l)
        _enrichissement.append(_bloc)
    except Exception as _exc:  # noqa: BLE001 — jamais fatal
        dire("    (diagnostic PnL indisponible : %s)" % str(_exc)[:80])
    if _enrichissement:            # ON ENRICHIT LE .md (append best-effort, jamais fatal)
        try:
            with (racine / RECAP.name).open("a", encoding="utf-8") as _fh:
                _fh.write("\n\n---\n\n" + "\n\n".join(_enrichissement) + "\n")
        except OSError:
            pass
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
            124: "BUDGET DE TEMPS DEPASSE — un sous-processus s'est fige, l'audit s'est arrete net.",
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


def _tuer_arbre(proc) -> None:
    """Tue le processus ET toute sa descendance (workers compris). 22/07 — sans ça, sous Windows,
    un timeout ou un Ctrl-C ne tue que `tout_tester.py` et laisse la recherche + ses workers tourner
    ORPHELINS (le blocage 114 min vu par Flo, Ctrl-C sans effet). psutil si présent (portable),
    sinon `taskkill /T` (Windows) ou `killpg` (POSIX). Idempotent, jamais une exception qui remonte."""
    if proc is None:
        return
    try:
        import psutil  # type: ignore
        p = psutil.Process(proc.pid)
        for enfant in p.children(recursive=True):
            try:
                enfant.kill()
            except Exception:  # noqa: BLE001
                pass
        p.kill()
        return
    except Exception:  # noqa: BLE001 — psutil absent ou course : repli natif
        pass
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=15)
        else:
            os.killpg(os.getpgid(proc.pid), 9)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
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
        _pause()                                   # 22/07 : la fenetre reste ouverte meme sur Ctrl-C
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
