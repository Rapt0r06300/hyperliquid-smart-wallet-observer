"""#314 #315 #319 #525 #286 #312 #313 #384 #390 #302 #398 #544 — **et #303/#348**.

🔑 CE FICHIER **EST** LES TESTS DE PANNE ET DE CHARGE (#303 / #348, ~35 cas).
Ce ne sont pas des tests « en plus » : ce sont **les memes** modules, mis en panne exprès.

*On a eu DEUX stalls (02:32, 04:08) et personne n'a crie. Ici, tout ce qui se tait est un ECHEC.*
"""
from __future__ import annotations

import random

import pytest

from hl_observer.market.hlp_vault import (
    MOTIF_HLP_GAGNE,
    MOTIF_HLP_PERD,
    MOTIF_PAS_ASSEZ,
    PRIVILEGES,
    PointVault,
    comparer_a_nos_pistes,
    evaluer,
    parser_vault,
)
from hl_observer.realtime.ws_resilience import (
    BACKOFF_MAX_MS,
    MORT,
    MOTIF_DOUBLON,
    MOTIF_SILENCE,
    MOTIF_TROU,
    NON_MESURE,
    VIVANT,
    Canal,
    Dedup,
    DetecteurDeTrou,
    Heartbeat,
    allouer,
    delai_reconnexion_ms,
    rapport,
    rotation_atomique,
)
from hl_observer.runtime.replay_shadow import (
    MOTIF_DETERMINISTE,
    MOTIF_NON_DETERMINISTE,
    Decision,
    est_deterministe,
    rejouer,
    shadow,
)
from hl_observer.runtime.session_and_bus import (
    BACKTEST,
    LIVE,
    REPLAY,
    BusEvenements,
    SessionsMelangees,
    empreinte_du_flux,
    nouvelle_session,
)

J = 86_400_000


# ════════════════════════════════════════════════════════════════════════════════════════════
# PANNE 1-6 — LE FLUX SE TAIT (#314). *Un flux qui se tait n'est pas un flux calme.*
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_panne_le_silence_est_declare_MORT_pas_calme() -> None:
    hb = Heartbeat(silence_max_ms=30_000)
    hb.battre(maintenant_ms=1_000)
    assert hb.etat(maintenant_ms=20_000)[0] == VIVANT
    etat, detail = hb.etat(maintenant_ms=40_000)
    assert etat == MORT and MOTIF_SILENCE in detail
    assert "sur du VIEUX" in detail


def test_panne_AUCUN_message_recu_n_est_PAS_un_feu_vert() -> None:
    """🔴 cf. le panneau SECURITE dont le voyant vert etait SOUDE."""
    etat, d = Heartbeat().etat(maintenant_ms=999)
    assert etat == NON_MESURE and "PAS un feu vert" in d


def test_panne_l_horloge_du_heartbeat_est_LOCALE() -> None:
    """*Sinon on refait la TAUTOLOGIE de `signal_age` : le « maintenant » derive des donnees
    GELAIT quand le flux calait.*"""
    hb = Heartbeat(silence_max_ms=1_000)
    hb.battre(maintenant_ms=0)
    # le temps LOCAL avance meme si aucune donnee n'arrive -> le flux est declare MORT
    assert hb.etat(maintenant_ms=5_000)[0] == MORT


def test_panne_le_backoff_a_un_JITTER_obligatoire() -> None:
    """🔴 Sans jitter, **tous les clients se reconnectent en meme temps** et achevent le serveur."""
    r = random.Random(1)
    valeurs = {delai_reconnexion_ms(3, rng=r) for _ in range(30)}
    assert len(valeurs) > 5, "le backoff DOIT etre jittere, pas deterministe"


def test_panne_le_backoff_est_PLAFONNE() -> None:
    assert delai_reconnexion_ms(50) <= BACKOFF_MAX_MS


def test_panne_un_essai_negatif_est_REFUSE() -> None:
    with pytest.raises(ValueError):
        delai_reconnexion_ms(-1)


# ════════════════════════════════════════════════════════════════════════════════════════════
# PANNE 7-11 — LE TROU APRES RECONNEXION
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_panne_un_TROU_est_marque_pas_ignore() -> None:
    """*Une decision qui traverse un trou sans le savoir est un mensonge.*"""
    d = DetecteurDeTrou()
    for s in (1, 2, 3):
        assert d.voir(s)[0]
    ok, m = d.voir(10)                       # 4..9 manquent
    assert not ok and MOTIF_TROU in m
    assert d.n_manquants == 6
    assert "continuité est ROMPUE" in m


def test_panne_le_rapport_CRIE_quand_la_continuite_est_rompue() -> None:
    hb = Heartbeat(); hb.battre(maintenant_ms=0)
    t = DetecteurDeTrou(); t.voir(1); t.voir(5)
    r = rapport(hb, t, Dedup(), maintenant_ms=100)
    assert not r["continuite"]
    assert "FAUSSE sur cette periode" in r["avertissement"]


def test_panne_un_flux_CONTINU_n_alerte_pas() -> None:
    d = DetecteurDeTrou()
    for s in range(1, 100):
        assert d.voir(s)[0]
    assert d.n_manquants == 0


def test_panne_une_sequence_QUI_RECULE_est_un_doublon_pas_un_trou() -> None:
    d = DetecteurDeTrou(); d.voir(10)
    ok, m = d.voir(5)
    assert not ok and m == MOTIF_DOUBLON


def test_panne_un_FILL_compte_DEUX_FOIS_serait_un_PnL_DOUBLE() -> None:
    """🔴 *Exactement le genre de faux edge que ce projet fabrique.*"""
    dd = Dedup()
    assert dd.nouveau("fill-1")
    assert not dd.nouveau("fill-1")           # le rejeu apres reconnexion
    assert dd.doublons == 1


# ════════════════════════════════════════════════════════════════════════════════════════════
# CHARGE 12-14 — LE DEDUP TIENT-IL SOUS LA CHARGE ?
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_charge_100_000_messages_le_dedup_ne_explose_PAS() -> None:
    dd = Dedup(fenetre=1_000)
    for i in range(100_000):
        dd.nouveau(i)
    assert len(dd._vus) <= 1_000, "la fenetre BORNE la memoire"


def test_charge_le_dedup_oublie_les_TRES_vieux_et_le_dit() -> None:
    dd = Dedup(fenetre=3)
    for i in range(5):
        dd.nouveau(i)
    assert dd.nouveau(0), "0 est sorti de la fenetre : il repasse (limite ASSUMEE)"


def test_charge_le_dedup_bloque_les_doublons_RECENTS() -> None:
    dd = Dedup(fenetre=100)
    dd.nouveau("a")
    assert not dd.nouveau("a")


# ════════════════════════════════════════════════════════════════════════════════════════════
# 15-17 — #315 : LA ROTATION ATOMIQUE (jamais de periode aveugle)
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_la_rotation_S_ABONNE_D_ABORD_et_se_desabonne_ENSUITE() -> None:
    """🔴 *Entre un desabonnement et un abonnement, on ne voit RIEN -- et c'est precisement le
    moment ou un signal passe.*"""
    souscrire, desouscrire = rotation_atomique(["A", "B"], ["B", "C"])
    assert souscrire == ["C"]                  # ON S'ABONNE D'ABORD
    assert desouscrire == ["A"]                # on se desabonne ENSUITE


def test_la_rotation_ne_touche_PAS_ce_qui_reste() -> None:
    s, d = rotation_atomique(["A", "B"], ["A", "B"])
    assert s == [] and d == []


def test_une_rotation_TOTALE_ne_laisse_aucun_trou() -> None:
    s, d = rotation_atomique(["A"], ["B"])
    assert s == ["B"] and d == ["A"]


# ════════════════════════════════════════════════════════════════════════════════════════════
# 18-20 — #319 / #525 : LE BUDGET D'ABONNEMENTS
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_budget_alloue_par_VALEUR_MESUREE() -> None:
    r = allouer([Canal("cher_inutile", 0.1, 5), Canal("utile", 10.0, 1)], budget=2)
    assert r["retenus"] == ["utile"]


def test_un_canal_de_valeur_INCONNUE_n_est_PAS_souscrit() -> None:
    """*Un canal qu'on n'utilise pas est un canal qu'on rend.*"""
    r = allouer([Canal("inconnu", 0.0), Canal("utile", 1.0)], budget=10)
    assert r["retenus"] == ["utile"] and "inconnu" in r["ecartes"]


def test_le_budget_EPUISE_est_dit() -> None:
    r = allouer([Canal("a", 5.0), Canal("b", 4.0), Canal("c", 3.0)], budget=2)
    assert len(r["retenus"]) == 2 and r["ecartes"] == ["c"]


# ════════════════════════════════════════════════════════════════════════════════════════════
# 21-25 — #286 : ON NE MELANGE PAS DEUX SESSIONS. **JAMAIS.**
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_un_evenement_d_une_AUTRE_SESSION_est_refuse_BRUYAMMENT() -> None:
    """🔴 ***Un PnL qui melange deux runs est un PnL FAUX.*** Un refus bruyant vaut mieux qu'une
    moyenne silencieuse."""
    bus = BusEvenements(nouvelle_session(LIVE, graine="s1"))
    with pytest.raises(SessionsMelangees):
        bus.publier(1, "fill", {}, session_id="AUTRE")
    assert bus.refuses_autre_session == 1


def test_un_evenement_d_un_AUTRE_MODE_est_refuse() -> None:
    """*La regle du projet l'interdisait deja -- **rien ne l'imposait**.*"""
    bus = BusEvenements(nouvelle_session(LIVE, graine="s"))
    with pytest.raises(SessionsMelangees):
        bus.publier(1, "fill", {}, mode=BACKTEST)
    assert bus.refuses_autre_mode == 1


def test_un_mode_INCONNU_est_refuse_a_la_creation() -> None:
    with pytest.raises(ValueError):
        nouvelle_session("PEUT_ETRE")


def test_la_session_LIVE_est_reconnaissable() -> None:
    assert nouvelle_session(LIVE, graine="x").live
    assert not nouvelle_session(REPLAY, graine="x").live


def test_deux_sessions_de_MEME_graine_ont_le_MEME_id() -> None:
    a = nouvelle_session(LIVE, graine="g", maintenant_ms=0)
    b = nouvelle_session(LIVE, graine="g", maintenant_ms=0)
    assert a.session_id == b.session_id, "deterministe en test"


# ════════════════════════════════════════════════════════════════════════════════════════════
# 26-30 — #312/#313/#384/#390 + #302 : L'ORDRE TOTAL ET LE DETERMINISME
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_bus_rend_les_evenements_par_ordre_CHRONOLOGIQUE() -> None:
    """*L'ordre est celui du MONDE, pas celui d'une boucle de 10 secondes.*"""
    bus = BusEvenements(nouvelle_session(REPLAY, graine="s"))
    bus.publier(300, "c", None); bus.publier(100, "a", None); bus.publier(200, "b", None)
    assert [e.type for e in bus.drainer()] == ["a", "b", "c"]


def test_deux_evenements_a_la_MEME_milliseconde_sont_departages() -> None:
    bus = BusEvenements(nouvelle_session(REPLAY, graine="s"))
    bus.publier(100, "premier", None); bus.publier(100, "second", None)
    assert [e.type for e in bus.drainer()] == ["premier", "second"]


def test_LE_REJEU_EST_DETERMINISTE() -> None:
    """🔑 **L'INVARIANT LE PLUS FONDAMENTAL, ET ON NE L'AVAIT JAMAIS.**"""
    ev = [(i * 10, "tick", i) for i in range(50)]
    moteur = lambda e: Decision(e.t_ms, "ENTRER", "BTC") if e.charge % 7 == 0 else None
    r = est_deterministe(ev, moteur)
    assert r["deterministe"] and r["motif"] == MOTIF_DETERMINISTE


def test_UN_MOTEUR_NON_DETERMINISTE_EST_DEMASQUE() -> None:
    """🔴 *Aucune comparaison -- backtest, shadow, avant/apres -- n'a de sens s'il ne l'est pas.*"""
    ev = [(i * 10, "tick", i) for i in range(50)]
    moteur = lambda e: (Decision(e.t_ms, "ENTRER", "BTC")
                        if random.random() < 0.5 else None)     # <- NON deterministe
    r = est_deterministe(ev, moteur, n_rejeux=5)
    assert not r["deterministe"] and r["motif"] == MOTIF_NON_DETERMINISTE
    assert "n'a de sens" in r["detail"]


def test_un_rejeu_ne_peut_PAS_tourner_en_mode_LIVE() -> None:
    """🔒 *On ne melange JAMAIS un rejeu avec le live.*"""
    with pytest.raises(ValueError):
        rejouer([(1, "t", 1)], lambda e: None, session=nouvelle_session(LIVE, graine="x"))


# ════════════════════════════════════════════════════════════════════════════════════════════
# 31-32 — LE SHADOW MODE
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_shadow_compare_les_DECISIONS_pas_les_PnL() -> None:
    """🔴 *Deux moteurs peuvent avoir le MEME PnL en prenant des trades COMPLETEMENT differents.*
    **Une divergence de decision est un FAIT ; une divergence de PnL est une opinion.**"""
    ev = [(i, "tick", i) for i in range(20)]
    ancien = lambda e: Decision(e.t_ms, "ENTRER", "BTC") if e.charge % 2 == 0 else None
    nouveau = lambda e: Decision(e.t_ms, "ENTRER", "BTC") if e.charge % 4 == 0 else None
    c = shadow(ev, ancien, nouveau)
    assert c.accord == 5 and c.desaccord == 5
    assert len(c.seulement_ancien) == 5 and c.seulement_nouveau == []
    d = c.as_dict()
    assert d["shadow_peut_agir"] is False       # ⚠️ structurel
    assert "DÉCISIONS" in d["note"]


def test_deux_moteurs_IDENTIQUES_sont_en_accord_total() -> None:
    ev = [(i, "tick", i) for i in range(10)]
    m = lambda e: Decision(e.t_ms, "ENTRER", "BTC")
    c = shadow(ev, m, m)
    assert c.taux_accord == 1.0 and c.desaccord == 0


# ════════════════════════════════════════════════════════════════════════════════════════════
# 33-36 — #398 / #544 : LE VAULT HLP
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_HLP_qui_GAGNE_ne_REFUTE_PAS_T1b() -> None:
    """🔴 **LE TEST QUI COMPTE.** *Le market making marche -- POUR CELUI QUI EST PAYE POUR LE FAIRE.*"""
    pts = [PointVault(i * J, 1.0 + i * 0.0003) for i in range(200)]
    v = evaluer(pts)
    assert v is not None and v.motif == MOTIF_HLP_GAGNE
    assert v.apr > 0
    assert "ne REFUTE PAS T1b" in v.as_dict()["avertissement"]
    # les DEUX privileges qui expliquent tout : il est PAYE, et il est le LIQUIDATEUR
    p = " ".join(PRIVILEGES).lower()
    assert "liquidateur" in p and "frais" in p


def test_HLP_qui_PERD_confirme_T1b_de_la_maniere_la_plus_FORTE() -> None:
    """***Si meme le market maker PAYE pour l'etre perd, T1b est confirme.***"""
    pts = [PointVault(i * J, 1.0 - i * 0.0005) for i in range(200)]
    v = evaluer(pts)
    assert v is not None and v.motif == MOTIF_HLP_PERD
    assert "T1b est CONFIRMÉ" in v.note


def test_notre_meilleure_piste_comparee_a_un_DEPOT_PASSIF() -> None:
    """🎯 **La question qui tue.** T2b (~2 % APR) bat-il un simple depot dans HLP ?"""
    r = comparer_a_nos_pistes(0.15, apr_carry_hype=0.02)      # HLP a 15 %
    assert not r["notre_meilleure_piste_bat_HLP"]
    assert "dominée par un dépôt passif" in r["verdict"]
    assert "sans risque" in r["reserve"].lower()      # HLP porte l'inventaire : il RISQUE


def test_un_historique_TROP_COURT_ne_donne_AUCUN_chiffre() -> None:
    """*Un rendement sur quelques jours n'est pas un rendement.*"""
    v = evaluer([PointVault(0, 1.0), PointVault(5 * J, 1.5)])   # +50 % en 5 jours !
    assert v is not None and MOTIF_PAS_ASSEZ in v.motif
    assert v.apr == 0.0, "on ne PROJETTE PAS un APR sur 5 jours"
    assert evaluer([]) is None
    assert parser_vault({"portfolio": [[1, "abc"]]}) == []       # illisible -> ECARTE
    assert parser_vault({"portfolio": [[1, -5.0]]}) == []        # valeur absurde -> ECARTE
