"""LE LABO LISAIT LE DÉBUT DU COFFRE, PAS SA PARTIE UTILE (17/11/2026).

Rejeu réel du labo ce jour-là : le pont LOCAL s'est arrêté à 60 shards sur 6 409 à la première
alerte mémoire, et de toute façon il ne dépassait jamais le 10/11 (ordre de scellement, plafond de
8 M lignes) alors que la chaîne causale complète n'existe qu'à partir du 13/11. Verdict :
« trop peu de jours » — une description de sa lecture, pas du coffre.

Voir `hl_observer.backtesting.copy_vault_fenetre_locale`.
"""
from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime

import pytest

from hl_observer.backtesting import copy_vault_fenetre_locale as F
from hl_observer.backtesting import copy_vault_local_lab as LAB
from hl_observer.backtesting import copy_vault_tier_local as TL
from hl_observer.ops import budget_ram as BR
from tests.test_lab_coffre_injection import _ecrire_shard, _fill, _index, _sha

JOUR = 86_400_000


def _ms(jour: str) -> int:
    return int(datetime.strptime(jour, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000)


def _carnet(ts: int, *, liable: bool) -> dict:
    ligne = {"coin": "ETH", "received_at_ms": ts, "exchange_ts_ms": ts - 400, "bid": 1999.0,
             "ask": 2001.0, "bids5": [[1999.0, 1.0]], "asks5": [[2001.0, 1.0]]}
    if liable:
        ligne.update({"connection_id": "l2-lane-x", "l2_gap_epoch": 0})
    return ligne


def _coffre(root, jours: dict[str, bool]) -> list[dict]:
    """Un shard de carnets et un shard de fills par jour ; ``True`` = carnets liables ce jour-là."""
    entrees = []
    for jour, liable in jours.items():
        debut = _ms(jour) + 3_600_000
        rel = _ecrire_shard(root, "book_l2", [_carnet(debut + i * 1000, liable=liable) for i in range(6)],
                            nom=f"l2_{jour}")
        entrees.append({"famille": "book_l2", "shard": rel, "sha256": _sha(root, rel), "deposes": 6,
                        "ts_min_ms": debut, "ts_max_ms": debut + 5000})
        rel = _ecrire_shard(root, "fills_forward", [_fill(debut, i) for i in range(4)], nom=f"f_{jour}")
        entrees.append({"famille": "fills_forward", "shard": rel, "sha256": _sha(root, rel), "deposes": 4,
                        "ts_min_ms": debut, "ts_max_ms": debut + 3})
    _index(root, entrees)
    return entrees


# ───────────────────────── la fenêtre ─────────────────────────

def test_la_fenetre_commence_au_premier_jour_LIABLE(tmp_path):
    _coffre(tmp_path, {"2026-11-10": False, "2026-11-11": False, "2026-11-13": True, "2026-11-14": True})
    fenetre = F.choisir_la_fenetre(tmp_path)
    assert fenetre["premier_jour_liable"] == "2026-11-13"
    assert fenetre["depuis_ms"] == _ms("2026-11-13") and fenetre["motif"] == F.MOTIF_PREMIER_JOUR_LIABLE
    assert fenetre["jours_sondes"] == 4


def test_sans_jour_liable_le_labo_lit_comme_avant_et_le_dit(tmp_path):
    _coffre(tmp_path, {"2026-11-10": False, "2026-11-11": False})
    fenetre = F.choisir_la_fenetre(tmp_path)
    assert fenetre["depuis_ms"] is None and fenetre["motif"] == F.MOTIF_AUCUN_JOUR_LIABLE


def test_index_absent_ou_illisible_ne_leve_pas(tmp_path):
    assert F.choisir_la_fenetre(tmp_path) == {"depuis_ms": None, "motif": F.MOTIF_INDEX_ILLISIBLE,
                                              "premier_jour_liable": None, "jours_sondes": 0}
    (tmp_path / F.INDEX_LOCAL).parent.mkdir(parents=True)
    (tmp_path / F.INDEX_LOCAL).write_text("{pas du json", encoding="utf-8")
    assert F.choisir_la_fenetre(tmp_path)["motif"] == F.MOTIF_INDEX_ILLISIBLE
    (tmp_path / F.INDEX_LOCAL).write_text(json.dumps({"shards": "pas une liste"}), encoding="utf-8")
    assert F.choisir_la_fenetre(tmp_path)["motif"] == F.MOTIF_INDEX_ILLISIBLE


def test_un_jour_a_MINORITE_de_carnets_liables_n_est_pas_liable(tmp_path):
    debut = _ms("2026-11-12") + 3_600_000
    lignes = [_carnet(debut + i, liable=i < 2) for i in range(6)]            # 2 liables sur 6
    rel = _ecrire_shard(tmp_path, "book_l2", lignes, nom="mixte")
    _index(tmp_path, [{"famille": "book_l2", "shard": rel, "sha256": _sha(tmp_path, rel),
                       "ts_min_ms": debut, "ts_max_ms": debut + 5}])
    assert F.choisir_la_fenetre(tmp_path)["depuis_ms"] is None


def test_le_pont_ne_lit_PLUS_les_jours_d_avant_la_fenetre(tmp_path):
    """Le cas réel : sans fenêtre, les vieux jours remplissaient le plafond avant les jours utiles."""
    _coffre(tmp_path, {"2026-11-09": False, "2026-11-10": False, "2026-11-13": True, "2026-11-14": True})
    sans = TL._charger_tier_local(tmp_path, max_lignes=12)
    assert sans["chargement_arrete"] == "PLAFOND_LIGNES"
    assert max(r["ts_ms"] for r in sans["_fills"]) < _ms("2026-11-13"), \
        "sans fenêtre, le plafond est atteint AVANT le premier jour liable"
    fenetre = F.choisir_la_fenetre(tmp_path)
    avec = TL._charger_tier_local(tmp_path, max_lignes=40, depuis_ms=fenetre["depuis_ms"])
    assert avec["chargement_arrete"] is None and avec["shards_hors_fenetre"] == 4
    assert min(r["ts_ms"] for r in avec["_fills"]) >= _ms("2026-11-13")
    assert {datetime.fromtimestamp(r["ts_ms"] / 1000, UTC).strftime("%m-%d") for r in avec["_fills"]} == {"11-13", "11-14"}


# ───────────────────────── la patience mémoire ─────────────────────────

class _FauxGouverneur:
    PAUSER = "PAUSER"

    def __init__(self, decisions, *, coupable="EXTERIEUR", attente_s=7.0, sans_etat=False):
        self._decisions = list(decisions)
        self._coupable = coupable
        self._attente_s = attente_s
        self._sans_etat = sans_etat
        self.attentes: list[float] = []
        self.photos = 0

    def decision(self):
        action = self._decisions.pop(0) if self._decisions else "CONTINUER"
        base = {"action": action, "raison": "test"}
        if not self._sans_etat:
            base["etat"] = {"dispo_octets": 2 * 2**30, "total_octets": 32 * 2**30}
        return base

    def etat_memoire(self):
        self.photos += 1
        return {"dispo_octets": 2 * 2**30, "total_octets": 32 * 2**30}

    def memoire_de_l_arbre_octets(self):
        return 2**30

    def coupable_de_la_pression(self, **_k):
        return {"coupable": self._coupable}

    def attendre_que_ca_respire(self, *, limite_s):
        self.attentes.append(limite_s)
        return {"attendu_s": self._attente_s, "a_respire": True}


def test_memoire_saine_on_continue_sans_incident():
    verdict = F.patienter_sous_pression(br=_FauxGouverneur(["CONTINUER"]))
    assert verdict == {"continuer": True, "attendu_s": 0.0, "incident": False, "coupable": None, "detail": None}


def test_pression_EXTERNE_qui_retombe_on_ATTEND_puis_on_continue():
    """Le cas réel du 17/11 : la mémoire revenait au vert trente secondes plus tard."""
    gouverneur = _FauxGouverneur(["PAUSER", "PAUSER", "CONTINUER"])
    verdict = F.patienter_sous_pression(br=gouverneur)
    assert verdict["continuer"] is True and verdict["incident"] is True and verdict["coupable"] == "EXTERIEUR"
    assert gouverneur.attentes == [30.0, 60.0] and verdict["attendu_s"] == 14.0


def test_pression_externe_PERSISTANTE_on_finit_par_s_arreter_et_on_dit_pourquoi():
    gouverneur = _FauxGouverneur(["PAUSER"] * 20)
    verdict = F.patienter_sous_pression(br=gouverneur)
    assert verdict["continuer"] is False and verdict["detail"] == F.DETAIL_EXTERNE_PERSISTANTE
    assert gouverneur.attentes == list(F.PATIENCE_S), "toute la patience a été essayée avant de renoncer"


def test_si_c_est_NOTRE_charge_on_s_arrete_TOUT_DE_SUITE():
    """Attendre ne libère rien quand c'est nous qui saturons : on rétrécit."""
    gouverneur = _FauxGouverneur(["PAUSER"], coupable="NOUS")
    verdict = F.patienter_sous_pression(br=gouverneur)
    assert verdict == {"continuer": False, "attendu_s": 0.0, "incident": True, "coupable": "NOUS",
                       "detail": F.DETAIL_NOTRE_CHARGE}
    assert gouverneur.attentes == []


def test_une_decision_sans_photo_memoire_est_toleree():
    gouverneur = _FauxGouverneur(["PAUSER", "CONTINUER"], sans_etat=True)
    assert F.patienter_sous_pression(br=gouverneur)["continuer"] is True
    assert gouverneur.photos == 1


def test_un_gouverneur_en_panne_ne_bloque_pas_le_labo():
    class _Casse:
        PAUSER = "PAUSER"

        def decision(self):
            raise RuntimeError("psutil a disparu")

    assert F.patienter_sous_pression(br=_Casse())["continuer"] is True


def test_le_pont_REPREND_apres_une_alerte_passagere(tmp_path, monkeypatch):
    """Avant : une seule alerte abandonnait tous les shards restants."""
    _coffre(tmp_path, {"2026-11-13": True, "2026-11-14": True, "2026-11-15": True})
    appels = {"n": 0}

    def decision(**_k):
        appels["n"] += 1
        return {"action": BR.PAUSER if appels["n"] == 1 else BR.CONTINUER, "raison": "test",
                "etat": {"dispo_octets": 2 * 2**30, "total_octets": 32 * 2**30}}

    monkeypatch.setattr(BR, "decision", decision)
    monkeypatch.setattr(BR, "attendre_que_ca_respire", lambda **_k: {"attendu_s": 12.0, "a_respire": True})
    monkeypatch.setattr(BR, "memoire_de_l_arbre_octets", lambda *a, **k: 2**28)
    res = TL._charger_tier_local(tmp_path)
    assert res["chargement_arrete"] is None and res["shards_non_lus"] == 0
    assert res["shards_injectes"] == 6
    assert res["memoire"] == {"incidents": 1, "attendu_s": 12.0, "arret_detail": None}


def test_le_pont_s_arrete_si_c_est_sa_propre_charge_et_le_detaille(tmp_path, monkeypatch):
    _coffre(tmp_path, {"2026-11-13": True, "2026-11-14": True})
    monkeypatch.setattr(BR, "decision", lambda **_k: {"action": BR.PAUSER, "raison": "test",
                                                    "etat": {"dispo_octets": 2**30, "total_octets": 4 * 2**30}})
    monkeypatch.setattr(BR, "memoire_de_l_arbre_octets", lambda *a, **k: 3 * 2**30)
    res = TL._charger_tier_local(tmp_path)
    assert res["chargement_arrete"] == F.ARRET_MEMOIRE
    assert res["memoire"]["arret_detail"] == F.DETAIL_NOTRE_CHARGE and res["shards_non_lus"] > 0


# ───────────────────────── le verdict ─────────────────────────

def test_lecture_complete_aucune_mention():
    assert F.mention_de_lecture({"chargement_arrete": None, "shards_injectes": 9, "shards_non_lus": 0}) == ""
    assert F.mention_de_lecture(None) == "" and F.mention_de_lecture({}) == ""


def test_lecture_INTERROMPUE_le_verdict_doit_le_dire():
    mention = F.mention_de_lecture({"chargement_arrete": "MEMOIRE_CRITIQUE", "shards_injectes": 60,
                                    "shards_non_lus": 6349})
    assert "MEMOIRE_CRITIQUE" in mention and "60 shards lus" in mention and "6349 non lus" in mention
    assert "pas le coffre" in mention


def test_le_labo_demande_la_fenetre_et_la_publie():
    source = inspect.getsource(LAB)
    assert "fenetre_locale = _FENETRE_LOCALE.choisir_la_fenetre(repository_root)" in source
    assert 'depuis_ms=fenetre_locale["depuis_ms"]' in source
    assert 'coffre_local_resume["fenetre_choisie"] = fenetre_locale' in source
    # 18/11 : le pont ne materialise plus les familles lourdes, le labo les lit en flux
    assert "garder_replay=False" in source


def test_la_console_ajoute_la_mention_au_verdict():
    import alina_quant_lab_console as C

    source = inspect.getsource(C)
    assert "freeze_verdict += FENETRE_LOCALE.mention_de_lecture(" in source


def test_une_seule_definition_du_premier_jour_liable():
    import matrice_coffre as M

    assert M.premier_jour_liable is F.premier_jour_liable


@pytest.mark.parametrize("patience", [F.PATIENCE_S])
def test_la_patience_totale_reste_bornee(patience):
    assert sum(patience) <= 600, "le labo ne doit pas attendre indéfiniment"
