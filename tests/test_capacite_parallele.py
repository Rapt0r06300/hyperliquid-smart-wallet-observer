"""Capacité de la fenêtre lue en parallèle (25/11/2026) : sortie IDENTIQUE à la lecture en flux d'origine.

475 s mesurées pour lire 2,45 Go de trades dans un seul processus. La nouvelle lecture répartit les shards
sur plusieurs processus mais doit rendre, au bit près, ``ROLES.capacite_par_coin(TRANCHES.flux(...))`` :
mêmes refus au même rang, mêmes lignes lues et ignorées, mêmes sommes flottantes par minute (l'ordre
d'addition compte : les montants vont de 1e-6 à 1e9 dans les mêmes minutes, à cheval sur plusieurs shards).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

RACINE = Path(__file__).resolve().parents[1]
for chemin in (RACINE / "src", RACINE / "tools"):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

import etude_copiabilite as E  # noqa: E402
from hl_observer.backtesting import coffre_tranches as TRANCHES  # noqa: E402
from hl_observer.backtesting import copy_vault_roles_familles as ROLES  # noqa: E402

DEBUT = 1_795_000_000_000
MIN = 60_000


def _sha(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def _trade(rng) -> dict:
    t = DEBUT + int(rng.integers(-3 * MIN, 40 * MIN))
    trade = {"coin": rng.choice(["BTC", "ETH", "SOL", "kPEPE", "", "BTC", "ETH"])}
    if rng.random() < 0.03:
        trade["coin"] = [None, 5, True][int(rng.integers(0, 3))]
    horloge = rng.random()
    if horloge < 0.8:
        trade["exchange_ts_ms"] = t
    elif horloge < 0.9:
        trade["exchange_ts_ms"], trade["received_at_ms"] = None, t + 500
    elif horloge < 0.95:
        trade["exchange_ts_ms"] = float(t)                                   # pas un entier : repli d'horloge
        trade["received_at_ms"] = t
    else:
        trade["exchange_ts_ms"] = True                                       # booléen : sans horloge
    montant = float(10.0 ** rng.uniform(-6, 9))
    prix = round(float(rng.uniform(0.5, 2.0)) * montant, 6)
    if rng.random() < 0.85:
        trade["price"] = prix if rng.random() < 0.7 else str(prix)
    else:
        trade["px"] = prix
        if rng.random() < 0.3:
            trade["price"] = None                                            # price présent mais None
    taille = [round(float(rng.uniform(0.01, 3)), 4), "1.5", "abc", -1.0, 0, True, "nan", "inf"][
        int(rng.choice(8, p=[0.7, 0.1, 0.04, 0.04, 0.04, 0.03, 0.03, 0.02]))]
    trade["size" if rng.random() < 0.8 else "sz"] = taille
    return trade


def _ecrire(chemin: Path, lignes: list[str], gz: bool = True) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    texte = "".join(lignes).encode("utf-8")
    chemin.write_bytes(gzip.compress(texte) if gz else texte)


def _coffre(racine: Path, graine: int) -> list[dict]:
    rng = np.random.default_rng(graine)
    entrees = []
    for i in range(int(rng.integers(6, 12))):
        lignes = []
        for _ in range(int(rng.integers(50, 400))):
            choix = rng.random()
            if choix < 0.02:
                lignes.append("   \n")
            elif choix < 0.04:
                lignes.append("{pas du json\n")
            elif choix < 0.05:
                lignes.append("[1, 2]\n")
            else:
                lignes.append(json.dumps(_trade(rng)) + "\n")
        gz = rng.random() < 0.85
        rel = f"coffre/trades_marche/s{i:02d}.jsonl" + (".gz" if gz else "")
        chemin = racine / rel
        _ecrire(chemin, lignes, gz=gz)
        entrees.append({"shard": rel, "sha256": _sha(chemin), "famille": "trades_marche"})
    # les refus, chacun à un rang tiré au hasard
    tronque = racine / "coffre/trades_marche/tronque.jsonl.gz"
    _ecrire(tronque, [json.dumps(_trade(rng)) + "\n" for _ in range(300)])
    tronque.write_bytes(tronque.read_bytes()[:-40])                           # lu en partie, puis EOFError
    geant = racine / "coffre/trades_marche/geant.jsonl.gz"
    _ecrire(geant, [json.dumps(_trade(rng)) + "\n" for _ in range(30)]
            + [json.dumps({"coin": "BTC", "exchange_ts_ms": 2 ** 60, "price": 1.0, "size": 1.0}) + "\n"])
    speciaux = [
        {"shard": "coffre/trades_marche/tronque.jsonl.gz", "sha256": _sha(tronque)},
        {"shard": "coffre/trades_marche/geant.jsonl.gz", "sha256": _sha(geant)},   # relu en flux
        {"shard": "coffre/trades_marche/absent.jsonl.gz", "sha256": "0" * 64},
        {"shard": entrees[0]["shard"], "sha256": "f" * 64},                        # SHA divergent
        {"shard": entrees[1]["shard"], "sha256": None},                            # SHA absent
        {"shard": "../hors_du_coffre.jsonl.gz", "sha256": "0" * 64},
    ]
    for special in speciaux:
        entrees.insert(int(rng.integers(0, len(entrees) + 1)), {**special, "famille": "trades_marche"})
    return entrees


def _origine(racine, entrees, debut, fin):
    compteurs: dict = {}
    sortie = ROLES.capacite_par_coin(TRANCHES.flux(racine, entrees, famille="trades_marche", debut_ms=debut,
                                                   fin_ms=fin, compteurs=compteurs))
    return sortie, compteurs


@pytest.mark.parametrize("graine", range(8))
def test_la_lecture_parallele_rend_exactement_la_lecture_en_flux(graine, tmp_path):
    entrees = _coffre(tmp_path, graine)
    rng = np.random.default_rng(1000 + graine)
    debut, fin = DEBUT + int(rng.integers(-2 * MIN, 5 * MIN)), DEBUT + int(rng.integers(20 * MIN, 45 * MIN))
    attendu, compteurs_attendus = _origine(tmp_path, entrees, debut, fin)
    for ouvriers in (2, 3):
        compteurs: dict = {}
        obtenu = E._capacite_en_parallele(tmp_path, entrees, famille="trades_marche", debut_ms=debut, fin_ms=fin,
                                          compteurs=compteurs, ouvriers=ouvriers)
        assert obtenu == attendu
        assert list(obtenu["par_coin"]) == list(attendu["par_coin"])
        assert compteurs == compteurs_attendus                    # tous les compteurs, refus compris
    assert compteurs_attendus["lignes_sans_horloge"] > 0 and compteurs_attendus["lignes_hors_fenetre"] > 0
    assert attendu["lignes_lues"] > 0 and {r["motif"] for r in compteurs_attendus["shards_refuses"]} == {
        "LECTURE_INTERROMPUE", "ABSENT_DU_DISQUE", "SHA_DIVERGENT", "SHA_ABSENT", "HORS_COFFRE"}


def test_les_ex_aequo_gardent_l_ordre_de_premiere_apparition(tmp_path):
    """Le classement des coins étroits départage les ex aequo par ordre d'entrée dans le dictionnaire."""
    lignes_a = [json.dumps({"coin": c, "exchange_ts_ms": DEBUT + 1, "price": 1.0, "size": 10.0}) + "\n"
                for c in ("ZZZ", "AAA", "MMM")]
    lignes_b = [json.dumps({"coin": c, "exchange_ts_ms": DEBUT + 2, "price": 1.0, "size": 10.0}) + "\n"
                for c in ("QQQ", "AAA", "BBB")]
    entrees = []
    for nom, lignes in (("a", lignes_a), ("b", lignes_b)):
        rel = f"coffre/trades_marche/{nom}.jsonl.gz"
        _ecrire(tmp_path / rel, lignes)
        entrees.append({"shard": rel, "sha256": _sha(tmp_path / rel)})
    attendu, _ = _origine(tmp_path, entrees, DEBUT, DEBUT + MIN)
    obtenu = E._capacite_en_parallele(tmp_path, entrees, famille="trades_marche", debut_ms=DEBUT,
                                      fin_ms=DEBUT + MIN, compteurs={}, ouvriers=2)
    assert obtenu["coins_ou_une_minute_mediane_absorbe_moins_que_l_ordre"] == \
        attendu["coins_ou_une_minute_mediane_absorbe_moins_que_l_ordre"]
    assert [c for c, _ in obtenu["coins_ou_une_minute_mediane_absorbe_moins_que_l_ordre"]] == [
        "ZZZ", "MMM", "QQQ", "BBB", "AAA"]                                     # AAA : 2 trades, multiple double


def test_capacite_de_la_fenetre_passe_par_la_lecture_parallele(tmp_path, monkeypatch):
    entrees = _coffre(tmp_path, 3)
    for e in entrees:
        e.update({"ts_min_ms": DEBUT - 5 * MIN, "ts_max_ms": DEBUT + 50 * MIN})
    index = tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    index.parent.mkdir(parents=True)
    index.write_text(json.dumps({"shards": entrees}), encoding="utf-8")
    appels = []
    vraie = E._capacite_en_parallele
    monkeypatch.setattr(E, "_capacite_en_parallele", lambda *a, **k: (appels.append(1), vraie(*a, **k))[1])
    parallele = E.capacite_de_la_fenetre(tmp_path, debut_ms=DEBUT, fin_ms=DEBUT + 30 * MIN, ouvriers=2)
    en_flux = E.capacite_de_la_fenetre(tmp_path, debut_ms=DEBUT, fin_ms=DEBUT + 30 * MIN, ouvriers=1)
    assert appels == [1]
    assert parallele == en_flux


@pytest.mark.parametrize("graine", range(4))
def test_les_sommes_par_minute_sont_les_memes_flottants(graine, tmp_path, monkeypatch):
    """Le résumé arrondit à 2 décimales : il cacherait une somme faite dans un autre ordre. On compare donc
    les sommes elles-mêmes, coin par coin et minute par minute, avant tout arrondi."""
    entrees = _coffre(tmp_path, 50 + graine)
    vus: list[dict] = []
    vraie = ROLES.capacite_depuis_minutes

    def capture(par_coin, **k):
        vus.append({c: dict(m) for c, m in par_coin.items()})
        return vraie(par_coin, **k)

    monkeypatch.setattr(ROLES, "capacite_depuis_minutes", capture)
    _origine(tmp_path, entrees, DEBUT - 5 * MIN, DEBUT + 50 * MIN)
    E._capacite_en_parallele(tmp_path, entrees, famille="trades_marche", debut_ms=DEBUT - 5 * MIN,
                             fin_ms=DEBUT + 50 * MIN, compteurs={}, ouvriers=2)
    origine, parallele = vus
    assert parallele == origine
    assert all(parallele[c][m].hex() == origine[c][m].hex() for c in origine for m in origine[c])
    assert sum(len(m) for m in origine.values()) < sum(1 for _ in TRANCHES.flux(
        tmp_path, entrees, famille="trades_marche", debut_ms=DEBUT - 5 * MIN, fin_ms=DEBUT + 50 * MIN))  # collisions
