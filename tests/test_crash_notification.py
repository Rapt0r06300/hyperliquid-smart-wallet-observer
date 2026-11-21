"""Le signal de crash : aucune injection de commande, aucun instant naif, aucun silence.

POURQUOI CE FICHIER EXISTE. La mesure du 21/11/2026 a liste 7 modules qu'aucun test n'atteint.
Celui-ci est le chemin par lequel un arret du moteur devient visible pour un operateur.

LE DEFAUT TROUVE EN LE COUVRANT. `send_toast` interpolait le titre et le message DANS le
source PowerShell :

    f"$text[0].AppendChild($template.CreateTextNode('{title}')) > $null; "

Une raison de crash contenant une apostrophe cassait le script ; une raison contenant
`'; <commande>; '` faisait EXECUTER cette commande. Or une raison de crash vient d'une
exception : c'est une DONNEE, pas une constante. C'est une injection de commande que la regle
`shell=True` de l'audit ne pouvait pas voir, puisqu'il n'y a pas de `shell=True`.

Aucun test ici ne lance PowerShell : `subprocess.run` est remplace et inspecte.
"""
from __future__ import annotations

import json
import time

import pytest

from hl_observer.ops import crash_notification as CN

MALVEILLANT = "boum'; Write-Output PWNED; '"


@pytest.fixture(autouse=True)
def _racine(monkeypatch, tmp_path):
    monkeypatch.setenv("ALINA_PROJECT_ROOT", str(tmp_path))
    return tmp_path


# ------------------------------------------------------------------ l'injection
def test_le_script_powershell_ne_contient_JAMAIS_le_texte_fourni(monkeypatch):
    """LA GARANTIE : le message n'entre pas dans le script, donc il ne peut pas en devenir une ligne."""
    vus = {}

    def _capture(cmd, **kwargs):
        vus["cmd"] = cmd
        vus["env"] = kwargs.get("env") or {}
        return None

    monkeypatch.setattr(CN.subprocess, "run", _capture)
    assert CN.send_toast(MALVEILLANT, MALVEILLANT) is True
    script = " ".join(vus["cmd"])
    assert "PWNED" not in script
    assert MALVEILLANT not in script
    assert "$env:HYPERSMART_TOAST_TITRE" in script


def test_le_texte_passe_par_l_environnement_et_y_arrive_intact(monkeypatch):
    """Il doit rester LISIBLE : une garde qui mutile le message ne previent plus de rien."""
    vus = {}
    monkeypatch.setattr(CN.subprocess, "run",
                        lambda cmd, **kw: vus.update(env=kw.get("env") or {}))
    CN.send_toast("TITRE", MALVEILLANT)
    assert vus["env"]["HYPERSMART_TOAST_TITRE"] == "TITRE"
    assert vus["env"]["HYPERSMART_TOAST_MESSAGE"] == MALVEILLANT


def test_un_texte_enorme_est_borne(monkeypatch):
    vus = {}
    monkeypatch.setattr(CN.subprocess, "run",
                        lambda cmd, **kw: vus.update(env=kw.get("env") or {}))
    CN.send_toast("T" * 10_000, "M" * 10_000)
    assert len(vus["env"]["HYPERSMART_TOAST_TITRE"]) == 200
    assert len(vus["env"]["HYPERSMART_TOAST_MESSAGE"]) == 400


def test_le_toast_porte_un_timeout_et_ne_passe_pas_par_un_shell(monkeypatch):
    """`shell=True` serait une seconde porte d'injection ; sans timeout, le crash gele l'arret."""
    vus = {}
    monkeypatch.setattr(CN.subprocess, "run", lambda cmd, **kw: vus.update(kw=kw, cmd=cmd))
    CN.send_toast("t", "m")
    assert vus["kw"].get("timeout") == 5
    assert vus["kw"].get("shell") in (None, False)
    assert isinstance(vus["cmd"], list) and vus["cmd"][0] == "powershell"


def test_un_echec_de_toast_est_COMPTE_et_jamais_propage(monkeypatch):
    """Best-effort VISIBLE : un toast qui n'arrive jamais sans trace, c'est une alerte fantome."""
    from hl_observer.ops import echec_silencieux

    echec_silencieux.reinitialiser()

    def _boum(cmd, **kw):
        raise OSError("powershell introuvable")

    monkeypatch.setattr(CN.subprocess, "run", _boum)
    assert CN.send_toast("t", "m") is False
    sites = [s["site"] for s in echec_silencieux.resume()["sites"]]
    assert any("send_toast" in s for s in sites)


# ------------------------------------------------------------------ le signal sur disque
def test_le_signal_est_ecrit_et_relisible(_racine):
    chemin = CN.write_crash_signal("perte de flux", exit_code=2, component="collecteur")
    data = json.loads(chemin.read_text(encoding="utf-8"))
    assert data["event"] == "CRASH_OR_HALT"
    assert data["reason"] == "perte de flux"
    assert data["exit_code"] == 2 and data["component"] == "collecteur"
    assert CN.check_crash_signal() == data


def test_l_horodatage_du_signal_est_en_UTC_et_coherent(_racine):
    """Un signal de crash sert a ORDONNER des evenements : un instant naif ne s'ordonne pas."""
    CN.write_crash_signal("x")
    data = CN.check_crash_signal()
    assert data["ts_iso"].endswith("Z")
    assert data["ts_iso"] == time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(data["ts"]))


def test_ts_et_ts_iso_viennent_d_une_SEULE_lecture_d_horloge(monkeypatch, _racine):
    appels = []
    vrai = time.time
    monkeypatch.setattr(CN.time, "time", lambda: (appels.append(1), vrai())[1])
    CN.write_crash_signal("x")
    assert len(appels) == 1


def test_la_raison_est_bornee(_racine):
    CN.write_crash_signal("R" * 5_000)
    assert len(CN.check_crash_signal()["reason"]) == 500


def test_aucun_signal_rend_None_et_pas_un_dictionnaire_vide(_racine):
    """`None` dit « pas de crash ». Un dict vide dirait « un crash sans raison » : faux."""
    assert CN.check_crash_signal() is None


def test_un_signal_illisible_rend_None_sans_lever(_racine):
    dossier = _racine / CN.SIGNAL_DIR
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / CN.SIGNAL_FILE).write_text("{ pas du json", encoding="utf-8")
    assert CN.check_crash_signal() is None


def test_un_signal_qui_n_est_pas_un_objet_rend_None(_racine):
    dossier = _racine / CN.SIGNAL_DIR
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / CN.SIGNAL_FILE).write_text("[1, 2, 3]", encoding="utf-8")
    assert CN.check_crash_signal() is None


def test_effacer_un_signal_absent_ne_leve_pas(_racine):
    CN.clear_crash_signal()
    CN.write_crash_signal("x")
    CN.clear_crash_signal()
    assert CN.check_crash_signal() is None


def test_notify_crash_ecrit_le_signal_meme_si_le_toast_echoue(monkeypatch, _racine):
    """L'ordre compte : la PREUVE sur disque d'abord, le confort visuel ensuite."""
    monkeypatch.setattr(CN, "send_toast", lambda *a, **k: False)
    CN.notify_crash("halt dur", exit_code=3, component="moteur")
    data = CN.check_crash_signal()
    assert data is not None and data["exit_code"] == 3
