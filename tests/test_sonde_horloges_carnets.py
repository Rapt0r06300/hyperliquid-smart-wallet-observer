"""La sonde mesure-t-elle LA MEME PORTE que le labo, ou autre chose ?

Une sonde qui dirait << le split se formerait >> alors que le labo refuse serait pire
qu'inutile : elle justifierait un refactor sur une illusion. Ces tests verrouillent
l'EQUIVALENCE entre `sonde_horloges_carnets.apparier` (horodatages seuls, `array('q')`) et
`copy_vault_signal_alignment.evaluable_signals` (la vraie fonction, dicts complets).

Pourquoi la sonde existe : l'appariement du labo ne lit **qu'un seul champ** de chaque carnet
(`ts_ms`), mais garde les lignes entieres en memoire -- 32,7 M dicts x ~700 o = 23 Go, ce qui
explique le RSS de **24,2 Go** mesure le 22/11/2026 sur 8 jours (RAM libre tombee a 0,6 Go).
Les memes horodatages en `array('q')` tiennent dans **0,26 Go**, soit ~90x moins. La sonde
mesure cette hypothese sans toucher au labo.
"""
from __future__ import annotations

import array
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

import sonde_horloges_carnets as SONDE  # noqa: E402

from hl_observer.backtesting.copy_vault_signal_alignment import (  # noqa: E402
    MAX_BOOK_AGE_MS,
    evaluable_signals,
)

JOUR_MS = 86_400_000


def _cas(signaux, carnets_par_coin):
    """Les memes donnees dans les deux formes : dicts pour le labo, array pour la sonde."""
    metaorders = [{"coin": c, "signal_ts_ms": ts, "action": a} for c, ts, a in signaux]
    books = {c: [{"ts_ms": ts} for ts in sorted(tss)] for c, tss in carnets_par_coin.items()}
    horloges = {c: array.array("q", sorted(tss)) for c, tss in carnets_par_coin.items()}
    return metaorders, books, horloges


def test_la_sonde_rend_LES_MEMES_nombres_que_le_labo():
    base = 10 * JOUR_MS
    signaux = [("BTC", base + 1_000, "ADD"), ("BTC", base + 60_000, "ADD"),
               ("ETH", base + 2_000, "REDUCE"), ("SOL", base + 3_000, "ADD")]
    carnets = {"BTC": [base, base + 59_000], "ETH": [base + 1_500]}   # SOL : aucun carnet
    metaorders, books, horloges = _cas(signaux, carnets)

    vrai = evaluable_signals(metaorders, books, max_book_age_ms=MAX_BOOK_AGE_MS,
                             min_signals_per_day=1)
    sonde = SONDE.apparier(signaux, horloges, age_max_ms=MAX_BOOK_AGE_MS)

    assert sonde["evaluables"] == vrai["summary"]["evaluable_signals"]
    assert sonde["alignes_add"] == vrai["aligned_adds"]
    assert sonde["sans_carnet_pour_ce_coin"] == 1, "SOL n'a aucun carnet"


def test_un_carnet_TROP_VIEUX_est_rejete_des_deux_cotes():
    base = 10 * JOUR_MS
    signaux = [("BTC", base + MAX_BOOK_AGE_MS + 1, "ADD")]
    carnets = {"BTC": [base]}
    metaorders, books, horloges = _cas(signaux, carnets)
    vrai = evaluable_signals(metaorders, books, min_signals_per_day=1)
    sonde = SONDE.apparier(signaux, horloges)
    assert sonde["evaluables"] == 0 == vrai["summary"]["evaluable_signals"]
    assert sonde["carnet_trop_vieux"] == 1


def test_un_carnet_POSTERIEUR_au_signal_ne_compte_pour_personne():
    """La dichotomie ne doit jamais retenir un carnet du futur : ce serait du lookahead."""
    base = 10 * JOUR_MS
    signaux = [("BTC", base, "ADD")]
    carnets = {"BTC": [base + 1_000]}
    metaorders, books, horloges = _cas(signaux, carnets)
    assert SONDE.apparier(signaux, horloges)["evaluables"] == 0
    assert evaluable_signals(metaorders, books, min_signals_per_day=1)["aligned_adds"] == 0


def test_le_seuil_des_jours_DENSES_est_le_meme():
    """Un jour sous le seuil ne doit pas entrer dans la base de la decoupe temporelle."""
    base = 10 * JOUR_MS
    signaux: list[tuple[str, int, str]] = []
    carnets: dict[str, list[int]] = {"BTC": []}
    for jour in range(3):
        n = 1 if jour == 0 else SONDE.MIN_SIGNALS_PER_DAY + 2   # jour 0 = creux
        for k in range(n):
            ts = base + jour * JOUR_MS + k * 1_000
            signaux.append(("BTC", ts, "ADD"))
            carnets["BTC"].append(ts - 500)
    metaorders, books, horloges = _cas(signaux, carnets)
    vrai = evaluable_signals(metaorders, books)
    sonde = SONDE.apparier(signaux, horloges)
    assert sonde["jours_DENSES"] == 2, sonde
    assert len(sonde["timestamps_denses"]) == len(vrai["timestamps"])


def test_les_horloges_tiennent_8_octets_par_horodatage():
    """C'est tout l'interet : 8 o par carnet au lieu d'un dict de ~700 o."""
    serie = array.array("q", range(1_000))
    assert serie.itemsize == 8
    assert serie.buffer_info()[1] * serie.itemsize == 8_000
