"""VÉRIFICATEUR OOS SHADOW (rectif Flo 25/07) — read-only, forward-only, fenêtres figées, one-shot.

On teste sur données SYNTHÉTIQUES (tape shadow_l2_v3 + ledger) : jointure par metaorder_id, exclusion
forward-only (avant t_prereg), exclusion des non-éligibles / OFI non mesurable / ledger-only, fenêtre A=30,
embargo 5 min, fenêtre B=30 (les slices dans l'embargo sont exclues), compteurs seuls tant que B<30,
génération one-shot du rapport + verrou .done, et AUCUNE promotion si l'IC bas ≤ 0. Aucun réseau.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

# import du script tools/ par chemin (pas un package)
_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("verif_checkpoint_oos_shadow",
                                               _ROOT / "tools" / "verif_checkpoint_oos_shadow.py")
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)

T0 = 1_000_000_000_000


def _tape(mid, t, *, ofi_statut="OK", ofi=1.0, lat=300.0, book_dt=100):
    return {"schema_version": "shadow_l2_v3", "type": "fill", "metaorder_id": mid, "coin": "SOL",
            "vault": "0xV", "sens": 1, "fill_exchange_time": t, "book_exchange_time": t + book_dt,
            "latence_pipeline_ms": lat, "ofi_statut": ofi_statut, "ofi_top5": ofi,
            "entree": {"bids": [[100.0, 60.0, 3], [99.9, 60.0, 2]], "asks": [[100.1, 60.0, 3], [100.2, 60.0, 2]]}}


def _ledger(mid, *, pnl, alpha=None, stade="CONTINUATION", taker="taker"):
    return {"metaorder_id": mid, "stade": stade, "maker_taker": taker, "sens": 1, "vault": "0xV",
            "coin": "SOL", "taille_usd": 500.0, "taille_relative": 0.02, "cout_ar_bps": 9.0,
            "cout_source": "L2", "is_twap": False, "jour": "2026-07-25", "horizon_ms": 300000.0,
            "pnl_net_bps": pnl, "alpha_vs_marche_bps": (alpha if alpha is not None else pnl)}


def _ecrire(root: Path, tape_lignes, ledger_lignes):
    d = root / "runtime" / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "metaorder_l2_tape.jsonl").write_text("\n".join(json.dumps(x) for x in tape_lignes), encoding="utf-8")
    (d / "metaorder_shadow_ledger.jsonl").write_text("\n".join(json.dumps(x) for x in ledger_lignes), encoding="utf-8")


def _jeu_complet():
    """30 (A) + 3 (dans l'embargo, exclus de B) + 30 (B) éligibles, + 4 cas à exclure. IC ~0 → non-promotion."""
    tape, led = [], []
    ids_A, ids_B = [], []
    def ajoute(mid, t, pnl):
        tape.append(_tape(mid, t)); led.append(_ledger(mid, pnl=pnl))
    # fenêtre A : i=0..29 espacés de 10 s, après t_prereg
    for i in range(30):
        mid = f"mo-A{i:02d}"; ids_A.append(mid); ajoute(mid, T0 + 10_000 + i * 10_000, 2.0 if i % 2 else -2.0)
    # 3 métaordres DANS l'embargo (> A_fin mais < A_fin+5min) -> exclus de B
    for k in range(3):
        ajoute(f"mo-E{k}", T0 + 310_000 + k * 10_000, 1.0)
    # fenêtre B : j=0..29 après l'embargo (A_fin=T0+300000 ; seuil=T0+600000)
    for j in range(30):
        mid = f"mo-B{j:02d}"; ids_B.append(mid); ajoute(mid, T0 + 610_000 + j * 10_000, 2.0 if j % 2 else -2.0)
    # cas à EXCLURE :
    tape.append(_tape("mo-old", T0 - 50_000)); led.append(_ledger("mo-old", pnl=5.0))          # avant t_prereg
    tape.append(_tape("mo-nonelig", T0 + 20_000, lat=5000.0)); led.append(_ledger("mo-nonelig", pnl=5))  # latence>plafond
    tape.append(_tape("mo-noofi", T0 + 20_000, ofi_statut="OFI_NON_MESURABLE")); led.append(_ledger("mo-noofi", pnl=5))
    led.append(_ledger("mo-ledgeronly", pnl=5.0))                                                # pas de tape -> exclu
    return tape, led, ids_A, ids_B


def test_pipeline_complet_forward_embargo_oneshot(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path)); monkeypatch.setenv("HOME", str(tmp_path))
    # Never open a real system-modal MessageBox during an automated Windows
    # run.  The durable alert files and one-shot lock remain exercised below.
    monkeypatch.setattr(V, "_fenetre_et_son", lambda *_args, **_kwargs: "affichee")
    repo = tmp_path / "repo"                                          # racine isolée -> Bureau = repo.parent = tmp_path
    tape, led, ids_A, ids_B = _jeu_complet()
    _ecrire(repo, tape, led)
    sortie = repo / V.SORTIE_REL
    V.assurer_preregistration(sortie, t_prereg_ms=T0)                # fige t_prereg AVANT

    # 1) chemin NON SURVEILLÉ (Planificateur Windows) : compteurs + sentinelle + ALERTE, AUCUN IC
    c = V.executer(repo)
    assert c["n_population_eligible"] == 63                          # 30 A + 3 embargo + 30 B (exclus non comptés)
    assert c["nA"] == 30 and c["A_complete"] is True
    assert c["nB"] == 30 and c["B_complete"] is True and c["pret_pour_rapport"] is True
    assert c["sentinelle"] == "creee"
    assert (sortie / "status.json").exists()
    assert (sortie / "CHECKPOINT_OOS_ATTEINT.txt").exists()          # sentinelle runtime (conservée)
    assert not (sortie / "RAPPORT_OOS_SHADOW_PRELIMINAIRE.md").exists()   # PAS d'analyse dans ce chemin
    # ALERTE one-shot : fichier Bureau très visible + verrou
    assert c["alerte"] == "alertee"
    bureau_file = tmp_path / "CHECKPOINT_OOS_ATTEINT.txt"
    assert bureau_file.exists() and "checkpoint_id" in bureau_file.read_text(encoding="utf-8")
    assert (sortie / ".alerte.done").exists()
    bornes = json.loads((sortie / "bornes_figees.json").read_text(encoding="utf-8"))
    assert bornes["A_metaorder_ids"] == ids_A and bornes["B_metaorder_ids"] == ids_B  # A/B disjoints, ordre chrono
    assert bornes["B_debut_ts"] >= bornes["B_seuil_ts"]             # embargo respecté
    assert "mo-old" not in ids_A and "mo-old" not in ids_B          # forward-only
    # idempotence : sentinelle ET alerte ne se redéclenchent pas
    c2 = V.executer(repo)
    assert c2["sentinelle"] == "deja_presente" and c2["alerte"] == "deja_alertee"

    # 2) mode --rapport (Claude uniquement) : analyse sur bornes figées
    rap = V.generer_rapport(repo)
    assert (sortie / "RAPPORT_OOS_SHADOW_PRELIMINAIRE.md").exists() and (sortie / ".rapport.done").exists()
    assert rap["pnl_net_bps"]["B_ic"]["n_clusters"] == 30            # unité = métaordre (30), pas les slices
    assert rap["verdict"] == "PAS_DE_PROMOTION_IC_BAS_NON_POSITIF"  # IC ~0 symétrique -> aucune promotion
    assert V.generer_rapport(repo).get("deja_genere") is True       # one-shot


def test_test_notification_ne_cree_ni_sentinelle_ni_compteur(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path)); monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(V, "_fenetre_et_son", lambda *_args, **_kwargs: "affichee")
    etat = V.tester_notification()                                  # affichage seul (hors Windows -> 'non_windows')
    assert etat in ("non_windows", "affichee", "erreur")            # ne casse jamais
    # AUCUN fichier créé : ni sentinelle Bureau, ni sortie, ni verrou, ni status
    assert not (tmp_path / "CHECKPOINT_OOS_ATTEINT.txt").exists()
    assert not (tmp_path / V.SORTIE_REL / "CHECKPOINT_OOS_ATTEINT.txt").exists()
    assert not (tmp_path / V.SORTIE_REL / ".alerte.done").exists()
    assert not (tmp_path / V.SORTIE_REL / "status.json").exists()


def test_compteurs_seuls_avant_B_complet(tmp_path):
    # 5 métaordres éligibles seulement -> A incomplète, aucun rapport, aucun IC calculé
    tape, led = [], []
    for i in range(5):
        mid = f"mo-{i}"; tape.append(_tape(mid, T0 + 10_000 + i * 10_000))
        led.append(_ledger(mid, pnl=3.0))
    _ecrire(tmp_path, tape, led)
    sortie = tmp_path / V.SORTIE_REL
    V.assurer_preregistration(sortie, t_prereg_ms=T0)
    c = V.executer(tmp_path)
    assert c["nA"] == 5 and c["A_complete"] is False and c["pret_pour_rapport"] is False
    assert not (sortie / "RAPPORT_OOS_SHADOW_PRELIMINAIRE.md").exists()
    assert (sortie / "status.json").exists()                        # compteurs écrits


def test_preregistration_immuable_et_hash_stable(tmp_path):
    sortie = tmp_path / V.SORTIE_REL
    p1 = V.assurer_preregistration(sortie, t_prereg_ms=T0)
    p2 = V.assurer_preregistration(sortie, t_prereg_ms=999)         # ignoré : déjà écrite
    assert p1["t_prereg_ms"] == p2["t_prereg_ms"] == T0             # immuable
    assert p1["checkpoint_hash"] == p2["checkpoint_hash"]
    assert p1["checkpoint_id"].startswith("ckpt-oos-shadow-")
    # hash déterministe = fonction pure de la spec canonique
    assert V.checkpoint_hash(V._spec_canonique(T0)) == p1["checkpoint_hash"]
