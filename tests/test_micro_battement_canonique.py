"""LE BATTEMENT CANONIQUE DU COLLECTEUR MICROSTRUCTURE — le faux mort de 31 heures.

CE QUE CES TESTS VERROUILLENT. Le 15/11, `runtime/research_lab/heartbeats/lab-microstructure.json`
avait **31 heures** pendant que les trois rubans `micro_*.jsonl` s'ecrivaient a la seconde : le
collecteur n'appelait `heartbeat_collecteur.battre()` QU'UNE FOIS, avant d'ouvrir le WebSocket, et
`ops/preuve_de_vie` (seuil 60 s) le declarait donc fige. Un collecteur sain juge mort, et aucun
moyen de le distinguer d'un vrai mort.

Les tests ci-dessous echouent sur le code d'avant : ils exigent que le battement canonique soit
repete DANS la boucle, cadence par le temps, avec les champs que la preuve de vie controle
reellement (ecritures qui progressent, horodatage d'exchange, ACK, reconnexions bornees).

Aucun reseau : `hb_mod` est un faux module et l'horloge est pilotee par le compteur.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("mic_hb", _ROOT / "tools" / "collecter_lab_microstructure.py")
MIC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MIC)


class FauxBattement:
    """Enregistre les appels a `battre` sans rien ecrire."""

    def __init__(self, casse: bool = False) -> None:
        self.appels: list[dict] = []
        self.casse = casse

    def battre(self, root, nom, **kw):
        if self.casse:
            raise RuntimeError("verrou heartbeat indisponible")
        self.appels.append({"nom": nom, **kw})
        return {"nom": nom}


def _racine(tmp_path: Path) -> Path:
    (tmp_path / "runtime" / "research_lab").mkdir(parents=True, exist_ok=True)
    return tmp_path


# ─────────────── le compte des reconnexions est une FENETRE, pas un cumul ───────────────
def test_reconnexions_comptees_sur_une_fenetre_glissante():
    # 3 reconnexions dans l'heure, 2 bien plus vieilles : la preuve de vie declare « excessives »
    # au-dela de 20, donc un cumul a vie saturerait l'indicateur en quelques jours de campagne.
    ts = [1000.0, 2000.0, 3_600_000.0, 3_601_000.0, 3_602_000.0]
    assert MIC.reconnexions_recentes(ts, maintenant=3_602_000.0) == 3
    assert MIC.reconnexions_recentes(ts, maintenant=3_602_000.0, fenetre_s=0.0) == 1


def test_reconnexions_recentes_ignore_un_horodatage_illisible():
    ts = [100.0, "bruit", None, 200.0]
    assert MIC.reconnexions_recentes(ts, maintenant=200.0, fenetre_s=1000.0) == 2, (
        "un horodatage illisible est ecarte, il ne compte ni pour ni contre")


def test_reconnexions_recentes_sur_rien():
    assert MIC.reconnexions_recentes(None, maintenant=10.0) == 0
    assert MIC.reconnexions_recentes([], maintenant=10.0) == 0


# ─────────────── ce qui est ECRIT est compte, et l'horodatage exchange retenu ───────────────
def test_noter_ecritures_cumule_et_retient_le_dernier_ts_exchange():
    cpt: dict = {}
    MIC._noter_ecritures(cpt, [{"ts_ex": 10}, {"ts_ex": 20}], 2)
    MIC._noter_ecritures(cpt, [{"ts_ex": 30}], 1)
    assert cpt["ecrites"] == 3
    assert cpt["ts_ex"] == 30, "le DERNIER horodatage d'exchange vu, pas le premier"


def test_noter_ecritures_garde_le_dernier_ts_connu_quand_la_ligne_n_en_a_pas():
    cpt = {"ts_ex": 42}
    MIC._noter_ecritures(cpt, [{"coin": "BTC"}], 1)
    assert cpt["ts_ex"] == 42, (
        "une ligne sans horodatage d'exchange n'EFFACE pas le dernier connu : "
        "l'ecraser par None ferait echouer le controle « horodatages manquants »")
    assert cpt["ecrites"] == 1


# ─────────────── le battement canonique bat DANS la boucle, cadence par le temps ───────────────
def test_premier_passage_bat_le_canonique_et_ecrit_le_local(tmp_path, monkeypatch):
    root = _racine(tmp_path)
    hb = FauxBattement()
    monkeypatch.setattr(MIC.time, "time", lambda: 1_000.0)
    cpt = {"msgs": 400, "ack": 3, "ecrites": 120, "ts_ex": 777, "reco": 1, "reco_ts": [999.0]}
    MIC._heartbeat_micro(root, ["BTC", "ETH"], cpt, {"BTC": 5, "_gaps": 2}, hb)

    local = json.loads((root / "runtime" / "research_lab" / "micro_heartbeat.json").read_text(encoding="utf-8"))
    assert local["coins"] == 2 and local["ecrites"] == 120 and local["reconnexions_1h"] == 1
    assert len(hb.appels) == 1, "le battement canonique part du MEME endroit que le local"
    appel = hb.appels[0]
    assert appel["nom"] == "lab-microstructure"
    assert appel["n_ecrites"] == 120, "delta depuis le dernier battement"
    assert appel["dernier_exchange_ts"] == 777, "sinon : controle « horodatages manquants »"
    assert appel["souscription_ack"] is True, "sinon : controle « souscription non ACK »"
    assert appel["metriques"]["reconnects"] == 1


def test_le_canonique_ne_bat_pas_deux_fois_dans_la_meme_cadence(tmp_path, monkeypatch):
    root = _racine(tmp_path)
    hb = FauxBattement()
    horloge = {"t": 1_000.0}
    monkeypatch.setattr(MIC.time, "time", lambda: horloge["t"])
    cpt: dict = {"msgs": 50, "ack": 1, "ecrites": 10}

    MIC._heartbeat_micro(root, ["BTC"], cpt, {}, hb)
    horloge["t"] += MIC.BATTEMENT_CANONIQUE_S / 2          # trop tot
    cpt["ecrites"] = 30
    MIC._heartbeat_micro(root, ["BTC"], cpt, {}, hb)
    assert len(hb.appels) == 1, "le verrou de cadence tient : un battement par periode"

    horloge["t"] += MIC.BATTEMENT_CANONIQUE_S              # l'heure est venue
    MIC._heartbeat_micro(root, ["BTC"], cpt, {}, hb)
    assert len(hb.appels) == 2
    assert hb.appels[1]["n_ecrites"] == 20, (
        "le delta compte les 20 ecritures depuis le battement precedent, pas les 30 du cumul : "
        "`preuve_de_vie` exige que le cumul PROGRESSE a chaque evaluation")


def test_cadence_bien_sous_le_seuil_de_fige():
    # `preuve_de_vie.SEUIL_HEARTBEAT_MS` vaut 60 000 ms. Battre a 60 s serait battre PILE a la
    # limite : la moindre latence rendrait le collecteur « fige » par intermittence.
    assert MIC.BATTEMENT_CANONIQUE_S <= 20.0
    assert MIC.BATTEMENT_CANONIQUE_S * 1000 * 3 <= 60_000


def test_un_battement_canonique_casse_ne_tue_pas_la_collecte(tmp_path, monkeypatch):
    root = _racine(tmp_path)
    hb = FauxBattement(casse=True)
    monkeypatch.setattr(MIC.time, "time", lambda: 1_000.0)
    cpt: dict = {"msgs": 10, "ecrites": 5}
    MIC._heartbeat_micro(root, ["BTC"], cpt, {}, hb)       # ne doit PAS lever
    assert (root / "runtime" / "research_lab" / "micro_heartbeat.json").exists(), (
        "le heartbeat local est ecrit AVANT le canonique : une panne de l'un ne masque pas l'autre")
    assert "hb_canon_ts" not in cpt, (
        "un battement rate ne marque PAS la periode comme servie, sinon la panne durerait 20 s "
        "de plus a chaque tour")


def test_sans_module_de_battement_le_local_est_quand_meme_ecrit(tmp_path, monkeypatch):
    root = _racine(tmp_path)
    monkeypatch.setattr(MIC.time, "time", lambda: 1_000.0)
    MIC._heartbeat_micro(root, ["BTC"], {"msgs": 1, "ecrites": 1}, {}, None)
    assert (root / "runtime" / "research_lab" / "micro_heartbeat.json").exists()
