"""T3e — L'INVARIANT « BRANCHER OU ENTERRER » ETENDU A `runtime/` (#593, 2026-07-13).

CE QUI A ETE PROUVE PAR EXECUTION
--------------------------------
Les taches **P4 (hot path)** et **P5 (queues bornees)** etaient marquees **« completed »**. Grep des
imports sur TOUT le depot :

    hot_path.py             -> importe UNIQUEMENT par son test
    event_driven_decider.py -> importe UNIQUEMENT par son test
    bounded_event_queue.py  -> importe par event_driven_decider (mort) + son test

**Zero import de production.** Le coeur de P4 et P5 n'est appele par personne. *Un test ne cable
rien.* (Meme motif que T3b/T3c : 25 garde-fous de `risk/`, 8 de `paper_trading/`.)

CE QUE CE FICHIER VERROUILLE
----------------------------
1. **Pas de LIMBE** : un module de `runtime/` doit etre soit **joignable depuis la production**,
   soit **explicitement enterre** dans `runtime/tombstones_runtime.py`. Ni l'un ni l'autre = echec.
2. **Pas de RESURRECTION accidentelle** : un module enterre ne doit pas etre importe par du code de
   production. S'il l'est, la suite rougit -- et celui qui le ressuscite doit retirer la tombe,
   donc ECRIRE pourquoi.
3. **Une tombe doit avoir une raison CONTREDISABLE** (pas « obsolete », pas « legacy »).

🚩 ET LA TOMBE DE `bounded_event_queue` PORTE UNE CORRECTION SUR MOI-MEME : le module se justifiait
par un bug (« la queue vivante jette des userFill en silence ») qui **n'existe pas** -- la seule
queue vivante est un tampon de tri qui ne voit que des `PriceEvent`. *Un module justifie par un bug
inexistant est deux fois mort.*

Aucun ordre reel.
"""

from __future__ import annotations

import ast
from pathlib import Path

from hl_observer.runtime.tombstones_runtime import MODULES_ENTERRES_RUNTIME, TOMBES_RUNTIME

RACINE = Path(__file__).resolve().parents[1]
SRC = RACINE / "src" / "hl_observer"
RUNTIME = SRC / "runtime"

# Ces modules ne sont NI des garde-fous NI des moteurs : ce sont des utilitaires appeles par le
# runtime lui-meme ou par les outils. Les juger avec la meme regle n'apprendrait rien.
_HORS_JUGEMENT = {
    "__init__",
    "tombstones_runtime",   # le registre lui-meme
}


def _modules_runtime() -> set[str]:
    return {
        p.stem
        for p in RUNTIME.glob("*.py")
        if "__pycache__" not in p.as_posix() and p.stem not in _HORS_JUGEMENT
    }


def _imports_de(fichier: Path) -> set[str]:
    """Les modules de `runtime/` importes par ce fichier. Par l'AST -- un grep lirait les docstrings.

    (Et ce n'est pas theorique : le docstring de `bounded_event_queue` CITE le nom du module qu'il
    accuse. Un grep l'aurait compte comme un import.)

    🚩 DEUX FORMES, ET MA 1re VERSION N'EN VOYAIT QU'UNE :
        from hl_observer.runtime.latency_journal import X   -> module = "hl_observer.runtime.X"
        from hl_observer.runtime import latency_journal     -> module = "hl_observer.runtime"  ← RATE
    La 2e forme est celle qu'utilise `paper_trading/fusion_paper_engine_adapter.py`. Mon detecteur
    declarait donc MORT un module bien vivant. *Un detecteur incomplet n'est pas prudent : il ment.*
    """
    out: set[str] = set()
    try:
        arbre = ast.parse(fichier.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return out
    for n in ast.walk(arbre):
        if isinstance(n, ast.ImportFrom) and n.module:
            if n.module.startswith("hl_observer.runtime."):
                out.add(n.module.split(".")[-1])
            elif n.module == "hl_observer.runtime":          # <- la forme qui manquait
                out |= {a.name for a in n.names}
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith("hl_observer.runtime."):
                    out.add(a.name.split(".")[-1])
    return out


def _modules_de_production() -> list[Path]:
    """Tout `src/`, SAUF `runtime/` lui-meme (un mort peut en importer un autre mort)."""
    return [
        p
        for p in SRC.rglob("*.py")
        if "__pycache__" not in p.as_posix() and RUNTIME not in p.parents
    ]


def _ligne_de_commentaire(ligne: str) -> bool:
    """`.ps1` : `#`. `.cmd` : `REM` / `::`. Un commentaire n'execute rien."""
    t = ligne.strip().lower()
    return t.startswith("#") or t.startswith("rem ") or t.startswith("::")


def _portes_des_lanceurs() -> set[str]:
    """🔴 LA 5e PORTE (lecon de #597) : un module lance par un SCRIPT est VIVANT.

    L'audit de cablage ne connaissait qu'une forme de porte (`python -m hl_observer.X`) et
    declarait donc MORT `backtesting.scenario_search` -- le moteur qu'on lance le plus. Meme piege
    ici : `runtime/persistent_poll_runner.py` est **le poller de la simulation vivante**, demarre
    par `tools/hypersmart_simulation_poll_loop.ps1:298`. Aucun module de `src/` ne l'importe. Il
    n'est pas mort pour autant. *Un module invisible ne peut jamais etre declare mort honnetement.*

    🚩 MAIS MA 1re VERSION GREPAIT LE TEXTE BRUT -- et elle a ressuscite les 3 morts de P4/P5 :
        tools/prouver_hot_path.py   : ecrit pour PROUVER que hot_path est mort. Il cite
                                      « python -m hl_observer.runtime.hot_path » DANS UN COMMENTAIRE.
        tools/auditer_cablage.py    : l'audit de cablage. Il LISTE les modules par leur nom.
    *Un outil qui NOMME un module mort n'est pas une porte : c'est un constat de deces.*
    D'ou la regle : une porte est une **EXECUTION**, jamais une **MENTION**.
      - un `.py` : un vrai `import` (par l'AST -- pas un nom dans une chaine) ;
      - un `.ps1` / `.cmd` : un `-m hl_observer.runtime.X` sur une ligne **non commentee**.
    """
    portes: set[str] = set()
    noms = _modules_runtime()

    # --- les outils Python : un VRAI import (AST). Une chaine de caracteres ne lance rien.
    for f in (RACINE / "tools").glob("*.py"):
        portes |= _imports_de(f)

    # --- les lanceurs shell : une commande, sur une ligne qui n'est pas un commentaire.
    fichiers = list((RACINE / "tools").glob("*.ps1")) + list(RACINE.glob("*.cmd"))
    for f in fichiers:
        try:
            texte = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for ligne in texte.splitlines():
            if _ligne_de_commentaire(ligne):
                continue
            for m in noms:
                if ("-m hl_observer.runtime.%s" % m) in ligne or ("runtime/%s.py" % m) in ligne:
                    portes.add(m)
    return portes


def _portes_cli_main() -> set[str]:
    """LA 3e PORTE : `if __name__ == "__main__":` -- un module qu'un HUMAIN peut lancer.

    `runtime/detailed_report.py` documente sa propre commande
    (`python -m hl_observer.runtime.detailed_report`) : c'est un outil de diagnostic en lecture
    seule, joignable, meme si aucun module ne l'importe. Ce n'est pas du code mort.

    La porte est ETROITE, et c'est ce qui la rend sure : `hot_path` et `event_driven_decider`
    n'ont **pas** de bloc `__main__` (verifie). Elle ne peut donc pas ressusciter les morts de
    P4/P5 -- et le test `test_la_porte_CLI_ne_ressuscite_PAS_les_morts_de_P4_P5` le verrouille.
    """
    portes: set[str] = set()
    for p in RUNTIME.glob("*.py"):
        if p.stem in _HORS_JUGEMENT:
            continue
        try:
            arbre = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, SyntaxError):
            continue
        for n in arbre.body:                      # niveau MODULE uniquement
            if not isinstance(n, ast.If):
                continue
            t = n.test
            if (
                isinstance(t, ast.Compare)
                and isinstance(t.left, ast.Name)
                and t.left.id == "__name__"
                and any(
                    isinstance(c, ast.Constant) and c.value == "__main__"
                    for c in t.comparators
                )
            ):
                portes.add(p.stem)
    return portes


def _importes_par_la_production() -> set[str]:
    vus: set[str] = set()
    for f in _modules_de_production():
        vus |= _imports_de(f)
    return vus


def _vivants() -> set[str]:
    """Les DEUX portes + la fermeture transitive.

    Un module joignable depuis un module VIVANT de `runtime/` est vivant lui aussi : le poller
    (vivant par le lanceur) importe `detailed_logger`, qui importe... etc. Sans cette fermeture,
    on enterrerait des modules que la production execute a chaque cycle.
    """
    vus = _importes_par_la_production() | _portes_des_lanceurs() | _portes_cli_main()
    for _ in range(6):
        avant = set(vus)
        for m in list(vus):
            f = RUNTIME / ("%s.py" % m)
            if f.exists():
                vus |= _imports_de(f)
        if vus == avant:
            break
    return vus


# ====================================================== 1. PAS DE LIMBE


def test_aucun_module_de_runtime_ne_reste_dans_le_LIMBE():
    """🔴 Un module ni joignable ni enterre : PERSONNE ne sait s'il compte. Interdit.

    C'est exactement l'etat dans lequel P4 et P5 ont vecu, « completed », pendant des semaines.
    """
    # 🚩 LES DEUX PORTES, et il faut les DEUX : un import de `src/`, ou un LANCEUR.
    # (J'ai d'abord ecrit `_portes_des_lanceurs()`... sans jamais l'appeler. Le test declarait donc
    # MORT `persistent_poll_runner` -- le poller de la simulation vivante. Exactement le bug de
    # #597, reproduit a l'identique. *Ecrire le detecteur ne suffit pas : il faut le BRANCHER.*)
    limbes = sorted(_modules_runtime() - _vivants() - MODULES_ENTERRES_RUNTIME)
    assert not limbes, (
        "modules de `runtime/` dans le LIMBE (ni appeles par la production, ni enterres) : %s\n\n"
        "Decide, par ecrit :\n"
        "  - BRANCHER : un chemin de production l'importe, et un test le prouve ; ou\n"
        "  - ENTERRER : ajoute une TombeRuntime dans runtime/tombstones_runtime.py, avec une "
        "raison qu'on puisse CONTREDIRE.\n"
        "Rien entre les deux. Un test vert ne cable rien." % ", ".join(limbes)
    )


# ====================================================== 2. PAS DE RESURRECTION SILENCIEUSE


def test_aucun_module_ENTERRE_n_est_ressuscite_par_la_production():
    """Un mort qui se remet a tourner sans qu'on l'ait decide est pire qu'un mort."""
    ressuscites = sorted(MODULES_ENTERRES_RUNTIME & _vivants())
    assert not ressuscites, (
        "module(s) ENTERRE(S) importe(s) par du code de production : %s\n"
        "Si c'est voulu, retire la tombe de runtime/tombstones_runtime.py -- et ecris POURQUOI "
        "la raison de l'enterrement ne tient plus." % ", ".join(ressuscites)
    )


# ====================================================== 3. LA QUALITE DES TOMBES


def test_les_3_modules_de_P4_et_P5_sont_bien_declares_MORTS():
    """La constatation qui a ouvert #593, figee ici pour qu'elle ne se reperde pas."""
    assert {"hot_path", "event_driven_decider", "bounded_event_queue"} <= MODULES_ENTERRES_RUNTIME


def test_une_tombe_doit_donner_une_raison_CONTREDISABLE():
    """🚩 « obsolete », « legacy », « deprecated » ne sont pas des raisons : ce sont des etiquettes.

    Une raison contredisable nomme un FAIT (une mesure, un appelant, un chiffre). Sinon, personne
    ne pourra jamais prouver qu'elle est fausse -- et une tombe qu'on ne peut pas rouvrir est une
    decision qu'on ne peut pas corriger.
    """
    MOTS_VIDES = ("obsolete", "legacy", "deprecated", "inutile", "ancien")
    for t in TOMBES_RUNTIME:
        assert t.motif and t.pourquoi and t.preuve, "tombe incomplete : %s" % t.module
        assert len(t.pourquoi) > 40, "raison trop courte pour etre contredite : %s" % t.module
        bas = t.pourquoi.lower()
        assert not any(m in bas for m in MOTS_VIDES), (
            "la tombe de %s se justifie par une ETIQUETTE (%s), pas par un FAIT" % (t.module, bas)
        )


# ============================== 4. LE DETECTEUR DE PORTES DOIT MORDRE (sinon il ne garde rien)


def test_le_poller_VIVANT_est_bien_reconnu_comme_une_PORTE():
    """`persistent_poll_runner` n'est importe par AUCUN module de `src/`. Il est pourtant LE poller
    de la simulation vivante (`tools/hypersmart_simulation_poll_loop.ps1:298`). Si ce test tombe,
    le detecteur est redevenu aveugle a la porte des lanceurs -- et il enterrera la production."""
    assert "persistent_poll_runner" in _portes_des_lanceurs()


def test_une_MENTION_dans_un_commentaire_n_est_PAS_une_porte():
    """🚩 LE BUG QUE MON PROPRE INVARIANT A COMMIS, fige ici.

    `tools/prouver_hot_path.py` existe pour PROUVER que hot_path est mort -- et il cite la commande
    `python -m hl_observer.runtime.hot_path` dans un commentaire. Un grep de texte y voyait une
    porte, et RESSUSCITAIT les trois morts de P4/P5.
    """
    assert not ({"hot_path", "event_driven_decider"} & _portes_des_lanceurs()), (
        "un module ENTERRE est vu comme lance par un script : le detecteur confond une MENTION "
        "(commentaire, chaine, liste d'audit) avec une EXECUTION."
    )


def test_la_porte_CLI_ne_ressuscite_PAS_les_morts_de_P4_P5():
    """Une porte trop LARGE ne garde plus rien. `hot_path` et `event_driven_decider` n'ont pas de
    bloc `__main__` : la porte CLI ne doit pas les faire revivre. Si quelqu'un leur en ajoute un,
    ce test tombe -- et il faudra decider, par ecrit, si on les rebranche."""
    assert not ({"hot_path", "event_driven_decider", "bounded_event_queue"} & _portes_cli_main())


def test_la_tombe_de_bounded_event_queue_dit_que_l_ACCUSATION_ETAIT_FAUSSE():
    """🚩 LA CORRECTION SUR MOI-MEME, ecrite noir sur blanc et testee.

    Le module se justifiait par un bug de la queue vivante (« elle jette des userFill en silence »).
    Verification du seul appelant reel (`fusion_runtime:167`) : cette queue est un tampon de TRI,
    nourri uniquement de `PriceEvent`, draine dans le meme appel. Elle ne voit JAMAIS un userFill.

    Si ce test disparait, la fausse accusation pourra revenir justifier un cablage inutile.
    """
    t = next(x for x in TOMBES_RUNTIME if x.module == "bounded_event_queue")
    assert "n'existe pas" in t.pourquoi.lower() or "existe pas" in t.pourquoi.lower()
    assert "fusion_runtime" in t.preuve
