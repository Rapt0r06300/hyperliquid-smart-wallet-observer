from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
CALIBRATION_FIXTURE = RACINE / "tests" / "fixtures" / "empirical_edge_TEST_FIXTURE.json"

# Prefixes de TOUTES les variables de calibrage du runtime. Un test ne doit JAMAIS en heriter.
PREFIXES_RUNTIME = ("HYPERSMART_", "HL_")
PORTABLE_CONTRACT = RACINE / "tests" / "test_extracted_portable_contract.py"


def _portable_extracted_collection_mode() -> bool:
    """Détecte la validation de l'archive réellement extraite, sans simple flag déclaratif.

    Le mode n'est vrai que si le runtime déclaré est exactement le checkout courant,
    que le workspace hermétique du validateur existe et que pytest tourne avec le
    ``python.exe`` embarqué dans cette même archive. Une variable d'environnement
    isolée dans une CI Linux normale ne peut donc pas réduire la couverture des tests.
    """

    raw_root = os.environ.get("HYPERSMART_RUNTIME_ROOT", "").strip()
    if not raw_root:
        return False
    try:
        runtime_root = Path(raw_root).resolve()
        executable = Path(sys.executable).resolve()
    except OSError:
        return False
    embedded_python = (runtime_root / "tools" / "python" / "python.exe").resolve()
    return bool(
        os.name == "nt"
        and runtime_root == RACINE.resolve()
        and executable == embedded_python
        and (runtime_root / "_validation_workspace").is_dir()
        and os.environ.get("PIP_NO_INDEX") == "1"
        and os.environ.get("PYTHONNOUSERSITE") == "1"
    )


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Dans l'archive extraite, collecte uniquement son contrat produit dédié.

    La suite de développement complète est déjà exécutée par la CI du dépôt. La
    relancer depuis le ZIP mélangeait des tests qui exigent un checkout Git, des
    mocks de développement et des fichiers volontairement non distribués. Ici on
    prouve le produit extrait : runtime embarqué, garde-fous paper-only, imports
    critiques et Git embarqué. Toute autre collecte reste inchangée hors de ce mode.
    """

    del config
    if not _portable_extracted_collection_mode():
        return None
    path = Path(str(collection_path)).resolve()
    tests_root = (RACINE / "tests").resolve()
    if path == tests_root or path == PORTABLE_CONTRACT.resolve():
        return False
    try:
        path.relative_to(tests_root)
    except ValueError:
        return None
    return True


@pytest.fixture(autouse=True)
def env_runtime_neutre(monkeypatch: pytest.MonkeyPatch) -> None:
    """UN TEST NE DOIT PAS CHANGER DE VERDICT SELON LA MACHINE QUI LE LANCE (2026-07-12).

    LE BUG QUE CETTE FIXTURE FERME
    ------------------------------
    `test_ui_simulation_default_profile_allows_bounded_multi_position_mode` attendait 6
    (le defaut ecrit dans `routes.py:730`) et recevait 3. Le 3 ne venait d'aucun code de
    production : `tools/audit_report.py` pose `os.environ["HYPERSMART_MAX_OPEN_POSITIONS"] = "3"`
    dans SON processus pour verifier qu'un plafond refuse -- puis lance pytest en sous-processus,
    qui HERITE de cet environnement (`_run_stream` : `env = dict(os.environ)`).

    Resultat : le test passait en `pytest` nu et echouait sous MEGATEST. Le meme code, deux
    verdicts. **Un test qui depend de l'environnement ne prouve rien** : il mesure la machine,
    pas le programme.

    CE QU'ELLE FAIT
    ---------------
    Chaque test demarre avec un environnement runtime VIERGE. Un test qui veut une valeur la
    pose lui-meme (`monkeypatch.setenv`) -- explicitement, sous ses yeux, dans son propre corps.

    Exception volontaire et bornée : le contrat de l'archive Windows réellement extraite doit
    au contraire vérifier les garde-fous injectés par le validateur hermétique. Ce mode est
    identifié physiquement par l'interpréteur embarqué, pas par un simple flag.

    C'est la meme regle que pour les logs et la table d'edge : le test parle du CODE, jamais de
    l'etat vivant de la production.
    """

    if _portable_extracted_collection_mode():
        return
    for cle in [k for k in os.environ if k.startswith(PREFIXES_RUNTIME)]:
        monkeypatch.delenv(cle, raising=False)


@pytest.fixture(autouse=True)
def isolate_test_logs_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env_runtime_neutre: None
) -> None:
    """Keep tests from appending diagnostics to the real runtime logs.

    Simulation endpoints export JSON/JSONL/Markdown diagnostics on each call.
    The project logs under ``logs/logs a envoyer`` are the user's real evidence
    bundle, so every pytest case gets a throwaway log directory unless it
    explicitly overrides ``settings.logs_dir`` itself.
    """

    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))


@pytest.fixture(autouse=True)
def isole_la_table_d_edge(monkeypatch: pytest.MonkeyPatch, env_runtime_neutre: None) -> None:
    """HYGIENE : les tests ne lisent plus la table d'edge du VRAI runtime.

    ATTENTION -- CE QUE CETTE FIXTURE NE FAIT PAS (2026-07-12)
    ---------------------------------------------------------
    Je l'ai d'abord ecrite en croyant qu'elle reparerait les 26 tests en echec. ELLE NE LES
    REPARE PAS, et je le laisse ecrit ici pour que personne ne reperde le temps que j'ai perdu.

    Le verrou qui refuse (`realtime_magic_score.py:160`) NE LIT PAS la table de calibration.
    Il teste un ATTRIBUT sur l'entree :

        if not bool(getattr(inputs, "edge_is_empirical", False)):   -> EDGE_NOT_EMPIRICAL_NO_TRADE

    Or `RealtimeMagicScoreInputs.edge_is_empirical` vaut `False` par defaut, et AUCUN appelant
    ne le calcule depuis la table. Changer le chemin de la table ne change donc rien : le verrou
    refuse quoi qu'il arrive. C'est un cablage mort, pas un reglage. (cf. le rapport du 12/07.)

    CE QU'ELLE FAIT QUAND MEME, ET POURQUOI ON LA GARDE
    --------------------------------------------------
    Un test qui lit `runtime/calibration/empirical_edge.json` depend de l'etat VIVANT de la
    production : il change de verdict quand le marche change. Ce n'est plus un test, c'est un
    thermometre. On l'isole donc vers une TEST_FIXTURE explicite.

    LA SEPARATION VOULUE
    --------------------
    - LA MECANIQUE (une position s'ouvre-t-elle ? le PnL est-il juste ?) -> table TEST_FIXTURE.
    - LE VERDICT ECONOMIQUE (l'edge mesure est-il positif ?) -> la VRAIE table, testee dans
      `tests/test_edge_reel_est_negatif.py`. Reponse mesuree : NON, a tous les horizons.

    Un test qui veut le comportement de production surcharge l'env lui-meme : on pose un
    DEFAUT, on n'impose rien.
    """

    monkeypatch.setenv("HYPERSMART_EDGE_CALIBRATION_PATH", str(CALIBRATION_FIXTURE))


# ============================================================ #594 : LA PORTE A CHANGE DE SERRURE
#
# Jusqu'au 13/07, le scoreur de copie lisait `edge.empirical_edge` -- une table indexee sur le
# SEUL age -- alors que le chemin LIVE mesurait deja l'edge par la porte Q1 (`edge.edge_source`,
# conditionnee sur coin x age x score x consensus, borne basse, anti-lookahead). DEUX sources de
# verite ; la plus pauvre gagnait. #594 a supprime la seconde.
#
# La consequence pour les TESTS : le decor qui laissait passer les signaux (la TEST_FIXTURE a
# 60 bps de `empirical_edge`) ne sert plus a rien. Il faut le poser sur la NOUVELLE porte -- sinon
# 26 tests de MECANIQUE (une position s'ouvre-t-elle ? le PnL est-il juste ? le ledger persiste-t-il ?)
# echouent pour une raison qui n'a rien a voir avec ce qu'ils testent.
#
# ⚠️ CE N'EST PAS UN AFFAIBLISSEMENT, ET LA NUANCE EST TOUT :
#   * la table posee ici est marquee `source=TEST_FIXTURE` -- impossible a confondre avec une mesure ;
#   * elle sert a tester la MECANIQUE, jamais le VERDICT ECONOMIQUE ;
#   * le verdict economique se teste contre la VRAIE table (tests/test_edge_reel_est_negatif.py),
#     et il dit NON : l'edge de copie est negatif a tous les horizons ;
#   * un test qui veut l'absence de mesure supprime simplement la variable d'environnement.


@pytest.fixture(scope="session")
def _table_edge_TEST_FIXTURE(tmp_path_factory) -> Path:
    """Une table Q1 LARGE, marquee TEST_FIXTURE, qui couvre toutes les bandes.

    75 bps : un edge INVENTE, volontairement large, dont le seul role est de laisser passer un
    signal pour que la MECANIQUE en aval soit testable (la position s'ouvre-t-elle ? le PnL est-il
    juste ? le ledger persiste-t-il ?). Ce n'est PAS une mesure, et le champ `source` le dit.

    ⚠️ POURQUOI 75 ET PLUS 60 -- ET CE N'EST PAS « REGLER JUSQU'A CE QUE CE SOIT VERT ».
    L'ancien decor valait 60 bps, mais le scoreur les MULTIPLIAIT ensuite par `consensus_factor`
    (jusqu'a x1,25) et par la fraicheur : un signal de decor arrivait donc a ~70 bps devant les
    gates. #594 a supprime ces multiplicateurs (ils double-comptaient la table). Sans compensation,
    le decor perdait ~10 bps de marge et des tests de MECANIQUE (ex. « un consensus a 3 wallets
    passe outre le cooldown d'un coin ») echouaient pour une raison qui n'a RIEN a voir avec ce
    qu'ils testent. On restitue la marge dans le decor, la ou elle est declaree fausse -- pas dans
    le moteur, ou elle serait un mensonge.
    """
    from hl_observer.edge.measured_edge_table import Features, Observation, construire

    # 6 marches (>= MIN_COINS_POUR_LARGE=5) -> les cellules LARGES `COPY|*|...` sont emises,
    # donc n'importe quel coin, meme jamais vu, tombe dans une cellule.
    coins = ("BTC", "ETH", "SOL", "HYPE", "DOGE", "PURR")
    ages = (500.0, 2_000.0, 5_000.0, 20_000.0, 60_000.0)        # une valeur par bande d'age
    scores = (10.0, 60.0, 70.0, 80.0, 95.0)                     # une valeur par bande de score
    consensus = (1.0, 2.0, 4.0, 9.0)                            # une valeur par bande de consensus

    obs = [
        Observation(
            features=Features(strategie="COPY", coin=c, direction="LONG",
                              signal_age_ms=a, leader_score=s, consensus_wallets=w),
            markout_bps=75.0 + (0.5 if i % 2 else -0.5),
            signal_ms=0.0,          # horodatees a l'origine -> aucun signal de test n'est "avant"
        )
        for c in coins for a in ages for s in scores for w in consensus for i in range(6)
    ]
    table = construire(obs, horizon_ms=30_000, min_echantillons=30, source="TEST_FIXTURE")
    p = tmp_path_factory.mktemp("edge_fixture") / "table_edge_TEST_FIXTURE.json"
    p.write_text(table.vers_json(), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def isole_la_porte_unique_de_l_edge(
    monkeypatch: pytest.MonkeyPatch,
    _table_edge_TEST_FIXTURE: Path,
    env_runtime_neutre: None,
) -> None:
    """Le decor de MECANIQUE, pose sur la porte unique (Q1). Un test qui veut l'ABSENCE de
    mesure fait simplement `monkeypatch.delenv("HYPERSMART_EDGE_TABLE_PATH")`."""
    from hl_observer.edge.edge_source import ENV_CHEMIN_TABLE, vider_le_cache

    monkeypatch.setenv(ENV_CHEMIN_TABLE, str(_table_edge_TEST_FIXTURE))
    vider_le_cache()
    yield
    vider_le_cache()
