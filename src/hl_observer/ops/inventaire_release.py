"""[RELEASE] Moteur de COMPLETUDE : rien d'important ne doit manquer dans l'archive portable.

Avant d'archiver, on ne se contente pas d'« inclure tout sauf l'exclu ». On PROUVE que la release est
complete :
  1. inventaire recursif categorise du dossier ;
  2. cloture transitive des imports intra-projet (AST : `import hl_observer.x` / `from hl_observer.x`)
     -> chaque module importe doit avoir son FICHIER present ;
  3. references des .cmd maitres (`python -m hl_observer.x`, `tools\\y.py/.ps1/.cmd`) -> present ;
  4. controle : tout fichier REQUIS absent / vide / exclu par erreur / import casse BLOQUE la release ;
  5. transparence : les fichiers non suivis (git) requis sont signales, jamais ignores en silence.

Pur (ast/pathlib), 0 reseau. Le detecteur de non-suivis prend la sortie git en parametre (injectable).
"""
from __future__ import annotations

import ast
from pathlib import Path

PAQUET = "hl_observer"
MAITRES = ("LANCER_HYPERSMART.cmd", "ANALYSER_BACKTESTS_REPLAYS.cmd", "CREER_ARCHIVE_PORTABLE.cmd")
# Fichiers/dossiers socle qui DOIVENT etre dans toute release (au-dela des .py importes).
SOCLE = ("pyproject.toml", "requirements-portable.txt")
EXT_CONFIG = (".yaml", ".yml", ".json", ".toml", ".ini", ".cfg")


# ── INVENTAIRE ────────────────────────────────────────────────────────────────────────────────
def _rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def inventaire(root: str | Path) -> dict:
    """Inventaire recursif categorise (chemins POSIX relatifs). Ne descend pas dans .git."""
    root = Path(root)
    cats: dict[str, list[str]] = {k: [] for k in
                                  ("modules", "collecteurs", "strategies", "pipelines", "tools_py",
                                   "cmd", "ps1", "tests", "configs", "certs", "autres")}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or ".git" in p.parts or "__pycache__" in p.parts:
            continue
        rel = _rel(root, p)
        bas = rel.lower()
        if rel.startswith("src/hl_observer/") and bas.endswith(".py"):
            cats["modules"].append(rel)
            if "/collection/" in rel:
                cats["collecteurs"].append(rel)
            if "/strategies/" in rel:
                cats["strategies"].append(rel)
            if "/pipelines/" in rel or "pipeline" in Path(rel).name:
                cats["pipelines"].append(rel)
        elif rel.startswith("tools/") and bas.endswith(".py"):
            cats["tools_py"].append(rel)
        elif bas.endswith(".cmd"):
            cats["cmd"].append(rel)
        elif bas.endswith(".ps1"):
            cats["ps1"].append(rel)
        elif rel.startswith("tests/") and bas.endswith(".py"):
            cats["tests"].append(rel)
        elif bas.endswith((".pem", ".crt", ".cer", ".ca-bundle")):
            cats["certs"].append(rel)
        elif bas.endswith(EXT_CONFIG):
            cats["configs"].append(rel)
        else:
            cats["autres"].append(rel)
    return cats


# ── RESOLUTION MODULE -> FICHIER ───────────────────────────────────────────────────────────────
def module_vers_fichier(root: str | Path, dotted: str) -> str | None:
    """`hl_observer.a.b` -> src/hl_observer/a/b.py OU src/hl_observer/a/b/__init__.py (rel POSIX)."""
    root = Path(root)
    parts = dotted.split(".")
    base = root / "src" / Path(*parts)
    fichier = base.with_suffix(".py")
    if fichier.is_file():
        return _rel(root, fichier)
    initf = base / "__init__.py"
    if initf.is_file():
        return _rel(root, initf)
    return None


def _handler_capte_import(h: ast.ExceptHandler) -> bool:
    """Un except qui capte ImportError/ModuleNotFoundError/Exception/BaseException (ou bare) rend
    l'import du try OPTIONNEL (best-effort) : son absence est geree, pas une release cassee."""
    if h.type is None:
        return True                                        # bare except
    noms = []
    cible = h.type
    if isinstance(cible, ast.Tuple):
        noms = [e.id for e in cible.elts if isinstance(e, ast.Name)]
    elif isinstance(cible, ast.Name):
        noms = [cible.id]
    return any(n in ("ImportError", "ModuleNotFoundError", "Exception", "BaseException") for n in noms)


class _ScanImports(ast.NodeVisitor):
    def __init__(self, paquet: str):
        self.paquet = paquet
        self.directs: set[str] = set()
        self.froms: set[str] = set()
        self.guardes: set[str] = set()                     # imports sous try/except optionnel
        self._garde = 0

    def _pkg(self, nom: str) -> bool:
        return nom == self.paquet or nom.startswith(self.paquet + ".")

    def visit_Try(self, node: ast.Try):
        garde = any(_handler_capte_import(h) for h in node.handlers)
        if garde:
            self._garde += 1
        for c in node.body:
            self.visit(c)
        if garde:
            self._garde -= 1
        for h in node.handlers:
            self.visit(h)
        for c in node.orelse + node.finalbody:
            self.visit(c)

    def visit_Import(self, node: ast.Import):
        for a in node.names:
            if self._pkg(a.name):
                self.directs.add(a.name)
                if self._garde:
                    self.guardes.add(a.name)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if not (node.level and node.level > 0):
            mod = node.module or ""
            if self._pkg(mod):
                self.froms.add(mod)
                if self._garde:
                    self.guardes.add(mod)


def _imports_intra(source: str, paquet: str) -> tuple[set[str], set[str], set[str]]:
    """(directs, froms, guardes). `directs` = import X.Y.Z (Z doit etre un module). `froms` = from X.Y
    import ... (X.Y doit resoudre). `guardes` = imports sous try/except optionnel (absence toleree)."""
    try:
        arbre = ast.parse(source)
    except SyntaxError:
        return set(), set(), set()
    s = _ScanImports(paquet)
    s.visit(arbre)
    return s.directs, s.froms, s.guardes


def cloture_imports(root: str | Path, *, paquet: str = PAQUET) -> dict:
    """Scanne tous les .py (src, tools, tests) et resout les imports intra-projet en FICHIERS. Rend
    {requis: set(fichiers rel), casses: [{depuis, module, genre}]}. `import X.Y.Z` exige que Z soit un
    module present (sinon casse) ; `from X.Y import a` exige seulement que X.Y resolve (a peut etre un
    attribut de X.Y/__init__.py)."""
    root = Path(root)
    requis: set[str] = set()
    casses: list[dict] = []
    a_scanner: list[Path] = []
    for base in ("src/hl_observer", "tools", "tests"):
        d = root / base
        if d.is_dir():
            a_scanner += [p for p in d.rglob("*.py") if "__pycache__" not in p.parts]
    for p in a_scanner:
        try:
            src = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        directs, froms, guardes = _imports_intra(src, paquet)
        for mod in directs:                                # import X.Y.Z : Z doit etre un module present
            fich = module_vers_fichier(root, mod)
            if fich is None:
                if mod not in guardes:                     # un import garde (try/except) est optionnel
                    casses.append({"depuis": _rel(root, p), "module": mod, "genre": "import"})
            else:
                requis.add(fich)
        for mod in froms:                                  # from X.Y import ... : X.Y doit resoudre
            fich = module_vers_fichier(root, mod)
            if fich is None:
                if mod not in guardes:
                    casses.append({"depuis": _rel(root, p), "module": mod, "genre": "from"})
            else:
                requis.add(fich)
    return {"requis": requis, "casses": casses}


def references_cmd(root: str | Path) -> dict:
    """Fichiers references par les .cmd maitres : `-m hl_observer.x` (module) et `tools\\y.ext`.
    Rend {requis: set(fichiers rel), manquants: [ref texte]}."""
    import re
    root = Path(root)
    requis: set[str] = set()
    manquants: list[str] = []
    mod_rx = re.compile(r"-m\s+(hl_observer\.[A-Za-z0-9_.]+)")
    outil_rx = re.compile(r"tools\\([A-Za-z0-9_./\\-]+\.(?:py|ps1|cmd))", re.IGNORECASE)
    for nom in MAITRES:
        p = root / nom
        if not p.is_file():
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        for m in mod_rx.finditer(txt):
            fich = module_vers_fichier(root, m.group(1))
            (requis.add(fich) if fich else manquants.append("-m " + m.group(1)))
        for m in outil_rx.finditer(txt):
            rel = ("tools/" + m.group(1).replace("\\", "/"))
            if (root / rel).is_file():
                requis.add(rel)
            else:
                manquants.append(rel)
    return {"requis": requis, "manquants": sorted(set(manquants))}


# ── CONTROLE DE COMPLETUDE ─────────────────────────────────────────────────────────────────────
def fichiers_requis(root: str | Path) -> set[str]:
    """Ensemble MINIMAL qui doit etre present ET inclus : masters + socle + configs + TOUS les .py de
    src/hl_observer et tests + cloture d'imports + references .cmd."""
    root = Path(root)
    inv = inventaire(root)
    req: set[str] = set()
    for nom in MAITRES + SOCLE:
        if (root / nom).is_file():
            req.add(nom)
    req.update(inv["modules"])                             # tous les modules runtime
    req.update(inv["tests"])                               # la suite de tests (pas de release allegee)
    req.update(inv["configs"])                             # configs/schemas/migrations
    req.update(cloture_imports(root)["requis"])
    req.update(references_cmd(root)["requis"])
    # Un fichier DELIBEREMENT exclu (etat machine volatil sous runtime/, secret, cache...) n'est jamais
    # « requis » : sinon on se bloquerait sur ce qu'on exclut a raison. On aligne requis sur includable.
    try:
        from hl_observer.ops.archive_portable import est_exclu
        req = {r for r in req if not est_exclu(r)}
    except Exception:  # noqa: BLE001 — si archive_portable indisponible, on garde le set brut
        pass
    return req


def controle_completude(root: str | Path, inclus, *, non_suivis: list[str] | None = None) -> dict:
    """Compare l'ensemble REQUIS a ce que l'archive INCLUT. Bloque si un requis est absent du disque,
    vide, ou exclu par erreur ; ou si un import intra-projet est casse ; ou si une reference .cmd manque.
    Signale les fichiers non suivis (git) requis (jamais ignores en silence)."""
    root = Path(root)
    inclus_set = set(inclus)
    requis = fichiers_requis(root)
    absents_disque = sorted(r for r in requis if not (root / r).is_file())
    # un __init__.py VIDE est un marqueur de paquet legitime : ne le compte pas comme « vide requis ».
    vides = sorted(r for r in requis if Path(r).name != "__init__.py"
                   and (root / r).is_file() and (root / r).stat().st_size == 0)
    exclus_par_erreur = sorted(r for r in requis
                               if (root / r).is_file() and r not in inclus_set)
    imports = cloture_imports(root)
    refs = references_cmd(root)
    ns = set(non_suivis or [])
    non_suivis_requis = sorted(r for r in requis if r in ns)
    complet = not (absents_disque or vides or exclus_par_erreur
                   or imports["casses"] or refs["manquants"])
    return {
        "complet": complet,
        "n_requis": len(requis),
        "absents_disque": absents_disque,
        "vides": vides,
        "exclus_par_erreur": exclus_par_erreur,
        "imports_casses": imports["casses"],
        "references_cmd_manquantes": refs["manquants"],
        "non_suivis_requis": non_suivis_requis,
    }


def formater(v: dict) -> str:
    if v["complet"]:
        return "COMPLETUDE OK : %d fichiers requis tous presents et inclus." % v["n_requis"]
    lignes = ["COMPLETUDE KO (%d requis) :" % v["n_requis"]]
    for cle in ("absents_disque", "vides", "exclus_par_erreur", "references_cmd_manquantes",
                "non_suivis_requis"):
        if v[cle]:
            lignes.append("  %s : %s" % (cle, ", ".join(map(str, v[cle][:10]))))
    if v["imports_casses"]:
        lignes.append("  imports_casses : %s"
                      % ", ".join("%s<-%s" % (c["module"], c["depuis"]) for c in v["imports_casses"][:10]))
    return "\n".join(lignes)


__all__ = ["inventaire", "module_vers_fichier", "cloture_imports", "references_cmd",
           "fichiers_requis", "controle_completude", "formater"]
