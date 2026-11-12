"""S1.2 / A2 — PRÉ-CHAUFFER les carnets, et débloquer une liste de coins qui était figée.

Deux défauts corrigés le 12/11, tous deux mesurés sur les données réelles :

1. **Les sources étaient toutes RÉACTIVES.** « Coins bloquant la mesure » et « coins sans carnet »
   nomment les marchés où les leaders ont DÉJÀ tradé sans qu'on ait de carnet : quand un coin y
   apparaît, ses signaux sont déjà perdus. Or c'est le motif de refus n°1 du labo — **77 008 signaux
   sur 98 138** rejetés pour « aucun carnet dans les 30 s avant le signal ». D'où une troisième source,
   PRÉVENTIVE : les coins que les leaders tradent habituellement, lus dans la queue du ruban de fills.
2. **La liste était SATURÉE donc figée.** `composer` gardait tous les coins existants et n'ajoutait que
   dans la place restante : avec 180 coins occupés sur 180, l'exécution réelle donnait « 0 ajouté,
   117 demandes hors plafond ». La boucle labo → collecteurs était morte en pratique. Les coins qui ne
   sont dans AUCUNE source cèdent donc leur place, de façon bornée et rapportée.
   Après correctif, sur les mêmes données : **36 ajoutés** (les marchés HIP-3 réclamés par le labo).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "src"))

OUTIL = RACINE / "tools" / "generer_coins_lanes.py"


def _module():
    spec = importlib.util.spec_from_file_location("generer_coins_lanes_test", OUTIL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _module()
UNIVERS = {f"C{i}" for i in range(50)} | {"NEUF1", "NEUF2", "NEUF3", "NEUF4", "NEUF5"}


# ------------------------------------------------------------------ déblocage de la liste saturée

def test_une_liste_SATUREE_laisse_entrer_les_demandes_en_deplacant_les_inutiles():
    existants = [f"C{i}" for i in range(10)]                       # plafond atteint
    demandes = ["NEUF1", "NEUF2"]
    r = G.composer(existants, demandes, UNIVERS, max_coins=10)
    assert r["ajoutes"] == ["NEUF1", "NEUF2"]                      # avant le correctif : []
    assert len(r["deplaces_car_plus_demandes"]) == 2
    assert len(r["coins"]) == 10                                   # le plafond est tenu
    assert set(demandes) <= set(r["coins"])


def test_le_deplacement_part_du_rang_LE_PLUS_BAS():
    """Les premiers coins de la liste sont les plus importants : ils ne doivent pas sauter d'abord."""
    existants = [f"C{i}" for i in range(10)]
    r = G.composer(existants, ["NEUF1"], UNIVERS, max_coins=10)
    assert r["deplaces_car_plus_demandes"] == ["C9"]               # le dernier, pas le premier
    assert r["coins"][0] == "C0"


def test_un_coin_encore_demande_n_est_JAMAIS_deplace():
    """Protection essentielle : un coin present dans une source (bloquant, demande ou habituel) est
    utile, meme s'il est en bas de liste."""
    existants = [f"C{i}" for i in range(10)]
    # C9 et C8 sont dans les demandes : ils sont proteges ; C7 doit ceder a leur place
    r = G.composer(existants, ["NEUF1", "C9", "C8"], UNIVERS, max_coins=10)
    assert "C9" in r["coins"] and "C8" in r["coins"]
    assert r["deplaces_car_plus_demandes"] == ["C7"]


def test_le_brassage_est_BORNE_par_passage():
    """Anti-brassage : un carnet qu'on vient de commencer ne doit pas etre abandonne au passage
    suivant. Au plus PART_MAX_DEPLACEE de la liste bouge a chaque fois."""
    existants = [f"C{i}" for i in range(20)]
    demandes = ["NEUF1", "NEUF2", "NEUF3", "NEUF4", "NEUF5"]
    r = G.composer(existants, demandes, UNIVERS, max_coins=20)
    plafond = max(1, int(20 * G.PART_MAX_DEPLACEE))
    assert len(r["deplaces_car_plus_demandes"]) == plafond == 4
    assert len(r["ajoutes"]) == 4
    assert r["demandes_hors_plafond"] == ["NEUF5"]                 # le reste attend le passage suivant


def test_si_TOUS_les_coins_existants_sont_utiles_on_ne_deplace_rien():
    existants = ["C0", "C1", "C2"]
    r = G.composer(existants, ["C0", "C1", "C2", "NEUF1"], UNIVERS, max_coins=3)
    assert r["deplaces_car_plus_demandes"] == []
    assert r["coins"] == existants
    assert r["demandes_hors_plafond"] == ["NEUF1"]                 # honnete : on le dit


def test_on_peut_desactiver_le_deplacement_et_retrouver_l_ancien_comportement():
    existants = [f"C{i}" for i in range(10)]
    r = G.composer(existants, ["NEUF1"], UNIVERS, max_coins=10, deplacer_les_inutiles=False)
    assert r["ajoutes"] == [] and r["deplaces_car_plus_demandes"] == []
    assert r["demandes_hors_plafond"] == ["NEUF1"]


def test_une_liste_NON_saturee_ne_deplace_rien(capsys):
    """Non-regression du comportement d'origine, qui reste le cas normal."""
    r = G.composer(["C0", "C1"], ["NEUF1", "NEUF2"], UNIVERS, max_coins=10)
    assert r["deplaces_car_plus_demandes"] == []
    assert r["coins"] == ["C0", "C1", "NEUF1", "NEUF2"]


# ------------------------------------------------------------------ source préventive

def _ruban(tmp_path: Path, fills: list[dict]) -> Path:
    chemin = tmp_path / G.FILLS_LIVE
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("\n".join(json.dumps(f) for f in fills) + "\n", encoding="utf-8")
    return chemin


def test_les_coins_habituels_sont_classes_par_NOTIONNEL(tmp_path):
    """Un coin tradé une fois en gros compte plus que dix fois en miettes : c'est le notionnel qui dit
    où le carnet manquera vraiment."""
    _ruban(tmp_path, [
        {"vault": "0xa", "coin": "PETIT", "px": 1.0, "sz": 1.0},
        {"vault": "0xa", "coin": "PETIT", "px": 1.0, "sz": 1.0},
        {"vault": "0xa", "coin": "GROS", "px": 1000.0, "sz": 5.0},
        {"vault": "0xb", "coin": "MOYEN", "px": 10.0, "sz": 10.0},
    ])
    assert G.coins_habituels_des_leaders(tmp_path) == ["GROS", "MOYEN", "PETIT"]


def test_le_signe_de_la_taille_ne_fausse_pas_le_classement(tmp_path):
    """Une vente a un notionnel positif : on mesure l'activite, pas une direction."""
    _ruban(tmp_path, [{"vault": "0xa", "coin": "X", "px": 100.0, "sz": -3.0},
                      {"vault": "0xa", "coin": "Y", "px": 100.0, "sz": 1.0}])
    assert G.coins_habituels_des_leaders(tmp_path) == ["X", "Y"]


def test_on_peut_restreindre_aux_comptes_SUIVIS(tmp_path):
    """Meme principe d'alignement que pour les ordres : seuls les comptes dont on capte les fills."""
    _ruban(tmp_path, [{"vault": "0xa", "coin": "SUIVI", "px": 1.0, "sz": 1.0},
                      {"vault": "0xz", "coin": "AUTRE", "px": 1000.0, "sz": 1000.0}])
    assert G.coins_habituels_des_leaders(tmp_path, vaults={"0xa"}) == ["SUIVI"]


def test_les_lignes_abimees_sont_ignorees_sans_tout_perdre(tmp_path):
    chemin = tmp_path / G.FILLS_LIVE
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("\n".join([
        "pas du json",
        json.dumps({"vault": "0xa", "coin": "BON", "px": 10.0, "sz": 2.0}),
        "{tronque",
        json.dumps([1, 2, 3]),
        json.dumps({"vault": "0xa", "px": 1.0, "sz": 1.0}),                    # sans coin
        json.dumps({"vault": "0xa", "coin": "SANSPRIX", "px": None, "sz": None}),
    ]) + "\n", encoding="utf-8")
    coins = G.coins_habituels_des_leaders(tmp_path)
    assert "BON" in coins and "SANSPRIX" in coins                              # notionnel 0, mais trade
    assert coins[0] == "BON"


def test_un_ruban_absent_ne_fait_rien_planter(tmp_path):
    assert G.coins_habituels_des_leaders(tmp_path) == []


def test_la_lecture_est_BORNEE_a_la_queue_du_ruban(tmp_path):
    """Cout borne quelle que soit la taille du fichier : on ne lit que les derniers octets."""
    fills = [{"vault": "0xa", "coin": f"VIEUX{i}", "px": 1.0, "sz": 1.0} for i in range(500)]
    fills += [{"vault": "0xa", "coin": "RECENT", "px": 1.0, "sz": 1.0}]
    _ruban(tmp_path, fills)
    coins = G.coins_habituels_des_leaders(tmp_path, octets=300)
    assert "RECENT" in coins
    assert len(coins) < 50                                                     # les vieux ne sont pas lus


def test_la_premiere_ligne_tronquee_est_jetee(tmp_path):
    """Lire depuis le milieu du fichier coupe une ligne en deux : elle doit etre jetee, pas parsee."""
    chemin = _ruban(tmp_path, [{"vault": "0xa", "coin": "A" * 50, "px": 1.0, "sz": 1.0},
                               {"vault": "0xa", "coin": "ENTIER", "px": 1.0, "sz": 1.0}])
    lignes = G._queue_du_ruban(chemin, 60)
    assert all(l.strip().startswith("{") or not l.strip() for l in lignes)
