"""ANTI-ORPHELIN (21/07) — « Q, et même la croix, doivent correctement terminer la session ».

Le bug : le handler de Q tuait le moteur mais pas les 6 boucles de collecteurs (lancées par
LANCER, invisibles pour lui) → orphelines, puis DOUBLÉES à la relance. Deux couches :
  * couche 1 (ps1) : Q tue les boucles par ligne de commande, en arbre ;
  * couche 2 (ce garde, appelé à CHAQUE passe) : une boucle s'arrête seule si le lanceur a
    changé de session (marqueur) ou si le moteur est silencieux 20 min — couvre la croix,
    les crashs, les kills brutaux. Les collecteurs suivent la vie du moteur, par principe.
"""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "collecteur_doit_vivre", RACINE / "tools" / "collecteur_doit_vivre.py")
cdv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cdv)


def _marqueur(root: Path, contenu: str, age_s: float = 0.0) -> Path:
    p = root / "runtime" / "data" / "lanceur_session_marqueur.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contenu, encoding="utf-8")
    if age_s:
        import os
        os.utime(p, (time.time() - age_s, time.time() - age_s))
    return p


def _heartbeat(root: Path, age_s: float) -> None:
    import os
    p = root / "runtime" / "data" / "carry_hype_paper_decisions.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}\n", encoding="utf-8")
    os.utime(p, (time.time() - age_s, time.time() - age_s))


def test_nouvelle_session_lanceur_la_boucle_perimee_s_arrete(tmp_path):
    """LE doublon tué : relance -> nouveau marqueur -> la vieille boucle se voit périmée."""
    _marqueur(tmp_path, "session-B")
    _heartbeat(tmp_path, age_s=10)                      # moteur vivant, peu importe :
    vivre, motif = cdv.doit_vivre("session-A", tmp_path)
    assert vivre is False and "NOUVELLE_SESSION" in motif


def test_moteur_vivant_et_meme_session_la_boucle_vit(tmp_path):
    _marqueur(tmp_path, "session-A")
    _heartbeat(tmp_path, age_s=60)
    assert cdv.doit_vivre("session-A", tmp_path) == (True, "")


def test_moteur_silencieux_20min_la_boucle_s_arrete_seule_la_croix_est_couverte(tmp_path):
    """La croix / un crash ne préviennent personne : le silence du moteur suffit."""
    _marqueur(tmp_path, "session-A", age_s=3600)        # session vieille d'une heure
    _heartbeat(tmp_path, age_s=25 * 60)                 # plus un signe depuis 25 min
    vivre, motif = cdv.doit_vivre("session-A", tmp_path)
    assert vivre is False and "MOTEUR_SILENCIEUX" in motif


def test_grace_de_demarrage_le_moteur_qui_chauffe_n_est_pas_tue(tmp_path):
    """Session toute neuve : le moteur n'a pas encore écrit -> on patiente (marqueur récent)."""
    _marqueur(tmp_path, "session-A")                    # marqueur frais = lanceur vient de partir
    assert cdv.doit_vivre("session-A", tmp_path)[0] is True


def test_marqueur_absent_compat_ancienne_session_le_heartbeat_decide(tmp_path):
    _heartbeat(tmp_path, age_s=60)
    assert cdv.doit_vivre("", tmp_path)[0] is True      # vivant
    _heartbeat(tmp_path, age_s=25 * 60)
    assert cdv.doit_vivre("", tmp_path)[0] is False     # silencieux -> stop


def test_le_cablage_existe_boucle_lanceur_et_handler_Q():
    """Mention ≠ porte : le garde doit être APPELÉ par la boucle, le marqueur ÉCRIT par le
    lanceur, et Q doit tuer les boucles par ligne de commande."""
    boucle = open(str(RACINE / "tools" / "boucle_collecteur.cmd"), encoding="utf-8",
                  errors="replace").read()
    lanceur = open(str(RACINE / "LANCER_HYPERSMART.cmd"), encoding="utf-8",
                   errors="replace").read()
    ps1 = open(str(RACINE / "tools" / "start_hypersmart_simulation.ps1"), encoding="utf-8",
               errors="replace").read()
    assert "collecteur_doit_vivre.py" in boucle and "arret propre anti-orphelin" in boucle
    assert "lanceur_session_marqueur.txt" in boucle
    assert "lanceur_session_marqueur.txt" in lanceur
    assert "boucle_collecteur" in ps1 and "Stopping collector loop tree" in ps1
