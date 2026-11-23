"""Compression intelligente du certificateur (23/11/2026) : sans perte, relue à l'offset, jamais redéposée.

Ce que ces tests tiennent :
- l'archive par blocs redonne CHAQUE octet (taille et SHA-256) et se lit avec un gzip standard ;
- chaque ligne se relit à son offset d'origine en ne décompressant qu'un bloc (le lecteur de preuves en dépend) ;
- une vérification ratée laisse la source intacte et aucun fichier partiel ;
- le lecteur de preuves et le score des vaults trouvent un ruban de session compressé ;
- un ruban de session scellé puis compressé n'est JAMAIS redéposé au coffre au passage suivant ;
- un ruban modifié récemment ou trop petit n'est pas compressé.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import random
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
for _p in (RACINE / "src", RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from hl_observer.datasets import archive_gzip_blocs as A  # noqa: E402

NOW = 1_795_000_000_000


def _ruban(chemin: Path, n: int, graine: int = 7, *, fin_sans_retour: bool = True) -> list[bytes]:
    rng = random.Random(graine)
    lignes = [(json.dumps({"coin": "ETH", "ts_ms": NOW - 10_000 + i, "mark": 2000 + rng.random(),
                           "bruit": "x" * rng.randint(0, 300)}) + "\n").encode() for i in range(n)]
    if fin_sans_retour:
        lignes[-1] = lignes[-1].rstrip(b"\n")             # dernière ligne sans fin de ligne : doit survivre aussi
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(b"".join(lignes))
    return lignes


def test_l_archive_redonne_chaque_octet_et_se_lit_avec_un_gzip_standard(tmp_path):
    src = tmp_path / "x.jsonl"
    _ruban(src, 3000)
    brut = src.read_bytes()
    idx = A.compresser(src, bloc=16 * 1024)
    gz = tmp_path / "x.jsonl.gz"
    assert len(idx["blocs"]) > 5                                                     # vraiment plusieurs blocs
    assert gzip.decompress(gz.read_bytes()) == brut                                  # outil standard, multi-membres
    assert idx["sha256_clair"] == hashlib.sha256(brut).hexdigest() and idx["taille_clair"] == len(brut)
    assert src.exists()                                                              # compresser ne retire rien


def test_chaque_ligne_se_relit_a_son_offset_d_origine(tmp_path):
    src = tmp_path / "x.jsonl"
    lignes = _ruban(src, 2000)
    A.compresser(src, bloc=8 * 1024)
    lecteur = A.LecteurArchive(tmp_path / "x.jsonl.gz")
    offset = 0
    for ligne in lignes:
        assert lecteur.ligne_a(offset) == ligne
        offset += len(ligne)
    assert lecteur.ligne_a(offset) is None                                            # au-delà de la fin : rien
    lecteur.fermer()


def test_une_verification_ratee_laisse_la_source_intacte_et_aucun_partiel(tmp_path, monkeypatch):
    src = tmp_path / "x.jsonl"
    _ruban(src, 500)
    avant = src.read_bytes()

    class Faux:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            return b""                                                               # relecture qui ne rend rien

    monkeypatch.setattr(A.gzip, "open", Faux)
    with pytest.raises(RuntimeError, match="verification"):
        A.remplacer_par_archive(src)
    assert src.read_bytes() == avant
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.jsonl"]


def test_le_lecteur_de_preuves_retrouve_la_ligne_dans_une_session_compressee(tmp_path):
    from hl_observer.collection.copy_vault_reference_binding import LecteurBorne

    session = tmp_path / "runtime" / "archive" / "session_20261120_100000" / "bbo_tape.jsonl"
    lignes = _ruban(session, 400)
    A.remplacer_par_archive(session, bloc=4096)
    assert not session.exists()
    lecteur = LecteurBorne(tmp_path.resolve())
    offset = sum(len(x) for x in lignes[:123])
    assert list(lecteur.alternatives("runtime/data/bbo_tape.jsonl", offset)) == [lignes[123]]
    lecteur.fermer()


def test_le_score_des_vaults_lit_une_session_compressee(tmp_path):
    import scorer_vaults as SV

    session = tmp_path / "runtime" / "archive" / "session_20261120_100000" / "vault_snapshots.jsonl"
    _ruban(session, 50)
    A.remplacer_par_archive(session)
    trouves = SV._rubans(tmp_path, "vault_snapshots.jsonl", now=time.mktime((2026, 11, 21, 0, 0, 0, 0, 0, -1)))
    assert trouves[0].name == "vault_snapshots.jsonl.gz"


def test_un_ruban_scelle_puis_compresse_n_est_jamais_redepose(tmp_path):
    import sceller_coffre_local as S

    session = tmp_path / "runtime" / "archive" / "session_20261120_100000" / "asset_ctx_tape.jsonl"
    _ruban(session, 2000, fin_sans_retour=False)
    assert S.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--archives", "--nom", "asset_ctx_tape.jsonl"]) == 0
    index = tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    deposes = sum(s["deposes"] for s in json.loads(index.read_text(encoding="utf-8"))["shards"])
    assert deposes == 2000
    bilan = S.compresser_rubans_figes(tmp_path, age_min_s=0, travailleurs=1)
    assert bilan["compresses"] == 1 and not session.exists()
    assert bilan["octets_apres"] < bilan["octets_avant"]
    assert S.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--archives", "--nom", "asset_ctx_tape.jsonl.gz"]) == 0
    assert sum(s["deposes"] for s in json.loads(index.read_text(encoding="utf-8"))["shards"]) == 2000   # rien de neuf


def _deposes(root: Path) -> int:
    index = root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    return sum(s["deposes"] for s in json.loads(index.read_text(encoding="utf-8"))["shards"])


def test_une_archive_dont_la_derniere_ligne_n_a_pas_de_retour_n_est_jamais_redeposee(tmp_path):
    """DÉFAUT TROUVÉ ICI (23/11/2026) : le préfixe noté s'arrêtait au dernier retour alors que toute l'archive
    était lue ; la dernière ligne revenait au passage suivant, en DOUBLON. Une archive figée est scellée en entier."""
    import sceller_coffre_local as S

    session = tmp_path / "runtime" / "archive" / "session_20261120_100000" / "asset_ctx_tape.jsonl"
    _ruban(session, 2000)                                    # > COMPRESSION_TAILLE_MIN : il SERA compressé
    assert S.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--archives", "--nom", "asset_ctx_tape.jsonl"]) == 0
    assert _deposes(tmp_path) == 2000
    assert S.compresser_rubans_figes(tmp_path, age_min_s=0, travailleurs=1)["compresses"] == 1   # sinon test aveugle
    for _ in range(2):
        S.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--archives", "--nom", "asset_ctx_tape.jsonl.gz"])
    assert _deposes(tmp_path) == 2000                                                # jamais une seconde fois


def test_un_ruban_vivant_ne_lit_pas_sa_ligne_en_cours_d_ecriture_et_la_scelle_une_fois_complete(tmp_path):
    """Le même défaut, côté ruban vivant : la ligne sans retour était déposée puis redéposée une fois complétée."""
    import sceller_coffre_local as S

    vivant = tmp_path / "runtime" / "data" / "asset_ctx_tape.jsonl"
    _ruban(vivant, 300)                                                              # la 300e « en cours d'écriture »
    assert S.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--nom", "asset_ctx_tape.jsonl"]) == 0
    assert _deposes(tmp_path) == 299
    quarantaine = list((tmp_path / "runtime" / "coffre_certifie" / "quarantine").rglob("*.jsonl"))
    assert all(q.stat().st_size == 0 for q in quarantaine)                           # ni lue, ni mise en quarantaine
    with vivant.open("ab") as f:
        f.write(b"\n")                                                               # l'écrivain termine sa ligne
    assert S.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--nom", "asset_ctx_tape.jsonl"]) == 0
    assert _deposes(tmp_path) == 300                                                 # une seule fois


def test_une_rotation_ancienne_est_reconnue_meme_apres_douze_rotations(tmp_path):
    """23/11/2026 : l'état ne gardait que 8 préfixes par chemin ; un certificateur bloqué longtemps laissait passer
    plus de 8 rotations, et la plus ancienne se rescellait EN ENTIER (doublons micro_bbo mesurés le jour même)."""
    import sceller_coffre_local as S

    vivant = tmp_path / "runtime" / "data" / "asset_ctx_tape.jsonl"
    premier = _ruban(vivant, 10, graine=100, fin_sans_retour=False)       # la PLUS COURTE : essayée en dernier
                                                                          # par un ordre « du plus long au plus court »
    assert S.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--nom", "asset_ctx_tape.jsonl"]) == 0
    for k in range(12):                                                   # 12 sessions : le ruban repart de zéro
        _ruban(vivant, 40, graine=200 + k, fin_sans_retour=False)
        assert S.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--nom", "asset_ctx_tape.jsonl"]) == 0
    avant = _deposes(tmp_path)
    rotation = vivant.with_name("asset_ctx_tape_1795000000000000000.jsonl.gz")
    with gzip.open(rotation, "wb") as g:
        g.write(b"".join(premier))                                        # la toute première version revient
    assert S.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--nom", rotation.name]) == 0
    assert _deposes(tmp_path) == avant                                    # reconnue : rien de redéposé


def test_un_ruban_modifie_recemment_ou_trop_petit_reste_en_clair(tmp_path):
    import sceller_coffre_local as S

    gros = tmp_path / "runtime" / "archive" / "session_20261120_100000" / "bbo_tape.jsonl"
    petit = gros.with_name("micro.jsonl")
    _ruban(gros, 3000)
    _ruban(petit, 3)
    bilan = S.compresser_rubans_figes(tmp_path, age_min_s=3600, travailleurs=1)       # tout vient d'être écrit
    assert bilan["compresses"] == 0 and gros.exists() and petit.exists()
    assert bilan["ignores"] == {"modifie_recemment": 1, "trop_petit": 1}
