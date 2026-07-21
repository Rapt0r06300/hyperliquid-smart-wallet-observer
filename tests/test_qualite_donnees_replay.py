"""QUALITÉ DES DONNÉES DE REPLAY (21/07) — chaque défaut a déjà tué une mesure ici.

L'audit du 21/07 sur les vraies données a trouvé : étiquetage 0,7 % (99,3 % des candidats
sans `strategie` -> tous rangés en « copy », arbitrage affamé) et 52 sauts de prix > 50 %.
Ces tests verrouillent la détection ET la réparation à la source.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "qualite", RACINE / "tools" / "qualite_donnees_replay.py")
Q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(Q)


def _ecrire(root: Path, cands, marks):
    d = root / "runtime" / "replay" / "_merged"
    d.mkdir(parents=True, exist_ok=True)
    (d / "candidates.jsonl").write_text(
        "\n".join(json.dumps(c) for c in cands) + "\n", encoding="utf-8")
    (d / "marks.jsonl").write_text(
        "\n".join(json.dumps(m) for m in marks) + "\n", encoding="utf-8")


def test_donnees_saines_aucun_defaut(tmp_path):
    cands = [{"recorded_at": 1000 + i, "coin": "BTC", "strategie": "carry"} for i in range(20)]
    marks = [{"ts": 1000 + i * 30, "coin": "BTC", "mid": 64000 + i} for i in range(200)]
    r = Q.auditer(tmp_path)
    _ecrire(tmp_path, cands, marks)
    r = Q.auditer(tmp_path)
    assert r["verdict"] == "PRÊT POUR LE REPLAY", r["defauts"]
    assert r["couverture_pct"] == 100.0 and r["etiquetage_pct"] == 100.0


def test_l_etiquetage_manquant_est_DETECTE(tmp_path):
    """LE défaut du 21/07 : sans `strategie`, tout part dans le seau copy."""
    cands = [{"recorded_at": 1000 + i, "coin": "BTC"} for i in range(20)]
    _ecrire(tmp_path, cands, [{"ts": 9999, "coin": "BTC", "mid": 64000}])
    r = Q.auditer(tmp_path)
    assert r["etiquetage_pct"] == 0.0
    assert any("ÉTIQUETAGE" in d for d in r["defauts"])


def test_la_couverture_manquante_est_DETECTEE_cause_n1_des_zero_trade(tmp_path):
    """Un candidat sans mark APRÈS lui est INMESURABLE — le replay le jette en silence."""
    cands = [{"recorded_at": 5000 + i, "coin": "BTC", "strategie": "carry"} for i in range(20)]
    _ecrire(tmp_path, cands, [{"ts": 1000, "coin": "BTC", "mid": 64000}])   # marks AVANT
    r = Q.auditer(tmp_path)
    assert r["couverture_pct"] == 0.0
    assert any("COUVERTURE" in d for d in r["defauts"])


def test_les_sauts_de_prix_absurdes_sont_DETECTES(tmp_path):
    cands = [{"recorded_at": 1000, "coin": "BTC", "strategie": "carry"}]
    marks = [{"ts": 1000, "coin": "BTC", "mid": 64000.0},
             {"ts": 1060, "coin": "BTC", "mid": 6400.0}]        # -90 %
    _ecrire(tmp_path, cands, marks)
    r = Q.auditer(tmp_path)
    assert r["sauts_prix_absurdes"] >= 1
    assert any("PRIX" in d for d in r["defauts"])


def test_les_doublons_sont_DETECTES(tmp_path):
    c = {"recorded_at": 1000, "coin": "BTC", "strategie": "carry", "direction": "LONG"}
    _ecrire(tmp_path, [c] * 10, [{"ts": 2000, "coin": "BTC", "mid": 64000}])
    r = Q.auditer(tmp_path)
    assert r["doublons_pct"] == 90.0 and any("DOUBLONS" in d for d in r["defauts"])


def test_le_rapport_markdown_est_ecrit_atomiquement(tmp_path):
    _ecrire(tmp_path, [{"recorded_at": 1, "coin": "BTC", "strategie": "carry"}],
            [{"ts": 2, "coin": "BTC", "mid": 1.0}])
    p = Q.ecrire_rapport(tmp_path)
    t = p.read_text(encoding="utf-8")
    assert "QUALITÉ DES DONNÉES" in t and "VERDICT" in t
    assert not list(p.parent.glob("*.tmp"))


def test_la_source_etiquette_desormais_les_candidats_copy():
    """Réparation À LA SOURCE : l'enregistreur des vetos d'entrée copy écrit `strategie`."""
    src = open(RACINE / "src/hl_observer/signals/v26_entry_vetos.py", encoding="utf-8").read()
    assert '"recorded_at": time.time(), "strategie": "copy", **snapshot' in src, \
        "un snapshot portant deja `strategie` la garde (jamais d'ecrasement)"


def test_les_tickers_TECHNIQUES_et_les_sauts_LENTS_ne_sont_plus_des_faux_positifs(tmp_path):
    """Enquête du 21/07 : les 52 « sauts » etaient des tickers @128/#5101 (paires spot et
    indices internes HL) ou des ecarts de 7 JOURS. Un prix a le droit de doubler en une
    semaine. Un saut n'est suspect que RAPIDE (<10 min) et sur un VRAI coin."""
    cands = [{"recorded_at": 1000, "coin": "BTC", "strategie": "carry"}]
    marks = [
        {"ts": 1000, "coin": "@128", "mid": 1.0}, {"ts": 1060, "coin": "@128", "mid": 5.0},
        {"ts": 1000, "coin": "ETH", "mid": 3000.0},
        {"ts": 1000 + 7 * 86400, "coin": "ETH", "mid": 9000.0},          # 7 jours : legitime
        {"ts": 2000, "coin": "BTC", "mid": 64000.0},
    ]
    _ecrire(tmp_path, cands, marks)
    r = Q.auditer(tmp_path)
    assert r["sauts_prix_absurdes"] == 0, r.get("sauts_exemples")
    # mais un VRAI saut rapide sur un VRAI coin reste detecte
    marks.append({"ts": 2300, "coin": "BTC", "mid": 6400.0})             # -90 % en 5 min
    _ecrire(tmp_path, cands, marks)
    assert Q.auditer(tmp_path)["sauts_prix_absurdes"] == 1
