"""Le capital PAPER du contrat, et rien d'autre.

POURQUOI CE MODULE EXISTE. Le capital vivait dans ``backtesting.copy_vault_protocol``. Or importer
ce module execute ``hl_observer/backtesting/__init__.py``, qui charge tout le moteur de backtest :
experiment -> evidence -> decision_ledger -> paper_trading -> paper_engine -> ... -> simulation.
Le jour ou ``simulation/paper_ledger.py`` a eu besoin du capital pour sa valeur par defaut, le
cycle s'est ferme et le paquet est devenu inimportable :

    ImportError: cannot import name 'PaperLedger' from partially initialized module
                 'hl_observer.simulation.paper_ledger' (most likely due to a circular import)

Une CONSTANTE DE CONTRAT ne doit dependre de rien. Celle-ci est lue par le moteur de backtest, le
grand livre paper, les controles de risque, l'interface et le laboratoire : la placer dans l'un
d'eux force tous les autres a charger celui-la. Ce module n'importe donc AUCUN module interne, et
il ne doit jamais en importer -- c'est ce qui le rend citable de partout.

``copy_vault_protocol`` reexporte ces noms, de sorte que tout le code existant qui fait
``from hl_observer.backtesting.copy_vault_protocol import PAPER_EQUITY_USD`` continue de marcher.
"""

from __future__ import annotations

#: Le capital paper du contrat. Passe de 350 a 100 USD le 18/11/2026.
#:
#: C'est du PAPER : ce montant n'est pas une mise, c'est l'UNITE DE MESURE des resultats. Le
#: choisir petit rend la mesure plus honnete -- 100 USD se placent sans deplacer le carnet, donc un
#: gain mesure a cette taille est un gain que le marche peut reellement donner. Les diagnostics de
#: capacite rejouent la politique gelee sur une echelle de capitaux plus large, en marquant leurs
#: resultats ``DIAGNOSTIC_ONLY`` : on regarde plus haut sans jamais confondre les deux.
PAPER_EQUITY_USD = 100.0

#: Aucun levier sur le capital paper.
PAPER_LEVERAGE = 1.0

#: L'exposition brute maximale. Une ligne ne peut jamais depasser le capital qui la finance.
MAX_GROSS_EXPOSURE_USD = PAPER_EQUITY_USD * PAPER_LEVERAGE

#: REPERE D'AFFICHAGE, JAMAIS UNE CONDITION.
#:
#: Le contrat du 18/11/2026 retire tout objectif chiffre des regles ACTIVES : le but est de
#: maximiser le PnL net causal reproductible, sans cible fixe, sous contraintes de risque, de cout,
#: de drawdown, d'exposition, de liquidite et de capacite. Ce nombre survit uniquement pour que les
#: rapports puissent situer un resultat par rapport a l'ancien repere de recherche ; aucune porte,
#: aucune promotion et aucun verdict ne doit le lire comme un seuil. Un gel qui s'arrete de gagner
#: mesure sa propre regularite, pas son avantage.
PAPER_TARGET_NET_USD_PER_DAY = 5.0

__all__ = [
    "MAX_GROSS_EXPOSURE_USD",
    "PAPER_EQUITY_USD",
    "PAPER_LEVERAGE",
    "PAPER_TARGET_NET_USD_PER_DAY",
]
