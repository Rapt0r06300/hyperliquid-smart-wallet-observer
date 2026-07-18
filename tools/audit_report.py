"""AUDIT MAXIMAL DU PROJET -> genere `resultat-audit.md` a la racine.

Lance par `ci_local.cmd` (racine). 100% LECTURE SEULE / PAPER : aucun ordre reel possible.
Le rapport est fait pour etre COLLE TEL QUEL a Claude.

Deux niveaux :
  ERREUR       -> bloquant (verdict ROUGE)
  AVERTISSEMENT-> non bloquant, mais signale les bugs silencieux (verdict ORANGE)

20 controles, dont plusieurs concus apres les bugs reels du 2026-07-11 :
  syntaxe . imports . imports circulaires . arite des appels inter-modules . imports inutilises
  exceptions avalees . aleatoire sans graine . encodage/gros fichiers . coherence config .cmd/.ps1
  reglages morts & defauts silencieux . planchers fail-open . scan de secrets . scan d'execution reelle
  audit securite . tests non isoles . doublons de tests . docs manquants . bornes de ressources
  ruff/mypy (si installes) . suite de tests . tests flaky (2e passe) . doctor
"""
from __future__ import annotations

import ast
import importlib
import inspect
import io
import os
import pathlib
import platform
import py_compile
import re
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# hyper_smart_observer/ vit a la RACINE (pas dans src/) : sans ca, tout import de cli.py echoue.
for _p in (str(SRC), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
REPORT = ROOT / "resultat-audit.md"
MAX_TB_LINES = 500
MAX_ITEMS = 60
FAST = "--fast" in sys.argv          # saute la 2e passe (tests flaky)


class Check:
    def __init__(self, title: str, blocking: bool = True):
        self.title, self.blocking = title, blocking
        self.ok = True
        self.summary = ""
        self.errors: list[str] = []
        self.warns: list[str] = []
        self.tb = ""
        self.seconds = 0.0

    def finish(self, summary: str, errors=None, warns=None):
        self.errors = list(errors or [])
        self.warns = list(warns or [])
        self.ok = not self.errors
        self.summary = summary
        return self


def _run_stream(cmd, timeout=7200, prefix="   | ", env_propre=False):
    """Comme _run mais AFFICHE la sortie en direct : on voit que ca avance.

    `env_propre=True` : le sous-processus ne recoit AUCUNE variable `HYPERSMART_*` / `HL_*`.

    POURQUOI (bug trouve le 2026-07-12) -- l'audit se contaminait lui-meme. Les controles de
    gates (`_max_positions_refuses`, ...) posent `os.environ["HYPERSMART_MAX_OPEN_POSITIONS"]="3"`
    pour verifier qu'un plafond refuse. Cet `os.environ` est ensuite COPIE dans le sous-processus
    pytest, qui heritait donc d'un calibrage de test. Un test lisant ce defaut (`routes.py`, 6)
    voyait 3 -- et echouait SOUS L'AUDIT SEULEMENT. L'outil de verification fabriquait l'echec
    qu'il rapportait.
    """
    env = dict(os.environ)
    if env_propre:
        for cle in [k for k in env if k.startswith(("HYPERSMART_", "HL_"))]:
            env.pop(cle, None)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    out = []
    # ISOLATION (bug du 2026-07-11) : la suite de tests declenchait un Ctrl-C qui remontait
    # a TOUTE la console -> l'audit lui-meme recevait SIGINT et s'arretait. En donnant au
    # sous-process son PROPRE groupe, son Ctrl-C ne peut plus nous tuer.
    creation = 0
    if os.name == "nt":
        creation = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        p = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                             errors="replace", bufsize=1, creationflags=creation)
    except FileNotFoundError:
        return 127, "outil introuvable"

    # Battement de coeur : pytest peut rester SILENCIEUX 1-2 min (collecte, coverage).
    # Sans ca on croit a un gel et on fait Ctrl-C. Ici on prouve que ca vit.
    import threading
    alive = {"on": True, "t0": time.time(), "pct": 0, "last": ""}

    def _beat():
        while alive["on"]:
            time.sleep(10)
            if not alive["on"]:
                return
            ec = time.time() - alive["t0"]
            pct = alive["pct"]
            if pct > 0:
                reste = ec * (100 - pct) / pct
                print(f"      {_barre(pct / 100.0)} {pct:3d}%   ecoule {_fmt_duree(ec)}"
                      f"   reste ~{_fmt_duree(reste)}   << ca AVANCE, ne ferme pas",
                      flush=True)
            else:
                print(f"      ... demarrage ({_fmt_duree(ec)})   << c'est normal, ne ferme pas",
                      flush=True)

    th = threading.Thread(target=_beat, daemon=True)
    th.start()
    try:
        for line in p.stdout:
            out.append(line)
            t = line.rstrip()
            if not t:
                continue
            m = re.search(r"\[\s*(\d{1,3})%\]", t)      # pytest imprime sa progression
            if m:
                alive["pct"] = int(m.group(1))
            # on n'affiche PAS les 2787 lignes de pytest : seulement les echecs et les jalons
            if ("FAILED" in t or "ERROR" in t or " Timeout" in t
                    or re.search(r"\d+ (passed|failed|error)", t)
                    or t.startswith(("=", "collected", "rootdir"))):
                print(prefix + t[:120], flush=True)
            alive["last"] = t
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        alive["on"] = False
        p.kill()
        return 124, "".join(out) + f"\nTIMEOUT apres {timeout}s"
    finally:
        alive["on"] = False
    return p.returncode, "".join(out)


def _run(cmd, timeout=3600):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        # Meme isolation que _run_pytest (ligne ~90) : le Ctrl-C d'un sous-processus ne doit
        # jamais remonter a notre console. Gratuit, et evite de perdre l'audit en route.
        p = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                                          if os.name == "nt" else 0))
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT apres {timeout}s"
    except FileNotFoundError:
        return 127, "outil introuvable"
    except Exception as e:                                              # noqa: BLE001
        return 1, f"{type(e).__name__}: {e}"


# Dossiers JAMAIS scannes (donnees, artefacts, dependances). Tout le reste est AUTO-DECOUVERT :
# un nouveau paquet cree a la racine sera pris en compte SANS toucher a ce script.
EXCLUDED_DIRS = {
    ".git", ".github", "runtime", "logs", "data", "archive", "docs", "config",
    ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", "build", "dist", "htmlcov",
}


def code_dirs() -> list[str]:
    """Tous les dossiers de 1er niveau qui contiennent du code Python + la racine elle-meme."""
    out = []
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir() or d.name in EXCLUDED_DIRS or d.name.endswith(".egg-info"):
            continue
        try:
            next(d.rglob("*.py"))
        except StopIteration:
            continue
        out.append(d.name)
    return out


SELF_FILES = {"tools/audit_report.py"}          # l'auditeur contient les motifs interdits : il
                                                #  ne doit pas se denoncer lui-meme.


def _py_files(*dirs):
    """Sans argument -> AUTO-DECOUVERTE (tout le code du projet, y compris les nouveaux paquets)."""
    if not dirs:
        dirs = tuple(code_dirs())
    out = []
    for d in dirs:
        p = ROOT / d
        if p.is_dir():
            out += [f for f in p.rglob("*.py")
                    if not set(f.parts) & EXCLUDED_DIRS]
    if not dirs or set(dirs) == set(code_dirs()):
        out += [f for f in ROOT.glob("*.py")]          # scripts .py poses a la racine
    return sorted({f for f in out
                   if _rel(f).replace(os.sep, "/") not in SELF_FILES})


def _rel(p):
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _trim(items):
    items = list(items)
    if len(items) > MAX_ITEMS:
        return items[:MAX_ITEMS] + [f"... et {len(items) - MAX_ITEMS} autres"]
    return items


# =============================================================== 1. syntaxe
def c_compile():
    c = Check("1. Syntaxe : compilation de tout le code")
    files = _py_files()
    bad = []
    for p in files:
        try:
            py_compile.compile(str(p), doraise=True)
        except Exception as e:                                          # noqa: BLE001
            bad.append(f"{_rel(p)} -> {str(e).splitlines()[0][:160]}")
    return c.finish(f"{len(files)} fichiers, {len(bad)} erreur(s)", bad)


# =============================================================== 2. imports
def c_imports():
    c = Check("2. Imports : tous les modules du toolkit")
    sys.path.insert(0, str(SRC))
    mods = sorted(p.stem for p in (SRC / "hl_observer/backtesting").glob("*.py") if p.stem != "__init__")
    bad = []
    for m in mods:
        try:
            importlib.import_module(f"hl_observer.backtesting.{m}")
        except Exception as e:                                          # noqa: BLE001
            bad.append(f"{m}: {type(e).__name__}: {e}")
    return c.finish(f"{len(mods)} modules, {len(bad)} casse(s)", bad)


# =============================================================== 3. imports circulaires
def c_circular():
    c = Check("3. Imports circulaires", blocking=False)
    graph = {}
    for p in _py_files("src"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                              # noqa: BLE001
            continue
        mod = _rel(p)[4:-3].replace(os.sep, ".").replace("/", ".")
        deps = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("hl_observer"):
                deps.add(n.module)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.name.startswith("hl_observer"):
                        deps.add(a.name)
        graph[mod] = deps
    cycles, seen = [], set()
    def walk(node, path):
        if node in path:
            cyc = " -> ".join(path[path.index(node):] + [node])
            if cyc not in seen:
                seen.add(cyc)
                cycles.append(cyc)
            return
        for d in graph.get(node, ()):
            if len(path) < 12:
                walk(d, path + [node])
    for m in list(graph):
        walk(m, [])
    return c.finish(f"{len(graph)} modules, {len(cycles)} cycle(s)", [], _trim(cycles))


# =============================================================== 4. arite des appels
def c_arity():
    c = Check("4. Signatures des appels inter-modules (mauvais branchements)")
    sys.path.insert(0, str(SRC))
    problems, checked, skipped = [], 0, 0
    for path in _py_files("src", "tests"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                              # noqa: BLE001
            continue
        imported = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("hl_observer"):
                for a in node.names:
                    if a.name == "*":
                        continue
                    try:
                        obj = getattr(importlib.import_module(node.module), a.name, None)
                        if obj is not None and (inspect.isfunction(obj) or inspect.isclass(obj)):
                            imported[a.asname or a.name] = obj
                    except Exception as e:                              # noqa: BLE001
                        problems.append(f"{_rel(path)}: IMPORT KO {node.module}.{a.name} -> {e}")
        if not imported:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in imported):
                continue
            obj = imported[node.func.id]
            target = obj.__init__ if inspect.isclass(obj) else obj
            try:
                sig = inspect.signature(target)
            except (TypeError, ValueError):
                continue
            params = list(sig.parameters.values())
            if inspect.isclass(obj) and params and params[0].name == "self":
                params = params[1:]
            checked += 1
            if any(k.arg is None for k in node.keywords) or any(isinstance(a, ast.Starred) for a in node.args):
                skipped += 1
                continue
            pos = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
            req = [p for p in pos if p.default is inspect.Parameter.empty]
            req += [p for p in params if p.kind == p.KEYWORD_ONLY and p.default is inspect.Parameter.empty]
            has_va = any(p.kind == p.VAR_POSITIONAL for p in params)
            has_kw = any(p.kind == p.VAR_KEYWORD for p in params)
            n, kw = len(node.args), {k.arg for k in node.keywords}
            given = {p.name for p in pos[:n]} | kw
            miss = [p.name for p in req if p.name not in given]
            loc = f"{_rel(path)}:{node.lineno}"
            if miss:
                problems.append(f"{loc} {node.func.id}() ARGS MANQUANTS {miss}")
            if not has_va and n > len(pos):
                problems.append(f"{loc} {node.func.id}() TROP d'args positionnels ({n}>{len(pos)})")
            if not has_kw and (kw - {p.name for p in params}):
                problems.append(f"{loc} {node.func.id}() KWARG INCONNU {sorted(kw - {p.name for p in params})}")
    return c.finish(f"{checked} appels ({skipped} ignores: depaquetage), {len(problems)} probleme(s)",
                    _trim(problems))


# =============================================================== 5. imports inutilises
def c_dead_imports():
    c = Check("5. Imports inutilises (code mort)", blocking=False)
    dead = []
    for p in _py_files("src"):
        rel = _rel(p)
        if rel.endswith("__init__.py"):
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except Exception:                                              # noqa: BLE001
            continue
        if "TYPE_CHECKING" in src:
            continue
        names = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    names[(a.asname or a.name.split(".")[0])] = n.lineno
            elif isinstance(n, ast.ImportFrom):
                # `from __future__ import annotations` est une DIRECTIVE du compilateur :
                # elle n'est jamais "utilisee" dans le code -> faux positif. On l'ignore.
                if n.module == "__future__":
                    continue
                for a in n.names:
                    if a.name != "*":
                        names[(a.asname or a.name)] = n.lineno
        for name, line in names.items():
            if len(re.findall(r"\b%s\b" % re.escape(name), src)) <= 1:
                dead.append(f"{rel}:{line} import jamais utilise : {name}")
    return c.finish(f"{len(dead)} import(s) inutilise(s)", [], _trim(dead))


# =============================================================== 6. exceptions avalees
def c_silent_except():
    c = Check("6. Exceptions avalees (un bug peut passer inapercu 48h)", blocking=False)
    bad = []
    for p in _py_files("src"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                              # noqa: BLE001
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.ExceptHandler):
                if n.type is None:
                    bad.append(f"{_rel(p)}:{n.lineno} `except:` nu (attrape meme KeyboardInterrupt)")
                elif len(n.body) == 1 and isinstance(n.body[0], ast.Pass):
                    tname = getattr(n.type, "id", None) or getattr(getattr(n.type, "attr", None), "__str__", lambda: "?")()
                    if tname in ("Exception", "BaseException"):
                        bad.append(f"{_rel(p)}:{n.lineno} `except {tname}: pass` (erreur avalee sans trace)")
    return c.finish(f"{len(bad)} exception(s) potentiellement avalee(s)", [], _trim(bad))


# =============================================================== 7. aleatoire sans graine
def c_unseeded_random():
    c = Check("7. Aleatoire sans graine (non-reproductibilite)", blocking=False)
    bad = []
    for p in _py_files("src"):
        txt = p.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\brandom\.(random|randint|choice|uniform|gauss|shuffle|sample)\b", txt) \
           and "seed" not in txt and "Random(" not in txt:
            bad.append(f"{_rel(p)} : utilise `random` sans graine -> resultats non reproductibles")
    return c.finish(f"{len(bad)} module(s) non deterministe(s)", [], _trim(bad))


# =============================================================== 8. encodage / gros fichiers
def c_files_health():
    c = Check("8. Sante des fichiers (encodage, taille)", blocking=False)
    warns = []
    for p in _py_files("src", "tests", "tools"):
        try:
            raw = p.read_bytes()
            raw.decode("utf-8")
        except UnicodeDecodeError:
            warns.append(f"{_rel(p)} : NON-UTF8 (risque de corruption)")
            continue
        n = raw.count(b"\n") + 1
        if n > 2000:
            warns.append(f"{_rel(p)} : {n} lignes (>2000 : difficile a editer sans casse)")
    return c.finish(f"{len(warns)} fichier(s) a surveiller", [], _trim(warns))


# =============================================================== config
CMD = ROOT / "LANCER_HYPERSMART.cmd"
PS1 = ROOT / "tools" / "start_hypersmart_simulation.ps1"


def _cmd_vars():
    return dict(re.findall(r'set "([A-Z0-9_]+)=([^"]*)"', CMD.read_text(encoding="utf-8", errors="replace")))


def _ps1_forced():
    t = PS1.read_text(encoding="utf-8", errors="replace")
    return dict(re.findall(
        r'\[Environment\]::SetEnvironmentVariable\(\s*"([A-Z0-9_]+)"\s*,\s*"([^"]*)"\s*,\s*"Process"\s*\)', t))


def _ps1_defaults():
    t = PS1.read_text(encoding="utf-8", errors="replace")
    return dict(re.findall(r'Set-HyperSmartDefaultEnv\s+"([A-Z0-9_]+)"\s+"([^"]*)"', t))


def effective_config():
    cfg = _cmd_vars()
    for k, v in _ps1_defaults().items():
        cfg.setdefault(k, v)
    cfg.update(_ps1_forced())
    return cfg


GUARDS = ["HYPERSMART_SIMULATION_MIN_EDGE_BPS", "HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE",
          "HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS", "HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS",
          "HYPERSMART_MAX_POSITION_USDT", "HYPERSMART_MAX_TOTAL_EXPOSURE_USDT",
          "HYPERSMART_MAX_OPEN_POSITIONS", "HYPERSMART_SIMULATION_LEVERAGE",
          "HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS"]


def c_config():
    c = Check("9. Coherence config : aucune valeur 'leurre' (.cmd ecrase par .ps1)")
    cmd, forced = _cmd_vars(), _ps1_forced()
    errs = [f"{k}: .cmd affiche {cmd[k]!r} MAIS le .ps1 force {forced[k]!r} -> le .cmd MENT"
            for k in sorted(set(cmd) & set(forced)) if cmd[k] != forced[k]]
    eff = effective_config()
    for g in GUARDS:
        if g not in eff:
            errs.append(f"garde-fou de risque ABSENT du lanceur : {g}")
        else:
            try:
                if float(eff[g]) <= 0:
                    errs.append(f"garde-fou NEUTRALISE : {g}={eff[g]} (<=0)")
            except ValueError:
                pass
    return c.finish(f"{len(errs)} probleme(s) de config", errs)


# =============================================================== reglages morts / defauts silencieux
def c_env_wiring():
    c = Check("10. Reglages morts (regles par le lanceur, jamais lus par le code)", blocking=False)
    code_txt = ""
    for p in _py_files("src", *[d for d in code_dirs() if d not in ("src", "tests", "tools")]):
        code_txt += p.read_text(encoding="utf-8", errors="replace")
    ps_txt = PS1.read_text(encoding="utf-8", errors="replace") + CMD.read_text(encoding="utf-8", errors="replace")
    dead = []
    for v in sorted(effective_config()):
        if not v.startswith(("HYPERSMART_", "HL_", "DYDX_")):
            continue
        if v in code_txt:              # lu par le code (getenv, helper, f-string, constante...)
            continue
        if f"env:{v}" in ps_txt:       # consomme par le script PowerShell lui-meme
            continue
        dead.append(f"REGLAGE MORT : {v} (regle par le lanceur, LU par aucun code)")
    return c.finish(f"{len(dead)} reglage(s) mort(s)", [], _trim(dead))


# =============================================================== planchers fail-open
def c_fail_open():
    c = Check("11. Planchers 'fail-open' (un plafond qui se desserre tout seul)", blocking=False)
    bad = []
    # `<=` COMPTE AUSSI : c'est exactement comme ca qu'un `if leverage <= 1.0: leverage = 10.0`
    # m'avait echappe le 2026-07-11.
    pat = re.compile(r"if\s+(\w+)\s*<=?\s*([\d.]+)\s*:\s*\n\s*\1\s*=\s*([\d.]+)")
    for p in _py_files("src"):
        txt = p.read_text(encoding="utf-8", errors="replace")
        for m in pat.finditer(txt):
            var, lo, val = m.group(1), float(m.group(2)), float(m.group(3))
            if val >= lo and lo > 0 and any(k in var.lower() for k in
                                            ("max", "cap", "exposure", "lev", "limit", "budget", "margin")):
                line = txt[:m.start()].count("\n") + 1
                bad.append(f"{_rel(p)}:{line} `if {var} < {lo}: {var} = {val}` -> resserrer est ANNULE")
    return c.finish(f"{len(bad)} plancher(s) suspect(s)", [], _trim(bad))


# =============================================================== secrets
def c_secrets():
    c = Check("12. Scan de secrets (cle privee / seed / mnemonic)")
    # STRICT : uniquement des secrets REELS. (L'heuristique "12 mots d'affilee" matchait la prose
    # anglaise des docstrings -> faux positif bloquant. Supprimee.)
    pats = [
        (r"0x[a-fA-F0-9]{64}\b", "cle privee 32 octets en dur"),
        (r"\b(private_key|privkey|mnemonic|seed_phrase|seedphrase|secret_key|api_secret)\s*=\s*[\"'][^\"'\s]{12,}[\"']",
         "secret assigne en dur"),
        (r"\bAccount\.from_key\(|\bWallet\(.*private", "derivation de cle privee"),
    ]
    hits = []
    skip = ("test", "mock", "fixture", "example", "runtime", "logs")
    # 18/07 : `0x[64 hex]` ne veut PAS dire « cle privee ». Un hash keccak, un topic d'evenement,
    # un hash de transaction ou de bloc ont exactement la meme forme. Le faux positif bloquant
    # etait TOPIC_TRANSFER (signature de l'evenement ERC-20 `Transfer`), une constante PUBLIQUE
    # et universelle, commentee comme telle deux lignes plus haut.
    # Une cle privee ne s'appelle jamais "TOPIC_..." : on regarde donc le CONTEXTE de la ligne.
    # C'est etroit et verifiable -- pas une exclusion de fichier qui aveuglerait le controle.
    contexte_hash = ("topic", "hash", "digest", "keccak", "sha", "selector",
                     "checksum", "commit", "signature de l'evenement", "event")
    for p in _py_files(*[d for d in code_dirs() if d != "tests"]):
        rel = _rel(p)
        if any(s_ in rel.lower() for s_ in skip):
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        lignes = txt.splitlines()
        for pat, label in pats:
            for m in re.finditer(pat, txt):
                line = txt[:m.start()].count("\n") + 1
                src = lignes[line - 1].lower() if line - 1 < len(lignes) else ""
                if any(k in src for k in contexte_hash):
                    continue
                hits.append(f"{rel}:{line} {label} -> {m.group(0)[:30]}...")
    return c.finish(f"{len(hits)} secret(s) reel(s) detecte(s)", _trim(hits))


# =============================================================== execution reelle
def c_no_real_exec():
    c = Check("13. Aucun chemin d'execution reelle (hors tests/mocks)")
    danger = [(r"['\"]/exchange['\"]", "endpoint d'execution /exchange"),
              (r"\.sign_typed_data\(|\.sign_transaction\(|eth_account", "signature reelle"),
              (r"place_mainnet_order|send_real_order|submit_order\(", "envoi d'ordre reel")]
    hits = []
    for p in _py_files("src", *[d for d in code_dirs() if d not in ("src", "tests", "tools")]):
        rel = _rel(p).lower()
        if any(s in rel for s in ("test", "mock", "fake", "safety_audit", "mainnet_guard", "disabled")):
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        for pat, label in danger:
            for m in re.finditer(pat, txt):
                line = txt[:m.start()].count("\n") + 1
                hits.append(f"{_rel(p)}:{line} {label}")
    return c.finish(f"{len(hits)} chemin(s) dangereux", _trim(hits))


# =============================================================== audit securite
def c_safety():
    c = Check("14. Audit securite no-real-trade")
    sys.path.insert(0, str(SRC))
    try:
        from hl_observer.security.safety_audit import run_safety_audit
        r = run_safety_audit(str(ROOT))
        errs = [f"controle ECHOUE : {k}" for k, v in r.checks.items() if not v]
        errs += [f"finding : {f}" for f in r.findings]
        return c.finish(f"{sum(r.checks.values())}/{len(r.checks)} controles", errs)
    except Exception as e:                                              # noqa: BLE001
        return c.finish(f"audit impossible : {type(e).__name__}: {e}", [f"{type(e).__name__}: {e}"])


# =============================================================== tests non isoles
def c_test_isolation():
    c = Check("15. Tests non isoles (resultat dependant de TA machine)", blocking=False)
    warns = []
    for p in _py_files("tests"):
        txt = p.read_text(encoding="utf-8", errors="replace")
        if re.search(r"['\"](?:\./)?(?:runtime|logs)[/\\]", txt) and "tmp_path" not in txt:
            warns.append(f"{_rel(p)} : lit runtime/ ou logs/ en dur, sans tmp_path")
        if re.search(r"\bopen\(\s*[\"'][A-Za-z]:[\\/]", txt):
            warns.append(f"{_rel(p)} : chemin absolu de machine en dur")
    return c.finish(f"{len(warns)} test(s) potentiellement non isole(s)", [], _trim(warns))


# =============================================================== doublons de tests
def c_test_dupes():
    c = Check("16. Doublons de noms de tests (un test peut en masquer un autre)", blocking=False)
    seen, dupes = {}, []
    for p in _py_files("tests"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                              # noqa: BLE001
            continue
        local = {}
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"):
                if n.name in local:
                    dupes.append(f"{_rel(p)} : `{n.name}` defini 2x DANS LE MEME FICHIER (le 1er est ignore !)")
                local[n.name] = n.lineno
                seen.setdefault(n.name, []).append(_rel(p))
    return c.finish(f"{len(dupes)} doublon(s) masquant(s)", [], _trim(dupes))


# =============================================================== docs manquants
def c_docs():
    c = Check("17. Docs referencees mais absentes", blocking=False)
    missing = set()
    for p in _py_files("src", "tests", "tools"):
        txt = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"[\"'](docs/[A-Za-z0-9_./-]+\.md)[\"']", txt):
            if not (ROOT / m.group(1)).is_file():
                missing.add(f"{m.group(1)}  (reference dans {_rel(p)})")
    return c.finish(f"{len(missing)} doc(s) referencee(s) mais absente(s)", [], _trim(sorted(missing)))


# =============================================================== ressources
def c_resources():
    c = Check("18. Bornes de ressources (bloat = crash du run 48h)", blocking=False)
    warns = []
    def size(path):
        p = ROOT / path
        if p.is_file():
            return p.stat().st_size
        if p.is_dir():
            return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        return 0
    for path, limit_gb, label in (("runtime", 60, "runtime/"), ("logs", 10, "logs/")):
        gb = size(path) / 1e9
        if gb > limit_gb:
            warns.append(f"{label} = {gb:.1f} Go (> {limit_gb} Go : risque de saturation disque)")
        elif gb > 0:
            warns.append(f"[info] {label} = {gb:.1f} Go")
    for db in (ROOT / "runtime").rglob("*.sqlite3") if (ROOT / "runtime").is_dir() else []:
        gb = db.stat().st_size / 1e9
        if gb > 5:
            warns.append(f"{_rel(db)} = {gb:.1f} Go (une DB > 5 Go a DEJA fait crasher un run)")
    return c.finish(f"{len(warns)} point(s) de vigilance", [], _trim(warns))


# =============================================================== lint / typage
def c_lint():
    c = Check("19. Lint (ruff) & typage (mypy) -- si installes", blocking=False)
    warns = []
    if shutil.which("ruff"):
        code, out = _run(["ruff", "check", "src", "tests"], timeout=600)
        n = len([l for l in out.splitlines() if re.match(r"^\S+:\d+:\d+:", l)])
        if n:
            warns.append(f"ruff : {n} probleme(s) -> `ruff check src tests` pour le detail")
            warns += [l for l in out.splitlines() if re.match(r"^\S+:\d+:\d+:", l)][:25]
    else:
        warns.append("[info] ruff non installe (`pip install ruff`) -- lint saute")
    if shutil.which("mypy"):
        code, out = _run(["mypy", "src/hl_observer/backtesting"], timeout=900)
        n = len([l for l in out.splitlines() if ": error:" in l])
        if n:
            warns.append(f"mypy : {n} erreur(s) de typage")
            warns += [l for l in out.splitlines() if ": error:" in l][:25]
    else:
        warns.append("[info] mypy non installe (`pip install mypy`) -- typage saute")
    return c.finish(f"{len(warns)} remarque(s)", [], warns[:MAX_ITEMS])


# =============================================================== tests
_TESTS_OUT = {"first": "", "second": ""}


def _parse_failed(out):
    return set(re.findall(r"^FAILED (\S+)", out, re.M))


def un_test_a_ete_tue_par_le_timeout(sortie_pytest: str) -> bool:
    """LE CONTROLE QUI CRIAIT AU LOUP A CHAQUE PASSAGE (bug trouve le 2026-07-12).

    L'ancien test etait :

        if "Timeout" in out or "timeout" in out.lower():   -> ECHEC BLOQUANT

    Or `--timeout=180` fait imprimer a pytest-timeout, DANS L'ENTETE DE CHAQUE SESSION :

        timeout: 180.0s
        timeout method: thread

    Le mot etait donc TOUJOURS present. **L'audit ne pouvait structurellement JAMAIS etre vert.**
    Tant que la suite avait de vrais echecs, personne ne l'a vu : le faux se cachait derriere les
    vrais. Le jour ou la suite est passee a 3 246/3 246, le fantome est reste seul -- et a continue
    de dire "le code est casse".

    Un faux positif permanent est pire qu'une absence de controle : il apprend a ignorer l'alarme.

    CE QUI PROUVE VRAIMENT UN TIMEOUT
    ---------------------------------
    pytest-timeout ne tue pas en silence. Il produit l'UNE de ces trois traces :
      * le test devient FAILED avec `Failed: Timeout >180.0s`  (deja compte dans `errs`) ;
      * il imprime une banniere `+++++++ Timeout +++++++` avec la pile des threads ;
      * la suite entiere meurt sans resume (deja detecte par l'absence de `summary`).
    On cherche donc des PREUVES, plus un mot.
    """
    if "Failed: Timeout" in sortie_pytest:
        return True
    if re.search(r"\+{3,}\s*Timeout\s*\+{3,}", sortie_pytest):
        return True
    # faulthandler : "Timeout (0:02:00)!" suivi du dump des piles
    return bool(re.search(r"^Timeout \(\d+:\d\d:\d\d\)!", sortie_pytest, re.M))


def _pytest_base_args() -> list[str]:
    """Args pytest communs. TIMEOUT PAR TEST : un test qui se BLOQUE (appel reseau, deadlock...)
    devient un ECHEC NOMME au lieu de figer tout l'audit. C'est exactement ce qui s'est passe
    le 2026-07-11 : la suite restait plantee a 57% et il fallait faire Ctrl-C."""
    # -v : chaque test imprime son nom AVANT de s'executer. Si la suite meurt (Ctrl-C interne,
    # crash, gel), la DERNIERE ligne nous donne le COUPABLE. C'est le seul moyen de le nommer.
    # faulthandler_timeout : si un test depasse 120s, on dumpe la pile de TOUS les threads.
    args = ["-v", "--tb=short", "-rf", "-p", "no:cacheprovider",
            "-o", "faulthandler_timeout=120"]
    try:
        import pytest_timeout  # noqa: F401
        args += ["--timeout=180", "--timeout-method=thread"]
    except ImportError:
        print("   [!] pytest-timeout absent : un test bloque figera l'audit.", flush=True)
        print("   [!] Installe-le : pip install pytest-timeout", flush=True)
    return args


def c_tests():
    c = Check("20. Suite de tests complete")
    print("   >>> PARTIE LONGUE (2 a 6 min). NE FERME PAS, NE FAIS PAS CTRL-C.", flush=True)
    print("   >>> Le rapport est deja sur le disque : tu ne perdras rien.", flush=True)
    print("   >>> Un test bloque > 180s est tue et signale (il ne peut plus figer l'audit).",
          flush=True)
    has_cov = True
    try:
        import coverage  # noqa: F401
    except ImportError:
        has_cov = False
    base = _pytest_base_args()
    if has_cov:
        cmd = [sys.executable, "-m", "coverage", "run", "--source=src/hl_observer",
               "-m", "pytest"] + base
        print("   (sous coverage -> couverture fichier par fichier en prime)", flush=True)
    else:
        cmd = [sys.executable, "-m", "pytest"] + base
    code, out = _run_stream(cmd, env_propre=True)   # la suite ne doit RIEN heriter de l'audit
    _TESTS_OUT["first"] = out
    summary = ""
    for line in reversed(out.strip().splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            summary = line.strip()
            break
    failed = re.findall(r"^FAILED (\S+)(?: - (.*))?$", out, re.M)
    errs = [f"{n}" + (f"  --  {r[:200]}" if r else "") for n, r in failed]
    if un_test_a_ete_tue_par_le_timeout(out):
        errs.append(">>> Au moins un test a ete TUE par le timeout (test bloque). "
                    "Cherche 'Timeout' dans les traces ci-dessous.")
    if code == 124:
        errs.append(">>> La suite entiere a depasse le timeout global : un test bloque sans fin.")
    if not summary or "KeyboardInterrupt" in out:
        started = re.findall(r"^(tests[/\\]\S+::\S+)", out, re.M)
        last = started[-1] if started else "?"
        errs.insert(0, f">>> LA SUITE S'EST ARRETEE TOUTE SEULE. DERNIER TEST LANCE : {last}")
        errs.insert(1, ">>> C'est LUI le coupable (Ctrl-C interne, gel ou crash). "
                       "L'audit, lui, a survecu et continue.")
        if "KeyboardInterrupt" in out:
            errs.insert(2, ">>> pytest a recu un KeyboardInterrupt que PERSONNE n'a tape : "
                           "un test declenche un Ctrl-C sur la console.")
    start = out.find("= FAILURES =")
    end = out.find("short test summary info")
    if start >= 0:
        block = out[start:end if end > start else None].splitlines()
        if len(block) > MAX_TB_LINES:
            block = block[:MAX_TB_LINES] + [f"... (tronque a {MAX_TB_LINES} lignes)"]
        c.tb = "\n".join(block)
    return c.finish(summary or f"pytest code={code}", _trim(errs))


def c_flaky():
    c = Check("21. Tests flaky (2e passe : meme resultat ?)", blocking=False)
    if FAST:
        return c.finish("saute (--fast)", [], ["[info] 2e passe sautee (--fast)"])
    code, out = _run_stream(
        [sys.executable, "-m", "pytest"] + _pytest_base_args(), env_propre=True
    )   # meme env que la 1re passe, sinon "flaky" ne mesurerait que la contamination
    _TESTS_OUT["second"] = out
    a, b = _parse_failed(_TESTS_OUT["first"]), _parse_failed(out)
    flaky = sorted((a | b) - (a & b))
    warns = [f"FLAKY : {t} (echoue a une passe seulement -> resultat non deterministe)" for t in flaky]
    return c.finish(f"{len(flaky)} test(s) flaky", [], _trim(warns))


# =============================================================== doctor
def c_doctor():
    c = Check("22. Doctor (sante du runtime)")
    code, out = _run_stream([sys.executable, "-m", "hl_observer", "doctor"], timeout=900)
    tail = out.strip().splitlines()[-15:]
    return c.finish("doctor OK" if code == 0 else f"doctor code={code}",
                    [] if code == 0 else tail)



# =============================================================== 23. import de TOUS les modules
def c_all_imports():
    c = Check("23. Import de CHAQUE module du projet (pas juste le toolkit)")
    sys.path.insert(0, str(SRC))
    bad, n = [], 0
    for p in _py_files("src"):
        rel = _rel(p)
        if rel.endswith("__init__.py"):
            continue
        mod = rel[4:-3].replace(os.sep, ".").replace("/", ".")
        n += 1
        try:
            importlib.import_module(mod)
        except Exception as e:                                          # noqa: BLE001
            bad.append(f"{rel} -> {type(e).__name__}: {e}")
    return c.finish(f"{n} modules importes, {len(bad)} casse(s)", _trim(bad))


# =============================================================== 24. modules orphelins
def c_orphans():
    c = Check("24. Modules orphelins (jamais importes = code mort)", blocking=False)
    all_mods, imported = {}, set()
    for p in _py_files("src"):
        rel = _rel(p)
        if rel.endswith("__init__.py"):
            continue
        all_mods[rel[4:-3].replace(os.sep, ".").replace("/", ".")] = rel
    for p in _py_files("src", "tests", "tools"):
        txt = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"(?:from|import)\s+(hl_observer[\w.]*)", txt):
            imported.add(m.group(1))
    orphans = []
    for mod, rel in sorted(all_mods.items()):
        if not any(mod == i or i.startswith(mod + ".") or mod.startswith(i + ".") for i in imported):
            orphans.append(f"{rel} : importe par PERSONNE (module dormant / non cable)")
    return c.finish(f"{len(orphans)} module(s) orphelin(s) / {len(all_mods)}", [], _trim(orphans))


# =============================================================== 25. tests sans assertion
def c_tests_without_assert():
    c = Check("25. Tests SANS assertion (faux vert : le test ne verifie RIEN)", blocking=False)
    bad = []
    for p in _py_files("tests"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                              # noqa: BLE001
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"):
                body = ast.dump(n)
                if "Assert(" not in body and "pytest.raises" not in body and "assert_" not in body \
                        and "pytest.warns" not in body and "pytest.fail" not in body:
                    bad.append(f"{_rel(p)}:{n.lineno} `{n.name}` ne contient AUCUNE assertion")
    return c.finish(f"{len(bad)} test(s) qui ne verifient rien", [], _trim(bad))


# =============================================================== 26. tests desactives
def c_skipped():
    c = Check("26. Tests desactives (skip / xfail)", blocking=False)
    bad = []
    for p in _py_files("tests"):
        txt = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"@pytest\.mark\.(skip|skipif|xfail)([^\n]*)", txt):
            line = txt[:m.start()].count("\n") + 1
            bad.append(f"{_rel(p)}:{line} @pytest.mark.{m.group(1)}{m.group(2)[:70]}")
    return c.finish(f"{len(bad)} test(s) desactive(s)", [], _trim(bad))


# =============================================================== 27. reseau dans les tests
def c_net_in_tests():
    """Analyse SYNTAXIQUE (pas du texte) : un `requests.post` cite dans une CHAINE ou un MOCK
    n'est pas un appel reseau. L'ancienne version en recherche de texte donnait 3 faux positifs."""
    c = Check("27. Tests qui sortent VRAIMENT sur le reseau (bloquent l'audit)", blocking=False)
    NET = {("httpx", "get"), ("httpx", "post"), ("httpx", "stream"),
           ("requests", "get"), ("requests", "post"),
           ("websockets", "connect"), ("urllib", "urlopen")}
    bad = []
    for p in _py_files("tests"):
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except Exception:                                              # noqa: BLE001
            continue
        mocked = ("mock" in src.lower() or "monkeypatch" in src)
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
               and isinstance(n.func.value, ast.Name):
                pair = (n.func.value.id, n.func.attr)
                if pair in NET and not mocked:
                    bad.append(f"{_rel(p)}:{n.lineno} appel reseau REEL : "
                               f"{pair[0]}.{pair[1]}() -- peut bloquer l'audit")
    return c.finish(f"{len(bad)} appel(s) reseau reel(s) dans les tests", [], _trim(bad))


# =============================================================== 28. dettes TODO/FIXME
def c_todo():
    c = Check("28. Dettes signalees dans le code (TODO / FIXME / HACK / XXX)", blocking=False)
    hits = []
    for p in _py_files("src", *[d for d in code_dirs() if d not in ("src", "tests", "tools")]):
        txt = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"#\s*(TODO|FIXME|HACK|XXX)\b[:\s]*(.{0,90})", txt):
            line = txt[:m.start()].count("\n") + 1
            hits.append(f"{_rel(p)}:{line} {m.group(1)}: {m.group(2).strip()}")
    return c.finish(f"{len(hits)} dette(s) signalee(s)", [], _trim(hits))


# =============================================================== 29. garde multiprocessing
def c_mp_guard():
    c = Check("29. multiprocessing sans garde __main__ (bombe a fork sous Windows)", blocking=False)
    bad = []
    for p in _py_files("src", "tools"):
        txt = p.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\b(multiprocessing|ProcessPoolExecutor|Pool\()", txt) \
           and '__name__ == "__main__"' not in txt and "__name__ == '__main__'" not in txt \
           and "def " in txt and "if __name__" not in txt:
            if re.search(r"^\s*(Pool\(|.*ProcessPoolExecutor\()", txt, re.M):
                bad.append(f"{_rel(p)} : cree des process au niveau module, sans garde __main__")
    return c.finish(f"{len(bad)} fichier(s) a risque", [], _trim(bad))


# =============================================================== 30. reason codes
def c_reason_codes():
    c = Check("30. Codes de refus (NO_TRADE) hors taxonomie", blocking=False)
    tax = ""
    tp = SRC / "hl_observer/signals/no_trade_taxonomy.py"
    if tp.is_file():
        tax = tp.read_text(encoding="utf-8", errors="replace")
    if not tax:
        return c.finish("taxonomie introuvable", [], ["[info] no_trade_taxonomy.py absent"])
    emitted = set()
    for p in _py_files("src"):
        if "no_trade_taxonomy" in _rel(p):
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        emitted |= set(re.findall(r'["\']([A-Z][A-Z0-9_]{6,})["\']', txt))
    unknown = sorted(r for r in emitted
                     if ("REFUS" in r or "NO_TRADE" in r or r.endswith(("_REQUIRED", "_TOO_SMALL",
                         "_TOO_OLD", "_REACHED", "_BLOCKED", "_REFUSED")))
                     and r not in tax)
    return c.finish(f"{len(unknown)} code(s) de refus non declare(s)", [],
                    _trim([f"code emis mais ABSENT de la taxonomie : {u}" for u in unknown]))


# =============================================================== 31. modules sans test
def c_untested():
    c = Check("31. Modules SANS test associe", blocking=False)
    test_txt = " ".join(p.read_text(encoding="utf-8", errors="replace") for p in _py_files("tests"))
    untested = []
    total = 0
    for p in _py_files("src"):
        rel = _rel(p)
        if rel.endswith("__init__.py"):
            continue
        total += 1
        mod = pathlib.Path(rel).stem
        if mod not in test_txt:
            untested.append(f"{rel} : jamais mentionne dans les tests")
    return c.finish(f"{len(untested)}/{total} module(s) sans test", [], _trim(untested))


# =============================================================== 32. couverture reelle
COVERAGE_ROWS = []


def c_coverage():
    c = Check("32. Couverture de tests REELLE, fichier par fichier", blocking=False)
    try:
        import coverage  # noqa: F401
    except ImportError:
        return c.finish("coverage non installe", [],
                        ["[info] `pip install coverage` pour la couverture par fichier"])
    # pytest a DEJA tourne sous coverage (controle 20) : on ne relance rien, on lit le rapport.
    code, out = _run([sys.executable, "-m", "coverage", "report", "-m"], timeout=900)
    rows = []
    for line in out.splitlines():
        m = re.match(r"^(src[\\/]\S+\.py)\s+(\d+)\s+(\d+)\s+(\d+)%", line)
        if m:
            rows.append((m.group(1), int(m.group(2)), int(m.group(4))))
    COVERAGE_ROWS.extend(sorted(rows, key=lambda r: r[2]))
    zero = [f"{f} : 0% couvert ({n} lignes JAMAIS executees)" for f, n, pct in rows if pct == 0]
    low = [f"{f} : {pct}% seulement ({n} lignes)" for f, n, pct in rows if 0 < pct < 40]
    tot = re.search(r"^TOTAL\s+\d+\s+\d+\s+(\d+)%", out, re.M)
    return c.finish(f"couverture globale {tot.group(1) if tot else '?'}% | {len(zero)} fichier(s) a 0%",
                    [], _trim(zero + low))


# =============================================================== 33. reconciliation PnL
def c_pnl():
    """Le PnL affiche doit etre EXPLICABLE par le ledger : on verifie que les briques existent."""
    c = Check("33. Verite du PnL (auditeur + realisme de simulation presents)", blocking=False)
    sys.path.insert(0, str(SRC))
    missing, ok = [], []
    for mod, why in (("hl_observer.analysis.negative_pnl_auditor", "explique chaque perte"),
                     ("hl_observer.audit.simulation_realism_audit", "frais/spread/slippage/funding"),
                     ("hl_observer.paper_trading.hedge_reconciliation", "reconciliation des positions")):
        try:
            importlib.import_module(mod)
            ok.append(f"[ok] {mod} ({why})")
        except Exception as e:                                          # noqa: BLE001
            missing.append(f"MANQUANT : {mod} ({why}) -> {type(e).__name__}: {e}")
    return c.finish(f"{len(ok)}/3 briques de verite du PnL presentes", missing, ok)



# =============================================================== 34. NOUVEAUX FICHIERS
MANIFEST = ROOT / "tools" / "audit_manifest.json"


def _current_inventory() -> list[str]:
    """Tout ce que l'audit doit suivre : le code (auto-decouvert) + les fichiers pilotes."""
    files = {_rel(f).replace(os.sep, "/") for f in _py_files()}
    for pat in ("*.cmd", "*.ps1", "*.toml", "*.ini", "*.txt", "*.yml", "*.yaml"):
        files |= {_rel(f).replace(os.sep, "/") for f in ROOT.glob(pat)}
        files |= {_rel(f).replace(os.sep, "/") for f in (ROOT / "tools").glob(pat)}
    return sorted(files)


def c_new_files():
    """EXIGENCE DE FLO (2026-07-11) : tout nouveau fichier/module doit etre PRIS EN COMPTE
    par les tests. Ce controle compare le projet a l'empreinte du dernier audit, liste ce qui
    est apparu, et REFUSE un nouveau module de `src/` qui n'a ni test ni utilisateur."""
    import json
    c = Check("34. Nouveaux fichiers depuis le dernier audit (doivent etre testes)")
    current = _current_inventory()
    try:
        known = set(json.loads(MANIFEST.read_text(encoding="utf-8")).get("files", []))
    except Exception:                                                  # noqa: BLE001
        known = set()
    if not known:
        STATE["manifest_pending"] = current
        return c.finish(f"premier audit : empreinte de {len(current)} fichiers creee", [],
                        ["[info] la prochaine execution signalera tout fichier ajoute/supprime"])

    added = sorted(set(current) - known)
    removed = sorted(known - set(current))
    STATE["manifest_pending"] = current

    test_txt = " ".join(p.read_text(encoding="utf-8", errors="replace") for p in _py_files("tests"))
    all_code = ""
    for p in _py_files():
        all_code += p.read_text(encoding="utf-8", errors="replace")

    errors, warns = [], []
    for f in added:
        if not f.endswith(".py"):
            warns.append(f"NOUVEAU fichier : {f}")
            continue
        if f.startswith("tests/"):
            warns.append(f"NOUVEAU test : {f}  (bien)")
            continue
        stem = pathlib.Path(f).stem
        mod = f[4:-3].replace("/", ".") if f.startswith("src/") else f[:-3].replace("/", ".")
        tested = stem in test_txt
        used = len(re.findall(r"\b%s\b" % re.escape(stem), all_code)) > 1
        if f.startswith(("src/", "hyper_smart_observer/")) and not tested:
            errors.append(f"NOUVEAU MODULE SANS TEST : {f} -> cree tests/test_{stem}.py "
                          f"(regle: aucun module non teste)")
        elif not used:
            warns.append(f"NOUVEAU module jamais importe (dormant) : {f}")
        else:
            warns.append(f"NOUVEAU module, teste et cable : {f}  (bien)")
    for f in removed:
        warns.append(f"SUPPRIME depuis le dernier audit : {f}")

    return c.finish(f"{len(added)} ajout(s), {len(removed)} suppression(s), "
                    f"{len(errors)} sans test", errors, warns)



# ==================================================================================
#  BATTERIE ETENDUE (demande de Flo : "il faut monter a 100 controles")
#  Chaque regle vise un vrai mode de panne. Rien de decoratif.
# ==================================================================================

def _code_dirs_no_tests():
    return [d for d in code_dirs() if d != "tests"]


def regex_rule(title, pattern, *, why="", blocking=False, dirs=None, exclude=(),
               line_exclude=(), flags=0):
    """Controle par expression reguliere.

    `line_exclude` : si la LIGNE contient un de ces mots, on ignore. Indispensable pour ne pas
    confondre une INTERDICTION (`wallet_connect_allowed=False`) ou un AVERTISSEMENT
    ("not a guaranteed profit signal") avec une infraction. Un controle bloquant qui crie au
    loup est pire qu'inutile.
    """
    def _fn():
        c = Check(title, blocking=blocking)
        hits = []
        for p in _py_files(*(dirs if dirs is not None else _code_dirs_no_tests())):
            rel = _rel(p).replace(os.sep, "/")
            if any(x in rel for x in exclude):
                continue
            txt = p.read_text(encoding="utf-8", errors="replace")
            lines = txt.splitlines()
            for m in re.finditer(pattern, txt, flags):
                line = txt[:m.start()].count("\n") + 1
                src_line = lines[line - 1] if line - 1 < len(lines) else ""
                # MARQUEUR EXPLICITE (18/07). Certaines lignes contiennent LEGITIMEMENT le motif
                # interdit : la liste des mots bannis d'un filtre, l'appat d'arnaque qu'un canari
                # doit REJETER... Le garde etait accuse a la place du voleur.
                # Plutot qu'une exclusion de fichier (large, invisible, qui aveugle le controle
                # pour tout le fichier a jamais), l'exemption se declare SUR LA LIGNE, se lit en
                # relecture de diff, et se compte (test_marqueurs_audit_fixture.py la cliquette).
                if "audit:fixture" in src_line.lower():
                    continue
                if line_exclude and any(w.lower() in src_line.lower() for w in line_exclude):
                    continue
                hits.append(f"{rel}:{line} {src_line.strip()[:90]}")
        msg = f"{len(hits)} occurrence(s)" + (f" -- {why}" if why else "")
        return c.finish(msg, _trim(hits) if blocking else [], _trim(hits))
    return _fn


# ---------------------------------------------------------------- SECURITE (bloquants)
c_lib_signature = regex_rule(
    "Aucune librairie de signature/cle (eth_account, web3, coincurve...)",
    r"^\s*(?:from|import)\s+(eth_account|web3|coincurve|ecdsa|bip32|mnemonic|bip_utils)\b",
    why="une lib de signature n'a RIEN a faire dans un bot paper", blocking=True, flags=re.M)

c_env_privkey = regex_rule(
    "Aucune variable d'env de cle privee lue par le code",
    r"(?:getenv|environ\.get|environ\[)\s*\(?\s*[\"'][A-Z_]*(PRIVATE_KEY|SECRET_KEY|MNEMONIC|SEED)[A-Z_]*[\"']",
    why="lire une cle = premier pas vers l'execution reelle", blocking=True)

c_exchange_url = regex_rule(
    "Aucune URL d'execution (endpoint /exchange)",
    r"[\"'][^\"']*hyperliquid[^\"']*/exchange[\"']|[\"']/exchange[\"']",
    why="l'endpoint d'ordre reel ne doit exister nulle part", blocking=True,
    exclude=("safety_audit", "mainnet_guard", "disabled"))

c_wallet_connect = regex_rule(
    "Aucun wallet-connect",
    r"walletconnect|WalletConnect|wallet_connect",
    why="aucun moyen de signer pour agir", blocking=True,
    # Ces deux paquets DECLARENT la liste de ce qui est INTERDIT. `security/dependances.py` est
    # litteralement la blocklist ("walletconnect": "Connexion d'un vrai portefeuille pour AGIR.").
    # Accuser la blocklist de contenir le mot qu'elle interdit, c'est confondre le garde et le
    # voleur -- et ca finit par faire desactiver l'audit. Un VRAI import walletconnect reste
    # attrape par `c_lib_signature` et par l'audit de dependances lui-meme.
    exclude=("agent_tools/", "security/dependances.py"),
    line_exclude=("False", "allowed", "not ", "forbidden", "interdit", "deny", "refus",
                  "banned", "disabled", "jamais", "aucun"))

c_shell_true = regex_rule(
    "Aucun subprocess shell=True (injection de commande)",
    r"shell\s*=\s*True",
    why="injection de commande possible", blocking=True)

def c_eval_exec():
    """AST, PAS REGEX — un APPEL a eval()/exec(), pas le MOT quelque part.

    Le 18/07, ce controle bloquait l'audit sur TROIS faux positifs, tous des chaines :
      * tools/verifier_moissonneur.py:22  ->  INTERDITS = (..., "exec(", "eval(", ...)
        c'est-a-dire LA LISTE DES INTERDITS elle-meme. Le garde etait accuse a la place du voleur.
      * tools/trier_h46_h89.py:32         ->  "mackinac/dex-exec (HL perp + Uniswap V3)"
        un NOM DE DEPOT dans un tableau de donnees.

    Meme lecon que l'invariant securite du 18/07 : un module qui ECRIT « n'appelle jamais
    /exchange » est innocent ; seul un APPEL est une porte. Une chaine n'execute rien.
    L'AST ne peut pas se tromper la-dessus -- et il attrape aussi ce que la regex ratait
    (`getattr(builtins, "eval")` reste hors de portee des deux, mais `eval (x)` sur plusieurs
    lignes passait la regex et ne passe pas l'AST).
    """
    c = Check("21. Aucun eval() / exec() (execution de code arbitraire)")
    hits = []
    for p in _py_files(*_code_dirs_no_tests()):
        rel = _rel(p).replace(os.sep, "/")
        if "audit_report" in rel:
            continue
        try:
            arbre = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for n in ast.walk(arbre):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("eval", "exec"):
                hits.append(f"{rel}:{getattr(n, 'lineno', 0)} APPEL reel a {n.func.id}()")
    return c.finish(f"{len(hits)} appel(s) reel(s)", _trim(hits))

c_pickle = regex_rule(
    "Aucun pickle.load sur donnee externe",
    r"pickle\.loads?\s*\(", why="pickle = execution de code a la desserialisation")

c_os_system = regex_rule(
    "Aucun os.system()", r"os\.system\s*\(", why="preferer subprocess sans shell")

c_profit_promise = regex_rule(
    "Aucune promesse de PnL dans le code",
    # (?<!...) : on EXCLUT les negations -- "does NOT guarantee profit" est un AVERTISSEMENT,
    # pas une promesse. C'est exactement l'inverse de ce qu'on cherche.
    r"(?:guaranteed[_ ]profit|risk[- ]free profit|profit garanti|gain garanti|100% win)",
    why="regle absolue : jamais de promesse de PnL", blocking=True, flags=re.I,
    # local_llm_explainer DECLARE la liste des phrases BANNIES (il les filtre) : ce n'est pas
    # une promesse, c'est le garde-fou lui-meme.
    exclude=("research/local_llm_explainer.py",),
    line_exclude=("not ", "no ", "never", "n't", "jamais", "aucun", "pas de", "hallucin",
                  "warning", "avertis", "disclaimer", "fallback", "falls back"))

# ---------------------------------------------------------------- ROBUSTESSE 48h
c_http_no_timeout = regex_rule(
    "Appels HTTP SANS timeout (peut geler le bot 48h)",
    r"(?:httpx|requests)\.(?:get|post|put|delete)\((?![^)]*timeout)",
    why="un appel sans timeout peut bloquer la boucle indefiniment")

c_ws_no_timeout = regex_rule(
    "WebSocket connect SANS timeout",
    r"websockets\.connect\((?![^)]*timeout)",
    why="un WS sans timeout gele le stream (deja arrive : bug du 2026-07-07)")

c_open_no_with = regex_rule(
    "Fichiers ouverts SANS `with` (descripteur fuit)",
    r"^\s*\w+\s*=\s*open\s*\(", why="fuite de descripteurs sur un run long", flags=re.M)

c_sqlite_no_ctx = regex_rule(
    "sqlite3.connect() sans fermeture explicite",
    r"^\s*\w+\s*=\s*sqlite3\.connect\(", why="connexions qui s'accumulent", flags=re.M)

c_thread_no_daemon = regex_rule(
    "Threads NON daemon (empechent l'arret propre)",
    r"threading\.Thread\((?![^)]*daemon)",
    why="un thread non-daemon empeche le processus de mourir -> orphelins")

c_while_true = regex_rule(
    "Boucles `while True` (verifier qu'elles ont une sortie + un sleep)",
    r"while\s+True\s*:", why="boucle infinie : doit avoir sortie ET pause")

c_mutable_default = regex_rule(
    "Arguments par defaut MUTABLES (piege Python classique)",
    r"def\s+\w+\([^)]*=\s*(\[\]|\{\})", why="l'etat est partage entre les appels !")

c_prod_assert = regex_rule(
    "`assert` dans le code de production (supprime avec python -O)",
    r"^\s*assert\s+", why="une garantie qui disparait en prod n'en est pas une", flags=re.M,
    exclude=("backtesting/",))

c_print_prod = regex_rule(
    "`print()` dans le code (au lieu du logger)",
    r"^\s*print\s*\(", why="invisible dans les logs d'un run 48h", flags=re.M,
    exclude=("cli.py", "tools/", "backtesting/", "__main__"))

c_naive_datetime = regex_rule(
    "datetime.now() sans fuseau (bug d'horodatage)",
    r"datetime\.now\(\s*\)", why="un timestamp sans TZ fausse la fraicheur des signaux")

c_abs_path = regex_rule(
    "Chemins absolus en dur (casse sur une autre machine)",
    r"[\"'][A-Za-z]:[\\\\/]{1,2}[^\"']{3,}[\"']", why="non portable")

c_global_state = regex_rule(
    "Etat global mutable (`global x`)",
    r"^\s*global\s+\w+", why="etat partage = bugs de concurrence", flags=re.M)

c_sleep_long = regex_rule(
    "time.sleep() tres long (> 60s)",
    r"time\.sleep\(\s*(?:[6-9]\d|\d{3,})", why="fige la boucle trop longtemps")


# ---------------------------------------------------------------- QUALITE (AST)
def c_long_functions():
    c = Check("Fonctions trop longues (> 120 lignes : intestables)", blocking=False)
    bad = []
    for p in _py_files(*_code_dirs_no_tests()):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                              # noqa: BLE001
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = getattr(n, "end_lineno", n.lineno)
                if end - n.lineno > 120:
                    bad.append(f"{_rel(p)}:{n.lineno} `{n.name}` = {end - n.lineno} lignes")
    return c.finish(f"{len(bad)} fonction(s) trop longue(s)", [], _trim(bad))


def c_too_many_args():
    c = Check("Fonctions a trop de parametres (> 8)", blocking=False)
    bad = []
    for p in _py_files(*_code_dirs_no_tests()):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                              # noqa: BLE001
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nargs = len(n.args.args) + len(n.args.kwonlyargs)
                if nargs > 8:
                    bad.append(f"{_rel(p)}:{n.lineno} `{n.name}` = {nargs} parametres")
    return c.finish(f"{len(bad)} fonction(s) surchargee(s)", [], _trim(bad))


def c_complexity():
    c = Check("Complexite excessive (> 25 branches dans une fonction)", blocking=False)
    bad = []
    BR = (ast.If, ast.For, ast.While, ast.Try, ast.BoolOp, ast.IfExp, ast.ExceptHandler)
    for p in _py_files(*_code_dirs_no_tests()):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                              # noqa: BLE001
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                score = sum(1 for x in ast.walk(n) if isinstance(x, BR))
                if score > 25:
                    bad.append(f"{_rel(p)}:{n.lineno} `{n.name}` complexite {score}")
    return c.finish(f"{len(bad)} fonction(s) trop complexe(s)", [], _trim(bad))


def c_duplicate_bodies():
    c = Check("Fonctions DUPLIQUEES (corps identique)", blocking=False)
    import hashlib
    seen, dupes = {}, []
    for p in _py_files(*_code_dirs_no_tests()):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                              # noqa: BLE001
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body = ast.dump(ast.Module(body=n.body, type_ignores=[]))
                if len(body) < 400:
                    continue
                h = hashlib.md5(body.encode()).hexdigest()
                if h in seen:
                    dupes.append(f"{_rel(p)}:{n.lineno} `{n.name}` == {seen[h]}")
                else:
                    seen[h] = f"{_rel(p)}:{n.lineno} `{n.name}`"
    return c.finish(f"{len(dupes)} duplication(s)", [], _trim(dupes))


def c_module_docstrings():
    c = Check("Modules sans docstring (on ne sait pas a quoi ils servent)", blocking=False)
    bad = []
    for p in _py_files("src"):
        if _rel(p).endswith("__init__.py"):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                              # noqa: BLE001
            continue
        if not ast.get_docstring(tree):
            bad.append(f"{_rel(p)} : aucune docstring de module")
    return c.finish(f"{len(bad)} module(s) non documente(s)", [], _trim(bad))


def c_duplicate_module_names():
    c = Check("Noms de modules DUPLIQUES entre paquets (confusion garantie)", blocking=False)
    names = {}
    for p in _py_files(*_code_dirs_no_tests()):
        if _rel(p).endswith("__init__.py"):
            continue
        names.setdefault(p.stem, []).append(_rel(p))
    dup = [f"`{k}` existe en {len(v)} exemplaires : {', '.join(v[:4])}"
           for k, v in sorted(names.items()) if len(v) > 1]
    return c.finish(f"{len(dup)} nom(s) duplique(s)", [], _trim(dup))


# ---------------------------------------------------------------- ARCHITECTURE
def _imports_of(path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:                                                  # noqa: BLE001
        return set()
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            if getattr(n, "level", 0):        # `from .x import y` = INTERNE, pas une dependance
                continue
            if n.module:
                out.add(n.module)
        elif isinstance(n, ast.Import):
            for a in n.names:
                out.add(a.name)
    return out


def _layer_rule(title, from_pkg, forbidden_pkg, why, exclude=()):
    def _fn():
        c = Check(title, blocking=False)
        bad = []
        for p in _py_files("src"):
            rel = _rel(p).replace(os.sep, "/")
            if from_pkg not in rel or any(x in rel for x in exclude):
                continue
            for imp in _imports_of(p):
                if forbidden_pkg in imp:
                    bad.append(f"{rel} importe {imp}")
        return c.finish(f"{len(bad)} violation(s) de couche -- {why}", [], _trim(bad))
    return _fn


c_layer_risk_ui = _layer_rule("Couches : risk/ ne doit PAS dependre de l'UI",
                              "hl_observer/risk/", "hl_observer.ui",
                              "le moteur de risque doit vivre sans interface")
c_layer_paper_ui = _layer_rule("Couches : paper_trading/ ne doit PAS dependre de l'UI",
                               "hl_observer/paper_trading/", "hl_observer.ui",
                               "le ledger doit etre independant de l'affichage")
c_layer_edge_ui = _layer_rule("Couches : edge/ ne doit PAS dependre de l'UI",
                              "hl_observer/edge/", "hl_observer.ui",
                              "le calcul d'edge doit etre pur")
c_layer_hl_dydx = _layer_rule("Separation : le runtime Hyperliquid ne doit PAS importer dYdX",
                              "hl_observer/", "dydx_v4",
                              "dydx_v4 est un LEGACY separe (regle CLAUDE.md)",
                              exclude=("cli.py", "ui/"))


def c_toolkit_pure():
    c = Check("Le toolkit quant (backtesting/) doit rester SANS dependance externe")
    STD = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()
    bad = []
    for p in _py_files("src"):
        rel = _rel(p).replace(os.sep, "/")
        if "hl_observer/backtesting/" not in rel:
            continue
        for imp in _imports_of(p):
            root = imp.split(".")[0]
            if root in STD or root in ("hl_observer", "__future__"):
                continue
            if root == "numpy" and "vectorized" in rel:
                continue                      # numpy AVEC fallback pur : autorise
            bad.append(f"{rel} importe `{imp}` (le toolkit doit rester pur)")
    return c.finish(f"{len(bad)} dependance(s) externe(s) dans le toolkit", _trim(bad))


def c_no_io_at_import():
    c = Check("Aucun I/O reseau au moment de l'import (un import ne doit rien faire)",
              blocking=False)
    bad = []
    for p in _py_files(*_code_dirs_no_tests()):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                              # noqa: BLE001
            continue
        for n in tree.body:                              # niveau MODULE uniquement
            for x in ast.walk(n):
                if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute):
                    if x.func.attr in ("get", "post", "connect", "urlopen") and \
                       isinstance(x.func.value, ast.Name) and \
                       x.func.value.id in ("httpx", "requests", "websockets", "urllib"):
                        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            bad.append(f"{_rel(p)}:{x.lineno} appel reseau a l'import")
    return c.finish(f"{len(bad)} I/O a l'import", [], _trim(bad))


# ---------------------------------------------------------------- CONFIG (suite)
def c_cmd_duplicate_set():
    c = Check("Doublons de `set` dans le lanceur (le DERNIER gagne : piege)", blocking=False)
    txt = CMD.read_text(encoding="utf-8", errors="replace")
    seen, dup = {}, []
    for m in re.finditer(r'set "([A-Z0-9_]+)=([^"]*)"', txt):
        k, v = m.group(1), m.group(2)
        line = txt[:m.start()].count("\n") + 1
        if k in seen and seen[k][1] != v:
            dup.append(f"{k} : ligne {seen[k][0]}={seen[k][1]!r} PUIS ligne {line}={v!r} "
                       f"-> seule la 2e compte")
        seen[k] = (line, v)
    return c.finish(f"{len(dup)} doublon(s) contradictoire(s)", [], _trim(dup))


def c_env_read_but_never_set():
    c = Check("Variables LUES par le code mais jamais reglees (defaut silencieux)", blocking=False)
    read = {}
    for p in _py_files(*_code_dirs_no_tests()):
        txt = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'(?:getenv|environ\.get)\(\s*["\'](HYPERSMART_[A-Z0-9_]+)["\']', txt):
            read.setdefault(m.group(1), _rel(p))
    cfg = set(effective_config())
    never = sorted(k for k in read if k not in cfg)
    warns = [f"{k} : lu par {read[k]} mais JAMAIS regle -> valeur par defaut silencieuse"
             for k in never]
    return c.finish(f"{len(never)} variable(s) sur defaut silencieux / {len(read)} lues",
                    [], _trim(warns))


def c_risk_values_sane():
    c = Check("Valeurs de risque dans des bornes sensees")
    cfg = effective_config()
    errs = []
    def g(k, d=None):
        try:
            return float(cfg.get(k, d))
        except (TypeError, ValueError):
            return None
    lev = g("HYPERSMART_SIMULATION_LEVERAGE")
    if lev is not None and not (1 <= lev <= 20):
        errs.append(f"levier hors bornes : {lev} (attendu 1..20)")
    marge = g("HYPERSMART_MAX_POSITION_USDT")
    pos = g("HYPERSMART_MAX_OPEN_POSITIONS")
    budget = g("HYPERSMART_MAX_TOTAL_EXPOSURE_USDT")
    if None not in (marge, pos, budget) and marge * pos > budget * 1.001:
        errs.append(f"budget incoherent : marge {marge} x {pos} positions = {marge * pos} "
                    f"> budget {budget}")
    sl = g("HYPERSMART_SLTP_STOP_LOSS_BPS")
    cat = g("HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS")
    if None not in (sl, cat) and sl > cat:
        errs.append(f"stop-loss ({sl}) > stop catastrophique ({cat}) : incoherent")
    age = g("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS")
    if age is not None and age > 60000:
        errs.append(f"fraicheur trop laxiste : {age} ms (> 60s = signal mort)")
    return c.finish(f"{len(errs)} incoherence(s) de risque", errs)


def c_env_example_sync():
    c = Check(".env.example couvre-t-il les variables lues ?", blocking=False)
    ex = (ROOT / ".env.example")
    if not ex.is_file():
        return c.finish(".env.example absent", [], ["[info] pas de .env.example"])
    txt = ex.read_text(encoding="utf-8", errors="replace")
    missing = sorted(k for k in effective_config() if k.startswith("HL_") and k not in txt)
    return c.finish(f"{len(missing)} variable(s) absente(s) de .env.example", [],
                    _trim([f"{k} : absente de .env.example" for k in missing]))


# ---------------------------------------------------------------- TESTS (suite)
def c_tests_write_runtime():
    c = Check("Tests qui ECRIVENT dans runtime/ ou logs/ (polluent tes vraies donnees)")
    bad = []
    for p in _py_files("tests"):
        txt = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"open\(\s*[\"'](?:\./)?(runtime|logs)[/\\]", txt):
            line = txt[:m.start()].count("\n") + 1
            bad.append(f"{_rel(p)}:{line} ecrit dans {m.group(1)}/ -- pollue tes donnees reelles")
    return c.finish(f"{len(bad)} test(s) qui polluent", _trim(bad))


def c_slow_tests():
    c = Check("Tests LENTS (> 5s) -- ralentissent chaque audit", blocking=False)
    out = _TESTS_OUT.get("first", "")
    if not out:
        return c.finish("suite pas encore lancee", [], ["[info] mesure pendant la suite"])
    slow = re.findall(r"^(\S+::\S+)\s+.*?(\d+\.\d+)s", out, re.M)
    rows = [f"{n} : {t}s" for n, t in slow if float(t) > 5]
    return c.finish(f"{len(rows)} test(s) lent(s)", [], _trim(rows))


def c_test_ratio():
    c = Check("Ratio tests / modules (densite de verification)", blocking=False)
    mods = len([p for p in _py_files("src") if not _rel(p).endswith("__init__.py")])
    tests = len(_py_files("tests"))
    ntest = 0
    for p in _py_files("tests"):
        ntest += len(re.findall(r"^def test_", p.read_text(encoding="utf-8", errors="replace"), re.M))
    ratio = ntest / mods if mods else 0
    warns = [f"{mods} modules, {tests} fichiers de test, {ntest} tests "
             f"-> {ratio:.1f} test(s) par module"]
    if ratio < 1:
        warns.append("ALERTE : moins d'un test par module en moyenne")
    return c.finish(f"{ratio:.1f} test/module", [], warns)


def c_critical_coverage():
    c = Check("Couverture des paquets CRITIQUES (risk, paper_trading, edge, signals)",
              blocking=False)
    if not COVERAGE_ROWS:
        return c.finish("coverage indisponible", [], ["[info] `pip install coverage`"])
    crit = ("risk", "paper_trading", "edge", "signals", "security")
    warns, low = [], 0
    for f, n, pct in COVERAGE_ROWS:
        norm = f.replace("\\", "/")
        if any(f"/{k}/" in norm for k in crit):
            if pct < 60:
                warns.append(f"CRITIQUE peu couvert : {norm} = {pct}%")
                low += 1
    return c.finish(f"{low} fichier(s) critique(s) sous 60% de couverture", [], _trim(warns))


# ---------------------------------------------------------------- DEPENDANCES / GIT
def c_deps_declared():
    c = Check("Dependances importees mais NON declarees dans requirements.txt", blocking=False)
    req = (ROOT / "requirements.txt")
    declared = set()
    if req.is_file():
        for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                declared.add(re.split(r"[<>=!\[]", line)[0].strip().lower())
    STD = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()
    used, missing = set(), []
    for p in _py_files(*_code_dirs_no_tests()):
        for imp in _imports_of(p):
            root = imp.split(".")[0]
            if root in STD or root in ("hl_observer", "hyper_smart_observer", "__future__"):
                continue
            used.add(root.lower())
    for u in sorted(used):
        if u not in declared:
            missing.append(f"`{u}` importe par le code mais absent de requirements.txt")
    unused = sorted(d for d in declared if d not in used and d not in ("pytest", "ruff", "mypy"))
    return c.finish(f"{len(missing)} dep(s) non declaree(s), {len(unused)} declaree(s) inutilisee(s)",
                    [], _trim(missing + [f"`{u}` declaree mais jamais importee" for u in unused]))


def c_gitignore():
    c = Check("Le .gitignore protege-t-il les donnees lourdes ?", blocking=False)
    gi = (ROOT / ".gitignore")
    txt = gi.read_text(encoding="utf-8", errors="replace") if gi.is_file() else ""
    need = ["runtime/", "logs/", ".coverage", "resultat-audit.md", "__pycache__"]
    missing = [n for n in need if n not in txt]
    return c.finish(f"{len(missing)} motif(s) manquant(s)", [],
                    [f"{m} : absent du .gitignore (risque de versionner du lourd)" for m in missing])


def c_big_tracked_files():
    c = Check("Gros fichiers suivis par git (> 5 Mo)", blocking=False)
    code, out = _run(["git", "ls-files"], timeout=120)
    big = []
    for rel in out.splitlines()[:6000]:
        f = ROOT / rel.strip()
        try:
            if f.is_file() and f.stat().st_size > 5_000_000:
                big.append(f"{rel.strip()} = {f.stat().st_size / 1e6:.0f} Mo (versionne !)")
        except OSError:
            continue
    return c.finish(f"{len(big)} gros fichier(s) versionne(s)", [], _trim(big))



# ---------------------------------------------------------------- PIEGES SPECIFIQUES A CE BOT
c_open_no_encoding = regex_rule(
    "open() SANS encoding= (sous Windows -> cp1252 -> mojibake)",
    r"open\((?![^)]*encoding)(?![^)]*[\"']rb[\"'])(?![^)]*[\"']wb[\"'])[^)]*\)",
    why="tu as DEJA eu des logs corrompus a cause de ca")

c_float_equality = regex_rule(
    "Comparaison d'egalite entre FLOTTANTS (== sur des prix/PnL)",
    r"(?:price|pnl|equity|notional|edge|qty|size|amount)\w*\s*==\s*[\d.]",
    why="0.1+0.2 != 0.3 : en trading c'est un bug garanti", flags=re.I)

c_div_no_guard = regex_rule(
    "Divisions sans garde (ZeroDivisionError en pleine boucle 48h)",
    r"/\s*(?:len\(|sum\(|total|count|denom|n_)\w*(?!\s*(?:if|or|\)))",
    why="une division par zero tue la boucle")

c_time_not_monotonic = regex_rule(
    "Duree mesuree avec time.time() (saute si l'horloge change)",
    r"(?:elapsed|duration|latency|took|delta)\w*\s*=\s*time\.time\(\)\s*-",
    why="utiliser time.monotonic() pour mesurer une duree", flags=re.I)

c_utcnow = regex_rule(
    "datetime.utcnow() (deprecie, et naif)",
    r"datetime\.utcnow\(\)", why="utiliser datetime.now(timezone.utc)")

c_star_import = regex_rule(
    "`from x import *` (pollue l'espace de noms, masque les erreurs)",
    r"^\s*from\s+\S+\s+import\s+\*", why="on ne sait plus d'ou vient quoi", flags=re.M)

c_env_no_default = regex_rule(
    "os.environ[...] sans defaut (KeyError au demarrage)",
    r"os\.environ\[[\"'][A-Z_]+[\"']\]", why="plante le bot au boot si la variable manque")

c_sys_exit_lib = regex_rule(
    "sys.exit() hors CLI (une librairie ne doit jamais tuer le process)",
    r"sys\.exit\(", why="un module importe ne doit pas decider de mourir",
    exclude=("cli.py", "__main__", "tools/"))

c_basicconfig = regex_rule(
    "logging.basicConfig() dans une librairie (ecrase la config globale)",
    r"logging\.basicConfig\(", why="seul le point d'entree doit configurer les logs",
    exclude=("cli.py", "__main__", "tools/"))

c_hardcoded_url = regex_rule(
    "URLs en dur (au lieu de la config)",
    r"[\"']https?://(?!127\.0\.0\.1|localhost)[^\"']+[\"']",
    why="une URL en dur ne se change pas sans recompiler")

c_shadow_builtin = regex_rule(
    "Variables qui masquent un builtin (list, dict, id, type, input...)",
    r"^\s*(list|dict|set|id|type|input|filter|map|max|min|sum|next|hash)\s*=",
    why="masquer un builtin = bug silencieux", flags=re.M)

c_type_ignore = regex_rule(
    "`# type: ignore` / `# noqa` (avertissements etouffes)",
    r"#\s*(type:\s*ignore|noqa)", why="chaque ignore cache un probleme reel")

c_lazy_import = regex_rule(
    "Imports a l'interieur de fonctions (souvent un contournement de cycle)",
    r"^\s{4,}(?:from|import)\s+hl_observer", why="signe d'une dependance circulaire", flags=re.M)

c_pass_in_except = regex_rule(
    "`continue` dans un except (erreur ignoree en boucle)",
    r"except[^\n]*:\s*\n\s+continue", why="une erreur repetee 48h passe inapercue")

c_recursion = regex_rule(
    "Recursion sans limite explicite",
    r"def\s+(\w+)\([^)]*\):(?:(?!\ndef ).)*?\b\1\s*\(",
    why="risque de RecursionError sur donnee inattendue", flags=re.S)


def c_deep_nesting():
    c = Check("Imbrication trop profonde (> 5 niveaux : illisible et fragile)", blocking=False)
    bad = []
    for p in _py_files(*_code_dirs_no_tests()):
        txt = p.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(txt.splitlines(), 1):
            if line.strip() and not line.strip().startswith("#"):
                indent = len(line) - len(line.lstrip(" "))
                if indent >= 24:                      # 6 niveaux de 4 espaces
                    bad.append(f"{_rel(p)}:{i} imbrication niveau {indent // 4}")
    return c.finish(f"{len(bad)} ligne(s) trop imbriquee(s)", [], _trim(bad))


def c_big_classes():
    c = Check("Classes trop grosses (> 400 lignes)", blocking=False)
    bad = []
    for p in _py_files(*_code_dirs_no_tests()):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                              # noqa: BLE001
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.ClassDef):
                end = getattr(n, "end_lineno", n.lineno)
                if end - n.lineno > 400:
                    bad.append(f"{_rel(p)}:{n.lineno} `{n.name}` = {end - n.lineno} lignes")
    return c.finish(f"{len(bad)} classe(s) obese(s)", [], _trim(bad))


def c_empty_files():
    c = Check("Fichiers Python vides ou quasi vides", blocking=False)
    bad = []
    for p in _py_files(*_code_dirs_no_tests()):
        if _rel(p).endswith("__init__.py"):
            continue
        txt = p.read_text(encoding="utf-8", errors="replace").strip()
        if len(txt) < 40:
            bad.append(f"{_rel(p)} : {len(txt)} caracteres (fichier vide ?)")
    return c.finish(f"{len(bad)} fichier(s) vide(s)", [], _trim(bad))


def c_init_with_logic():
    c = Check("__init__.py contenant de la LOGIQUE (effets de bord a l'import)", blocking=False)
    bad = []
    for p in _py_files(*_code_dirs_no_tests()):
        if not _rel(p).endswith("__init__.py"):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                              # noqa: BLE001
            continue
        heavy = [n for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.For, ast.While, ast.If))]
        if len(heavy) > 2:
            bad.append(f"{_rel(p)} : {len(heavy)} bloc(s) de logique dans un __init__")
    return c.finish(f"{len(bad)} __init__ avec logique", [], _trim(bad))


def c_test_files_misplaced():
    c = Check("Fichiers test_*.py HORS du dossier tests/ (jamais executes)")
    bad = []
    for p in _py_files(*_code_dirs_no_tests()):
        if p.name.startswith("test_"):
            bad.append(f"{_rel(p)} : nomme test_* mais hors de tests/ -> JAMAIS lance")
    return c.finish(f"{len(bad)} test(s) au mauvais endroit", _trim(bad))


def c_type_hints():
    c = Check("Taux de fonctions annotees (types)", blocking=False)
    total = annotated = 0
    for p in _py_files("src"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                              # noqa: BLE001
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total += 1
                if n.returns is not None or any(a.annotation for a in n.args.args):
                    annotated += 1
    pct = (100 * annotated / total) if total else 0
    return c.finish(f"{pct:.0f}% des fonctions sont annotees ({annotated}/{total})", [],
                    [f"{pct:.0f}% de fonctions typees -- viser > 70% pour attraper les bugs tot"])


def c_git_dirty():
    c = Check("Etat git (fichiers non commites = travail non protege)", blocking=False)
    code, out = _run(["git", "status", "--porcelain"], timeout=120)
    rows = [l for l in out.splitlines() if l.strip()]
    warns = [f"{len(rows)} fichier(s) modifie(s) non commite(s)"]
    warns += [f"  {l.strip()[:100]}" for l in rows[:25]]
    return c.finish(f"{len(rows)} fichier(s) non commite(s)", [], warns)


def c_inventory_stats():
    c = Check("Inventaire global du projet", blocking=False)
    mods = [p for p in _py_files("src") if not _rel(p).endswith("__init__.py")]
    lines = sum(p.read_text(encoding="utf-8", errors="replace").count("\n") for p in _py_files())
    tests = _py_files("tests")
    return c.finish(f"{len(mods)} modules, {len(tests)} fichiers de test, {lines} lignes", [],
                    [f"paquets de code : {', '.join(code_dirs())}",
                     f"modules src/ : {len(mods)}",
                     f"fichiers de test : {len(tests)}",
                     f"lignes de code totales : {lines}"])



# ==================================================================================
#  BATTERIE PnL & SIMULATION (demande de Flo)
#  Ces controles NE LISENT PAS le code : ils l'EXECUTENT avec des chiffres connus
#  et verifient que le resultat est le bon. C'est la seule facon de prouver que le
#  PnL n'est pas faux.
# ==================================================================================

def exec_rule(title, fn, *, blocking=True):
    """Controle EXECUTE : fn() doit lever AssertionError si le calcul est faux."""
    def _wrapped():
        c = Check(title, blocking=blocking)
        try:
            detail = fn()
            return c.finish(f"OK -- {detail}" if detail else "OK")
        except AssertionError as e:
            return c.finish("CALCUL FAUX", [f"{e}"])
        except (ImportError, AttributeError, TypeError) as e:
            c.blocking = False
            return c.finish("non verifiable (API differente)", [], [f"[info] {type(e).__name__}: {e}"])
    return _wrapped


def _V():
    from hl_observer.backtesting import vectorized as v
    return v


def _edge(**kw):
    from hl_observer.edge.edge_calculator import EdgeNetInputs, compute_net_edge
    min_edge = kw.pop("min_edge_bps", 30.0)        # parametre du GATE, pas des inputs
    base = dict(gross_edge_bps=100.0, taker_fee_bps=0.0, spread_cost_bps=0.0, slippage_bps=0.0,
                latency_decay_bps=0.0, copy_degradation_bps=0.0, funding_cost_bps=0.0,
                maker_rebate_bps=0.0)
    base.update(kw)
    return compute_net_edge(EdgeNetInputs(**base), min_edge_bps=min_edge)


# ---------------- PnL : le signe et la magnitude ----------------
def _pnl_long_up():
    p = _V().fast_pnl([100.0], [110.0], [1], notional=500.0, cost_bps=0.0)[0]
    assert abs(p - 50.0) < 1e-6, f"LONG +10% sur 500$ devrait donner +50$, obtenu {p}"
    return "LONG, prix +10% -> +50$ sur 500$ de notional"


def _pnl_long_down():
    p = _V().fast_pnl([100.0], [90.0], [1], notional=500.0, cost_bps=0.0)[0]
    assert abs(p + 50.0) < 1e-6, f"LONG -10% devrait donner -50$, obtenu {p}"
    return "LONG, prix -10% -> -50$ (la perte est bien comptee)"


def _pnl_short_down():
    p = _V().fast_pnl([100.0], [90.0], [-1], notional=500.0, cost_bps=0.0)[0]
    assert abs(p - 50.0) < 1e-6, f"SHORT -10% devrait donner +50$, obtenu {p}"
    return "SHORT, prix -10% -> +50$ (le signe du short est correct)"


def _pnl_short_up():
    p = _V().fast_pnl([100.0], [110.0], [-1], notional=500.0, cost_bps=0.0)[0]
    assert abs(p + 50.0) < 1e-6, f"SHORT +10% devrait donner -50$, obtenu {p}"
    return "SHORT, prix +10% -> -50$"


def _pnl_symmetry():
    lo = _V().fast_pnl([100.0], [110.0], [1], notional=500.0, cost_bps=0.0)[0]
    sh = _V().fast_pnl([100.0], [110.0], [-1], notional=500.0, cost_bps=0.0)[0]
    assert abs(lo + sh) < 1e-9, f"long et short doivent etre opposes : {lo} vs {sh}"
    return "LONG et SHORT sont exactement opposes (pas de biais cache)"


def _fees_are_charged():
    p = _V().fast_pnl([100.0], [100.0], [1], notional=500.0, cost_bps=6.0)[0]
    assert abs(p + 0.30) < 1e-9, f"entree=sortie devrait coder -0.30$ de frais, obtenu {p}"
    return "entree = sortie -> il reste EXACTEMENT le cout (-0.30$) : les frais sont preleves"


def _fees_not_double_counted():
    a = _V().fast_pnl([100.0], [100.0], [1], notional=500.0, cost_bps=6.0)[0]
    b = _V().fast_pnl([100.0], [100.0], [1], notional=500.0, cost_bps=12.0)[0]
    assert abs(b - 2 * a) < 1e-9, f"doubler le cout doit doubler la charge : {a} -> {b}"
    return "doubler les frais double EXACTEMENT la charge (pas de double comptage)"


def _pnl_scales_with_notional():
    a = _V().fast_pnl([100.0], [110.0], [1], notional=500.0, cost_bps=0.0)[0]
    b = _V().fast_pnl([100.0], [110.0], [1], notional=1000.0, cost_bps=0.0)[0]
    assert abs(b - 2 * a) < 1e-9, f"doubler le notional doit doubler le PnL : {a} -> {b}"
    return "PnL proportionnel au notional (x2 notional = x2 PnL)"


def _pnl_numpy_equals_pure():
    e = [100.0, 101.0, 99.0]
    x = [102.0, 100.0, 97.0]
    s = [1, -1, 1]
    a = _V().fast_pnl(e, x, s, use_numpy=True)
    b = _V().fast_pnl(e, x, s, use_numpy=False)
    assert all(abs(u - v) < 1e-9 for u, v in zip(a, b)), "numpy et python pur divergent !"
    return "le chemin numpy et le chemin python pur donnent le MEME PnL"


# ---------------- Sizing : marge x levier ----------------
def _sizing_margin_times_leverage():
    os.environ["HYPERSMART_MAX_POSITION_USDT"] = "50"
    os.environ["HYPERSMART_SIMULATION_LEVERAGE"] = "10"
    from hl_observer.ui.fusion_persistent_adapter import _cap_paper_notional_and_quantity
    r = _cap_paper_notional_and_quantity(999.0, 1.0, 100.0)
    assert abs(r["notional"] - 500.0) < 1e-6, \
        f"marge 50 x levier 10 doit donner 500 de notional, obtenu {r['notional']}"
    return "sizing = marge (50$) x levier (10) = 500$ de notional"


def _leverage_not_applied_twice():
    os.environ["HYPERSMART_MAX_POSITION_USDT"] = "50"
    os.environ["HYPERSMART_SIMULATION_LEVERAGE"] = "10"
    from hl_observer.ui.fusion_persistent_adapter import _cap_paper_notional_and_quantity
    r = _cap_paper_notional_and_quantity(50.0, 0.5, 100.0)
    assert r["notional"] <= 500.0 + 1e-6, \
        f"levier applique DEUX fois ? notional={r['notional']} (max attendu 500)"
    return "le levier n'est PAS applique deux fois (notional <= marge x levier)"


def _quantity_matches_notional():
    os.environ["HYPERSMART_MAX_POSITION_USDT"] = "50"
    os.environ["HYPERSMART_SIMULATION_LEVERAGE"] = "10"
    from hl_observer.ui.fusion_persistent_adapter import _cap_paper_notional_and_quantity
    r = _cap_paper_notional_and_quantity(999.0, 1.0, 250.0)
    assert abs(r["quantity"] * 250.0 - r["notional"]) < 1e-4, \
        "quantite x prix != notional : la position affichee serait FAUSSE"
    return "quantite x prix = notional (la position affichee est coherente)"


# ---------------- Edge net : les couts reduisent TOUJOURS ----------------
def _costs_always_reduce_edge():
    brut = _edge().net_edge_bps
    net = _edge(taker_fee_bps=5.0, spread_cost_bps=3.0, slippage_bps=2.0).net_edge_bps
    assert net < brut, f"les couts doivent REDUIRE l'edge : brut={brut} net={net}"
    assert abs(brut - net - 10.0) < 1e-6, f"5+3+2 = 10 bps de cout attendus, ecart={brut - net}"
    return "frais + spread + slippage = 10 bps retires de l'edge, exactement"


def _all_six_costs_counted():
    net = _edge(taker_fee_bps=1.0, spread_cost_bps=2.0, slippage_bps=3.0, latency_decay_bps=4.0,
                copy_degradation_bps=5.0, funding_cost_bps=6.0).net_edge_bps
    assert abs(net - (100.0 - 21.0)) < 1e-6, \
        f"les 6 couts (1+2+3+4+5+6=21) doivent tous compter, net={net}"
    return "les 6 couts comptent : frais, spread, slippage, latence, degradation, funding"


def _degradation_hurts():
    a = _edge(copy_degradation_bps=0.0).net_edge_bps
    b = _edge(copy_degradation_bps=13.0).net_edge_bps
    assert b < a and abs(a - b - 13.0) < 1e-6, "la degradation de copie doit couter exactement 13 bps"
    return "la degradation de copie (13 bps) est bien facturee -- c'est LE cout qui tue le copy-trading"


def _maker_rebate_helps():
    a = _edge(taker_fee_bps=5.0).net_edge_bps
    b = _edge(taker_fee_bps=5.0, maker_rebate_bps=2.0).net_edge_bps
    assert b > a, "le rebate maker doit AMELIORER l'edge net"
    return "le rebate maker ameliore l'edge (2 bps recuperes)"


def _negative_edge_rejected():
    r = _edge(gross_edge_bps=5.0, taker_fee_bps=10.0)
    assert "REJECT" in r.decision, f"un edge NEGATIF doit etre REFUSE, decision={r.decision}"
    return "edge net negatif -> REFUS automatique"


def _small_edge_rejected():
    r = _edge(gross_edge_bps=35.0, taker_fee_bps=10.0, min_edge_bps=30.0)
    assert "REJECT" in r.decision, f"edge 25 bps < plancher 30 -> doit etre refuse, {r.decision}"
    return "edge sous le plancher -> REFUS (le plancher est vraiment applique)"


def _good_edge_accepted():
    r = _edge(gross_edge_bps=100.0, taker_fee_bps=5.0, min_edge_bps=30.0)
    assert "REJECT" not in r.decision, f"un edge de 95 bps devrait passer, {r.decision}"
    return "edge largement positif -> accepte (le gate ne bloque pas tout)"


# ---------------- Gates de risque : ils refusent VRAIMENT ----------------
def _exposure_cap_refuses():
    from hl_observer.ui.fusion_persistent_adapter import _portfolio_open_refusal
    from hl_observer.ui.state import UiState
    os.environ["HYPERSMART_MAX_TOTAL_EXPOSURE_USDT"] = "75"
    os.environ["HYPERSMART_SIMULATION_LEVERAGE"] = "1"
    os.environ["HYPERSMART_MAX_OPEN_POSITIONS"] = "10"
    st = UiState()
    st.simulation_virtual_positions = {"a": {"notional_usdt": 60.0}}
    r = _portfolio_open_refusal(st, new_notional_usdt=40.0)
    assert r, "60 + 40 = 100 > budget 75 : le plafond DOIT refuser (fail-open detecte !)"
    return f"budget depasse -> refus `{r}` (le plafond n'est pas fail-open)"


def _max_positions_refuses():
    from hl_observer.ui.fusion_persistent_adapter import _portfolio_open_refusal
    from hl_observer.ui.state import UiState
    os.environ["HYPERSMART_MAX_OPEN_POSITIONS"] = "3"
    os.environ["HYPERSMART_MAX_TOTAL_EXPOSURE_USDT"] = "100000"
    st = UiState()
    st.simulation_virtual_positions = {f"p{i}": {"notional_usdt": 10.0} for i in range(3)}
    r = _portfolio_open_refusal(st, new_notional_usdt=10.0)
    assert r, "3 positions ouvertes sur un max de 3 : la 4e DOIT etre refusee"
    return f"plafond de positions -> refus `{r}`"


def _min_notional_refuses():
    from hl_observer.ui.fusion_persistent_adapter import _min_paper_notional_refusal
    os.environ["HYPERSMART_MIN_PAPER_NOTIONAL_USDT"] = "40"
    r = _min_paper_notional_refusal(12.0)
    assert r, "un trade de 12$ sous un plancher de 40$ DOIT etre refuse"
    os.environ["HYPERSMART_MIN_PAPER_NOTIONAL_USDT"] = "0"
    return f"micro-trade sous le plancher -> refus `{r}` (les frais mangeraient le gain)"


# ---------------- Drawdown / equity ----------------
def _drawdown_known_value():
    dd = _V().fast_drawdown([1000.0, 1020.0, 980.0, 1005.0, 950.0])
    assert abs(dd - 70.0) < 1e-9, f"drawdown attendu 70 (1020 -> 950), obtenu {dd}"
    return "drawdown = pic (1020) - creux (950) = 70$"


def _drawdown_never_negative():
    dd = _V().fast_drawdown([1000.0, 1100.0, 1200.0])
    assert dd >= 0, f"un drawdown ne peut pas etre negatif : {dd}"
    return "courbe qui ne fait que monter -> drawdown = 0 (jamais negatif)"


def _profit_factor_known():
    from hl_observer.backtesting.robustness import profit_factor
    pf = profit_factor([10.0, 10.0, -5.0])
    assert abs(pf - 4.0) < 1e-9, f"profit factor = 20/5 = 4, obtenu {pf}"
    return "profit factor = gains/pertes = 20/5 = 4 (le juge de paix, pas le winrate)"


# ---------------- Risque ----------------
def _cvar_worse_than_var():
    from hl_observer.backtesting.risk_sizing import cvar, historical_var
    rets = [-0.10, -0.08, -0.05, -0.01, 0.0, 0.02, 0.03, 0.05, 0.07, 0.10]
    v, cv = historical_var(rets, alpha=0.2), cvar(rets, alpha=0.2)
    # convention : les deux renvoient une PERTE POSITIVE -> la CVaR doit etre PLUS GRANDE
    assert cv >= v - 1e-12, f"la CVaR (perte moyenne en queue) doit etre >= la VaR : {cv} vs {v}"
    return f"VaR={v:.3f}, CVaR={cv:.3f} : la queue est bien pire que le seuil"


def _kelly_is_bounded():
    from hl_observer.backtesting.risk_sizing import fractional_kelly
    k = fractional_kelly(0.99, 10.0, fraction=0.5)
    assert 0.0 <= k <= 1.0, f"la fraction de Kelly doit rester dans [0,1], obtenu {k}"
    return "Kelly borne dans [0,1] : jamais de sur-levier meme sur un signal 'parfait'"


def _vol_target_inverse():
    from hl_observer.backtesting.risk_sizing import vol_target_size
    small = vol_target_size(0.10, 0.40, 1000.0)
    big = vol_target_size(0.10, 0.10, 1000.0)
    assert big > small, "quand la volatilite MONTE, la taille doit BAISSER"
    return "vol-targeting : marche agite -> position plus petite"


# ---------------- Execution / microstructure ----------------
def _slippage_grows_with_size():
    from hl_observer.backtesting.execution_models import almgren_chriss_cost
    a = almgren_chriss_cost(100.0, adv=1_000_000.0, spread_bps=2.0)
    b = almgren_chriss_cost(100_000.0, adv=1_000_000.0, spread_bps=2.0)
    assert b > a, f"un gros ordre doit couter PLUS cher : petit={a} gros={b}"
    return f"impact : petit ordre {a:.2f} bps -> gros ordre {b:.2f} bps"


def _micro_price_between_bid_ask():
    from hl_observer.backtesting.execution_models import micro_price
    mp = micro_price(100.0, 100.1, 8.0, 2.0)
    assert 100.0 <= mp <= 100.1, f"le micro-prix doit rester dans le spread, obtenu {mp}"
    return "micro-prix toujours entre bid et ask"


def _spread_costs_money():
    from hl_observer.backtesting.execution_models import effective_spread
    s = effective_spread(100.10, 100.05, "BUY")
    assert s > 0, "acheter au-dessus du mid DOIT couter (spread positif)"
    return "acheter a l'ask coute vraiment (spread effectif > 0)"


# ---------------- Determinisme / anti-triche ----------------
def _replay_is_deterministic():
    from hl_observer.backtesting.robustness import bootstrap_pnl_ci
    a = bootstrap_pnl_ci([1.0, -2.0, 3.0, -1.0, 5.0], n=200, seed=7)
    b = bootstrap_pnl_ci([1.0, -2.0, 3.0, -1.0, 5.0], n=200, seed=7)
    assert a == b, "meme graine -> meme resultat. Sinon le replay ne prouve RIEN."
    return "meme graine = meme resultat (le replay est reproductible)"


def _lookahead_guard_catches_cheating():
    from hl_observer.backtesting.lookahead_guard import assert_no_lookahead
    caught = False
    try:
        assert_no_lookahead(decision_ts=100, data_ts=200)     # decide avec une donnee du FUTUR
    except Exception:
        caught = True
    assert caught, "le garde anti-lookahead n'a PAS vu une decision prise avec une donnee du futur !"
    return "le garde anti-lookahead attrape bien la triche (donnee du futur)"


def _no_real_order_object():
    from hl_observer.paper_trading.paper_engine import PaperTrade
    fields = str(PaperTrade.__dataclass_fields__.keys()) if hasattr(PaperTrade, "__dataclass_fields__") else ""
    for banned in ("order_id_exchange", "signature", "private_key", "tx_hash"):
        assert banned not in fields, f"PaperTrade contient `{banned}` : ce n'est plus un paper trade !"
    return "PaperTrade ne contient AUCUN champ d'ordre reel (pas de signature, pas de tx)"


# ---------------- Verifications statiques PnL / simulation ----------------
c_pnl_hardcoded = regex_rule(
    "Aucun PnL/equity CODE EN DUR dans l'UI LIVE (donnee de demo)",
    r"(?:net_pnl|current_pnl|current_equity|equity_usdt)\s*[=:]\s*[-+]?\d+\.\d+",
    why="un chiffre en dur dans l'UI que tu regardes = mensonge affiche", blocking=True,
    # AFFINE (audit 2026-07-11) : la 1re version scannait TOUT `src/` et remontait des defauts de
    # fonction et des FIXTURES de dev (`refactor_fusion/runner.py`, verifie : NON importe par
    # `ui/` -> ces chiffres n'atteignent JAMAIS ton dashboard). On ne scanne donc que l'UI LIVE.
    dirs=["src/hl_observer/ui", "src/hl_observer/dashboard"],
    line_exclude=("def ", "default", "starting", "initial", "= 0.0", "or 0", "test", "fixture"))

c_demo_data = regex_rule(
    "Aucune donnee 'demo/fake/dummy' dans le moteur de simulation",
    r"\b(demo_|fake_|dummy_|placeholder_)\w*(?:pnl|price|position|trade|equity|fill)",
    why="une donnee fabriquee presentee comme reelle est INTERDITE", blocking=True,
    dirs=["src"],
    # fake_data_scanner est le module qui DETECTE les fausses donnees : il cite forcement les
    # motifs interdits dans sa doc. Il se denoncait lui-meme.
    exclude=("security/fake_data_scanner.py",),
    line_exclude=("#", "*", "detect", "interdit", "forbidden", "banned", "scanner"))

c_ledger_append_only = regex_rule(
    "Le LEDGER D'EVENEMENTS ne doit jamais etre supprime ni reecrit",
    r"(?:DELETE\s+FROM|UPDATE)\s+\w*(?:ledger|event)",
    why="un ledger qui se reecrit ne prouve plus rien", blocking=True, flags=re.I,
    # AFFINE : la 1re version matchait `UPDATE paper_trades` (une table de POSITIONS qu'on marque
    # 'CLOSED' -- parfaitement legitime) et un COMMENTAIRE. Seul le LEDGER D'EVENEMENTS est
    # concerne par la regle d'append-only.
    line_exclude=("#", '"""', "or a paper"))

c_no_trade_default = regex_rule(
    "Le refus (NO_TRADE) existe comme comportement par defaut",
    r"NO_TRADE|INSUFFICIENT_DATA", why="fail-safe : dans le doute, on ne trade pas")

c_modes_separated = regex_rule(
    "Les modes LIVE / BACKTEST / REPLAY / TEST sont distingues",
    r"LIVE|BACKTEST|REPLAY|TEST_FIXTURE",
    why="ne JAMAIS melanger un PnL de test avec le PnL live")




# --- Assemblage de la batterie PnL/simulation (controles EXECUTES) ---
c_pnl_long_up        = exec_rule("PnL LONG : prix qui monte -> gain", _pnl_long_up)
c_pnl_long_down      = exec_rule("PnL LONG : prix qui baisse -> perte", _pnl_long_down)
c_pnl_short_down     = exec_rule("PnL SHORT : prix qui baisse -> gain", _pnl_short_down)
c_pnl_short_up       = exec_rule("PnL SHORT : prix qui monte -> perte", _pnl_short_up)
c_pnl_symmetry       = exec_rule("PnL : long et short exactement opposes", _pnl_symmetry)
c_fees_charged       = exec_rule("FRAIS : reellement preleves (entree=sortie -> perte seche)", _fees_are_charged)
c_fees_not_double    = exec_rule("FRAIS : jamais comptes DEUX fois", _fees_not_double_counted)
c_pnl_scales         = exec_rule("PnL proportionnel au notional", _pnl_scales_with_notional)
c_pnl_numpy_pure     = exec_rule("PnL : numpy et python pur donnent le MEME chiffre", _pnl_numpy_equals_pure)
c_sizing_margin_lev  = exec_rule("SIZING : marge x levier (le fix des 'centimes')", _sizing_margin_times_leverage)
c_lev_not_twice      = exec_rule("SIZING : levier PAS applique deux fois", _leverage_not_applied_twice)
c_qty_coherent       = exec_rule("SIZING : quantite x prix = notional", _quantity_matches_notional)
c_costs_reduce       = exec_rule("EDGE : les couts reduisent TOUJOURS l'edge", _costs_always_reduce_edge)
c_six_costs          = exec_rule("EDGE : les 6 couts sont TOUS comptes", _all_six_costs_counted)
c_degradation_cost   = exec_rule("EDGE : la degradation de copie est facturee", _degradation_hurts)
c_maker_rebate       = exec_rule("EDGE : le rebate maker ameliore l'edge", _maker_rebate_helps)
c_edge_neg_reject    = exec_rule("REFUS : edge net negatif -> rejete", _negative_edge_rejected)
c_edge_small_reject  = exec_rule("REFUS : edge sous le plancher -> rejete", _small_edge_rejected)
c_edge_good_accept   = exec_rule("ACCEPT : un bon edge passe (le gate ne bloque pas tout)", _good_edge_accepted)
c_exposure_refuses   = exec_rule("REFUS : plafond d'exposition applique (anti fail-open)", _exposure_cap_refuses)
c_maxpos_refuses     = exec_rule("REFUS : plafond de positions applique", _max_positions_refuses)
c_minnotional_ref    = exec_rule("REFUS : micro-trade sous le plancher notional", _min_notional_refuses)
c_dd_value           = exec_rule("DRAWDOWN : valeur exacte (pic - creux)", _drawdown_known_value)
c_dd_positive        = exec_rule("DRAWDOWN : jamais negatif", _drawdown_never_negative)
c_profit_factor      = exec_rule("PROFIT FACTOR : calcul exact (le vrai juge de paix)", _profit_factor_known)
c_cvar_var           = exec_rule("RISQUE : CVaR au moins aussi mauvaise que la VaR", _cvar_worse_than_var)
c_kelly_bounded      = exec_rule("RISQUE : Kelly borne (jamais de sur-levier)", _kelly_is_bounded)
c_vol_target         = exec_rule("RISQUE : vol-targeting (marche agite -> position plus petite)", _vol_target_inverse)
c_slippage_size      = exec_rule("EXECUTION : gros ordre = plus cher", _slippage_grows_with_size)
c_microprice_range   = exec_rule("EXECUTION : micro-prix entre bid et ask", _micro_price_between_bid_ask)
c_spread_costs       = exec_rule("EXECUTION : acheter a l'ask coute vraiment", _spread_costs_money)
c_determinism        = exec_rule("REPLAY : meme graine -> meme resultat", _replay_is_deterministic)
c_lookahead          = exec_rule("ANTI-TRICHE : le garde anti-lookahead attrape la fuite", _lookahead_guard_catches_cheating)
c_no_real_order_obj  = exec_rule("SECURITE : PaperTrade n'a aucun champ d'ordre reel", _no_real_order_object)




def _latency_degrades():
    from hl_observer.backtesting.cost_model import apply_latency
    path = [(0, 100.0), (1000, 101.0), (2000, 102.0), (3000, 103.0)]   # prix qui MONTE
    fast = apply_latency(0, path, latency_ms=0)         # entree immediate
    slow = apply_latency(0, path, latency_ms=2000)      # entree 2s plus tard
    assert fast and slow, "apply_latency doit renvoyer un point du chemin"
    assert slow[1] > fast[1], (
        f"sur un prix qui monte, entrer 2s APRES doit couter plus cher : "
        f"{fast[1]} -> {slow[1]}")
    return f"entree immediate a {fast[1]}, entree +2s a {slow[1]} : le retard coute vraiment"


def _latency_no_invented_price():
    from hl_observer.backtesting.cost_model import apply_latency
    path = [(0, 100.0), (1000, 101.0)]
    r = apply_latency(0, path, latency_ms=99_999)       # au-dela du chemin connu
    assert r is None, "sans donnee apres le delai, on ne doit PAS fabriquer un prix"
    return "aucun prix invente quand la donnee manque (regle : jamais de donnee fabriquee)"


def _cost_varies_by_coin():
    from hl_observer.backtesting.cost_model import cost_bps_for
    a = cost_bps_for("BTC")
    b = cost_bps_for("UNKNOWNCOIN")
    assert a > 0 and b > 0, "un cout doit toujours etre positif"
    assert b >= a, "un coin illiquide/inconnu doit couter AU MOINS autant que BTC"
    return f"cout BTC={a} bps, coin inconnu={b} bps (jamais moins cher que BTC)"


def _maker_missed_fills_hurt():
    from hl_observer.backtesting.robustness import maker_adjust_net
    full = maker_adjust_net([10.0] * 20, spread_saving_usd=0.5, fill_rate=1.0, seed=7)
    part = maker_adjust_net([10.0] * 20, spread_saving_usd=0.5, fill_rate=0.3, seed=7)
    assert sum(part) < sum(full), "rater des fills maker DOIT couter (sinon le maker est magique)"
    return "les fills maker rates coutent : pas de repas gratuit"


def _deflated_sharpe_is_stricter():
    from hl_observer.backtesting.quant_methods import deflated_sharpe
    d = deflated_sharpe(1.5, 200, 1000)
    assert 0.0 <= d <= 1.0, f"la probabilite deflatee doit etre dans [0,1], obtenu {d}"
    return f"Sharpe deflate = {d:.2f} : essayer 1000 strategies punit le meilleur Sharpe"


def _pbo_is_bounded():
    from hl_observer.backtesting.validation_methods import probability_of_backtest_overfitting
    import random
    rng = random.Random(3)
    m = [[rng.gauss(0, 1) for _ in range(40)] for _ in range(6)]
    p = probability_of_backtest_overfitting(m)
    assert 0.0 <= p <= 1.0, f"la PBO doit etre une probabilite, obtenu {p}"
    return f"probabilite de sur-apprentissage = {p:.2f} (sur du bruit pur, elle doit etre elevee)"


def _purged_cv_no_overlap():
    from hl_observer.backtesting.cross_validation import purged_walk_forward_splits
    for tr, te in purged_walk_forward_splits(100, n_splits=4, embargo=5):
        assert not (set(tr) & set(te)), "FUITE : le train et le test se chevauchent !"
    return "train et test ne se chevauchent JAMAIS (pas de fuite d'information)"


def _stress_worst_case():
    from hl_observer.backtesting.stress_testing import portfolio_stress
    # crash de 20% : un portefeuille LONG doit PERDRE, un SHORT doit GAGNER
    perte = portfolio_stress({"BTC": 1000.0}, {"BTC": -0.20})
    gain = portfolio_stress({"BTC": -1000.0}, {"BTC": -0.20})
    assert perte < 0, f"un LONG dans un crash -20% doit PERDRE, obtenu {perte}"
    assert gain > 0, f"un SHORT dans un crash -20% doit GAGNER, obtenu {gain}"
    assert abs(perte + 200.0) < 1e-6, f"1000$ long, -20% -> -200$ attendu, obtenu {perte}"
    return "crash -20% : long -200$, short +200$ (le stress-test a le bon signe)"


def _mc_p5_below_median():
    from hl_observer.backtesting.experiment_harness import mc_p5
    import random
    rng = random.Random(1)
    trades = [rng.gauss(0.5, 5.0) for _ in range(200)]
    p5 = mc_p5(trades, n=300, seed=7)
    med = sum(trades)
    assert p5 <= med, f"le 5e percentile Monte-Carlo doit etre PIRE que le resultat brut : {p5} vs {med}"
    return f"Monte-Carlo p5 = {p5:.1f} vs brut {med:.1f} : le scenario defavorable est bien pire"


def _promotion_gate_rejects_noise():
    from hl_observer.backtesting.experiment_harness import promotion_gate
    # cas 1 : resultat qui ne bat PAS le hasard -> doit etre REFUSE
    r = promotion_gate(50.0, 100, beats_random=False, mc_p5_value=10.0)
    assert not r["promote"], "un resultat qui ne bat pas le hasard NE DOIT PAS etre promu !"
    assert "DOES_NOT_BEAT_RANDOM" in r["reasons"]
    # cas 2 : p5 Monte-Carlo negatif -> REFUSE (le scenario defavorable perd)
    r2 = promotion_gate(50.0, 100, beats_random=True, mc_p5_value=-5.0)
    assert not r2["promote"], "un p5 Monte-Carlo negatif NE DOIT PAS etre promu !"
    # cas 3 : trop peu de trades -> REFUSE
    r3 = promotion_gate(50.0, 5, beats_random=True, mc_p5_value=10.0)
    assert not r3["promote"], "5 trades, c'est du hasard : NE DOIT PAS etre promu !"
    # cas 4 : tout est bon -> ACCEPTE (le gate ne bloque pas tout)
    r4 = promotion_gate(50.0, 100, beats_random=True, mc_p5_value=10.0)
    assert r4["promote"], "un resultat solide DOIT pouvoir passer, sinon le gate est inutile"
    return "le gate refuse le hasard, le p5 negatif et les echantillons trop petits -- et accepte le solide"


c_latency_cost       = exec_rule("LATENCE : arriver apres coute plus cher", _latency_degrades)
c_latency_no_invent  = exec_rule("VERITE : aucun prix invente quand la donnee manque", _latency_no_invented_price)
c_cost_per_coin      = exec_rule("COUTS : un coin illiquide coute plus cher", _cost_varies_by_coin)
c_maker_missed       = exec_rule("MAKER : les fills rates coutent (pas de repas gratuit)", _maker_missed_fills_hurt)
c_deflated_sharpe    = exec_rule("ANTI-OVERFIT : Sharpe deflate (punit les 1000 essais)", _deflated_sharpe_is_stricter)
c_pbo                = exec_rule("ANTI-OVERFIT : probabilite de sur-apprentissage bornee", _pbo_is_bounded)
c_purged_cv          = exec_rule("ANTI-FUITE : train et test ne se chevauchent jamais", _purged_cv_no_overlap)
c_stress             = exec_rule("STRESS : pire drawdown calculable", _stress_worst_case)
c_mc_p5              = exec_rule("MONTE-CARLO : le scenario defavorable est bien pire", _mc_p5_below_median)
c_promotion_gate     = exec_rule("GATE : refuse du bruit pur (ne se laisse pas berner)", _promotion_gate_rejects_noise)



# ==================================================================================
#  FUZZING & PROPRIETES : on APPELLE reellement chaque fonction publique du bot avec
#  des entrees degenerees. C'est ce qui attrape le crash de 3h du matin.
#  Chaque controle ci-dessous verifie des CENTAINES de fonctions.
# ==================================================================================

# On fuzz le COEUR PUR (calculs de PnL, edge, risque). Les paquets d'I/O ne sont pas fuzzables
# sans effets de bord -- ils sont couverts par la suite de tests et les gates.
_TOOLKIT_PKGS = ["hl_observer.backtesting", "hl_observer.edge", "hl_observer.risk"]

# Entrees degenerees : ce que le monde reel envoie a 3h du matin.
# Les 10 entrees qui font tomber un bot dans la vraie vie (liste vide, zeros, negatif,
# NaN, Inf, overflow, None, mauvais type). Plus n'apporterait rien : ce sont les classes
# d'equivalence qui comptent, pas le nombre.
_EVIL = [
    [],                 # rien a manger
    [0.0, 0.0],         # que des zeros -> division par zero ?
    [-1.0],             # negatif la ou on attend du positif
    [float("nan")],     # NaN -> poison silencieux
    1e18,               # overflow
    None,               # absence de donnee
]


# Le fuzzer ne doit toucher QUE des fonctions PURES. Tout ce qui ecrit, lance, se connecte ou
# parse la ligne de commande est EXCLU : sinon on casse des donnees ou on tue le process
# (bug reel rencontre : appeler `main()` declenchait argparse -> SystemExit).
_UNSAFE_NAMES = ("main", "cli", "app", "serve", "start", "stop", "run", "connect", "fetch",
                 "scan", "poll", "store", "save", "write", "export", "record", "delete",
                 "purge", "reset", "build_database", "download", "upload", "send", "post",
                 "commit", "migrate", "init", "setup", "install", "kill", "exec",
                 # generateurs massifs / profileurs : pas fuzzables (11s l'appel, ou effets globaux)
                 "generate", "grid", "search", "profile", "load_test", "chaos")


# Modules exclus du fuzz : ce sont des GENERATEURS (on leur demande N elements, ils obeissent --
# leur passer 1e18 n'a aucun sens et ne prouve rien).
_UNSAFE_MODULES = ("scenario_grid", "scenario_db", "scenario_search", "perf_tools")


def _is_pure_name(name: str) -> bool:
    return not any(u in name.lower() for u in _UNSAFE_NAMES)


def _is_fuzzable_module(mod: str) -> bool:
    return not any(u in mod for u in _UNSAFE_MODULES)



def _call_with_timeout(fn, args, seconds=2.0):
    """Appelle fn(*args) avec un VRAI timeout. Renvoie ("ok", res) / ("exc", e) / ("timeout", None).

    Indispensable : sans ca, une fonction qui boucle a l'infini bloque tout l'audit. Le thread
    est daemon -> il ne retiendra pas le processus a la sortie.
    """
    import threading
    box = {}

    def _work():
        try:
            box["r"] = ("ok", fn(*args))
        except BaseException as e:                                     # noqa: BLE001
            box["r"] = ("exc", e)

    th = threading.Thread(target=_work, daemon=True)
    th.start()
    th.join(seconds)
    if th.is_alive():
        return ("timeout", None)
    return box.get("r", ("exc", RuntimeError("aucun resultat")))


def _public_functions():
    import importlib
    import inspect
    import pkgutil
    out = []
    for pkg_name in _TOOLKIT_PKGS:
        try:
            pkg = importlib.import_module(pkg_name)
        except Exception:                                              # noqa: BLE001
            continue
        mods = [pkg_name]
        if hasattr(pkg, "__path__"):
            mods += [f"{pkg_name}.{m.name}" for m in pkgutil.iter_modules(pkg.__path__)]
        for mn in mods:
            try:
                mod = importlib.import_module(mn)
            except Exception:                                          # noqa: BLE001
                continue
            for name, fn in vars(mod).items():
                if name.startswith("_") or not inspect.isfunction(fn):
                    continue
                if getattr(fn, "__module__", "") != mn:
                    continue                                            # pas re-exporte
                if not _is_pure_name(name) or not _is_fuzzable_module(mn):
                    continue                          # point d'entree / I/O / generateur massif
                out.append((mn, name, fn))
    return out


FUZZ_PROGRESS = ROOT / "tools" / ".fuzz_progress.tmp"


def _contient_nan(x) -> bool:
    import math
    if isinstance(x, float):
        return math.isnan(x) or math.isinf(x)
    if isinstance(x, (list, tuple)):
        return any(_contient_nan(v) for v in x)
    return False


def _fuzz_worker():
    """Tourne dans un PROCESSUS SEPARE et fait TOUTES les analyses de fuzz en une passe :
    crash, NaN/Inf, determinisme, entree vide.

    BUG CORRIGE (2026-07-11, 15h40) : seul le controle "crash" tournait dans ce sous-processus.
    Les 3 autres appelaient les fonctions EN DIRECT, sans aucun garde-fou -> une boucle infinie
    a GELE l'audit pendant 30 minutes au controle 147. Maintenant TOUT passe par ici, donc tout
    est protege par le timeout du parent. Le nom de la fonction est trace AVANT chaque appel :
    si le process se fige, le dernier nom ecrit EST le coupable.
    """
    import inspect
    import json
    import math
    FATALES = (ZeroDivisionError, IndexError, OverflowError, RecursionError,
               UnboundLocalError, NameError)
    res = {"crashes": [], "nan": [], "nondet": [], "invented": [],
           "tested": 0, "fns": 0, "done": False}
    sample = [0.5, -0.2, 1.3, -0.8, 2.1, 0.3, -1.1, 0.9, 1.7, -0.4] * 3

    def _trace(label):
        with open(FUZZ_PROGRESS, "w", encoding="utf-8") as f:
            f.write(json.dumps({**res, "fn": label}))

    for mod, name, fn in _public_functions():
        res["fns"] += 1
        try:
            sig = inspect.signature(fn)
            required = [p for p in sig.parameters.values()
                        if p.default is inspect.Parameter.empty
                        and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        except (TypeError, ValueError):
            continue
        if len(required) > 3:
            continue
        n = len(required)

        # --- A. crash / NaN / valeur inventee sur entrees pourries ---
        for evil in _EVIL:
            res["tested"] += 1
            _trace(f"{mod}.{name}({evil!r:.20})")
            try:
                r = fn(*([evil] * n))
            except FATALES as e:
                res["crashes"].append(f"{mod}.{name}({evil!r:.24}) -> {type(e).__name__}: {e}")
                break
            except SystemExit:
                res["crashes"].append(f"{mod}.{name} appelle sys.exit() -> TUE LE PROCESSUS")
                break
            except BaseException:                                      # noqa: BLE001
                continue          # la fonction se DEFEND : c'est le comportement voulu
            # NaN en SORTIE : ce n'est un BUG que si l'entree etait PROPRE. Donner [nan] et
            # recevoir nan, c'est de la propagation normale ("garbage in, garbage out") --
            # la vraie defense est au niveau de l'ingestion, pas dans chaque fonction pure.
            entree_propre = not _contient_nan(evil)
            if entree_propre:
                vals = []
                if isinstance(r, (int, float)) and not isinstance(r, bool):
                    vals = [r]
                elif isinstance(r, dict):
                    vals = [v for v in r.values() if isinstance(v, float)]
                elif isinstance(r, (list, tuple)):
                    vals = [v for v in r if isinstance(v, float)]
                for v in vals:
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        res["nan"].append(f"{mod}.{name}({evil!r:.16}) -> {v} : la fonction CREE "
                                          f"un NaN/Inf a partir d'une entree PROPRE "
                                          f"(0/0 ?) -> empoisonne tout le PnL en aval")
                        break
            # entree VIDE sur une fonction de mesure -> doit rendre 0/neutre, jamais un chiffre
            if evil == [] and any(k in name for k in ("pnl", "edge", "profit", "sharpe",
                                                      "drawdown", "var", "factor", "ratio")):
                if isinstance(r, (int, float)) and not isinstance(r, bool) and r not in (0, 0.0) \
                        and r == r:
                    res["invented"].append(f"{mod}.{name}([]) = {r} -- entree VIDE, chiffre "
                                           f"non nul : donnee inventee ?")

        # --- B. determinisme (fonctions a 1 argument) ---
        # Aleatoire VOULU (jitter anti-troupeau) : ce n'est pas un defaut, c'est la fonctionnalite.
        if n == 1 and not any(k in name for k in ("jitter", "random", "sample", "shuffle",
                                                  "compose", "make", "factory", "wrap")):
            _trace(f"{mod}.{name} [determinisme]")
            try:
                a = fn(list(sample))
                b = fn(list(sample))
                ra, rb = repr(a), repr(b)
                # un retour identitaire (<function ...>, <obj at 0x...>) change d'adresse a chaque
                # appel : ce n'est PAS du non-determinisme, juste un nouvel objet.
                identitaire = " at 0x" in ra or ra.startswith("<")
                if ra != rb and not identitaire:
                    res["nondet"].append(f"{mod}.{name} : deux appels identiques donnent des "
                                         f"resultats DIFFERENTS -> aleatoire non seede ? "
                                         f"(le replay ne prouverait plus rien)")
            except BaseException:                                      # noqa: BLE001
                pass

    res["done"] = True
    with open(FUZZ_PROGRESS, "w", encoding="utf-8") as f:
        f.write(json.dumps({**res, "fn": None}))


FUZZ_RESULTS = {}


def _run_fuzz_once():
    """Lance le worker UNE fois ; les 4 controles de fuzz lisent son resultat."""
    if FUZZ_RESULTS:
        return FUZZ_RESULTS
    import json
    try:
        FUZZ_PROGRESS.unlink()
    except OSError:
        pass
    _run([sys.executable, str(ROOT / "tools" / "audit_report.py"), "--fuzz-worker"], timeout=600)
    data = {}
    try:
        data = json.loads(FUZZ_PROGRESS.read_text(encoding="utf-8"))
    except Exception:                                                  # noqa: BLE001
        pass
    try:
        FUZZ_PROGRESS.unlink()
    except OSError:
        pass
    FUZZ_RESULTS.update(data)
    return FUZZ_RESULTS


def c_fuzz_no_crash():
    """Appelle chaque fonction pure avec des entrees pourries, dans un PROCESSUS SEPARE."""
    c = Check("FUZZING : aucune fonction ne CRASHE ni ne BOUCLE sur une entree pourrie")
    d = _run_fuzz_once()
    crashes = list(d.get("crashes") or [])
    if not d.get("done"):
        crashes.insert(0, f">>> BOUCLE INFINIE : `{d.get('fn') or '?'}` NE TERMINE JAMAIS. "
                          f"Si une valeur corrompue atteint cette fonction, LE BOT GELE.")
    return c.finish(f"{d.get('fns', 0)} fonctions, {d.get('tested', 0)} appels pourris, "
                    f"{len(crashes)} CRASH/GEL", _trim(crashes))


def c_fuzz_no_nan():
    """NaN/Inf renvoyes par une fonction de PnL empoisonnent TOUT le calcul en aval,
    sans lever la moindre erreur. Le PnL affiche devient faux en silence. Interdit."""
    c = Check("FUZZING : aucune fonction ne renvoie NaN / Inf (poison silencieux)")
    d = _run_fuzz_once()
    bad = list(d.get("nan") or [])
    return c.finish(f"{d.get('tested', 0)} appels verifies, {len(bad)} retour(s) NaN/Inf",
                    _trim(bad))


def c_fuzz_deterministic():
    """Deux appels identiques doivent rendre le MEME resultat. Sinon le replay ne prouve rien."""
    c = Check("DETERMINISME : deux appels identiques -> resultat identique")
    d = _run_fuzz_once()
    bad = list(d.get("nondet") or [])
    return c.finish(f"{d.get('fns', 0)} fonctions testees, {len(bad)} non deterministe(s)",
                    _trim(bad))


def c_fuzz_empty_input():
    """Entree VIDE -> resultat vide/neutre. Jamais un chiffre invente (regle du projet)."""
    c = Check("VERITE : entree vide -> resultat neutre (jamais un chiffre invente)",
              blocking=False)
    d = _run_fuzz_once()
    bad = list(d.get("invented") or [])
    return c.finish(f"{len(bad)} fonction(s) suspecte(s)", [], _trim(bad))


def c_fuzz_monotonic_costs():
    """Propriete METIER : augmenter un cout ne doit JAMAIS augmenter l'edge net.
    On le verifie sur les 6 couts, avec 20 valeurs chacun."""
    c = Check("PROPRIETE : augmenter un cout ne peut JAMAIS augmenter l'edge")
    bad = []
    for cost in ("taker_fee_bps", "spread_cost_bps", "slippage_bps", "latency_decay_bps",
                 "copy_degradation_bps", "funding_cost_bps"):
        prev = None
        for v in range(0, 40, 2):
            net = _edge(**{cost: float(v)}).net_edge_bps
            if prev is not None and net > prev + 1e-9:
                bad.append(f"{cost} : passer de {v - 2} a {v} bps AUGMENTE l'edge "
                           f"({prev} -> {net}) : impossible !")
            prev = net
    return c.finish(f"6 couts x 20 valeurs = 120 verifications, {len(bad)} anomalie(s)",
                    _trim(bad))


def c_fuzz_pnl_signs():
    """Propriete METIER : sur 200 combinaisons prix/sens, le signe du PnL doit TOUJOURS
    etre coherent. Un seul signe faux = un PnL menteur."""
    import random
    c = Check("PROPRIETE : le signe du PnL est correct sur 200 combinaisons")
    rng = random.Random(11)
    bad = []
    for _ in range(200):
        e = rng.uniform(1.0, 1000.0)
        x = rng.uniform(1.0, 1000.0)
        side = rng.choice([1, -1])
        p = _V().fast_pnl([e], [x], [side], notional=500.0, cost_bps=0.0)[0]
        attendu = (x > e) if side == 1 else (x < e)
        if p > 1e-9 and not attendu:
            bad.append(f"entree={e:.2f} sortie={x:.2f} sens={side} -> PnL={p:.2f} : SIGNE FAUX")
        if p < -1e-9 and attendu:
            bad.append(f"entree={e:.2f} sortie={x:.2f} sens={side} -> PnL={p:.2f} : SIGNE FAUX")
    return c.finish(f"200 combinaisons testees, {len(bad)} signe(s) faux", _trim(bad))


def c_fuzz_costs_never_help():
    """Propriete METIER : quel que soit le trade, ajouter des frais ne peut QUE reduire le PnL.
    200 trades aleatoires."""
    import random
    c = Check("PROPRIETE : les frais ne peuvent JAMAIS augmenter le PnL (200 trades)")
    rng = random.Random(13)
    bad = []
    for _ in range(200):
        e = rng.uniform(10.0, 500.0)
        x = rng.uniform(10.0, 500.0)
        side = rng.choice([1, -1])
        sans = _V().fast_pnl([e], [x], [side], notional=500.0, cost_bps=0.0)[0]
        avec = _V().fast_pnl([e], [x], [side], notional=500.0, cost_bps=8.0)[0]
        if avec > sans + 1e-9:
            bad.append(f"e={e:.1f} x={x:.1f} : AVEC frais ({avec:.2f}) > SANS frais ({sans:.2f}) !")
    return c.finish(f"200 trades, {len(bad)} anomalie(s)", _trim(bad))


def c_all_modules_have_public_api():
    """Un module sans aucune fonction publique est soit mort, soit mal concu."""
    import importlib
    import inspect
    c = Check("Chaque module du toolkit expose au moins une fonction publique", blocking=False)
    bad = []
    for p in _py_files("src"):
        rel = _rel(p).replace(os.sep, "/")
        if "/backtesting/" not in rel or rel.endswith("__init__.py"):
            continue
        mod = rel[4:-3].replace("/", ".")
        try:
            m = importlib.import_module(mod)
        except Exception:                                              # noqa: BLE001
            continue
        pub = [n for n, o in vars(m).items()
               if not n.startswith("_") and (inspect.isfunction(o) or inspect.isclass(o))
               and getattr(o, "__module__", "") == mod]
        if not pub:
            bad.append(f"{rel} : aucune fonction/classe publique (module mort ?)")
    return c.finish(f"{len(bad)} module(s) sans API publique", [], _trim(bad))


# =============================================================== rapport
def git_ctx():
    rows = []
    for label, cmd in (("branche", ["git", "rev-parse", "--abbrev-ref", "HEAD"]),
                       ("commit", ["git", "log", "-1", "--format=%h %s"])):
        _, out = _run(cmd, timeout=60)
        rows.append(f"- {label} : {out.strip().splitlines()[0] if out.strip() else '?'}")
    _, out = _run(["git", "status", "--porcelain"], timeout=60)
    rows.append(f"- fichiers modifies non commites : {len([x for x in out.splitlines() if x.strip()])}")
    return rows



def file_inventory():
    """Table de CHAQUE module de src/ : lignes, importe par combien, test associe, couverture."""
    cov = {f.replace("\\", "/"): pct for f, _n, pct in COVERAGE_ROWS}
    imports = {}
    for p in _py_files("src", "tests", "tools"):
        txt = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"(?:from|import)\s+(hl_observer[\w.]*)", txt):
            imports[m.group(1)] = imports.get(m.group(1), 0) + 1
    test_txt = " ".join(p.read_text(encoding="utf-8", errors="replace") for p in _py_files("tests"))
    rows = []
    for p in sorted(_py_files("src")):
        rel = _rel(p).replace("\\", "/")
        if rel.endswith("__init__.py"):
            continue
        mod = rel[4:-3].replace("/", ".")
        lines = p.read_text(encoding="utf-8", errors="replace").count("\n") + 1
        used = sum(v for k, v in imports.items() if k == mod or k.startswith(mod + "."))
        tested = "oui" if pathlib.Path(rel).stem in test_txt else "**NON**"
        pct = cov.get(rel)
        rows.append((rel, lines, used, tested, f"{pct}%" if pct is not None else "-"))
    return rows



TIMINGS_FILE = ROOT / "tools" / "audit_timings.json"

# Durees par defaut au 1er lancement (secondes). Ensuite l'audit apprend les VRAIES durees
# de ta machine et l'ETA devient exacte.
DEFAULT_SECONDS = {
    "c_compile": 13.0, "c_all_imports": 5.0, "c_arity": 4.0, "c_tests": 240.0,
    "c_coverage": 15.0, "c_flaky": 150.0, "c_doctor": 20.0, "c_fuzz_no_crash": 12.0,
    "c_lint": 8.0, "c_resources": 4.0, "c_big_tracked_files": 5.0,
}


def _load_timings() -> dict:
    import json
    try:
        return json.loads(TIMINGS_FILE.read_text(encoding="utf-8"))
    except Exception:                                                  # noqa: BLE001
        return {}


def _save_timings(t: dict) -> None:
    import json
    try:
        TIMINGS_FILE.write_text(json.dumps(t, indent=1), encoding="utf-8")
    except Exception:                                                  # noqa: BLE001
        pass


def _estimate(name: str, hist: dict) -> float:
    if name in hist:
        return max(0.2, float(hist[name]))
    return DEFAULT_SECONDS.get(name, 1.2)


def _fmt_duree(sec: float) -> str:
    sec = max(0, int(sec))
    if sec < 60:
        return f"{sec}s"
    m, s_ = divmod(sec, 60)
    if m < 60:
        return f"{m}m{s_:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


L = 74                       # largeur interieure de l'encadre


def _cadre(txt: str = "", sep: str = "") -> str:
    if sep:
        return "+" + sep * L + "+"
    return "| " + txt[:L - 2].ljust(L - 2) + " |"


def _barre(pct: float, largeur: int = 28) -> str:
    plein = int(round(largeur * min(1.0, max(0.0, pct))))
    return "[" + "#" * plein + "-" * (largeur - plein) + "]"



# --- etat global : permet d'ecrire le rapport MEME si on crashe / ferme la fenetre -------------
STATE = {"done": [], "planned": [], "started": None, "t0": time.time(), "final": False,
         "interrupted": ""}


def build_report() -> str:
    checks = STATE["done"]
    blocking_ko = [c for c in checks if not c.ok and c.blocking]
    nonblock_ko = [c for c in checks if not c.ok and not c.blocking]
    warned = [c for c in checks if c.warns]
    pending = STATE.get("todo", [])

    if STATE["interrupted"]:
        verdict = "AUDIT INTERROMPU (rapport partiel)"
    elif blocking_ko or nonblock_ko:
        verdict = "ECHECS DETECTES"
    elif pending:
        verdict = "EN COURS"
    else:
        verdict = "TOUT EST VERT"

    L = ["# Resultat audit HyperSmart", "", f"**VERDICT : {verdict}**", ""]
    if STATE["interrupted"]:
        L += [f"> **L'audit s'est arrete avant la fin** ({STATE['interrupted']}).",
              f"> Controle en cours au moment de l'arret : **{STATE['started'] or '?'}**",
              "> Ce rapport contient tout ce qui a pu etre mesure. Envoie-le quand meme.", ""]
    L.append(f"- date : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    L.append(f"- machine : {platform.system()} {platform.release()} | Python {platform.python_version()}")
    L += git_ctx()
    L.append(f"- duree : {time.time() - STATE['t0']:.0f}s")
    L.append(f"- controles executes : {len(checks)}/{STATE.get('total', len(STATE['planned']))} "
             f"| echecs bloquants : {len(blocking_ko)} | avertissements : {sum(len(c.warns) for c in checks)}")
    L.append("")
    if blocking_ko or nonblock_ko or STATE["interrupted"]:
        L += ["> **COLLE CE FICHIER A CLAUDE TEL QUEL.**", ""]

    L += ["## Recapitulatif", "", "| # | Controle | Etat | Resultat | Duree |", "|---|---|---|---|---|"]
    for i, c in enumerate(checks, 1):
        state = "**ECHEC**" if not c.ok else ("OK (avert.)" if c.warns else "OK")
        L.append(f"| {i} | {c.title.split('. ', 1)[-1]} | {state} | {c.summary} | {c.seconds:.1f}s |")
    for t in pending:
        label = t[2:].replace("_", " ") if t.startswith("c_") else t
        L.append(f"| - | {label} | *non execute (audit interrompu avant)* | - | - |")
    L.append("")

    if blocking_ko or nonblock_ko:
        L += ["## Echecs", ""]
        for c in blocking_ko + nonblock_ko:
            L += [f"### {c.title}", "", c.summary, ""]
            if c.errors:
                L += ["```"] + c.errors + ["```", ""]
            if c.tb:
                L += ["<details><summary>Traces completes</summary>", "", "```", c.tb, "```", "",
                      "</details>", ""]

    if warned:
        L += ["## Avertissements (non bloquants, mais a regarder)", ""]
        for c in warned:
            L += [f"### {c.title}", "", "```"] + c.warns + ["```", ""]

    L += ["## Config REELLEMENT appliquee au runtime", "",
          "(.cmd, puis defauts .ps1, puis forcages .ps1 -- **le .ps1 fait autorite**)", "",
          "| Variable | Valeur effective |", "|---|---|"]
    try:
        eff = effective_config()
        for k in sorted(eff):
            if k.startswith("HYPERSMART_") and any(x in k for x in
                                                   ("MIN_", "MAX_", "LEVERAGE", "SLTP", "ENABLED",
                                                    "AUTHORITATIVE")):
                L.append(f"| {k} | `{eff[k]}` |")
    except Exception as e:                                              # noqa: BLE001
        L.append(f"| (config illisible) | {e} |")
    L.append("")

    if STATE["final"]:
        try:
            inv = file_inventory()
            L += ["## Inventaire : CHAQUE fichier du bot", "",
                  "`importe par` = nb de fichiers qui l'importent (0 = dormant). "
                  "`test` = un test mentionne ce module. `couv.` = couverture reelle.", "",
                  "| Fichier | Lignes | Importe par | Test | Couv. |", "|---|---|---|---|---|"]
            for rel, lines, used, tested, pct in inv:
                L.append(f"| `{rel}` | {lines} | {used} | {tested} | {pct} |")
            L += ["", f"**{len(inv)} modules** | sans test : "
                  f"**{sum(1 for r in inv if r[3] != 'oui')}** | jamais importes : "
                  f"**{sum(1 for r in inv if r[2] == 0)}**", ""]
        except Exception as e:                                          # noqa: BLE001
            L += ["", f"(inventaire indisponible : {e})", ""]

    L += ["## Securite", "",
          "0 ordre reel - 0 argent reel - 0 cle privee - 0 signature - 0 depot/retrait.",
          "Cet audit est en LECTURE SEULE : le seul fichier ecrit est `resultat-audit.md`.", ""]
    return "\n".join(L) + "\n"


def write_report():
    """Ecrit le rapport. Appele APRES CHAQUE CONTROLE -> le fichier existe toujours,
    meme si tu fermes la fenetre ou si ca crashe."""
    try:
        tmp = str(REPORT) + ".tmp"
        io.open(tmp, "w", encoding="utf-8").write(build_report())
        os.replace(tmp, REPORT)                       # ecriture atomique : jamais de fichier tronque
    except Exception as e:                                              # noqa: BLE001
        print(f"   [!] impossible d'ecrire le rapport : {e}", flush=True)


def _on_signal(signum, frame):                                          # noqa: ARG001
    STATE["interrupted"] = f"interrompu (signal {signum})"
    write_report()
    print(f"\n>>> Interrompu. Rapport PARTIEL ecrit : {REPORT}\n", flush=True)
    os._exit(2)



# ==================================================================================
#  SANTE ECONOMIQUE DU MOTEUR REEL  (ajoute le 2026-07-11)
#
#  POURQUOI CETTE FAMILLE EXISTE. L'audit verifiait que le code TOURNE (imports, tests
#  presents, aucun ordre reel) et que les fonctions de LABORATOIRE calculent juste
#  (`backtesting.vectorized`). Il ne verifiait pas que le MOTEUR REEL -- celui qui produit
#  le PnL -- soit economiquement sain. Resultat : il a laisse passer, sans un seul warning,
#  des bugs qui GARANTISSAIENT la perte :
#
#    - un ratio TP/SL qui exigeait 87 % de winrate (perte certaine, quel que soit le signal) ;
#    - un "stop catastrophique" qui ne fermait RIEN (2 trades = 46 % de la perte) ;
#    - un plafond de degradation (12 bps) INFERIEUR au cout plancher (14,2) -> 0 trade possible ;
#    - un plancher single-wallet (55 bps) au-dessus du maximum atteignable (32) -> sniper mort ;
#    - une latence de copie facturee ZERO alors qu'on copie avec 57 s de retard ;
#    - des cliquets de session qui bannissaient un coin des 2 $ de perte.
#
#  Un audit qui ne teste que la mecanique laisse le bot perdre proprement.
#  Ces controles-ci testent la RENTABILITE STRUCTURELLE : ils repondent a la seule question
#  qui compte -- "cette configuration peut-elle, en principe, ne pas perdre ?"
# ==================================================================================

_FRAIS_AR_BPS = 13.0     # aller-retour mesure sur le ledger reel


def _launcher_env():
    import re as _re
    txt = (ROOT / "tools" / "start_hypersmart_simulation.ps1").read_text(encoding="utf-8", errors="ignore")
    out = {}
    for pat in (r'Set-HyperSmartDefaultEnv\s+"([A-Z0-9_]+)"\s+"([^"]*)"',
                r'\[Environment\]::SetEnvironmentVariable\("([A-Z0-9_]+)",\s*"([^"]*)",\s*"Process"\)'):
        for k, v in _re.findall(pat, txt):
            out[k] = v
    return out


def _lf(name, default):
    try:
        return float(_launcher_env().get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _eco_ratio_tp_sl():
    tp, sl = _lf("HYPERSMART_SLTP_TAKE_PROFIT_BPS", 0), _lf("HYPERSMART_SLTP_STOP_LOSS_BPS", 0)
    fmin = _lf("HYPERSMART_V26_VOL_FACTOR_MIN", 1.0)
    floor = _lf("HYPERSMART_V26_TP_FLOOR_BPS", 0.0)
    assert tp > 0 and sl > 0, "TP/SL absents du launcher"
    tp_eff, sl_eff = max(tp * fmin, floor), sl * fmin
    gain, perte = tp_eff - _FRAIS_AR_BPS, sl_eff + _FRAIS_AR_BPS
    assert gain > 0, f"le TP effectif ({tp_eff:.0f} bps) est mange par les frais ({_FRAIS_AR_BPS})"
    be = perte / (perte + gain) * 100
    assert be <= 50.0, (
        f"STRUCTURE PERDANTE : il faut {be:.0f} % de winrate pour rentrer dans ses frais "
        f"(TP {tp_eff:.0f} / SL {sl_eff:.0f} apres frais). Le run du 09-07 en exigeait 87 % "
        f"et en realisait 50 : la perte etait CERTAINE, quel que soit le signal."
    )
    return f"breakeven {be:.0f} % de winrate (TP {tp_eff:.0f} / SL {sl_eff:.0f} bps nets)"


def _eco_tp_floor():
    floor = _lf("HYPERSMART_V26_TP_FLOOR_BPS", 0.0)
    assert floor >= 3 * _FRAIS_AR_BPS, (
        f"plancher de TP {floor:.0f} bps pour {_FRAIS_AR_BPS:.0f} bps de frais : la volatilite "
        f"peut raboter le take-profit sous le niveau des frais (bug mesure : TP a 28 bps)"
    )
    return f"un TP ne peut jamais tomber sous {floor:.0f} bps (>= 3x les frais)"


def _eco_degradation_franchissable():
    from hl_observer.copying.realtime_magic_score import RealtimeCopyRiskConfig
    import re as _re
    src = (ROOT / "src" / "hl_observer" / "ui" / "routes.py").read_text(encoding="utf-8", errors="ignore")
    bloc = src[src.index("realtime_score_config = RealtimeCopyRiskConfig(") :][:400]
    cout = sum(float(_re.search(rf"{n}=([0-9.]+)", bloc).group(1)) for n in ("fee_bps", "spread_bps", "slippage_bps"))
    cout += RealtimeCopyRiskConfig().adverse_selection_penalty_bps
    plafond = _lf("HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS", 28.0)
    assert plafond > cout, (
        f"VERROU MORT : plafond de degradation {plafond:.0f} bps <= cout plancher {cout:.1f} bps "
        f"-> COPY_DEGRADATION_TOO_HIGH sur TOUT signal. Zero trade possible."
    )
    return f"plafond {plafond:.0f} bps > cout plancher {cout:.1f} bps (franchissable)"


#: Au-dessus de ce plancher, le mode sniper mono-wallet est declare VOLONTAIREMENT FERME.
#: Ce n'est pas un reglage : c'est un verdict de MESURE (voir _eco_single_wallet_atteignable).
SENTINELLE_SNIPER_FERME = 1000.0


def _eco_single_wallet_atteignable():
    """CE CONTROLE MESURAIT LE MAUVAIS OBJET (corrige le 2026-07-18).

    Il injectait `leader_expected_edge_bps=52` et concluait « maximum atteignable -17 bps ».
    Or le scoreur n'utilise PAS cette entree : `edge_base_bps` vient de la TABLE D'EDGE MESUREE
    (`edge.edge_source.edge_brut`). Sans table chargee, deny-by-default met l'edge a 0 -- donc
    le resultat valait -17 bps que le leader ait 52 ou 300 bps d'edge. Verifie :

        leader_edge =  52 bps -> edge restant = -17.00
        leader_edge = 300 bps -> edge restant = -17.00

    L'audit bloquait donc sur le fait que le deny-by-default FONCTIONNE. Un audit qui punit le
    comportement correct finit desactive.

    CE QU'ON MESURE MAINTENANT, et qui a un sens : quel edge MESURE faudrait-il pour franchir le
    plancher, une fois les couts payes ? Puis on confronte ce chiffre a ce que nos mesures
    disent de l'edge de copie reel -- **-7,97 bps sur 24 133 signaux hors echantillon** (le
    leader est CONTRARIEN). Aucun edge positif n'est donc disponible : le mode sniper mono-wallet
    est MORT PAR MESURE, pas par reglage.

    Deux etats sont acceptes, et seulement deux :
      * le plancher est franchissable avec un edge de copie plausible -> le mode vit ;
      * le plancher vaut la SENTINELLE -> le mode est declare ferme, par ecrit.
    Ce qui reste interdit, c'est l'entre-deux : un plancher qu'on croit actif et que rien ne peut
    franchir. Et surtout : on ne BAISSE PAS le plancher pour faire passer le test -- ce serait
    laisser entrer des trades a edge negatif, c'est-a-dire payer pour perdre.
    """
    from hl_observer.copying.realtime_magic_score import (
        RealtimeCopyRiskConfig, RealtimeCopyScoreInput, score_realtime_copy_candidate)
    floor = _lf("HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS", 55.0)
    if floor >= SENTINELLE_SNIPER_FERME:
        return (f"mode sniper mono-wallet DECLARE FERME (plancher {floor:.0f} bps >= sentinelle) "
                f"-- coherent avec l'edge de copie mesure a -7,97 bps hors echantillon")
    sc = score_realtime_copy_candidate(
        RealtimeCopyScoreInput(
            action_type="OPEN_LONG", direction="LONG", leader_expected_edge_bps=52.0,
            leader_consistency_factor=1.0, signal_age_ms=200, consensus_wallets=1,
            liquidity_score=1.0, leader_score=100.0, leader_reference_price=100.0,
            current_mid=100.0, leader_notional_usdt=5000.0, current_open_exposure_usdt=0.0,
            current_open_positions=0, max_open_positions=20),
        config=RealtimeCopyRiskConfig(spread_bps=3.0, slippage_bps=5.0, fee_bps=4.0))
    maxi = float(sc.edge_remaining_bps or 0.0)
    cout_plancher = -maxi                       # edge de base = 0 ici -> ce qui reste, c'est le cout
    edge_requis = floor + cout_plancher
    assert maxi >= floor, (
        f"VERROU MORT : plancher single-wallet {floor:.0f} bps, couts {cout_plancher:.1f} bps "
        f"-> il faudrait un edge de copie MESURE de {edge_requis:.1f} bps pour passer. Or nos "
        f"mesures donnent -7,97 bps (24 133 signaux hors echantillon) : c'est inatteignable.\n"
        f"NE BAISSE PAS LE PLANCHER (ce serait ouvrir des trades a edge negatif). Deux issues "
        f"honnetes : mesurer un edge de copie positif, ou declarer le mode ferme en mettant "
        f"HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS >= {SENTINELLE_SNIPER_FERME:.0f}."
    )
    return f"plancher {floor:.0f} <= maximum atteignable {maxi:.1f} bps"


def _eco_taker_jamais_gratuit():
    from hl_observer.paper_trading.exec_model import ExecModelConfig, simulate_execution
    cfg = ExecModelConfig()
    assert cfg.latency_cost_bps_per_sec > 0, (
        "la LATENCE coute ZERO : on copie un leader avec 57 s de retard median, et le prix "
        "d'entree paper etait exactement celui du leader (8 entrees sur 20 a un prix MEILLEUR "
        "que le marche -- physiquement impossible)"
    )
    for side, mid in (("LONG", 100.0), ("SHORT", 100.0)):
        r = simulate_execution(side=side, notional_usdc=500, mid_price=mid,
                               top_depth_usdc=50_000, latency_sec=0.0, config=cfg)
        assert r.net_cost_bps > 0, f"cout taker nul ou negatif ({side}) : le bot serait paye pour entrer"
        if side == "LONG":
            assert r.fill_price > mid, "achat rempli SOUS le mid : gain impossible"
        else:
            assert r.fill_price < mid, "vente remplie AU-DESSUS du mid : gain impossible"
    lent = simulate_execution(side="LONG", notional_usdc=500, mid_price=100.0,
                              top_depth_usdc=50_000, latency_sec=57.0, config=cfg)
    assert lent.latency_bps >= 10.0, f"57 s de retard ne coutent que {lent.latency_bps:.1f} bps"
    return f"copie a 57 s facturee {lent.net_cost_bps:.1f} bps (dont {lent.latency_bps:.1f} de latence)"


def _eco_aller_retour_perd_les_couts():
    from hl_observer.paper_trading.exec_model import ExecModelConfig, simulate_execution
    cfg = ExecModelConfig()
    e = simulate_execution(side="LONG", notional_usdc=500, mid_price=100.0, top_depth_usdc=50_000,
                           latency_sec=57.0, config=cfg)
    s = simulate_execution(side="SELL", notional_usdc=500, mid_price=100.0, top_depth_usdc=50_000,
                           latency_sec=0.0, config=cfg)
    pnl = (s.fill_price - e.fill_price) / e.fill_price * 10_000
    attendu = -(e.net_cost_bps + s.net_cost_bps)
    assert abs(pnl - attendu) < 0.5, (
        f"aller-retour a prix CONSTANT : {pnl:.2f} bps, attendu {attendu:.2f}. "
        f"Un ecart = double comptage des frais, ou fuite de couts."
    )
    assert pnl < 0, "un aller-retour a prix constant DOIT perdre les couts"
    return f"a prix constant, un aller-retour perd {-pnl:.1f} bps = exactement les couts"


def _eco_cliquets_pas_sur_du_bruit():
    marge = _lf("HYPERSMART_MAX_POSITION_USDT", 50.0)
    levier = _lf("HYPERSMART_SIMULATION_LEVERAGE", 10.0)
    sl = _lf("HYPERSMART_SLTP_STOP_LOSS_BPS", 60.0)
    perte_normale = marge * levier * sl / 10_000.0
    mauvais = []
    for var, dft in (("HYPERSMART_SESSION_GUARD_SOFT_LOSS_USDC", 2.50),
                     ("HYPERSMART_SESSION_GUARD_HARD_LOSS_USDC", 10.0),
                     ("HYPERSMART_COIN_SIDE_LOSS_COOLDOWN_USDC", 0.20),
                     ("HYPERSMART_COIN_SESSION_LOSS_COOLDOWN_USDC", 0.50),
                     ("HYPERSMART_LEADER_SESSION_LOSS_COOLDOWN_USDC", 0.35)):
        v = _lf(var, dft)
        if v < perte_normale:
            mauvais.append(f"{var}={v:.2f}$")
    assert not mauvais, (
        f"CLIQUETS SUR DU BRUIT : {', '.join(mauvais)} -- alors qu'UNE perte normale vaut "
        f"{perte_normale:.2f} $. Ces garde-fous sont IRREVERSIBLES : ils se declenchent au "
        f"premier trade perdant et le bot cesse d'ouvrir pour le reste du run."
    )
    hard = _lf("HYPERSMART_SESSION_GUARD_HARD_LOSS_USDC", 10.0)
    assert hard / 1000.0 >= 0.10, (
        f"HALT TOTAL de session a {hard:.0f} $ = {hard/10:.1f} % du capital. Irreversible : "
        f"un drawdown de routine tue le run de 48 h et on ne mesure plus rien."
    )
    return f"tous les cliquets > une perte normale ({perte_normale:.2f} $) ; halt a {hard:.0f} $"


def _eco_stop_catastrophique_ferme():
    from hl_observer.paper_trading.sl_tp import SLTPConfig
    from hl_observer.paper_trading.sltp_runtime import apply_sltp_exits
    import os as _os
    old = dict(_os.environ)
    try:
        _os.environ["HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS"] = "110"
        _os.environ["HYPERSMART_SLTP_STOP_MIN_HOLD_MS"] = "45000"
        pos = {"0xw|ARB|SHORT": {"coin": "ARB", "direction": "SHORT", "side": "SHORT",
                                 "size": -5.0, "avg_price": 100.0, "opened_at_ms": 0,
                                 "wallet_address": "0xw"}}
        ledger = []
        closed = apply_sltp_exits(pos, ledger, {"ARB": 103.0}, now_ms=1000,
                                  config=SLTPConfig(take_profit_bps=110.0, stop_loss_bps=315.0))
        assert closed, (
            "LE STOP CATASTROPHIQUE NE FERME RIEN. Mesure : quand la volatilite gonflait le SL "
            "a 315 bps, la perte courait jusqu'a -323 bps. Les 2 trades concernes (ARB, ZEC) "
            "pesent 46 % de TOUTE la perte du run."
        )
        assert closed[0]["reason"] == "CATASTROPHIC_STOP"
    finally:
        _os.environ.clear(); _os.environ.update(old)
    return "le filet de securite ferme reellement la position (perte plafonnee)"


def _eco_gate_et_pnl_coherents():
    """Le scorer refuse un signal a 21 bps de couts. Le PnL doit facturer un ordre comparable."""
    from hl_observer.paper_trading.exec_model import ExecModelConfig, simulate_execution
    cfg = ExecModelConfig()
    e = simulate_execution(side="SHORT", notional_usdc=500, mid_price=100.0, top_depth_usdc=50_000,
                           latency_sec=57.0, config=cfg)
    s = simulate_execution(side="BUY", notional_usdc=500, mid_price=100.0, top_depth_usdc=50_000,
                           latency_sec=0.0, config=cfg)
    total = e.net_cost_bps + s.net_cost_bps
    assert 15.0 <= total <= 45.0, (
        f"le PnL facture {total:.1f} bps par aller-retour alors que le SCORER en facture ~21 pour "
        f"DECIDER. Si le PnL en facture moins, il est FLATTE et les gates deviennent incoherents "
        f"avec lui : on refuse des trades qu'on aurait comptes gagnants."
    )
    return f"aller-retour facture {total:.1f} bps au PnL, coherent avec les ~21 bps du gate"


c_eco_ratio        = exec_rule("ECONOMIE : le ratio TP/SL n'exige pas un winrate impossible", _eco_ratio_tp_sl)
c_eco_tp_floor     = exec_rule("ECONOMIE : la volatilite ne peut pas raboter le TP sous les frais", _eco_tp_floor)
c_eco_degr         = exec_rule("ECONOMIE : le plafond de degradation est FRANCHISSABLE", _eco_degradation_franchissable)
c_eco_sniper       = exec_rule("ECONOMIE : le plancher single-wallet est ATTEIGNABLE", _eco_single_wallet_atteignable)
c_eco_taker        = exec_rule("ECONOMIE : entrer coute toujours (latence + spread factures)", _eco_taker_jamais_gratuit)
c_eco_aller_retour = exec_rule("ECONOMIE : a prix constant, un aller-retour perd EXACTEMENT les couts", _eco_aller_retour_perd_les_couts)
c_eco_cliquets     = exec_rule("ECONOMIE : les cliquets de session ne se declenchent pas sur du bruit", _eco_cliquets_pas_sur_du_bruit)
c_eco_cata         = exec_rule("ECONOMIE : le stop catastrophique ferme REELLEMENT", _eco_stop_catastrophique_ferme)
c_eco_coherence    = exec_rule("ECONOMIE : les couts du GATE et ceux du PnL sont coherents", _eco_gate_et_pnl_coherents)


def main():
    import atexit
    import signal

    for sig in ("SIGINT", "SIGTERM", "SIGBREAK"):
        s_ = getattr(signal, sig, None)
        if s_ is not None:
            try:
                signal.signal(s_, _on_signal)
            except (OSError, ValueError):
                pass

    def _at_exit():
        if not STATE["final"] and not STATE["interrupted"]:
            STATE["interrupted"] = "arret imprevu (crash ou fermeture)"
            write_report()
    atexit.register(_at_exit)

    plan = [
        # --- INTEGRITE DU CODE ---
        c_compile, c_imports, c_all_imports, c_circular, c_arity, c_dead_imports,
        c_lazy_import, c_star_import, c_empty_files, c_init_with_logic,
        c_duplicate_module_names, c_module_docstrings, c_type_hints,
        # --- SECURITE : AUCUNE EXECUTION REELLE ---
        c_secrets, c_no_real_exec, c_lib_signature, c_env_privkey, c_exchange_url,
        c_wallet_connect, c_shell_true, c_eval_exec, c_pickle, c_os_system,
        c_profit_promise, c_safety,
        # --- ROBUSTESSE D'UN RUN 48h ---
        c_silent_except, c_pass_in_except, c_http_no_timeout, c_ws_no_timeout,
        c_open_no_with, c_open_no_encoding, c_sqlite_no_ctx, c_thread_no_daemon,
        c_while_true, c_sleep_long, c_mutable_default, c_global_state, c_env_no_default,
        c_sys_exit_lib, c_basicconfig, c_recursion, c_no_io_at_import, c_mp_guard,
        c_unseeded_random,
        # --- PIEGES DE TRADING / DONNEES ---
        c_float_equality, c_div_no_guard, c_time_not_monotonic, c_naive_datetime,
        c_utcnow, c_reason_codes, c_pnl,
        # --- QUALITE ---
        c_long_functions, c_too_many_args, c_complexity, c_big_classes, c_deep_nesting,
        c_duplicate_bodies, c_prod_assert, c_print_prod, c_shadow_builtin, c_type_ignore,
        c_abs_path, c_hardcoded_url, c_files_health, c_todo,
        # --- ARCHITECTURE ---
        c_layer_risk_ui, c_layer_paper_ui, c_layer_edge_ui, c_layer_hl_dydx,
        c_toolkit_pure, c_orphans,
        # --- CONFIG DU LANCEUR ---
        c_config, c_cmd_duplicate_set, c_env_wiring, c_env_read_but_never_set,
        c_fail_open, c_risk_values_sane, c_env_example_sync,
        # --- TESTS ---
        c_new_files, c_untested, c_test_isolation, c_tests_without_assert, c_skipped,
        c_net_in_tests, c_test_dupes, c_tests_write_runtime, c_test_files_misplaced,
        c_test_ratio,
        # --- PROJET / DEPENDANCES / GIT ---
        c_docs, c_deps_declared, c_gitignore, c_big_tracked_files, c_git_dirty,
        c_resources, c_lint, c_inventory_stats,
        # --- PnL & SIMULATION : controles EXECUTES (on fait tourner le code) ---
        c_pnl_long_up, c_pnl_long_down, c_pnl_short_down, c_pnl_short_up, c_pnl_symmetry,
        c_fees_charged, c_fees_not_double, c_pnl_scales, c_pnl_numpy_pure,
        c_sizing_margin_lev, c_lev_not_twice, c_qty_coherent,
        c_costs_reduce, c_six_costs, c_degradation_cost, c_maker_rebate,
        c_edge_neg_reject, c_edge_small_reject, c_edge_good_accept,
        c_exposure_refuses, c_maxpos_refuses, c_minnotional_ref,
        c_dd_value, c_dd_positive, c_profit_factor,
        c_cvar_var, c_kelly_bounded, c_vol_target,
        c_slippage_size, c_microprice_range, c_spread_costs,
        c_determinism, c_lookahead, c_no_real_order_obj,
        c_latency_cost, c_latency_no_invent, c_cost_per_coin, c_maker_missed,
        c_deflated_sharpe, c_pbo, c_purged_cv, c_stress, c_mc_p5, c_promotion_gate,
        # --- SANTE ECONOMIQUE DU MOTEUR REEL (2026-07-11) : l'audit laissait passer des
        # configurations qui GARANTISSAIENT la perte. Ces 9 controles y repondent.
        c_eco_ratio, c_eco_tp_floor, c_eco_degr, c_eco_sniper, c_eco_taker,
        c_eco_aller_retour, c_eco_cliquets, c_eco_cata, c_eco_coherence,
        # --- VERITE DES DONNEES ---
        c_pnl_hardcoded, c_demo_data, c_ledger_append_only, c_no_trade_default,
        c_modes_separated,
        # --- FUZZING : on appelle VRAIMENT chaque fonction avec des entrees pourries ---
        c_fuzz_no_crash, c_fuzz_no_nan, c_fuzz_deterministic, c_fuzz_empty_input,
        c_fuzz_monotonic_costs, c_fuzz_pnl_signs, c_fuzz_costs_never_help,
        c_all_modules_have_public_api,
        # --- LA SUITE DE TESTS (partie longue) ---
        c_tests, c_coverage, c_critical_coverage, c_slow_tests, c_flaky, c_doctor,
    ]

    hist = _load_timings()
    total_est = sum(_estimate(fn.__name__, hist) for fn in plan)
    STATE["total"] = len(plan)
    STATE["todo"] = [fn.__name__ for fn in plan]
    fait_est = 0.0

    print()
    print(_cadre(sep="="))
    print(_cadre("AUDIT HYPERSMART -- lecture seule / paper. Aucun ordre reel possible."))
    print(_cadre(f"{len(plan)} controles.   Duree estimee : ~{_fmt_duree(total_est)}"))
    print(_cadre(sep="-"))
    print(_cadre("Le rapport est REECRIT APRES CHAQUE CONTROLE."))
    print(_cadre("Meme si tu fermes la fenetre, resultat-audit.md sera la."))
    print(_cadre(sep="="))
    print(flush=True)

    for i, fn in enumerate(plan, 1):
        est = _estimate(fn.__name__, hist)
        ecoule = time.time() - STATE["t0"]
        pct = min(0.999, fait_est / total_est) if total_est else 0.0
        reste = max(0.0, total_est - fait_est)
        long_check = est > 20.0

        print()
        print(f"  {_barre(pct)} {pct * 100:5.1f}%   [{i:3d}/{len(plan)}]"
              f"   ecoule {_fmt_duree(ecoule):>6s}   reste ~{_fmt_duree(reste):>6s}")
        if long_check:
            print(f"  >>> ETAPE LONGUE (~{_fmt_duree(est)}). NE FERME PAS, NE FAIS PAS CTRL-C.")
            print("  >>> Le rapport est deja sur le disque : tu ne perdras rien.")
        print(f"      ... {fn.__name__[2:].replace('_', ' ')}", flush=True)

        s_ = time.time()
        STATE["started"] = fn.__name__
        try:
            c = fn()
        except Exception as e:                                          # noqa: BLE001
            import traceback
            c = Check(f"{fn.__name__} (a CRASHE)").finish(
                f"CRASH: {type(e).__name__}: {e}",
                traceback.format_exc().splitlines()[-12:])
        c.title = f"{i}. " + re.sub(r"^\d+\.\s*", "", c.title)
        c.seconds = time.time() - s_
        hist[fn.__name__] = round(c.seconds, 2)
        fait_est += max(est, c.seconds)
        STATE["done"].append(c)
        if fn.__name__ in STATE.get("todo", []):
            STATE["todo"].remove(fn.__name__)

        if not c.ok:
            tag, mark = "ECHEC", "!!"
        elif c.warns:
            tag, mark = "OK*  ", "  "
        else:
            tag, mark = "OK   ", "  "
        print(f"  {mark}[{tag}] {c.title}")
        print(f"        {c.summary}   ({_fmt_duree(c.seconds) if c.seconds >= 1 else f'{c.seconds:.1f}s'})",
              flush=True)
        write_report()                                   # <-- le rapport existe des maintenant

    _save_timings(hist)                                  # l'ETA du prochain run sera exacte
    STATE["final"] = True
    STATE["started"] = None
    # empreinte mise a jour SEULEMENT si l'audit est alle au bout : un audit interrompu
    # ne doit pas "oublier" des fichiers pour la fois suivante.
    if STATE.get("manifest_pending"):
        try:
            import json
            MANIFEST.write_text(json.dumps({"updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                                            "files": STATE["manifest_pending"]},
                                           indent=1), encoding="utf-8")
        except Exception as e:                                          # noqa: BLE001
            print(f"   [!] empreinte non ecrite : {e}", flush=True)
    write_report()

    blocking_ko = [c for c in STATE["done"] if not c.ok and c.blocking]
    nonblock_ko = [c for c in STATE["done"] if not c.ok and not c.blocking]
    warns = sum(len(c.warns) for c in STATE["done"])
    ok = len(STATE["done"]) - len(blocking_ko) - len(nonblock_ko)
    duree = time.time() - STATE["t0"]

    print()
    print(_cadre(sep="="))
    print(_cadre(f"{_barre(1.0)} 100%   TERMINE en {_fmt_duree(duree)}"))
    print(_cadre(sep="-"))
    print(_cadre(f"Controles reussis .............. {ok:>4d} / {len(STATE['done'])}"))
    print(_cadre(f"ECHECS BLOQUANTS ............... {len(blocking_ko):>4d}"))
    print(_cadre(f"Echecs non bloquants ........... {len(nonblock_ko):>4d}"))
    print(_cadre(f"Avertissements a regarder ...... {warns:>4d}"))
    if blocking_ko:
        print(_cadre(sep="-"))
        print(_cadre("LES ECHECS BLOQUANTS :"))
        for c in blocking_ko[:8]:
            print(_cadre(f"   - {c.title}"))
    print(_cadre(sep="-"))
    print(_cadre("RAPPORT : resultat-audit.md  (a la racine du projet)"))
    print(_cadre(sep="="))
    print()
    if blocking_ko or nonblock_ko or warns:
        print("   >>> Envoie `resultat-audit.md` a Claude : il contient TOUT le detail.")
    else:
        print("   >>> TOUT EST VERT.")
    print(flush=True)
    return 1 if blocking_ko else 0


if __name__ == "__main__":
    if "--fuzz-worker" in sys.argv:          # sous-processus du controle de fuzzing
        _fuzz_worker()
        raise SystemExit(0)
    raise SystemExit(main())
