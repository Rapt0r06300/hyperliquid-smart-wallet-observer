"""M0 — GOUVERNEUR DE MEMOIRE : la RAM fait RETRECIR, elle ne fait JAMAIS CRASHER.

Exigence de Florent (12/11) : « il ne faut pas que ça fasse crash nos modules, on doit adapter la
puissance vis-à-vis de la ram utilisée, mais jamais crashé ». Deux passages du labo avaient été tués
par le reap mémoire (16 Go demandés, 6 Go libres). Ces tests verrouillent le contrat :

1. le niveau de pression prend le PIRE du critère absolu (Go libres) et du critère relatif (fraction) ;
2. la dégradation est PROGRESSIVE : on rétrécit le lot, on ne descend jamais à zéro ;
3. l'attente est BORNEE : on ne bloque jamais un pipeline indéfiniment pour de la RAM ;
4. le gouverneur ne lève JAMAIS, même avec un psutil cassé (fail-open prudent).

Tout est injectable : aucun test n'a besoin de vraie pression mémoire.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import budget_ram as B  # noqa: E402

GO = 1024 ** 3


class _FauxPsutil:
    """psutil minimal injectable : RAM dispo/totale fixées, RSS fixé."""

    def __init__(self, dispo: int, total: int = 32 * GO, rss: int = 1 * GO):
        self._dispo, self._total, self._rss = dispo, total, rss

    def virtual_memory(self):
        class _VM:
            available = self._dispo
            total = self._total
        return _VM()

    def Process(self, *_a, **_k):  # noqa: N802 — on imite l'API psutil
        rss = self._rss

        class _P:
            def memory_info(self_inner):
                class _M:
                    pass
                m = _M()
                m.rss = rss
                return m
        return _P()


class _PsutilCasse:
    """psutil qui explose à chaque appel : le gouverneur doit rester muet et prudent."""

    def virtual_memory(self):
        raise RuntimeError("psutil casse")

    def Process(self, *_a, **_k):  # noqa: N802
        raise RuntimeError("psutil casse")


# ---------------------------------------------------------------- niveau de pression

def test_niveau_vert_quand_la_ram_est_saine():
    assert B.niveau_pression(dispo_octets=16 * GO, total_octets=32 * GO) == B.VERT


def test_niveau_orange_par_le_critere_absolu():
    # 5 Go libres sur 32 : 15,6 % (> 12 %) mais <= 6 Go => ORANGE par le seuil absolu
    assert B.niveau_pression(dispo_octets=5 * GO, total_octets=32 * GO) == B.ORANGE


def test_niveau_rouge_par_le_critere_absolu():
    assert B.niveau_pression(dispo_octets=2 * GO, total_octets=32 * GO) == B.ROUGE


def test_niveau_rouge_par_le_critere_RELATIF_meme_avec_beaucoup_de_go_libres():
    """LE cas que le seuil absolu seul raterait : 10 Go libres, mais sur une machine de 100 Go c'est
    10 % => critique. On prend le PIRE des deux critères, pas le plus indulgent."""
    assert B.niveau_pression(dispo_octets=10 * GO, total_octets=100 * GO) == B.ROUGE


def test_niveau_orange_par_le_critere_relatif():
    assert B.niveau_pression(dispo_octets=20 * GO, total_octets=100 * GO) == B.ORANGE


def test_les_seuils_sont_reglables_par_environnement(monkeypatch):
    """Florent doit pouvoir durcir le seuil sans toucher au code.

    (20 Go sur 64 = 31 % : VERT par les deux criteres. En durcissant le seuil absolu a 25 Go, la
    meme machine passe ROUGE — on verifie bien l'effet du reglage, pas un hasard de fraction.)"""
    assert B.niveau_pression(dispo_octets=20 * GO, total_octets=64 * GO) == B.VERT
    monkeypatch.setenv(B.ENV_SEUIL_ROUGE_GO, "25")
    assert B.niveau_pression(dispo_octets=20 * GO, total_octets=64 * GO) == B.ROUGE


def test_un_seuil_illisible_ou_negatif_retombe_sur_le_defaut(monkeypatch):
    monkeypatch.setenv(B.ENV_SEUIL_ROUGE_GO, "pas-un-nombre")
    assert B.niveau_pression(dispo_octets=16 * GO, total_octets=32 * GO) == B.VERT
    monkeypatch.setenv(B.ENV_SEUIL_ROUGE_GO, "-5")
    assert B.niveau_pression(dispo_octets=16 * GO, total_octets=32 * GO) == B.VERT


def test_seuils_incoherents_ne_cassent_pas_l_ordre(monkeypatch):
    """ORANGE réglé SOUS ROUGE : on ne doit pas obtenir un classement absurde ni une exception."""
    monkeypatch.setenv(B.ENV_SEUIL_ROUGE_GO, "8")
    monkeypatch.setenv(B.ENV_SEUIL_ORANGE_GO, "2")
    assert B.niveau_pression(dispo_octets=5 * GO, total_octets=64 * GO) == B.ROUGE


# ---------------------------------------------------------------- dégradation progressive

def test_le_facteur_d_ampleur_retrecit_par_palier():
    assert B.facteur_d_ampleur(B.VERT) == 1.0
    assert B.facteur_d_ampleur(B.ORANGE) == 0.5
    assert B.facteur_d_ampleur(B.ROUGE) == 0.25


def test_un_niveau_inconnu_prend_le_plus_prudent():
    assert B.facteur_d_ampleur("PERDU") == B.FACTEURS_AMPLEUR[B.ROUGE]


def test_reduire_ampleur_retrecit_sans_jamais_atteindre_zero():
    assert B.reduire_ampleur(1000, niveau=B.VERT) == 1000
    assert B.reduire_ampleur(1000, niveau=B.ORANGE) == 500
    assert B.reduire_ampleur(1000, niveau=B.ROUGE) == 250
    # un tout petit lot en ROUGE ne doit pas tomber à 0 : zéro serait un blocage déguisé
    assert B.reduire_ampleur(2, niveau=B.ROUGE) >= 1
    assert B.reduire_ampleur(1, niveau=B.ROUGE) >= 1


def test_reduire_ampleur_respecte_un_plancher_metier():
    assert B.reduire_ampleur(1000, niveau=B.ROUGE, mini=400) == 400


def test_reduire_ampleur_encaisse_une_entree_absurde():
    assert B.reduire_ampleur("bof", niveau=B.ROUGE) >= 1          # type: ignore[arg-type]
    assert B.reduire_ampleur(0, niveau=B.VERT) >= 1
    assert B.reduire_ampleur(-10, niveau=B.VERT) >= 1


# ---------------------------------------------------------------- demande d'allocation

def test_assez_de_memoire_applique_la_marge_de_securite():
    # besoin 4 Go, marge x1,5 => il faut 6 Go ; avec 5 Go dispo, c'est NON
    assert B.assez_de_memoire_pour(4 * GO, dispo_octets=5 * GO) is False
    assert B.assez_de_memoire_pour(4 * GO, dispo_octets=7 * GO) is True


def test_un_besoin_nul_ou_absurde_est_toujours_permis():
    assert B.assez_de_memoire_pour(0, dispo_octets=1) is True
    assert B.assez_de_memoire_pour(-5, dispo_octets=1) is True
    assert B.assez_de_memoire_pour("bof", dispo_octets=1) is True   # type: ignore[arg-type]


# ---------------------------------------------------------------- décision

def test_decision_continue_quand_tout_va_bien():
    d = B.decision(dispo_octets=16 * GO, total_octets=32 * GO)
    assert d["action"] == B.CONTINUER and d["niveau"] == B.VERT and d["facteur"] == 1.0


def test_decision_reduit_en_orange():
    d = B.decision(dispo_octets=5 * GO, total_octets=32 * GO)
    assert d["action"] == B.REDUIRE and d["facteur"] == 0.5
    assert "tendue" in d["raison"]


def test_decision_pause_en_rouge_mais_ne_dit_jamais_d_abandonner():
    d = B.decision(dispo_octets=2 * GO, total_octets=32 * GO)
    assert d["action"] == B.PAUSER and d["facteur"] == 0.25
    assert d["action"] in {B.CONTINUER, B.RALENTIR, B.REDUIRE, B.PAUSER}   # jamais « ABANDONNER »


def test_une_demande_trop_grosse_durcit_la_decision_meme_en_vert():
    """Le cas du labo : la RAM est « saine » mais on s'apprête à demander 16 Go. Il faut rétrécir
    AVANT, pas découvrir le problème en se faisant tuer."""
    d = B.decision(besoin_octets=16 * GO, dispo_octets=16 * GO, total_octets=32 * GO)
    assert d["niveau"] == B.VERT          # la RAM seule semblait saine
    assert d["action"] == B.REDUIRE       # mais la demande ne passe pas avec la marge
    assert d["facteur"] <= 0.5
    assert "besoin estime" in d["raison"]


def test_etat_memoire_expose_tout_le_necessaire():
    e = B.etat_memoire(dispo_octets=8 * GO, total_octets=32 * GO,
                       psutil_mod=_FauxPsutil(8 * GO, 32 * GO, rss=3 * GO))
    for cle in ("dispo_octets", "total_octets", "rss_octets", "dispo_go", "total_go", "rss_go",
                "fraction_libre", "niveau"):
        assert cle in e
    assert e["dispo_go"] == 8.0 and e["total_go"] == 32.0 and e["rss_go"] == 3.0
    assert e["fraction_libre"] == 0.25


# ---------------------------------------------------------------- attente bornée

class _Horloge:
    """Horloge et sommeil factices : le sommeil fait AVANCER l'horloge (pas de vraie attente)."""

    def __init__(self):
        self.t = 0.0
        self.dormi = 0

    def maintenant(self):
        return self.t

    def dormir(self, d):
        self.t += float(d)
        self.dormi += 1


def test_l_attente_s_arrete_des_que_ca_respire():
    h = _Horloge()
    etats = [1 * GO, 1 * GO, 20 * GO, 20 * GO]       # ROUGE, ROUGE, puis ça se libère

    def dispo():
        return etats.pop(0) if etats else 20 * GO

    r = B.attendre_que_ca_respire(limite_s=30, pas_s=1, dormir=h.dormir, horloge=h.maintenant,
                                  dispo_octets=dispo, total_octets=32 * GO)
    assert r["a_respire"] is True
    assert r["tours"] == 2
    assert r["niveau"] != B.ROUGE


def test_l_attente_est_BORNEE_et_rend_la_main_meme_si_ca_ne_respire_jamais():
    """Le point non négociable : on ne bloque JAMAIS le pipeline indéfiniment pour de la RAM."""
    h = _Horloge()
    r = B.attendre_que_ca_respire(limite_s=5, pas_s=1, dormir=h.dormir, horloge=h.maintenant,
                                  dispo_octets=lambda: 1 * GO, total_octets=32 * GO)
    assert r["a_respire"] is False
    assert r["niveau"] == B.ROUGE
    assert r["tours"] <= 5 and r["attendu_s"] <= 5.0      # borné, et terminé


def test_une_limite_nulle_ne_dort_pas_du_tout():
    h = _Horloge()
    r = B.attendre_que_ca_respire(limite_s=0, pas_s=1, dormir=h.dormir, horloge=h.maintenant,
                                  dispo_octets=lambda: 1 * GO, total_octets=32 * GO)
    assert r["tours"] == 0 and h.dormi == 0


def test_une_panne_transitoire_du_sommeil_ne_tue_pas_le_pipeline():
    """Un sommeil qui echoue (signal, horloge systeme, EINTR) ne doit pas faire tomber le pipeline :
    on sort de l'attente et on continue en mode degrade."""
    def dormir_qui_echoue(_):
        raise OSError("EINTR : sommeil interrompu par le systeme")

    h = _Horloge()
    r = B.attendre_que_ca_respire(limite_s=5, pas_s=1, dormir=dormir_qui_echoue,
                                  horloge=h.maintenant, dispo_octets=lambda: 1 * GO,
                                  total_octets=32 * GO)
    assert r["niveau"] == B.ROUGE and r["tours"] == 0     # sorti proprement, sans propager


def test_un_CTRL_C_doit_au_contraire_SE_PROPAGER():
    """Contrat inverse, tout aussi important : le gouverneur ne doit PAS avaler un Ctrl+C. Le projet
    a deja paye cette lecon sur les collecteurs (arret immediat exige). `except Exception` laisse
    passer KeyboardInterrupt/SystemExit : ce test verrouille ce comportement."""
    import pytest

    def dormir_interrompu(_):
        raise KeyboardInterrupt("Ctrl+C de l'utilisateur")

    h = _Horloge()
    with pytest.raises(KeyboardInterrupt):
        B.attendre_que_ca_respire(limite_s=5, pas_s=1, dormir=dormir_interrompu,
                                  horloge=h.maintenant, dispo_octets=lambda: 1 * GO,
                                  total_octets=32 * GO)


# ---------------------------------------------------------------- fail-open : jamais d'exception

def test_un_psutil_casse_ne_fait_jamais_lever_le_gouverneur():
    casse = _PsutilCasse()
    # chaque point d'entrée doit répondre, prudemment, sans exception
    assert B.memoire_disponible_octets(psutil_mod=casse) > 0
    assert B.memoire_totale_octets(psutil_mod=casse) > 0
    assert B.memoire_du_processus_octets(psutil_mod=casse) == 0
    assert B.niveau_pression(psutil_mod=casse) in {B.VERT, B.ORANGE, B.ROUGE}
    d = B.decision(psutil_mod=casse)
    assert d["action"] in {B.CONTINUER, B.RALENTIR, B.REDUIRE, B.PAUSER}
    assert isinstance(B.journal_memoire(psutil_mod=casse), str)


def test_sans_psutil_du_tout_on_reste_prudent_et_vivant():
    """psutil absent (module None) : on retombe sur le défaut conservateur, sans lever."""
    assert B.memoire_du_processus_octets(psutil_mod=None) >= 0
    assert B.niveau_pression(dispo_octets=None, total_octets=None) in {B.VERT, B.ORANGE, B.ROUGE}


def test_journal_memoire_est_une_ligne_lisible():
    ligne = B.journal_memoire("labo", dispo_octets=4 * GO, total_octets=32 * GO,
                              psutil_mod=_FauxPsutil(4 * GO, 32 * GO, rss=2 * GO))
    assert ligne.startswith("[labo]")
    assert "libre 4.0 Go / 32.0 Go" in ligne
    assert "ce processus 2.0 Go" in ligne
    assert "\n" not in ligne


# ---------------------------------------------------------------- non-régression de l'existant

def test_la_couche_historique_est_intacte():
    """Le gouverneur est ADDITIF : `lab_alpha` et les tests existants doivent continuer de marcher."""
    assert B.resoudre_max_events(123_456, dispo_octets=8 * GO) == 123_456
    assert B.resoudre_max_events(0, dispo_octets=8 * GO) <= B.MAXI_EVENTS
    assert B.budget_events(dispo_octets=1024) == B.MINI_EVENTS
