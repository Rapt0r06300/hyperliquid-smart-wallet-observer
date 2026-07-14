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
    REFUS_ZONE_MORTE,
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


# ====================================================== 1. LE NOYAU POSSEDE L'EDGE


def test_le_noyau_IGNORE_l_edge_fourni_par_l_appelant(monkeypatch):
    """🔴 LE COEUR DE G2.

    `LocalDecisionEngine` prenait `candidate.edge_remaining_bps` TEL QUEL. Le RiskEngine notait
    ensuite ce nombre avec une arithmetique impeccable... sur une valeur qu'il n'avait JAMAIS
    questionnee. C'est comme ca que trois edges FABRIQUES ont vecu des mois.

    Le noyau, lui, VA CHERCHER l'edge. Il ne le RECOIT pas.
    """
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    t = _table_avec_edge("FUNDING", "BTC", 40.0)

    # L'appelant pretend avoir 999 bps d'edge. Le noyau mesure 40.
    d = decider(_ctx(edge_fourni_bps=999.0), table=t)

    assert d.edge_brut_bps == pytest.approx(40.0, abs=1.0), (
        "le noyau a utilise l'edge FOURNI (999) au lieu de l'edge MESURE (40)"
    )
    assert EDGE_FOURNI_IGNORE in d.signalements
    assert EDGE_FOURNI_CONTREDIT_LA_MESURE in d.signalements, (
        "un ecart de 959 bps entre le chiffre de l'appelant et la mesure doit laisser une TRACE"
    )


def test_un_edge_fourni_COHERENT_ne_declenche_pas_de_contradiction(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    t = _table_avec_edge("FUNDING", "BTC", 40.0)
    d = decider(_ctx(edge_fourni_bps=39.8), table=t)
    assert EDGE_FOURNI_IGNORE in d.signalements
    assert EDGE_FOURNI_CONTREDIT_LA_MESURE not in d.signalements


def test_le_noyau_n_appelle_JAMAIS_de_formule_de_secours(monkeypatch):
    """Il passe `formule_de_secours=None`. Il ne peut donc PAS fabriquer, meme par accident."""
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    d = decider(_ctx(coin="INCONNU_XYZ"), table=_table_avec_edge("FUNDING", "BTC", 40.0))
    assert d.verdict == NO_TRADE
    assert d.raison == REFUS_EDGE_NON_MESURE
    assert d.edge_brut_bps is None, "un edge rendu ici serait un edge INVENTE"


def test_le_mode_FORMULE_ne_franchit_PAS_le_noyau(monkeypatch):
    """On PEUT rallumer la formule (flag explicite). Mais elle n'autorise plus d'entree.

    C'est la difference entre « on peut mentir a la machine » et « la machine trade sur un
    mensonge ». Le premier est un choix d'outillage ; le second est un bug.
    """
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_FORMULE)
    d = decider(_ctx())
    assert d.verdict == NO_TRADE
    assert d.raison == REFUS_EDGE_FABRIQUE
    assert d.edge_fabrique is True


# ====================================================== 2. LES QUATRE QUESTIONS


def test_1_la_ZONE_MORTE_est_refusee_AVANT_tout_calcul(monkeypatch):
    """Le copy-trading est mort (3 mesures independantes). Inutile de calculer son edge."""
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    d = decider(_ctx(strategie="COPY"), table=_table_avec_edge("COPY", "BTC", 999.0))
    assert d.verdict == NO_TRADE
    assert d.raison == REFUS_ZONE_MORTE
    assert d.famille == DISCRETIONNAIRE_PUBLIC
    assert d.edge_brut_bps is None, (
        "le noyau a calcule l'edge d'une zone morte : il aurait pu se laisser convaincre"
    )


def test_1b_une_strategie_INCONNUE_est_refusee(monkeypatch):
    """Deny-by-default. « ma_super_strategie_v2 » n'a pas droit d'entrer par defaut."""
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    d = decider(_ctx(strategie="MA_SUPER_STRATEGIE_V2"))
    assert d.raison == REFUS_FAMILLE_INCONNUE
    assert famille_de_la_strategie("MA_SUPER_STRATEGIE_V2") == ""


def test_3_un_PRIX_INEXECUTABLE_est_refuse(monkeypatch):
    """Carnet trop mince : on ne peut pas acheter 500 $. On n'invente pas le prix."""
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    t = _table_avec_edge("FUNDING", "BTC", 100.0)
    d = decider(_ctx(niveaux_achat=[(100.0, 0.5)]), table=t)     # ~50 $ dispo
    assert d.verdict == NO_TRADE
    assert d.raison == REFUS_PRIX_NON_EXECUTABLE
    assert d.edge_brut_bps == pytest.approx(100.0, abs=1.0), (
        "l'edge etait bien mesure -- c'est le PRIX qui bloque, et la preuve doit le montrer"
    )


def test_3b_sans_carnet_du_tout_on_REFUSE(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    t = _table_avec_edge("FUNDING", "BTC", 100.0)
    assert decider(_ctx(niveaux_achat=None), table=t).raison == REFUS_PRIX_NON_EXECUTABLE


def test_4_l_EDGE_NET_est_calcule_APRES_les_vrais_couts(monkeypatch):
    """40 bps d'edge, 12 bps de frais, 13 bps de degradation -> 15 bps nets. Plancher a 20 -> NON."""
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    t = _table_avec_edge("FUNDING", "BTC", 40.0)

    d = decider(_ctx(frais_bps=12.0, degradation_copie_bps=13.0, plancher_edge_net_bps=20.0),
                table=t)
    assert d.verdict == NO_TRADE
    assert d.raison == REFUS_EDGE_NET_INSUFFISANT
    assert d.couts_bps == pytest.approx(25.0, abs=0.1)
    assert d.edge_net_bps == pytest.approx(15.0, abs=1.0)

    # Meme edge, plancher a 10 -> OUI.
    d2 = decider(_ctx(frais_bps=12.0, degradation_copie_bps=13.0, plancher_edge_net_bps=10.0),
                 table=t)
    assert d2.verdict == ENTREE
    assert d2.autorise


def test_le_SLIPPAGE_reel_entre_dans_les_couts(monkeypatch):
    """Le slippage vient du carnet TRAVERSE, pas d'une constante."""
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    t = _table_avec_edge("FUNDING", "BTC", 100.0)
    # 500 $ : 100 $ a 10.0 puis 400 $ a 10.5 -> slippage REEL, non nul
    d = decider(_ctx(niveaux_achat=[(10.0, 10.0), (10.5, 1_000.0)], frais_bps=0.0), table=t)
    assert d.slippage_bps is not None and d.slippage_bps > 0.0
    assert d.couts_bps == pytest.approx(d.slippage_bps, abs=1e-6)


def test_un_notional_invalide_REFUSE_avant_tout():
    assert decider(_ctx(notional_usd=0.0)).raison == REFUS_NOTIONAL_INVALIDE
    assert decider(_ctx(notional_usd=-1.0)).raison == REFUS_NOTIONAL_INVALIDE


def test_le_noyau_ne_pretend_JAMAIS_a_une_execution_reelle(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    d = decider(_ctx(), table=_table_avec_edge("FUNDING", "BTC", 40.0))
    assert d.paper_only is True
    assert d.as_dict()["real_execution"] is False


def test_les_familles_couvrent_les_4_moteurs_de_G2():
    """Grinder + Sniper + Arbitrage + CopyWallet -- G2 demandait de les FUSIONNER."""
    assert famille_de_la_strategie("GRINDER") == DISCRETIONNAIRE_PUBLIC
    assert famille_de_la_strategie("SNIPER") == DISCRETIONNAIRE_PUBLIC
    assert famille_de_la_strategie("COPY") == DISCRETIONNAIRE_PUBLIC
    assert famille_de_la_strategie("ARBITRAGE") == FLUX_FORCE
    assert famille_de_la_strategie("FUNDING") == CARRY_STRUCTUREL
    # Consequence DURE, et il faut la dire : TROIS des quatre moteurs de G2 sont dans la MEME
    # zone morte. Les « fusionner » ne les ressuscite pas -- ca rend juste leur mort visible
    # depuis un seul endroit, au lieu de trois.


# ====================================================== 3. L'INVARIANT : PERSONNE NE CONTOURNE


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
    """Une exception doit etre VISIBLE, AU BON ENDROIT, et JUSTIFIEE.

    Pas de liste centrale d'exemptions : une liste s'eloigne du code et finit par mentir. Le
    marqueur `# EDGE_NON_FABRIQUE: <raison>` vit sur les lignes qui PRECEDENT immediatement
    l'affectation, et il doit porter une vraie raison (>= 60 caracteres). Un marqueur nu serait
    un blanc-seing ; c'est exactement ce qu'on refuse.
    """
    debut = max(0, lineno - 9)
    fenetre = lignes[debut : max(0, lineno - 1)]
    for ligne in fenetre:
        if _MARQUEUR in ligne:
            raison = ligne.split(_MARQUEUR, 1)[1].strip()
            # la raison peut se poursuivre sur les lignes de commentaire suivantes
            suite = "".join(
                l.strip().lstrip("#").strip()
                for l in fenetre[fenetre.index(ligne) + 1 :]
                if l.strip().startswith("#")
            )
            return len(raison + suite) >= 60
    return False


def _est_une_formule_inventee(valeur: ast.AST) -> bool:
    """Une arithmetique qui melange des CONSTANTES MAGIQUES et des VARIABLES.

    `24.0 + score * 24.0 + copyability * 18.0`  -> OUI (2+ constantes, des variables)
    `float(x) if mesure else 0.0`               -> non (aucune arithmetique)
    `edge_bps - couts_bps`                      -> non (aucune constante magique)
    `x * 10_000.0`                              -> non (une seule constante : une CONVERSION)
    """
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
    """🔴 L'INVARIANT. Il DECOUVRE par AST -- il ne fait confiance a AUCUNE liste.

    Une liste ecrite a la main expire le jour ou quelqu'un ajoute une formule, et personne ne se
    plaint. C'est exactement ce qui est arrive : `wallet_mirror_runtime:144` a vecu des mois --
    et la 4e formule (`ui/routes.py`) a survecu a Q1, qui pretendait pourtant les avoir toutes
    remplacees. C'est CE TEST qui l'a trouvee.

    Pourquoi l'AST et pas une regex : une regex lit aussi les docstrings et les commentaires. La
    premiere version de ce test s'accusait elle-meme (elle CITAIT une formule fabriquee en
    exemple). Un garde-fou qui crie au loup finit ignore ; un faux positif coute aussi cher qu'un
    faux negatif.
    """
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
        + "\n\nUn edge d'entree se MESURE (hl_observer.edge.edge_source). Il ne s'invente pas "
          "avec des constantes. QUATRE formules comme celles-ci ont deja vecu des mois ici."
    )


def test_l_invariant_ATTRAPE_vraiment_une_formule_fabriquee():
    """Un garde-fou qui ne peut pas echouer ne garde rien. On lui donne la VRAIE formule.

    Celle-ci a vecu des mois dans `ui/routes.py`, et Q1 -- qui pretendait avoir remplace tous les
    edges fabriques -- ne l'avait pas vue.
    """
    vraie = ast.parse(
        "leader_expected_edge_bps = 18.0 + confidence * 34.0 + min(24.0, (n - 1) * 8.0)"
    ).body[0]
    assert isinstance(vraie, ast.Assign)
    assert _est_une_formule_inventee(vraie.value), "l'invariant ne verrait PAS la vraie formule"

    # ... et il ne doit PAS accuser le code honnete.
    honnete = ast.parse("edge_net_bps = edge_brut_bps - couts_bps").body[0]
    assert isinstance(honnete, ast.Assign)
    assert not _est_une_formule_inventee(honnete.value), "faux positif sur une soustraction de couts"

    mesure = ast.parse(
        "leader_expected_edge_bps = float(e.valeur_bps) if e.utilisable else 0.0"
    ).body[0]
    assert isinstance(mesure, ast.Assign)
    assert not _est_une_formule_inventee(mesure.value), "faux positif sur l'edge MESURE"


def test_le_MARQUEUR_d_exemption_n_est_PAS_un_blanc_seing():
    """Un marqueur nu ne doit RIEN exempter. Sinon l'invariant se contourne en une seconde."""
    nu = ["# EDGE_NON_FABRIQUE:", "edge_bps = 1.0 + x * 2.0"]
    assert not _exemption_justifiee(nu, 2), "un marqueur SANS raison exempte -- blanc-seing"

    trois_mots = ["# EDGE_NON_FABRIQUE: c'est bon", "edge_bps = 1.0 + x * 2.0"]
    assert not _exemption_justifiee(trois_mots, 2), "trois mots ne sont pas une justification"

    vrai = [
        "# EDGE_NON_FABRIQUE: c'est un SEUIL de politique de risque, pas une valeur d'edge : on",
        "# ne predit rien, on exige une barre plus haute apres des pertes.",
        "edge_bps = min_edge + 10.0",
    ]
    assert _exemption_justifiee(vrai, 3), "une exemption VRAIMENT justifiee doit passer"


def test_le_noyau_importe_BIEN_les_trois_verrous():
    """Q1 (edge mesure) + Q2 (jambes executables) + Q3 (taxonomie). Si un import disparait,
    le noyau redevient un juge qui note un chiffre sans savoir d'ou il vient."""
    src = (SRC / "decision_engine" / "noyau_unique.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    importes = {
        n.module for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.module
    }
    assert "hl_observer.edge.edge_source" in importes, "Q1 (edge MESURE) n'est pas branche"
    assert "hl_observer.arbitrage.executable_legs" in importes, "Q2 (prix EXECUTABLES) absent"
    assert "hl_observer.signals.signal_taxonomy" in importes, "Q3 (zones mortes) absent"
