"""A7 — ROTATION vers le meilleur carry net, AVEC hysteresis (anti-churn).

Le multi-coins (A2/#3) ouvre deja le top-K et ferme les sortants -> rotation de BASE. Mais sans
garde-fou, on churne : deux coins de carry net presque egal se font remplacer l'un l'autre a chaque
mesure, et chaque swap coute un round-trip (fermer + rouvrir = 2 sorties + 2 entrees, 2 jambes).

Ce module fournit la regle d'hysteresis : on ne remplace un carry ouvert par un meilleur QUE si le
gain net SUPPLEMENTAIRE couvre le cout de rotation. Sinon on garde l'ouvert (il gagne deja).

Unites : le net est en bps/24h (gain_net_24h_bps) ; le cout de rotation est un one-shot (bps).
Regle : (net_entrant - net_sortant) x horizon_jours >= cout_rotation. Horizon 1 jour par defaut
= il faut que le surplus quotidien rembourse la rotation en <= 1 jour. PAPER only.
"""
from __future__ import annotations

# fermer (2 jambes maker ~11) + rouvrir (2 jambes maker ~11) = ~22 bps de round-trip
COUT_ROTATION_BPS = 22.0
HORIZON_ROTATION_JOURS = 1.0


def rotation_justifiee(net_sortant_bps_24h: float, net_entrant_bps_24h: float, *,
                       cout_rotation_bps: float = COUT_ROTATION_BPS,
                       horizon_jours: float = HORIZON_ROTATION_JOURS) -> bool:
    """True si remplacer le carry sortant par l'entrant est justifie : le surplus de net quotidien
    rembourse le cout de rotation dans l'horizon. Sinon False (on ne churne pas pour un gain marginal)."""
    surplus = (float(net_entrant_bps_24h) - float(net_sortant_bps_24h)) * float(horizon_jours)
    return surplus > float(cout_rotation_bps)


def selection_avec_rotation(ouvertes_net: dict[str, float], candidats_net: dict[str, float], *,
                            max_slots: int, cout_rotation_bps: float = COUT_ROTATION_BPS,
                            horizon_jours: float = HORIZON_ROTATION_JOURS
                            ) -> tuple[list[str], list[str]]:
    """Décide (a_ouvrir, a_fermer_pour_rotation) sous contrainte de `max_slots`, avec hysteresis.
    `ouvertes_net` : coins ouverts -> leur net 24h. `candidats_net` : coins mesurés -> net 24h.
    On garde les ouverts ; on remplit les slots libres par les meilleurs candidats non ouverts ;
    si plein, on ne remplace un ouvert que si un candidat le bat de > cout de rotation."""
    ouverts = dict(ouvertes_net)
    non_ouverts = {c: n for c, n in candidats_net.items() if c not in ouverts}
    a_ouvrir: list[str] = []
    a_fermer: list[str] = []

    libres = int(max_slots) - len(ouverts)
    meilleurs = sorted(non_ouverts.items(), key=lambda kv: -kv[1])
    # 1) remplir les slots libres par les meilleurs candidats
    for coin, _net in meilleurs[:max(0, libres)]:
        a_ouvrir.append(coin)
    restants = meilleurs[max(0, libres):]

    # 2) slots pleins : rotation avec hysteresis (challenger vs le PIRE ouvert)
    ouverts_tries = sorted(ouverts.items(), key=lambda kv: kv[1])   # pire d'abord
    i = 0
    for coin, net_c in restants:
        if i >= len(ouverts_tries):
            break
        pire_coin, pire_net = ouverts_tries[i]
        if pire_coin in a_fermer:
            i += 1
        if i < len(ouverts_tries):
            pire_coin, pire_net = ouverts_tries[i]
            if rotation_justifiee(pire_net, net_c, cout_rotation_bps=cout_rotation_bps,
                                  horizon_jours=horizon_jours):
                a_fermer.append(pire_coin)
                a_ouvrir.append(coin)
                i += 1
    return a_ouvrir, a_fermer


__all__ = ["COUT_ROTATION_BPS", "HORIZON_ROTATION_JOURS", "rotation_justifiee", "selection_avec_rotation"]
