"""Le collecteur de LIQUIDATIONS — celui sans qui la mesure #3 reste impossible à jamais.

CONSTAT DU 19/07 (sortie réelle de MESURER-588 / mesure #3) :

    { "snapshots": 0, "coins": 0, "verdict": "AUCUN_HISTORIQUE_LA_MESURE_EST_IMPOSSIBLE" }
    >>> INSUFFISANT : laisse le moteur tourner plus longtemps pour accumuler des liquidations.

Le conseil était FAUX : rien n'écrivait ces données. `enregistrer_grappes` n'était appelé que par
`mainnet_readonly_observer`, hors de la boucle live. Attendre n'aurait jamais rien produit.

Ces tests vérifient que le collecteur écrit VRAIMENT, qu'il n'invente RIEN, et qu'il survit à une
coupure réseau. Aucun appel réseau réel ici : tout est bouchonné.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod():
    chemin = RACINE / "tools" / "collecter_liquidations.py"
    spec = importlib.util.spec_from_file_location("collecter_liquidations", chemin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_wallets_locaux_connus_ELARGIT_depuis_les_traders_actifs(tmp_path):
    """🟢 22/07 — LE goulot mesuré : la base de liquidations ne voyait que 2 coins car la source
    (leaderboard) ne donne que des baleines PEU leveragées. On élargit avec les adresses de traders
    ACTIFS déjà connues localement (leaders copy, fills) — dédupliquées, dans l'ordre."""
    m = _mod()
    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True)
    a1, a2, a3 = "0x" + "1" * 40, "0x" + "2" * 40, "0x" + "3" * 40
    (d / "leader_fills_bruts.jsonl").write_text(
        json.dumps({"user": a1, "coin": "BTC"}) + "\n" + json.dumps({"user": a2}) + "\n", encoding="utf-8")
    (d / "copy_whitelist.json").write_text(json.dumps({"leaders": [a2, a3]}), encoding="utf-8")  # a2 en double
    assert m.wallets_locaux_connus(tmp_path) == [a1, a2, a3]


def test_wallets_locaux_connus_borne_et_survit_a_l_absence(tmp_path):
    m = _mod()
    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True)
    (d / "leader_fills_bruts.jsonl").write_text(
        "\n".join(json.dumps({"user": "0x%040x" % i}) for i in range(50)), encoding="utf-8")
    assert len(m.wallets_locaux_connus(tmp_path, limite=10)) == 10        # borné
    assert m.wallets_locaux_connus(tmp_path / "inexistant") == []          # aucun fichier -> vide, pas d'erreur


def _etat_clearinghouse(coin: str, *, liq_px: float | None, szi: float = 200.0) -> dict:
    """Réponse /info réaliste. `liq_px=None` = position SANS prix de liquidation.

    ⚠️ TAILLE VOLONTAIREMENT RÉALISTE (20 000 $ par wallet). Ma première version utilisait
    1 000 $ et produisait 0 grappe — je croyais à un bug du collecteur, c'était le code qui avait
    RAISON : `construire_carte` exige >= 2 wallets DISTINCTS et >= 10 000 $ pour former une
    grappe (« un seul wallet ne fait pas un flux »). Un test-jouet aurait fait passer un vrai
    garde-fou pour une panne.
    """
    return {"assetPositions": [{"position": {
        "coin": coin, "szi": str(szi), "entryPx": "100.0",
        "positionValue": str(abs(szi) * 100.0),
        "liquidationPx": None if liq_px is None else str(liq_px)}}]}


# ------------------------------------------------------------------ il ÉCRIT vraiment

def test_une_passe_ECRIT_des_snapshots_dans_la_base(tmp_path, monkeypatch):
    """LE TEST QUI COMPTE : après une passe, la base n'est plus vide. C'est exactement ce qui
    manquait pour que la mesure #3 devienne possible."""
    m = _mod()
    monkeypatch.setattr(m, "lire_all_mids", lambda **k: {"BTC": 100.0, "ETH": 50.0})
    monkeypatch.setattr(m, "_post_info", lambda charge, **k: _etat_clearinghouse("BTC", liq_px=99.0))

    n, vues, lus = m.une_passe(tmp_path, ["0x" + "a" * 40, "0x" + "b" * 40], pause_s=0.0)

    assert lus == 2 and vues == 2
    assert n > 0, "aucune ligne ecrite -> la mesure #3 resterait impossible"
    etat = m.resume_historique(root=str(tmp_path))
    assert etat["snapshots"] > 0
    assert etat["verdict"] != "AUCUN_HISTORIQUE_LA_MESURE_EST_IMPOSSIBLE"


def test_une_position_SANS_prix_de_liquidation_est_ECARTEE(tmp_path, monkeypatch):
    """DENY-BY-DEFAULT : pas de `liquidationPx` -> on n'invente pas le prix, on jette la ligne.
    Une carte avec des prix inventés est pire qu'aucune carte."""
    m = _mod()
    monkeypatch.setattr(m, "lire_all_mids", lambda **k: {"BTC": 100.0})
    monkeypatch.setattr(m, "_post_info", lambda charge, **k: _etat_clearinghouse("BTC", liq_px=None))

    n, vues, lus = m.une_passe(tmp_path, ["0x" + "c" * 40], pause_s=0.0)

    assert vues == 0 and n == 0, "une position sans liquidationPx ne doit RIEN produire"
    assert lus == 1, "le wallet a bien ete lu -- c'est la POSITION qui est ecartee"


def test_sans_mids_on_n_ecrit_RIEN(tmp_path, monkeypatch):
    """Sans prix courant, impossible de situer une liquidation. On s'abstient."""
    m = _mod()
    monkeypatch.setattr(m, "lire_all_mids", lambda **k: {})
    monkeypatch.setattr(m, "_post_info", lambda charge, **k: _etat_clearinghouse("BTC", liq_px=99.0))
    assert m.une_passe(tmp_path, ["0x" + "d" * 40], pause_s=0.0) == (0, 0, 0)


# ------------------------------------------------------------------ il SURVIT

def test_une_coupure_reseau_ne_tue_pas_la_passe(tmp_path, monkeypatch):
    m = _mod()

    def boom(**_kw):
        raise OSError("reseau coupe")

    monkeypatch.setattr(m, "lire_all_mids", boom)
    assert m.une_passe(tmp_path, ["0x" + "e" * 40], pause_s=0.0) == (0, 0, 0)


def test_un_wallet_illisible_n_arrete_pas_les_autres(tmp_path, monkeypatch):
    """Un wallet qui répond mal ne doit pas faire perdre la passe entière."""
    m = _mod()
    monkeypatch.setattr(m, "lire_all_mids", lambda **k: {"BTC": 100.0})
    appels = {"n": 0}

    def parfois_casse(charge, **_k):
        appels["n"] += 1
        if appels["n"] == 1:
            raise OSError("timeout")
        return _etat_clearinghouse("BTC", liq_px=99.0)

    monkeypatch.setattr(m, "_post_info", parfois_casse)
    n, vues, lus = m.une_passe(tmp_path, ["0x" + "1" * 40, "0x" + "2" * 40, "0x" + "3" * 40],
                               pause_s=0.0)
    # le 1er wallet casse, les 2 autres passent -> il reste de quoi former une grappe (>= 2 wallets)
    assert lus == 2 and vues == 2 and n > 0


# ------------------------------------------------------------------ la source de wallets

def test_le_leaderboard_est_parse_tolerant_au_schema(monkeypatch):
    """Le format du leaderboard a déjà changé : on cherche des adresses, d'où qu'elles viennent."""
    m = _mod()
    charge = {"leaderboardRows": [
        {"ethAddress": "0x" + "a" * 40}, {"address": "0x" + "b" * 40},
        {"user": "0x" + "c" * 40}, {"rien": "du tout"}, {"ethAddress": "pas-une-adresse"}]}

    class Rep:
        def read(self): return json.dumps(charge).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(m.urllib.request, "urlopen", lambda *a, **k: Rep())
    w = m.wallets_du_leaderboard(limite=10)
    assert w == ["0x" + "a" * 40, "0x" + "b" * 40, "0x" + "c" * 40]


def test_leaderboard_injoignable_rend_une_liste_vide_pas_une_invention(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("dns")))
    assert m.wallets_du_leaderboard() == []


def test_le_repli_lit_les_wallets_deja_vus_par_le_bot(tmp_path):
    """Mieux vaut 3 wallets réels que zéro."""
    m = _mod()
    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True)
    (d / "hypersmart_engine_status.json").write_text(
        json.dumps({"leaders": ["0x" + "f" * 40, "0x" + "e" * 40, "0x" + "f" * 40]}),
        encoding="utf-8")
    assert m.wallets_de_secours(tmp_path) == ["0x" + "f" * 40, "0x" + "e" * 40]


# ---------------------------------------- Levier 4 (22/07) : ciblage FORT LEVIER + watchlist

from types import SimpleNamespace  # noqa: E402


def _pos(wallet: str, coin: str, liq: float, notionnel: float = 30000.0):
    return SimpleNamespace(wallet=wallet, coin=coin, liq_px=liq, notionnel_usd=notionnel)


def test_wallets_a_risque_ne_garde_QUE_le_fort_levier():
    """🟢 LE CIBLAGE QUI MANQUAIT : seul un compte dont la liq est PROCHE du mid (fort levier)
    est retenu. La baleine peu leveragee (liq a 50 % du marche) est ecartee — elle ne se liquide pas."""
    m = _mod()
    positions = [_pos("0xLEVIER", "BTC", 59800.0),    # ~33 bps -> A RISQUE
                 _pos("0xBALEINE", "BTC", 30000.0)]    # 5000 bps -> ecartee
    assert m.wallets_a_risque(positions, {"BTC": 60000.0}, seuil_bps=500.0) == ["0xLEVIER"]


def test_un_mid_absent_n_invente_pas_de_risque():
    m = _mod()
    assert m.wallets_a_risque([_pos("0xX", "PEPE", 1.0)], {}, seuil_bps=500.0) == []


def test_la_watchlist_s_accumule_et_se_dedoublonne(tmp_path):
    m = _mod()
    assert m.sauver_watchlist(tmp_path, ["0xA", "0xB", "0xA"]) == 2
    assert set(m.charger_watchlist(tmp_path)) == {"0xA", "0xB"}
    m.sauver_watchlist(tmp_path, m.charger_watchlist(tmp_path) + ["0xC"])
    assert set(m.charger_watchlist(tmp_path)) == {"0xA", "0xB", "0xC"}


def test_la_watchlist_est_bornee_aux_plus_recents(tmp_path):
    m = _mod()
    assert m.sauver_watchlist(tmp_path, ["0x%03d" % i for i in range(m.MAX_WATCHLIST + 50)]) \
        == m.MAX_WATCHLIST


def test_watchlist_absente_rend_liste_vide():
    m = _mod()
    assert m.charger_watchlist(RACINE / "n_existe_pas_xyz") == []
