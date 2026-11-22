"""EXERCER la chaine, pas verifier qu'elle existe — et refuser les preuves VIDES.

POURQUOI CET EXERCICE EXISTE. Une premiere validation etait STATIQUE : existence des
modules, appel par un lanceur reel, presence des artefacts. Elle a trouve un vrai defaut
(`avancement_rattrapage.py` appele par PERSONNE), mais elle ne prouve pas qu'un maillon
FONCTIONNE : un module cable peut echouer, perdre des lignes, ou ecrire un fichier vide
sans que personne ne le voie.

MESURE REELLE DU 22/11/2026, sur 120 000 lignes par ruban prises dans les rubans REELS :

```
reconciliation     1,4 s   RSS   471 Mo
enrichissement     3,6 s   RSS   761 Mo   120 000 -> 120 000 lignes   (zero perte)
certification     16,6 s   RSS    66 Mo   3 shards
relecture labo             239 973 horodatages / 229 coins
REPRISE : coupee en vol a 2,5 s sur 16,6  ->  3 shards contre 3 : IDENTIQUE
```

CE QUE CES TESTS VERROUILLENT, et c'est le plus important : **une preuve vide doit etre
refusee**. Au premier essai (3 000 lignes), la certification finissait en 1,0 s, AVANT la
coupure a 2,0 s : rien n'etait interrompu, et le verdict << IDENTIQUE >> etait vrai mais
VIDE. Une preuve vide est pire qu'une absence de preuve, parce qu'elle rassure. L'outil rend
donc `REPRISE_NON_EXERCEE` quand il n'a rien coupe.

Ces tests n'exercent PAS la chaine (ce serait long et lourd) : ils verrouillent les regles
de verdict, qui sont pures. L'exercice lui-meme se lance a la main, borne.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

import exercer_chaine_reelle as EX  # noqa: E402


def _index(dossier: Path, shards: int) -> Path:
    cible = dossier / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(json.dumps({"shards": [{"i": i} for i in range(shards)]}),
                     encoding="utf-8")
    return cible


# ------------------------------------------------- la preuve VIDE est refusee
def test_une_REPRISE_NON_EXERCEE_n_est_jamais_declaree_IDENTIQUE(tmp_path, monkeypatch):
    """Le defaut exact : rien d'interrompu, mais un verdict rassurant."""
    a, b = tmp_path / "continue", tmp_path / "reprise"
    for d in (a, b):
        d.mkdir(parents=True)
    _index(a, 3)
    _index(b, 3)

    # On simule : le processus finit AVANT la coupure, donc rien n'est interrompu.
    monkeypatch.setattr(EX, "preparer_echantillon", lambda *a, **k: {"rubans": [],
                                                                     "lignes_totales": 0})
    monkeypatch.setattr(EX, "lancer", lambda *a, **k: {"etape": "x", "etat": "OK"})

    class _ProcFini:
        pid = 1

        def poll(self):
            return 0                 # deja termine : rien a interrompre

        def terminate(self):
            raise AssertionError("on ne doit pas tuer un process deja fini")

    monkeypatch.setattr(EX.subprocess, "Popen", lambda *a, **k: _ProcFini())
    monkeypatch.setattr(EX.time, "sleep", lambda _s: None)

    verdict = EX.exercer_la_reprise(tmp_path, a, b, lignes=10, coupure_s=0.2)
    assert verdict["interrompu_en_vol"] is False
    assert verdict["verdict"] == "REPRISE_NON_EXERCEE", (
        "un verdict IDENTIQUE sans interruption est une preuve VIDE")


def test_une_PERTE_apres_reprise_est_nommee(tmp_path, monkeypatch):
    """Moins de shards apres reprise : la reprise a perdu des donnees."""
    a, b = tmp_path / "continue", tmp_path / "reprise"
    for d in (a, b):
        d.mkdir(parents=True)
    _index(a, 10)
    _index(b, 7)
    monkeypatch.setattr(EX, "preparer_echantillon", lambda *a, **k: {})
    monkeypatch.setattr(EX, "lancer", lambda *a, **k: {"etape": "x", "etat": "OK"})

    class _ProcVivant:
        pid = 1
        _appels = 0

        def poll(self):
            _ProcVivant._appels += 1
            return None if _ProcVivant._appels < 3 else 0

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(EX.subprocess, "Popen", lambda *a, **k: _ProcVivant())
    monkeypatch.setattr(EX.time, "sleep", lambda _s: None)
    verdict = EX.exercer_la_reprise(tmp_path, a, b, lignes=10, coupure_s=0.2)
    assert verdict["interrompu_en_vol"] is True
    assert verdict["verdict"] == "PERTE_APRES_REPRISE"


def test_une_DUPLICATION_apres_reprise_est_nommee(tmp_path, monkeypatch):
    """Plus de shards apres reprise : la reprise a duplique — aussi grave qu'une perte."""
    a, b = tmp_path / "continue", tmp_path / "reprise"
    for d in (a, b):
        d.mkdir(parents=True)
    _index(a, 7)
    _index(b, 10)
    monkeypatch.setattr(EX, "preparer_echantillon", lambda *a, **k: {})
    monkeypatch.setattr(EX, "lancer", lambda *a, **k: {"etape": "x", "etat": "OK"})

    class _P:
        pid = 1
        n = 0

        def poll(self):
            _P.n += 1
            return None if _P.n < 3 else 0

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(EX.subprocess, "Popen", lambda *a, **k: _P())
    monkeypatch.setattr(EX.time, "sleep", lambda _s: None)
    assert EX.exercer_la_reprise(tmp_path, a, b, lignes=10,
                                 coupure_s=0.2)["verdict"] == "DUPLICATION_APRES_REPRISE"


# ------------------------------------------------- l'echantillon est BORNE et reel
def test_l_echantillon_est_BORNE_et_pris_en_TETE(tmp_path):
    """Prendre la QUEUE melangerait des fills sans leurs carnets : la causalite exige
    l'ordre chronologique, donc la tete du fichier."""
    source = tmp_path / "runtime" / "data"
    source.mkdir(parents=True)
    ruban = source / "vault_fills_live.jsonl"
    ruban.write_text("".join(f'{{"n":{i}}}\n' for i in range(500)), encoding="utf-8")
    atelier = tmp_path / "atelier"
    bilan = EX.preparer_echantillon(tmp_path, atelier, lignes=50)
    copie = atelier / "runtime" / "data" / "vault_fills_live.jsonl"
    lignes = copie.read_text(encoding="utf-8").splitlines()
    assert len(lignes) == 50
    assert json.loads(lignes[0])["n"] == 0, "l'echantillon doit partir du DEBUT"
    assert any(r["etat"] == "COPIE" for r in bilan["rubans"])


def test_un_ruban_SOURCE_ABSENTE_est_dit_et_pas_compte_comme_copie(tmp_path):
    bilan = EX.preparer_echantillon(tmp_path, tmp_path / "atelier", lignes=10)
    etats = {r["ruban"]: r["etat"] for r in bilan["rubans"]}
    assert set(etats.values()) == {"SOURCE_ABSENTE"}
    assert bilan["lignes_totales"] == 0


# ------------------------------------------------- le comptage des lignes
def test_le_comptage_des_lignes_rend_moins_un_si_illisible(tmp_path):
    """`-1` dit << je n'ai pas su lire >> ; un `0` ferait croire a un fichier vide."""
    assert EX._compter_lignes(tmp_path / "absent.jsonl") == -1
    present = tmp_path / "present.jsonl"
    present.write_text("a\nb\nc\n", encoding="utf-8")
    assert EX._compter_lignes(present) == 3
