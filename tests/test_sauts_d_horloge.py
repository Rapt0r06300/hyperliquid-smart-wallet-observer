"""DÉTECTION DES SAUTS D'HORLOGE (17/11/2026) : un recul de l'heure murale crée une fenêtre où un
carnet reçu APRÈS un signal peut paraître reçu AVANT. Voir `hl_observer.ops.sauts_d_horloge`.
"""
from __future__ import annotations

import inspect

import tunnel_executabilite as T

from hl_observer.ops import sauts_d_horloge as H

T0 = 1_800_000_000_000


def _ligne(detecteur, mono_ms: float, decalage_ms: float = 0.0) -> int:
    """Une ligne reçue à l'instant monotone ``mono_ms`` ; l'heure murale est décalée de ``decalage_ms``."""
    recu = int(T0 + mono_ms + decalage_ms)
    detecteur.observer(recu, int(mono_ms * 1e6))
    return recu


def test_horloges_d_accord_aucun_saut():
    d = H.Detecteur()
    for k in range(200):
        _ligne(d, k * 137.0, decalage_ms=(k % 7) - 3)          # gigue de quelques millisecondes
    bilan = d.bilan()
    assert bilan["verdict"] == H.VERDICT_OK
    assert bilan["sauts_en_avant"] == 0 and bilan["sauts_en_arriere"] == 0
    assert bilan["lignes_avec_horloge_monotone"] == 200


def test_le_saut_EN_AVANT_du_reveil_est_vu_et_ne_rend_rien_ambigu():
    """Le cas réel du 17/11 : 42 min de veille, puis l'heure avancée de ~1,2 s."""
    d = H.Detecteur()
    _ligne(d, 0)
    _ligne(d, 1_000)
    recu = _ligne(d, 2_593_000, decalage_ms=1_195)
    bilan = d.bilan()
    assert bilan["verdict"] == H.VERDICT_OK, "un saut en avant conserve l'ordre de réception"
    assert bilan["sauts_en_avant"] == 1 and bilan["exemples_en_avant"][0]["saut_ms"] == 1195
    assert not d.ambigu(recu)


def test_un_saut_EN_ARRIERE_ouvre_une_fenetre_ambigue():
    d = H.Detecteur()
    avant = _ligne(d, 10_000, decalage_ms=800)                  # l'heure avance de 800 ms
    apres = _ligne(d, 10_200)                                   # Windows la recule de 800 ms
    bilan = d.bilan()
    assert bilan["verdict"] == H.VERDICT_AMBIGU
    assert bilan["sauts_en_arriere"] == 1 and bilan["plus_grand_recul_ms"] == 800
    exemple = bilan["exemples_en_arriere"][0]
    assert exemple["fenetre_debut_ms"] <= apres - 800 and exemple["fenetre_fin_ms"] >= avant
    assert d.ambigu(apres) and d.ambigu(avant)
    assert not d.ambigu(avant + 5_000), "la fenêtre est bornée"


def test_un_signal_recu_dans_la_fenetre_est_compte_comme_refuse():
    d = H.Detecteur()
    _ligne(d, 10_000, decalage_ms=800)
    apres = _ligne(d, 10_200)
    assert d.ambigu(apres)
    d.noter_signal(apres, refuse=True)
    assert d.bilan()["signaux_refuses_dans_une_fenetre"] == 1


def test_les_signaux_DEJA_juges_avant_le_saut_sont_comptes_apres_coup():
    """Le saut n'est connu qu'en lisant la ligne suivante : ceux d'avant ont déjà été jugés."""
    d = H.Detecteur()
    for mono in (9_000, 9_600, 9_900):
        d.noter_signal(_ligne(d, mono, decalage_ms=800))
    d.noter_signal(_ligne(d, 1_000, decalage_ms=800))            # trop ancien pour la fenêtre
    _ligne(d, 10_200)
    assert d.bilan()["signaux_deja_juges_dans_une_fenetre"] == 3


def test_des_lignes_lues_dans_le_DESORDRE_ne_sont_pas_un_saut():
    """Le coffre ne rend pas les lignes dans l'ordre de réception : les deux horloges reculent ensemble."""
    d = H.Detecteur()
    for mono in (50_000, 10_000, 90_000, 20_000, 5_000):
        _ligne(d, mono)
    bilan = d.bilan()
    assert bilan["sauts_en_arriere"] == 0 and bilan["sauts_en_avant"] == 0


def test_un_redemarrage_lu_dans_le_desordre_n_est_PAS_un_recul_d_horloge():
    d = H.Detecteur()
    d.observer(T0 + 86_400_000, 5_000_000_000)                  # après redémarrage : monotone petite
    d.observer(T0, 400_000_000_000_000)                         # avant : monotone énorme
    bilan = d.bilan()
    assert bilan["sauts_en_arriere"] == 0 and bilan["redemarrages_lus_dans_le_desordre"] == 1
    assert bilan["verdict"] == H.VERDICT_OK


def test_sans_horloge_monotone_le_verdict_est_NON_MESURABLE_pas_OK():
    d = H.Detecteur()
    for k in range(5):
        d.observer(T0 + k, None)
    bilan = d.bilan()
    assert bilan["verdict"] == H.VERDICT_NON_MESURABLE
    assert bilan["lignes_sans_horloge_monotone"] == 5 and bilan["lignes_avec_horloge_monotone"] == 0


def test_les_types_inattendus_ne_levent_pas():
    d = H.Detecteur()
    d.observer("1800000000000", 12)
    d.observer(True, 12)
    d.observer(T0, 12.5)
    assert d.bilan()["lignes_sans_horloge_monotone"] == 3 and not d.ambigu(None)


def test_un_ecart_egal_au_seuil_n_est_pas_un_saut():
    d = H.Detecteur()
    _ligne(d, 0)
    _ligne(d, 1_000, decalage_ms=H.SEUIL_MS)
    _ligne(d, 2_000)
    assert d.bilan()["sauts_en_avant"] == 0 and d.bilan()["sauts_en_arriere"] == 0


def test_le_nombre_d_exemples_est_borne_mais_le_compte_est_exact():
    d = H.Detecteur(max_exemples=3)
    decalage = 0.0
    for k in range(10):
        decalage += 500
        _ligne(d, k * 1_000.0, decalage_ms=decalage)
    bilan = d.bilan()
    assert bilan["sauts_en_avant"] == 9 and len(bilan["exemples_en_avant"]) == 3


def test_le_tunnel_observe_chaque_fill_refuse_les_signaux_ambigus_et_publie_le_bilan():
    source = inspect.getsource(T.mesurer)
    assert "horloge = SAUTS.Detecteur()" in source
    assert 'horloge.observer(recu, fill.get("recv_mono_ns"))' in source
    assert 'motifs["SAUT_D_HORLOGE_EN_ARRIERE"] += 1' in source
    assert '"sauts_d_horloge": horloge.bilan()' in source
