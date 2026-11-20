"""L'audit ne doit auditer que le CODE DU PROJET, et son perimetre doit rester large.

LE DEFAUT MESURE (20/11/2026). ``tools/audit_report.py`` decouvre ses dossiers tout seul
(``code_dirs()``), et ``tools/`` contient la DISTRIBUTION PYTHON EMBARQUEE : 5 896 fichiers
tiers sous ``site-packages``, dont aucune partie du chemin n'etait exclue. Mesure sur une seule
regle -- l'horodatage sans fuseau -- avant et apres l'exclusion :

    107 occurrence(s)  ->  2 occurrence(s)        (puis 0 apres correction des 2 vraies)
    11 300 fichiers lus ->  5 428

89 % de ce que l'audit signalait venait de dependances qu'on ne corrige pas, et qui changent a
chaque mise a jour. Un controle noye dans du bruit tiers apprend a l'operateur a l'ignorer.

CE QUE CE TEST TIENT, DANS LES DEUX SENS. Le perimetre ne doit plus contenir de code tiers --
et il doit rester LARGE : une exclusion trop gourmande aveuglerait l'audit sur le projet, ce qui
serait bien pire que le bruit qu'on vient de retirer.
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


#: Le balayage du perimetre marche l'arborescence de `tools/` (distribution embarquee et
#: git inclus) : ~35 s. Le refaire a chaque test coutait 104 s pour la meme reponse.
_CACHE: dict[str, object] = {}


def _module_audit():
    if "module" not in _CACHE:
        spec = importlib.util.spec_from_file_location(
            "audit_report_perimetre", RACINE / "tools" / "audit_report.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["audit_report_perimetre"] = module
        spec.loader.exec_module(module)
        _CACHE["module"] = module
    return _CACHE["module"]


def _fichiers_audites() -> list:
    if "fichiers" not in _CACHE:
        _CACHE["fichiers"] = list(_module_audit()._py_files())
    return _CACHE["fichiers"]  # type: ignore[return-value]


def test_l_audit_n_audite_pas_la_distribution_python_embarquee() -> None:
    fichiers = _fichiers_audites()
    tiers = [str(p) for p in fichiers if "site-packages" in p.parts]
    assert tiers == [], (
        f"{len(tiers)} fichier(s) tiers dans le perimetre de l'audit (ex. {tiers[:2]}) : "
        "ses compteurs melangent le projet et ses dependances")


def test_le_perimetre_de_l_audit_reste_large() -> None:
    """La moitie qui compte : une exclusion trop gourmande aveuglerait l'audit sur le projet."""
    fichiers = _fichiers_audites()
    assert len(fichiers) > 2000, (
        f"{len(fichiers)} fichier(s) seulement : l'audit ne couvre plus le projet")
    noms = {p.name for p in fichiers}
    for attendu in ("copy_vault_local_lab.py", "restore_alina.py", "tester_cmds.py"):
        assert attendu in noms, f"{attendu} est sorti du perimetre de l'audit"


def test_aucun_instant_naif_ne_produit_d_horodatage() -> None:
    """Les deux sites REELS corriges le 20/11/2026, verrouilles.

    Un instant sans fuseau est lu en heure LOCALE : pendant un changement d'heure, l'heure
    locale est ambigue, donc l'horodatage pouvait etre faux d'UNE HEURE -- et il est compare a
    des horodatages de marche. Le formatage d'affichage (``strftime``) n'est pas concerne.
    """
    cibles = {
        "src/hl_observer/markets/universal_registry.py": "observed_at_ms = int(",
        "tools/rapport_collecteurs.py": "    now = ",
    }
    for relatif, prefixe in cibles.items():
        lignes = [l.strip() for l in (RACINE / relatif).read_text(
            encoding="utf-8", errors="replace").splitlines()
            if l.lstrip().startswith(prefixe.strip()) and "timestamp()" in l]
        assert lignes, f"{relatif} : la ligne d'horodatage a disparu, le test ne verrouille rien"
        for ligne in lignes:
            assert "timezone.utc" in ligne, (
                f"{relatif} : horodatage produit sans fuseau -> {ligne[:90]}")


def test_le_perimetre_n_est_parcouru_qu_une_fois() -> None:
    """MESURE DU 20/11/2026 : la marche de repertoires coute 52,0 s, la LECTURE des
    5 429 fichiers 0,5 s. `regex_rule` rappelait `_py_files()` a chaque regle : 42 regles
    x 52 s = ~37 MINUTES a enumerer les memes chemins. Avec le cache : une seule marche.
    """
    module = _module_audit()
    premier = _fichiers_audites()          # paye la marche (ou la reutilise)
    debut = time.monotonic()
    second = module._py_files()
    ecoule = time.monotonic() - debut
    assert [str(x) for x in second] == [str(x) for x in premier], (
        "le cache ne rend pas le meme perimetre que la marche initiale")
    assert ecoule < 5.0, (
        f"second appel en {ecoule:.1f} s : le perimetre est re-parcouru, donc l audit paiera "
        "cette marche une fois par regle")


def test_le_cache_distingue_les_perimetres_demandes() -> None:
    """La moitie qui compte : un cache qui rendrait TOUJOURS la meme liste serait faux.

    `_py_files()` sans argument ajoute les scripts .py de la racine ; `_py_files("src")`
    ne doit rendre que `src/`. Une cle de cache trop large melangerait les deux.
    """
    module = _module_audit()
    src_seul = module._py_files("src")
    tout = _fichiers_audites()
    assert src_seul, "perimetre `src` vide : le test ne verifie plus rien"
    assert len(src_seul) < len(tout), (
        f"`src` seul ({len(src_seul)}) devrait etre plus petit que tout ({len(tout)})")
    assert all("src" in p.parts for p in src_seul), (
        "le cache a rendu des fichiers hors du perimetre demande")
