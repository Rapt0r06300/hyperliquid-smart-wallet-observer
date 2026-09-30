r"""LES 10 MANQUES DU MOISSONNEUR — *un test par idée. Aucun module sans test.*

Flo : *« il manque quoi au moissonneur ? donne-moi 10 idées »* -> puis *« implémente tout »*.

Aucun ordre reel. Aucun reseau.
"""
from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

import pytest

from hl_observer.research.jugement_plus import (
    CIMETIERE,
    appliquer_retours,
    charger_retours,
    dedupliquer_idees,
    deja_mort,
    enregistrer_retour,
    lier_repo_et_papier,
    prioriser,
)
from hl_observer.research.lecture_profonde import (
    est_recent,
    extraits_du_corps,
    filtre_date_github,
    linter_md,
    lire_derniere_date,
    ecrire_derniere_date,
    texte_du_html,
    url_papier_plein_texte,
)
from hl_observer.research.semantique import (
    diagnostic,
    merite_un_second_regard,
    plus_proche,
)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #1 — LA SÉMANTIQUE. *Repêche ce que le grep rate. Contre LE faux négatif.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_1_la_semantique_repeche_une_PARAPHRASE_que_le_grep_raterait() -> None:
    """🔑 ***« the chance our resting order gets executed » == probabilité de fill*** — sans un
    seul de nos mots-clés. Le grep le rate ; la sémantique doit le repêcher.
    """
    para = ("We estimate the chance that our resting passive order will actually get executed "
            "depending on how far it sits from the middle of the book.")
    # le grep n'y verrait rien (pas de « fill probability », pas de « queue »)
    repeche, sem = merite_un_second_regard(para, deja_vu_par_grep=False)
    assert repeche, "🔴 la paraphrase n'est PAS repêchée -> c'est le faux négatif qu'on voulait tuer"
    assert sem.concept in ("fill_probability", "queue_double_count", "adverse_selection")


def test_IDEE_1_si_le_grep_a_DEJA_pris_on_ne_repeche_pas() -> None:
    """*Inutile de repêcher ce que le grep tient déjà.*"""
    repeche, _ = merite_un_second_regard("lambda = A exp(-kappa delta) queue position",
                                         deja_vu_par_grep=True)
    assert repeche is False


def test_IDEE_1_un_texte_HORS_SUJET_ne_ressemble_a_RIEN() -> None:
    _, sem = merite_un_second_regard("How to bake sourdough bread with a good crust.",
                                     deja_vu_par_grep=False)
    assert sem.score < 0.14, "du pain ne doit ressembler a aucun de nos trous"


def test_IDEE_1_on_DIT_quelle_methode_est_active_jamais_de_faux_semblant() -> None:
    """🚩 *On ne fait pas semblant d'avoir un modele neuronal si on ne l'a pas.*"""
    d = diagnostic()
    assert d["methode_active"] in ("lexical", "neuronal (sentence-transformers)")
    if d["methode_active"] == "lexical":
        assert "PAS les reformulations totales" in d["franchise"]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #3 — NOS MORTS. *Ne jamais faire relire ce qu'on a mesuré MORT.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_3_un_beau_papier_de_MARKET_MAKING_recoit_son_certificat_de_deces() -> None:
    """🔑 *S'il trouve un beau papier de MM, il doit afficher : T1b 0/29, HLP -0,01 %.*"""
    m = deja_mort("An optimal market making strategy using Avellaneda-Stoikov inventory skew.")
    assert m, "🔴 le MM n'a PAS declenche notre cimetiere -> on relira une idee deja morte"
    assert "0/29" in m[0].verdict


def test_IDEE_3_le_copy_trading_est_reconnu_mort() -> None:
    m = deja_mort("A smart money copy trading bot that mirrors whale wallets.")
    assert m and "7,97" in m[0].verdict


def test_IDEE_3_une_idee_NEUVE_ne_declenche_AUCUN_certificat() -> None:
    """*Le cimetiere ne doit pas condamner ce qu'on n'a jamais mesure.*"""
    assert deja_mort("A liquidation cascade detector from public margin data.") == []


def test_IDEE_3_chaque_mort_porte_le_CHIFFRE_qui_l_a_tuee() -> None:
    for mort in CIMETIERE:
        assert any(ch in mort.verdict for ch in ("0/", "bps", "%", "ratio")), (
            "une mort sans chiffre est une opinion : %s" % mort.idee)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #4 — DÉDUP ENTRE SOURCES. *Le même papier sur 4 sources = UNE idée.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_4_le_MEME_papier_sur_4_sources_devient_UNE_entree() -> None:
    """🔑 arXiv + OpenAlex + S2 + PwC du meme travail -> 1, pas 4."""
    titre = "Optimal Market Making under Inventory Risk"
    items = [
        {"titre": titre, "lien": "https://arxiv.org/abs/2401.01234", "source": "arxiv",
         "score": 40},
        {"titre": titre, "lien": "https://openalex.org/W99", "source": "openalex", "score": 55},
        {"titre": "optimal market making under inventory risk", "lien": "x", "source": "s2",
         "score": 30},
        {"titre": "A totally different paper", "lien": "y", "source": "arxiv", "score": 20},
    ]
    fus = dedupliquer_idees(items)
    assert len(fus) == 2, "3 doublons du meme titre doivent fusionner en 1"
    gros = fus[0]
    assert gros.doublons == 2
    assert set(gros.sources) >= {"arxiv", "openalex"}
    assert gros.representant["score"] == 55, "on garde le mieux-score comme representant"


def test_IDEE_4_le_DOI_identifie_le_meme_papier_malgre_un_titre_different() -> None:
    items = [
        {"titre": "Paper A", "lien": "https://doi.org/10.1000/xyz", "source": "crossref"},
        {"titre": "Paper A (preprint)", "lien": "doi:10.1000/xyz", "source": "arxiv"},
    ]
    assert len(dedupliquer_idees(items)) == 1


def test_IDEE_4_lier_un_repo_a_son_papier_la_theorie_ET_le_code() -> None:
    liens = lier_repo_et_papier(
        ["nkaz001/hftbacktest"],
        [{"titre": "hftbacktest: high frequency backtesting", "lien": "u"}],
    )
    assert liens and liens[0]["repo"] == "nkaz001/hftbacktest"


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #7 — LE MÉTA-CLASSEMENT. *« Si tu ne fais qu'UNE chose… »*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_7_le_meta_classement_croise_GRAVITE_x_etayage_x_facilite() -> None:
    """*Le score classe par nouveaute ; le meta-classement dit quoi faire EN PREMIER.*"""
    idees = [
        {"cle": "kappa_fill", "sources": [1, 2, 3]},      # grave + bien etaye
        {"cle": "inventaire", "sources": [1, 2, 3, 4]},   # MM mort -> doit finir en BAS
        {"cle": "execution", "sources": [1]},
    ]
    pr = prioriser(idees)
    assert pr[0].cle != "inventaire", "le MM mort ne doit JAMAIS etre priorite n.1"
    assert pr[-1].cle == "inventaire"
    assert "NE PAS FAIRE" in pr[-1].pourquoi


def test_IDEE_7_une_idee_grave_bat_une_idee_anecdotique_a_etayage_egal() -> None:
    pr = {p.cle: p.priorite for p in prioriser(
        [{"cle": "lookahead", "sources": [1]}, {"cle": "execution", "sources": [1]}])}
    assert pr["lookahead"] > pr["execution"], "notre coupe train/test FUYAIT (68 %) -> grave"


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #10 — LE RETOUR. *Un canari qui APPREND.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_10_un_retour_UTILE_augmente_le_poids_du_concept() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "retours.json"
        enregistrer_retour(p, "kappa_fill", "utile")
        r = charger_retours(p)
        assert r.get("kappa_fill", 0) > 0
        assert appliquer_retours(10.0, "kappa_fill", r) > 10.0


def test_IDEE_10_un_retour_du_VENT_diminue_le_poids() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "retours.json"
        enregistrer_retour(p, "un_truc", "vent")
        r = charger_retours(p)
        assert appliquer_retours(10.0, "un_truc", r) < 10.0


def test_IDEE_10_pas_de_retours_ne_change_RIEN() -> None:
    assert appliquer_retours(10.0, "x", {}) == 10.0


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #2 — LIRE LE PAPIER, pas le resume.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_2_on_sait_construire_l_URL_du_CORPS_d_un_papier_arxiv() -> None:
    u = url_papier_plein_texte("https://arxiv.org/abs/2401.01234")
    assert u == "https://arxiv.org/html/2401.01234"
    assert url_papier_plein_texte("https://example.com/blog") is None


def test_IDEE_2_on_extrait_le_TEXTE_du_html_sans_les_balises() -> None:
    html = "<html><body><p>market <b>impact</b></p><script>evil()</script></body></html>"
    t = texte_du_html(html)
    assert "market impact" in t
    assert "evil" not in t, "le script doit etre vire -- et JAMAIS execute"


def test_IDEE_2_on_extrait_les_LIMITES_et_RESULTATS_du_corps() -> None:
    """*Le resume est la page de vente ; le corps a l'aveu et le tableau de resultats.*"""
    corps = ("Introduction blah blah. Limitations: we assume zero latency and ignore "
             "transaction costs. Results: table 1 shows the strategy fails out of sample.")
    ex = extraits_du_corps(corps)
    j = " ".join(ex).lower()
    assert "limitation" in j or "assume" in j
    assert "out of sample" in j or "fails" in j


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #6 — LE MODE INCRÉMENTAL.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_6_on_ne_re_scanne_que_le_NOUVEAU() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "date.txt"
        assert lire_derniere_date(p) is None          # 1er run -> tout
        ecrire_derniere_date(p, date(2026, 7, 1))
        assert lire_derniere_date(p) == date(2026, 7, 1)
        assert "created:>=2026-07-01" in filtre_date_github(date(2026, 7, 1))


def test_IDEE_6_le_premier_run_prend_TOUT_pas_de_filtre() -> None:
    assert filtre_date_github(None) == ""
    assert est_recent("2020-01-01", None) is True      # depuis=None -> tout passe


def test_IDEE_6_une_date_illisible_ne_JETTE_pas() -> None:
    """*Dans le doute, on garde -- ne pas savoir n'est pas une raison de jeter.*"""
    assert est_recent("date pourrie", date(2026, 1, 1)) is True


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #8 — LINTER LE .md PRODUIT.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

_MD_BON = ("# Titre\n" + "x" * 500 + "\ndéjà accepté ... MESURÉE CHEZ NOUS ... "
           "Bilan de couverture\n[lien](https://ok)\n")


def test_IDEE_8_un_md_BIEN_FORME_passe() -> None:
    assert linter_md(_MD_BON).ok


def test_IDEE_8_un_LIEN_CASSE_est_attrape() -> None:
    """🔴 `](None)` = un chiffre qu'on ne peut pas suivre."""
    bad = _MD_BON + "\nvoir [ça](None)\n"
    lint = linter_md(bad)
    assert not lint.ok
    assert any("cassé" in p for p in lint.problemes)


def test_IDEE_8_une_SECTION_OBLIGATOIRE_manquante_est_attrapee() -> None:
    """*Un livrable sans le bloc de pre-approbation est un livrable casse.*"""
    sans = "# Titre\n" + "x" * 500 + "\npas de sections importantes ici\n"
    lint = linter_md(sans)
    assert not lint.ok
    assert any("absente" in p for p in lint.problemes)


def test_IDEE_8_un_PLACEHOLDER_oublie_est_attrape() -> None:
    bad = _MD_BON + "\nTODO finir ça\n"
    assert not linter_md(bad).ok


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #9 — LE QUANT NON ANGLOPHONE.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_9_le_quant_chinois_est_couvert() -> None:
    """🌏 *vn.py, qlib, akshare -- un angle mort dont on n'avait pas conscience.*"""
    from hl_observer.research.domaines import DOMAINES

    d = next((x for x in DOMAINES if x.cle == "quant_non_anglophone"), None)
    assert d is not None, "🔴 le quant non anglophone n'est PAS couvert"
    joint = " ".join(d.requetes).lower()
    assert "vnpy" in joint and "qlib" in joint
    assert any("量化" in q or "高频" in q for q in d.requetes), "les motifs chinois doivent etre la"
