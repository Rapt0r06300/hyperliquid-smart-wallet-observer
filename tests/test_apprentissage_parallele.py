"""Apprentissage parallèle : toutes les variantes à la fois, sur données neuves, sans se mentir (22/11/2026)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.experimental import apprentissage_parallele as AP  # noqa: E402
from hl_observer.experimental import auto_amelioration as A  # noqa: E402
from hl_observer.experimental import cohortes as CO  # noqa: E402
from hl_observer.experimental import cycles_fantomes as CF  # noqa: E402

J = AP.JOUR_MS
H = 3_600_000
VAULT = "0x" + "a" * 40


def _tape(jours: int, *, pente_bps_par_h: float = 0.0, coin: str = "BTC") -> dict:
    """Un prix toutes les 60 s ; une pente par heure pour fabriquer un gain connu."""
    pts, p = [], 100.0
    for k in range(int(jours * J / 60_000) + 1):
        pts.append((k * 60_000, p))
        p *= 1 + pente_bps_par_h / 1e4 / 60
    return {coin: pts}


def _ouverture(t_ms: int, *, ident: str, sz: float = 50.0, px: float = 100.0, cote: str = "Long") -> dict:
    return {"cohorte": "RAW_PROBE", "vault": VAULT, "coin": "BTC", "dir": f"Open {cote}", "sz": sz, "px": px,
            "recu_ms": t_ms, "hash": ident, "isSnapshot": False}


def test_la_grille_est_exactement_ce_que_le_moteur_sait_executer() -> None:
    g = AP.grille()
    assert len(g) == 45 and len(set(g)) == 45
    assert {v[0] for v in g} == set(AP.FRACS) and {v[1] for v in g} == set(AP.STOPS)
    assert AP.lire_variante(AP.etiquette(g[7])) == g[7]
    assert A.lire_etiquette(AP.etiquette(g[7])) == (g[7], 0)          # la boucle séquentielle sait la lire


def test_un_fill_n_est_inscrit_que_resolu_pour_toutes_les_variantes() -> None:
    tape = _tape(2)
    lignes = [_ouverture(10 * H, ident="a"), _ouverture(30 * H, ident="b")]
    neufs, comptes = AP.simuler_les_fills(lignes, tape, {VAULT: 1_000_000.0}, debut_ms=0, now_ms=32 * H)
    # « b » (30 h) n'est pas encore résolu pour l'horizon de 4 h : il attend, pour TOUTES les variantes
    assert [r["identite"] for r in neufs] == ["a"] and comptes["trop_recents"] > 0
    res = neufs[0]["res"]
    assert len(res) == 45
    # 5 000 USD de notionnel : seuil 0,05 % et 0,1 % (500 et 1 000 USD) atteints, 0,8 % (plafonné à 2 000) aussi
    assert all(res[AP.etiquette(v)] is not None for v in AP.grille() if v[0] in (0.0005, 0.001, 0.002))
    petit = AP.simuler_les_fills([_ouverture(10 * H, ident="c", sz=3.0)], tape, {VAULT: 200_000.0},
                                 debut_ms=0, now_ms=32 * H)[0][0]["res"]           # 300 USD, TVL 200 k
    assert petit[AP.etiquette((0.0005, 40.0, 3_600_000.0))] is not None              # 100 -> plancher 150 : atteint
    assert petit[AP.etiquette((0.004, 40.0, 3_600_000.0))] is None                   # 800 : absence, pas zéro


def _registre_synthetique(jours: int, par_jour: int, gain_usd: float, bruit: float, *, lab_gagnant: str) -> list[dict]:
    out = []
    for j in range(jours):
        for i in range(par_jour):
            res = {AP.etiquette(v): (-0.01 + (bruit if i % 2 else -bruit)) for v in AP.grille()}
            res[lab_gagnant] = gain_usd + (bruit if i % 2 else -bruit) * 0.1
            out.append({"identite": f"{j}-{i}", "jour": j, "res": res})
    return out


def test_une_championne_exige_borne_basse_positive_cinq_jours_et_cinquante_cycles() -> None:
    lab = AP.etiquette((0.002, 40.0, 3_600_000.0))
    fort = AP.juger(_registre_synthetique(6, 12, 0.05, 0.01, lab_gagnant=lab), eliminees=set())
    assert fort["championne"] == lab and fort["bornes"][lab]["bas"] > 0
    assert lab not in fort["a_eliminer"] and len(fort["a_eliminer"]) > 0            # les perdantes sont écartées
    court = AP.juger(_registre_synthetique(4, 20, 0.05, 0.01, lab_gagnant=lab), eliminees=set())
    assert court["championne"] is None                                               # 4 jours : pas assez
    rare = AP.juger(_registre_synthetique(6, 5, 0.05, 0.01, lab_gagnant=lab), eliminees=set())
    assert rare["championne"] is None                                                # 30 cycles : pas assez


def test_la_correction_se_resserre_avec_les_variantes_et_les_jours_regardes() -> None:
    lab = AP.etiquette((0.002, 40.0, 3_600_000.0))
    a = AP.juger(_registre_synthetique(6, 12, 0.05, 0.01, lab_gagnant=lab), eliminees=set())["alpha"]
    b = AP.juger(_registre_synthetique(12, 12, 0.05, 0.01, lab_gagnant=lab), eliminees=set())["alpha"]
    assert abs(a - 0.05 / (45 * 6)) < 1e-12 and b < a


def test_donnees_neuves_seulement_et_aucun_fill_compte_deux_fois(tmp_path) -> None:
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vaults_scores.json").write_text(
        json.dumps({"classement": [{"vault": VAULT, "facteurs": {"tvl_usd": 1_000_000.0}}]}), encoding="utf-8")
    journal = tmp_path / CF.JOURNAL
    journal.write_text(json.dumps(_ouverture(1 * H, ident="avant")) + "\n", encoding="utf-8")
    tape = _tape(3)
    e1 = AP.une_passe(tmp_path, ecrire=True, now_ms=2 * H, tape=tape)                # 1er passage : fixe le début
    assert e1["debut_ms"] == 2 * H and e1["fills_inscrits"] == 0                     # le fill d'AVANT ne compte pas
    with journal.open("a", encoding="utf-8") as f:
        f.write(json.dumps(_ouverture(3 * H, ident="apres")) + "\n")
    e2 = AP.une_passe(tmp_path, ecrire=True, now_ms=20 * H, tape=tape)
    assert e2["fills_inscrits"] == 1 and e2["fills_ce_passage"] == 1
    e3 = AP.une_passe(tmp_path, ecrire=True, now_ms=21 * H, tape=tape)
    assert e3["fills_inscrits"] == 1 and e3["fills_ce_passage"] == 0                 # pas de double compte


def test_seule_une_avance_mesuree_en_fantome_arme_le_bac_a_sable(tmp_path) -> None:
    chemin = CO._p(CO.RAW_PROBE, tmp_path, "auto.json")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    assert CO._cfg_defaut(CO.RAW_PROBE, tmp_path)["edge_brut_bps"] is None          # sans réglage : aucune avance
    chemin.write_text(json.dumps({"edge_brut_bps": 30.0, "edge_source": "SUPPOSE"}), encoding="utf-8")
    assert CO._cfg_defaut(CO.RAW_PROBE, tmp_path)["edge_brut_bps"] is None          # source non mesurée : ignorée
    chemin.write_text(json.dumps({"edge_brut_bps": 30.0, "edge_source": "FANTOME_LCB"}), encoding="utf-8")
    assert CO._cfg_defaut(CO.RAW_PROBE, tmp_path)["edge_brut_bps"] == 30.0
    assert CO._cfg_defaut(CO.ALPHA, tmp_path)["edge_brut_bps"] is None              # ALPHA garde ses tables


def test_sans_championne_rien_n_est_arme(tmp_path) -> None:
    etat = A.une_passe(tmp_path, appliquer=True, tape={})
    assert etat["parallele"]["decision"]["action"] == "OBSERVER"
    assert not CO._p(CO.RAW_PROBE, tmp_path, "auto.json").is_file()


def test_un_ordre_execute_en_plusieurs_fills_ne_fait_qu_un_cycle() -> None:
    """Défaut réel du 22/11 : un ordre HYPE en 4 fills faisait 4 trades fantômes identiques."""
    tape = _tape(2)
    lignes = [{**_ouverture(10 * H, ident=f"h{i}"), "oid": 777} for i in range(4)]
    sim = CF.simuler(lignes, tape, {VAULT: 1_000_000.0}, frac_tvl=0.0005, stop_bps=40.0, horizon_ms=H,
                     depuis_ms=0, now_ms=20 * H, etiquette="t")
    assert len(sim["cycles"]) == 1 and sim["compte"]["doublons"] == 3


def test_un_fill_inscrit_deux_fois_ne_compte_qu_une_fois(tmp_path) -> None:
    chemin = tmp_path / AP.REGISTRE
    chemin.parent.mkdir(parents=True)
    rec = {"identite": "x", "jour": 1, "res": {AP.etiquette(AP.grille()[0]): 0.1}}
    chemin.write_text((json.dumps(rec) + "\n") * 2, encoding="utf-8")
    assert len(AP.lire_registre(tmp_path)) == 1


def test_la_bande_de_prix_ne_lit_que_la_fenetre_et_rend_les_memes_prix(tmp_path, monkeypatch) -> None:
    """Le fichier grossit d'environ 500 Mo par jour : on ne relit que la fenêtre utile, depuis la fin."""
    chemin = tmp_path / CF.BANDE_DE_PRIX
    chemin.parent.mkdir(parents=True)
    lignes = [json.dumps({"ts_ms": 1_000 * k, "mids": {"BTC": str(100 + k), "kPEPE": "0.01"}}) for k in range(500)]
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    monkeypatch.setattr(CF, "BLOC_OCTETS", 97)                   # blocs minuscules : coupures de lignes partout
    b = CF.bande_de_prix(tmp_path, depuis_ms=400_000)
    assert [t for t, _ in b["BTC"]] == [1_000 * k for k in range(400, 500)]      # exactement la fenêtre
    assert b["BTC"][0][1] == 500.0 and set(b) == {"BTC", "KPEPE"}               # mêmes clés que le chargeur complet
    assert CF.bande_de_prix(tmp_path, depuis_ms=0)["BTC"][0] == (0, 100.0)      # tout le fichier si on le demande
    assert CF.bande_de_prix(tmp_path / "absent", depuis_ms=0) == {}


def test_l_etat_publie_est_du_json_valide_meme_sans_aucune_donnee(tmp_path) -> None:
    """Défaut réel du 22/11 : des bornes NaN rendaient l'état illisible et la page /direct en erreur."""
    e = AP.une_passe(tmp_path, ecrire=True, now_ms=10 * H, tape={})
    texte = (tmp_path / AP.ETAT).read_text(encoding="utf-8")
    json.loads(texte, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))   # NaN refusé
    json.dumps(e, allow_nan=False)
    assert AP.sans_nan({"a": [float("nan"), 1.0, float("inf")]}) == {"a": [None, 1.0, None]}


def test_le_contexte_d_entree_est_enregistre_sans_changer_le_gain() -> None:
    """Pour juger plus tard des règles de refus (signal absorbé, latence) sur données neuves."""
    tape = _tape(2, pente_bps_par_h=10.0)
    ligne = {**_ouverture(10 * H, ident="z", px=99.0), "fill_ts_ms": 10 * H - 5_000}
    c = CF.simuler([ligne], tape, {VAULT: 1_000_000.0}, frac_tvl=0.0005, stop_bps=400.0, horizon_ms=H,
                   depuis_ms=0, now_ms=20 * H, etiquette="t")["cycles"][0]
    p0 = next(p for t, p in tape["BTC"] if t >= 10 * H)
    assert abs(c["contexte"]["absorption_bps"] - 1e4 * (p0 / 99.0 - 1)) < 1e-2    # le prix a déjà bougé depuis le fill
    assert c["contexte"]["latence_ms"] == 5_000 and c["contexte"]["notionnel_leader_usd"] == 4950.0
    sans = CF.simuler([{**ligne, "px": 100.0}], tape, {VAULT: 1_000_000.0}, frac_tvl=0.0005, stop_bps=400.0,
                      horizon_ms=H, depuis_ms=0, now_ms=20 * H, etiquette="t")["cycles"][0]
    assert sans["realized_usd"] == c["realized_usd"]                                 # le contexte ne change pas le gain
