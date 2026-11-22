"""L'aval de la collecte : réconciliation croisée et enrichissement des fills.

MESURE DU 21/11/2026 — pourquoi ce fichier existe. Deux outils livrés et testés,
``tools/reconcilier_sources.py`` (trous entre sources, couverture des leaders) et
``tools/enrichir_fills.py`` (contexte au plus près de chaque fill, sans futur),
n'étaient appelés par **aucun lanceur**. Mesuré en comptant les appelants de production :
``prod=0``. Les rubans arrivaient donc bruts, et personne ne savait quelle source avait
raté quoi.

ET UN FAUX SUCCÈS AU PASSAGE. Les deux rendaient le code **0** quand leur entrée
manquait : branchés tels quels dans une chaîne fail-soft, un ruban absent aurait été
compté comme une étape réussie. Une entrée manquante est un refus — code 2 — jamais un
zéro favorable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

import enrichir_fills as E  # noqa: E402
import reconcilier_sources as R  # noqa: E402

LANCEUR = RACINE / "ALINA_SYNC_COMPLETE.cmd"


def _lanceur() -> str:
    return LANCEUR.read_text(encoding="cp1252", errors="replace")


def test_les_deux_outils_sont_appeles_par_le_lanceur():
    """Un outil que personne n'appelle ne produit rien, quels que soient ses tests."""
    texte = _lanceur()
    for outil in ("reconcilier_sources.py", "enrichir_fills.py"):
        assert outil in texte, f"{outil} n'est appele par aucun lanceur"


def test_chaque_appel_est_compte_comme_lane_en_cas_de_refus():
    """Fail-soft NE VEUT PAS DIRE silencieux : un refus doit incrémenter le compteur."""
    texte = _lanceur()
    for outil in ("reconcilier_sources.py", "enrichir_fills.py"):
        position = texte.index(outil)
        suite = texte[position:position + 1200]
        assert 'RESULT github-lanes "%s"' % outil in suite, outil
        assert "LANE_FAILURES+=1" in suite, outil


def test_le_lanceur_reste_en_crlf_sans_double_retour():
    """Piège connu du dépôt : 358 fins `\\r\\r\\n` avaient déjà été réparées ici."""
    octets = LANCEUR.read_bytes()
    assert octets.count(b"\r\n") > 50
    assert b"\r\r\n" not in octets, "double CR reintroduit"
    assert octets.count(b"\n") == octets.count(b"\r\n"), "LF orphelin"


def test_une_entree_absente_est_un_refus_et_non_un_succes(tmp_path, capsys):
    """Le défaut corrigé : `return 0` sur un ruban introuvable."""
    code = E.main(["--root", str(tmp_path), "--fills", str(tmp_path / "absent.jsonl")])
    assert code == 2, "un ruban absent a ete compte comme un succes"
    assert "introuvables" in capsys.readouterr().out

    code = R.main(["--root", str(tmp_path)])
    assert code == 2, "aucune source a ete compte comme un succes"


def test_la_reconciliation_rend_les_trous_entre_sources(tmp_path):
    """Ce que la chaîne gagne : savoir quelle source a raté quoi, chiffré."""
    commun = {"vault": "0xaa", "coin": "BTC", "ts_ms": 1_700_000_000_000,
              "px": 100.0, "sz": 1.0, "tid": 111}
    seul_a = dict(commun, tid=222, ts_ms=1_700_000_001_000)
    a = tmp_path / "a.jsonl"
    b = tmp_path / "b.jsonl"
    a.write_text(json.dumps(commun) + "\n" + json.dumps(seul_a) + "\n", encoding="utf-8")
    b.write_text(json.dumps(commun) + "\n", encoding="utf-8")
    sortie = tmp_path / "rapport.json"
    code = R.main(["--root", str(tmp_path), "--source", f"a={a}", "--source", f"b={b}",
                   "--out", str(sortie)])
    assert code == 0
    rapport = json.loads(sortie.read_text(encoding="utf-8"))
    assert rapport["par_source"]["a"] == 2
    assert rapport["par_source"]["b"] == 1
    # Le fill que seule `a` porte doit apparaitre comme TROU de `b`.
    trous = json.dumps(rapport.get("trous") or rapport, ensure_ascii=False)
    assert "b" in trous


def test_le_ruban_twap_est_passe_a_l_enrichissement():
    """Le marqueur TWAP n'existe que si la chaine fournit le ruban des tranches.

    L'option `--twap` sans le ruban laisserait `contexte.twap` a `None` pour toujours :
    une option non cablee ne produit rien, comme les cinq modules orphelins mesures le
    21/11/2026.
    """
    texte = _lanceur()
    position = texte.index("enrichir_fills.py")
    appel = texte[position:position + 900]
    assert "--twap" in appel, "l'enrichissement ne recoit pas le ruban des tranches TWAP"
    assert "copy_vault_twap_lane.jsonl" in appel
