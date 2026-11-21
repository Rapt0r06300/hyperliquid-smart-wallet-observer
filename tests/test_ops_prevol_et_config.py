"""Les deux prevols OPS que personne ne testait : joignabilite reseau et dump de config.

POURQUOI CE FICHIER EXISTE. La mesure du 21/11/2026 a liste 7 modules qu'AUCUN test n'atteint,
meme indirectement. Deux d'entre eux decident du demarrage (`network_health`) ou ecrivent le
seul document d'audit post-mortem de la configuration (`config_dump`).

DEUX DEFAUTS TROUVES EN LES COUVRANT, et verifies ici :
  * `config_dump` lisait l'horloge DEUX fois pour une seule grandeur (`ts` et `ts_iso`
    pouvaient enjamber une seconde) ;
  * `ts_iso` etait un instant NAIF en heure locale : deux lignes du changement d'heure
    devenaient impossibles a ordonner dans un fichier fait pour etre relu apres coup.

Aucun test ici ne touche le reseau : `urlopen` est remplace.
"""
from __future__ import annotations

import json
import time

import pytest

from hl_observer.ops import config_dump as CD
from hl_observer.ops import network_health as NH


# ------------------------------------------------------------------ prevol reseau
class _Reponse:
    def __init__(self, status): self.status = status
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_une_reponse_200_est_joignable(monkeypatch):
    monkeypatch.setattr(NH, "urlopen", lambda req, timeout=None: _Reponse(200))
    r = NH.check_hl_reachable(timeout=1)
    assert r["reachable"] is True and r["status"] == 200
    assert r["url"] == NH.HL_INFO_URL and r["latency_ms"] >= 0


@pytest.mark.parametrize("status", [204, 301, 401, 429, 500, 503])
def test_tout_sauf_200_est_declare_NON_joignable(monkeypatch, status):
    """Fail-closed : un 429 ou un 503 n'est pas « joignable », c'est un refus a respecter."""
    monkeypatch.setattr(NH, "urlopen", lambda req, timeout=None: _Reponse(status))
    assert NH.check_hl_reachable(timeout=1)["reachable"] is False


def test_une_panne_reseau_rend_un_diagnostic_nomme_sans_lever(monkeypatch):
    """Un prevol qui EXPLOSE n'est pas un prevol : il doit rendre la cause, pas une trace."""
    def _boum(req, timeout=None):
        raise OSError("getaddrinfo failed")
    monkeypatch.setattr(NH, "urlopen", _boum)
    r = NH.check_hl_reachable(timeout=1)
    assert r["reachable"] is False
    assert "getaddrinfo" in r["error"] and len(r["error"]) <= 200


def test_le_message_d_erreur_est_borne(monkeypatch):
    """Un message de 10 000 caracteres dans un diagnostic noie le journal."""
    def _boum(req, timeout=None):
        raise OSError("x" * 10_000)
    monkeypatch.setattr(NH, "urlopen", _boum)
    assert len(NH.check_hl_reachable(timeout=1)["error"]) == 200


def test_assert_leve_quand_c_est_injoignable_et_se_taise_sinon(monkeypatch):
    monkeypatch.setattr(NH, "urlopen", lambda req, timeout=None: _Reponse(503))
    with pytest.raises(ConnectionError):
        NH.assert_hl_reachable(timeout=1)
    monkeypatch.setattr(NH, "urlopen", lambda req, timeout=None: _Reponse(200))
    assert NH.assert_hl_reachable(timeout=1) is None


def test_la_requete_porte_un_timeout(monkeypatch):
    """Sans timeout, un prevol peut geler le demarrage indefiniment."""
    vus = {}
    def _capture(req, timeout=None):
        vus["timeout"] = timeout
        return _Reponse(200)
    monkeypatch.setattr(NH, "urlopen", _capture)
    NH.check_hl_reachable(timeout=3.5)
    assert vus["timeout"] == 3.5
    assert NH.TIMEOUT_S > 0


# ------------------------------------------------------------------ dump de config
def test_seules_les_variables_du_projet_sont_dumpees(monkeypatch, tmp_path):
    """L'environnement AMBIANT porte deja des HYPERSMART_ : un test qui exige le contraire
    mesure la machine, pas le code. On verifie donc l'INCLUSION et l'EXCLUSION, pas un total."""
    monkeypatch.setenv("HYPERSMART_SONDE_DE_TEST", "3")
    monkeypatch.setenv("PATH_SANS_RAPPORT", "zzz")
    payload = CD.dump_config(tmp_path)
    assert payload["config"]["HYPERSMART_SONDE_DE_TEST"] == "3"
    assert "PATH_SANS_RAPPORT" not in payload["config"]
    assert all(cle.startswith(CD.PREFIX) for cle in payload["config"])
    assert payload["var_count"] == len(payload["config"])


@pytest.mark.parametrize("nom", ["HYPERSMART_API_KEY", "HYPERSMART_SECRET_X",
                                  "HYPERSMART_TOKEN", "HYPERSMART_PASSWORD",
                                  "HYPERSMART_CREDENTIAL_FILE"])
def test_un_secret_n_est_JAMAIS_ecrit_en_clair(monkeypatch, tmp_path, nom):
    """Le dump est un fichier sur disque : y ecrire un secret le rend definitivement expose."""
    monkeypatch.setenv(nom, "valeur-ultra-secrete")
    payload = CD.dump_config(tmp_path)
    assert payload["config"][nom] == "***REDACTED***"
    ecrit = (tmp_path / "runtime" / "data" / "config_dump.json").read_text(encoding="utf-8")
    assert "valeur-ultra-secrete" not in ecrit


def test_l_horodatage_est_en_UTC_et_explicite(monkeypatch, tmp_path):
    """UN INSTANT NAIF NE SE RELIT PAS. Le `Z` dit lequel : sans lui, 02:30 peut etre deux fois."""
    payload = CD.dump_config(tmp_path)
    assert payload["ts_iso"].endswith("Z")
    attendu = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(payload["ts"]))
    assert payload["ts_iso"] == attendu, "ts et ts_iso ne decrivent pas le MEME instant"


def test_ts_et_ts_iso_viennent_d_UNE_SEULE_lecture_d_horloge(monkeypatch, tmp_path):
    """Une grandeur, une valeur : deux `time.time()` peuvent enjamber une seconde."""
    appels = []
    vrai = time.time

    def _compte():
        appels.append(1)
        return vrai()

    monkeypatch.setattr(CD.time, "time", _compte)
    CD.dump_config(tmp_path)
    assert len(appels) == 1, f"{len(appels)} lectures d'horloge pour un seul instant"


def test_le_fichier_ecrit_est_du_json_relisible(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPERSMART_X", "1")
    payload = CD.dump_config(tmp_path)
    chemin = tmp_path / "runtime" / "data" / "config_dump.json"
    assert json.loads(chemin.read_text(encoding="utf-8")) == payload


def test_un_dossier_non_inscriptible_ne_fait_pas_tomber_le_demarrage(monkeypatch, tmp_path):
    """Le dump est un CONFORT d'audit : son echec ne doit jamais empecher de demarrer."""
    monkeypatch.setenv("HYPERSMART_X", "1")
    cible = tmp_path / "runtime" / "data" / "config_dump.json"
    cible.parent.mkdir(parents=True)
    cible.mkdir()                               # un DOSSIER a la place du fichier -> OSError
    payload = CD.dump_config(tmp_path)
    # la valeur est RENDUE malgre l'echec d'ecriture : c'est tout ce qui compte ici
    assert payload["config"]["HYPERSMART_X"] == "1"
    assert payload["var_count"] == len(payload["config"])


def test_la_racine_vient_de_l_environnement_quand_elle_n_est_pas_donnee(monkeypatch, tmp_path):
    monkeypatch.setenv("ALINA_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("HYPERSMART_X", "1")
    CD.dump_config()
    assert (tmp_path / "runtime" / "data" / "config_dump.json").exists()
