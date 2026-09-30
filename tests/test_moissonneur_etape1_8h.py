r"""ETAPE 1 = 8 h DE RECHERCHE  (decision de Flo, 2026-07-15).

*« il faut que pendant 8 heures il cherche des repos et autres, ensuite l'etape 2 ; il ne doit
jamais arreter de chercher et toujours savoir quoi chercher, en restant coherent. »*

On verifie, SANS un seul appel reseau, que :
  1. le budget de temps donne bien ~8 h a l'etape 1 (le scan) sur un run de 12 h ;
  2. la RE-ALIMENTATION reste DANS NOTRE DOMAINE (topics coherents seulement, pas 'python') ;
  3. la re-alimentation ne repete pas une requete deja faite ;
  4. le scan sait PAGINER et se RE-ALIMENTER (il ne s'arrete pas quand la liste s'epuise) ;
  5. le tableau de bord montre les 'Xh / 8h de recherche'.

Aucun ordre reel. Aucun reseau.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "tools" / "moissonner_10h.py"


def _worker():
    """Importe le worker comme module (aucun reseau : le top-level ne fait que definir)."""
    spec = importlib.util.spec_from_file_location("moissonner_10h_e1", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_etape1_dure_environ_8h_sur_un_run_de_12h() -> None:
    mod = _worker()
    dl_a, dl_b, dl_c = mod.budgets_de_phase(12 * 3600.0)
    scan = 12 * 3600.0 - dl_a
    assert 7.5 * 3600.0 <= scan <= 8.5 * 3600.0, \
        "l'etape 1 doit durer ~8 h, mesure : %.2f h" % (scan / 3600.0)
    assert dl_a > dl_b > dl_c > 0.0


def test_budget_reste_sain_sur_un_run_court() -> None:
    mod = _worker()
    dl_a, dl_b, dl_c = mod.budgets_de_phase(0.1 * 3600.0)   # un run de test de 6 min
    assert dl_a > dl_b > dl_c > 0.0
    assert dl_a < 0.1 * 3600.0, "il doit rester du temps pour les etapes 2-4"


def test_re_alimentation_reste_coherente() -> None:
    mod = _worker()
    repos = {
        "a/coherent": {"topics": ["market-making", "hft", "orderbook", "defi"]},
        "b/bruit": {"topics": ["python", "docker", "hacktoberfest"]},
    }
    boites = mod.requetes_de_relance(repos, set())
    qs = " ".join(q for (_g, q, _p, _t) in boites)
    assert "market" in qs or "hft" in qs, \
        "les topics de NOTRE domaine doivent revenir : %r" % qs
    assert "docker" not in qs and "hacktoberfest" not in qs and "topic:python" not in qs, \
        "le bruit hors-domaine doit etre filtre : %r" % qs
    # forme exacte des boites : (genre, requete, pourquoi, tri)
    for genre, requete, _pourquoi, tri in boites:
        assert genre == "repo" and requete.startswith("topic:") and tri == "stars"


def test_re_alimentation_ne_repete_pas_le_deja_fait() -> None:
    mod = _worker()
    repos = {"a/c": {"topics": ["market-making"]}}
    faites = {"repo|topic:market-making|stars"}
    assert mod.requetes_de_relance(repos, faites) == []


def test_le_scan_sait_paginer_et_se_re_alimenter() -> None:
    src = SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert "&page=%d" in src, "le scan doit PAGINER (GitHub sert jusqu'a 10 pages)"
    assert "requetes_de_relance(" in src, "le scan doit se RE-ALIMENTER quand la liste s'epuise"
    assert "while _reste() > DL_A" in src, "l'etape 1 doit tourner PENDANT TOUT son budget de temps"
    assert "de recherche" in src, "le tableau de bord doit montrer 'Xh / 8h de recherche'"


# ─────────────────────────────────────────────────────────────────────────────────────────────
#  CHOIX B de Flo (2026-07-15) : « garder 8h mais LIRE PLUS MALIN ».
#  - lire les depots de NOTRE domaine d'abord (pas par etoiles) ;
#  - couper le repechage semantique du bruit ML hors-domaine ;
#  - resserrer la pagination sur les requetes generiques ;
#  - mode RELIRE pour rentabiliser un scan deja fait.
# ─────────────────────────────────────────────────────────────────────────────────────────────
def test_pertinence_domaine_lit_le_quant_avant_le_ml() -> None:
    mod = _worker()
    quant = {"nom": "x/perp-arb", "topics": ["funding-rate", "perpetuals", "arbitrage"],
             "pourquoi": "", "etoiles": 3}
    ml = {"nom": "google/tensorflow", "topics": ["machine-learning", "deep-learning", "python"],
          "pourquoi": "", "etoiles": 180000}
    assert mod.pertinence_domaine(quant) > mod.pertinence_domaine(ml)
    assert mod.pertinence_domaine(ml) == 0, "un repo ML fameux n'a aucun topic de NOTRE domaine"


def test_pertinence_domaine_valorise_la_requete_ciblee() -> None:
    mod = _worker()
    trouve_code = {"nom": "a/b", "topics": [], "pourquoi": "", "trouve_dans_le_code": "kappa"}
    banal = {"nom": "a/b", "topics": [], "pourquoi": ""}
    assert mod.pertinence_domaine(trouve_code) > mod.pertinence_domaine(banal)


def test_le_tri_lit_par_domaine_et_coupe_le_bruit_ml() -> None:
    src = SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert "pertinence_domaine(repos[n])" in src, "le tri doit lire par pertinence, pas par etoiles"
    assert "repeche and en_domaine" in src, "le repechage semantique doit etre coupe hors-domaine"
    assert "else 3" in src, "la pagination doit etre resserree (3 pages) sur les requetes generiques"


def test_mode_relire_existe_et_saute_le_scan() -> None:
    src = SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert '"--relire"' in src, "l'option --relire doit exister"
    assert "MODE RELIRE" in src, "le mode relire saute le scan et donne tout le temps a la lecture"


def test_aucune_variable_partagee_n_est_rebindee_par_plus_egal() -> None:
    """🔴 LE BUG DU 15/07 (rapport VIDE) : `constantes += ...` dans la fonction _ouvrir, alors que
    `constantes` vit dans main() -> Python la croit LOCALE -> UnboundLocalError au 1er fichier ->
    l'etape 3 (ouvrir le code) plante -> 0 depot retenu -> moisson-fini.md vide.

    Regle dure : ces listes/dicts PARTAGES se MUTENT (.append / .extend / [x]=), JAMAIS avec `+=`
    (qui rebinde et rend la variable locale). Ce test le garantit pour tout le worker.
    """
    import ast
    src = SCRIPT.read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    partagees = {"entrees", "codes", "constantes", "concepts_par_repo",
                 "notes", "qui_cite", "web_gardes"}
    fautes = [
        "ligne %d : `%s +=`" % (n.lineno, n.target.id)
        for n in ast.walk(arbre)
        if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name)
        and n.target.id in partagees
    ]
    assert not fautes, (
        "une variable partagee de main() est rebindee par += (UnboundLocalError garanti dans la "
        "fonction imbriquee, comme le bug 'constantes' du 15/07) : %s" % "; ".join(fautes))


def test_le_tri_est_local_cache_d_abord_et_borne() -> None:
    """Flo (15/07) : le tri doit etre LOCAL et rapide. Le vrai cout des 43h etait `sleep(0.8s)`
    x 180k = 40h de sommeil, MEME sur cache. Donc : cache disque d'abord (aucune attente), fetch
    BORNE (PLAFOND_FETCH), score local sur les metadonnees pour le reste (aucun oubli)."""
    src = SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert 'CACHE.lire("readme|%s" % nom)' in src, "le tri doit lire le cache AVANT tout reseau"
    assert "PLAFOND_FETCH" in src, "le nombre de telechargements doit etre borne"
    assert 'fetch_faits["n"] += 1' in src, "on ne compte (et ne dort) que sur un VRAI telechargement"
    assert "s_meta = float(pertinence_domaine(repos[nom]))" in src, "score LOCAL de repli (metadonnees)"
