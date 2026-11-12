"""Le lanceur de 6 jours lance-t-il VRAIMENT ce qu'on croit ? (piege trouve le 12/11/2026)

CE QUI S'ETAIT PASSE. `userfills-poll` et `contexte-leaders` venaient d'etre ajoutes au REGISTRE et
au profil `harvest`, et tout etait vert. Mais la campagne de 6 jours se lance par
`LANCER_COLLECTEURS_COPY_VAULT.cmd`, qui appelle `watch_economic_collectors.py --profile copy-vault`,
lequel ignore completement les profils du registre et utilise sa PROPRE liste en dur `DEFAULT_NAMES`.
Pire : `CV_PROFILE=copy-vault` n'est meme jamais transmis au superviseur (il ne sert qu'a un `echo`),
et aucun profil « copy-vault » n'existe dans le registre. Les deux nouveaux collecteurs seraient donc
restes SILENCIEUSEMENT A L'ARRET pendant toute la campagne — six jours de collecte sans le levier qui
fait passer de 8 a ~120 leaders, decouverts seulement a la fin.

Deux sources de verite pour « quels collecteurs tournent » est deja fragile ; qu'elles divergent sans
que rien ne rougisse est inacceptable. Ces tests font rougir la divergence.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import collecteur_registry as R  # noqa: E402


def _watchdog():
    spec = importlib.util.spec_from_file_location(
        "watch_eco", RACINE / "tools" / "watch_economic_collectors.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tout_ce_que_le_lanceur_demande_existe_dans_le_registre():
    """Un nom mal orthographie ici ne lancerait rien, sans erreur visible."""
    connus = {c["nom"] for c in R.REGISTRE}
    inconnus = [n for n in _watchdog().DEFAULT_NAMES if n not in connus]
    assert inconnus == [], f"noms absents du registre : {inconnus}"


def test_les_collecteurs_de_LEADERS_sont_bien_lances_par_la_campagne():
    """LE test qui aurait evite de perdre six jours : sans eux, le labo ne voit que ~8 leaders,
    dont un seul porte 63 % des fills — il mesurerait un trader, pas une strategie."""
    noms = _watchdog().DEFAULT_NAMES
    for collecteur in ("userfills-poll", "contexte-leaders"):
        assert collecteur in noms, (
            f"{collecteur} est dans le registre mais PAS dans DEFAULT_NAMES : il ne tournera pas "
            "pendant la campagne de 6 jours (voir LANCER_COLLECTEURS_COPY_VAULT.cmd)")


def test_aucun_doublon_dans_la_liste_du_lanceur():
    noms = list(_watchdog().DEFAULT_NAMES)
    assert len(noms) == len(set(noms))


def test_le_profil_copy_vault_du_cmd_N_EST_PAS_un_profil_du_registre():
    """On VERROUILLE le piege au lieu de faire semblant qu'il n'existe pas : tant que ce nom n'est
    pas un vrai profil, c'est bien `DEFAULT_NAMES` qui fait foi, et le test du dessus est le garde-fou.
    Le jour ou quelqu'un cree un vrai profil « copy-vault », ce test rougit et oblige a relire la
    chaine complete (.cmd -> watchdog -> registre) plutot qu'a croire qu'elle est deja coherente."""
    assert "copy-vault" not in R.PROFILS_VALIDES


def test_le_cmd_annonce_le_BON_nombre_de_collecteurs():
    """Un `echo` qui ment sur le nombre lance est un mensonge d'interface : on le verrouille."""
    texte = (RACINE / "LANCER_COLLECTEURS_COPY_VAULT.cmd").read_text(encoding="utf-8",
                                                                     errors="replace")
    attendu = len(_watchdog().DEFAULT_NAMES)
    assert f"echo   {attendu} collecteurs actifs" in texte, (
        f"le .cmd doit annoncer {attendu} collecteurs")


def test_les_collecteurs_de_LEADERS_sont_lançables_par_les_DEUX_chemins():
    """Les deux sources de verite doivent s'accorder sur les collecteurs qui portent la campagne.

    (Les autres entrees de `DEFAULT_NAMES` n'ont PAS a etre dans `harvest` : certaines appartiennent
    a d'autres profils. Exiger l'egalite des deux listes serait un test qui rougit pour rien ;
    on verrouille donc exactement ce qui compte, sans fabriquer une contrainte qui n'existe pas.)
    """
    noms = _watchdog().DEFAULT_NAMES
    for collecteur in ("userfills-poll", "contexte-leaders", "l2-leaders", "userfills-live"):
        assert collecteur in noms, f"{collecteur} ne tournerait pas pendant la campagne"
        assert collecteur in R.COLLECTEURS_HARVEST, f"{collecteur} absent du profil harvest"
