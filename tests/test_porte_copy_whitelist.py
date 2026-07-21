"""#185 — la porte copy-whitelist : DEUXIÈME verrou du copy-follow, EN SÉRIE.

La loi du 11/07 (copy global : −7,97 bps OOS) a tué le copy moyen ; C12 a montré qu'une
minorité de leaders a un markout forward positif. Cette porte impose : même si le verrou
d'edge s'ouvrait, on ne suit QUE ces leaders-là. Deny-by-default absolu — chaque état
dégradé (absent / vide / périmé / illisible / hors liste / sans adresse) est un REFUS
MOTIVÉ, jamais une exception silencieuse, jamais un passage par défaut.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from hl_observer.signals.porte_copy_whitelist import (
    AGE_MAX_WHITELIST_H, CHEMIN_WHITELIST, MOTIF_ABSENTE, MOTIF_HORS_LISTE,
    MOTIF_ILLISIBLE, MOTIF_PERIMEE, MOTIF_SANS_ADRESSE, MOTIF_VIDE,
    signal_copy_autorise,
)

A1, A2 = "0xAAA1", "0xbbb2"


def _ecrire(root: Path, gardes, genere_ts=None, brut=None):
    p = root / CHEMIN_WHITELIST
    p.parent.mkdir(parents=True, exist_ok=True)
    if brut is not None:
        p.write_text(brut, encoding="utf-8")
    else:
        p.write_text(json.dumps({"genere_ts": genere_ts if genere_ts is not None else time.time(),
                                 "gardes": gardes, "rejetes": 0, "regle": "test"}), encoding="utf-8")


# ------------------------------------------------ deny-by-default : chaque etat degrade refuse

def test_fichier_absent_refuse(tmp_path):
    assert signal_copy_autorise([A1], root=tmp_path) == (False, MOTIF_ABSENTE)


def test_liste_vide_est_verrouillee(tmp_path):
    _ecrire(tmp_path, [])
    assert signal_copy_autorise([A1], root=tmp_path) == (False, MOTIF_VIDE)


def test_liste_perimee_refuse_un_markout_d_avant_hier_ne_vaut_plus_permission(tmp_path):
    _ecrire(tmp_path, [{"adresse": A1}], genere_ts=time.time() - (AGE_MAX_WHITELIST_H + 1) * 3600)
    assert signal_copy_autorise([A1], root=tmp_path) == (False, MOTIF_PERIMEE)


def test_fichier_illisible_refuse_au_lieu_de_lever(tmp_path):
    _ecrire(tmp_path, None, brut="{pas du json")
    assert signal_copy_autorise([A1], root=tmp_path) == (False, MOTIF_ILLISIBLE)


def test_signal_sans_adresse_refuse(tmp_path):
    _ecrire(tmp_path, [{"adresse": A1}])
    assert signal_copy_autorise([], root=tmp_path) == (False, MOTIF_SANS_ADRESSE)
    assert signal_copy_autorise(None, root=tmp_path) == (False, MOTIF_SANS_ADRESSE)


def test_UN_SEUL_votant_hors_liste_contamine_le_consensus(tmp_path):
    """On ne moyenne pas un leader prouvé avec un leader réfuté : TOUS ou refus."""
    _ecrire(tmp_path, [{"adresse": A1}])
    assert signal_copy_autorise([A1, A2], root=tmp_path) == (False, MOTIF_HORS_LISTE)


def test_tous_les_votants_whitelistes_passent_insensible_a_la_casse(tmp_path):
    _ecrire(tmp_path, [{"adresse": A1}, {"adresse": A2}])
    assert signal_copy_autorise([A1.lower(), A2.upper()], root=tmp_path) == (True, None)


# ------------------------------------------------ cablage : la porte est SUR le chemin (X4)

def test_invariant_la_porte_est_EN_SERIE_avant_l_ouverture_dans_fusion_runtime():
    """Mention ≠ porte (leçon V8) : le refus d'edge, PUIS la whitelist, PUIS l'ouverture —
    dans cet ordre, dans la source. Un elif déplacé ou supprimé casse ce test."""
    src = open("src/hl_observer/strategies/fusion_runtime.py", encoding="utf-8").read()
    i_edge = src.index('no_trade.append("COPY_FOLLOW_BLOCKED_BY_EMPIRICAL_EDGE_GATE")')
    i_wl = src.index("not _copy_whitelist_ok(")
    i_open = src.index('"copy_conflict_resolved_follow"')
    assert i_edge < i_wl < i_open, "l'ordre des verrous a change : edge -> whitelist -> ouverture"
    assert "from hl_observer.signals.porte_copy_whitelist import signal_copy_autorise" in src


def test_integration_le_helper_extrait_les_votants_gagnants_et_motive_le_refus(tmp_path, monkeypatch):
    from hl_observer.copy_wallet.copy_conflict_resolver import CopyConflictDecision, LeaderVote
    from hl_observer.strategies.fusion_runtime import _copy_whitelist_ok
    monkeypatch.chdir(tmp_path)
    conflict = CopyConflictDecision(coin="HYPE", decision="FOLLOW", winning_side="LONG",
                                    long_score=2.0, short_score=0.0, reasons=())
    votes = (LeaderVote(wallet=A1, coin="HYPE", side="LONG"),
             LeaderVote(wallet=A2, coin="HYPE", side="SHORT"),   # perdant : ignore
             LeaderVote(wallet="0xcc", coin="PURR", side="LONG"))  # autre coin : ignore
    no_trade: list = []
    _ecrire(tmp_path, [{"adresse": A1}])
    assert _copy_whitelist_ok(conflict, votes, no_trade) is True and no_trade == []
    _ecrire(tmp_path, [{"adresse": A2}])   # le votant gagnant n'y est plus
    assert _copy_whitelist_ok(conflict, votes, no_trade) is False
    assert no_trade == [MOTIF_HORS_LISTE], "le motif precis doit partir dans no_trade"


# ---------------- 21/07 : la SOURCE de la whitelist enfin branchee ----------------

def test_le_moteur_journalise_les_fills_leaders_avec_dedup(tmp_path, monkeypatch):
    """leader_wallet etait VIDE sur 50 000 candidats replay : RIEN ne produisait les fills.
    Le moteur les voit a chaque cycle -> il les journalise (dedup, append, jamais bloquant)."""
    import json as _j
    from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote
    from hl_observer.strategies import fusion_runtime as fr
    monkeypatch.chdir(tmp_path)
    fr._FILLS_LEADERS_VUS.clear()
    votes = (LeaderVote(wallet="0xAA", coin="SOL", side="LONG", observed_at_ms=1000),
             LeaderVote(wallet="", coin="SOL", side="LONG", observed_at_ms=1000),   # sans wallet: ignore
             LeaderVote(wallet="0xAA", coin="SOL", side="LONG", observed_at_ms=1000))  # doublon
    fr._journaliser_fills_leaders(votes)
    fr._journaliser_fills_leaders(votes)                # rejoue : le dedup tient entre cycles
    lignes = (tmp_path / "runtime" / "data" / "leader_fills_bruts.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    assert len(lignes) == 1
    assert _j.loads(lignes[0]) == {"adresse": "0xAA", "coin": "SOL", "side": "LONG",
                                   "ts_ms": 1000, "real_execution": False}


def test_construire_fills_forward_joint_bruts_et_marks_sans_jamais_inventer(tmp_path):
    """mid au fill (<=5 min apres) + mid forward (a l'horizon, tolere 15 min) : un fill sans
    mark exploitable est IGNORE — jamais un prix invente."""
    import importlib.util, json as _j
    from pathlib import Path as _P
    spec = importlib.util.spec_from_file_location(
        "ecw", _P(__file__).resolve().parents[1] / "tools" / "ecrire_copy_whitelist.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    # 🔴 21/07 — FIXTURE CORRIGEE, ET C'ETAIT ELLE QUI AVAIT TORT.
    # Elle datait le fill a `ts_ms = 1_000_000`, soit le 1er janvier 1970. Le garde
    # anti-fixtures ajoute le meme jour (un horodatage doit tomber dans une fenetre
    # plausible, sinon un leader SYNTHETIQUE pourrait entrer dans la whitelist et
    # debloquer le copy sur une donnee FABRIQUEE) rejetait donc la fixture elle-meme.
    # Le garde a raison ; la fixture doit vivre dans le present, comme la vraie donnee.
    import time as _t
    T0 = _t.time() - 7200.0                       # il y a 2 h : plausible, et assez vieux
    d = tmp_path / "runtime" / "data"; d.mkdir(parents=True)                # pour le forward
    (d / "leader_fills_bruts.jsonl").write_text("\n".join([
        _j.dumps({"adresse": "0xa17e4f2c9b8d3e6a1f05c7d2b94e8a3f6c0d1b25", "coin": "SOL", "side": "LONG",
                  "ts_ms": int(T0 * 1000)}),
        _j.dumps({"adresse": "0xb28f5a3d0c9e4f7b2a16d8e3ca05f9b4d7e2c136", "coin": "SOL", "side": "SHORT",
                  "ts_ms": int((T0 + 9_000_000) * 1000)}),   # hors de toute plage de marks
    ]) + "\n", encoding="utf-8")
    r = tmp_path / "runtime" / "replay" / "_merged"; r.mkdir(parents=True)
    (r / "candidates.jsonl").write_text("{}\n", encoding="utf-8")
    (r / "marks.jsonl").write_text("\n".join(
        _j.dumps({"coin": "SOL", "ts": T0 + k, "mid": 100.0 + k}) for k in (10, 1800, 1850))
        + "\n", encoding="utf-8")
    n = m.construire_fills_forward(tmp_path, horizon_min=30.0)
    assert n == 1, "0xAA a fill+forward ; 0xBB (aucun mark) est ignore, jamais invente"
    row = _j.loads((d / "leader_fills_forward.jsonl").read_text(encoding="utf-8"))
    assert row["adresse"].startswith("0xa17e4f") and row["mid_at_fill"] == 110.0 and row["mid_forward"] == 1900.0
