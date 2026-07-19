"""SUPERVISEUR DES COLLECTEURS — la panne du 19/07 ne doit plus jamais durer 30 minutes.

Contexte : à 15:27 les 4 collecteurs sont morts ensemble (dernier log « code de sortie = 0 »,
morts en plein sommeil). 15 min plus tard le carry refusait tout : INPUTS_SPOT_PERIMES_NO_TRADE.
L'alarme existait (VERIFIER-TOUT section 5) — mais une alarme sans bras ne relance rien.

Ces tests verrouillent les quatre points qui comptent :
  1. la DÉTECTION (log figé ou absent = mort ; log frais = vivant) ;
  2. la RELANCE (bonne commande, mêmes chemins relatifs sans guillemets que le lanceur) ;
  3. le COOLDOWN (pas de mitraillage d'une panne récurrente) ;
  4. le CÂBLAGE (le runtime carry APPELLE le superviseur — mention ≠ porte) et la
     COHÉRENCE registre ↔ LANCER_HYPERSMART.cmd (un collecteur ajouté au lanceur mais
     pas au registre mourrait sans supervision : exactement la panne qu'on vient de payer).
"""
from __future__ import annotations

import ast
import os
import time
from pathlib import Path

from hl_observer.ops import superviseur_collecteurs as SC

RACINE = Path(__file__).resolve().parents[1]


def _log(root: Path, nom: str, *, age_s: float = 0.0) -> Path:
    p = root / "runtime" / "logs" / ("%s.log" % nom)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("passe\n", encoding="utf-8")
    if age_s:
        vieux = time.time() - age_s
        os.utime(p, (vieux, vieux))
    return p


def _tous_vivants(root: Path) -> None:
    for c in SC.REGISTRE:
        _log(root, c["nom"])


# ------------------------------------------------------------------ 1. détection

def test_un_log_FIGE_est_declare_mort(tmp_path):
    _tous_vivants(tmp_path)
    _log(tmp_path, "carry-feeder", age_s=16 * 60)          # limite : 15 min
    morts = [e["nom"] for e in SC.etat_collecteurs(tmp_path) if e["mort"]]
    assert morts == ["carry-feeder"]


def test_un_log_ABSENT_est_mort_aussi(tmp_path):
    """« Jamais démarré » est une mort plus discrète que « mort en route » — pas moins grave."""
    _tous_vivants(tmp_path)
    (tmp_path / "runtime" / "logs" / "marks-collector.log").unlink()
    morts = [e["nom"] for e in SC.etat_collecteurs(tmp_path) if e["mort"]]
    assert morts == ["marks-collector"]


def test_des_logs_frais_ne_declenchent_RIEN(tmp_path):
    """CONTRE-ÉPREUVE anti garde affamé : vivant = on ne touche à rien."""
    _tous_vivants(tmp_path)
    appels: list[list[str]] = []
    r = SC.verifier_et_relancer(tmp_path, lanceur=lambda cmd, cwd: appels.append(cmd) or True)
    assert r["morts"] == [] and r["relances"] == [] and appels == []


# ------------------------------------------------------------------ 2. relance

def test_un_mort_est_RELANCE_avec_la_commande_du_lanceur(tmp_path):
    _tous_vivants(tmp_path)
    _log(tmp_path, "carry-feeder", age_s=16 * 60)
    appels: list[list[str]] = []
    r = SC.verifier_et_relancer(tmp_path, lanceur=lambda cmd, cwd: appels.append(cmd) or True)
    assert r["relances"] == ["carry-feeder"]
    assert len(appels) == 1
    cmd = appels[0]
    # La MÊME forme que LANCER : start "" /b + chemins RELATIFS, AUCUN guillemet ajouté.
    # (Leçon du 19/07 : cmd /c mange la 1re et la dernière quote -> 3 lancements cassés.)
    assert cmd[:5] == ["cmd", "/c", "start", "", "/b"]
    assert cmd[5] == "tools\\boucle_collecteur.cmd"
    assert cmd[6] == "carry-feeder"
    assert cmd[7] == "tools\\ecrire_carry_spot_inputs.py"
    assert cmd[8] == "240"
    assert not any('"' in p for p in cmd), "aucun guillemet : cmd /c les mange par paires"


def test_la_relance_est_JOURNALISEE(tmp_path):
    """Un processus ressuscité en silence serait un mensonge de plus."""
    _tous_vivants(tmp_path)
    _log(tmp_path, "venues-collector", age_s=25 * 60)
    SC.verifier_et_relancer(tmp_path, lanceur=lambda cmd, cwd: True)
    journal = SC._lire_journal(tmp_path)
    e = journal.get("venues-collector") or {}
    assert e.get("derniere_relance_ok") is True
    assert e.get("relances_total") == 1
    assert isinstance(e.get("derniere_relance_ts"), float)


def test_le_lanceur_par_defaut_REFUSE_hors_Windows(tmp_path):
    """Le runtime vit sous Windows ; le sandbox ne doit jamais lancer de vrais processus."""
    if os.name != "nt":
        assert SC._lanceur_windows(["cmd", "/c", "echo"], tmp_path) is False


def test_le_lanceur_reel_REFUSE_une_racine_sans_boucle(tmp_path):
    """🔴 LE POPUP DE L'AUDIT WINDOWS (19/07 16:49) : un appel avec une racine fantaisiste
    (test sans lanceur injecte) faisait un VRAI `start tools\\boucle_collecteur.cmd` depuis
    un dossier ou ce fichier n'existe pas -> boite « Windows ne trouve pas » en plein audit.
    Sous Linux le refus etait silencieux : mes tests sandbox ne pouvaient PAS le voir.
    Regle : pas de tools/boucle_collecteur.cmd sous la racine -> refus, sur TOUTE plateforme."""
    assert SC._lanceur_windows(["cmd", "/c", "start", "", "/b",
                                "tools\\boucle_collecteur.cmd", "x", "y", "1"],
                               tmp_path) is False
    assert SC._lanceur_windows(["cmd"], tmp_path / "inexistante") is False


# ------------------------------------------------------------------ 3. cooldown

def test_pas_de_MITRAILLAGE_dans_le_cooldown(tmp_path):
    """Une panne récurrente doit rester VISIBLE, pas clignoter sous des relances en boucle."""
    _tous_vivants(tmp_path)
    _log(tmp_path, "liq-collector", age_s=30 * 60)
    appels: list[list[str]] = []
    lanceur = lambda cmd, cwd: appels.append(cmd) or True                  # noqa: E731
    t0 = time.time()
    r1 = SC.verifier_et_relancer(tmp_path, maintenant=t0, lanceur=lanceur)
    _log(tmp_path, "liq-collector", age_s=30 * 60)                         # toujours mort
    r2 = SC.verifier_et_relancer(tmp_path, maintenant=t0 + 60, lanceur=lanceur)
    # a t0+601 s, les logs FRAIS de t0 depassent la limite de marks-collector (5 min) : il est
    # legitimement mort lui aussi -- on les rafraichit pour isoler le SEUL effet du cooldown.
    for c in SC.REGISTRE:
        if c["nom"] != "liq-collector":
            _log(tmp_path, c["nom"])
    os_age = SC.COOLDOWN_S + 1
    r3 = SC.verifier_et_relancer(tmp_path, maintenant=t0 + os_age, lanceur=lanceur)
    assert r1["relances"] == ["liq-collector"]
    assert r2["relances"] == [] and r2["en_cooldown"] == ["liq-collector"]
    assert "liq-collector" in r3["relances"]
    assert [c for c in appels if c[6] == "liq-collector"] and len(
        [c for c in appels if c[6] == "liq-collector"]) == 2, "1 relance + 1 apres cooldown"


def test_l_interrupteur_env_coupe_tout(tmp_path, monkeypatch):
    monkeypatch.setenv(SC.ENV_INTERRUPTEUR, "0")
    _tous_vivants(tmp_path)
    _log(tmp_path, "carry-feeder", age_s=60 * 60)
    appels: list[list[str]] = []
    r = SC.verifier_et_relancer(tmp_path, lanceur=lambda cmd, cwd: appels.append(cmd) or True)
    assert r["actif"] is False and appels == []


def test_ne_leve_JAMAIS_meme_si_le_lanceur_explose(tmp_path):
    """Un superviseur qui tue le moteur qu'il protège serait pire que la panne."""
    _tous_vivants(tmp_path)
    _log(tmp_path, "carry-feeder", age_s=60 * 60)
    def bombe(cmd, cwd):
        raise RuntimeError("boum")
    r = SC.verifier_et_relancer(tmp_path, lanceur=bombe)
    assert r["morts"] == ["carry-feeder"] and r["relances"] == []


def test_racine_inexistante_ne_leve_pas(tmp_path):
    r = SC.verifier_et_relancer(tmp_path / "nulle_part")
    assert isinstance(r, dict) and "morts" in r


# ------------------------------------------------------------------ 4. cohérence & câblage

import pytest


@pytest.mark.parametrize("fichier", ["LANCER_HYPERSMART.cmd", "REANIMER-COLLECTEURS.cmd"])
def test_le_REGISTRE_correspond_au_LANCEUR(fichier):
    """CANARI ANTI-DÉRIVE. Un collecteur présent dans le lanceur (ou le bouton de réanimation)
    mais absent du registre mourrait SANS supervision — la panne du 19/07, en silence, pour
    toujours. Les TROIS listes (LANCER, REANIMER, registre) doivent évoluer ENSEMBLE."""
    texte = (RACINE / fichier).read_text(encoding="utf-8", errors="ignore")
    lignes = [l for l in texte.splitlines()
              if "boucle_collecteur.cmd" in l and l.strip().lower().startswith("start")]
    assert len(lignes) == len(SC.REGISTRE), (
        "%s démarre %d collecteur(s), le registre en supervise %d — les listes doivent "
        "évoluer ENSEMBLE" % (fichier, len(lignes), len(SC.REGISTRE)))
    for c in SC.REGISTRE:
        ligne = next((l for l in lignes if " %s " % c["nom"] in l), None)
        assert ligne is not None, "%r est au registre mais pas dans %s" % (c["nom"], fichier)
        assert c["script"].replace("/", "\\") in ligne.replace("/", "\\")
        assert (" %d" % c["intervalle_s"]) in ligne


def test_le_runtime_carry_APPELLE_le_superviseur():
    """MENTION ≠ PORTE. L'import ne suffit pas : on exige l'APPEL dans le module runtime.
    (23/25 gardes « branchés » étaient morts en T3b ; on ne repaye pas cette leçon.)"""
    src = (RACINE / "src" / "hl_observer" / "funding" / "carry_paper_runtime.py"
           ).read_text(encoding="utf-8")
    arbre = ast.parse(src)
    appels = [n for n in ast.walk(arbre)
              if isinstance(n, ast.Call)
              and getattr(n.func, "id", getattr(n.func, "attr", "")) == "verifier_et_relancer"]
    assert appels, "carry_paper_runtime doit APPELER verifier_et_relancer (pas juste l'importer)"


def test_les_limites_sont_plus_larges_que_les_cadences():
    """Un seuil plus court que la cadence déclarerait mort un collecteur en pleine santé —
    et le superviseur relancerait en boucle un processus vivant (double collecte)."""
    for c in SC.REGISTRE:
        assert c["limite_minutes"] * 60.0 > c["intervalle_s"] * 1.5, c["nom"]
