"""Les outils de la chasse à l'alpha (mission 2) : ce qu'ils REFUSENT, et ce qu'ils voient.

Un outil de recherche qui se trompe en silence fabrique de l'alpha. Chaque test ci-dessous
garde une erreur qui a réellement eu lieu ou qui aurait fabriqué un faux résultat :

- lire l'OOS final « par un filtre de date oublié » ;
- trier les fills d'une même milliseconde par `tid` (60 953 faux trous de position le 22/11) ;
- prendre une position pour « tenue » alors que rien ne le confirme ;
- compter deux fills d'un même leader comme un consensus ;
- comparer un événement à des jumeaux qui le recouvrent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
for _chemin in (ROOT / "src", ROOT / "tools"):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

import goal2_commun as G  # noqa: E402
import goal2_etude_consensus as C  # noqa: E402
import goal2_etude_position_en_perte as L1  # noqa: E402
import goal2_placebo_position_en_perte as P  # noqa: E402

H = G.HEURE_MS
T0 = G._ms(2026, 5, 1)


# ---------------------------------------------------------------- protocole
def test_l_oos_final_est_verrouille_par_defaut() -> None:
    with pytest.raises(PermissionError, match="OOS_FINAL_VERROUILLE"):
        G.bornes("oos_final")
    assert G.bornes("oos_final", ouvrir_oos_final=True) == G.SEGMENTS["oos_final"]
    with pytest.raises(ValueError):
        G.bornes("n_importe_quoi")


def test_les_segments_ne_se_chevauchent_pas() -> None:
    ordre = ["exploration", "validation", "execution", "oos_final"]
    for a, b in zip(ordre, ordre[1:]):
        assert G.SEGMENTS[a][1] == G.SEGMENTS[b][0], (a, b)


def test_une_marge_de_prix_ne_mord_jamais_sur_l_oos(tmp_path, monkeypatch) -> None:
    verrou = G.SEGMENTS["oos_final"][0]
    t = np.arange(verrou - 48 * H, verrou + 48 * H, H)
    pd.DataFrame({"coin": "BTC", "t_ms": t, "o": 1.0, "c": 1.0}).to_parquet(tmp_path / "candles_1h.parquet")
    monkeypatch.setattr(G, "CACHE", tmp_path)
    lu = G.charger("candles_1h", "execution", marge_apres_ms=30 * G.JOUR_MS)
    assert len(lu) == 48 and lu["t_ms"].max() < verrou


def test_un_essai_sans_nom_ni_statut_est_refuse_et_le_registre_est_chaine(tmp_path, monkeypatch) -> None:
    from etude_copiabilite import verify_ledger

    monkeypatch.setattr(G, "REGISTRE", tmp_path / "ESSAIS.ndjson")
    with pytest.raises(ValueError):
        G.enregistrer({"hypothese": "x", "segment": "exploration"})
    assert G.nombre_d_essais() == 0
    G.enregistrer({"hypothese": "a", "segment": "exploration", "statut": "EXPLORATION"})
    G.enregistrer({"hypothese": "b", "segment": "exploration", "statut": "EXPLORATION"})
    assert G.nombre_d_essais() == 2
    assert verify_ledger(G.REGISTRE)["records"] == 2


def test_le_bootstrap_est_deterministe_et_tire_des_blocs() -> None:
    v = np.array([1.0, 2.0, 3.0, np.nan, 10.0, 11.0])
    blocs = np.array([0, 0, 0, 0, 1, 1])
    assert G.ic_bootstrap_par_blocs(v, blocs) == G.ic_bootstrap_par_blocs(v, blocs)
    m, bas, haut = G.ic_bootstrap_par_blocs(v, blocs)
    assert m == pytest.approx(5.4) and bas <= m <= haut
    # un seul bloc : aucune dispersion a tirer -> l'intervalle s'effondre sur la moyenne
    m1, b1, h1 = G.ic_bootstrap_par_blocs(v, np.zeros(6))
    assert b1 == pytest.approx(m1) and h1 == pytest.approx(m1)
    assert all(np.isnan(x) for x in G.ic_bootstrap_par_blocs([np.nan], [0]))


# ---------------------------------------------------------------- positions
def _etats(lignes):
    ts, px, sz, signe, sp = (np.array(c, dtype=float) for c in zip(*lignes))
    return L1.etats_du_groupe(ts, px, sz, signe, sp)


def test_prix_moyen_renfort_reduction_retournement() -> None:
    apres, entree, connu, episode, coherent = _etats([
        (1, 100.0, 2.0, +1, 0.0),     # ouverture depuis le plat
        (2, 110.0, 2.0, +1, 2.0),     # renfort : (2*100 + 2*110) / 4 = 105
        (3, 120.0, 1.0, -1, 4.0),     # reduction : prix moyen inchange
        (4, 90.0, 5.0, -1, 3.0),      # retournement : court de 2 a 90
        (5, 80.0, 2.0, +1, -2.0),     # cloture a plat
    ])
    assert list(apres) == [2.0, 4.0, 3.0, -2.0, 0.0]
    assert list(entree[:4]) == [100.0, 105.0, 105.0, 90.0]
    assert connu.all() and coherent.all()
    assert episode[0] == episode[1] == episode[2] != episode[3]


def test_une_position_heritee_n_a_pas_de_prix_d_entree() -> None:
    _, entree, connu, _, _ = _etats([(1, 100.0, 1.0, +1, 5.0), (2, 101.0, 6.0, -1, 6.0), (3, 99.0, 1.0, +1, 0.0)])
    assert not connu[0] and np.isnan(entree[0])      # heritee d'avant la fenetre : jamais supposee
    assert connu[2] and entree[2] == 99.0            # rouverte depuis le plat : connue


def test_un_trou_invalide_l_etat() -> None:
    _, _, connu, _, coherent = _etats([(1, 100.0, 1.0, +1, 0.0), (2, 101.0, 1.0, +1, 3.0)])
    assert not coherent[0]          # le fill suivant ne prolonge pas celui-ci
    assert not connu[1]             # et le prix d'entree n'est plus fiable


def _bougies(prix_ouverture, coin="X") -> pd.DataFrame:
    o = np.asarray(prix_ouverture, dtype=float)
    c = np.append(o[1:], o[-1])     # la cloture d'une bougie = l'ouverture de la suivante
    return pd.DataFrame({"coin": coin, "t_ms": T0 + H * np.arange(len(o)), "o": o, "c": c})


def _fill(vault, coin, ts, sens_dir, px, sz, sp, tid=0) -> dict:
    signe = +1 if sens_dir in ("Open Long", "Close Short") else -1
    return {"vault": vault, "coin": coin, "ts_ms": int(ts), "dir": sens_dir, "px": float(px),
            "sz": float(sz), "signe": signe, "start_position": float(sp), "tid": tid}


def _signaux(fills, bougies, latence_ms=120_000):
    t = bougies["t_ms"].to_numpy()
    return L1.signaux(pd.DataFrame(fills), bougies, debut=int(t[0]), fin=int(t[-1]) + 1,
                      latence_ms=latence_ms, notionnel_min=1000.0)


def test_les_fills_d_une_meme_milliseconde_suivent_la_chaine_pas_le_tid() -> None:
    """Regression du 22/11 : tries par `tid`, trois fills simultanes faisaient deux faux trous."""
    ts = T0 + H + 60_000
    fills = [_fill("A", "X", ts, "Open Long", 100, 1, 2, tid=1),     # 3e de la chaine, plus petit tid
             _fill("A", "X", ts, "Open Long", 100, 1, 0, tid=3),     # 1er
             _fill("A", "X", ts, "Open Long", 100, 1, 1, tid=2)]     # 2e
    par_tid = sorted(fills, key=lambda f: f["tid"])
    assert [f["start_position"] for f in par_tid] != [0.0, 1.0, 2.0]   # le piege est bien pose
    _, stats = _signaux(fills, _bougies([100] * 40))
    assert stats["trous"] == 0 and stats["fills_prix_connu"] == 3


PRIX = [100] * 6 + [98] * 4 + [99] * 30       # la bougie 5 cloture a 98 : -200 bps pour un long a 100
OUVRE = _fill("A", "X", T0 + H + 60_000, "Open Long", 100, 20, 0)
TEMOIN = _fill("A", "AUTRE", T0 + 30 * H, "Open Long", 5, 1, 0)   # le compte est encore observe


def test_l_evenement_est_causal_et_bien_signe() -> None:
    ev, _ = _signaux([OUVRE, TEMOIN], _bougies(PRIX))
    assert list(ev["seuil"]) == [-100]                       # -200 bps : sous -100, pas sous -300
    e = ev.iloc[0]
    assert e["t_ms"] == T0 + 6 * H and e["sens"] == 1        # entree a l'ouverture qui SUIT la cloture vue
    assert e["latent_bps"] == pytest.approx(-200.0)
    assert e["r_4h"] == pytest.approx(1e4 * (99 / 98 - 1))   # de l'ouverture 6 (98) a l'ouverture 10 (99)


def test_une_cloture_connue_supprime_le_signal_une_cloture_pas_encore_vue_non() -> None:
    connue = _fill("A", "X", T0 + 6 * H - 300_000, "Close Long", 98, 20, 20)
    ev, _ = _signaux([OUVRE, connue, TEMOIN], _bougies(PRIX))
    assert len(ev) == 0                                      # il a coupe 5 min avant : on le sait
    pas_vue = _fill("A", "X", T0 + 6 * H - 30_000, "Close Long", 98, 20, 20)
    ev, _ = _signaux([OUVRE, pas_vue, TEMOIN], _bougies(PRIX))
    assert len(ev) == 1                                      # 30 s avant : pas encore observable


def test_sans_preuve_que_le_compte_est_encore_observe_la_position_n_est_pas_tenue() -> None:
    ev, _ = _signaux([OUVRE], _bougies(PRIX))                # aucun fill ulterieur du compte
    assert len(ev) == 0                                      # absent != tenu : refus


# ---------------------------------------------------------------- jumeaux
def _bougies_a_chutes(n: int) -> pd.DataFrame:
    """Une bougie sur cinq perd 1 % ; les autres sont plates."""
    o = np.empty(n)
    o[0] = 100.0
    for i in range(1, n):
        o[i] = o[i - 1] * (0.99 if (i - 1) % 5 == 0 else 1.0)
    return _bougies(o)


def test_les_jumeaux_excluent_le_voisinage_de_l_evenement() -> None:
    b = _bougies_a_chutes(300)
    t = b["t_ms"].to_numpy()
    k = 151                                                  # la bougie 150 vient de chuter
    ev = pd.DataFrame([{"vault": "A", "coin": "X", "seuil": -100, "t_ms": int(t[k]), "sens": 1}])
    j = P.jumeler(ev, b, debut=int(t[0]), fin=int(t[-1]) + 1, passe_h=1, horizons=(1,)).iloc[0]
    attendus = [i for i in range(1, 300) if (i - 1) % 5 == 0 and abs(i - k) >= 24]
    assert j["jumeaux"] == len(attendus)
    assert j["passe_bps"] == pytest.approx(-100.0)
    assert j["ex_1h"] == pytest.approx(0.0, abs=1e-9)        # meme mecanique, meme suite : exces nul


def test_trop_peu_de_jumeaux_rend_l_evenement_non_mesurable() -> None:
    b = _bougies_a_chutes(60)
    t = b["t_ms"].to_numpy()
    ev = pd.DataFrame([{"vault": "A", "coin": "X", "seuil": -100, "t_ms": int(t[31]), "sens": 1}])
    j = P.jumeler(ev, b, debut=int(t[0]), fin=int(t[-1]) + 1, passe_h=1, horizons=(1,)).iloc[0]
    assert j["jumeaux"] < P.JUMEAUX_MIN and np.isnan(j["ex_1h"])   # jamais une valeur par defaut


# ---------------------------------------------------------------- consensus
def _consensus(fills):
    b = _bougies([100] * 120)
    t = b["t_ms"].to_numpy()
    return C.evenements(pd.DataFrame(fills), b, debut=int(t[0]), fin=int(t[-1]) + 1,
                        latence_ms=120_000, seuil_usd=1000.0, niveaux=(2,)), t


def test_deux_leaders_distincts_font_un_consensus_un_seul_evenement() -> None:
    ev, t = _consensus([_fill("A", "X", T0 + 10 * H + 60_000, "Open Long", 100, 20, 0),
                        _fill("B", "X", T0 + 12 * H + 60_000, "Open Long", 100, 20, 0)])
    assert len(ev) == 1                                      # 24 h de silence apres le premier
    assert ev.iloc[0]["t_ms"] == t[13] and ev.iloc[0]["sens"] == 1   # 1re bougie ou B est connu


def test_le_meme_leader_deux_fois_n_est_pas_un_consensus() -> None:
    ev, _ = _consensus([_fill("A", "X", T0 + 10 * H + 60_000, "Open Long", 100, 20, 0),
                        _fill("A", "X", T0 + 12 * H + 60_000, "Open Long", 100, 20, 20)])
    assert len(ev) == 0


def test_deux_leaders_opposes_s_annulent() -> None:
    ev, _ = _consensus([_fill("A", "X", T0 + 10 * H + 60_000, "Open Long", 100, 20, 0),
                        _fill("B", "X", T0 + 12 * H + 60_000, "Open Short", 100, 20, 0)])
    assert len(ev) == 0


# ---------------------------------------------------------------- moitie de confirmation
def test_les_deux_moities_recouvrent_exactement_le_segment_d_execution() -> None:
    a, b, tout = G.SEGMENTS["execution_a"], G.SEGMENTS["execution_b"], G.SEGMENTS["execution"]
    assert a[0] == tout[0] and a[1] == b[0] and b[1] == tout[1] == G.SEGMENTS["oos_final"][0]


def test_la_moitie_de_confirmation_ne_se_lit_pas_sans_horizon_fige(monkeypatch, capsys) -> None:
    import goal2_etude_cloture_fine as F

    def _interdit(*_a, **_k):
        raise AssertionError("la confirmation a ete LUE alors qu'elle devait etre refusee")

    monkeypatch.setattr(G, "charger", _interdit)
    assert F.main(["--segment", "execution_b"]) == 2
    assert "REFUS" in capsys.readouterr().err
    # et une lecture de la confirmation ne peut pas echapper au registre
    assert F.main(["--segment", "execution_b", "--horizon-fige-min", "15", "--sans-registre"]) == 2


def test_la_resolution_fine_est_causale_et_signee() -> None:
    import goal2_etude_cloture_fine as F

    t = T0 + F.PAS_MS * np.arange(40)
    o = np.array([100.0] * 5 + [101.0] * 35)
    bougies = pd.DataFrame({"coin": "X", "t_ms": t, "o": o})
    # stop d'un LONG a t[1]+10 s : connu a +120 s -> entree a l'ouverture de t[2] (100), sortie t[5] (101)
    ev = pd.DataFrame([{"vault": "A", "coin": "X", "sens_position": 1, "dernier_ms": int(t[1]) + 10_000},
                       {"vault": "A", "coin": "X", "sens_position": -1, "dernier_ms": int(t[1]) + 10_000}])
    r = F.rendements(ev, bougies, latence_ms=120_000)
    assert r["r_15m"].iloc[0] == pytest.approx(100.0)       # +1 % pour la position longue
    assert r["r_15m"].iloc[1] == pytest.approx(-100.0)      # et l'oppose pour la courte
    assert r["r_5m"].iloc[0] == pytest.approx(0.0)          # t[2] -> t[3] : rien n'a bouge
