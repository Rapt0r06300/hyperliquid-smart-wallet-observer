"""DISPERSION CROSS-VENUE — le collecteur et le juge. Dernière piste ouverte du projet.

Protocole (barres fixées AVANT la donnée) : `docs/audit/PROTOCOLE_CROSS_VENUE.md`.

DEUX RISQUES À VERROUILLER ICI, et ils ont chacun déjà coûté cher à ce projet :

1. **L'UNITÉ.** Hyperliquid paie le funding par HEURE, Binance par 8 HEURES. Le 13/07, une
   confusion d'unité de ce type avait produit un « 38 % APR » qui n'était que l'intervalle de
   funding. Un facteur 8 sur un funding transforme une piste morte en pépite imaginaire.

2. **LA DONNÉE INVENTÉE.** Si une venue est muette et qu'on écrit 0 à la place, la dispersion
   calculée devient énorme et fausse — et elle passerait toutes les barres. Un trou honnête
   vaut mieux qu'un chiffre fabriqué.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod(nom: str):
    chemin = RACINE / "tools" / ("%s.py" % nom)
    spec = importlib.util.spec_from_file_location(nom, chemin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


COLL = _mod("collecter_dispersion_venues")
JUGE = _mod("mesurer_dispersion_venues")


# ------------------------------------------------------------------ 1. l'unité

def test_le_funding_BINANCE_est_divise_par_8(monkeypatch):
    """LE PIÈGE Nº1. Binance publie un taux PAR 8 H. Sans la division, tout est faux d'un
    facteur 8 — et 8× sur un funding, ça fabrique une pépite qui n'existe pas."""
    charge = [{"symbol": "BTCUSDT", "lastFundingRate": "0.0008"}]     # 8 bps / 8 h

    class Rep:
        def read(self): return json.dumps(charge).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(COLL.urllib.request, "urlopen", lambda *a, **k: Rep())
    f = COLL.funding_binance()
    assert round(f["BTC"], 6) == 1.0, "8 bps par 8 h = 1 bps/h, pas 8"


def test_le_funding_HL_reste_horaire(monkeypatch):
    """HL publie deja un taux HORAIRE : surtout ne pas le diviser."""
    charge = [{"universe": [{"name": "BTC"}]}, [{"funding": "0.0000125"}]]
    monkeypatch.setattr(COLL, "_post", lambda *a, **k: charge)
    assert round(COLL.funding_hyperliquid()["BTC"], 6) == 0.125


# ------------------------------------------------------------------ 2. rien d'inventé

def test_une_venue_MUETTE_n_ecrit_RIEN(tmp_path, monkeypatch):
    """Si Binance ne répond pas, on n'écrit pas une dispersion contre un zéro imaginaire."""
    monkeypatch.setattr(COLL, "funding_hyperliquid", lambda: {"BTC": 0.125})
    monkeypatch.setattr(COLL, "funding_binance", lambda: {})
    assert COLL.une_passe(tmp_path, ["BTC"]) == (0, 0)
    assert not (tmp_path / COLL.SORTIE).exists()


def test_un_coin_absent_d_une_venue_est_ECARTE(tmp_path, monkeypatch):
    monkeypatch.setattr(COLL, "donnees_hyperliquid", lambda: {"BTC": {"f": 0.125, "px": None}, "HYPE": {"f": 0.125, "px": None}})
    monkeypatch.setattr(COLL, "donnees_binance", lambda: {"BTC": {"f": 0.4, "px": None}})   # pas de HYPE
    n, _ = COLL.une_passe(tmp_path, ["BTC", "HYPE"])
    assert n == 1
    lignes = (tmp_path / COLL.SORTIE).read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lignes[0])["coin"] == "BTC"


def test_la_dispersion_ecrite_est_juste(tmp_path, monkeypatch):
    monkeypatch.setattr(COLL, "donnees_hyperliquid", lambda: {"BTC": {"f": 0.125, "px": None}})
    monkeypatch.setattr(COLL, "donnees_binance", lambda: {"BTC": {"f": 0.425, "px": None}})
    COLL.une_passe(tmp_path, ["BTC"])
    r = json.loads((tmp_path / COLL.SORTIE).read_text(encoding="utf-8").strip())
    assert round(r["dispersion_bps_h"], 6) == 0.3
    assert r["venue_haute"] == "BINANCE"
    assert r["real_execution"] is False


# ------------------------------------------------------------------ 3. le juge

def _ecrire(tmp_path, *, disp: float, heures: float, coins: int, n_par_coin: int = 60):
    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True, exist_ok=True)
    pas = heures * 3600.0 / max(1, n_par_coin - 1)
    with (d / "dispersion_venues.jsonl").open("w", encoding="utf-8") as fh:
        for c in range(coins):
            for i in range(n_par_coin):
                fh.write(json.dumps({"ts": 1_000_000.0 + i * pas, "coin": "C%d" % c,
                                     "dispersion_bps_h": disp}) + "\n")


def test_sans_donnees_le_verdict_est_INSUFFISANT(tmp_path):
    assert JUGE.juger(JUGE.charger(tmp_path))["verdict"] == "INSUFFISANT"


def test_trop_peu_d_heures_ou_de_coins_reste_INSUFFISANT(tmp_path):
    """« Pas assez de donnees » n'est NI un succes NI un echec. Confondre les deux est
    exactement ce qui avait produit le faux « 1 sur 1M »."""
    _ecrire(tmp_path, disp=5.0, heures=10.0, coins=9)          # 10 h < 72 h
    assert JUGE.juger(JUGE.charger(tmp_path))["verdict"] == "INSUFFISANT"
    _ecrire(tmp_path, disp=5.0, heures=100.0, coins=2)         # 2 coins < 5
    assert JUGE.juger(JUGE.charger(tmp_path))["verdict"] == "INSUFFISANT"


def test_une_dispersion_MINUSCULE_est_REJETEE(tmp_path):
    """Le cas le plus probable, et celui qu'on refuse de maquiller."""
    _ecrire(tmp_path, disp=0.001, heures=100.0, coins=8)
    r = JUGE.juger(JUGE.charger(tmp_path))
    assert r["verdict"] == "REJETE"
    assert len(r["barres_ratees"]) >= 2


def test_une_dispersion_FRANCHE_est_EXPLOITABLE(tmp_path):
    """Le cas favorable doit passer — sinon la mesure serait un refus deguise."""
    _ecrire(tmp_path, disp=1.0, heures=100.0, coins=8)
    r = JUGE.juger(JUGE.charger(tmp_path))
    assert r["verdict"] == "EXPLOITABLE", r
    assert all(b["passee"] for b in r["barres"])


def test_le_cout_ALLER_RETOUR_est_bien_soustrait(tmp_path):
    """Un rendement brut n'est pas un rendement. Les 4 jambes doivent etre payees."""
    _ecrire(tmp_path, disp=1.0, heures=100.0, coins=8)
    r = JUGE.juger(JUGE.charger(tmp_path))
    brut = 1.0 * 24 * 365 / 100.0
    assert r["rendement_net_annuel_pct"] < brut
    assert abs(r["rendement_net_annuel_pct"] - (brut - JUGE.COUT_ALLER_RETOUR_BPS / 100.0)) < 1e-6


def test_les_BARRES_correspondent_au_protocole_ecrit():
    """CLIQUET ANTI-DEPLACEMENT. Si quelqu'un adoucit un seuil pour faire passer la piste,
    ce test rougit. Les barres ont ete fixees AVANT la donnee : c'est tout leur interet."""
    assert JUGE.MAX_HEURES_AMORTISSEMENT == 168.0
    assert JUGE.MIN_RENDEMENT_ANNUEL_PCT == 2.0
    assert JUGE.MIN_PERSISTANCE == 0.60
    assert JUGE.MIN_HEURES_OBSERVEES == 72.0
    assert JUGE.MIN_COINS == 5
    assert JUGE.COUT_ALLER_RETOUR_BPS == 22.0
    texte = (RACINE / "docs" / "audit" / "PROTOCOLE_CROSS_VENUE.md").read_text(encoding="utf-8")
    for attendu in ("168 h", "2 %/an", "60 %", "72 h", "5 coins", "22 bps"):
        assert attendu in texte, "le protocole ecrit ne mentionne plus %r" % attendu


# ---------------- 21/07 : MECANISME ARBITRAGE — dislocation de prix HL<->Binance ----------------
# Litterature (recherche X/GitHub) : le spread du MEME perp entre 2 venues revient a sa
# moyenne. MESURE d'abord : ecart >= 20 bps (seuil PRE-declare) -> candidat 'arbitrage' au
# replay, jamais un trade. Le laboratoire jugera aux memes portes.

def test_l_ecart_de_prix_est_mesure_et_le_candidat_emis_au_dela_du_seuil(tmp_path, monkeypatch):
    import json as _j
    m = COLL
    monkeypatch.setattr(m, "donnees_hyperliquid", lambda: {
        "BTC": {"f": 0.125, "px": 64000.0},          # HL riche de ~31 bps
        "ETH": {"f": 0.125, "px": 3200.0}})          # ecart nul
    monkeypatch.setattr(m, "donnees_binance", lambda: {
        "BTC": {"f": 0.100, "px": 63800.0},
        "ETH": {"f": 0.100, "px": 3200.0}})
    n, _ = m.une_passe(tmp_path, ["BTC", "ETH"])
    assert n == 2
    lignes = [_j.loads(l) for l in
              (tmp_path / "runtime" / "data" / "dispersion_venues.jsonl")
              .read_text(encoding="utf-8").splitlines()]
    btc = next(l for l in lignes if l["coin"] == "BTC")
    assert abs(btc["ecart_prix_bps"] - 31.3480) < 0.01
    # le candidat arbitrage est emis dans le shard replay du process
    import glob
    shards = glob.glob(str(tmp_path / "runtime" / "replay" / "candidates.*.jsonl"))
    assert shards, "l'ecart 31 bps >= seuil 20 -> candidat emis"
    cands = [_j.loads(l) for l in open(shards[0], encoding="utf-8")]
    assert len(cands) == 1 and cands[0]["strategie"] == "arbitrage"
    assert cands[0]["direction"] == "SHORT" and cands[0]["venue_riche"] == "HL"
    assert cands[0]["real_execution"] is False


def test_sous_le_seuil_AUCUN_candidat_la_mesure_funding_continue(tmp_path, monkeypatch):
    m = COLL
    monkeypatch.setattr(m, "donnees_hyperliquid", lambda: {"ETH": {"f": 0.2, "px": 3201.0}})
    monkeypatch.setattr(m, "donnees_binance", lambda: {"ETH": {"f": 0.1, "px": 3200.0}})
    n, _ = m.une_passe(tmp_path, ["ETH"])           # ecart ~3 bps < 20
    assert n == 1
    import glob
    assert not glob.glob(str(tmp_path / "runtime" / "replay" / "candidates.*.jsonl"))
