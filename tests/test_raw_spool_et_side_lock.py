"""#501 + #502 (raw spool / consommateur lent) et #566 (`only_per_side`).

🔴 #501/#502 sont **probablement la cause des stalls a 02:32 et 04:08** : le consommateur bloquait
la socket, et `signal_age` -- une tautologie -- **GELAIT** au lieu de crier. *Deux bugs qui se
cachaient l'un l'autre.*

🔴 #566 : **19 de nos 21 ouvertures etaient des SHORT.** P(hasard) = 2,2e-4 -> **1 chance sur
4 520.** Ce n'est PAS le hasard.
"""
from __future__ import annotations

import pytest

from hl_observer.realtime.raw_spool import (
    Compteurs,
    FileBornee,
    RawSpool,
    sante,
)
from hl_observer.risk.side_lock import (
    DESEQUILIBRE_MAX,
    LONG,
    MOTIF_BIAIS_DU_BOT,
    MOTIF_BIAIS_DU_MARCHE,
    MOTIF_EQUILIBRE,
    MOTIF_TROP_PEU,
    SHORT,
    diagnostiquer,
    only_per_side,
)


# ════════════════════════════════════════════════════════════════════════════════════════════
# #501 — LE RAW SPOOL : la trame brute AVANT le parsing
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_spool_ecrit_la_trame_BRUTE_et_la_relit(tmp_path) -> None:
    """*Si on parse mal, on perd la donnee POUR TOUJOURS.* Le spool ne juge pas."""
    p = tmp_path / "spool.jsonl"
    with RawSpool(p, flush_tous_les=1) as s:
        s.ecrire('{"channel":"trades","data":[1,2]}', recu_ms=1000)
        s.ecrire('pas du json du tout', recu_ms=1001)      # meme une trame ILLISIBLE est gardee
    lignes = list(RawSpool(p).relire())
    assert len(lignes) == 2
    assert lignes[0] == (1000, '{"channel":"trades","data":[1,2]}')
    assert lignes[1] == (1001, 'pas du json du tout')


def test_l_horodatage_vient_de_NOTRE_horloge_pas_des_donnees(tmp_path) -> None:
    """🔴 Sinon on refait la TAUTOLOGIE de `signal_age` : le « maintenant » derive des donnees
    **GELAIT** quand le flux calait -> un signal de 10 min restait « frais »."""
    p = tmp_path / "s.jsonl"
    with RawSpool(p, flush_tous_les=1) as s:
        s.ecrire('{"time": 999999999}', recu_ms=42)        # la trame ment sur son heure
    t, brut = next(iter(RawSpool(p).relire()))
    assert t == 42, "l'horodatage doit venir de la RECEPTION LOCALE, jamais du contenu"
    assert "999999999" in brut                              # le contenu reste intact


def test_une_ligne_de_spool_corrompue_est_SAUTEE_pas_devinee(tmp_path) -> None:
    p = tmp_path / "s.jsonl"
    p.write_text('{"recu_ms":1,"brut":"ok"}\nCORROMPU\n{"recu_ms":2,"brut":"ok2"}\n')
    assert [b for _, b in RawSpool(p).relire()] == ["ok", "ok2"]


# ════════════════════════════════════════════════════════════════════════════════════════════
# #502 — UN CONSOMMATEUR LENT NE DOIT JAMAIS BLOQUER LA SOCKET
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_la_file_ne_bloque_JAMAIS_meme_pleine() -> None:
    """***La socket ne doit jamais attendre le consommateur.*** On jette, mais on ne bloque pas."""
    f = FileBornee(taille_max=3)
    for i in range(10):
        f.deposer(i, recu_ms=1000 + i)                     # aucun appel bloquant possible
    assert len(f) == 3
    assert f.compteurs.recus == 10
    assert f.compteurs.jetes_file_pleine == 7


def test_on_jette_le_PLUS_ANCIEN_jamais_le_plus_recent() -> None:
    """Le marche ne s'interesse pas a un carnet vieux de 3 minutes."""
    f = FileBornee(taille_max=2)
    for i in range(5):
        f.deposer(i, recu_ms=1000 + i)
    restants = []
    while (m := f.retirer(maintenant_ms=1005)) is not None:
        restants.append(m[1])
    assert restants == [3, 4], "les PLUS RECENTS survivent"


def test_ce_qui_est_JETE_est_COMPTE() -> None:
    """🔴 *Une perte silencieuse est un mensonge ; une perte comptee est une mesure.*"""
    f = FileBornee(taille_max=2)
    for i in range(10):
        f.deposer(i, recu_ms=1000)
    c = f.compteurs
    assert c.perdus == 8
    assert c.taux_de_perte == pytest.approx(0.8)
    assert "sacree" in c.as_dict()["note"]


def test_un_message_TROP_VIEUX_est_jete_et_compte() -> None:
    f = FileBornee(taille_max=10, age_max_ms=1000)
    f.deposer("vieux", recu_ms=0)
    f.deposer("frais", recu_ms=5000)
    m = f.retirer(maintenant_ms=5100)
    assert m is not None and m[1] == "frais"
    assert f.compteurs.jetes_trop_vieux == 1


def test_le_voyant_de_sante_ne_peut_PAS_etre_SOUDE_AU_VERT() -> None:
    """cf. le panneau SECURITE dont le voyant etait soude. **Aucun message recu != feu vert.**"""
    assert sante(Compteurs())["etat"] == "NON_MESURE"
    ok = Compteurs(recus=1000, traites=1000)
    assert sante(ok)["etat"] == "OK"
    degrade = Compteurs(recus=1000, jetes_file_pleine=50)
    s = sante(degrade)
    assert s["etat"] == "DEGRADE"
    assert "n'a PAS bloque" in s["detail"]


def test_une_file_de_taille_zero_est_REFUSEE() -> None:
    with pytest.raises(ValueError):
        FileBornee(taille_max=0)


# ════════════════════════════════════════════════════════════════════════════════════════════
# #566 — 19 SHORT SUR 21 : bug du BOT, ou pari MACRO subi ?
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_NOS_19_SHORT_SUR_21_ne_sont_PAS_le_hasard() -> None:
    """🔴 **1 chance sur 4 520.** Ce chiffre exige une explication."""
    d = diagnostiquer([SHORT] * 19 + [LONG] * 2)
    assert d.part_short == pytest.approx(19 / 21)
    assert d.p_hasard < 1e-3
    assert 1 / d.p_hasard > 4000
    assert d.motif == MOTIF_BIAIS_DU_BOT           # signaux non fournis -> on ne tranche PAS
    assert "on ne peut pas encore dire" in d.note
    assert "maquiller le symptôme" in d.note


def test_signaux_EQUILIBRES_mais_ouvertures_biaisees_LE_BOT_BIAISE() -> None:
    """🔴 Le cas grave : le filtre n'est pas symetrique. **C'est un BUG.**"""
    d = diagnostiquer([SHORT] * 19 + [LONG] * 2,
                      cotes_signaux=[SHORT] * 50 + [LONG] * 50)
    assert d.motif == MOTIF_BIAIS_DU_BOT
    assert "LE BOT BIAISE" in d.note
    assert "gate asymétrique" in d.note


def test_signaux_DEJA_BIAISES_c_est_un_PARI_MACRO_non_voulu() -> None:
    """L'autre cas grave : on croit copier, on parie sur la baisse. **Sans l'avoir decide.**"""
    d = diagnostiquer([SHORT] * 19 + [LONG] * 2,
                      cotes_signaux=[SHORT] * 90 + [LONG] * 10)
    assert d.motif == MOTIF_BIAIS_DU_MARCHE
    assert "PARI DIRECTIONNEL NON VOULU" in d.note


def test_un_equilibre_normal_n_alerte_PAS() -> None:
    d = diagnostiquer([SHORT] * 11 + [LONG] * 10)
    assert d.motif == MOTIF_EQUILIBRE and d.p_hasard >= 0.05


def test_cinq_trades_ne_prouvent_RIEN() -> None:
    d = diagnostiquer([SHORT] * 5)
    assert d.motif.startswith(MOTIF_TROP_PEU)
    assert "n'est pas un déséquilibre" in d.note


def test_le_verrou_REFUSE_d_aggraver_un_desequilibre() -> None:
    ok, m = only_per_side(SHORT, ouvertures_en_cours=[SHORT] * 19 + [LONG] * 2)
    assert not ok and "91 %" in m
    # l'autre cote, lui, REEQUILIBRE -> autorise
    ok2, _ = only_per_side(LONG, ouvertures_en_cours=[SHORT] * 19 + [LONG] * 2)
    assert ok2


def test_le_verrou_peut_n_autoriser_QU_UN_cote() -> None:
    ok, m = only_per_side(SHORT, ouvertures_en_cours=[], cote_autorise=LONG)
    assert not ok and "seul LONG" in m
    assert only_per_side(LONG, ouvertures_en_cours=[], cote_autorise=LONG)[0]


def test_une_cote_inconnue_est_REFUSEE() -> None:
    assert not only_per_side("PEUT-ETRE", ouvertures_en_cours=[])[0]
    assert DESEQUILIBRE_MAX == 0.70
