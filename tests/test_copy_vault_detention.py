"""COMBIEN DE TEMPS LES LEADERS TIENNENT — mesuré, et jamais une sortie absente comptée pour zéro.

POURQUOI (17/11/2026). Tout le modèle de copie rapide repose sur un horizon de détention que NOUS
choisissons : le tunnel mesure la sortie à `entrée + 300 s`, `copy_vault_v5_lifecycle_train` explore
une grille de `max_hold_ms`. Recherche sur tout le dépôt : **personne n'avait mesuré la durée que
les leaders tiennent réellement.**

MESURE, journée du 16/11 au coffre, 1 660 493 fills, 1 231 050 paires appariées :

```
p10   2,4 min        p50  44,8 min        p90   5,53 h
p25  10,7 min        p75   2,27 h         p99  14,74 h
médiane pondérée par la taille : 30,9 min
160 comptes sur 163 ont une médiane supérieure à 300 s
part censurée : 12,2 %
```

L'horizon de 300 s du tunnel tombe donc **entre le p10 et le p25** : presque aucun leader ne tient
aussi peu. Cela n'invalide pas le tunnel — il mesure l'observabilité d'une sortie à horizon fixe —
mais il situe ce que la copie rapide modélise : une stratégie que les leaders observés n'emploient
pas. La médiane de 44,8 min, elle, est remarquablement proche de la cadence de réalignement de
60 min de l'étude de réplication.

Ces tests verrouillent l'appariement FIFO, le traitement des réductions partielles, des
retournements, et surtout la CENSURE : une position encore ouverte en fin de fenêtre n'a pas de
durée, et on ne lui en invente aucune.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import copy_vault_detention as D  # noqa: E402

MINUTE = 60_000


def _f(ts: int, label: str, taille: float = 1.0, *, coin: str = "BTC", vault: str = "0xa",
       pnl: float | None = None) -> dict:
    ligne = {"vault": vault, "coin": coin, "ts_ms": ts, "sz": taille, "dir": label}
    if pnl is not None:
        ligne["closedPnl"] = pnl
    return ligne


def test_une_ouverture_puis_sa_cloture_donnent_la_DUREE_REELLE():
    r = D.apparier([_f(0, "Open Long"), _f(45 * MINUTE, "Close Long", pnl=3.0)])
    assert r["appariees"] == 1
    assert r["detention_ms"]["p50"] == 45 * MINUTE
    assert r["censurees"] == 0
    assert r["pnl_clos_observes"] == 1


def test_une_position_ENCORE_OUVERTE_est_CENSUREE_jamais_zero():
    """Le cœur de l'honnêteté : une sortie non observée n'est pas une détention nulle."""
    r = D.apparier([_f(0, "Open Long"), _f(MINUTE, "Open Long")])
    assert r["appariees"] == 0
    assert r["censurees"] == 2
    assert r["part_censuree"] == 1.0
    assert r["detention_ms"]["p50"] is None, "aucune duree ne doit etre fabriquee"


def test_une_REDUCTION_PARTIELLE_ferme_une_partie_et_laisse_courir_le_reste():
    r = D.apparier([_f(0, "Open Long", 10.0), _f(30 * MINUTE, "Close Long", 4.0)])
    assert r["appariees"] == 1
    assert r["detention_ms"]["p50"] == 30 * MINUTE
    assert r["censurees"] == 1, "les 6 unites restantes sont encore ouvertes"


def test_l_appariement_est_FIFO_la_tranche_la_plus_ANCIENNE_se_ferme_d_abord():
    r = D.apparier([_f(0, "Open Long", 1.0), _f(10 * MINUTE, "Open Long", 1.0),
                    _f(60 * MINUTE, "Close Long", 1.0)])
    assert r["appariees"] == 1
    assert r["detention_ms"]["p50"] == 60 * MINUTE, "c'est la tranche de t=0 qui se ferme"
    assert r["censurees"] == 1


def test_un_RETOURNEMENT_ferme_le_sens_existant_et_ouvre_l_oppose():
    r = D.apparier([_f(0, "Open Long", 1.0), _f(20 * MINUTE, "Long > Short", 1.0),
                    _f(50 * MINUTE, "Close Short", 1.0)])
    assert r["appariees"] == 2
    durees = sorted(r["comptes"]["0xa"]["n_durees"] for _ in (0,))
    assert durees == [2]
    assert r["detention_ms"]["p10"] == 20 * MINUTE
    assert r["detention_ms"]["p90"] == 30 * MINUTE


def test_les_coins_et_les_comptes_ne_se_melangent_JAMAIS():
    r = D.apparier([_f(0, "Open Long", coin="BTC"), _f(MINUTE, "Close Long", coin="ETH"),
                    _f(2 * MINUTE, "Close Long", coin="BTC", vault="0xb")])
    assert r["appariees"] == 0, "ni le coin ni le compte ne doivent servir de passerelle"
    assert r["cloture_sans_ouverture_observee"] == 2
    assert r["censurees"] == 1


def test_une_cloture_SANS_ouverture_observee_est_une_troncature_a_GAUCHE_declaree():
    """La fenêtre commence après l'ouverture : ce n'est pas une durée de zéro."""
    r = D.apparier([_f(5 * MINUTE, "Close Long", 3.0)])
    assert r["appariees"] == 0
    assert r["cloture_sans_ouverture_observee"] == 1
    assert r["detention_ms"]["p50"] is None


def test_une_etiquette_INCONNUE_est_comptee_et_n_entre_dans_aucun_appariement():
    """`Sell` et `Buy` existent au coffre (65 814 et 50 552 le 16/11) : sens non déductible."""
    r = D.apparier([_f(0, "Open Long"), _f(MINUTE, "Sell"), _f(2 * MINUTE, "Buy"),
                    _f(3 * MINUTE, "Close Long")])
    assert r["etiquettes_inconnues"] == {"sell": 1, "buy": 1}
    assert r["appariees"] == 1, "seules les etiquettes connues apparient"


def test_la_MEDIANE_PONDEREE_par_la_taille_differe_de_la_mediane_simple():
    """Une grosse position courte ne doit pas peser comme une petite position longue."""
    r = D.apparier([
        _f(0, "Open Long", 100.0), _f(MINUTE, "Close Long", 100.0),        # grosse, 1 min
        _f(0, "Open Short", 1.0, coin="ETH"), _f(60 * MINUTE, "Close Short", 1.0, coin="ETH"),
    ])
    assert r["appariees"] == 2
    assert r["detention_mediane_ponderee_par_taille_ms"] == MINUTE
    assert r["detention_ms"]["p50"] in (MINUTE, 60 * MINUTE)


def test_l_horloge_est_CHOISIE_par_l_appelant_et_declaree():
    """Comportement du leader = horloge d'échange ; copiabilité = horloge de réception."""
    lignes = [{"vault": "0xa", "coin": "BTC", "ts_ms": 0, "received_at_ms": 500,
               "sz": 1.0, "dir": "Open Long"},
              {"vault": "0xa", "coin": "BTC", "ts_ms": MINUTE, "received_at_ms": MINUTE + 900,
               "sz": 1.0, "dir": "Close Long"}]
    echange = D.apparier(lignes)
    reception = D.apparier(lignes, horloge="received_at_ms")
    assert echange["detention_ms"]["p50"] == MINUTE
    assert reception["detention_ms"]["p50"] == MINUTE + 400
    assert echange["horloge"] == "ts_ms" and reception["horloge"] == "received_at_ms"


def test_la_part_censuree_est_publiee_AVEC_la_mediane():
    """Une médiane sur les seules positions refermées est biaisée vers le court."""
    r = D.apparier([_f(0, "Open Long"), _f(MINUTE, "Close Long"), _f(2 * MINUTE, "Open Short")])
    assert r["part_censuree"] == 0.5
    assert "biaisee vers" in r["avertissement"]


# ───────── 17/11 : LE MÊME FILL VU DEUX FOIS, ET LE PIÈGE DU HASH DE TRANSACTION ─────────
#
# MA PREMIÈRE MESURE Y ÉTAIT TOMBÉE. `fills_forward` contient le même fill d'échange observé par
# plusieurs sources : journée du 17/11, **618 264 lignes pour 579 363 fills distincts**, soit 6,3 %
# de doublons entre `LIVE_POLL` (596 102), `LIVE_WS` (20 338) et `LIVE_TWAP` (1 824). Sans
# déduplication, une ouverture vue deux fois remplit deux fois la file FIFO.
#
# Effet mesuré sur la journée du 16/11 (1 660 493 lignes, 54 304 doublons écartés) : les doublons
# biaisaient la détention **vers le bas** — p50 44,8 -> 46,6 min, médiane pondérée par la taille
# 30,9 -> 35,3 min (+14 %).
#
# MAIS LE PIÈGE EST AILLEURS : `hash` est le hash de TRANSACTION, pas du fill. Mesuré : 83 862
# hashes portent plusieurs lignes, et le hash sentinelle `0x0000…0000` en porte **40 915** (les
# sous-fills d'un TWAP). Dédupliquer sur `hash` écraserait 40 915 fills distincts en un seul.
def test_le_meme_fill_vu_par_DEUX_SOURCES_ne_compte_qu_une_fois():
    ws = {"vault": "0xa", "coin": "BTC", "ts_ms": 0, "sz": 1.0, "px": 100.0,
          "dir": "Open Long", "source": "LIVE_WS",
          "stable_event_id": "abc"}
    poll = {**ws, "source": "LIVE_POLL", "stable_event_id": "abc"}
    r = D.apparier([ws, poll, _f(30 * MINUTE, "Close Long")])
    assert r["doublons_ignores"] == 1
    assert r["appariees"] == 1
    assert r["censurees"] == 0, "sans dedup, une ouverture fantome resterait ouverte"


def test_un_fill_SANS_stable_event_id_se_deduplique_sur_sa_cle_NATURELLE():
    """97 % des lignes n'ont pas de `stable_event_id` : il faut une clé d'échange."""
    base = {"vault": "0xa", "coin": "BTC", "ts_ms": 0, "sz": 1.0, "px": 100.0,
            "dir": "Open Long"}
    r = D.apparier([dict(base, source="LIVE_POLL"), dict(base, source="LIVE_WS"),
                    _f(20 * MINUTE, "Close Long")])
    assert r["doublons_ignores"] == 1
    assert r["appariees"] == 1


def test_le_HASH_DE_TRANSACTION_n_est_JAMAIS_une_identite():
    """Le hash sentinelle `0x0000…0000` porte 40 915 lignes : s'en servir écraserait tout."""
    sentinelle = "0x" + "0" * 64
    a = {"vault": "0xa", "coin": "XMR", "ts_ms": 1, "sz": 0.727, "px": 508.98,
         "dir": "Open Long", "hash": sentinelle}
    b = {"vault": "0xa", "coin": "XMR", "ts_ms": 2, "sz": 0.727, "px": 508.72,
         "dir": "Open Long", "hash": sentinelle}
    assert D.cle_d_identite(a) != D.cle_d_identite(b), (
        "deux sous-fills TWAP du meme hash sont des fills DIFFERENTS")
    r = D.apparier([a, b])
    assert r["doublons_ignores"] == 0
    assert r["censurees"] == 2, "les deux ouvertures doivent exister"


def test_deux_fills_IDENTIQUES_mais_de_PRIX_different_ne_sont_pas_des_doublons():
    """Le prix fait partie de l'identité d'échange : deux exécutions, deux fills."""
    a = {"vault": "0xa", "coin": "BTC", "ts_ms": 7, "sz": 1.0, "px": 100.0, "dir": "Open Long"}
    b = {**a, "px": 100.5}
    r = D.apparier([a, b])
    assert r["doublons_ignores"] == 0
    assert r["censurees"] == 2


def test_la_deduplication_peut_etre_DESACTIVEE_et_c_est_declare():
    base = {"vault": "0xa", "coin": "BTC", "ts_ms": 0, "sz": 1.0, "px": 1.0, "dir": "Open Long"}
    sans = D.apparier([base, dict(base)], dedupliquer=False)
    avec = D.apparier([base, dict(base)], dedupliquer=True)
    assert sans["deduplique"] is False and sans["doublons_ignores"] == 0
    assert avec["deduplique"] is True and avec["doublons_ignores"] == 1
