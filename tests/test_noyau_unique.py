"""G2 -- LE NOYAU UNIQUE, ET L'INVARIANT QUI L'EMPECHE D'ETRE CONTOURNE.

Un noyau qu'on peut contourner ne decide rien. Ces tests verifient les deux moities :

  1. le noyau REFUSE tout ce qu'il doit refuser (zone morte, edge fabrique, edge non mesure,
     prix inexecutable, edge net insuffisant) -- et surtout : il REFUSE l'edge que l'appelant
     lui apporte ;
  2. AUCUN module de production ne calcule un edge d'entree en dehors de lui.

Aucun ordre reel.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from hl_observer.decision_engine.noyau_unique import (
    EDGE_FOURNI_CONTREDIT_LA_MESURE,
    EDGE_FOURNI_IGNORE,
    ENTREE,
    NO_TRADE,
    REFUS_EDGE_FABRIQUE,
    REFUS_EDGE_NET_INSUFFISANT,
    REFUS_EDGE_NON_MESURE,
    REFUS_FAMILLE_INCONNUE,
    REFUS_NOTIONAL_INVALIDE,
    REFUS_PRIX_NON_EXECUTABLE,
    REFUS_QUALITE_FLUX,
    REFUS_ZONE_MORTE,
    QUALITE_FLUX_NON_FOURNIE,
    Contexte,
    decider,
    famille_de_la_strategie,
)
from hl_observer.edge.edge_source import SOURCE_FORMULE, SOURCE_TABLE, vider_le_cache
from hl_observer.edge.measured_edge_table import Features, Observation, construire
from hl_observer.signals.signal_taxonomy import (
    CARRY_STRUCTUREL,
    DISCRETIONNAIRE_PUBLIC,
    FLUX_FORCE,
)

RACINE = Path(__file__).resolve().parents[1]
SRC = RACINE / "src" / "hl_observer"


@pytest.fixture(autouse=True)
def _cache_propre():
    vider_le_cache()
    yield
    vider_le_cache()


def _table_avec_edge(strategie: str, coin: str, edge: float, ms: float = 1_000.0):
    obs = [
        Observation(
            features=Features(strategie=strategie, coin=coin, direction="LONG",
                              signal_age_ms=500.0, leader_score=70.0, consensus_wallets=2.0),
            markout_bps=edge + (0.2 if i % 2 else -0.2),
            signal_ms=ms,
        )
        for i in range(60)
    ]
    return construire(obs, horizon_ms=60_000, min_echantillons=30)


def _ctx(**kw):
    base = dict(
        strategie="FUNDING", coin="BTC", direction="LONG", notional_usd=500.0,
        signal_ms=9_999_999.0, signal_age_ms=500.0, leader_score=70.0, consensus_wallets=2.0,
        niveaux_achat=[(100.0, 1_000.0)], niveaux_vente=[(99.9, 1_000.0)],
        frais_bps=12.0, plancher_edge_net_bps=0.0,
    )
    base.update(kw)
    return Contexte(**base)  # type: ignore[arg-type]


def test_le_noyau_IGNORE_l_edge_fourni_par_l_appelant(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    t = _table_avec_edge("ARBITRAGE", "BTC", 40.0)
    d = decider(_ctx(edge_fourni_bps=999.0, strategie="ARBITRAGE"), table=t)
    assert d.edge_brut_bps == pytest.approx(40.0, abs=1.0)
    assert EDGE_FOURNI_IGNORE in d.signalements
    assert EDGE_FOURNI_CONTREDIT_LA_MESURE in d.signalements


def test_un_edge_fourni_COHERENT_ne_declenche_pas_de_contradiction(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    t = _table_avec_edge("ARBITRAGE", "BTC", 40.0)
    d = decider(_ctx(edge_fourni_bps=39.8, strategie="ARBITRAGE"), table=t)
    assert EDGE_FOURNI_IGNORE in d.signalements
    assert EDGE_FOURNI_CONTREDIT_LA_MESURE not in d.signalements


def test_le_noyau_n_appelle_JAMAIS_de_formule_de_secours(monkeypatch):
    """La mécanique table se teste sur une famille table, jamais sur le carry funding réel."""
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    d = decider(
        _ctx(coin="INCONNU_XYZ", strategie="ARBITRAGE"),
        table=_table_avec_edge("ARBITRAGE", "BTC", 40.0),
    )
    assert d.verdict == NO_TRADE
    assert d.raison == REFUS_EDGE_NON_MESURE
    assert d.edge_brut_bps is None


def test_le_mode_FORMULE_ne_franchit_PAS_le_noyau(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_FORMULE)
    d = decider(_ctx())
    assert d.verdict == NO_TRADE
    assert d.raison == REFUS_EDGE_FABRIQUE
    assert d.edge_fabrique is True


def test_1_la_ZONE_MORTE_est_refusee_AVANT_tout_calcul(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    d = decider(_ctx(strategie="COPY"), table=_table_avec_edge("COPY", "BTC", 999.0))
    assert d.verdict == NO_TRADE
    assert d.raison == REFUS_ZONE_MORTE
    assert d.famille == DISCRETIONNAIRE_PUBLIC
    assert d.edge_brut_bps is None


def test_1b_une_strategie_INCONNUE_est_refusee(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    d = decider(_ctx(strategie="MA_SUPER_STRATEGIE_V2"))
    assert d.raison == REFUS_FAMILLE_INCONNUE
    assert famille_de_la_strategie("MA_SUPER_STRATEGIE_V2") == ""


def test_3_un_PRIX_INEXECUTABLE_est_refuse(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    t = _table_avec_edge("ARBITRAGE", "BTC", 100.0)
    d = decider(_ctx(niveaux_achat=[(100.0, 0.5)], strategie="ARBITRAGE"), table=t)
    assert d.verdict == NO_TRADE
    assert d.raison == REFUS_PRIX_NON_EXECUTABLE
    assert d.edge_brut_bps == pytest.approx(100.0, abs=1.0)


def test_3b_sans_carnet_du_tout_on_REFUSE(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    t = _table_avec_edge("FUNDING", "BTC", 100.0)
    assert decider(_ctx(niveaux_achat=None), table=t).raison == REFUS_PRIX_NON_EXECUTABLE


def test_4_l_EDGE_NET_est_calcule_APRES_les_vrais_couts(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    t = _table_avec_edge("ARBITRAGE", "BTC", 40.0)
    d = decider(_ctx(frais_bps=12.0, degradation_copie_bps=13.0, plancher_edge_net_bps=20.0,
                     strategie="ARBITRAGE"), table=t)
    assert d.verdict == NO_TRADE
    assert d.raison == REFUS_EDGE_NET_INSUFFISANT
    assert d.couts_bps == pytest.approx(25.0, abs=0.1)
    assert d.edge_net_bps == pytest.approx(15.0, abs=1.0)
    d2 = decider(_ctx(frais_bps=12.0, degradation_copie_bps=13.0, plancher_edge_net_bps=10.0,
                      strategie="ARBITRAGE"), table=t)
    assert d2.verdict == ENTREE
    assert d2.autorise


def test_le_SLIPPAGE_reel_entre_dans_les_couts(monkeypatch):
    """Le slippage directionnel vient du carnet traverse ; le carry a son test 4-jambes dédié."""
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    t = _table_avec_edge("ARBITRAGE", "BTC", 100.0)
    d = decider(
        _ctx(
            strategie="ARBITRAGE",
            niveaux_achat=[(10.0, 10.0), (10.5, 1_000.0)],
            frais_bps=0.0,
        ),
        table=t,
    )
    assert d.slippage_bps is not None and d.slippage_bps > 0.0
    assert d.couts_bps == pytest.approx(d.slippage_bps, abs=1e-6)


def test_un_notional_invalide_REFUSE_avant_tout():
    assert decider(_ctx(notional_usd=0.0)).raison == REFUS_NOTIONAL_INVALIDE
    assert decider(_ctx(notional_usd=-1.0)).raison == REFUS_NOTIONAL_INVALIDE


def test_qualite_flux_runtime_explicitement_mauvaise_refuse_avant_l_edge():
    d = decider(_ctx(feed_quality_ready=False, feed_quality_score=92.0,
                     feed_quality_reasons=("UNRESOLVED_GAP",)))
    assert d.verdict == NO_TRADE
    assert d.raison == REFUS_QUALITE_FLUX
    assert d.preuve["feed_quality"]["reasons"] == ["UNRESOLVED_GAP"]


def test_score_qualite_flux_sous_le_plancher_refuse():
    d = decider(_ctx(feed_quality_ready=True, feed_quality_score=74.99))
    assert d.raison == REFUS_QUALITE_FLUX
    assert d.preuve["feed_quality"]["score"] == pytest.approx(74.99)


def test_qualite_dite_prete_sans_score_mesurable_refuse():
    d = decider(_ctx(feed_quality_ready=True, feed_quality_score=None))
    assert d.raison == REFUS_QUALITE_FLUX


def test_appel_legacy_sans_qualite_reste_trace():
    d = decider(_ctx(strategie="COPY"))
    assert d.raison == REFUS_ZONE_MORTE
    assert QUALITE_FLUX_NON_FOURNIE in d.signalements


def test_le_noyau_ne_pretend_JAMAIS_a_une_execution_reelle(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    d = decider(_ctx(), table=_table_avec_edge("FUNDING", "BTC", 40.0))
    assert d.paper_only is True
    assert d.as_dict()["real_execution"] is False


def test_les_familles_couvrent_les_4_moteurs_de_G2():
    assert famille_de_la_strategie("GRINDER") == DISCRETIONNAIRE_PUBLIC
    assert famille_de_la_strategie("SNIPER") == DISCRETIONNAIRE_PUBLIC
    assert famille_de_la_strategie("COPY") == DISCRETIONNAIRE_PUBLIC
    assert famille_de_la_strategie("ARBITRAGE") == FLUX_FORCE
    assert famille_de_la_strategie("FUNDING") == CARRY_STRUCTUREL


_NOM_EDGE = re.compile(r"(expected_edge|edge_bps|edge_remaining)", re.I)
_ARITHMETIQUE = (ast.Add, ast.Sub, ast.Mult, ast.Div)


def _modules_de_production() -> list[Path]:
    out = []
    for f in sorted(SRC.rglob("*.py")):
        p = str(f)
        if "__pycache__" in p or "DISABLED" in p:
            continue
        out.append(f)
    return out


def _cibles(noeud: ast.AST) -> list[str]:
    noms = []
    if isinstance(noeud, ast.Assign):
        cibles = noeud.targets
    elif isinstance(noeud, ast.AnnAssign):
        cibles = [noeud.target]
    else:
        return noms
    for c in cibles:
        if isinstance(c, ast.Name):
            noms.append(c.id)
        elif isinstance(c, ast.Attribute):
            noms.append(c.attr)
    return noms


_MARQUEUR = "EDGE_NON_FABRIQUE:"


def _exemption_justifiee(lignes: list[str], lineno: int) -> bool:
    debut = max(0, lineno - 9)
    fenetre = lignes[debut : max(0, lineno - 1)]
    for ligne in fenetre:
        if _MARQUEUR in ligne:
            raison = ligne.split(_MARQUEUR, 1)[1].strip()
            suite = "".join(
                l.strip().lstrip("#").strip()
                for l in fenetre[fenetre.index(ligne) + 1 :]
                if l.strip().startswith("#")
            )
            return len(raison + suite) >= 60
    return False


def _est_une_formule_inventee(valeur: ast.AST) -> bool:
    binops = [n for n in ast.walk(valeur) if isinstance(n, ast.BinOp) and isinstance(n.op, _ARITHMETIQUE)]
    if not binops:
        return False
    constantes = [
        n.value for n in ast.walk(valeur)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
        and not isinstance(n.value, bool)
    ]
    variables = [n for n in ast.walk(valeur) if isinstance(n, (ast.Name, ast.Attribute))]
    return len(constantes) >= 2 and len(variables) >= 1


def test_AUCUN_module_de_production_ne_FABRIQUE_un_edge_d_entree():
    coupables = []
    for f in _modules_de_production():
        try:
            texte = f.read_text(encoding="utf-8", errors="ignore")
            arbre = ast.parse(texte)
        except (OSError, SyntaxError):
            continue
        lignes = texte.splitlines()
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, (ast.Assign, ast.AnnAssign)):
                continue
            if noeud.value is None:
                continue
            if not any(_NOM_EDGE.search(n) for n in _cibles(noeud)):
                continue
            if not _est_une_formule_inventee(noeud.value):
                continue
            if _exemption_justifiee(lignes, getattr(noeud, "lineno", 0)):
                continue
            coupables.append(
                f"{f.relative_to(RACINE)}:{getattr(noeud, 'lineno', 0)}  "
                f"{'/'.join(_cibles(noeud))} = <formule a constantes magiques>"
            )
    assert not coupables, (
        "EDGE(S) FABRIQUE(S) trouve(s) dans le code de production :\n  "
        + "\n  ".join(coupables[:10])
        + "\n\nUn edge d'entree se MESURE (hl_observer.edge.edge_source)."
    )


def test_l_invariant_ATTRAPE_vraiment_une_formule_fabriquee():
    vraie = ast.parse(
        "leader_expected_edge_bps = 18.0 + confidence * 34.0 + min(24.0, (n - 1) * 8.0)"
    ).body[0]
    assert isinstance(vraie, ast.Assign)
    assert _est_une_formule_inventee(vraie.value)
    honnete = ast.parse("edge_net_bps = edge_brut_bps - couts_bps").body[0]
    assert isinstance(honnete, ast.Assign)
    assert not _est_une_formule_inventee(honnete.value)
    mesure = ast.parse(
        "leader_expected_edge_bps = float(e.valeur_bps) if e.utilisable else 0.0"
    ).body[0]
    assert isinstance(mesure, ast.Assign)
    assert not _est_une_formule_inventee(mesure.value)


def test_le_MARQUEUR_d_exemption_n_est_PAS_un_blanc_seing():
    nu = ["# EDGE_NON_FABRIQUE:", "edge_bps = 1.0 + x * 2.0"]
    assert not _exemption_justifiee(nu, 2)
    trois_mots = ["# EDGE_NON_FABRIQUE: c'est bon", "edge_bps = 1.0 + x * 2.0"]
    assert not _exemption_justifiee(trois_mots, 2)
    vrai = [
        "# EDGE_NON_FABRIQUE: c'est un SEUIL de politique de risque, pas une valeur d'edge : on",
        "# ne predit rien, on exige une barre plus haute apres des pertes.",
        "edge_bps = min_edge + 10.0",
    ]
    assert _exemption_justifiee(vrai, 3)


def test_le_noyau_importe_BIEN_les_trois_verrous():
    src = (SRC / "decision_engine" / "noyau_unique.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    importes = {
        n.module for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.module
    }
    assert "hl_observer.edge.edge_source" in importes
    assert "hl_observer.arbitrage.executable_legs" in importes
    assert "hl_observer.signals.signal_taxonomy" in importes
