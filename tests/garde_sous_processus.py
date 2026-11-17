"""GARDE : aucun test ne doit laisser `subprocess` remplacé derrière lui.

LE DÉFAUT, TROUVÉ LE 17/11/2026 PAR LA SUITE COMPLÈTE. `tests/test_sync_git_robustesse.py` posait
un espion ainsi :

    module.subprocess.run = faux_run          # faux_run rend returncode=0, stdout="ok"

`module.subprocess` EST le module `subprocess` global : l'affectation remplaçait donc
`subprocess.run` pour tout le processus, et rien ne la défaisait. Tout test exécuté ensuite dans le
même processus recevait un faux succès à la place de son vrai sous-processus.

Conséquence mesurée sur la suite complète (4 ouvriers) : **7 échecs sans rapport apparent** —
l'audit de sécurité annonçait « .env is tracked by git » (il croyait que git avait répondu), une
empreinte de manifeste valait `ok`, un lanceur censé refuser « réussissait ». Rejoués seuls, ils
passaient tous : la cause n'était pas en eux. Et le pire n'est pas ces 7 rouges : c'est le nombre
inconnu de tests qui passaient AU VERT pour la même raison, en affirmant sur un `returncode == 0`
que le faux leur servait.

Ce garde restaure les fonctions réelles et DÉSIGNE le module fautif, à la fin de ce module — là où
la fuite se produit, pas huit fichiers plus loin.
"""
from __future__ import annotations

import subprocess

#: Les fonctions réelles, capturées à l'import — avant qu'aucun test n'ait pu les remplacer.
REELS = {
    "run": subprocess.run,
    "Popen": subprocess.Popen,
    "call": subprocess.call,
    "check_call": subprocess.check_call,
    "check_output": subprocess.check_output,
}


def fuites_et_restauration() -> list[str]:
    """Rend les noms de `subprocess` restés remplacés, APRÈS les avoir restaurés.

    Restaurer avant de signaler est délibéré : la fuite d'un module ne doit pas contaminer les
    suivants, même si le signalement échoue.
    """
    fuites = [nom for nom, reel in REELS.items() if getattr(subprocess, nom) is not reel]
    for nom in fuites:
        setattr(subprocess, nom, REELS[nom])
    return fuites


__all__ = ["REELS", "fuites_et_restauration"]
