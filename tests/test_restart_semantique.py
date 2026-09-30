"""AUD-054 — RELANCER sur échec SÉMANTIQUE, pas seulement sur le SILENCE.

La panne du 19/07 était un SILENCE : quatre collecteurs morts, log figé, heartbeat périmé. Le
superviseur relance déjà ce cas (`etat["mort"]`). Mais un collecteur peut être VIVANT — process up,
heartbeat FRAIS — et pourtant SÉMANTIQUEMENT cassé : gap critique, carnet désynchronisé, séquence
exchange invalide, reconnexions en rafale. Ce collecteur ment : il « bat » mais son flux est troué.
Le laisser tourner, c'est réintroduire la maladie du 19/07 sous un déguisement (heartbeat vert).

La santé sémantique EXISTE déjà : `preuve_de_vie` (via `protections.etat_ingestion`) distingue
MARCHE_CALME (0 événement mais collecte OK = SAIN, VERT) de PANNE_TECHNIQUE (gap → NON sain, ROUGE).
On RÉUTILISE ce diagnostic ; on ne le réinvente pas.

Ces trois tests verrouillent la frontière :
  1. MORT (silence)                       -> relancé   (comportement existant PRÉSERVÉ) ;
  2. VIVANT + heartbeat frais + PANNE gap -> relancé   (le nouveau : sémantique, pas seulement silence) ;
  3. VIVANT + heartbeat frais + MARCHE_CALME (0 event, collecte OK) -> JAMAIS relancé.

⚠️ (3) est LE PIÈGE : un marché sans événement est SAIN. Relancer un collecteur en marché calme
serait la panne INVERSE — tuer une source qui va bien. Le test l'interdit explicitement.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from hl_observer.ops import superviseur_collecteurs as SC
from tools.heartbeat_collecteur import battre


# ── Liveness "superviseur" (fraîcheur du fichier de vie) : rend un collecteur NON mort. ──────────────
# allmids-collector : pas de clé heartbeat -> la vie se mesure au LOG. bbo/userfills : clé heartbeat.
def _fichier_frais(root: Path, relpath: str) -> Path:
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    return p


def _core_vivants(root: Path) -> None:
    """Les trois collecteurs CORE VIVANTS au sens superviseur (fichier de vie frais)."""
    _fichier_frais(root, "runtime/logs/allmids-collector.log")   # allmids -> log
    _fichier_frais(root, "runtime/data/bbo_heartbeat.json")      # bbo -> heartbeat superviseur
    _fichier_frais(root, "runtime/data/userfills_live.lock")     # userfills -> heartbeat superviseur


def _vieillir(p: Path, age_s: float) -> None:
    t = time.time() - age_s
    os.utime(p, (t, t))


# ────────────────────────────────────────────────────────────── 1. MORT -> relancé (préservé)

def test_1_collecteur_mort_est_relance(tmp_path):
    """Comportement EXISTANT préservé : un collecteur MORT (log figé au-delà de sa limite) est relancé.
    Ne référence PAS la sémantique -> vert avant ET après le correctif (garde anti-régression)."""
    _core_vivants(tmp_path)
    _vieillir(tmp_path / "runtime/logs/allmids-collector.log", age_s=30 * 60)   # limite 5 min -> MORT
    appels: list[list[str]] = []
    r = SC.verifier_et_relancer(
        tmp_path, profil="core",
        lanceur=lambda cmd, cwd: appels.append(cmd) or True,
    )
    assert r["morts"] == ["allmids-collector"]
    assert r["relances"] == ["allmids-collector"]
    assert len(appels) == 1 and appels[0][6] == "allmids-collector"


# ─────────────────────────────────────────── 2. VIVANT + heartbeat FRAIS mais PANNE gap -> relancé

def test_2_panne_semantique_gap_est_relancee(tmp_path):
    """LE NOUVEAU : bbo est VIVANT (heartbeat frais) mais son flux est TROUÉ (gap critique). Ce n'est
    NI un marché calme NI un silence : `preuve_de_vie` le classe PANNE_TECHNIQUE. Le superviseur DOIT
    relancer — sinon on reçoit exactement la panne du 19/07 déguisée en heartbeat vert."""
    _core_vivants(tmp_path)
    # heartbeat canonique FRAIS (pid du process de test = vivant), flux non vide + horodatage exchange,
    # MAIS gap critique -> VIVANT n'est pas SAIN.
    battre(tmp_path, "bbo-collector", n_ecrites=100,
           dernier_exchange_ts=int(time.time() * 1000) - 500, metriques={"gaps_critiques": 1})
    appels: list[list[str]] = []
    r = SC.verifier_et_relancer(
        tmp_path, profil="core",
        lanceur=lambda cmd, cwd: appels.append(cmd) or True,
    )
    assert r["morts"] == []                        # bbo n'est PAS mort : son heartbeat est frais
    assert r["pannes"] == ["bbo-collector"]        # il est SÉMANTIQUEMENT cassé (gap)
    assert r["relances"] == ["bbo-collector"]      # -> relancé
    assert len(appels) == 1 and appels[0][6] == "bbo-collector"


# ───────────────────────────────────── 3. VIVANT + heartbeat FRAIS + MARCHE_CALME -> JAMAIS relancé

def test_3_marche_calme_ne_relance_JAMAIS(tmp_path):
    """LE PIÈGE. bbo est VIVANT, heartbeat FRAIS, 0 événement mais la COLLECTE fonctionne : c'est un
    MARCHÉ CALME (VERT dans preuve_de_vie), PAS une panne. Le relancer tuerait une source SAINE. Doit
    rester intouché — même effet qu'un collecteur sain."""
    _core_vivants(tmp_path)
    # 0 événement + aucune métrique de qualité dégradée = collecte OK, marché calme (sain).
    battre(tmp_path, "bbo-collector", n_ecrites=0, metriques={})
    appels: list[list[str]] = []
    r = SC.verifier_et_relancer(
        tmp_path, profil="core",
        lanceur=lambda cmd, cwd: appels.append(cmd) or True,
    )
    assert r["morts"] == []
    assert r.get("pannes", []) == []                     # marché calme n'est PAS une panne
    assert "bbo-collector" not in r["relances"]          # source saine : jamais relancée
    assert appels == []
