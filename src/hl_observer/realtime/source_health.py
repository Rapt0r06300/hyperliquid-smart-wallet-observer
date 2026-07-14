"""SANTÉ DES SOURCES — interdire le faux « OK » (2026-07-11). Phase 12 du brief.

LE BUG : `realtime_health.check_realtime_health` juge la sante sur **l'age du fichier de log**.
Des logs qui s'ecrivent => statut `LIVE_FROM_LOCAL_LOGS`. Meme si ces logs ne contiennent QUE des
refus et **zero signal frais**.

Autrement dit : le systeme se declare en bonne sante parce qu'il ECRIT, pas parce qu'il SERT.
C'est le meme genre de mensonge que "controles reussis" avec toutes les preuves a `null` : une
apparence de fonctionnement qui empeche de voir que rien ne fonctionne.

LA DISTINCTION QUI MANQUAIT, ET QUI EST TOUT LE SUJET :

    HEALTHY          la source va bien ET produit des signaux frais
    NO_FRESH_SIGNAL  la source va techniquement bien... et ne produit RIEN d'exploitable

**Ce ne sont PAS le meme etat.** Les confondre, c'est laisser un bot tourner des heures en croyant
qu'il travaille. Le dashboard doit montrer les deux SEPAREMENT.

Les 9 etats du brief, du meilleur au pire :
    HEALTHY | NO_FRESH_SIGNAL | DEGRADED | STALE | RECONNECTING | GAP_DETECTED
    | BACKPRESSURED | DATA_INCOMPLETE | CRITICAL

PUR, sans I/O. Aucun ordre reel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

HEALTHY = "HEALTHY"
NO_FRESH_SIGNAL = "NO_FRESH_SIGNAL"
DEGRADED = "DEGRADED"
STALE = "STALE"
RECONNECTING = "RECONNECTING"
GAP_DETECTED = "GAP_DETECTED"
BACKPRESSURED = "BACKPRESSURED"
DATA_INCOMPLETE = "DATA_INCOMPLETE"
CRITICAL = "CRITICAL"

# Du plus grave au moins grave : en cas de cumul, c'est le PIRE qui est rapporte.
# (un systeme qui a plusieurs maux ne va pas "moyennement" bien -- il va aussi mal que son pire mal)
GRAVITE = (
    CRITICAL, GAP_DETECTED, BACKPRESSURED, DATA_INCOMPLETE,
    RECONNECTING, STALE, DEGRADED, NO_FRESH_SIGNAL, HEALTHY,
)


@dataclass(frozen=True, slots=True)
class SourceHealth:
    status: str
    # LA SEPARATION QUI COMPTE : "techniquement sain" et "utile" sont deux questions.
    techniquement_sain: bool
    produit_des_signaux_frais: bool
    reasons: tuple[str, ...]

    @property
    def utilisable(self) -> bool:
        """Une source n'est UTILISABLE que si elle va bien ET qu'elle sert a quelque chose."""
        return self.techniquement_sain and self.produit_des_signaux_frais

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            # les deux nombres sont exposes SEPAREMENT au dashboard, jamais fondus en un seul
            "techniquement_sain": self.techniquement_sain,
            "produit_des_signaux_frais": self.produit_des_signaux_frais,
            "utilisable": self.utilisable,
            "reasons": list(self.reasons),
        }


def evaluer_sante(
    *,
    fresh_entry_deltas: int = 0,
    fresh_follow_signals: int = 0,
    market_data_age_ms: float | None = None,
    max_market_data_age_ms: float = 10_000.0,
    reconnects_recents: int = 0,
    gaps_detectes: int = 0,
    queue_lag_ms: float = 0.0,
    max_queue_lag_ms: float = 5_000.0,
    events_dropped: int = 0,
    contrat_incomplet: int = 0,
    horloge_fiable: bool = True,
    source_principale_active: bool = True,
) -> SourceHealth:
    """La sante REELLE d'une source. **Deny-by-default : on ne declare pas OK par defaut.**

    Chaque parametre correspond a une facon dont le systeme a DEJA menti, ou pourrait mentir.
    """
    raisons: list[str] = []
    etats: list[str] = []

    # --- la source est-elle seulement la ?
    if not source_principale_active:
        etats.append(CRITICAL)
        raisons.append("SOURCE_PRINCIPALE_INACTIVE")

    if not horloge_fiable:
        etats.append(CRITICAL)
        raisons.append("HORLOGE_NON_FIABLE")   # sans horloge, toute mesure de fraicheur est fausse

    if gaps_detectes > 0:
        etats.append(GAP_DETECTED)
        raisons.append(f"TROUS_DETECTES_{gaps_detectes}")

    if events_dropped > 0:
        etats.append(BACKPRESSURED)
        raisons.append(f"EVENEMENTS_PERDUS_{events_dropped}")

    if queue_lag_ms > max_queue_lag_ms:
        etats.append(BACKPRESSURED)
        raisons.append(f"QUEUE_EN_RETARD_{int(queue_lag_ms)}MS")

    if contrat_incomplet > 0:
        etats.append(DATA_INCOMPLETE)
        raisons.append(f"CONTRAT_DE_DONNEES_INCOMPLET_{contrat_incomplet}")

    if reconnects_recents > 0:
        etats.append(RECONNECTING)
        raisons.append(f"RECONNEXIONS_{reconnects_recents}")

    if market_data_age_ms is None:
        etats.append(DATA_INCOMPLETE)
        raisons.append("AGE_DONNEE_MARCHE_INCONNU")
    elif market_data_age_ms > max_market_data_age_ms:
        etats.append(STALE)
        raisons.append(f"DONNEE_MARCHE_PERIMEE_{int(market_data_age_ms)}MS")

    technique_ok = not etats

    # --- LE POINT CENTRAL : produire des signaux frais est une AUTRE question.
    frais = (fresh_entry_deltas > 0) or (fresh_follow_signals > 0)
    if not frais:
        etats.append(NO_FRESH_SIGNAL)
        raisons.append("ZERO_SIGNAL_FRAIS")

    if not etats:
        return SourceHealth(HEALTHY, True, True, ())

    # en cas de cumul, on rapporte le PIRE. Un systeme malade de trois maux ne va pas "moyennement" bien.
    pire = min(etats, key=lambda e: GRAVITE.index(e))
    return SourceHealth(
        status=pire,
        techniquement_sain=technique_ok,
        produit_des_signaux_frais=frais,
        reasons=tuple(raisons),
    )


__all__ = [
    "BACKPRESSURED", "CRITICAL", "DATA_INCOMPLETE", "DEGRADED", "GAP_DETECTED",
    "GRAVITE", "HEALTHY", "NO_FRESH_SIGNAL", "RECONNECTING", "STALE",
    "SourceHealth", "evaluer_sante",
]
