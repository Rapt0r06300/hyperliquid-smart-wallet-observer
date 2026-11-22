"""MODE HORLOGES : jeter le contenu des carnets apres l'avoir mesure, garder les instants.

CE QUE CE MODE REPARE, mesure des deux cotes :

```
le split du labo exige >= 6 journees UTC distinctes DANS UNE SEULE tranche
la memoire               n'en tenait qu'une : 24,2 Go de RSS pour 8 jours (22/11/2026,
                         RAM libre tombee a 0,6 Go), ~28 Go pour 6 jours (18/11/2026)
```

Or `copy_vault_signal_alignment.evaluable_signals` ne lit **qu'un seul champ** de chaque
carnet pour decider l'appariement, le split et les portes :

    for row in metaorders:
        stamps = horloges.get(row["coin"])        # <- uniquement des ts_ms
        index = bisect.bisect_right(stamps, signal_ms) - 1

32,7 M lignes x ~700 o en dicts = 23 Go ; les memes horodatages en `array("q")` = 0,26 Go. La
sonde `tools/sonde_horloges_carnets.py` a mesure que le split **SE FORME** ainsi : 7 journees
denses pour **0,084 Go**.

POURQUOI LA LIGNE EST QUAND MEME CONSTRUITE. Les diagnostics de rejouabilite
(`non_causal_rows`, `safe_causal_rows`) se calculent sur la ligne complete. Le mode horloges la
construit, l'evalue avec la **MEME expression** que le mode complet, puis ne garde que l'entier.
Recopier ces predicats ailleurs creerait deux verites qui divergeraient un jour -- le defaut que
ce depot a deja paye plusieurs fois.

CE QUE CES TESTS VERROUILLENT :
1. `False` par defaut -> le mode complet est INCHANGE (aucun appelant ne bouge) ;
2. EQUIVALENCE des instants : les horloges portent exactement les `ts_ms` du mode complet ;
3. EQUIVALENCE des diagnostics : `valid_rows`, `non_causal_rows`, `safe_causal_rows` et le
   bilan de rejouabilite sont les memes dans les deux modes ;
4. les horloges sont TRIEES (la dichotomie du labo l'exige) et compactes (8 o par instant) ;
5. l'audit DIT dans quel mode il est, pour qu'un consommateur ne decouvre pas en plantant que
   `row["bid"]` n'existe pas ;
6. les filtres amont (causal, borne basse, fenetres) s'appliquent IDENTIQUEMENT -- sans quoi le
   mode horloges rendrait des signaux << evaluables >> qui ne le sont pas : de l'executabilite
   fabriquee, interdite par le contrat.
"""
from __future__ import annotations

import array
import json
from typing import Any

from hl_observer.backtesting.copy_vault_book_loader import load_observed_books

JOUR_MS = 86_400_000


def _ecrire_carnets(tmp_path, instants):
    data_dir = tmp_path / "runtime" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "carnet_venues.jsonl").write_text(
        "\n".join(
            json.dumps({"coin": coin, "collecte_ts": instant / 1000.0, "hl_bid": 99.0,
                        "hl_ask": 101.0, "taille_min_usd": 1_000.0})
            for coin, instant in instants
        ) + "\n",
        encoding="utf-8",
    )
    return tmp_path


def _instants_du_mode_complet(books):
    return {coin: sorted(row["ts_ms"] for row in rows) for coin, rows in books.items()}


def _instants_du_mode_horloges(horloges):
    return {coin: list(serie) for coin, serie in horloges.items()}


# ------------------------------------------------- 1. le defaut ne change rien
def test_sans_le_mode_horloges_le_comportement_est_INCHANGE(tmp_path):
    _ecrire_carnets(tmp_path, [("BTC", 1_000), ("BTC", 2_000), ("ETH", 3_000)])
    books, audit = load_observed_books(tmp_path)
    assert audit["horloges_seulement"] is False
    assert all(isinstance(rows, list) for rows in books.values())
    assert books["BTC"][0]["bid"] == 99.0, "le mode complet doit toujours porter les prix"


# ------------------------------------------------- 2 et 3. equivalence
def test_les_horloges_portent_EXACTEMENT_les_instants_du_mode_complet(tmp_path):
    instants = [("BTC", 1_000), ("BTC", 5_000), ("BTC", 2_000),
                ("ETH", 3_000), ("SOL", 9_000), ("ETH", 500)]
    _ecrire_carnets(tmp_path, instants)
    books, _ = load_observed_books(tmp_path)
    horloges, _ = load_observed_books(tmp_path, horloges_seulement=True)
    assert _instants_du_mode_horloges(horloges) == _instants_du_mode_complet(books)


def test_les_DIAGNOSTICS_sont_les_memes_dans_les_deux_modes(tmp_path):
    """Si les compteurs incrementaux divergeaient du calcul sur les lignes, le mode horloges
    rendrait un bilan de rejouabilite different -- donc une autre verite."""
    _ecrire_carnets(tmp_path, [("BTC", 1_000), ("BTC", 2_000), ("ETH", 3_000)])
    _, complet = load_observed_books(tmp_path)
    _, horloges = load_observed_books(tmp_path, horloges_seulement=True)
    for cle in ("valid_rows", "invalid_rows", "rows_read", "duplicate_rows_rejected",
                "future_rows_rejected", "past_rows_rejected",
                "replay_grade_ready", "replay_grade_blockers"):
        assert horloges[cle] == complet[cle], cle


def test_un_corpus_VIDE_bloque_pareil_dans_les_deux_modes(tmp_path):
    """`NO_OBSERVED_BOOK_ROWS` ne doit pas dependre du mode : sinon le mode horloges
    declarerait rejouable un corpus que le mode complet refuse."""
    _ecrire_carnets(tmp_path, [])
    _, complet = load_observed_books(tmp_path)
    _, horloges = load_observed_books(tmp_path, horloges_seulement=True)
    assert "NO_OBSERVED_BOOK_ROWS" in complet["replay_grade_blockers"]
    assert "NO_OBSERVED_BOOK_ROWS" in horloges["replay_grade_blockers"]
    assert horloges["replay_grade_ready"] is complet["replay_grade_ready"] is False


# ------------------------------------------------- 4. triees et compactes
def test_les_horloges_sont_TRIEES_et_compactes(tmp_path):
    """La dichotomie du labo exige l'ordre ; `array('q')` donne 8 o par instant."""
    _ecrire_carnets(tmp_path, [("BTC", 9_000), ("BTC", 1_000), ("BTC", 5_000)])
    horloges, _ = load_observed_books(tmp_path, horloges_seulement=True)
    serie = horloges["BTC"]
    assert isinstance(serie, array.array) and serie.itemsize == 8
    assert list(serie) == sorted(serie) == [1_000, 5_000, 9_000]


# ------------------------------------------------- 5. l audit dit le mode
def test_l_audit_DIT_qu_il_est_en_mode_horloges(tmp_path):
    """Un consommateur ne doit pas decouvrir en plantant que `row["bid"]` n'existe pas."""
    _ecrire_carnets(tmp_path, [("BTC", 1_000)])
    _, audit = load_observed_books(tmp_path, horloges_seulement=True)
    assert audit["horloges_seulement"] is True


# ------------------------------------------------- 6. les filtres amont tiennent
def test_la_borne_BASSE_filtre_identiquement_en_mode_horloges(tmp_path):
    """Un filtre amont relache rendrait des signaux << evaluables >> qui ne le sont pas."""
    _ecrire_carnets(tmp_path, [("BTC", 1_000), ("BTC", 2_000), ("BTC", 3_000)])
    books, complet = load_observed_books(tmp_path, depuis_ms=2_000)
    horloges, audit = load_observed_books(tmp_path, depuis_ms=2_000, horloges_seulement=True)
    assert list(horloges["BTC"]) == [2_000, 3_000]
    assert _instants_du_mode_horloges(horloges) == _instants_du_mode_complet(books)
    assert audit["past_rows_rejected"] == complet["past_rows_rejected"] == 1


def test_la_borne_HAUTE_causale_filtre_identiquement(tmp_path):
    """La coupure causale est la garde contre le lookahead : elle ne doit pas s'assouplir."""
    _ecrire_carnets(tmp_path, [("BTC", 1_000), ("BTC", 2_000), ("BTC", 3_000)])
    books, complet = load_observed_books(tmp_path, as_of_ms=2_000)
    horloges, audit = load_observed_books(tmp_path, as_of_ms=2_000, horloges_seulement=True)
    assert list(horloges["BTC"]) == [1_000, 2_000]
    assert _instants_du_mode_horloges(horloges) == _instants_du_mode_complet(books)
    assert audit["future_rows_rejected"] == complet["future_rows_rejected"] == 1


def test_les_fenetres_de_signal_se_combinent_au_mode_horloges(tmp_path):
    """Les deux economies doivent pouvoir jouer ensemble sans se contredire."""
    signal = 10 * JOUR_MS
    _ecrire_carnets(tmp_path, [("BTC", signal - 5 * JOUR_MS), ("BTC", signal - 10_000),
                               ("BTC", signal)])
    horloges, audit = load_observed_books(
        tmp_path, horloges_seulement=True, fenetres_signal_ms=[(signal, signal)])
    assert list(horloges["BTC"]) == [signal - 10_000, signal]
    assert audit["hors_fenetres_signal_rejected"] == 1
    assert audit["horloges_seulement"] is True


# ------------------------------------------------- 7. l'appariement accepte les horloges
def test_l_appariement_rend_LA_MEME_CHOSE_par_books_ou_par_horloges():
    """La boucle ne lit qu'un `ts_ms` : les deux entrees doivent donner le meme dict ENTIER.

    C'est la propriete qui autorise le mode horloges a servir la porte du labo : si les deux
    chemins divergeaient d'un seul compteur, le mode econome mesurerait autre chose.
    """
    from hl_observer.backtesting.copy_vault_signal_alignment import evaluable_signals
    base = 10 * JOUR_MS
    metaorders = [{"coin": "BTC", "signal_ts_ms": base + 1_000, "action": "ADD"},
                  {"coin": "BTC", "signal_ts_ms": base + 60_000, "action": "ADD"},
                  {"coin": "ETH", "signal_ts_ms": base + 2_000, "action": "REDUCE"},
                  {"coin": "SOL", "signal_ts_ms": base + 3_000, "action": "ADD"}]
    books = {"BTC": [{"ts_ms": base}, {"ts_ms": base + 59_000}],
             "ETH": [{"ts_ms": base + 1_500}]}
    horloges = {"BTC": array.array("q", [base, base + 59_000]),
                "ETH": array.array("q", [base + 1_500])}
    par_books = evaluable_signals(metaorders, books, min_signals_per_day=1)
    par_horloges = evaluable_signals(metaorders, horloges=horloges, min_signals_per_day=1)
    assert par_books == par_horloges


def test_fournir_LES_DEUX_ou_AUCUN_est_un_refus():
    """Deviner l'entree ferait silencieusement autre chose que ce que l'appelant croit, et
    ici << autre chose >> voudrait dire des signaux declares evaluables sans carnet."""
    import pytest

    from hl_observer.backtesting.copy_vault_signal_alignment import evaluable_signals
    metas = [{"coin": "BTC", "signal_ts_ms": 10 * JOUR_MS, "action": "ADD"}]
    books = {"BTC": [{"ts_ms": 10 * JOUR_MS}]}
    horloges = {"BTC": array.array("q", [10 * JOUR_MS])}
    with pytest.raises(ValueError, match="FOURNIR_BOOKS_OU_HORLOGES"):
        evaluable_signals(metas, books, horloges=horloges)
    with pytest.raises(ValueError, match="FOURNIR_BOOKS_OU_HORLOGES"):
        evaluable_signals(metas)


def test_la_CHAINE_COMPLETE_chargeur_puis_appariement_tient(tmp_path):
    """De bout en bout : charger en mode horloges, puis apparier, sans jamais voir un dict."""
    from hl_observer.backtesting.copy_vault_signal_alignment import evaluable_signals
    base = 10 * JOUR_MS
    _ecrire_carnets(tmp_path, [("BTC", base), ("BTC", base + 20_000)])
    horloges, audit = load_observed_books(tmp_path, horloges_seulement=True)
    assert audit["horloges_seulement"] is True
    metaorders = [{"coin": "BTC", "signal_ts_ms": base + 25_000, "action": "ADD"}]
    bilan = evaluable_signals(metaorders, horloges=horloges, min_signals_per_day=1)
    assert bilan["aligned_adds"] == 1, "le carnet de +20 s precede le signal de 5 s"


# ------------------------------------------------- 8. le chargement EN DEUX TEMPS
def test_le_chargement_en_deux_temps_NE_PAYE_PAS_les_carnets_quand_le_split_refuse():
    """Le gain tient a une seule chose : ne pas charger 24,2 Go pour apprendre qu'on refuse."""
    from hl_observer.backtesting.chargement_en_deux_temps import (
        charger_carnets_en_deux_temps,
    )
    appels: list[bool] = []

    def charger(_ws, **kw):
        horloges_seulement = bool(kw.get("horloges_seulement"))
        appels.append(horloges_seulement)
        if horloges_seulement:
            return ({"BTC": array.array("q", [1_000])}, {"horloges_seulement": True})
        return ({"BTC": [{"ts_ms": 1_000, "bid": 1.0}]}, {"horloges_seulement": False})

    carnets, audit = charger_carnets_en_deux_temps(
        "ws", [{"coin": "BTC", "signal_ts_ms": 1_000, "action": "ADD"}],
        tranche=None, seuil_jours=6,
        charger=charger,
        apparier=lambda _m, **_k: {"timestamps": [1_000]},
        bornes=lambda *_a, **_k: None,            # le split REFUSE
        diagnostic=lambda *_a, **_k: {"motif": "JOURS_UTC_INSUFFISANTS_DANS_LA_FENETRE"})
    assert appels == [True], "les carnets COMPLETS ont ete charges pour rien"
    assert audit["phase_1_horloges"]["split_possible"] is False
    assert audit["phase_1_horloges"]["carnets_complets_charges"] is False
    assert audit["phase_1_horloges"]["diagnostic"]["motif"].startswith("JOURS_UTC")
    assert isinstance(carnets["BTC"], array.array)


def test_le_chargement_en_deux_temps_PAYE_les_carnets_quand_le_split_se_forme():
    from hl_observer.backtesting.chargement_en_deux_temps import (
        charger_carnets_en_deux_temps,
    )
    appels: list[bool] = []

    def charger(_ws, **kw):
        horloges_seulement = bool(kw.get("horloges_seulement"))
        appels.append(horloges_seulement)
        if horloges_seulement:
            return ({"BTC": array.array("q", [1_000])}, {"horloges_seulement": True})
        return ({"BTC": [{"ts_ms": 1_000, "bid": 1.0}]}, {"horloges_seulement": False})

    carnets, audit = charger_carnets_en_deux_temps(
        "ws", [{"coin": "BTC", "signal_ts_ms": 1_000, "action": "ADD"}],
        tranche=None, seuil_jours=6,
        charger=charger,
        apparier=lambda _m, **_k: {"timestamps": [1_000]},
        bornes=lambda *_a, **_k: {"train_start_ms": 0})   # le split SE FORME
    assert appels == [True, False], "le rejeu doit recevoir des carnets COMPLETS"
    assert audit["phase_1_horloges"]["carnets_complets_charges"] is True
    assert carnets["BTC"][0]["bid"] == 1.0


def test_un_chargeur_qui_IGNORE_le_drapeau_ne_fait_pas_tomber_la_chaine():
    """Defaut mesure le 22/11/2026 : 3 tests du labo substituent le chargeur par
    `lambda *a, **k: (books, {})`, qui rend des carnets COMPLETS et un audit VIDE. Les passer
    comme horloges comparait un dict a un entier dans la dichotomie. On lit donc ce que
    l'audit DIT du mode, au lieu de supposer qu'il a ete honore."""
    from hl_observer.backtesting.chargement_en_deux_temps import (
        charger_carnets_en_deux_temps,
    )
    complets = {"BTC": [{"ts_ms": 1_000, "bid": 1.0}]}
    vus: list[Any] = []

    def apparier(metaorders, *args, **kw):
        vus.append(("horloges" in kw and kw["horloges"] is not None, bool(args)))
        return {"timestamps": [1_000]}

    carnets, audit = charger_carnets_en_deux_temps(
        "ws", [{"coin": "BTC", "signal_ts_ms": 1_000, "action": "ADD"}],
        tranche=None, seuil_jours=6,
        charger=lambda *_a, **_k: (complets, {}),     # drapeau IGNORE, audit vide
        apparier=apparier,
        bornes=lambda *_a, **_k: None)
    assert vus[0] == (False, True), "les lignes completes doivent partir en `books`"
    assert audit["phase_1_horloges"]["mode_horloges_honore"] is False
    assert audit["phase_1_horloges"]["octets_horloges"] == -1, "poids INCONNU, pas zero"
    assert carnets is complets
