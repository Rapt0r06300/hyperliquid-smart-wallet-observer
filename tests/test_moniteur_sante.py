"""[LANCEUR item 12] Moniteur de santé — boucle qui rafraîchit la zone dynamique + journalise chaque
passe. Prouvé sans réseau ni temps réel (état/horloge/sleep/sortie injectés).
"""
from __future__ import annotations

from hl_observer.ops import moniteur_sante as MS
from hl_observer.ops.preuve_de_vie import SourceAttendue

NOW = 1_700_000_000.0
SRCS = (SourceAttendue("bbo-collector", "HYPERLIQUID", "bbo", True),)


def test_boucle_rafraichit_et_journalise(tmp_path):
    clock = {"t": NOW}
    etat = {"n": 10}
    sorties: list[str] = []

    def lecteur():
        etat["n"] += 20
        hb = {"pid": 123, "ts_ms": clock["t"] * 1000, "n_ecrites_cumul": etat["n"],
              "dernier_exchange_ts": clock["t"] * 1000 - 50}
        return {"bbo-collector": hb}, {"bbo-collector": 123}, {}

    dernier = MS.boucle(tmp_path, sources=SRCS, passes=2, intervalle_s=1.0,
                        horloge=lambda: clock["t"], dormir=lambda s: clock.__setitem__("t", clock["t"] + s),
                        sortie=sorties.append, lecteur=lecteur, pid_vivant=lambda p: True,
                        horodateur=lambda t: "H%d" % int(t))

    assert len(sorties) == 2 and "TABLEAU DE SANTE" in sorties[0]         # zone dynamique ré-affichée
    journal = (tmp_path / MS.JOURNAL_RELPATH).read_text(encoding="utf-8").strip().splitlines()
    assert len(journal) == 2 and journal[0].startswith("[H")             # journal horodaté append-only
    assert dernier.lignes[0].events_par_s == 20.0                        # 20 events en 1 s (2e passe)


def test_une_passe_lit_l_etat_reel_vide_sans_crash(tmp_path):
    # aucune donnée sur disque -> tableau honnête (sources MANQUE), jamais d'exception
    tab = MS.une_passe(tmp_path, SRCS, now_ms=NOW * 1000, pid_vivant=lambda p: True,
                       precedent=None, horodatage="H0")
    assert len(tab.lignes) == 1 and tab.lignes[0].etat == "MANQUE"
