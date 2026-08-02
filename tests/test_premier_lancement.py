"""[PORTABILITE item 21] Controles de premier lancement sur PC neuf. Tout injectable -> 0 reseau.
Verifie : OS/arch (INFO hors Windows, ECHEC Windows non-x64), droits d'ecriture reels, chemin
accents/espaces, horloge, port (sonde injectee), reseau/TLS advisory, aucune cle copiee (BLOQUANT),
sessions preservees (jamais supprimees), et la REGENERATION d'identite (purge PID/verrous, machine-id neuf).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import premier_lancement as PL       # noqa: E402
from hl_observer.ops import session_catalog as SC         # noqa: E402
from hl_observer.ops.registre_pids import REGISTRE_RELPATH  # noqa: E402

CMD = (RACINE / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="ignore")


def _session_complete(root: Path, run_id: str) -> None:
    c = SC.CatalogueSession(root, run_id)
    c.demarrer()
    (SC.chemin_session(root, run_id) / "bbo.jsonl").write_text('{"px":1}\n', encoding="utf-8")
    c.enregistrer_source(SC.EntreeSource(source="bbo", chemin="bbo.jsonl", sante="VERTE"))
    c.cloturer(writers_arretes=True)


# ── controles unitaires ──────────────────────────────────────────────────────────────────────
def test_os_arch_info_hors_windows_echec_si_windows_non_x64():
    assert PL.verifier_os_arch(systeme="Linux", machine="x86_64")["statut"] == PL.INFO
    assert PL.verifier_os_arch(systeme="Windows", machine="AMD64")["statut"] == PL.OK
    assert PL.verifier_os_arch(systeme="Windows", machine="x86")["statut"] == PL.ECHEC


def test_droits_ecriture_ok(tmp_path):
    assert PL.verifier_droits_ecriture(tmp_path)["statut"] == PL.OK


def test_chemin_accents_espaces(tmp_path):
    d = tmp_path / "Projet invest é"
    d.mkdir()
    r = PL.verifier_chemin_espaces_accents(d)
    assert r["statut"] == PL.OK and "espace" in r["detail"] and "accent" in r["detail"]


def test_horloge_avert_si_absurde():
    assert PL.verifier_horloge(maintenant_ms=0)["statut"] == PL.AVERT              # avant 2025
    assert PL.verifier_horloge(maintenant_ms=1_735_689_600_000 + 1000)["statut"] == PL.OK
    tres_loin = 1_735_689_600_000 + PL.DERIVE_HORLOGE_MAX_MS + 10
    assert PL.verifier_horloge(maintenant_ms=tres_loin)["statut"] == PL.AVERT      # futur absurde


def test_port_advisory_via_sonde():
    assert PL.verifier_port(sonde=lambda _p: True)["statut"] == PL.OK
    occ = PL.verifier_port(sonde=lambda _p: False)
    assert occ["statut"] == PL.AVERT and "occupe" in occ["detail"]                 # jamais bloquant


def test_reseau_tls_advisory():
    assert PL.verifier_reseau_tls(sonde=None)["statut"] == PL.INFO                 # non sonde
    assert PL.verifier_reseau_tls(sonde=lambda: {"ok": True})["statut"] == PL.OK
    assert PL.verifier_reseau_tls(sonde=lambda: {"ok": False})["statut"] == PL.AVERT


def test_aucune_cle_bloquant(tmp_path):
    assert PL.verifier_aucune_cle(tmp_path)["statut"] == PL.OK
    (tmp_path / "wallet.key").write_text("SECRET", encoding="utf-8")
    r = PL.verifier_aucune_cle(tmp_path)
    assert r["statut"] == PL.ECHEC and "wallet.key" in r["detail"]
    # du code source « private/secret » ne declenche PAS le blocage.
    (tmp_path / "wallet.key").unlink()
    (tmp_path / "private_helpers.py").write_text("x=1", encoding="utf-8")
    assert PL.verifier_aucune_cle(tmp_path)["statut"] == PL.OK


def test_sessions_preservees_comptees(tmp_path):
    _session_complete(tmp_path, "run_a")
    _session_complete(tmp_path, "run_b")
    r = PL.verifier_sessions_preservees(tmp_path)
    assert r["statut"] == PL.OK and "2 session" in r["detail"] and "2 COMPLETE" in r["detail"]


# ── item 10 : espace disque / imports / DLL / manifeste ──────────────────────────────────────
def test_espace_disque(tmp_path):
    assert PL.verifier_espace_disque(tmp_path, min_mo=0)["statut"] == PL.OK
    r = PL.verifier_espace_disque(tmp_path, min_mo=10**9)          # seuil absurde -> AVERT
    assert r["statut"] == PL.AVERT


def test_imports_bloquant(tmp_path):
    assert PL.verifier_imports(("json", "hashlib"))["statut"] == PL.OK
    r = PL.verifier_imports(("module_qui_nexiste_pas_123",))
    assert r["statut"] == PL.ECHEC and "module_qui_nexiste_pas_123" in r["detail"]
    # importateur injectable : simule un echec d'import de dep.
    def _faux(m):
        raise ImportError("simule")
    assert PL.verifier_imports(("numpy",), importateur=_faux)["statut"] == PL.ECHEC


def test_dll_info_hors_windows_et_echec_si_embed_sans_dll(tmp_path):
    assert PL.verifier_dll(tmp_path, systeme="Linux")["statut"] == PL.INFO
    # Windows + dossier python embarque SANS python*.dll -> ECHEC.
    d = tmp_path / "tools" / "python"
    d.mkdir(parents=True)
    (d / "python.exe").write_bytes(b"MZ")
    assert PL.verifier_dll(tmp_path, systeme="Windows", dossier_python=d)["statut"] == PL.ECHEC
    (d / "python314.dll").write_bytes(b"MZ")
    assert PL.verifier_dll(tmp_path, systeme="Windows", dossier_python=d)["statut"] == PL.OK


def test_manifeste_integrite(tmp_path):
    assert PL.verifier_manifeste(tmp_path)["statut"] == PL.INFO      # absent -> INFO
    (tmp_path / "PORTABLE_MANIFEST.json").write_text('{"schema":"x","empreinte_globale":"abc"}',
                                                     encoding="utf-8")
    assert PL.verifier_manifeste(tmp_path)["statut"] == PL.OK
    (tmp_path / "PORTABLE_MANIFEST.json").write_text("{ pas du json", encoding="utf-8")
    assert PL.verifier_manifeste(tmp_path)["statut"] == PL.ECHEC     # present mais corrompu -> ECHEC


def test_regen_purge_caches_compiles_et_status_volatils(tmp_path):
    # item 6 : caches compiles + dumps de statut volatils sont purges.
    (tmp_path / "src" / "pkg" / "__pycache__").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "__pycache__" / "m.pyc").write_bytes(b"x")
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "debug_status_30s.json").write_text('{"p":"C:\\\\old"}', encoding="utf-8")
    res = PL.regenerer_identite(tmp_path, generateur=lambda: "M")
    assert not (tmp_path / "src" / "pkg" / "__pycache__").exists()
    assert not (tmp_path / "runtime" / "debug_status_30s.json").exists()
    assert any("__pycache__" in x for x in res["purges"])


# ── regeneration d'identite (le coeur de l'item 21) ──────────────────────────────────────────
def test_regenere_identite_purge_et_preserve(tmp_path):
    # etat machine-specifique herite d'une archive copiee...
    (tmp_path / REGISTRE_RELPATH).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / REGISTRE_RELPATH).write_text('{"collecteurs": {"bbo": 111}}', encoding="utf-8")
    (tmp_path / "runtime" / "data" / "COURANTE.json").write_text('{"run_id": "vieux"}', encoding="utf-8")
    (tmp_path / "runtime" / "data" / "lanceur_session_marqueur.txt").write_text("x", encoding="utf-8")
    (tmp_path / "instance.lock").write_text("999", encoding="utf-8")             # verrou perime herite
    # ...le verrou d'instance VIVANT du lanceur courant, qui NE DOIT PAS etre purge...
    (tmp_path / "runtime" / "data" / PL.LOCK_INSTANCE_VIVANT).write_text("moi", encoding="utf-8")
    # ...et une session COMPLETE (historique/PnL) qui NE DOIT PAS bouger.
    _session_complete(tmp_path, "run_garde")

    res = PL.regenerer_identite(tmp_path, generateur=lambda: "NEUF123")
    assert res["machine_id"] == "NEUF123"
    assert (tmp_path / PL.MACHINE_ID_RELPATH).read_text(encoding="utf-8") == "NEUF123"
    # identite machine purgee...
    assert not (tmp_path / REGISTRE_RELPATH).exists()
    assert not (tmp_path / "runtime" / "data" / "COURANTE.json").exists()
    assert not (tmp_path / "instance.lock").exists()
    assert "instance.lock" in res["purges"]
    # ...mais le verrou d'instance VIVANT survit (garde anti-double-lancement)...
    assert (tmp_path / "runtime" / "data" / PL.LOCK_INSTANCE_VIVANT).exists()
    assert PL.LOCK_INSTANCE_VIVANT not in " ".join(res["purges"])
    # ...et la session COMPLETE est INTACTE.
    assert SC.CatalogueSession(tmp_path, "run_garde").lire()["statut"] == SC.STATUT_COMPLETE


# ── orchestrateur ─────────────────────────────────────────────────────────────────────────────
def test_orchestrateur_go_sur_pc_sain(tmp_path):
    _session_complete(tmp_path, "run_ok")
    v = PL.verifier_premier_lancement(
        tmp_path, os_info={"systeme": "Windows", "machine": "AMD64"},
        maintenant_ms=1_735_689_600_000 + 1000, sonde_port=lambda _p: True,
        sonde_reseau=lambda: {"ok": True, "detail": "TLS ok"}, generateur_id=lambda: "MID")
    assert v["go"] is True and v["echecs"] == [] and v["machine_id"] == "MID"
    assert (tmp_path / PL.MACHINE_ID_RELPATH).exists()


def test_orchestrateur_no_go_si_cle_presente(tmp_path):
    (tmp_path / "secret.pem").write_text("KEY", encoding="utf-8")
    v = PL.verifier_premier_lancement(tmp_path, os_info={"systeme": "Linux"},
                                      maintenant_ms=1_735_689_600_000 + 1000,
                                      sonde_port=lambda _p: True, generateur_id=lambda: "MID")
    assert v["go"] is False and "aucune_cle" in v["echecs"]


def test_avertissements_ne_bloquent_pas(tmp_path):
    v = PL.verifier_premier_lancement(tmp_path, os_info={"systeme": "Linux"},
                                      maintenant_ms=0,                    # horloge absurde -> AVERT
                                      sonde_port=lambda _p: False,        # port occupe -> AVERT
                                      generateur_id=lambda: "MID")
    assert v["go"] is True                                               # AVERT n'empeche jamais le GO
    assert "horloge" in v["avertissements"] and "port_ui" in v["avertissements"]


def test_cli_json(tmp_path, capsys):
    code = PL.main(["--racine", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["go"] is True and out["machine_id"]


# ── cablage dans le lanceur ───────────────────────────────────────────────────────────────────
def test_lanceur_appelle_premier_lancement_avant_collecteurs():
    assert "premier_lancement" in CMD
    i_pl = CMD.index("premier_lancement")
    i_coll = CMD.index("demarrer_collecteurs", i_pl)
    assert i_pl < i_coll                                                 # item 21 : controle AVANT tout writer
