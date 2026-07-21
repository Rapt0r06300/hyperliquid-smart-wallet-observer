r"""LES 15 IDEES DU MOISSONNEUR — *chaque test verrouille une idee.*

═══════════════════════════════════════════════════════════════════════════════════════════════
LA PLUS IMPORTANTE EST LA n°1 — ET ELLE CONDITIONNE LES 14 AUTRES
═══════════════════════════════════════════════════════════════════════════════════════════════

**LE CANARI.** Un trieur qu'on n'a jamais teste contre une **verite connue** est un trieur auquel
on fait confiance **sans raison**.

Ce projet a deja paye ca : le balayage de lookahead #563 (un grep pandas sur du code Python pur
-> **0 trouvaille**, et j'ai failli conclure « aucun lookahead »). La version qui a marche (#562)
etait celle qui **REFUSAIT de rendre un verdict** si elle ne retrouvait pas le bug **connu**.
**Ce garde-fou a paye des sa 2e execution.**

    ***Un outil de mesure qu'on ne calibre pas mesure ce qu'il veut.***

Aucun ordre reel. Aucun reseau.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hl_observer.research.canari import BONS, CREUX, MARGE_MIN, pourquoi_temoin, verifier
from hl_observer.research.differentiel import (
    NOS_CAPACITES,
    NotreEtat,
    indexer_notre_code,
    score_differentiel,
    zones_vierges,
)
from hl_observer.research.github_signals import analyser, score
from hl_observer.research.mine_de_code import (
    LES_NOTRES,
    extraire_constantes,
    fouiller_commits,
    fouiller_issues,
    peurs_de_l_auteur,
    reproductibilite,
)
from hl_observer.research.moteur import (
    Bandit,
    CacheBrut,
    autorite,
    autres_repos_de_l_auteur,
    citations_inverses,
    dedupliquer,
    empreintes,
    normaliser,
    requetes_chronologiques,
    requetes_de_contradiction,
    similarite,
)


def _notre_noteur(txt: str) -> float:
    return score(analyser(txt), etoiles=0)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #1 — LE CANARI. **Le test le plus important du moissonneur.**
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_1_LE_CANARI_notre_trieur_actuel_PASSE_l_epreuve_du_connu() -> None:
    """🔑 **LE TEST QUI AUTORISE TOUS LES AUTRES.**

    Si le trieur ne separe pas ce qu'on SAIT bon de ce qu'on SAIT creux, il n'a **rien** a dire
    sur ce qu'on ne connait pas.
    """
    r = verifier(_notre_noteur)
    assert r.fiable, (
        "🔴🔴🔴 **CANARI MORT.** %s\n"
        "Le trieur ne retrouve pas ce qu'on sait deja bon -> **aucun verdict n'est recevable.**"
        % r.raison
    )
    assert r.marge >= MARGE_MIN


def test_IDEE_1_un_trieur_CASSE_est_DETECTE_et_le_corpus_est_BLOQUE() -> None:
    """***Il ne dit pas « je n'ai rien trouve ». Il dit « JE NE SAIS PAS TROUVER ».***"""
    r = verifier(lambda _t: 1.0)               # un trieur qui note tout pareil
    assert r.fiable is False
    assert "NE SAIT PAS TROUVER" in r.rapport()
    assert "Aucun verdict" in r.rapport()


def test_IDEE_1_un_trieur_INVERSE_est_detecte_avec_les_inversions_NOMMEES() -> None:
    """*Un echec global ne dit pas QUOI reparer.*"""
    r = verifier(lambda t: -_notre_noteur(t))
    assert r.fiable is False
    assert r.inversions, "on doit NOMMER quel creux depasse quel bon"


def test_IDEE_1_le_jeu_temoin_est_JUSTIFIE_pas_arbitraire() -> None:
    p = pourquoi_temoin()
    assert len(p) == len(BONS) + len(CREUX)
    for x in p:
        assert len(x["pourquoi"]) > 20, "un temoin sans justification est un temoin arbitraire"


def test_IDEE_1_hftbacktest_est_dans_le_jeu_temoin_il_nous_a_donne_5_bugs() -> None:
    assert any("hftbacktest" in n for n, _, _ in BONS)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #2 — LES COMMITS. *La liste des erreurs que le metier a deja PAYEES.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_2_un_commit_qui_CORRIGE_notre_bug_est_repere() -> None:
    """🔑 `fix: double counting of fills` est **litteralement** le bug trouve chez hftbacktest."""
    c = fouiller_commits([
        ("abc1234", "fix: double counting of fills, chg -= cum_trade_qty"),
        ("def5678", "chore: bump version"),
        ("aaa1111", "fix wrong maker taker fee, they were inverted"),
        ("bbb2222", "fix lookahead: shift by one bar"),
        ("ccc3333", "revert: this was wrong, my bad"),
    ])
    cats = {x.categorie for x in c}
    assert "bug_de_fill" in cats
    assert "bug_de_frais" in cats
    assert "bug_de_lookahead" in cats
    assert "aveu_de_regression" in cats
    assert not any(x.sha == "def5678" for x in c), "un bump de version n'est pas une lecon"
    for x in c:
        assert x.pourquoi, "un commit repere sans POURQUOI est du bruit"


def test_IDEE_2_chaque_commit_dit_quel_trou_DE_NOUS_il_touche() -> None:
    c = fouiller_commits([("x", "fix funding rate: 8h vs 1h interval was wrong")])
    assert c and "38" in c[0].pourquoi, "le piege d'unite 8 h vs 1 h : notre faux 38 % APR"


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #4 — LES ISSUES. *Des aveux INVOLONTAIRES.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_4_une_issue_qui_dit_que_CA_NE_MARCHE_PAS_est_gardee() -> None:
    """***Le README vend. L'issue se plaint.*** Et l'aveu est notre signal le plus fort."""
    i = fouiller_issues([
        {"number": 12, "title": "Backtest results don't match live",
         "body": "Our live fills diverge from the backtest by 40%.", "state": "open"},
        {"number": 13, "title": "Add dark mode", "body": "please", "state": "open"},
        {"number": 14, "title": "Fill model too optimistic",
         "body": "You overestimate the fill rate on thin books.", "state": "closed"},
    ])
    nums = {x.numero for x in i}
    assert 12 in nums and 14 in nums
    assert 13 not in nums, "« add dark mode » n'apprend rien sur notre bot"
    assert all("INVOLONTAIRE" in x.as_dict()["pourquoi"] for x in i)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #5 — LES TESTS. *La carte des PEURS de l'auteur.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_5_les_tests_revelent_les_PEURS_de_l_auteur() -> None:
    """***Ses peurs valent mieux que ses promesses.***"""
    p = peurs_de_l_auteur([
        "tests/test_no_lookahead.py",
        "tests/test_queue_model.py",
        "tests/test_backtest_live_parity.py",
        "tests/test_utils.py",
    ])
    peurs = {x["peur"] for x in p}
    assert "lookahead" in peurs, "*et NOUS, notre coupe train/test FUYAIT*"
    assert "queue" in peurs
    assert "parity" in peurs, (
        "🔑 il a peur que backtest != live -- **le critere qu'on n'a JAMAIS applique**")
    for x in p:
        assert x["pourquoi"]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #6 — LES CONSTANTES. *Du calibrage gratuit, vole a des gens qui l'ont paye.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_6_les_constantes_des_autres_sont_extraites_ET_comparees_aux_NOTRES() -> None:
    src = "\n".join([
        "TAKER_FEE = 0.00045",
        "LATENCY_MS = 50",
        "MIN_SPREAD_BPS = 2",
        "fill_rate = 0.12",
        "kappa = 1.8",
        "x = compute(1)",
    ])
    c = extraire_constantes("mm.py", src)
    genres = {x.genre for x in c}
    assert {"frais", "latence_ms", "spread_bps", "taux_de_fill", "kappa"} <= genres

    d = {x.genre: x.as_dict() for x in c}
    assert "INVENT" in d["taux_de_fill"]["la_notre"].upper(), (
        "🔴 notre taux de fill est « 10 %% du flux » -- **un chiffre INVENTE**")
    assert "JAMAIS MESUR" in d["kappa"]["la_notre"].upper()
    assert "4,5" in d["frais"]["la_notre"]


def test_IDEE_6_on_se_COMPARE_on_ne_se_contemple_pas() -> None:
    """*Notre nombre de frais a vecu dans 6 fichiers, 4 valeurs.*"""
    assert set(LES_NOTRES) >= {"frais", "kappa", "taux_de_fill", "latence_ms"}


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #12 — LA REPRODUCTIBILITE. *Un backtest qu'on ne peut pas rejouer est une AFFIRMATION.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_12_un_repo_SANS_donnees_n_est_PAS_rejouable() -> None:
    r = reproductibilite(["src/bot.py", "README.md"])
    assert r.a_des_donnees is False
    assert "affirmation, pas une preuve" in r.verdict


def test_IDEE_12_un_repo_AVEC_donnees_et_telechargeur_est_rejouable() -> None:
    r = reproductibilite(["data/l2.parquet", "Makefile", "tests/test_x.py", "demo.ipynb"])
    assert r.a_des_donnees and r.a_un_telechargeur
    assert r.score >= 60 and "Rejouable" in r.verdict


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #3 — LE SCORE DIFFERENTIEL. *Mesurer le DELTA, pas le niveau.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_3_LE_TEST_QUI_COMPTE_3_concepts_NEUFS_battent_12_concepts_CONNUS() -> None:
    """🔑 *Un repo qui a 12 concepts dont on en a 11 vaut UNE idee.
       Un repo qui en a 3 dont on en a ZERO en vaut TROIS.*

    ***L'ancien score aurait mis le premier tout en haut. Il aurait eu tort.***
    """
    etat = NotreEtat(
        acquis={"frais_reels": "ok", "edge_net_apres_couts": "ok", "profondeur_du_carnet": "ok",
                "toxicite_du_flux": "ok", "contraintes_exchange": "ok",
                "disjoncteurs_session": "ok", "verrou_de_cote": "ok",
                "carry_delta_neutre": "ok", "funding_historique": "ok",
                "ledger_de_paper": "ok", "detection_lookahead": "ok"},
        manquants={"modele_de_file": "RIEN", "kappa_intensite": "RIEN",
                   "impact_de_marche": "RIEN"},
    )
    bavard = score_differentiel(list(etat.acquis) + ["modele_de_file"], etat)   # 12 dont 11 connus
    cible = score_differentiel(["modele_de_file", "kappa_intensite", "impact_de_marche"], etat)

    assert cible.score > bavard.score, (
        "REGRESSION : le repo qui n'apporte QU'UNE idee neuve repasse devant celui qui en "
        "apporte TROIS. **Le score mesure de nouveau le NIVEAU, pas le DELTA.**"
    )
    assert len(cible.nouveaux) == 3
    assert "N'A PAS" in cible.pourquoi


def test_IDEE_3_un_repo_qui_ne_fait_QUE_ce_qu_on_a_deja_est_une_VALIDATION_pas_une_decouverte():
    etat = NotreEtat(acquis={"frais_reels": "ok"}, manquants={"kappa_intensite": "RIEN"})
    d = score_differentiel(["frais_reels"], etat)
    assert not d.nouveaux
    assert "pas une découverte" in d.pourquoi or "validation externe" in d.pourquoi


def test_IDEE_3_on_INDEXE_NOTRE_VRAI_code_on_ne_le_recite_pas_de_memoire() -> None:
    """🔒 *Une liste tenue a la main diverge du code des le lendemain.* On la DERIVE."""
    racine = Path(__file__).resolve().parents[1] / "src" / "hl_observer"
    etat = indexer_notre_code(racine)
    assert "frais_reels" in etat.acquis, "on A la source unique des frais -- le code le prouve"
    assert "carry_delta_neutre" in etat.acquis, "le carry est notre seule piste positive"
    assert "modele_de_file" in etat.manquants, (
        "🔴 on n'a **AUCUN** modele de file -- notre fill est un chiffre INVENTE")
    assert "impact_de_marche" in etat.manquants


def test_IDEE_3_un_code_INTROUVABLE_ne_donne_PAS_un_faux_acquis() -> None:
    """*Ne pas savoir n'est pas « on l'a ».*"""
    etat = indexer_notre_code(Path(tempfile.gettempdir()) / "nexistepas_hypersmart")
    assert not etat.acquis
    assert len(etat.manquants) == len(NOS_CAPACITES)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #15 — LES ZONES VIERGES. *Ce que PERSONNE ne fait.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_15_on_signale_ce_que_PERSONNE_n_implemente() -> None:
    """***Un concept que personne n'implemente est soit inutile, soit INEXPLOITE.***"""
    z = zones_vierges(
        {"a/b": ["frais_reels", "modele_de_file"], "c/d": ["frais_reels"]},
        tous_les_concepts=["frais_reels", "modele_de_file", "cascade_de_liquidation"],
    )
    assert "cascade_de_liquidation" in z.jamais_vus
    assert ("modele_de_file", 1) in z.rares
    assert "INEXPLOIT" in z.as_dict()["pourquoi"].upper()


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #7 — LE CACHE BRUT. *On garde le TEXTE (un fait), jamais le VERDICT (une opinion).*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_7_on_peut_RE_JUGER_le_corpus_HORS_LIGNE() -> None:
    """🔑 ***C'est ce qui rend les 14 autres idees presque gratuites.***

    Ameliorer le filtre ne doit **pas** exiger de tout re-telecharger.
    """
    with tempfile.TemporaryDirectory() as d:
        c = CacheBrut(Path(d))
        c.ecrire("repo:a/b", "lambda = A * exp(-kappa * delta)")
        c.ecrire("repo:c/d", "guaranteed profit 🚀")
        assert c.taille() == 2

        tout = CacheBrut(Path(d)).tout()          # un NOUVEAU cache, sans reseau
        assert set(tout) == {"repo:a/b", "repo:c/d"}
        # on re-juge, hors ligne, avec le filtre du jour
        notes = {k: _notre_noteur(v) for k, v in tout.items()}
        assert notes["repo:a/b"] > notes["repo:c/d"]


def test_IDEE_7_le_cache_garde_le_TEXTE_jamais_le_verdict() -> None:
    """*Cacher un verdict, c'est figer une opinion. Cacher un texte, c'est garder un fait.*"""
    with tempfile.TemporaryDirectory() as d:
        c = CacheBrut(Path(d))
        c.ecrire("k", "texte brut")
        brut = (Path(d) / next(p.name for p in Path(d).glob("*.json"))).read_text(encoding="utf-8")
        assert "texte brut" in brut
        assert "score" not in brut and "verdict" not in brut


def test_IDEE_7_une_cle_absente_rend_None_pas_une_chaine_vide() -> None:
    with tempfile.TemporaryDirectory() as d:
        assert CacheBrut(Path(d)).lire("rien") is None


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #8 — LA DEDUPLICATION PAR CODE. *Sans elle, on lit 30 fois le meme bot.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

_CODE = "\n".join([
    "def compute_fill(price, size, book):",
    "    total = 0.0",
    "    for level in book:",
    "        qty = min(size, level.size)",
    "        total += qty * level.price",
    "        size -= qty",
    "    return total / max(size, 1)",
])
_FORK = _CODE.replace("compute_fill", "calc_fill").replace("total", "acc").replace(
    "level", "lvl").replace("0.0", "0.000")


def test_IDEE_8_un_FORK_aux_variables_renommees_est_DETECTE() -> None:
    """***Renommer ses variables ne rend pas un fork original.***"""
    assert similarite(empreintes(_CODE), empreintes(_FORK)) > 0.7


def test_IDEE_8_deux_codes_DIFFERENTS_ne_sont_PAS_jumeaux() -> None:
    autre = "def funding_apr(rate, hours):\n    return rate * hours * 24 * 365\n"
    assert similarite(empreintes(_CODE), empreintes(autre)) < 0.3


def test_IDEE_8_on_ne_lira_QU_UN_repo_par_groupe_de_jumeaux() -> None:
    j = dedupliquer({"a/orig": _CODE, "b/fork": _FORK, "c/autre": "def f(): return 42 * 1337"})
    assert j.groupes and sorted(j.groupes[0]) == ["a/orig", "b/fork"]
    assert j.representants["b/fork"] == "a/orig"
    assert "c/autre" not in j.representants


def test_IDEE_8_deux_codes_VIDES_ne_sont_PAS_declares_jumeaux() -> None:
    """*On ne declare pas jumeaux deux inconnus.*"""
    assert similarite(set(), set()) == 0.0


def test_IDEE_8_les_commentaires_ne_sont_PAS_du_code() -> None:
    assert normaliser("x = 1  # un long commentaire") == normaliser("x = 1")


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #9 — LE BUDGET ADAPTATIF. *Une ressource rare se pilote, elle ne se saupoudre pas.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_9_le_bandit_essaie_TOUT_avant_de_privilegier() -> None:
    """🔒 *On n'ecarte pas ce qu'on n'a pas essaye.*"""
    b = Bandit()
    bras = ["q1", "q2", "q3"]
    for _ in range(3):
        x = b.choisir(bras)
        b.noter(x, 0.0)
    assert set(b.tires) == set(bras)


def test_IDEE_9_le_bandit_APPREND_ou_creuser() -> None:
    b = Bandit()
    bras = ["sec", "fertile"]
    for _ in range(12):
        x = b.choisir(bras)
        b.noter(x, 5.0 if x == "fertile" else 0.0)
    assert b.tires["fertile"] > b.tires["sec"], (
        "un scan de 3 h doit APPRENDRE ou creuser -- sinon il saupoudre")
    d = b.as_dict()
    assert d["meilleures_requetes"][0]["requete"] == "fertile"
    assert any(x["requete"] == "sec" for x in d["sans_rendement"])


def test_IDEE_9_une_requete_sans_rendement_est_DEPRIORISEE_pas_CONDAMNEE() -> None:
    """🚩 *Une requete essayee une fois sans resultat n'est pas PROUVEE sterile.*

    La nuance n'est pas cosmetique : c'est la meme que « je n'ai pas su lire » vs « il n'y avait
    rien ». **Le bandit deprise ; il ne condamne pas.**
    """
    b = Bandit()
    for _ in range(6):
        x = b.choisir(["a", "b"])
        b.noter(x, 3.0 if x == "a" else 0.0)
    d = b.as_dict()
    assert "sans_rendement" in d
    assert "condamn" in d["pourquoi"].lower()


def test_IDEE_9_la_CURIOSITE_empeche_de_se_figer_sur_le_premier_filon() -> None:
    """*Sans le terme d'exploration, on se fige sur le premier filon et on rate le reste.*"""
    b = Bandit()
    for _ in range(30):
        x = b.choisir(["a", "b"])
        b.noter(x, 1.0 if x == "a" else 0.9)
    assert b.tires["b"] >= 3, "un bras presque aussi bon doit continuer d'etre essaye"


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #10 / #11 — LE GRAPHE SOCIAL.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_10_etre_CITE_vaut_plus_que_des_etoiles() -> None:
    """***Une etoile est un clic ; une citation est un CHOIX D'INGENIEUR.***"""
    inv = citations_inverses({"a/x": ["nkaz001/hftbacktest"], "b/y": ["nkaz001/hftbacktest"],
                              "c/z": ["nkaz001/hftbacktest", "autre/repo"]})
    assert sorted(inv["nkaz001/hftbacktest"]) == ["a/x", "b/y", "c/z"]
    assert autorite(inv, "nkaz001/hftbacktest") > autorite(inv, "autre/repo")


def test_IDEE_10_l_autorite_est_PLAFONNEE_POUR_DE_VRAI() -> None:
    """*Vingt citations ne valent pas vingt fois une -- et CENT ne valent pas cinq fois vingt.*

    Sans plafond dur, une awesome-list tres citee **ecraserait tout le classement**.
    """
    from hl_observer.research.moteur import AUTORITE_MAX

    beaucoup = autorite({"r": ["x%d" % i for i in range(500)]}, "r")
    peu = autorite({"r": ["x%d" % i for i in range(4)]}, "r")
    assert beaucoup == AUTORITE_MAX, "le plafond doit MORDRE, pas seulement exister"
    assert beaucoup < 5 * peu
    assert autorite({}, "inconnu") == 0.0


def test_IDEE_11_on_suit_les_AUTEURS_pas_les_projets() -> None:
    """*Les gens sont plus constants que les projets.*"""
    a = autres_repos_de_l_auteur(
        bons=["nkaz001/hftbacktest"],
        tous=["nkaz001/hftbacktest", "nkaz001/autre-truc", "inconnu/bidule"],
    )
    assert a["nkaz001"] == ["nkaz001/autre-truc"]
    assert "inconnu" not in a


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #13 — LA CHRONOLOGIE DU PROTOCOLE.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_13_on_cherche_les_repos_nes_APRES_un_changement_de_protocole() -> None:
    """*Un repo ne la semaine d'un changement sait quelque chose qu'on ne sait pas encore.*"""
    r = requetes_chronologiques()
    assert len(r) >= 4
    assert any("HIP-3" in x["evenement"] for x in r)
    assert any("airdrop" in x["evenement"].lower() for x in r)
    joint = " ".join(x["pourquoi"] for x in r)
    assert "farmeur" in joint.lower() or "bruit" in joint.lower(), (
        "l'airdrop a produit une VAGUE DE BRUIT -- il faut le dire")
    for x in r:
        assert x["requete"].startswith("hyperliquid created:")


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  #14 — 🔴 CHERCHER CE QUI NOUS DONNE **TORT**.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_IDEE_14_on_cherche_ACTIVEMENT_ce_qui_nous_donne_TORT() -> None:
    """***Un corpus qui ne contient que ce qui nous conforte est un corpus qu'on a CHOISI.***"""
    r = requetes_de_contradiction()
    assert len(r) >= 5
    conclusions = " ".join(x["notre_conclusion"] for x in r).lower()
    assert "market making" in conclusions
    assert "copy-trading" in conclusions or "copy trading" in conclusions
    for x in r:
        assert x["requete"], "une conclusion qu'on ne cherche pas a refuter est un dogme"
        assert len(x["notre_arme"]) > 40, (
            "on doit etre ARME pour juger le contradicteur, sinon on se fera avoir")


def test_IDEE_14_nos_armes_sont_des_MESURES_pas_des_opinions() -> None:
    joint = " ".join(x["notre_arme"] for x in requetes_de_contradiction())
    assert "0/29" in joint          # T1b : le MM a 100 % de fill
    assert "HLP" in joint           # le MM PAYE rend -0,01 %
    assert "7,97" in joint          # le copy-trading a cout zero
    assert "0/120" in joint         # le funding perp<->perp


@pytest.mark.parametrize("f", [requetes_de_contradiction, requetes_chronologiques])
def test_les_generateurs_de_requetes_ne_renvoient_JAMAIS_de_requete_vide(f) -> None:
    for x in f():
        assert x.get("requete")
