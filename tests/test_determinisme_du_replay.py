"""Aucun aleatoire NON REPRODUCTIBLE dans le chemin replay / backtest.

CE QUE CA PROTEGE. Le contrat du labo exige des replays, backtests, OOS et forward-paper
« reellement causaux, deterministes et reproductibles ». Un seul appel au generateur GLOBAL
de Python (``random.random()``, ``random.shuffle(l)``) ou de NumPy (``np.random.rand()``,
``np.random.seed(0)``) suffit a rendre un resultat irreproductible : l'etat est partage par tout
le processus, donc l'ordre des appels -- et avec lui le chiffre produit -- depend de ce que les
autres modules ont tire avant. Un PnL qui change d'un passage a l'autre ne prouve plus rien.

L'ETAT MESURE (20/11/2026). Les 225 modules de ``src/hl_observer/backtesting/`` contiennent
**46 sources d'alea, et les 46 sont graines explicitement** : ``random.Random(seed)``,
``np.random.default_rng(config.seed)``, ``seeded_rng(seed)``, ou une methode appelee sur un
generateur ainsi construit. Ce test ne corrige donc rien : il EMPECHE la regression.

POURQUOI LA REGLE EST SI ETROITE. ``random.getrandbits(64)`` est admis : il ne sert qu'a nommer
un fichier temporaire (``.partial``), jamais a produire un resultat. Un controle qui crierait au
loup sur lui apprendrait a l'operateur a ignorer ses alertes.
"""
from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
CHEMIN_REPLAY = RACINE / "src" / "hl_observer" / "backtesting"

#: Appels au generateur GLOBAL : etat partage par le processus entier.
INTERDITS = (
    "random.random(", "random.randint(", "random.choice(", "random.choices(",
    "random.shuffle(", "random.uniform(", "random.sample(", "random.gauss(",
    "random.normalvariate(", "random.randrange(", "random.seed(",
    "np.random.rand(", "np.random.randn(", "np.random.seed(", "np.random.choice(",
    "np.random.permutation(", "np.random.shuffle(", "np.random.normal(",
    "numpy.random.seed(",
)

#: Formes REPRODUCTIBLES : un generateur porte sa graine, et les tirages passent par lui.
ADMIS = ("random.Random(", "np.random.default_rng(", "numpy.random.default_rng(",
         "random.getrandbits(", "seeded_rng(")


def alea_non_reproductible(ligne: str) -> bool:
    nu = ligne.strip()
    if nu.startswith("#"):
        return False
    if any(forme in nu for forme in ADMIS):
        return False
    return any(appel in nu for appel in INTERDITS)


def _modules() -> list[Path]:
    return [p for p in CHEMIN_REPLAY.rglob("*.py")
            if p.is_file() and "__pycache__" not in p.parts]


def test_le_chemin_replay_ne_tire_jamais_du_generateur_global() -> None:
    modules = _modules()
    assert len(modules) > 100, (
        f"{len(modules)} module(s) de backtesting trouves : le balayage ne couvre plus le "
        "chemin qu'il doit proteger")
    fautifs: list[str] = []
    for chemin in modules:
        for numero, ligne in enumerate(
                chemin.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if alea_non_reproductible(ligne):
                fautifs.append(f"{chemin.relative_to(RACINE)}:{numero} -> {ligne.strip()[:88]}")
    assert not fautifs, (
        "tirage(s) sur le generateur GLOBAL dans le chemin replay/backtest : un resultat "
        "irreproductible ne prouve rien. Construire un generateur graine "
        "(random.Random(seed) / np.random.default_rng(seed)) et tirer par lui :\n  "
        + "\n  ".join(fautifs))


def test_la_regle_attrape_un_vrai_tirage_global() -> None:
    """Sans ceci, le test ci-dessus passerait avec une regle qui ne detecte rien."""
    assert alea_non_reproductible("    bruit = random.random() * 0.01")
    assert alea_non_reproductible("    random.shuffle(episodes)")
    assert alea_non_reproductible("    np.random.seed(0)")
    assert alea_non_reproductible("    idx = np.random.permutation(len(X))")


def test_la_regle_laisse_passer_un_generateur_graine() -> None:
    """La moitie qui compte : les 46 formes REELLES du projet ne doivent jamais etre signalees."""
    assert not alea_non_reproductible("    rng = random.Random(seed)")
    assert not alea_non_reproductible("    rng = np.random.default_rng(config.seed)")
    assert not alea_non_reproductible("    rng.shuffle(shuffled)")
    assert not alea_non_reproductible("    g = random.Random(seed + s)")
    assert not alea_non_reproductible(
        '        f".CURRENT_CHAMPION.{os.getpid()}.{random.getrandbits(64):016x}.partial"')
    assert not alea_non_reproductible("# random.shuffle(x) : la forme interdite, en commentaire")
