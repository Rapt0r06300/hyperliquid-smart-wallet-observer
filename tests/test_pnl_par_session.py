"""PnL PAR SESSION (20/07, demande de Flo) — repartir à zéro SANS rien effacer.

Le contrat, en trois lois :
  1. chaque ligne du ledger porte le `session_id` de SA session (append-only inchangé) ;
  2. le PnL « session courante » ne compte QUE les fermetures de cette session — au
     redémarrage (nouvel id), il vaut zéro ;
  3. l'HISTORIQUE complet reste : dans `realized_net_pnl_usdc`, dans le fichier ligne par
     ligne, dans le rapport quotidien. Remettre à zéro l'affichage n'est jamais effacer.

Le piège évité : les vieilles lignes SANS étiquette (d'avant ce commit) n'appartiennent à
AUCUNE session courante — elles comptent dans l'historique, jamais dans la session.
"""
from __future__ import annotations

import json

from hl_observer.funding.carry_positions_store import (
    LEDGER_RELPATH, etat_carry, resume_depuis_ledger, tick_sur_disque,
)

_DEC = {"coin": "HYPE", "funding_bps_h": 0.125, "base_bps": -0.68,
        "liquidite_spot_usd": 200_000.0, "cout_entree_bps": -19.0, "base_bps_entree": 30.0,
        "heures_pour_rentabiliser": 72.0, "viable": True, "motif": "CARRY_NEUTRE_VIABLE",
        "real_execution": False}
_INP = {"ts_ms": 0, "coin": "HYPE", "levier_utilise": 2.0, "levier_max": 10.0,
        "marge_ratio": 0.5, "perp_px": 1.0}
H = 3_600_000


def _cycle(root, *, base=30.0):
    """Un OPEN + un CLOSE (hemorragie) -> deux lignes de ledger."""
    d = dict(_DEC); d["base_bps"] = base
    tick_sur_disque(root, d, _INP, now_ms=0, funding_bps_h_courant=0.125)
    tick_sur_disque(root, d, _INP, now_ms=200 * H, funding_bps_h_courant=-1.0)


def test_1_chaque_ligne_du_ledger_porte_sa_session(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSMART_SESSION_ID", "S-UN")
    _cycle(tmp_path)
    lignes = [json.loads(l) for l in
              (tmp_path / LEDGER_RELPATH).read_text(encoding="utf-8").splitlines()]
    assert lignes and all(r.get("session_id") == "S-UN" for r in lignes)


def test_2_nouvelle_session_PNL_SESSION_A_ZERO_historique_INTACT(tmp_path, monkeypatch):
    """LE COEUR DE LA DEMANDE. Session 1 perd ; on redemarre (nouvel id) : le compteur de
    session vaut 0,00 — et l'historique garde la perte, au centime."""
    monkeypatch.setenv("HYPERSMART_SESSION_ID", "S-UN")
    _cycle(tmp_path)
    e1 = etat_carry(tmp_path)
    assert e1["closes"] == 1 and e1["realized_net_pnl_usdc"] != 0.0
    assert e1["realized_net_pnl_usdc_session"] == e1["realized_net_pnl_usdc"]

    monkeypatch.setenv("HYPERSMART_SESSION_ID", "S-DEUX")          # <- redemarrage
    e2 = etat_carry(tmp_path)
    assert e2["realized_net_pnl_usdc_session"] == 0.0, "nouvelle session = compteur a zero"
    assert e2["closes_session"] == 0
    assert e2["realized_net_pnl_usdc"] == e1["realized_net_pnl_usdc"], (
        "l'HISTORIQUE ne bouge pas d'un centime — remettre a zero n'est jamais effacer")
    assert e2["closes"] == 1


def test_3_la_nouvelle_session_compte_SES_fermetures(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSMART_SESSION_ID", "S-UN")
    _cycle(tmp_path)
    total_s1 = etat_carry(tmp_path)["realized_net_pnl_usdc"]
    monkeypatch.setenv("HYPERSMART_SESSION_ID", "S-DEUX")
    _cycle(tmp_path)
    e = etat_carry(tmp_path)
    assert e["closes_session"] == 1
    assert e["closes"] == 2
    assert round(e["realized_net_pnl_usdc"], 6) == round(
        total_s1 + e["realized_net_pnl_usdc_session"], 6), "historique = somme des sessions"


def test_4_les_vieilles_lignes_SANS_etiquette_restent_hors_session(tmp_path, monkeypatch):
    """Les lignes d'avant ce commit n'ont pas de session_id : historique OUI, session NON."""
    p = tmp_path / LEDGER_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"kind": "CLOSE", "coin": "PURR", "mode": "LIVE",
                             "realized_net_pnl_usdc": -5.0, "ts_ms": 1}) + "\n",
                 encoding="utf-8")
    monkeypatch.setenv("HYPERSMART_SESSION_ID", "S-COURANTE")
    e = etat_carry(tmp_path)
    assert e["realized_net_pnl_usdc"] == -5.0                      # l'histoire reste
    assert e["realized_net_pnl_usdc_session"] == 0.0               # la session demarre propre


def test_5_sans_session_id_le_resume_reste_l_ancien_contrat(tmp_path, monkeypatch):
    """Retro-compatibilite : les appels existants (sans session) gardent les memes cles."""
    monkeypatch.setenv("HYPERSMART_SESSION_ID", "S-UN")
    _cycle(tmp_path)
    r = resume_depuis_ledger(tmp_path)
    assert "realized_net_pnl_usdc" in r and "realized_net_pnl_usdc_session" not in r
