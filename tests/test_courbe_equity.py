"""LA COURBE D'EQUITY — le métagraphe ne doit plus jamais mentir (21/07).

Le bug corrigé ici n'était pas graphique. La courbe servie contenait 600 points valant TOUS
1 000,00 $ (pile copy éteinte), et le PnL carry était greffé sur le dernier point : à l'écran,
599 points immobiles puis une falaise verticale. Ces tests verrouillent les quatre propriétés
qui l'empêchent de revenir.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.ui import courbe_equity as ce


def _ledger(tmp_path, lignes):
    from hl_observer.funding.carry_positions_store import LEDGER_RELPATH
    p = tmp_path / LEDGER_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(l) for l in lignes) + "\n", encoding="utf-8")
    return tmp_path


# 🔴 23/07 : le carry delta-neutre est RETIRÉ (exclu de la courbe live par défaut). Ces tests vérifient
# la MÉCANIQUE de la courbe (agnostique à la stratégie) -> on utilise une stratégie VIVANTE (arbitrage).
def _close(ts, pnl, coin="BTC", mode="LIVE", strategie="arbitrage"):
    return {"kind": "CLOSE", "mode": mode, "ts_ms": ts, "realized_net_pnl_usdc": pnl,
            "coin": coin, "strategie": strategie}


def test_le_carry_retire_est_exclu_de_la_courbe_live_mais_reste_au_ledger(tmp_path):
    """🔴 23/07 (décision Flo) — les CLOSE du carry retiré n'entrent plus dans la courbe LIVE ;
    l'arbitrage du même ledger reste. Tout est réaffichable (audit) via exclure_strategies=∅."""
    root = _ledger(tmp_path, [_close(1000, -10.0, strategie="carry"),
                              _close(2000, -2.0, strategie="arbitrage")])
    c = ce.construire(root, now_ms=3000)
    assert c["evenements"] == 1 and c["realise_cumule"] == pytest.approx(-2.0)   # seul l'arbitrage
    assert len(ce.evenements_realises(root, exclure_strategies=frozenset())) == 2   # audit : voit tout


# ─────────────────────────── la série vient du ledger ───────────────────────────

def test_la_courbe_bouge_quand_le_ledger_bouge(tmp_path):
    """LE test du bug : une equity qui reste plate alors que des trades se ferment."""
    root = _ledger(tmp_path, [_close(1000, -2.0, "HYPE"), _close(2000, +0.5, "ZEC")])
    c = ce.construire(root, now_ms=3000)
    assert c["evenements"] == 2
    assert c["plate"] is False
    assert c["amplitude_usd"] > 0, "une equity qui bouge doit avoir une amplitude non nulle"
    assert c["realise_cumule"] == pytest.approx(-1.5)
    # départ + 2 événements + maintenant
    assert [p["equity"] for p in c["points"]] == pytest.approx([1000.0, 998.0, 998.5, 998.5])


def test_le_dernier_point_vaut_le_pnl_stable_du_bandeau(tmp_path):
    """L'INVARIANT central : la courbe et le grand chiffre lisent la MÊME vérité.

    `stable_net_pnl = réalisé + funding RÉGLÉ`. Si le dernier point de la courbe s'en écarte,
    l'écran affiche deux nombres pour une seule réalité — ce que CLAUDE.md interdit.
    """
    root = _ledger(tmp_path, [_close(1000, -6.0)])
    c = ce.construire(root, funding_regle_usd=0.35, now_ms=2000)
    stable = -6.0 + 0.35
    assert c["points"][-1]["pnl"] == pytest.approx(stable)
    assert c["points"][-1]["equity"] == pytest.approx(1000.0 + stable)


def test_le_funding_ne_retro_projette_jamais_sur_le_passe(tmp_path):
    """Le funding réglé n'a pas d'historique horodaté : il n'a le droit de toucher QUE le
    point courant. L'appliquer au passé serait réécrire l'histoire."""
    root = _ledger(tmp_path, [_close(1000, -1.0), _close(2000, -1.0)])
    c = ce.construire(root, funding_regle_usd=5.0, now_ms=3000)
    assert c["points"][1]["equity"] == pytest.approx(999.0)
    assert c["points"][2]["equity"] == pytest.approx(998.0)
    assert c["points"][-1].get("inclut_funding_courant") is True
    assert c["points"][-1]["equity"] == pytest.approx(1003.0)


def test_seul_le_mode_demande_entre_dans_la_courbe(tmp_path):
    """LIVE / BACKTEST / REPLAY ne se mélangent jamais — un PnL de replay dans la courbe
    live serait un PnL fabriqué."""
    root = _ledger(tmp_path, [_close(1000, -1.0, mode="LIVE"),
                              _close(1500, +99.0, mode="REPLAY"),
                              _close(2000, -1.0, mode="LIVE")])
    c = ce.construire(root, now_ms=3000)
    assert c["evenements"] == 2
    assert c["realise_cumule"] == pytest.approx(-2.0)


def test_une_ligne_sans_horodatage_est_ignoree_pas_devinee(tmp_path):
    root = _ledger(tmp_path, [{"kind": "CLOSE", "mode": "LIVE", "realized_net_pnl_usdc": -1.0},
                              {"kind": "CLOSE", "mode": "LIVE", "ts_ms": 2000},
                              _close(3000, -1.0)])
    c = ce.construire(root, now_ms=4000)
    assert c["evenements"] == 1, "on ne devine pas QUAND un gain a eu lieu"


def test_les_evenements_sont_tries_dans_le_temps(tmp_path):
    root = _ledger(tmp_path, [_close(3000, -1.0), _close(1000, -1.0), _close(2000, -1.0)])
    c = ce.construire(root, now_ms=4000)
    ts = [p["t"] for p in c["points"]]
    assert ts == sorted(ts), "une courbe qui recule dans le temps dessine des zigzags"


def test_ledger_absent_donne_une_ligne_plate_declaree(tmp_path):
    """Aucune donnée -> on le DIT (`plate`), on ne dessine pas du bruit."""
    c = ce.construire(tmp_path, now_ms=1_000_000)
    assert c["plate"] is True and c["evenements"] == 0
    assert c["amplitude_usd"] == pytest.approx(0.0)
    assert len(c["points"]) == 2, "départ + maintenant : de quoi tracer une ligne plate honnête"


def test_le_plafond_de_points_garde_le_depart_et_le_present(tmp_path):
    """Tronquer par le milieu est acceptable ; perdre la base ou le point courant ne l'est
    pas — c'est le CADRE du graphe qui se mettrait alors à mentir."""
    root = _ledger(tmp_path, [_close(1000 + i, -0.01) for i in range(300)])
    c = ce.construire(root, now_ms=999_999, max_points=50)
    assert len(c["points"]) <= 50
    assert c["points"][0]["evenement"] == "DEPART"
    assert c["points"][0]["equity"] == pytest.approx(1000.0)
    assert c["points"][-1]["evenement"] == "MAINTENANT"


# ─────────────────────────── bornes : le cas dégénéré est TRAITÉ ───────────────────────────

def test_amplitude_nulle_ne_fabrique_pas_une_echelle(tmp_path):
    """`rng = (hi-lo) || 1` écrasait tous les points sur une ligne et rendait le moindre
    point vivant vertical. Une amplitude nulle doit produire une fenêtre finie ET déclarée."""
    b = ce.bornes_affichage([{"equity": 1000.0}, {"equity": 1000.0}])
    assert b["degenere"] is True and b["motif"]
    assert b["lo"] < 1000.0 < b["hi"]
    assert 0 < (b["hi"] - b["lo"]) < 20.0, "fenêtre serrée : la ligne plate reste au centre"


def test_bornes_sans_aucun_point(tmp_path):
    b = ce.bornes_affichage([])
    assert b["degenere"] is True and b["hi"] > b["lo"]


def test_bornes_normales_encadrent_les_valeurs(tmp_path):
    b = ce.bornes_affichage([{"equity": 990.0}, {"equity": 1010.0}])
    assert b["degenere"] is False
    assert b["lo"] < 990.0 and b["hi"] > 1010.0


# ─────────────────────────── fusion de la pile copy ───────────────────────────

def test_une_pile_copy_a_plat_n_ecrase_pas_la_courbe(tmp_path):
    """LA CAUSE RACINE : 600 points copy identiquement nuls prenaient le dessus sur le
    ledger. Ils doivent être mesurés, constatés plats, et ignorés — en le disant."""
    root = _ledger(tmp_path, [_close(1000, -6.0)])
    c = ce.construire(root, funding_regle_usd=0.35, now_ms=2000)
    plate = [{"t": 900 + i, "equity": 1000.0, "pnl": 0.0} for i in range(600)]
    f = ce.fusionner_copy(c, plate)
    assert f["copy_fusionnee"] is False and "plat" in f["copy_motif"]
    assert f["points"][-1]["equity"] == pytest.approx(c["points"][-1]["equity"])
    assert f["amplitude_usd"] > 0


def test_une_pile_copy_qui_bouge_est_bien_fusionnee(tmp_path):
    root = _ledger(tmp_path, [_close(2000, -1.0)])
    c = ce.construire(root, now_ms=3000)
    copy = [{"t": 1500, "equity": 1002.0, "pnl": 2.0}, {"t": 2500, "equity": 1003.0, "pnl": 3.0}]
    f = ce.fusionner_copy(c, copy)
    assert f["copy_fusionnee"] is True
    assert any("copy" in s for s in f["sources"])
    assert f["points"][-1]["pnl"] == pytest.approx(-1.0 + 3.0)


def test_la_copy_ne_contribue_rien_avant_sa_premiere_mesure(tmp_path):
    """Avant la 1ʳᵉ mesure copy, sa contribution est 0 — pas sa première valeur projetée
    en arrière. Rétro-projeter, c'est exactement le geste qu'on vient de bannir."""
    root = _ledger(tmp_path, [_close(1000, 0.0)])
    c = ce.construire(root, now_ms=5000)
    f = ce.fusionner_copy(c, [{"t": 4000, "equity": 1007.0, "pnl": 7.0}])
    assert f["points"][1]["copy_pnl"] == pytest.approx(0.0)
    assert f["points"][-1]["copy_pnl"] == pytest.approx(7.0)


def test_la_courbe_enumere_toujours_ses_sources(tmp_path):
    """Une courbe qui ne sait pas dire ce qu'elle contient finira par en oublier un morceau —
    c'est précisément comment le carry avait disparu de l'écran."""
    c = ce.construire(tmp_path, now_ms=1000)
    for pts in (None, [], [{"t": 1, "equity": 1000.0, "pnl": 0.0}]):
        f = ce.fusionner_copy(c, pts)
        assert f["sources"] and all(isinstance(s, str) and s for s in f["sources"])


def test_aucune_execution_reelle(tmp_path):
    c = ce.construire(tmp_path, now_ms=1000)
    assert c["real_execution"] is False
