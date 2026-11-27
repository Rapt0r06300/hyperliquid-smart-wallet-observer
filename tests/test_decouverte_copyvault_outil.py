"""L'outil du moteur de decouverte, de bout en bout sur un faux coffre (27/11/2026) : ce qu'il lit, ce qu'il ecrit."""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

RACINE = Path(__file__).resolve().parents[1]
for chemin in (RACINE / "src", RACINE / "tools"):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

import decouverte_copyvault as T  # noqa: E402
from hl_observer.backtesting import copy_vault_decouverte as D  # noqa: E402

H, J = D.HEURE_MS, D.JOUR_MS
J0 = 20_000


def _shard(root: Path, famille: str, nom: str, lignes: list[dict]) -> dict:
    rel = Path("runtime/coffre_certifie/local/shards") / famille / nom
    chemin = root / rel
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(chemin, "wt", encoding="utf-8") as h:
        for r in lignes:
            h.write(json.dumps(r) + "\n")
    return {"famille": famille, "shard": rel.as_posix(), "sha256": hashlib.sha256(chemin.read_bytes()).hexdigest()}


def _faux_coffre(root: Path, *, jours: int = 70) -> None:
    rng = np.random.default_rng(3)
    episodes, i = [], 0
    for d in range(jours):
        for v in range(5):
            for k in range(3):
                i += 1
                episodes.append({"fill_id": f"f{i}", "vault": f"0x{v:040x}", "coin": ["BTC", "ETH", "EXT"][k],
                                 "action": "OPEN", "ts_ms": (J0 + d) * J + (2 + 6 * k) * H + v * 60_000,
                                 "fill_sign": int(rng.choice([1, -1])), "taille_usd": 5_000.0})
    bougies = []
    for coin in ("BTC", "ETH"):
        px = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.004, (jours + 3) * 24)))
        bougies += [{"coin": coin, "interval": "1h", "open_ts_ms": J0 * J + k * H, "close": float(p),
                     "source": "REST_BACKFILL_1H"} for k, p in enumerate(px)]
    externe = [{"coin": "EXT", "interval": "1h", "open_ts_ms": J0 * J + k * H, "close": 1.0, "source": "IRONFLOW_HF"}
               for k in range((jours + 3) * 24)]
    funding = [{"coin": c, "ts_ms": J0 * J + k * H, "funding": 1e-5} for c in ("BTC", "ETH") for k in range((jours + 3) * 24)]
    index = {"shards": [
        _shard(root, "fills_backfill", "a__vault_episodes.jsonl.gz", episodes),
        _shard(root, "candle", "a__candles_1h.jsonl.gz", bougies),
        _shard(root, "candle", "b__externe_ironflow_candles_1h_1.jsonl.gz", externe),
        _shard(root, "funding_history", "a__funding_history.jsonl.gz", funding)]}
    (root / "runtime/coffre_certifie/LOCAL_INDEX.json").write_text(json.dumps(index), encoding="utf-8")
    dates = {f"0x{v:040x}": (J0 + 40) * J for v in range(5)}       # sans Git : le cache des dates d'entree
    (root / T.ETAT_DIR).mkdir(parents=True, exist_ok=True)
    (root / T.ETAT_DIR / "entree_suivi.json").write_text(json.dumps(dates), encoding="utf-8")


def test_campagne_et_suivi_ecrivent_registre_memoire_et_recommandation(tmp_path, capsys):
    _faux_coffre(tmp_path)
    assert T.main(["--root", str(tmp_path), "--campagne", "--suivi", "--sans-ecarts-mesures"]) == 0
    sortie = capsys.readouterr().out
    assert "[campagne 1]" in sortie and "champion PAPER : AUCUN_TRADE" in sortie
    essais = [json.loads(x) for x in (tmp_path / "runtime/data/registre_essais.jsonl").read_text(encoding="utf-8").splitlines()]
    prereg = [e for e in essais if e["phase"] == "preregistration"]
    resultats = [e for e in essais if e["phase"] == "resultat"]
    assert prereg and len(prereg) == len(resultats)                 # chaque cellule inscrite AVANT, jugee APRES
    assert essais.index(prereg[-1]) < essais.index(resultats[0])
    ledger = [json.loads(x) for x in (tmp_path / "runtime/reports/copy_vault_quant_lab/copiabilite/EXPERIENCES.ndjson")
              .read_text(encoding="utf-8").splitlines()]
    assert ledger[-1]["hypotheses_tested"] == [D.HYPOTHESE] and ledger[-1]["verdicts"][0]["status"] == "MORE_DATA"
    etat = json.loads((tmp_path / T.ETAT_DIR / "CHAMPION_CHALLENGER.json").read_text(encoding="utf-8"))
    assert etat["recommandation_paper"]["applique_au_moteur"] is False
    memoire = json.loads((tmp_path / T.ETAT_DIR / "MEMOIRE_SCIENTIFIQUE.json").read_text(encoding="utf-8"))
    assert len(memoire["campagnes"]) == 1
    rapports = list((tmp_path / T.RAPPORTS).glob("*/RAPPORT.md"))
    assert len(rapports) == 1 and "Hypotheses declarees" in rapports[0].read_text(encoding="utf-8")
    # memes donnees, meme methode, meme juge : rien de neuf -> aucun essai de plus, rien d'ecrit
    n_essais = len(essais)
    assert T.main(["--root", str(tmp_path), "--campagne", "--sans-ecarts-mesures"]) == 0
    assert "rien de neuf" in capsys.readouterr().out
    assert len((tmp_path / "runtime/data/registre_essais.jsonl").read_text(encoding="utf-8").splitlines()) == n_essais
    # des donnees nouvelles : nouvelle campagne, mais les MEMES cellules ne gonflent pas le N du DSR
    n1 = ledger[-1]["inputs"]["cellules"]
    assert T._essais_anterieurs(tmp_path, set())[0] == n1          # cellules distinctes, pas 2 x les memes


def test_les_bougies_externes_ne_donnent_jamais_de_prix(tmp_path):
    _faux_coffre(tmp_path, jours=45)
    table, meta = T.construire_table(tmp_path, config=D.DecouverteConfig(), ecarts_mesures=False)
    assert "EXT" not in set(table["coin"]) and meta["rejets"]["coin_sans_prix"] > 0
    assert set(table["population"]) <= {"exploration", "validation", "exclue"}


def test_banc_ecrit_une_methode_dans_les_garde_fous(tmp_path):
    _faux_coffre(tmp_path, jours=60)
    assert T.main(["--root", str(tmp_path), "--banc", "--mondes", "1", "--sans-ecarts-mesures"]) == 0
    m = json.loads((tmp_path / T.ETAT_DIR / "METHODE_COURANTE.json").read_text(encoding="utf-8"))
    assert D.Methode(**m).respecte_les_garde_fous()
    assert len((tmp_path / T.ETAT_DIR / "METHODES.ndjson").read_text(encoding="utf-8").splitlines()) == 1


def test_sans_coffre_le_labo_continue(tmp_path, capsys):
    assert T.main(["--root", str(tmp_path)]) == 0
    assert "UNMEASURABLE" in capsys.readouterr().out


def test_memoire_insuffisante_pour_les_ecarts_rien_n_est_ecrit(tmp_path, capsys, monkeypatch):
    _faux_coffre(tmp_path, jours=45)

    def plein(*_a, **_k):
        raise MemoryError

    monkeypatch.setattr(T.E, "load_half_spreads", plein)
    assert T.main(["--root", str(tmp_path), "--campagne"]) == 0
    assert "memoire insuffisante" in capsys.readouterr().out
    assert not (tmp_path / "runtime/data/registre_essais.jsonl").exists()


def test_une_erreur_imprevue_ne_bloque_pas_le_labo(tmp_path, capsys, monkeypatch):
    _faux_coffre(tmp_path, jours=45)

    def casse(*_a, **_k):
        raise RuntimeError("panne simulee")

    monkeypatch.setattr(T, "construire_table", casse)
    assert T.main(["--root", str(tmp_path)]) == 0
    assert "[ERREUR]" in capsys.readouterr().out
    assert "panne simulee" in (tmp_path / T.ETAT_DIR / "DERNIERE_ERREUR.txt").read_text(encoding="utf-8")



def test_hypothese_declaree_inscrite_une_fois_et_suivie(tmp_path):
    _faux_coffre(tmp_path)
    assert T.main(["--root", str(tmp_path), "--campagne", "--suivi", "--sans-ecarts-mesures"]) == 0
    etat = json.loads((tmp_path / T.ETAT_DIR / "CHAMPION_CHALLENGER.json").read_text(encoding="utf-8"))
    declarees = [c for c in etat["challengers"].values() if c.get("palier") == "HYPOTHESE_DECLAREE"]
    assert len(declarees) == len(T.HYPOTHESES_DECLAREES) and declarees[0]["etat"] in ("GELE", "SUIVI")


def test_la_boucle_du_labo_relance_le_moteur_seulement_quand_il_faut(tmp_path):
    sys.path.insert(0, str(RACINE / "tools"))
    import alina_quant_lab_console as LAB

    appels = []
    (tmp_path / "runtime/coffre_certifie").mkdir(parents=True)
    index = tmp_path / "runtime/coffre_certifie/LOCAL_INDEX.json"
    index.write_text("{}", encoding="utf-8")
    lancer = lambda cmd: appels.append(cmd) or 0                                   # noqa: E731
    assert LAB._decouverte_periodique(tmp_path, maintenant=10_000.0, lancer=lancer)["lance"] is True
    assert LAB._decouverte_periodique(tmp_path, maintenant=10_600.0, lancer=lancer)["lance"] is False   # rien de neuf
    index.write_text('{"a": 1}', encoding="utf-8")
    assert LAB._decouverte_periodique(tmp_path, maintenant=10_900.0, lancer=lancer)["lance"] is False   # trop tot
    assert LAB._decouverte_periodique(tmp_path, maintenant=12_000.0, lancer=lancer)["lance"] is True    # neuf, 30 min
    assert LAB._decouverte_periodique(tmp_path, maintenant=12_000.0 + 6 * 3600, lancer=lancer)["lance"] is True
    assert len(appels) == 3 and appels[0][-1] == str(tmp_path)

    def casse(_cmd):
        raise OSError("panne")

    assert LAB._decouverte_periodique(tmp_path, maintenant=99_999_999.0, lancer=casse)["lance"] is True  # jamais d'exception



def test_un_seul_passage_a_la_fois(tmp_path, capsys):
    import os

    _faux_coffre(tmp_path, jours=45)
    verrou = tmp_path / T.ETAT_DIR / "decouverte.lock"
    verrou.write_text(json.dumps({"pid": os.getpid(), "ts": __import__("time").time()}), encoding="utf-8")
    assert T.main(["--root", str(tmp_path), "--campagne", "--sans-ecarts-mesures"]) == 0
    assert "[OCCUPE]" in capsys.readouterr().out
    assert not (tmp_path / "runtime/data/registre_essais.jsonl").exists()



def test_les_attentes_du_labo_relancent_aussi_le_moteur():
    import inspect

    sys.path.insert(0, str(RACINE / "tools"))
    import alina_quant_lab_console as LAB

    source = inspect.getsource(LAB)
    attentes = source.count("time.sleep(10)")
    assert attentes >= 3 and source.count("_decouverte_pendant_l_attente(ROOT)") == attentes



def test_pas_de_passage_si_la_memoire_manque(tmp_path, monkeypatch):
    import types

    (tmp_path / "runtime/coffre_certifie").mkdir(parents=True)
    (tmp_path / "runtime/coffre_certifie/LOCAL_INDEX.json").write_text("{}", encoding="utf-8")
    faux = types.SimpleNamespace(virtual_memory=lambda: types.SimpleNamespace(available=0.5 * 1024 ** 3))
    monkeypatch.setitem(sys.modules, "psutil", faux)
    r = T.periodique(tmp_path, maintenant=10_000.0)
    assert r["lance"] is False and "memoire basse" in r["raison"]
    assert not (tmp_path / T.ETAT_DIR / "BOUCLE_LABO.json").exists()       # rien d'ecrit : il reessaiera
