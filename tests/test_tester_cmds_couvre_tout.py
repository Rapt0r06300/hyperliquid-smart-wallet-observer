"""LE HARNAIS DOIT CONNAÎTRE **TOUS** LES LANCEURS DE LA RACINE.

D'OÙ VIENT CE TEST (16/11/2026). `tools/tester_cmds.py` teste les `.cmd` de la racine — mais
uniquement ceux inscrits à son registre. `RATTRAPAGE.cmd` (ajouté le 15/11) et
`CERTIFIER_EN_CONTINU.cmd` (publié sur `origin/main` sans rôle déclaré) n'y étaient pas : ils
n'étaient donc testés par **personne**, et rien ne le signalait. Un lanceur oublié est un lanceur
qui casse en silence.

Ce test rend l'oubli impossible : tout `.cmd` de la racine doit être au registre, avec une
catégorie explicite.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _harnais():
    spec = importlib.util.spec_from_file_location(
        "tester_cmds_pour_test", RACINE / "tools" / "tester_cmds.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("tester_cmds_pour_test", module)
    spec.loader.exec_module(module)
    return module


def test_chaque_cmd_de_la_racine_est_au_registre():
    harnais = _harnais()
    racine_cmd = {p.name for p in RACINE.glob("*.cmd")}
    au_registre = {entree[1] for entree in harnais.REGISTRE}
    oublies = sorted(racine_cmd - au_registre)
    assert oublies == [], (
        f"lanceurs de la racine absents du harnais : {oublies}. Un .cmd qui n'est au registre de "
        "personne n'est teste par personne.")


def test_le_registre_ne_vise_que_des_fichiers_qui_EXISTENT():
    harnais = _harnais()
    fantomes = sorted({e[1] for e in harnais.REGISTRE if not (RACINE / e[1]).is_file()})
    assert fantomes == [], f"entrees pointant vers un fichier absent : {fantomes}"


def test_chaque_entree_a_une_categorie_connue():
    harnais = _harnais()
    for nom, fichier, args, timeout, categorie in harnais.REGISTRE:
        assert categorie in {"sur", "long", "danger"}, f"{nom} : categorie {categorie!r}"
        assert isinstance(args, list), nom
        assert timeout >= 0, nom
        if categorie == "danger":
            assert timeout == 0, (
                f"{nom} : un lanceur a effet externe ne doit JAMAIS avoir de timeout non nul, "
                "sinon une passe automatique pourrait le lancer")


def test_les_lanceurs_a_effet_EXTERNE_restent_en_danger():
    """Pousser sur GitHub ou installer un nœud ne doit jamais partir d'une passe de test."""
    harnais = _harnais()
    dangereux = {e[1] for e in harnais.REGISTRE if e[4] == "danger"}
    for fichier in ("POUSSER-GITHUB.cmd", "Installer Noeud HL.cmd", "Noeud-HL.cmd"):
        assert fichier in dangereux, f"{fichier} doit rester en categorie danger"


def test_les_services_CONTINUS_ne_sont_pas_dans_la_passe_sure():
    """Les relancer pendant une campagne la tuerait : le harnais arrête les collecteurs à la fin."""
    harnais = _harnais()
    par_fichier = {e[1]: e[4] for e in harnais.REGISTRE}
    for fichier in ("LANCER_COLLECTEURS_COPY_VAULT.cmd", "LANCER_HYPERSMART.cmd",
                    "CERTIFIER_EN_CONTINU.cmd"):
        assert par_fichier.get(fichier) == "long", (
            f"{fichier} est un service continu : en categorie 'sur' il serait lance pendant une "
            "campagne, et le harnais arreterait les collecteurs en partant")


def test_l_entree_PREFLIGHT_passe_vraiment_un_preflight():
    """16/11 : l'entrée s'appelait `ALINA_SYNC_preflight` mais ne passait AUCUN argument.

    Sans argument, `ALINA_SYNC_COMPLETE.cmd` retombe sur son défaut
    `--download-safe --all-safe --unpack-safe` : une passe de test déclenchait donc le
    téléchargement et la décompression de tout le corpus SAFE (15 456 lots). Le nom mentait sur
    l'effet — exactement le genre d'écart qui fait qu'on croit avoir testé quelque chose.
    """
    harnais = _harnais()
    entree = next(e for e in harnais.REGISTRE if e[0] == "ALINA_SYNC_preflight")
    assert "--preflight-only" in entree[2], (
        f"args {entree[2]} : une entree nommee preflight doit EN passer un")


def test_le_harnais_ne_compte_plus_le_BRUIT_comme_une_panne():
    """16/11 : les 5 lanceurs de la passe sûre ressortaient « A VOIR » avec 5 à 12 CRITIQUE
    chacun, et aucune n'était réelle. Un verdict illisible est un verdict qu'on cesse de lire.

    Le filtre est IMPORTÉ de `rapport_collecteurs` : une seule règle de tri dans le dépôt.
    """
    harnais = _harnais()
    bruit = [
        "[candles] 1d termine : 0 bougies, 263/263 deja a jour | 0 refus encaisse(s)",
        'log_schema="3" status="SUCCESS" operation="python-version-dependencies-critical"',
        "[contexte] vivant : 740 positions, 107 portefeuilles, 0 reconnexions",
        "[vaults] 188 ecrits pour 94 leaders (echecs 0)",
    ]
    comptes, _lignes = harnais.scanner("\n".join(bruit))
    assert sum(comptes.values()) == 0, (
        f"du bruit attendu est compte comme panne : {comptes}")


def test_le_harnais_attrape_TOUJOURS_une_vraie_panne():
    """Le filtre ne doit pas rendre le harnais aveugle."""
    harnais = _harnais()
    vraies = [
        "Traceback (most recent call last):",
        "ModuleNotFoundError: No module named 'hl_observer'",
        "'attrapage_complet.py' n'est pas reconnu en tant que commande interne",
        '[NO_GO] Python 3 introuvable',
    ]
    comptes, lignes = harnais.scanner("\n".join(vraies))
    assert comptes["CRITIQUE"] >= 3, f"{comptes} — une vraie panne doit toujours remonter"
    assert any("Traceback" in l for l in lignes["CRITIQUE"])
