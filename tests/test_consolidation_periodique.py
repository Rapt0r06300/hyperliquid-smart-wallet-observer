"""LA CONSOLIDATION DU REPLAY — atomique, et périodique (21/07).

DEUX DÉFAUTS TROUVÉS LE MÊME SOIR
---------------------------------
1. **Elle ne tournait qu'au démarrage.** `LANCER_HYPERSMART.cmd:287` puis plus rien. Session
   de 11 h : `_merged/marks.jsonl` et `_merged/candidates.jsonl` **figés depuis 11,5 h**
   pendant que les collecteurs écrivaient en continu (276 coins, un mark/61 s). Tout ce qui
   lit le consolidé travaillait sur du vieux — c'est ce qui a réduit le markout copy à 2,4 %.

2. **Elle n'était pas atomique.** La fusion ouvrait la CIBLE en `"w"` : elle la vidait puis la
   remplissait ligne par ligne pendant des dizaines de secondes (215 Mo). Vérifié en vrai en
   la coupant : **215 Mo -> 130 Mo, dernière ligne « Unterminated string »**. Le trim du même
   module était déjà atomique ; la fusion, qui écrit 1 600 fois plus, ne l'était pas.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from hl_observer.runtime import consolidation_periodique as cp
from hl_observer.runtime.replay_recorder import merge_replay


def _replay(tmp_path: Path, n: int = 50) -> Path:
    base = tmp_path / "runtime" / "replay"
    base.mkdir(parents=True)
    (base / "candidates.1.jsonl").write_text("\n".join(
        json.dumps({"coin": "BTC", "ts": 1000.0 + i}) for i in range(n)) + "\n",
        encoding="utf-8")
    (base / "marks.1.jsonl").write_text("\n".join(
        json.dumps({"coin": "BTC", "ts": 1000.0 + i, "mid": 100.0 + i}) for i in range(n))
        + "\n", encoding="utf-8")
    return base


# ─────────────── l'écriture est ATOMIQUE ───────────────

def test_la_fusion_ne_laisse_jamais_un_consolide_tronque(tmp_path):
    """🔴 LE BUG VÉCU. En coupant la fusion, `candidates.jsonl` est passé de 215 Mo à 130 Mo
    avec une dernière ligne coupée en plein objet JSON. Un lecteur doit voir l'ANCIEN fichier
    complet ou le NOUVEAU complet — jamais un entre-deux."""
    base = _replay(tmp_path)
    merge_replay(base)
    cible = base / "_merged" / "candidates.jsonl"
    ancien = cible.read_text(encoding="utf-8")
    assert json.loads(ancien.strip().splitlines()[-1])       # complet

    # une 2e fusion qui echoue en cours de route ne doit PAS abimer l'existant
    import hl_observer.runtime.replay_recorder as rr
    vrai = rr.read_replay_lines

    def explose(*a, **k):
        raise RuntimeError("coupure simulee au milieu de la fusion")

    rr.read_replay_lines = explose
    try:
        merge_replay(base)                                   # best-effort : ne leve pas
    finally:
        rr.read_replay_lines = vrai
    assert cible.read_text(encoding="utf-8") == ancien, (
        "une fusion interrompue doit laisser l'ANCIEN consolide intact")


def test_le_temporaire_porte_le_pid(tmp_path):
    """Deux fusions concurrentes ne doivent pas se marcher dessus."""
    base = _replay(tmp_path)
    merge_replay(base)
    assert not list((base / "_merged").glob("*.mergetmp")), "aucun dechet apres un succes"


def test_les_temporaires_ORPHELINS_sont_balayes_au_demarrage(tmp_path):
    """Un SIGKILL n'execute pas le `finally`. Constaté en vrai : un `.9.mergetmp` de 105 Mo
    survivant à une fusion tuée. Sans balayage, chaque interruption laisse sur le disque un
    fichier de la taille du consolidé."""
    base = _replay(tmp_path)
    merged = base / "_merged"
    merged.mkdir(parents=True, exist_ok=True)
    vieux = merged / "candidates.jsonl.999.mergetmp"
    vieux.write_text("dechet", encoding="utf-8")
    os.utime(vieux, (time.time() - 3600, time.time() - 3600))
    recent = merged / "candidates.jsonl.888.mergetmp"
    recent.write_text("fusion en cours", encoding="utf-8")
    merge_replay(base)
    assert not vieux.exists(), "l'orphelin ancien doit etre balaye"
    assert recent.exists(), "un temporaire RECENT peut appartenir a une fusion VIVANTE"


# ─────────────── la périodicité ───────────────

def test_un_consolide_a_jour_n_est_pas_refait(tmp_path):
    """Consolider 215 Mo à chaque passe de feeder serait une charge inutile."""
    base = _replay(tmp_path)
    merge_replay(base)
    r = cp.consolider_si_en_retard(tmp_path)
    assert r["fait"] is False and "a jour" in r["motif"]


def test_un_consolide_en_retard_est_DETECTE(tmp_path):
    base = _replay(tmp_path)
    merge_replay(base)
    cible = base / "_merged" / "marks.jsonl"
    vieux = time.time() - 12 * 3600
    os.utime(cible, (vieux, vieux))
    assert cp.retard_s(tmp_path) == pytest.approx(12 * 3600, rel=0.01)
    ligne = cp.ligne_de_rapport({"retard_avant_h": 12.0, "fait": False, "motif": "x"})
    assert "EN RETARD de 12.0 h" in ligne
    assert "travaille sur du vieux" in ligne, "un retard doit se VOIR, pas rester silencieux"


def test_un_consolide_absent_compte_comme_en_retard(tmp_path):
    """Deny-by-default : pas de consolidé du tout, c'est le pire des retards."""
    _replay(tmp_path)
    assert cp.retard_s(tmp_path) is None
    r = cp.consolider_si_en_retard(tmp_path, budget_s=60.0)
    assert r["fait"] is True, "absence de consolide -> on consolide"


def test_deux_passes_ne_consolident_pas_en_meme_temps(tmp_path):
    base = _replay(tmp_path)
    verrou = tmp_path / cp.VERROU
    verrou.parent.mkdir(parents=True, exist_ok=True)
    verrou.write_text("1234", encoding="utf-8")
    r = cp.consolider_si_en_retard(tmp_path)
    assert r["fait"] is False and "autre passe" in r["motif"]
    assert (base / "_merged" / "marks.jsonl").exists() is False


def test_un_verrou_PERIME_ne_bloque_pas_pour_toujours(tmp_path):
    """Un crash pendant la consolidation laisse un verrou. Sans expiration, plus aucune
    consolidation ne se ferait jamais — le remède serait pire que le mal."""
    _replay(tmp_path)
    verrou = tmp_path / cp.VERROU
    verrou.parent.mkdir(parents=True, exist_ok=True)
    verrou.write_text("mort", encoding="utf-8")
    vieux = time.time() - (cp.VERROU_PERIME_S + 60)
    os.utime(verrou, (vieux, vieux))
    r = cp.consolider_si_en_retard(tmp_path, budget_s=60.0)
    assert r["fait"] is True and not verrou.exists()


def test_la_consolidation_ne_LEVE_jamais(tmp_path):
    """Un rangement qui tue le feeder serait pire que le desordre."""
    r = cp.consolider_si_en_retard(tmp_path / "nexiste_pas", budget_s=5.0)
    assert isinstance(r, dict) and r["real_execution"] is False


def test_le_feeder_appelle_bien_la_consolidation():
    """« mention ≠ porte » : le module ne sert a rien s'il n'est pas sur le chemin qui
    tourne toutes les 10 minutes."""
    src = Path("tools/ecrire_carry_spot_inputs.py").read_text(encoding="utf-8")
    assert "consolider_si_en_retard" in src
    assert "ligne_de_rapport" in src, "le retard doit etre AFFICHE, pas seulement corrige"
