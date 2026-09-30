"""Q1 -- LA PORTE DE L'EDGE BRUT EST BRANCHEE, ET ELLE NE MENT JAMAIS.

Deux formules inventees produisaient l'edge brut de toute la chaine :

    fresh_opportunity.py:342      14 + score*0,55 + wallets*9 + notional/25000 + tightness*10
    wallet_mirror_runtime.py:144  24 + score*24 + copyability*18

Ces tests prouvent trois choses, et refusent les trois mensonges correspondants :

  1. le DEFAUT est la table MESUREE (pas la formule) ;
  2. sans donnee -> `None` -> NO_TRADE (jamais une valeur de secours) ;
  3. si quelqu'un rallume la formule, la decision est ESTAMPILLEE `fabrique=True`.

Aucun ordre reel.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.edge.edge_source import (
    EDGE_FABRIQUE_FORMULE,
    EDGE_SOURCE_INCONNUE,
    SOURCE_FORMULE,
    SOURCE_TABLE,
    edge_brut,
    source_configuree,
    vider_le_cache,
)
from hl_observer.edge.measured_edge_table import (
    EDGE_BUCKET_VIDE,
    EDGE_TABLE_ABSENTE,
    EDGE_TABLE_LOOKAHEAD,
    Features,
    Observation,
    construire,
)


@pytest.fixture(autouse=True)
def _cache_propre():
    vider_le_cache()
    yield
    vider_le_cache()


def _table(markout: float = 25.0, n: int = 60, ms: float = 1_000.0):
    obs = [
        Observation(
            features=Features(strategie="COPY", coin="BTC", direction="LONG",
                              signal_age_ms=500.0, leader_score=70.0, consensus_wallets=2.0),
            markout_bps=markout + (0.5 if i % 2 else -0.5),
            signal_ms=ms,
        )
        for i in range(n)
    ]
    return construire(obs, horizon_ms=60_000, min_echantillons=30)


def _appel(**kw):
    base = dict(coin="BTC", direction="LONG", signal_age_ms=500.0, leader_score=70.0,
                consensus_wallets=2.0, signal_ms=9_999_999.0, strategie="COPY")
    base.update(kw)
    return edge_brut(**base)  # type: ignore[arg-type]


# ====================================================== 1. LE DEFAUT


def test_le_DEFAUT_est_la_table_mesuree_PAS_la_formule(monkeypatch):
    """Si le defaut etait `formule`, tout ce travail ne servirait a rien : le bot continuerait
    a trader sur onze constantes inventees, et personne ne s'en apercevrait."""
    monkeypatch.delenv("HYPERSMART_EDGE_SOURCE", raising=False)
    assert source_configuree() == SOURCE_TABLE


def test_une_source_INCONNUE_refuse_au_lieu_de_retomber_sur_la_formule(monkeypatch):
    """Deny-by-default. Une faute de frappe dans le lanceur ne doit pas rallumer le mensonge."""
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", "formule_ou_table_jsp")
    r = _appel(table=_table(), formule_de_secours=lambda: 999.0)
    assert r.valeur_bps is None
    assert r.raison == EDGE_SOURCE_INCONNUE
    assert not r.utilisable


# ====================================================== 2. PAS DE DONNEE -> PAS DE TRADE


def test_sans_TABLE_on_REFUSE_et_on_n_appelle_MEME_PAS_la_formule(monkeypatch, tmp_path):
    """LE test central. Le mode `table` ne doit JAMAIS retomber en douce sur la formule.
    Si la table manque, la reponse est `None` -- et l'appelant refuse."""
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    appelee = {"oui": False}

    def _formule():
        appelee["oui"] = True
        return 999.0

    r = _appel(racine=tmp_path, formule_de_secours=_formule)   # aucune table sur le disque
    assert r.valeur_bps is None
    assert r.raison == EDGE_TABLE_ABSENTE
    assert appelee["oui"] is False, "la formule a ete appelee en mode table : repli SILENCIEUX"


def test_un_bucket_VIDE_refuse_sans_valeur_de_secours(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    r = _appel(coin="DOGE", strategie="ARBITRAGE", table=_table(),
               formule_de_secours=lambda: 999.0)
    assert r.valeur_bps is None
    assert r.raison == EDGE_BUCKET_VIDE


def test_le_LOOKAHEAD_est_refuse_meme_quand_la_cellule_existe(monkeypatch):
    """La table a ete construite sur des signaux jusqu'a T=1 000 000. Un signal ANTERIEUR a ete
    vu par elle : lui demander son edge, c'est lui demander son propre futur."""
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    t = _table(ms=1_000_000.0)
    assert _appel(table=t, signal_ms=999_999.0).raison == EDGE_TABLE_LOOKAHEAD
    assert _appel(table=t, signal_ms=1_000_001.0).utilisable


# ====================================================== 3. LA FORMULE, SI ON LA RALLUME


def test_le_mode_formule_MARCHE_mais_ESTAMPILLE_la_decision(monkeypatch):
    """On peut mentir a la machine. On ne se ment plus a soi-meme.

    Le chiffre est utilisable (le bot tradera), mais `fabrique=True` et la raison
    EDGE_FABRIQUE_FORMULE remontent dans le resultat, le journal, le dashboard et l'audit.
    """
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_FORMULE)
    r = _appel(formule_de_secours=lambda: 42.0)
    assert r.valeur_bps == pytest.approx(42.0)
    assert r.utilisable
    assert r.fabrique is True
    assert r.raison == EDGE_FABRIQUE_FORMULE
    assert r.as_dict()["fabrique"] is True


def test_un_edge_MESURE_n_est_JAMAIS_marque_fabrique(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    r = _appel(table=_table())
    assert r.utilisable
    assert r.fabrique is False
    assert r.detail["niveau"] == "fin"
    assert r.detail["n"] == 60


# ====================================================== LE CHARGEMENT DEPUIS LE DISQUE


def test_la_table_est_lue_depuis_le_disque_a_l_emplacement_attendu(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    p = tmp_path / "data" / "reports" / "table_edge_mesuree.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_table().vers_json(), encoding="utf-8")

    r = _appel(racine=tmp_path)
    assert r.utilisable
    assert r.fabrique is False


def test_une_table_CORROMPUE_refuse_au_lieu_de_deviner(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", SOURCE_TABLE)
    p = tmp_path / "data" / "reports" / "table_edge_mesuree.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ ceci n'est pas du json", encoding="utf-8")
    r = _appel(racine=tmp_path, formule_de_secours=lambda: 999.0)
    assert r.valeur_bps is None
    assert r.raison == EDGE_TABLE_ABSENTE


def test_la_table_LIVREE_n_est_JAMAIS_celle_de_l_entrainement():
    """🚩 MON PREMIER TEST ETAIT FAUX, ET IL M'A APPRIS QUELQUE CHOSE.

    J'avais ecrit : « la table ne doit contenir aucune cellule a edge positif ». Il a ECHOUE :
    la table d'ENTRAINEMENT en contient 3 (dont BTC, signal < 1 s, score eleve : n=56,
    moyenne +23,1 bps). Mon test etait mal cible -- mais ces 3 buckets sont DANGEREUX.

    Car la validation hors-echantillon disait deja la verite : sur les signaux de TEST que ces
    buckets auraient acceptes, le prix fait **-2,69 bps**. Ce sont des ALPHAS FANTOMES.

    Un bucket qui trouve de l'edge sur ses PROPRES donnees ne prouve rien : c'est la definition
    du sur-ajustement. La seule question honnete : « tient-il sur des donnees jamais vues ? »

    Le pipeline livre donc `table_edge_mesuree.json` = les cellules CONFIRMEES sur le test,
    avec les statistiques DU TEST. La table d'entrainement est conservee a part
    (`table_edge_entrainement.json`) pour l'audit, et le moteur ne la lit JAMAIS.
    """
    from pathlib import Path

    base = Path(__file__).resolve().parents[1] / "data" / "reports"
    livree = base / "table_edge_mesuree.json"
    train = base / "table_edge_entrainement.json"
    if not livree.is_file() or not train.is_file():
        pytest.skip("tables non construites (tools/construire_table_edge.py)")

    d_liv = json.loads(livree.read_text(encoding="utf-8"))
    d_tr = json.loads(train.read_text(encoding="utf-8"))

    cles_livrees = {c["cle"] for c in (d_liv.get("cellules") or [])}
    cles_train = {c["cle"] for c in (d_tr.get("cellules") or [])}

    # La livree est un SOUS-ENSEMBLE STRICT du train : on ne peut que perdre des cellules a la
    # validation, jamais en gagner. Si ce n'est pas le cas, la purge est cassee.
    assert cles_livrees <= cles_train, (
        "la table livree contient des cellules ABSENTES de l'entrainement : la purge est cassee"
    )

    # Et les statistiques doivent VENIR DU TEST, donc differer de celles du train.
    par_cle_tr = {c["cle"]: c for c in (d_tr.get("cellules") or [])}
    identiques = [
        c["cle"] for c in (d_liv.get("cellules") or [])
        if c["cle"] in par_cle_tr and c["n"] == par_cle_tr[c["cle"]]["n"]
        and abs(float(c["moyenne_bps"]) - float(par_cle_tr[c["cle"]]["moyenne_bps"])) < 1e-9
    ]
    assert not identiques, (
        "%d cellule(s) livree(s) portent les statistiques D'ENTRAINEMENT. On livrerait une "
        "esperance mesuree sur les donnees qui l'ont fabriquee : %r"
        % (len(identiques), identiques[:5])
    )


def test_la_table_LIVREE_n_autorise_AUCUN_trade_a_edge_net_positif():
    """LE RESULTAT HONNETE, fige dans un test.

    Sur 22 472 markouts REELS, aucun bucket ne survit au hors-echantillon avec un edge net
    positif. Branchee, la table REFUSE le copy-trading. Ce n'est pas une panne : c'est la 3e
    confirmation independante de la preuve du 11/07.

    Si un jour ce test ECHOUE, ce n'est PAS une regression -- c'est qu'un bucket a enfin un edge
    net positif CONFIRME hors echantillon. Il faudra alors le valider encore (bootstrap, autre
    periode, autre horizon) avant de s'en rejouir. Mais ce sera une nouvelle, pas un bug.
    """
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / "data" / "reports" / "table_edge_mesuree.json"
    if not p.is_file():
        pytest.skip("table non construite (tools/construire_table_edge.py)")

    d = json.loads(p.read_text(encoding="utf-8"))
    cout_aller_retour_bps = 12.0
    positives = [
        c for c in (d.get("cellules") or [])
        if float(c["borne_basse_bps"]) - cout_aller_retour_bps > 0.0
        and int(c["n"]) >= int(d["min_echantillons"])
    ]
    assert not positives, (
        "%d bucket(s) a edge NET positif CONFIRME hors echantillon. Ce n'est pas une panne -- "
        "c'est une piste. A re-valider (bootstrap, autre periode) avant d'y croire : %r"
        % (len(positives), [c["cle"] for c in positives[:5]])
    )
