"""UN PROCESSUS VIVANT N'EST PAS UNE COLLECTE QUI MARCHE — les quatre niveaux.

    processus vivant  !=  collecte fonctionnelle  !=  donnees fraiches  !=  certifiables

CE QUE CES TESTS INTERDISENT, mesure sur le vrai lanceur le 22/11/2026 :

```
--- Etat interne (economic_collection_pids.json) ---
  Lease valide: ?                      <- POUR TOUJOURS : la clef lue n'existe pas
  Workers: 20                          <- alors que 0 etait vivant
```

* `runtime/data/economic_collection_pids.json` listait **20 workers avec leurs PID** alors
  que l'identification par ligne de commande en trouvait **0**. Le fichier decrivait une
  campagne morte depuis **10,2 h**. Un watchdog qui s'y fierait croirait tout sain -- ou
  tuerait ces PID, desormais recycles.
* L'ecran lisait `d.get("lease_valid")`, une clef absente de CE schema (elle appartient a
  `bounded_collection`). Le bail y vit sous `lease.expires_at_ms`. Un homonyme de clef
  decidait donc la mesure, et rendait `?` au lieu de dire << expire depuis dix heures >>.
* Le fichier annoncait `pids: 20` et `demarres_et_verifies: 19` : une incoherence interne
  que personne ne regardait.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

import etat_collecte_reel as E  # noqa: E402

PROJET = "C:/Users/flo/Desktop/Projet invest"
MAINTENANT_MS = 1_795_310_000_000


def _collecteur(pid, famille="bbo"):
    return {"pid": pid, "owner": "flo",
            "cmdline": f"{PROJET}/tools/python/python.exe {PROJET}/tools/collecter_{famille}.py"}


# ---------------------------------------------------------------- le bail
def test_le_bail_se_lit_sous_lease_expires_at_ms_PAS_lease_valid():
    """`lease_valid` appartient a un AUTRE schema : le chercher ici rendait `?` a jamais."""
    etat = {"lease": {"issued_at_ms": MAINTENANT_MS - 120_000,
                      "expires_at_ms": MAINTENANT_MS - 60_000,
                      "lease_id": "lease-abc"}}
    verdict = E.validite_du_bail(etat, maintenant_ms=MAINTENANT_MS)
    assert verdict["valide"] is False
    assert verdict["motif"] == "EXPIRE"
    assert verdict["reste_s"] < 0
    assert verdict["lease_id"] == "lease-abc"


def test_un_bail_encore_valide_est_reconnu():
    etat = {"lease": {"issued_at_ms": MAINTENANT_MS - 10_000,
                      "expires_at_ms": MAINTENANT_MS + 110_000}}
    verdict = E.validite_du_bail(etat, maintenant_ms=MAINTENANT_MS)
    assert verdict["valide"] is True
    assert verdict["motif"] == "VALIDE"
    assert 100 < verdict["reste_s"] <= 110


def test_un_bail_ABSENT_ou_ILLISIBLE_rend_None_jamais_False():
    """`None` = je ne sais pas ; `False` = j'ai mesure qu'il est expire. Confondre les deux
    ferait passer une ignorance pour une observation."""
    assert E.validite_du_bail({}, maintenant_ms=MAINTENANT_MS)["valide"] is None
    assert E.validite_du_bail({}, maintenant_ms=MAINTENANT_MS)["motif"] == "BAIL_ABSENT"
    bancal = {"lease": {"expires_at_ms": "bientot"}}
    verdict = E.validite_du_bail(bancal, maintenant_ms=MAINTENANT_MS)
    assert verdict["valide"] is None
    assert verdict["motif"] == "EXPIRATION_ILLISIBLE"


# ------------------------------------------------- declares contre REELLEMENT vivants
def test_vingt_workers_DECLARES_et_zero_VIVANT_est_dit_comme_tel():
    """Le cas exact mesure sur la machine : un etat de 10,2 h listant des PID recycles."""
    etat = {"pids": {f"famille-{i}": 10_000 + i for i in range(20)}}
    workers = E.workers_reellement_vivants(etat, processus=[], racine=PROJET)
    assert workers["declares"] == 20
    assert workers["vivants"] == []
    assert len(workers["morts"]) == 20
    assert {m["motif"] for m in workers["morts"]} == {"INTROUVABLE"}


def test_un_worker_vivant_ET_identifie_est_compte_vivant():
    etat = {"pids": {"bbo-collector": 777}}
    workers = E.workers_reellement_vivants(
        etat, processus=[_collecteur(777)], racine=PROJET)
    assert len(workers["vivants"]) == 1
    assert workers["morts"] == []


def test_un_PID_recycle_par_un_processus_ETRANGER_compte_pour_MORT():
    """Le danger du PID recycle : le processus existe, mais ce n'est pas le notre."""
    etat = {"pids": {"bbo-collector": 777}}
    etranger = [{"pid": 777, "owner": "flo", "cmdline": "C:/Python/python.exe -m pip list"}]
    workers = E.workers_reellement_vivants(etat, processus=etranger, racine=PROJET)
    assert workers["vivants"] == []
    assert workers["morts"][0]["motif"] == "HORS_PROJET"


# ---------------------------------------------------------------- fraicheur
def test_un_ruban_ABSENT_et_un_ruban_PERIME_sont_DISTINGUES(tmp_path):
    """<< ce flux n'existe pas >> et << ce flux ne bouge plus >> n'appellent pas la meme
    action : les confondre ferait relancer un collecteur sain, ou ignorer une panne."""
    import os
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    frais = data / "vault_fills_live.jsonl"
    frais.write_text("{}\n", encoding="utf-8")
    vieux = data / "copy_vault_bbo_lane.jsonl"   # nom du ruban LOCAL (22/11 : etait *_tape, un telechargement)
    vieux.write_text("{}\n", encoding="utf-8")
    ancien = frais.stat().st_mtime - (E.AGE_RUBAN_PERIME_S + 600)
    os.utime(vieux, (ancien, ancien))

    etats = {r["ruban"]: r["etat"] for r in E.fraicheur_des_rubans(tmp_path)}
    assert etats["runtime/data/vault_fills_live.jsonl"] == "FRAIS"
    assert etats["runtime/data/copy_vault_bbo_lane.jsonl"] == "PERIME"
    assert etats["runtime/data/copy_vault_l2_tape.jsonl"] == "ABSENT"


# ---------------------------------------------------------------- le verdict
def test_des_processus_VIVANTS_sans_donnee_fraiche_ne_sont_JAMAIS_marques_OK():
    """La regle centrale de la mission : ca respire, ca ne collecte plus -> on le DIT."""
    verdict = E.verdict_global(
        bail={"valide": True, "motif": "VALIDE", "reste_s": 90},
        workers={"declares": 3, "vivants": [{"pid": 1}, {"pid": 2}], "morts": []},
        rubans=[{"ruban": "a", "age_s": 99_999, "etat": "PERIME"}],
        identifies_par_commande=2)
    assert verdict["processus"] == "VIVANTS"
    assert verdict["collecte"] == "PROCESSUS_VIVANTS_MAIS_AUCUNE_DONNEE_FRAICHE"
    assert any("RUBANS_PERIMES" in a for a in verdict["alertes"])


def test_un_etat_qui_declare_des_workers_INTROUVABLES_leve_une_alerte():
    verdict = E.verdict_global(
        bail={"valide": False, "motif": "EXPIRE", "reste_s": -36_654},
        workers={"declares": 20, "vivants": [], "morts": [{"pid": i} for i in range(20)]},
        rubans=[{"ruban": "a", "age_s": None, "etat": "ABSENT"}],
        identifies_par_commande=0)
    assert verdict["processus"] == "AUCUN"
    assert verdict["collecte"] == "ARRETEE"
    assert any("ETAT_PERIME" in a for a in verdict["alertes"])
    assert any("BAIL_EXPIRE" in a for a in verdict["alertes"])


def test_une_collecte_qui_PRODUIT_est_reconnue_sans_alerte_de_fraicheur():
    verdict = E.verdict_global(
        bail={"valide": True, "motif": "VALIDE", "reste_s": 100},
        workers={"declares": 2, "vivants": [{"pid": 1}, {"pid": 2}], "morts": []},
        rubans=[{"ruban": "a", "age_s": 30, "etat": "FRAIS"}],
        identifies_par_commande=2)
    assert verdict["collecte"] == "PRODUIT"
    assert verdict["alertes"] == []


def test_un_bail_INDETERMINE_est_signale_et_pas_pris_pour_valide():
    verdict = E.verdict_global(
        bail={"valide": None, "motif": "BAIL_ABSENT", "reste_s": None},
        workers={"declares": 0, "vivants": [], "morts": []},
        rubans=[{"ruban": "a", "age_s": 10, "etat": "FRAIS"}],
        identifies_par_commande=0)
    assert any("BAIL_INDETERMINE" in a for a in verdict["alertes"])
