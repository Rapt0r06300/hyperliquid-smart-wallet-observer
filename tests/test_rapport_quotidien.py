"""RAPPORT QUOTIDIEN (R6) — une page honnête, jamais un plantage, jamais un chiffre orphelin.

Trois exigences testées :
  1. les chiffres du rapport = ceux du LEDGER (pas d'un compteur parallèle) ;
  2. l'absence de données est DITE, pas masquée ;
  3. le générateur ne lève JAMAIS (un rapport qui plante = un matin aveugle).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location(
        "rapport_quotidien", RACINE / "tools" / "rapport_quotidien.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


RQ = _mod()
H = 3_600_000


def _peupler(root: Path, now_ms: int) -> None:
    d = root / "runtime" / "data"
    d.mkdir(parents=True, exist_ok=True)
    # ledger : 1 fermeture recente (-0,16), 1 vieille (-1,00 hors fenetre), 1 gagnante recente
    (d / "carry_paper_ledger.jsonl").write_text("\n".join([
        json.dumps({"kind": "CLOSE", "coin": "PURR", "ts_ms": now_ms - 2 * H,
                    "realized_net_pnl_usdc": -0.16, "reason": "DONNEE_ABSENTE_PROLONGEE"}),
        json.dumps({"kind": "CLOSE", "coin": "HYPE", "ts_ms": now_ms - 30 * 24 * H,
                    "realized_net_pnl_usdc": -1.00, "reason": "VIEILLE_EPOQUE"}),
        json.dumps({"kind": "CLOSE", "coin": "PURR", "ts_ms": now_ms - 1 * H,
                    "realized_net_pnl_usdc": 0.03, "reason": "BASE_CONVERGEE_PREMIUM_CAPTURE"}),
    ]) + "\n", encoding="utf-8")
    (d / "carry_paper_positions.json").write_text(json.dumps({
        "mode": "LIVE", "ouvertes": {"HYPE": {
            "coin": "HYPE", "notional_usdt": 75.0, "levier": 1.5,
            "entry_ts_ms": now_ms - 19 * H, "funding_accrued_usdt": 0.0174}}}),
        encoding="utf-8")
    (d / "dispersion_venues.jsonl").write_text("\n".join(
        json.dumps({"ts": (now_ms - k * H) / 1000.0, "coin": "BTC", "dispersion_bps_h": 0.1})
        for k in range(24)) + "\n", encoding="utf-8")


def test_les_chiffres_du_rapport_VIENNENT_du_ledger(tmp_path):
    now = 1_800_000_000_000
    _peupler(tmp_path, now)
    r = RQ.generer(tmp_path, now_ms=now)
    assert "-0.1600" in r or "-0,16" in r or "-0.16" in r      # la fermeture recente
    assert "DONNEE_ABSENTE_PROLONGEE" in r
    assert "-1.1300" in r, "total historique = -0.16 - 1.00 + 0.03 (fenetre IGNOREE pour lui)"
    assert "Total 24 h : -0.1300" in r, "24 h = -0.16 + 0.03 (la vieille epoque exclue)"
    assert "HYPE" in r and "19.0 h" in r                       # position + age
    assert "23.0 h / 72 h" in r                                # cross-venue en cours


def test_l_absence_de_donnees_est_DITE_pas_masquee(tmp_path):
    r = RQ.generer(tmp_path, now_ms=1_800_000_000_000)
    assert "Aucune fermeture" in r
    assert "Aucune position ouverte" in r
    assert "aucune donnée" in r.lower() or "aucune donnee" in r.lower()


def test_le_generateur_ne_leve_JAMAIS(tmp_path):
    # racine inexistante, fichiers corrompus : le rapport se genere quand meme
    assert isinstance(RQ.generer(tmp_path / "nulle_part"), str)
    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True)
    (d / "carry_paper_ledger.jsonl").write_text("{corrompu", encoding="utf-8")
    r = RQ.generer(tmp_path)
    assert "Rapport quotidien" in r


def test_ecrire_produit_le_fichier_ET_l_archive_datee(tmp_path):
    now = 1_800_000_000_000
    _peupler(tmp_path, now)
    chemin = RQ.ecrire(tmp_path, now_ms=now)
    assert chemin.exists() and chemin.name == "RAPPORT_DU_JOUR.md"
    archives = list((tmp_path / "rapports" / "archive_quotidienne").glob("RAPPORT_*.md"))
    assert len(archives) == 1, "une copie datee pour l'historique"


def test_la_ligne_de_securite_est_TOUJOURS_presente(tmp_path):
    assert "0 ordre réel" in RQ.generer(tmp_path, now_ms=1_800_000_000_000)


# ---------------- #186 (20/07) : PnL des refus — section HEBDO, cache date, jamais bloquante ----

def test_section7_recalcule_quand_le_cache_est_absent_et_ECRIT_le_cache(tmp_path):
    m = _mod()
    lignes = m._sec_pnl_des_refus(tmp_path, now_ms=1_000_000_000_000)
    texte = "\n".join(lignes)
    assert "## 7. PnL des refus" in texte
    # 0 donnee replay -> constat honnete, pas un chiffre
    assert ("Aucun refus mesurable" in texte) or ("indisponible" in texte)
    if "Aucun refus mesurable" in texte:
        assert (tmp_path / m.CACHE_PNL_REFUS).exists(), "le cache hebdo doit etre ecrit"


def test_section7_sert_le_CACHE_frais_sans_recalculer(tmp_path):
    m = _mod()
    now = 2_000_000_000_000
    cache = tmp_path / m.CACHE_PNL_REFUS
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"calcule_ts_ms": now - 3600_000, "resultat": {
        "par_motif": {"EDGE_TROP_FAIBLE": {"n": 4, "mesures": 3, "pnl_simule_usd": -1.25}},
        "non_mesurables": 1, "honnetete": "re-mesurer au replay complet, jamais ouvrir sur ce chiffre"}}),
        encoding="utf-8")
    texte = "\n".join(m._sec_pnl_des_refus(tmp_path, now_ms=now))
    assert "EDGE_TROP_FAIBLE" in texte and "-1.25" in texte
    assert "×1 — comptés, jamais inventés" in texte
    assert "jamais ouvrir sur ce chiffre" in texte
    assert "0.0 j" in texte or "0,0 j" in texte.replace(".", ",") or "il y a" in texte


def test_le_rapport_complet_contient_la_section_7(tmp_path):
    m = _mod()
    texte = m.generer(tmp_path, now_ms=1_000_000_000_000)
    assert "## 7. PnL des refus" in texte
    assert "Sécurité : 0 ordre réel" in texte
