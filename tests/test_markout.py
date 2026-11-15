"""Le markout : ce qu'un remplissage coute APRES le fill — la moitie qui manquait.

Le 14/11 au matin, `maker_fill_probe` a mesure le taux de remplissage (48,2 %) et le gain de
spread (0,0421 USD) : la moitie FAVORABLE. La decomposition complete est
`net = capture + adverse - frais`, et la litterature mesure que sur Hyperliquid la seconde moitie
est PLUS GROSSE que la premiere (Daru Finance, 125,8 M de remplissages simules, meme hypothese de
file que la notre : capture +0,56 bp, derive a 10 s -1,02 bp, net -0,46 bp AVANT frais).

Ces tests verrouillent les refus qui empechent de transformer un trou de donnees en bonne
nouvelle — c'est la seule facon qu'un markout a de mentir.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import markout as MK  # noqa: E402

INSTANTS = [0, 1000, 2000, 3000, 10_000]
MIDS = [100.0, 100.0, 99.0, 99.0, 98.0]


# ------------------------------------------------------------------ la jointure as-of

def test_on_prend_le_dernier_mid_A_OU_AVANT_la_cible():
    """« Au plus proche » peut resoudre APRES la cible : un markout a 100 ms deviendrait un
    markout a 1,9 s avec un trou de 1,9 s, sans que rien ne le signale."""
    valeur, motif = MK.mid_prevalant(INSTANTS, MIDS, 1999, peremption_ms=None)
    assert valeur == 100.0 and motif is None      # et PAS 99.0 (qui est a 2000, apres)


def test_sans_mid_AVANT_le_fill_on_refuse_au_lieu_de_regarder_apres():
    valeur, motif = MK.mid_prevalant(INSTANTS, MIDS, -1, peremption_ms=None)
    assert valeur is None and motif == MK.SANS_REFERENCE


def test_un_mid_trop_VIEUX_est_refuse():
    """Un mid traine a travers un trou de flux est aussi faux qu'un mid invente ; il echoue
    seulement en silence."""
    valeur, motif = MK.mid_prevalant(INSTANTS, MIDS, 9000, peremption_ms=1000)
    assert valeur is None and motif == MK.PERIME


# ------------------------------------------------------------------ la decomposition

def test_capture_et_derive_sur_un_achat_passif():
    """Achat passif a 99,5 quand le mid vaut 100 : on encaisse un demi-spread, puis le mid tombe."""
    r = MK.markout_d_un_fill(prix_fill=99.5, cote=MK.ACHAT, instant_ms=0,
                             instants=INSTANTS, mids=MIDS, horizons_ms=[2000],
                             peremption_ms=None)
    assert r["verdict"] == MK.MESURE
    assert abs(r["capture_bps"] - 50.0) < 1e-6          # (100 - 99.5)/100 = 50 bp
    assert abs(r["par_horizon"][2000]["adverse_bps"] + 100.0) < 1e-6   # (99-100)/100 = -100 bp
    assert abs(r["par_horizon"][2000]["net_bps"] + 50.0) < 1e-6        # la derive reprend plus


def test_le_SIGNE_est_inverse_pour_une_vente_passive():
    """Oublier l'inversion retourne toute la courbe du cote vente."""
    r = MK.markout_d_un_fill(prix_fill=100.5, cote=MK.VENTE, instant_ms=0,
                             instants=INSTANTS, mids=MIDS, horizons_ms=[2000],
                             peremption_ms=None)
    assert abs(r["capture_bps"] - 50.0) < 1e-6
    assert abs(r["par_horizon"][2000]["adverse_bps"] - 100.0) < 1e-6   # le prix BAISSE : favorable


def test_un_horizon_hors_donnees_est_TRONQUE_et_pas_zero():
    """LE piege : prolonger par le dernier prix connu produit un markout de 0,0 et transforme
    un trou de donnees en « aucune derive »."""
    r = MK.markout_d_un_fill(prix_fill=99.5, cote=MK.ACHAT, instant_ms=0,
                             instants=INSTANTS, mids=MIDS, horizons_ms=[60_000],
                             peremption_ms=None)
    details = r["par_horizon"][60_000]
    assert details["motif"] == MK.TRONQUE
    assert details["net_bps"] is None and details["adverse_bps"] is None


# ------------------------------------------------------------------ l'agregation

def _fill(net_par_horizon: dict[int, float]) -> dict:
    return {"verdict": MK.MESURE, "capture_bps": 1.0,
            "par_horizon": {h: {"motif": None, "adverse_bps": v - 1.0, "net_bps": v}
                            for h, v in net_par_horizon.items()}}


def test_aucun_horizon_exploitable_n_est_PAS_un_flux_sain():
    """`toxique=False` sans donnee voudrait dire « sain ». C'est « rien n'a ete mesure »."""
    r = MK.agreger([{"verdict": MK.NON_MESURABLE, "motif": MK.SANS_REFERENCE}],
                   horizons_ms=[1000])
    assert r["verdict"] == MK.NON_MESURABLE
    assert "PAS" in r["lecture"] and "toxique" not in r.get("lecture", "").split("PAS")[0]


def test_un_horizon_sans_donnee_ne_VOTE_pas():
    """Sinon une fenetre courte diluerait silencieusement une courbe franchement toxique."""
    resultats = [_fill({1000: -2.0}) for _ in range(5)]
    r = MK.agreger(resultats, horizons_ms=[1000, 60_000])
    assert r["horizons_exploitables"] == [1000]
    assert r["par_horizon"][60_000]["verdict"] == MK.NON_MESURABLE
    assert r["toxique"] is True          # 1 horizon sur 1, pas 1 sur 2


def test_les_frais_sont_SOUSTRAITS_explicitement():
    """Un net « avant frais » positif peut devenir negatif une fois le frais paye."""
    resultats = [_fill({1000: 0.3}) for _ in range(10)]
    sans = MK.agreger(resultats, horizons_ms=[1000], frais_bps=0.0)
    avec = MK.agreger(resultats, horizons_ms=[1000], frais_bps=0.5)
    assert sans["toxique"] is False and avec["toxique"] is True


def test_la_distribution_est_publiee_pas_seulement_la_moyenne():
    """Une queue de quelques fills tres mal selectionnes cache une mediane saine."""
    resultats = [_fill({1000: 1.0}) for _ in range(9)] + [_fill({1000: -100.0})]
    r = MK.agreger(resultats, horizons_ms=[1000])
    details = r["par_horizon"][1000]
    assert details["net_moyen_bps"] < 0          # la moyenne est tiree par la queue
    assert details["net_median_bps"] > 0         # la mediane reste saine
    assert "net_p25_bps" in details and "net_p75_bps" in details


def test_les_ecartes_sont_comptes_par_motif():
    r = MK.agreger([{"verdict": MK.NON_MESURABLE, "motif": MK.PERIME},
                    {"verdict": MK.NON_MESURABLE, "motif": MK.SANS_REFERENCE},
                    _fill({1000: 1.0})], horizons_ms=[1000])
    assert r["ecartes"] == {MK.PERIME: 1, MK.SANS_REFERENCE: 1}


# ------------------------------------------------------- L'ATTRIBUTION DE LA CAPTURE

def test_sans_instant_d_ordre_la_capture_peut_sortir_NEGATIVE():
    """Le defaut historique, conserve et documente : `m0` pris au FILL replie la derive d'attente
    dans la capture. C'est ce qui a produit une capture de -6,01 bp le 14/11 — impossible par
    construction, puisqu'on place toujours SOUS le mid a l'achat."""
    instants = [0, 1000, 2000]
    mids = [100.0, 99.0, 98.9]          # le mid DESCEND pendant l'attente
    r = MK.markout_d_un_fill(prix_fill=99.5, cote=MK.ACHAT, instant_ms=1000,
                            instants=instants, mids=mids, horizons_ms=[1000],
                            peremption_ms=60_000)
    assert r["verdict"] == MK.MESURE
    assert r["capture_bps"] < 0          # achat a 99,5 contre un mid de 99 au fill


def test_avec_l_instant_d_ordre_la_capture_redevient_POSITIVE():
    """Au moment du PLACEMENT, le mid etait a 100 et l'ordre a 99,5 : un vrai demi-spread."""
    instants = [0, 1000, 2000]
    mids = [100.0, 99.0, 98.9]
    r = MK.markout_d_un_fill(prix_fill=99.5, cote=MK.ACHAT, instant_ms=1000,
                            instants=instants, mids=mids, horizons_ms=[1000],
                            peremption_ms=60_000, instant_ordre_ms=0)
    assert abs(r["capture_bps"] - 50.0) < 1e-6      # (100 - 99,5)/100 = +50 bp, un VRAI demi-spread
    assert r["attente_bps"] is not None
    assert abs(r["attente_bps"] + 100.0) < 1e-6     # (99 - 100)/100 = -100 bp : l'attente a COUTE


def test_le_NET_est_INCHANGE_par_le_changement_d_attribution():
    """Le point qui compte : `net = eps(m_tau - p)/m0`, le choix de la reference s'annule. Seule
    l'ATTRIBUTION change. Si le net bougeait, la correction serait une falsification."""
    instants = [0, 1000, 2000]
    mids = [100.0, 99.0, 98.9]
    sans = MK.markout_d_un_fill(prix_fill=99.5, cote=MK.ACHAT, instant_ms=1000,
                               instants=instants, mids=mids, horizons_ms=[1000],
                               peremption_ms=60_000)
    avec = MK.markout_d_un_fill(prix_fill=99.5, cote=MK.ACHAT, instant_ms=1000,
                               instants=instants, mids=mids, horizons_ms=[1000],
                               peremption_ms=60_000, instant_ordre_ms=0)
    n_sans = sans["par_horizon"][1000]["net_bps"]
    n_avec = avec["par_horizon"][1000]["net_bps"]
    # L'invariant EXACT n'est pas le net lui-meme mais son NUMERATEUR : `eps(m_tau - p)`. Les deux
    # lectures ne different que par la normalisation (99,0 contre 100,0), soit 1 %. Exiger une
    # egalite stricte du net serait exiger que deux normalisations donnent le meme nombre.
    assert abs(n_sans * sans["mid_reference"] - n_avec * avec["mid_reference"]) < 1e-6
    assert abs(n_avec - n_sans) / abs(n_sans) < 0.02      # et l'ecart reste de l'ordre du 1 %


def test_la_decomposition_se_RECOMPOSE_exactement():
    instants = [0, 1000, 2000]
    mids = [100.0, 99.0, 98.9]
    r = MK.markout_d_un_fill(prix_fill=99.5, cote=MK.ACHAT, instant_ms=1000,
                            instants=instants, mids=mids, horizons_ms=[1000],
                            peremption_ms=60_000, instant_ordre_ms=0)
    d = r["par_horizon"][1000]
    somme = r["capture_bps"] + r["attente_bps"] + d["adverse_bps"]
    assert abs(d["net_bps"] - somme) < 1e-9          # +50 - 100 - 10 = -60 bp, exactement
