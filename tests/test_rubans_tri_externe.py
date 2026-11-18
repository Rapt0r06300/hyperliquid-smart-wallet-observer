"""LE RUBAN DE REPLAY, PRODUIT SANS TENIR LE CORPUS EN MÉMOIRE — OCTET POUR OCTET IDENTIQUE.

Défaut mesuré le 17/11/2026 : le labo charge 3,2 millions de lignes dans des dictionnaires pour
les trier et les écrire, alors que la phase suivante relit les rubans depuis le disque. Il
s'arrête en `MEMOIRE_CRITIQUE` après 452 shards sur 5 570 et conclut « trop peu de jours », là où
le tunnel compte onze jours exploitables sur onze dans le même coffre.

Le contrat de ce module est l'IDENTITÉ DES OCTETS avec l'ancien chemin. Ces tests le vérifient sur
des corpus construits pour piéger les deux difficultés : des clés de tri à égalité (seul un tri
stable donne le bon ordre) et des doublons d'identité à préférence différente.
"""
from __future__ import annotations

import hashlib
import json
import random

import pytest

from hl_observer.backtesting import rubans_tri_externe as R

CLE_TRI = (lambda ligne: (ligne["ts_ms"], ligne["vault"], str(ligne.get("tid"))))
CLE_ID = (lambda ligne: (ligne["vault"], ligne["coin"], ligne["ts_ms"], ligne.get("tid"),
                         ligne.get("px"), ligne.get("sz"), ligne.get("signe")))
#: la règle du labo : un fill observé en direct est préféré à la même ligne vue en snapshot
PREFERENCE = (lambda ligne: 1 if ligne.get("isSnapshot") else 0)


def _fill(ts, vault="0xa", coin="ETH", tid=1, px=2000.0, sz=1.0, signe=1, snapshot=False, **extra):
    return {"ts_ms": ts, "vault": vault, "coin": coin, "tid": tid, "px": px, "sz": sz,
            "signe": signe, "isSnapshot": snapshot, **extra}


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _les_deux_chemins(tmp_path, lignes, **kw):
    """Écrit le ruban par les deux chemins et rend (sha_memoire, sha_flux, bilan_flux)."""
    memoire, flux = tmp_path / "memoire.jsonl", tmp_path / "flux.jsonl"
    bm = R.ecrire_ruban_en_memoire(memoire, list(lignes), cle_tri=CLE_TRI, cle_identite=CLE_ID, **kw)
    bf = R.ecrire_ruban_trie(flux, lambda: iter(list(lignes)), cle_tri=CLE_TRI, cle_identite=CLE_ID,
                             dossier_temporaire=tmp_path / "morceaux", **kw)
    return _sha(memoire), _sha(flux), bm, bf


# ───────────────────────── l'identité des octets ─────────────────────────

def test_corpus_simple_les_deux_chemins_donnent_les_MEMES_OCTETS(tmp_path):
    lignes = [_fill(300, tid=3), _fill(100, tid=1), _fill(200, tid=2)]
    a, b, bm, bf = _les_deux_chemins(tmp_path, lignes)
    assert a == b and bm["lignes_ecrites"] == bf["lignes_ecrites"] == 3


def test_les_CLES_DE_TRI_A_EGALITE_gardent_l_ordre_de_lecture(tmp_path):
    """Trois lignes de même (ts, vault, tid) : seul un tri STABLE donne le bon ordre."""
    lignes = [_fill(100, px=3.0), _fill(100, px=1.0), _fill(100, px=2.0)]
    a, b, _bm, bf = _les_deux_chemins(tmp_path, lignes)
    assert a == b and bf["lignes_ecrites"] == 3
    ordre = [json.loads(l)["px"] for l in (tmp_path / "flux.jsonl").read_text(encoding="utf-8").splitlines()]
    assert ordre == [3.0, 1.0, 2.0], "l'ordre de lecture est conservé, comme le tri stable d'origine"


def test_un_DOUBLON_exact_est_ecarte_et_le_premier_est_garde(tmp_path):
    lignes = [_fill(100, bruit="premier"), _fill(100, bruit="second")]
    # même identité (bruit n'en fait pas partie) : une seule ligne survit, la première
    a, b, bm, bf = _les_deux_chemins(tmp_path, lignes)
    assert a == b and bf["lignes_ecrites"] == 1 and bf["doublons_ecartes"] == 1
    assert json.loads((tmp_path / "flux.jsonl").read_text(encoding="utf-8"))["bruit"] == "premier"


def test_un_fill_EN_DIRECT_est_prefere_au_meme_fill_en_SNAPSHOT(tmp_path):
    for ordre_de_lecture in ([_fill(100, snapshot=True), _fill(100, snapshot=False)],
                             [_fill(100, snapshot=False), _fill(100, snapshot=True)]):
        a, b, _bm, bf = _les_deux_chemins(tmp_path, ordre_de_lecture, rang_preference=PREFERENCE)
        assert a == b and bf["lignes_ecrites"] == 1
        garde = json.loads((tmp_path / "flux.jsonl").read_text(encoding="utf-8"))
        assert garde["isSnapshot"] is False, "la ligne observée en direct gagne, quel que soit l'ordre"


def test_sans_regle_de_preference_le_premier_lu_gagne_toujours(tmp_path):
    lignes = [_fill(100, snapshot=True), _fill(100, snapshot=False)]
    a, b, _bm, bf = _les_deux_chemins(tmp_path, lignes)       # pas de rang_preference
    assert a == b and json.loads((tmp_path / "flux.jsonl").read_text(encoding="utf-8"))["isSnapshot"] is True


@pytest.mark.parametrize("lignes_par_morceau", [1, 2, 3, 7, 100])
def test_la_TAILLE_DES_MORCEAUX_ne_change_pas_un_seul_octet(tmp_path, lignes_par_morceau):
    alea = random.Random(20261118)
    lignes = [_fill(alea.randrange(50), vault=f"0x{alea.randrange(3)}", tid=alea.randrange(5),
                    px=float(alea.randrange(10)), snapshot=alea.random() < 0.3)
              for _ in range(60)]
    memoire, flux = tmp_path / "m.jsonl", tmp_path / "f.jsonl"
    R.ecrire_ruban_en_memoire(memoire, lignes, cle_tri=CLE_TRI, cle_identite=CLE_ID, rang_preference=PREFERENCE)
    bilan = R.ecrire_ruban_trie(flux, lambda: iter(lignes), cle_tri=CLE_TRI, cle_identite=CLE_ID,
                                rang_preference=PREFERENCE, dossier_temporaire=tmp_path / "t",
                                lignes_par_morceau=lignes_par_morceau)
    assert _sha(memoire) == _sha(flux)
    assert bilan["morceaux"] == max(1, -(-bilan["lignes_ecrites"] // lignes_par_morceau))


def test_corpus_ALEATOIRE_300_tirages_les_deux_chemins_concordent(tmp_path):
    """Le vrai juge : des centaines de corpus avec doublons, égalités et snapshots mêlés."""
    alea = random.Random(7)
    for tirage in range(300):
        n = alea.randrange(0, 40)
        lignes = [_fill(alea.randrange(5), vault=f"0x{alea.randrange(2)}", coin=alea.choice("AB"),
                        tid=alea.randrange(3), px=float(alea.randrange(4)), sz=float(alea.randrange(3)),
                        signe=alea.choice((-1, 1)), snapshot=alea.random() < 0.4,
                        bruit=alea.randrange(100))
                  for _ in range(n)]
        memoire, flux = tmp_path / f"m{tirage}.jsonl", tmp_path / f"f{tirage}.jsonl"
        R.ecrire_ruban_en_memoire(memoire, lignes, cle_tri=CLE_TRI, cle_identite=CLE_ID,
                                  rang_preference=PREFERENCE)
        R.ecrire_ruban_trie(flux, lambda lignes=lignes: iter(lignes), cle_tri=CLE_TRI,
                            cle_identite=CLE_ID, rang_preference=PREFERENCE,
                            dossier_temporaire=tmp_path / f"t{tirage}", lignes_par_morceau=3)
        assert _sha(memoire) == _sha(flux), f"tirage {tirage} ({n} lignes)"
        memoire.unlink(); flux.unlink()


def test_un_corpus_VIDE_produit_un_ruban_vide_sans_echouer(tmp_path):
    bilan = R.ecrire_ruban_trie(tmp_path / "vide.jsonl", lambda: iter(()), cle_tri=CLE_TRI,
                                cle_identite=CLE_ID, dossier_temporaire=tmp_path / "t")
    assert (tmp_path / "vide.jsonl").read_bytes() == b"" and bilan["lignes_ecrites"] == 0


# ───────────────────────── la mémoire réellement économisée ─────────────────────────

def test_la_PREMIERE_PASSE_ne_garde_AUCUNE_ligne(tmp_path):
    """C'est tout l'intérêt : 16 octets d'empreinte par identité au lieu de la ligne entière."""
    lignes = [_fill(i, tid=i, bruit="x" * 500) for i in range(200)]
    selection = R.gagnants(lambda: iter(lignes), cle_identite=CLE_ID)
    assert selection["identites"] == 200 and selection["lignes_lues"] == 200
    cles = list(selection["index_par_identite"])
    assert all(isinstance(c, bytes) and len(c) == R.EMPREINTE_OCTETS for c in cles)
    import sys
    tenu = sum(sys.getsizeof(c) + sys.getsizeof(0) for c in cles)
    corpus = sum(sys.getsizeof(json.dumps(l)) for l in lignes)
    assert tenu < corpus / 3, f"la passe 1 doit tenir bien moins que le corpus ({tenu} vs {corpus})"


def test_la_selection_deja_calculee_est_REUTILISEE(tmp_path):
    lignes = [_fill(2, tid=2), _fill(1, tid=1)]
    passes = []

    def fabrique():
        passes.append(1)
        return iter(lignes)

    selection = R.gagnants(fabrique, cle_identite=CLE_ID)
    R.ecrire_ruban_trie(tmp_path / "r.jsonl", fabrique, cle_tri=CLE_TRI, cle_identite=CLE_ID,
                        dossier_temporaire=tmp_path / "t", selection=selection)
    assert len(passes) == 2, "une passe pour les gagnants, une pour l'écriture : jamais trois"


# ───────────────────────── les refus, plutôt qu'un ruban faux ─────────────────────────

def test_une_source_QUI_BOUGE_entre_les_deux_passes_fait_REFUSER_le_ruban(tmp_path):
    """Un ruban incomplet écrit en silence serait pris pour le corpus entier."""
    etat = {"n": 3}

    def fabrique():
        lignes = [_fill(i, tid=i) for i in range(etat["n"])]
        etat["n"] -= 1          # la source perd une ligne entre les deux passes
        return iter(lignes)

    cible = tmp_path / "r.jsonl"
    with pytest.raises(ValueError, match="la source a change"):
        R.ecrire_ruban_trie(cible, fabrique, cle_tri=CLE_TRI, cle_identite=CLE_ID,
                            dossier_temporaire=tmp_path / "t")
    assert not cible.exists(), "aucun ruban partiel ne doit rester"


def test_une_source_qui_change_de_CONTENU_fait_aussi_REFUSER(tmp_path):
    appels = {"n": 0}

    def fabrique():
        appels["n"] += 1
        if appels["n"] == 1:
            return iter([_fill(1, tid=1), _fill(2, tid=2)])
        return iter([_fill(1, tid=1), _fill(9, tid=9)])      # autant de lignes, mais pas les mêmes

    with pytest.raises(ValueError, match="gagnants introuvables"):
        R.ecrire_ruban_trie(tmp_path / "r.jsonl", fabrique, cle_tri=CLE_TRI, cle_identite=CLE_ID,
                            dossier_temporaire=tmp_path / "t")


def test_les_morceaux_temporaires_sont_NETTOYES_meme_apres_un_refus(tmp_path):
    etat = {"n": 5}

    def fabrique():
        lignes = [_fill(i, tid=i) for i in range(etat["n"])]
        etat["n"] -= 2
        return iter(lignes)

    dossier = tmp_path / "t"
    with pytest.raises(ValueError):
        R.ecrire_ruban_trie(tmp_path / "r.jsonl", fabrique, cle_tri=CLE_TRI, cle_identite=CLE_ID,
                            dossier_temporaire=dossier, lignes_par_morceau=1)
    assert not list(dossier.glob("morceau_*.jsonl")), "aucun fichier temporaire ne doit survivre"


def test_un_lien_symbolique_est_REFUSE(tmp_path):
    reel = tmp_path / "reel.jsonl"
    reel.write_text("", encoding="utf-8")
    lien = tmp_path / "lien.jsonl"
    try:
        lien.symlink_to(reel)
    except (OSError, NotImplementedError):
        pytest.skip("liens symboliques indisponibles sur cette machine")
    with pytest.raises(OSError, match="lien symbolique"):
        R.ecrire_ruban_trie(lien, lambda: iter(()), cle_tri=CLE_TRI, cle_identite=CLE_ID)


# ───────────────────────── l'empreinte d'identité ─────────────────────────

def test_l_empreinte_ne_confond_pas_un_ENTIER_et_un_FLOTTANT_equivalents():
    """`repr` les distinguerait, et deux lignes identiques deviendraient deux signaux."""
    assert R.empreinte(("0xa", "ETH", 100, 1)) == R.empreinte(("0xa", "ETH", 100, 1.0))
    assert R.empreinte(("0xa", "ETH", 100, 1)) != R.empreinte(("0xa", "ETH", 100, 2))


def test_l_empreinte_distingue_le_DECOUPAGE_des_champs():
    """Sans séparateur, ("ab","c") et ("a","bc") se confondraient."""
    assert R.empreinte(("ab", "c")) != R.empreinte(("a", "bc"))


def test_l_empreinte_supporte_un_None_et_un_type_inattendu():
    assert len(R.empreinte(("0xa", None, 100))) == R.EMPREINTE_OCTETS
    assert len(R.empreinte((object(),))) == R.EMPREINTE_OCTETS


def test_la_serialisation_est_celle_des_rubans_du_labo():
    """Clés triées, accents conservés : c'est ce qui fixe les empreintes publiées au manifeste."""
    assert R.serialiser({"b": 1, "a": "é"}) == '{"a": "é", "b": 1}'


# ───────── l'identité d'un carnet contient ses niveaux de prix ─────────

CLE_CARNET = (lambda l: (l["coin"], l["received_at_ms"], l["exchange_ts_ms"], l["bid"], l["ask"],
                         tuple(tuple(n) for n in l["bids5"]), tuple(tuple(n) for n in l["asks5"])))
TRI_CARNET = (lambda l: (l["received_at_ms"], l["coin"]))


def _carnet(recu, coin="ETH", bid=1999.0, ask=2001.0, niveaux=None, **extra):
    n = niveaux if niveaux is not None else [[1999.0, 1.0]]
    return {"coin": coin, "received_at_ms": recu, "exchange_ts_ms": recu - 400, "bid": bid,
            "ask": ask, "bids5": n, "asks5": [[2001.0, 2.0]], **extra}


def test_une_LISTE_imbriquee_dans_l_identite_est_normalisee_comme_un_tuple_Python():
    """Le labo compare des tuples : (1,) == (1.0,). Deux empreintes différentes feraient deux carnets."""
    assert R.empreinte(("ETH", 100, [[1999.0, 1.0]])) == R.empreinte(("ETH", 100, ((1999, 1),)))
    assert R.empreinte(("ETH", 100, [[1999.0, 1.0]])) != R.empreinte(("ETH", 100, [[1999.0, 2.0]]))


def test_une_liste_imbriquee_ne_se_confond_pas_avec_sa_mise_a_plat():
    assert R.empreinte(([1, 2], [3],)) != R.empreinte(([1], [2, 3],))
    assert R.empreinte(([[1]],)) != R.empreinte(([1],))


def test_les_CARNETS_passent_par_les_deux_chemins_a_l_identique(tmp_path):
    lignes = [_carnet(300), _carnet(100), _carnet(200, coin="BTC"),
              _carnet(100, bruit="doublon"),                       # même identité que le 2e
              _carnet(100, niveaux=[[1999, 1]]),                   # entiers : même identité aussi
              _carnet(400, niveaux=[[1999.0, 5.0]])]               # niveaux différents : autre carnet
    memoire, flux = tmp_path / "m.jsonl", tmp_path / "f.jsonl"
    bm = R.ecrire_ruban_en_memoire(memoire, lignes, cle_tri=TRI_CARNET, cle_identite=CLE_CARNET)
    bf = R.ecrire_ruban_trie(flux, lambda: iter(lignes), cle_tri=TRI_CARNET, cle_identite=CLE_CARNET,
                             dossier_temporaire=tmp_path / "t", lignes_par_morceau=2)
    assert _sha(memoire) == _sha(flux)
    assert bm["lignes_ecrites"] == bf["lignes_ecrites"] == 4, "deux doublons écartés sur six lignes"


def test_le_bilan_porte_les_BORNES_du_ruban_sans_le_relire(tmp_path):
    """Le labo publie `fill_start_ms` / `fill_end_ms` : ils doivent sortir de l'écriture même."""
    lignes = [_fill(300, tid=3), _fill(100, tid=1), _fill(200, tid=2)]
    bilan = R.ecrire_ruban_trie(tmp_path / "r.jsonl", lambda: iter(lignes), cle_tri=CLE_TRI,
                                cle_identite=CLE_ID, dossier_temporaire=tmp_path / "t",
                                lignes_par_morceau=1)
    assert bilan["premiere_cle"] == (100, "0xa", "1")
    assert bilan["derniere_cle"] == (300, "0xa", "3")


def test_les_bornes_d_un_ruban_VIDE_sont_INCONNUES_et_non_zero(tmp_path):
    bilan = R.ecrire_ruban_trie(tmp_path / "v.jsonl", lambda: iter(()), cle_tri=CLE_TRI,
                                cle_identite=CLE_ID, dossier_temporaire=tmp_path / "t")
    assert bilan["premiere_cle"] is None and bilan["derniere_cle"] is None


def test_un_FILTRE_restreint_le_ruban_sans_refaire_la_deduplication(tmp_path):
    lignes = [_fill(100, snapshot=True), _fill(100, snapshot=False), _fill(200, snapshot=True)]
    bilan = R.ecrire_ruban_trie(tmp_path / "s.jsonl", lambda: iter(lignes), cle_tri=CLE_TRI,
                                cle_identite=CLE_ID, rang_preference=PREFERENCE,
                                dossier_temporaire=tmp_path / "t",
                                garder=lambda l: bool(l.get("isSnapshot")))
    assert bilan["lignes_retenues"] == 2, "deux identités après déduplication"
    assert bilan["lignes_ecrites"] == 1 and bilan["ecartees_par_le_filtre"] == 1
    assert json.loads((tmp_path / "s.jsonl").read_text(encoding="utf-8"))["ts_ms"] == 200
