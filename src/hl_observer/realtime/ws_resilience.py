"""#314 + #315 + #319 + #525 — LE WS QUI NE MENT PAS QUAND IL TOMBE.

Quatre tâches, une seule brique : **ce qui arrive quand le flux se coupe et que personne ne crie.**

═══════════════════════════════════════════════════════════════════════════════════════════════
#314 — WS PERSISTANT : heartbeat, reconnect, GAP, dédup
═══════════════════════════════════════════════════════════════════════════════════════════════

On a eu **deux stalls** (02:32 et 04:08). Le flux s'était arrêté, et **rien n'a crié** —
`signal_age` était une tautologie qui **gelait**. Le bot a continué à décider sur du vieux.

    ***Un flux qui se tait n'est pas un flux calme. C'est un flux MORT.***

  * **HEARTBEAT** : si aucun message depuis `silence_max_ms`, on déclare le flux **MORT**.
    🔴 L'horloge est **LOCALE**, jamais dérivée des données — sinon on refait la tautologie.
  * **RECONNECT** : backoff exponentiel **avec jitter** (sans jitter, tous les clients se
    reconnectent en même temps et achèvent le serveur).
  * **GAP** : après une reconnexion, il **manque** des messages. On ne fait pas semblant :
    on marque un **TROU**, et le trou invalide toute décision qui aurait besoin de continuité.
  * **DÉDUP** : la reprise renvoie des messages **déjà vus**. Un fill compté deux fois, c'est un
    PnL doublé — *exactement le genre de faux edge que ce projet fabrique.*

═══════════════════════════════════════════════════════════════════════════════════════════════
#315 — SHORTLIST CHAUDE : rotation **ATOMIQUE**, sans période aveugle
═══════════════════════════════════════════════════════════════════════════════════════════════

Naïvement : on se désabonne des anciens wallets, **puis** on s'abonne aux nouveaux.
    ***Entre les deux, on ne voit RIEN.*** Et c'est précisément le moment où un signal passe.
-> On s'abonne d'ABORD, on se désabonne ENSUITE. **Jamais l'inverse.**

═══════════════════════════════════════════════════════════════════════════════════════════════
#319 + #525 — LE BUDGET D'ABONNEMENT : on n'écoute pas tout, on **alloue**
═══════════════════════════════════════════════════════════════════════════════════════════════

Les abonnements sont limités. Souscrire à tout, c'est saturer sans rien prioriser.
On alloue par **valeur mesurée** — *et un canal qu'on n'utilise pas est un canal qu'on rend.*

PUR : aucun réseau ici. Ce module DÉCIDE et COMPTE. Aucun ordre réel.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

# Silence au-delà duquel le flux est déclaré MORT (et non « calme »).
SILENCE_MAX_MS = 30_000

# Backoff : base, plafond, et jitter OBLIGATOIRE.
BACKOFF_BASE_MS = 500
BACKOFF_MAX_MS = 30_000

# Nombre d'identifiants gardés pour la déduplication.
FENETRE_DEDUP = 50_000

# Budget d'abonnements (limite de la venue).
BUDGET_ABONNEMENTS = 100

VIVANT = "VIVANT"
MORT = "MORT"
NON_MESURE = "NON_MESURE"

MOTIF_SILENCE = "AUCUN_MESSAGE_DEPUIS_TROP_LONGTEMPS_FLUX_MORT"
MOTIF_TROU = "TROU_DANS_LA_SEQUENCE_APRES_RECONNEXION"
MOTIF_DOUBLON = "MESSAGE_DEJA_VU_IGNORE"
MOTIF_BUDGET = "BUDGET_D_ABONNEMENTS_EPUISE"


# ── #314a — HEARTBEAT ─────────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class Heartbeat:
    """***Un flux qui se tait n'est pas un flux calme. C'est un flux MORT.***"""
    silence_max_ms: int = SILENCE_MAX_MS
    dernier_message_ms: int | None = None

    def battre(self, *, maintenant_ms: int) -> None:
        self.dernier_message_ms = int(maintenant_ms)

    def etat(self, *, maintenant_ms: int) -> tuple[str, str]:
        """🔴 `maintenant_ms` vient de **l'horloge LOCALE**, jamais des données.

        *Sinon on refait la tautologie de `signal_age` : le « maintenant » dérivé des données
        GELAIT quand le flux calait, et l'âge restait à zéro.*
        """
        if self.dernier_message_ms is None:
            return NON_MESURE, "aucun message recu — **ce n'est PAS un feu vert**"
        age = int(maintenant_ms) - self.dernier_message_ms
        if age > self.silence_max_ms:
            return MORT, ("%s : %d ms de silence (max %d). **Le flux est MORT — toute decision "
                          "prise maintenant le serait sur du VIEUX.**"
                          % (MOTIF_SILENCE, age, self.silence_max_ms))
        return VIVANT, "silence %d ms" % age


# ── #314b — RECONNECT avec BACKOFF + JITTER ───────────────────────────────────────────────────
def delai_reconnexion_ms(essai: int, *, base: int = BACKOFF_BASE_MS,
                         plafond: int = BACKOFF_MAX_MS, rng: random.Random | None = None) -> int:
    """Backoff exponentiel **avec jitter**.

    🔴 **Le jitter n'est pas cosmétique** : sans lui, tous les clients se reconnectent
    **exactement en même temps** après une coupure — et achèvent le serveur qui se relevait.
    """
    if essai < 0:
        raise ValueError("numero d'essai negatif")
    r = rng or random
    brut = min(plafond, base * (2 ** min(essai, 20)))
    return int(r.uniform(brut * 0.5, brut))          # jitter : entre 50 % et 100 %


# ── #314c — GAP : on ne fait PAS semblant ─────────────────────────────────────────────────────
@dataclass(slots=True)
class DetecteurDeTrou:
    """Après une reconnexion, il **manque** des messages. **On marque le trou.**

    *Un backtest ou une décision qui traverse un trou sans le savoir est un mensonge.*
    """
    derniere_sequence: int | None = None
    trous: list[tuple[int, int]] = field(default_factory=list)

    def voir(self, sequence: int) -> tuple[bool, str]:
        s = int(sequence)
        if self.derniere_sequence is None:
            self.derniere_sequence = s
            return True, "premiere sequence"
        attendu = self.derniere_sequence + 1
        if s == attendu:
            self.derniere_sequence = s
            return True, "continu"
        if s <= self.derniere_sequence:
            return False, MOTIF_DOUBLON                 # rejeu : le dédup s'en charge
        self.trous.append((attendu, s - 1))
        self.derniere_sequence = s
        return False, ("%s : %d..%d manquants (%d messages). **La continuité est ROMPUE.**"
                       % (MOTIF_TROU, attendu, s - 1, s - attendu))

    @property
    def n_manquants(self) -> int:
        return sum(b - a + 1 for a, b in self.trous)


# ── #314d — DÉDUP ─────────────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class Dedup:
    """***Un fill compté deux fois, c'est un PnL doublé.*** Exactement le faux edge à éviter."""
    fenetre: int = FENETRE_DEDUP
    _vus: set = field(default_factory=set)
    _ordre: list = field(default_factory=list)
    doublons: int = 0

    def nouveau(self, cle: Any) -> bool:
        if cle in self._vus:
            self.doublons += 1
            return False
        self._vus.add(cle)
        self._ordre.append(cle)
        if len(self._ordre) > self.fenetre:
            vieux = self._ordre.pop(0)
            self._vus.discard(vieux)
        return True


# ── #315 — ROTATION ATOMIQUE DE LA SHORTLIST ──────────────────────────────────────────────────
def rotation_atomique(
    actuels: Iterable[str], cibles: Iterable[str],
) -> tuple[list[str], list[str]]:
    """🔴 **ON S'ABONNE D'ABORD. ON SE DÉSABONNE ENSUITE.**

    Naïvement on se désabonne puis on s'abonne — et **entre les deux, on ne voit RIEN**.
    *C'est précisément le moment où un signal passe.*

    Rend `(a_souscrire, a_desouscrire)` **dans cet ordre d'exécution**.
    """
    a, c = set(actuels), set(cibles)
    return sorted(c - a), sorted(a - c)


# ── #319 + #525 — LE BUDGET D'ABONNEMENTS ─────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Canal:
    nom: str
    valeur: float          # ce qu'il nous rapporte (mesuré, pas supposé)
    cout: int = 1          # combien d'abonnements il consomme


def allouer(canaux: Sequence[Canal], *, budget: int = BUDGET_ABONNEMENTS) -> dict[str, Any]:
    """On n'écoute pas tout : **on alloue par VALEUR MESURÉE.**

    ⚠️ Un canal de valeur **nulle ou inconnue** n'est pas souscrit. *Un canal qu'on n'utilise pas
    est un canal qu'on rend.*
    """
    utiles = [c for c in canaux if c.valeur > 0 and c.cout > 0]
    utiles.sort(key=lambda c: c.valeur / c.cout, reverse=True)

    retenus: list[str] = []
    reste = int(budget)
    for c in utiles:
        if c.cout <= reste:
            retenus.append(c.nom)
            reste -= c.cout
    ecartes = [c.nom for c in canaux if c.nom not in retenus]
    return {
        "retenus": retenus, "ecartes": ecartes,
        "budget": int(budget), "reste": reste,
        "motif": MOTIF_BUDGET if reste == 0 and ecartes else "OK",
        "note": ("Les canaux de valeur nulle ou INCONNUE ne sont pas souscrits. "
                 "*Un canal qu'on n'utilise pas est un canal qu'on rend.*"),
        "real_execution": False,
    }


def rapport(hb: Heartbeat, trous: DetecteurDeTrou, dd: Dedup,
            *, maintenant_ms: int) -> dict[str, Any]:
    etat, detail = hb.etat(maintenant_ms=maintenant_ms)
    return {
        "flux": etat, "detail": detail,
        "n_trous": len(trous.trous), "n_messages_manquants": trous.n_manquants,
        "doublons_ignores": dd.doublons,
        "continuite": len(trous.trous) == 0,
        "avertissement": ("🔴 **La continuite est ROMPUE.** Toute mesure qui suppose une serie "
                          "complete est FAUSSE sur cette periode."
                          if trous.trous else ""),
        "real_execution": False,
    }


__all__ = [
    "BACKOFF_BASE_MS", "BACKOFF_MAX_MS", "BUDGET_ABONNEMENTS", "FENETRE_DEDUP", "MORT",
    "MOTIF_BUDGET", "MOTIF_DOUBLON", "MOTIF_SILENCE", "MOTIF_TROU", "NON_MESURE",
    "SILENCE_MAX_MS", "VIVANT",
    "Canal", "Dedup", "DetecteurDeTrou", "Heartbeat",
    "allouer", "delai_reconnexion_ms", "rapport", "rotation_atomique",
]
