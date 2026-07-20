"""FUNDING PRÉVISIONNEL — la meilleure idée du monde sur CETTE venue, portée chez nous.

ORIGINE (20/07, tour du monde demandé par Flo)
----------------------------------------------
La doc Hyperliquid et toute la littérature des desks convergent : le funding d'HL n'est pas
une loterie, c'est une FORMULE — `F = premium_moyen + clamp(taux_interet − P, ±0,05 %)`,
premium échantillonné toutes les 5 s contre l'ORACLE, moyenné sur l'heure, payé chaque heure.
Conséquence que les pros exploitent : **le premium COURANT prédit largement le funding de la
PROCHAINE heure**. « Current spot-perp basis is a strong predictor of the next funding. »

Nous mesurons déjà le premium à chaque passe (mark vs oracle). Ce module transforme cette
mesure en PRÉVISION — pour le TIMING, jamais pour gonfler un chiffre :

  * `prevoir_funding_bps_h(premium)` : la formule officielle, en bps/h ;
  * `tendance(prevu, actuel)`        : HAUSSE / BAISSE / STABLE ;
  * `facteur_prevision(...)`         : ≤ 1.0 — on RÉDUIT la taille quand on s'apprête à
    entrer dans une DÉCRUE (le funding affiché va fondre) ; on n'amplifie JAMAIS sur une
    prévision (le z-score A4, lui, amplifie sur du RÉALISÉ). Une prévision réduit le risque,
    elle ne fabrique pas un edge.

Le verdict `viable` du carry ne bouge pas d'un cheveu : il reste assis sur le funding
RÉALISÉ. La prévision n'est qu'une paire de lunettes de plus — orientée vers l'avant.

Constantes = la formule PUBLIQUE d'Hyperliquid (docs officielles), pas un calibrage à nous.
"""
from __future__ import annotations

#: taux d'intérêt du protocole : 0,01 %/8 h = 0,00125 %/h = 0,125 bps/h (« 11,6 % APR to short »)
TAUX_INTERET_BPS_H = 0.125
#: borne du clamp : ±0,05 % par heure = ±5 bps/h (la doc : clamp(interest − P, −0.0005, 0.0005))
BORNE_CLAMP_BPS_H = 5.0
#: bande morte de la tendance : sous ±20 % d'écart, on dit STABLE (pas de clignotement)
BANDE_TENDANCE = 0.20
#: décrue franche (prévu < 50 % de l'actuel) -> taille réduite de moitié à l'entrée
FACTEUR_DECRUE = 0.5

TENDANCE_HAUSSE = "HAUSSE"
TENDANCE_BAISSE = "BAISSE"
TENDANCE_STABLE = "STABLE"


def prevoir_funding_bps_h(premium_bps: float | None) -> float | None:
    """La formule officielle, alimentée par le premium COURANT (mark vs oracle, en bps).

    Comportements qu'elle explique — et que nos 105 096 relevés confirment :
      * premium ≈ 0    -> F ≈ 0,125 (LE plancher : 57 % de nos relevés y sont exactement) ;
      * premium grand  -> F ≈ premium (le clamp ne retient plus rien) ;
      * premium très négatif -> F plancher à premium + 5 (le clamp borne la remontée).
    """
    if premium_bps is None:
        return None
    p = float(premium_bps)
    correction = max(-BORNE_CLAMP_BPS_H, min(BORNE_CLAMP_BPS_H, TAUX_INTERET_BPS_H - p))
    return round(p + correction, 6)


def tendance(prevu_bps_h: float | None, actuel_bps_h: float | None) -> str:
    """HAUSSE / BAISSE / STABLE, avec bande morte anti-clignotement (leçon A2)."""
    if prevu_bps_h is None or actuel_bps_h is None or float(actuel_bps_h) == 0.0:
        return TENDANCE_STABLE
    ratio = float(prevu_bps_h) / float(actuel_bps_h)
    if ratio >= 1.0 + BANDE_TENDANCE:
        return TENDANCE_HAUSSE
    if ratio <= 1.0 - BANDE_TENDANCE:
        return TENDANCE_BAISSE
    return TENDANCE_STABLE


def facteur_prevision(prevu_bps_h: float | None, actuel_bps_h: float | None) -> float:
    """≤ 1.0, JAMAIS plus. Entrer plein pot dans une décrue annoncée par la formule même de
    la venue, c'est payer l'entrée sur un revenu qui fond. Décrue franche -> taille ÷ 2.
    Tout le reste (hausse comprise) -> 1.0 : on n'amplifie pas sur une prévision."""
    if prevu_bps_h is None or actuel_bps_h is None or float(actuel_bps_h) <= 0.0:
        return 1.0
    if float(prevu_bps_h) < FACTEUR_DECRUE * float(actuel_bps_h):
        return FACTEUR_DECRUE
    return 1.0




# ---------------- ALERTE DE RUPTURE DE BANDE MORTE (idees #1/#5/#9 de la vague 1, 20/07) ----
#: le premium doit depasser TAUX+BORNE (5,125 bps) pour que F decolle ; on alerte a l'APPROCHE.
SEUIL_APPROCHE_BPS = 4.0
#: build-up d'OI qui CONFIRME l'approche (la litterature : l'OI long precede le funding positif)
SEUIL_OI_CONFIRME_PCT = 2.0

NIVEAU_RUPTURE_HAUTE = "RUPTURE_HAUTE"      # F decolle DEJA (F = P - 5) -> spike en cours
NIVEAU_APPROCHE_HAUTE = "APPROCHE_HAUTE"    # 1 h d'avance : le premium approche la borne
NIVEAU_RUPTURE_BASSE = "RUPTURE_BASSE"      # funding profondement negatif imminent.
#                                           # ⚠️ HL ne permet PAS de shorter le spot (pas de
#                                           # margin spot) -> PAS d'ouverture inverse ici :
#                                           # c'est un signal pour le LIVRE CROSS-VENUE (Y2).
NIVEAU_APPROCHE_BASSE = "APPROCHE_BASSE"


def alerte_rupture(premium_bps: float | None,
                   delta_oi_pct: float | None = None) -> dict | None:
    """None = rien a signaler. Sinon {niveau, premium_bps, confirmee_par_oi, note}.

    La DECOUVERTE du 20/07 rendue operationnelle : le clamp cree une bande morte ±~5 bps ;
    le vrai signal avance d'un spike est 'le premium APPROCHE la borne'. L'OI en hausse
    (build-up de longs) CONFIRME l'approche haute — jamais requis, jamais invente."""
    if premium_bps is None:
        return None
    p = float(premium_bps)
    borne_haute = TAUX_INTERET_BPS_H + BORNE_CLAMP_BPS_H          # 5.125
    borne_basse = TAUX_INTERET_BPS_H - BORNE_CLAMP_BPS_H          # -4.875
    if p >= borne_haute:
        niveau = NIVEAU_RUPTURE_HAUTE
    elif p >= SEUIL_APPROCHE_BPS:
        niveau = NIVEAU_APPROCHE_HAUTE
    elif p <= borne_basse:
        niveau = NIVEAU_RUPTURE_BASSE
    elif p <= -SEUIL_APPROCHE_BPS:
        niveau = NIVEAU_APPROCHE_BASSE
    else:
        return None
    confirmee = (niveau in (NIVEAU_RUPTURE_HAUTE, NIVEAU_APPROCHE_HAUTE)
                 and isinstance(delta_oi_pct, (int, float))
                 and float(delta_oi_pct) >= SEUIL_OI_CONFIRME_PCT)
    notes = {
        NIVEAU_RUPTURE_HAUTE: "F decolle DEJA (F = P - 5) : spike de funding en cours",
        NIVEAU_APPROCHE_HAUTE: "premium approche la borne : spike possible d'ici ~1 h",
        NIVEAU_RUPTURE_BASSE: "funding profondement negatif imminent -- signal CROSS-VENUE "
                              "(HL ne short pas le spot : aucune ouverture inverse ici)",
        NIVEAU_APPROCHE_BASSE: "premium tres negatif : surveiller la rupture basse",
    }
    return {"niveau": niveau, "premium_bps": round(p, 4), "confirmee_par_oi": bool(confirmee),
            "note": notes[niveau] + (" — CONFIRMEE par build-up d'OI" if confirmee else "")}


__all__ = ["TAUX_INTERET_BPS_H", "BORNE_CLAMP_BPS_H", "BANDE_TENDANCE", "FACTEUR_DECRUE",
           "TENDANCE_HAUSSE", "TENDANCE_BAISSE", "TENDANCE_STABLE",
           "prevoir_funding_bps_h", "tendance", "facteur_prevision",
           "SEUIL_APPROCHE_BPS", "SEUIL_OI_CONFIRME_PCT", "alerte_rupture",
           "NIVEAU_RUPTURE_HAUTE", "NIVEAU_APPROCHE_HAUTE",
           "NIVEAU_RUPTURE_BASSE", "NIVEAU_APPROCHE_BASSE"]
