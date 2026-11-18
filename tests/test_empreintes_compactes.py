"""L'ENSEMBLE D'IDENTITÉS COMPACT : se comporter comme un `set`, pour dix-huit fois moins de mémoire.

Le 18/11/2026, un scellement du coffre a atteint **9,13 Go** et fait tomber la machine à 1,8 Go de
RAM libre, menaçant des collecteurs qui tournaient depuis 21 heures. La cause : un `set` de tuples
d'identité, dont un `hash` de transaction de 66 caractères pour les fills.

Ces tests vérifient les deux choses qui comptent : qu'il **répond comme un `set`** (sans quoi la
déduplication changerait de résultat), et qu'il **tient la promesse de mémoire** (sans quoi il n'y
avait aucune raison de l'écrire).
"""
from __future__ import annotations

import random

from hl_observer.datasets.empreintes_compactes import (
    TAMPON_MAX,
    EnsembleDIdentites,
    empreinte,
)


def _identite(i: int) -> tuple:
    """La forme réelle d'une identité de fill : famille, hash de 66 caractères, vault, instant."""
    return ("fills_forward", "0x%064x" % i, "vault%d" % (i % 50), 1_700_000_000_000 + i)


# ───────────────────────── l'empreinte ─────────────────────────

def test_l_empreinte_est_DETERMINISTE():
    """Une reprise doit retrouver ses doublons : deux exécutions, la même empreinte."""
    assert empreinte(_identite(7)) == empreinte(_identite(7))


def test_deux_identites_DIFFERENTES_ont_des_empreintes_differentes():
    vues = {empreinte(_identite(i)) for i in range(5_000)}
    assert len(vues) == 5_000, "aucune collision sur 5 000 identités"


def test_l_empreinte_fait_bien_128_bits():
    haut, bas = empreinte(_identite(1))
    assert 0 <= haut < 2 ** 64 and 0 <= bas < 2 ** 64


def test_des_identites_de_FORMES_differentes_sont_distinguees():
    """Les familles n'ont pas toutes la même forme de clé."""
    formes = [
        ("vault_snapshot", "0xA", 1_000),
        ("vault_snapshot", "0xA", 1_000, "dex"),
        ("explorer_tx", "0xh", "0xu", "open", 1_000),
        ("micro_bbo", "BTC", 1_000, "somme"),
    ]
    assert len({empreinte(f) for f in formes}) == len(formes)


# ───────────────────────── il répond comme un `set` ─────────────────────────

def test_ce_qu_on_ajoute_est_RETROUVE():
    ens = EnsembleDIdentites()
    for i in range(100):
        ens.add(_identite(i))
    assert all(_identite(i) in ens for i in range(100))


def test_ce_qu_on_n_a_PAS_ajoute_est_absent():
    ens = EnsembleDIdentites(_identite(i) for i in range(100))
    assert all(_identite(i) not in ens for i in range(100, 200))


def test_ajouter_DEUX_FOIS_ne_compte_qu_une_fois():
    ens = EnsembleDIdentites()
    ens.add(_identite(1))
    ens.add(_identite(1))
    assert len(ens) == 1


def test_un_ensemble_VIDE_ne_contient_rien():
    ens = EnsembleDIdentites()
    assert len(ens) == 0 and _identite(1) not in ens


def test_il_se_comporte_comme_un_SET_sur_des_milliers_d_operations():
    """La comparaison qui compte : même réponse qu'un `set` ordinaire, opération par opération."""
    alea = random.Random(20261118)
    reference: set = set()
    compact = EnsembleDIdentites()
    for _ in range(8_000):
        i = alea.randrange(2_000)
        cle = _identite(i)
        assert (cle in compact) == (cle in reference), i
        if alea.random() < 0.6:
            reference.add(cle)
            compact.add(cle)
    assert len(compact) == len(reference)


def test_la_FUSION_du_tampon_ne_perd_rien():
    """Le tampon se vide dans les tableaux triés : aucune identité ne doit disparaître."""
    ens = EnsembleDIdentites()
    total = TAMPON_MAX + 2_500
    for i in range(total):
        ens.add(_identite(i))
    assert len(ens) == total
    assert all(_identite(i) in ens for i in (0, 1, TAMPON_MAX - 1, TAMPON_MAX, total - 1))
    assert ens.bilan()["fusions"] >= 1, "le tampon a bien été fusionné au moins une fois"


def test_la_construction_depuis_un_ITERABLE_marche():
    ens = EnsembleDIdentites(_identite(i) for i in range(50))
    assert len(ens) == 50 and _identite(25) in ens


# ───────────────────────── il tient la promesse de mémoire ─────────────────────────

def test_il_consomme_BEAUCOUP_moins_qu_un_set_de_tuples():
    """Sans ce gain, il n'y avait aucune raison d'écrire ce conteneur.

    On mesure ce qui RESTE après insertion, pas le pic : le scelleur garde cet ensemble pendant
    tout le scellement, et c'est cette mémoire-là qui a fait tomber la machine à 1,8 Go libres.
    Le pic du conteneur compact est plus élevé que son reste — il alloue une empreinte par appel,
    aussitôt jetée — et mesurer le pic m'avait d'abord fait croire qu'il ne gagnait rien.

    L'identité est créée À LA VOLÉE dans les deux cas, comme le fait le scelleur : c'est ce qui
    distingue les deux formes, puisque le `set` RETIENT ces tuples et le compact non.
    """
    import gc
    import tracemalloc

    n = 40_000
    restes = {}
    for nom in ("set", "compact"):
        gc.collect()
        tracemalloc.start()
        depart = tracemalloc.get_traced_memory()[0]
        if nom == "set":
            conteneur: object = set()
            for i in range(n):
                conteneur.add(_identite(i))  # type: ignore[attr-defined]
        else:
            conteneur = EnsembleDIdentites()
            for i in range(n):
                conteneur.add(_identite(i))  # type: ignore[attr-defined]
            conteneur.bilan()                # type: ignore[attr-defined]
        gc.collect()
        restes[nom] = tracemalloc.get_traced_memory()[0] - depart
        tracemalloc.stop()
        del conteneur

    assert restes["compact"] * 10 < restes["set"], (
        f'attendu au moins dix fois moins : {restes["compact"]:,} contre {restes["set"]:,}')
    assert restes["compact"] / n < 30, (
        f'attendu ~16 octets par entrée, mesuré {restes["compact"] / n:.1f}')

def test_le_bilan_dit_ce_qu_il_contient_et_ce_qu_il_a_coute():
    ens = EnsembleDIdentites(_identite(i) for i in range(1_000))
    bilan = ens.bilan()
    assert bilan["identites"] == 1_000
    assert bilan["octets_approximatifs"] == 16_000
    assert "fusions" in bilan


def test_le_bilan_VIDE_le_tampon_donc_il_est_stable_apres_appel():
    ens = EnsembleDIdentites(_identite(i) for i in range(10))
    assert ens.bilan()["identites"] == 10
    assert ens.bilan()["identites"] == 10, "appeler deux fois ne change rien"
