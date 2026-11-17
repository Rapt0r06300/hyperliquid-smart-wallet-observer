"""UN JOURNAL N'EST PAS UNE PREUVE DE VIE — mais un vrai mort doit rester détecté.

D'OÙ VIENT CE TEST (16/11/2026, trouvé par le harnais des .cmd). Le contrôle qualité annonçait
**6 anomalies par passage**, dont :

    !! copy-vault-checkpoints : MORT — journal fige depuis 1320 min ET aucun processus.
       Ce flux est PERDU tant qu'il ne repart pas.

C'était FAUX : au même instant son battement datait de 0 s, sept processus tournaient, et son
ruban `copy_vault_l2_tape.jsonl` venait d'être écrit à la seconde. Deux causes :

1. `_collecteurs_attendus` lisait `REGISTRE` **seul**, alors que `copy-vault-checkpoints` vit dans
   `COLLECTEURS_CAMPAGNE` — exactement le piège déjà corrigé le matin même dans le test du
   lanceur. Son `script` valait `""`, donc aucun processus ne pouvait correspondre : « MORT ».
2. La fraîcheur se jugeait sur le `mtime` d'un journal qui n'est écrit que sur événement.

Six fausses alarmes par passage, c'est la garantie que plus personne ne lit l'alerte — et le jour
où un collecteur meurt vraiment, personne ne le voit. Après correction : **0 anomalie, 20 frais**.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))


def _controle():
    spec = importlib.util.spec_from_file_location(
        "controle_qualite_pour_test", RACINE / "tools" / "controle_qualite_campagne.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("controle_qualite_pour_test", module)
    spec.loader.exec_module(module)
    return module


def test_le_compagnon_de_CAMPAGNE_a_bien_un_script_connu():
    """Sans son script, aucun processus ne peut lui correspondre : il est déclaré MORT à tort."""
    attendus = {nom: script for nom, _cadence, script in _controle()._collecteurs_attendus()}
    assert "copy-vault-checkpoints" in attendus, "le compagnon doit etre attendu par le controle"
    assert attendus["copy-vault-checkpoints"], (
        "script vide : c'est exactement ce qui produisait le faux « MORT » du 16/11")
    assert "checkpoint" in attendus["copy-vault-checkpoints"]


def test_un_BATTEMENT_frais_suffit_meme_si_le_journal_dort(tmp_path):
    """Le battement est écrit POUR dire « je vis » ; le journal, seulement sur événement."""
    controle = _controle()
    maintenant = time.time()
    hb = tmp_path / "runtime" / "research_lab" / "heartbeats"
    hb.mkdir(parents=True)
    logs = tmp_path / "runtime" / "logs"
    logs.mkdir(parents=True)
    for nom, _cadence, _script in controle._collecteurs_attendus():
        (hb / f"{nom}.json").write_text(json.dumps({"ts_ms": int(maintenant * 1000)}),
                                        encoding="utf-8")
        vieux = logs / f"economic-{nom}.log"
        vieux.write_text("rien", encoding="utf-8")
        import os
        os.utime(vieux, (maintenant - 86_400, maintenant - 86_400))   # journal vieux d'un jour
    rapport = controle.controler(tmp_path, maintenant=maintenant)
    assert rapport["collecteurs_morts"] == 0, rapport["anomalies"]
    assert rapport["collecteurs_figes"] == 0, (
        f"un battement frais ne doit produire AUCUNE anomalie : {rapport['anomalies']}")


def test_sans_battement_la_DONNEE_PRODUITE_fait_foi(tmp_path):
    """`userfills-poll` n'a pas de battement : son ruban de 1 051,8 Mo, écrit à la seconde, si."""
    controle = _controle()
    maintenant = time.time()
    (tmp_path / "runtime" / "logs").mkdir(parents=True)
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    rubans = controle._rubans_par_script()
    assert "collecter_userfills_poll.py" in rubans, (
        f"le depot doit declarer ce que produit ce script : {sorted(rubans)[:5]}")
    for _dossier, fichier in rubans["collecter_userfills_poll.py"]:
        (data / fichier).write_text("{}", encoding="utf-8")
    age = controle._age_des_rubans_produits(tmp_path, "tools/collecter_userfills_poll.py", maintenant)
    assert age is not None and age < 60, "un ruban ecrit a l'instant doit compter comme vivant"


def test_un_VRAI_mort_reste_detecte(tmp_path):
    """La correction ne doit pas rendre le contrôle complaisant : sans battement, sans ruban frais
    et sans processus, le collecteur est mort et doit être annoncé."""
    import os

    controle = _controle()
    maintenant = time.time()
    logs = tmp_path / "runtime" / "logs"
    logs.mkdir(parents=True)
    (tmp_path / "runtime" / "research_lab" / "heartbeats").mkdir(parents=True)
    for nom, _cadence, _script in controle._collecteurs_attendus():
        vieux = logs / f"economic-{nom}.log"
        vieux.write_text("rien", encoding="utf-8")
        os.utime(vieux, (maintenant - 86_400, maintenant - 86_400))
    rapport = controle.controler(tmp_path, maintenant=maintenant)
    assert rapport["collecteurs_frais"] == 0
    assert rapport["anomalies"], "un collecteur sans aucun signe de vie doit faire une anomalie"
    assert rapport["collecteurs_morts"] + rapport["collecteurs_figes"] > 0


def test_les_rubans_declares_viennent_du_depot_et_non_d_une_liste_tenue_a_la_main():
    controle = _controle()
    rubans = controle._rubans_par_script()
    assert len(rubans) >= 8, f"declaration suspecte : {len(rubans)} scripts"
    for script, paires in rubans.items():
        assert script.endswith(".py"), script
        for dossier, fichier in paires:
            assert fichier and "*" not in fichier
