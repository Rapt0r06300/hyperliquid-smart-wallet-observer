"""Le DEFAUT du code ne doit jamais etre une perte garantie par arithmetique.

L'HISTOIRE (2026-07-13)
-----------------------
Le garde-fou breakeven (T3c) refusait 100 % des entrees dans deux tests UI. On aurait pu croire
a un garde-fou trop severe. Il avait RAISON :

    defaut du code : TP=30, SL=40, cout=12  ->  breakeven = (40+12)/(30+40) = 74 %
    lanceur        : TP=110, SL=60, cout=12 ->  breakeven = (60+12)/(110+60) = 42 %

Un winrate d'equilibre de 74 % n'est pas atteignable : cette structure de sortie PERD, par
arithmetique, quel que soit le signal. La production n'etait sauvee que parce que le LANCEUR
ecrasait les valeurs -- le motif exact qui nous a deja coute le poller L2 et le funding
(« une capacite presente, un chainon manquant, et personne ne se plaint »).

Ce test verrouille la seule chose qui compte : **le defaut, seul, doit etre jouable.** Si
quelqu'un rabote le TP « pour prendre ses profits plus tot » sans regarder les frais, ce test
rougit avant que le PnL ne le dise.
"""

from __future__ import annotations

import pytest

from hl_observer.paper_trading.barrier_calibration import breakeven_winrate
from hl_observer.paper_trading.sltp_runtime import sltp_config_from_env

# Cout aller-retour reel mesure sur Hyperliquid (entree + sortie). Voir docs/audit.
COUT_ALLER_RETOUR_BPS = 12.0
# Au-dela, on ne parle plus de strategie mais d'esperance de perte : meme un bon signal ne suffit
# pas. 60 % est deja genereux -- le copy-trading mesure ne depasse pas 50 %.
PLAFOND_BREAKEVEN_PCT = 60.0


@pytest.fixture()
def env_sltp_actif(monkeypatch):
    """On active SL/TP et on n'ecrit AUCUNE barriere : on veut juger le DEFAUT NU."""
    monkeypatch.setenv("HYPERSMART_SLTP_ENABLED", "1")
    for cle in ("HYPERSMART_SLTP_TAKE_PROFIT_BPS", "HYPERSMART_SLTP_STOP_LOSS_BPS"):
        monkeypatch.delenv(cle, raising=False)


def test_le_DEFAUT_du_code_est_jouable_sans_aucun_flag(env_sltp_actif):
    """🔴 SANS le lanceur, le code doit deja etre honnete.

    C'est LA lecon des deux jambes (funding repare, L2 oublie) : ne jamais dependre d'un flag
    externe pour ne pas perdre.
    """
    cfg = sltp_config_from_env()
    assert cfg is not None

    tp = float(cfg.take_profit_bps)
    sl = float(cfg.stop_loss_bps)
    be = breakeven_winrate(tp, sl, COUT_ALLER_RETOUR_BPS) * 100.0

    assert be <= PLAFOND_BREAKEVEN_PCT, (
        "Le DEFAUT du code exige %.0f %% de winrate pour ne rien gagner (TP=%.0f SL=%.0f "
        "cout=%.0f). C'est une perte garantie par arithmetique -- et le lanceur ne sera pas "
        "toujours la pour l'ecraser." % (be, tp, sl, COUT_ALLER_RETOUR_BPS)
    )


def test_le_defaut_du_code_EGALE_celui_du_lanceur(env_sltp_actif):
    """Deux sources de verite qui divergent, c'est un bug qui attend son heure (audit du 11/07)."""
    cfg = sltp_config_from_env()
    assert (float(cfg.take_profit_bps), float(cfg.stop_loss_bps)) == (110.0, 60.0), (
        "Le defaut du code ne correspond plus au lanceur (LANCER_HYPERSMART.cmd : TP=110, SL=60). "
        "Si l'un des deux change, l'autre doit suivre -- sinon le comportement depend de COMMENT "
        "on demarre, ce qui est precisement le bug qu'on a deja paye deux fois."
    )


def test_l_ANCIEN_defaut_aurait_bien_ete_refuse(env_sltp_actif):
    """🚩 Un garde-fou qui ne peut pas mordre ne garde rien : on prouve qu'il MORD.

    On rejoue l'ancien defaut (30/40) et on verifie qu'il depasse le plafond. Sans ce test, on
    pourrait croire que le plafond de 60 % est decoratif.
    """
    be_ancien = breakeven_winrate(30.0, 40.0, COUT_ALLER_RETOUR_BPS) * 100.0
    assert be_ancien > PLAFOND_BREAKEVEN_PCT
    assert round(be_ancien) == 74, "l'arithmetique de l'autopsie a change : %.1f" % be_ancien
