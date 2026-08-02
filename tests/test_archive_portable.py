"""[PORTABILITE items 20 & 22] Archive portable + re-verification. Tout est teste sur un projet
SYNTHETIQUE (aucun reseau, aucun Windows requis) : SQLite WAL reel, exclusions, manifeste SHA-256,
refus des sessions ACTIVE / writers vivants, neutralisation des chemins absolus, detection de
falsification a la re-verification. Le .cmd est verifie par test_creer_archive_cmd.py.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import zipfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import archive_portable as AP        # noqa: E402
from hl_observer.ops import session_catalog as SC         # noqa: E402
from hl_observer.ops.registre_pids import REGISTRE_RELPATH  # noqa: E402

HORLOGE = lambda: 1_700_000.0                              # noqa: E731 — deterministe


# ── fabrique de projet synthetique ───────────────────────────────────────────────────────────
def _registre_arrete(root: Path) -> None:
    """Registre PID present mais SANS aucun writer vivant -> preuve d'arret (fail-closed satisfait)."""
    p = root / REGISTRE_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"collecteurs": {}}), encoding="utf-8")


def _session_complete(root: Path, run_id: str) -> None:
    cat = SC.CatalogueSession(root, run_id)
    cat.demarrer()
    d = SC.chemin_session(root, run_id)
    (d / "bbo.jsonl").write_text('{"px":1}\n', encoding="utf-8")
    cat.enregistrer_source(SC.EntreeSource(source="bbo", chemin="bbo.jsonl", sante="VERTE"))
    cat.cloturer(writers_arretes=True)


def _projet(root: Path) -> None:
    (root / "runtime" / "data" / "sessions").mkdir(parents=True, exist_ok=True)
    _registre_arrete(root)
    _session_complete(root, "run_ok")
    # fichiers a conserver
    (root / "LANCER_HYPERSMART.cmd").write_text('cd /d "%~dp0"\n', encoding="utf-8")
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    # fichiers a EXCLURE (item 20.4)
    (root / REGISTRE_RELPATH).parent.mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "data" / "lanceur_session_marqueur.txt").write_text("x", encoding="utf-8")
    (root / "instance.lock").write_text("1234", encoding="utf-8")
    (root / "trace.log").write_text("bla", encoding="utf-8")
    (root / "__pycache__").mkdir(exist_ok=True)
    (root / "__pycache__" / "z.pyc").write_text("x", encoding="utf-8")
    (root / "transport.bundle").write_text("x", encoding="utf-8")


def _sqlite_avec_wal(root: Path) -> Path:
    base = root / "runtime" / "data" / "marche.sqlite3"
    base.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(base))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t(x INTEGER)")
    con.executemany("INSERT INTO t VALUES(?)", [(i,) for i in range(50)])
    con.commit()
    con.close()
    return base


# ── exclusions (items 20.4/20.5) ─────────────────────────────────────────────────────────────
def test_exclusions_et_conservation(tmp_path):
    _projet(tmp_path)
    inclus, exclus = AP.lister_pour_archive(tmp_path)
    assert "LANCER_HYPERSMART.cmd" in inclus and "src/app.py" in inclus
    assert "runtime/data/sessions/run_ok/bbo.jsonl" in inclus       # session conservee (item 20.5)
    joint = " ".join(exclus)
    assert REGISTRE_RELPATH.as_posix() in exclus                    # PID exclu
    assert "runtime/data/lanceur_session_marqueur.txt" in exclus    # marqueur machine exclu
    assert "instance.lock" in exclus and "trace.log" in exclus and "transport.bundle" in exclus
    assert "z.pyc" in joint                                          # __pycache__ exclu


def test_est_exclu_regles():
    assert AP.est_exclu("runtime/data/lanceur_pids.json")
    assert AP.est_exclu("x/y/.git/config") and AP.est_exclu("a.lock") and AP.est_exclu("b/c.tmp")
    assert AP.est_exclu("db.sqlite3-wal") and AP.est_exclu("db.sqlite3-shm")
    assert not AP.est_exclu("src/app.py") and not AP.est_exclu("runtime/data/sessions/r/bbo.jsonl")


def test_aucune_cle_dans_archive(tmp_path):
    # item 21 : matiere de cle EXCLUE par extension, mais le code source « private/secret » RESTE.
    for cle in ("wallet.key", "cert.pem", "id.p12", "backup.pfx", "phrase.mnemonic", ".env", ".env.local"):
        assert AP.est_exclu(cle), cle
    assert not AP.est_exclu("src/private_helpers.py")              # code source jamais exclu par sous-chaine
    assert not AP.est_exclu("src/secret_santa.py")
    # round-trip : une cle deposee dans le projet ne se retrouve PAS dans l'archive.
    _projet(tmp_path)
    (tmp_path / "wallet.key").write_text("SECRET", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=x", encoding="utf-8")
    cible = tmp_path / "out.zip"
    AP.creer_archive_portable(tmp_path, cible, pid_vivant=lambda _p: False, horloge=HORLOGE)
    with zipfile.ZipFile(cible) as z:
        noms = set(z.namelist())
    assert "wallet.key" not in noms and ".env" not in noms


# ── SQLite WAL (item 20.3) ───────────────────────────────────────────────────────────────────
def test_checkpoint_wal_rend_base_portante(tmp_path):
    base = _sqlite_avec_wal(tmp_path)
    res = AP.checkpoint_wal_sqlite(base)
    assert res["ok"] is True
    con = sqlite3.connect(str(base))
    mode = con.execute("PRAGMA journal_mode").fetchone()[0].lower()
    n = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    con.close()
    assert mode == "delete" and n == 50                             # donnees intactes, WAL fusionne


# ── refus durs (items 20.1/20.2) ─────────────────────────────────────────────────────────────
def test_refuse_si_writer_vivant(tmp_path):
    _projet(tmp_path)
    cible = tmp_path / "out.zip"
    # un writer vivant : pid_vivant renvoie True pour le pid enregistre.
    (tmp_path / REGISTRE_RELPATH).write_text(json.dumps({"collecteurs": {"bbo": 4242}}), encoding="utf-8")
    try:
        AP.creer_archive_portable(tmp_path, cible, pid_vivant=lambda _p: True, horloge=HORLOGE)
        assert False, "aurait du refuser"
    except AP.ArchiveRefuseeError as exc:
        assert "writers" in str(exc).lower()
    assert not cible.exists()                                       # rien d'ecrit


def test_checkout_propre_sans_registre_est_quiescent(tmp_path):
    # item 20.1 : un checkout neuf (lanceur JAMAIS lance -> pas de registre) mais SANS session ACTIVE
    # est un etat quiescent : l'archive doit se construire (le garde-fou reste « aucune session ACTIVE »).
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "LANCER_HYPERSMART.cmd").write_text('cd /d "%~dp0"\n', encoding="utf-8")
    assert AP.writers_vivants(tmp_path, pid_vivant=lambda _p: False) == []       # aucun writer reel
    cible = tmp_path / "out.zip"
    res = AP.creer_archive_portable(tmp_path, cible, pid_vivant=lambda _p: False, horloge=HORLOGE)
    assert cible.exists() and res["arret"].startswith("QUIESCENT_SANS_REGISTRE")
    assert res["verification"]["ok"]


def test_refuse_si_session_active(tmp_path):
    _projet(tmp_path)
    SC.CatalogueSession(tmp_path, "run_active").demarrer()                  # laissee ACTIVE
    cible = tmp_path / "out.zip"
    try:
        AP.creer_archive_portable(tmp_path, cible, pid_vivant=lambda _p: False, horloge=HORLOGE)
        assert False, "aurait du refuser"
    except AP.ArchiveRefuseeError as exc:
        assert "active" in str(exc).lower() and "run_active" in str(exc)
    assert not cible.exists()


# ── neutralisation des chemins absolus (item 20.6) ───────────────────────────────────────────
def test_neutralise_prefixe_racine():
    txt = '{"p": "/home/x/projet/runtime/data/sessions/r/bbo.jsonl"}'
    out, n = AP.neutraliser_metadonnees(txt, "/home/x/projet")
    assert n >= 1 and "runtime/data/sessions/r/bbo.jsonl" in out
    assert AP.chemins_absolus_residuels(out) == []


def test_detecte_chemin_absolu_etranger():
    assert AP.chemins_absolus_residuels(r'{"p": "C:\\Users\\autre\\x"}')
    assert AP.chemins_absolus_residuels('{"p": "/home/autre/x"}')
    assert AP.chemins_absolus_residuels("pas de chemin ici") == []


def test_ecriture_refuse_chemin_absolu_residuel(tmp_path):
    _projet(tmp_path)
    # une metadonnee qui contient un chemin absolu ETRANGER (autre machine) -> refus a l'ecriture.
    (tmp_path / "config.json").write_text(r'{"cache": "D:\\autre\\build\\x"}', encoding="utf-8")
    inclus, exclus = AP.lister_pour_archive(tmp_path)
    manifeste = AP.construire_manifeste(tmp_path, inclus, exclus, version="9.9", horloge=HORLOGE)
    try:
        AP.ecrire_archive(tmp_path, tmp_path / "out.zip", inclus, manifeste)
        assert False, "aurait du refuser"
    except AP.ArchiveRefuseeError as exc:
        assert "residuel" in str(exc).lower()
    assert not (tmp_path / "out.zip").exists()


# ── manifeste (item 22) ──────────────────────────────────────────────────────────────────────
def test_manifeste_champs_obligatoires(tmp_path):
    _projet(tmp_path)
    (tmp_path / "tools" / "python").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tools" / "python" / "python.dll").write_bytes(b"\x00\x01\x02")   # binaire hashe
    (tmp_path / "wheelhouse").mkdir(exist_ok=True)
    (tmp_path / "wheelhouse" / "pkg-1.0-py3-none-any.whl").write_bytes(b"ZIPZIP")
    (tmp_path / "VERSION").write_text("24.1.0", encoding="utf-8")
    inclus, exclus = AP.lister_pour_archive(tmp_path)
    m = AP.construire_manifeste(tmp_path, inclus, exclus, git_sha="deadbeef", horloge=HORLOGE)
    assert m["schema"] == AP.SCHEMA_MANIFESTE
    assert m["hypersmart_version"] == "24.1.0" and m["git_sha"] == "deadbeef"
    assert m["python"]["version"] and m["plateforme"]["cible"] == "Windows-x64"
    assert m["date_build_ms"] == 1_700_000_000
    assert "run_ok" in m["donnees_incluses"]                        # session COMPLETE listee
    assert m["empreinte_globale"] and m["nombre_fichiers"] == len(inclus)
    # hashes exe/DLL/wheels (item 22) presents et corrects.
    assert any(b["categorie"] == "dll" for b in m["binaires"].values())
    assert any(b["categorie"] == "wheel" for b in m["binaires"].values())
    for rel, meta in m["fichiers"].items():
        assert len(meta["sha256"]) == 64 and meta["taille"] >= 0


def test_git_sha_lu_dans_dossier_git(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (tmp_path / ".git" / "refs" / "heads").mkdir(parents=True)
    (tmp_path / ".git" / "refs" / "heads" / "main").write_text("abc123def456\n", encoding="utf-8")
    assert AP._git_sha_depuis_dossier(tmp_path) == "abc123def456"
    # HEAD detache
    (tmp_path / ".git" / "HEAD").write_text("f00dcafe\n", encoding="utf-8")
    assert AP._git_sha_depuis_dossier(tmp_path) == "f00dcafe"


# ── round-trip complet + re-verification (items 20.8/20.9) ───────────────────────────────────
def test_round_trip_ok_et_reverification(tmp_path):
    _projet(tmp_path)
    _sqlite_avec_wal(tmp_path)
    cible = tmp_path / "dist" / "hypersmart_portable.zip"
    res = AP.creer_archive_portable(tmp_path, cible, version="24.1.0",
                                    pid_vivant=lambda _p: False, horloge=HORLOGE)
    assert res["verification"]["ok"] is True and cible.exists()
    # l'archive contient bien le manifeste + les fichiers conserves, PAS les exclus.
    with zipfile.ZipFile(cible) as z:
        noms = set(z.namelist())
        assert AP.NOM_MANIFESTE in noms and "src/app.py" in noms
        assert "runtime/data/sessions/run_ok/bbo.jsonl" in noms
        assert REGISTRE_RELPATH.as_posix() not in noms and "instance.lock" not in noms
        assert "transport.bundle" not in noms
    # re-verif independante : OK.
    verif = AP.reverifier_archive(cible)
    assert verif["ok"] and verif["verifies"] >= 3 and not verif["divergences"]


def test_reverification_detecte_falsification(tmp_path):
    _projet(tmp_path)
    cible = tmp_path / "out.zip"
    AP.creer_archive_portable(tmp_path, cible, version="1.0",
                              pid_vivant=lambda _p: False, horloge=HORLOGE)
    # falsifie un membre APRES coup : la re-verif doit le detecter (divergence de hash).
    with zipfile.ZipFile(cible) as z:
        manifeste = json.loads(z.read(AP.NOM_MANIFESTE).decode("utf-8"))
        autres = {n: z.read(n) for n in z.namelist() if n != "src/app.py"}
    tmp2 = cible.with_suffix(".falsifie.zip")
    with zipfile.ZipFile(tmp2, "w") as z:
        for n, data in autres.items():
            z.writestr(n, data)
        z.writestr("src/app.py", b"CODE INJECTE MALVEILLANT\n")     # meme nom, contenu different
    verif = AP.reverifier_archive(tmp2)
    assert verif["ok"] is False and "src/app.py" in verif["divergences"]


def test_sbom_dans_le_manifeste(tmp_path):
    _projet(tmp_path)
    (tmp_path / "LICENSE").write_text("MIT", encoding="utf-8")
    (tmp_path / "requirements-portable.txt").write_text("numpy>=1.24\nrich>=13\n", encoding="utf-8")
    inclus, exclus = AP.lister_pour_archive(tmp_path)
    m = AP.construire_manifeste(tmp_path, inclus, exclus, horloge=HORLOGE)
    sbom = m["sbom"]
    assert sbom["modules_python"] >= 1                      # src/app.py compte
    assert "LICENSE" in sbom["licences"]
    assert any("numpy" in d for d in sbom["deps_verrouillees"])
    assert "LANCER_HYPERSMART.cmd" in sbom["cmd_maitres"]


def test_extraction_de_controle_reverifie_sur_disque(tmp_path):
    _projet(tmp_path)
    cible = tmp_path / "out.zip"
    res = AP.creer_archive_portable(tmp_path, cible, pid_vivant=lambda _p: False, horloge=HORLOGE)
    # la creation a fait l'extraction de controle ET elle est verte.
    assert res["verification_extraction"]["ok"] is True and res["verification_extraction"]["verifies"] >= 3
    assert res["sbom"]["modules_python"] >= 1
    # extraction independante : re-hash sur disque == manifeste.
    v = AP.extraire_et_reverifier(cible)
    assert v["ok"] and not v["divergences"] and not v["manquants"]


def test_extraction_detecte_membre_falsifie(tmp_path):
    _projet(tmp_path)
    cible = tmp_path / "out.zip"
    AP.creer_archive_portable(tmp_path, cible, pid_vivant=lambda _p: False, horloge=HORLOGE)
    # falsifie un membre dans le zip -> l'extraction de controle detecte la divergence.
    import zipfile
    with zipfile.ZipFile(cible) as z:
        membres = {n: z.read(n) for n in z.namelist()}
    membres["src/app.py"] = b"INJECTE\n"
    faux = tmp_path / "faux.zip"
    with zipfile.ZipFile(faux, "w") as z:
        for n, d in membres.items():
            z.writestr(n, d)
    v = AP.extraire_et_reverifier(faux)
    assert v["ok"] is False and "src/app.py" in v["divergences"]


def test_cli_verifier(tmp_path, capsys):
    _projet(tmp_path)
    cible = tmp_path / "out.zip"
    AP.creer_archive_portable(tmp_path, cible, version="1.0",
                              pid_vivant=lambda _p: False, horloge=HORLOGE)
    code = AP.main(["--verifier", str(cible)])
    assert code == 0 and "true" in capsys.readouterr().out.lower()
