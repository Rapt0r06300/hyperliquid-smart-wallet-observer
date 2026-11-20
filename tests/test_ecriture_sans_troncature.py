"""``open(p, "w").write(expr)`` : le fichier est VIDE avant que ``expr`` soit evalue.

LE FAIT. Quatre ecritures de ce genre vivaient dans le projet (20/11/2026), et chacune portait
un risque different :

* ``tools/analysis/_seg_analysis.py`` -- ``open(p, "w")`` TRONQUE des l ouverture : un
  ``json.dumps`` qui echoue detruisait le resultat precedent et laissait un fichier VIDE.
* ``tools/audit_report.py`` -- le fichier etait ferme APRES l instruction, et une exception
  levee a la FERMETURE (disque plein, quota) est ignoree par Python. Le ``os.replace`` qui suit
  publiait alors un rapport TRONQUE comme s il etait complet : un faux succes silencieux.
* ``tools/recherche_18h.py`` et ``tools/recherche_continue.py`` -- ces deux ecritures etaient
  DANS un gestionnaire d exception. Si la journalisation echouait, son exception REMPLACAIT
  l erreur d origine, et la boucle censee survivre mourait sans qu on sache pourquoi.

LA REGLE. Un contenu se construit AVANT l ouverture, et l ecriture se fait dans un ``with`` :
une erreur de fermeture remonte alors au lieu d etre avalee. Le controle est exact -- il ne
cherche que la forme ``open(..., "w"|"a").write(`` -- donc il ne peut pas crier au loup.
"""
from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DOSSIERS = ("src", "tools")
MODES_QUI_ECRIVENT = ('"w"', "'w'", '"a"', "'a'", '"w+"', "'w+'", '"wb"', "'wb'")

#: Arbres QU'ON NE CORRIGE PAS. `tools/python/` est la distribution Python EMBARQUEE :
#: 5 896 des 11 075 fichiers balayes au depart venaient de `site-packages`. Un controle
#: qui echoue sur du code tiers est une fausse alerte que le projet ne peut pas reparer,
#: et la prochaine mise a jour de dependance l'aurait declenchee.
HORS_PERIMETRE = ("site-packages", "__pycache__", "node_modules", ".venv")


def _hors_perimetre(chemin: Path) -> bool:
    return any(part in HORS_PERIMETRE for part in chemin.parts)

def ecriture_sans_garde(ligne: str) -> bool:
    """``open(..., mode d ecriture).write(`` hors ``with`` et hors commentaire."""
    nu = ligne.strip()
    if nu.startswith("#") or "open(" not in nu or ").write(" not in nu:
        return False
    if nu.startswith("with ") or nu.startswith("async with "):
        return False
    arguments = nu[nu.index("open("):nu.index(").write(")]
    return any(mode in arguments for mode in MODES_QUI_ECRIVENT)


def _sources() -> list[Path]:
    fichiers: list[Path] = []
    for dossier in DOSSIERS:
        base = RACINE / dossier
        if base.is_dir():
            fichiers.extend(p for p in base.rglob("*.py")
                            if p.is_file() and not _hors_perimetre(p))
    return fichiers


def test_aucune_ecriture_ne_tronque_avant_d_evaluer() -> None:
    fichiers = _sources()
    assert len(fichiers) > 2000, (
        f"{len(fichiers)} source(s) : le balayage ne couvre plus le projet")
    fautifs: list[str] = []
    for chemin in fichiers:
        for numero, ligne in enumerate(
                chemin.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if ecriture_sans_garde(ligne):
                fautifs.append(f"{chemin.relative_to(RACINE)}:{numero} -> {ligne.strip()[:88]}")
    assert not fautifs, (
        "ecriture(s) qui tronquent avant d evaluer, ou dont l erreur de fermeture serait "
        "ignoree (construire le contenu AVANT, puis ecrire dans un `with`) :\n  "
        + "\n  ".join(fautifs))


def test_la_regle_attrape_bien_les_quatre_formes_corrigees() -> None:
    """Sans ceci, le test ci-dessus passerait avec une regle qui ne detecte rien.

    Ce sont les quatre lignes REELLES retirees du projet le 20/11/2026.
    """
    assert ecriture_sans_garde(
        'open("runtime/scenarios/segment_analysis.json","w").write(json.dumps(out,indent=2))')
    assert ecriture_sans_garde(
        '        io.open(tmp, "w", encoding="utf-8").write(build_report())')
    assert ecriture_sans_garde(
        '    (rundir / "logs" / "erreurs.jsonl").open("a", encoding="utf-8").write(')
    assert ecriture_sans_garde(
        '    (rundir / "errors.csv").open("a", encoding="utf-8").write("%d" % cycle)')


def test_la_regle_laisse_passer_une_ecriture_correcte() -> None:
    """La moitie qui compte : la forme SAINE ne doit jamais etre signalee."""
    assert not ecriture_sans_garde('with open(chemin, "w", encoding="utf-8") as flux:')
    assert not ecriture_sans_garde('    with chemin.open("a", encoding="utf-8") as flux:')
    assert not ecriture_sans_garde('        flux.write(contenu)')
    assert not ecriture_sans_garde('    texte = open(chemin, "r", encoding="utf-8").read()')
    assert not ecriture_sans_garde(
        '# open(p, "w").write(x) : la forme interdite, citee dans un commentaire')
