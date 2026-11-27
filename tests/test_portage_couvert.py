"""Portage couvert sur funding (26/11/2026) : la regle figee, mesuree sans regarder le futur."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for chemin in (RACINE / "src", RACINE / "tools"):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

from hl_observer.backtesting import copy_vault_research_planner as PLAN  # noqa: E402
from hl_observer.backtesting import portage_couvert as P  # noqa: E402

H, J = P.HEURE_MS, P.JOUR_MS
J0 = 20_000                                                     # un jour UTC quelconque


def _obs(coin: str, jours: range, taux) -> list[tuple]:
    """Une observation par heure ; ``taux`` peut dependre du jour (fonction) ou etre constant."""
    out = []
    for j in jours:
        for h in range(24):
            out.append((coin, (J0 + j) * J + h * H + 5, taux(j) if callable(taux) else taux))
    return out


def test_une_heure_n_est_comptee_qu_une_fois_et_les_lignes_illisibles_sont_ignorees():
    obs = _obs("BTC", range(2), 1e-5) + _obs("BTC", range(1), 9e-5)            # doublons : premiere vue gardee
    obs += [("BTC", None, 1e-5), ("", J0 * J, 1e-5), ("ETH", J0 * J, "abc"), ("ETH", True, 1e-5)]
    fj = P.funding_journalier(obs)
    assert fj["coins"] == ["BTC"] and fj["heures"][0].tolist() == [24.0, 24.0]
    assert abs(fj["somme"][0, 0] - 24e-5) < 1e-12


def test_la_selection_ne_lit_que_le_passe():
    cfg = P.PortageConfig(k=1)
    # ETH paie fort AVANT chaque debut de periode ; SOL ne paie fort qu'APRES : le futur ne doit jamais choisir.
    obs = _obs("ETH", range(90), lambda j: 3e-5 if (j // 30) % 2 == 0 else 1e-5)
    obs += _obs("SOL", range(90), lambda j: 0.5e-5 if (j // 30) % 2 == 0 else 9e-5)
    periodes = P.simuler_portage(P.funding_journalier(obs), cfg)
    assert periodes[0]["coins"] == ["ETH"]                       # choisi sur les jours 0-29, ou ETH paie plus
    assert abs(periodes[0]["funding_bps"] - 30 * 24 * 1e-5 * 1e4) < 1e-6   # puis encaisse les jours 30-59 (bas)


def test_les_frais_ne_se_paient_qu_aux_changements():
    cfg = P.PortageConfig(k=2)
    obs = _obs("BTC", range(150), 2e-5) + _obs("ETH", range(150), 1.5e-5) + _obs("SOL", range(150), 1e-5)
    periodes = P.simuler_portage(P.funding_journalier(obs), cfg)
    assert periodes[0]["frais_bps"] == cfg.frais_rotation_bps * (2 / 2)          # deux entrees, poids 1/2 chacune
    assert all(p["frais_bps"] == 0 for p in periodes[1:])                         # meme selection : rien a payer


def test_un_marche_non_couvrable_n_est_jamais_choisi():
    obs = _obs("xyz:NATGAS", range(90), 9e-4) + _obs("BTC", range(90), 1e-5)
    periodes = P.simuler_portage(P.funding_journalier(obs), P.PortageConfig(k=5))
    assert all(p["coins"] == ["BTC"] for p in periodes)


def test_un_funding_negatif_partout_ne_fait_rien_tenir():
    periodes = P.simuler_portage(P.funding_journalier(_obs("BTC", range(90), -2e-5)), P.PortageConfig())
    assert all(p["coins"] == [] and p["net_bps"] == 0 for p in periodes)


def test_verdicts():
    jours = range(30 * 16)
    gagnant = P.etudier(_obs("BTC", jours, 1e-5) + _obs("ETH", jours, 1.2e-5))
    assert gagnant["verdicts"][0]["status"] == "PROMISING"
    assert gagnant["primary"]["mois"] == 15 and gagnant["primary"]["mois_negatifs"] == 0
    perdant = P.etudier(_obs("BTC", jours, lambda j: 1e-5 if j < 30 or (j // 30) % 2 else -3e-5))
    assert perdant["verdicts"][0]["status"] in ("REJECTED", "MORE_DATA")
    court = P.etudier(_obs("BTC", range(30 * 5), 1e-5))
    assert court["verdicts"][0]["status"] == "MORE_DATA" and "il en faut au moins 12" in court["verdicts"][0]["reason"]


def test_le_planificateur_lit_le_portage():
    jours = range(30 * 16)
    rapport = P.etudier(_obs("BTC", jours, 1e-5))
    record = {"verdicts": rapport["verdicts"], "primary": rapport["primary"], "config": rapport["config"]}
    plan = PLAN.build_plan([record])
    ligne = next(h for h in plan["hypotheses"] if h["hypothesis"] == P.HYPOTHESE)
    assert ligne["status"] == "PROMISING" and ligne["effet"] is not None
    # hors famille CopyVault : mesure affichee, mais jamais prioritaire ni « prochaine action »
    assert ligne["hors_famille_copyvault"] is True and ligne["priorite"] == 0
    assert plan["prochaine_action"] != P.HYPOTHESE


def test_le_rapport_du_labo_se_lit():
    import etude_copiabilite as E

    rapport = P.etudier(_obs("BTC", range(30 * 16), 1e-5))
    texte = E.render_portage_report(rapport, {"experiment_id": "x", "code_head": "y"})
    assert "funding_hedged_carry_majors" in texte and "couverture parfaite" in texte and "IN-SAMPLE" in texte


def test_sans_funding_le_labo_continue(tmp_path, monkeypatch):
    import etude_copiabilite as E

    # coffre PRESENT (sinon la garde commune « coffre LOCAL absent » repond 2 pour toutes les etudes), sans funding
    (tmp_path / "runtime" / "coffre_certifie").mkdir(parents=True)
    (tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").write_text('{"shards": []}', encoding="utf-8")
    monkeypatch.setattr(E, "select_shards", lambda root, wanted, **_: ({"funding_history": []}, []))
    monkeypatch.setattr(sys, "argv", ["etude_copiabilite.py", "--root", str(tmp_path), "--portage"])
    assert E.main() == 0
