"""#462 / H-57 -- l'archive S3 officielle Hyperliquid.

Ce que ces tests gardent :
  * 🔒 **AUCUN identifiant AWS dans un fichier du projet** (invariant sur le source lui-meme) ;
  * deny-by-default : sans identifiants -> **REFUS**, pas une tentative a l'aveugle ;
  * deny-by-default : un nom de jeu de donnees absent de la doc -> **REFUS**, pas un chemin devine ;
  * les chemins reproduisent **EXACTEMENT** l'exemple de la doc officielle ;
  * on **COMPTE les trous** (la doc previent : « data may be missing »).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hl_observer.collection.archive_s3 import (
    BUCKET_MARCHE,
    BUCKET_NOEUD,
    JEUX_NOEUD,
    VARIABLES_AWS,
    CleS3,
    IdentifiantsAbsents,
    JeuDeDonneesInconnu,
    cle_asset_ctxs,
    cle_l2_book,
    couverture,
    exiger_identifiants,
    identifiants_presents,
    plan_l2_book,
    prefixe_noeud,
)

UTC = timezone.utc


# ════════════════════════════════════════════════════════════════════════════════════════════
# 1. 🔒 SECURITE : aucun secret dans un fichier, jamais
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_aucune_cle_aws_ecrite_en_dur_dans_le_module() -> None:
    """Invariant : un secret ecrit dans un fichier est un secret publie."""
    src = Path(__file__).resolve().parents[1] / "src" / "hl_observer" / "collection" / "archive_s3.py"
    texte = src.read_text(encoding="utf-8")
    # AKIA... = prefixe des cles d'acces AWS. Aucune ne doit exister ici.
    assert not re.search(r"AKIA[0-9A-Z]{16}", texte), "cle d'acces AWS ecrite en dur !"
    # Une secret key fait 40 caracteres base64. On interdit toute affectation suspecte.
    assert not re.search(r"AWS_SECRET_ACCESS_KEY\s*=\s*['\"][^'\"]{20,}", texte)


def test_sans_identifiants_on_REFUSE_au_lieu_de_tenter() -> None:
    """L'archive est en **requester-pays** (doc). Sans identifiants, on ne tente RIEN."""
    with pytest.raises(IdentifiantsAbsents):
        exiger_identifiants({})
    with pytest.raises(IdentifiantsAbsents):
        exiger_identifiants({"AWS_ACCESS_KEY_ID": "x"})            # une seule des deux
    with pytest.raises(IdentifiantsAbsents):
        exiger_identifiants({"AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "   "})


def test_avec_identifiants_on_passe() -> None:
    env = {v: "valeur" for v in VARIABLES_AWS}
    assert identifiants_presents(env)
    exiger_identifiants(env)          # ne doit pas lever


# ════════════════════════════════════════════════════════════════════════════════════════════
# 2. Les chemins REPRODUISENT l'exemple de la doc — on n'invente rien
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_la_cle_l2_book_reproduit_EXACTEMENT_l_exemple_de_la_doc() -> None:
    """Doc : s3://hyperliquid-archive/market_data/20230916/9/l2Book/SOL.lz4

    Noter l'heure **SANS zero de tete** (9, pas 09). Un chemin faux = un 404 silencieux.
    """
    k = cle_l2_book("SOL", datetime(2023, 9, 16, tzinfo=UTC), 9)
    assert k.uri == "s3://hyperliquid-archive/market_data/20230916/9/l2Book/SOL.lz4"
    assert k.bucket == BUCKET_MARCHE


def test_l_heure_n_a_PAS_de_zero_de_tete() -> None:
    k = cle_l2_book("BTC", datetime(2024, 1, 5, tzinfo=UTC), 3)
    assert "/3/l2Book/" in k.cle and "/03/" not in k.cle


def test_la_cle_asset_ctxs_suit_la_doc() -> None:
    assert cle_asset_ctxs(datetime(2023, 9, 16, tzinfo=UTC)).uri == \
        "s3://hyperliquid-archive/asset_ctxs/20230916.csv.lz4"


@pytest.mark.parametrize("heure", [-1, 24, 99])
def test_une_heure_absurde_est_REFUSEE(heure: int) -> None:
    with pytest.raises(ValueError):
        cle_l2_book("BTC", datetime(2024, 1, 1, tzinfo=UTC), heure)


def test_un_coin_vide_est_REFUSE() -> None:
    with pytest.raises(ValueError):
        cle_l2_book("  ", datetime(2024, 1, 1, tzinfo=UTC), 0)


# ════════════════════════════════════════════════════════════════════════════════════════════
# 3. Deny-by-default sur le NOM du jeu de donnees
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_les_jeux_du_noeud_sont_ceux_de_la_doc() -> None:
    for jeu in ("node_fills_by_block", "node_trades", "misc_events_by_block"):
        assert prefixe_noeud(jeu).bucket == BUCKET_NOEUD
        assert jeu in JEUX_NOEUD


@pytest.mark.parametrize("jeu", ["node_orders", "l3Book", "", "trades", None])
def test_un_jeu_ABSENT_DE_LA_DOC_est_refuse_jamais_devine(jeu: object) -> None:
    """*On ne fabrique pas un chemin S3 « de memoire ».* Un chemin devine = un 404, ou pire :
    une donnee qui n'est pas celle qu'on croit."""
    with pytest.raises(JeuDeDonneesInconnu):
        prefixe_noeud(jeu)  # type: ignore[arg-type]


# ════════════════════════════════════════════════════════════════════════════════════════════
# 4. Le plan horaire
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_plan_produit_une_cle_par_HEURE() -> None:
    d = datetime(2024, 3, 1, 0, tzinfo=UTC)
    cles = plan_l2_book("BTC", debut=d, fin=d + timedelta(hours=5))
    assert len(cles) == 5
    assert cles[0].cle.endswith("/0/l2Book/BTC.lz4")
    assert cles[4].cle.endswith("/4/l2Book/BTC.lz4")


def test_le_plan_ne_demande_JAMAIS_le_futur() -> None:
    futur = datetime.now(UTC) + timedelta(days=30)
    cles = plan_l2_book("BTC", debut=datetime.now(UTC) - timedelta(hours=2), fin=futur)
    assert len(cles) <= 3, "le plan doit etre borne a maintenant"


def test_le_plan_exige_un_fuseau_explicite() -> None:
    with pytest.raises(ValueError):
        plan_l2_book("BTC", debut=datetime(2024, 1, 1), fin=datetime(2024, 1, 2))


def test_un_intervalle_inverse_ne_produit_aucune_cle() -> None:
    d = datetime(2024, 3, 1, tzinfo=UTC)
    assert plan_l2_book("BTC", debut=d, fin=d) == []
    assert plan_l2_book("BTC", debut=d, fin=d - timedelta(hours=1)) == []


# ════════════════════════════════════════════════════════════════════════════════════════════
# 5. 🔴 On COMPTE les trous — la doc previent : « data may be missing »
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_une_couverture_trouee_est_annoncee_trouee() -> None:
    d = datetime(2024, 3, 1, tzinfo=UTC)
    attendues = plan_l2_book("BTC", debut=d, fin=d + timedelta(hours=10))
    obtenues = [k.cle for k in attendues[:7]]          # 3 manquantes
    c = couverture("BTC", attendues, obtenues)
    assert c.n_attendues == 10 and c.n_obtenues == 7 and c.n_manquantes == 3
    assert c.taux == pytest.approx(0.7)


def test_une_couverture_vide_rend_zero_pas_une_division_par_zero() -> None:
    c = couverture("BTC", [], [])
    assert c.n_attendues == 0 and c.taux == 0.0


def test_une_cle_obtenue_hors_plan_ne_gonfle_PAS_la_couverture() -> None:
    """Sinon on pourrait « atteindre 100 % » avec des fichiers qu'on n'a pas demandes."""
    d = datetime(2024, 3, 1, tzinfo=UTC)
    attendues = plan_l2_book("BTC", debut=d, fin=d + timedelta(hours=3))
    c = couverture("BTC", attendues, ["market_data/19990101/0/l2Book/BTC.lz4"] * 50)
    assert c.n_obtenues == 0 and c.n_manquantes == 3


def test_cles3_uri_est_bien_formee() -> None:
    assert CleS3("b", "k").uri == "s3://b/k"
