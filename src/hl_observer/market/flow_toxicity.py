"""#389 + #507 + #516 + #521 + #529 + #535 + #558 — LA TOXICITÉ DU FLUX.

Sept tâches, **une seule entrée** : les trades avec leur **côté agresseur** (+ l'open interest).
On les traite ensemble parce que c'est la même donnée.

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QU'ON MESURE, ET POURQUOI
═══════════════════════════════════════════════════════════════════════════════════════════════

**#389 / #507 — OFI (Order Flow Imbalance), fait correctement.**
    OFI = (volume agressé à l'ACHAT − volume agressé à la VENTE) / volume total
    C'est le **déséquilibre du flux**, pas le prix. Cont-Kukanov-Stoikov montrent qu'il prédit
    le mouvement de prix à court terme **mieux que le prix lui-même**.

**#521 — VPIN, sur HORLOGE DE VOLUME (pas horloge de temps).**
    🔑 **C'est le cœur de la méthode, et c'est ce que tout le monde rate.**
    Le VPIN découpe le flux en **buckets de VOLUME ÉGAL**, pas en minutes égales.
    *Pourquoi ?* Parce que l'information n'arrive pas à un rythme régulier : elle arrive quand ça
    trade. Une minute calme et une minute de panique ne contiennent pas la même information.
    **Découper en temps, c'est mélanger les deux.**

**#516 / #529 / #535 — LA TOXICITÉ PAR CÔTÉ.**
    Le bid et l'ask **n'ont PAS la même toxicité**. Si les acheteurs agressifs sont informés et
    les vendeurs ne le sont pas, vendre au bid est sûr et vendre à l'ask est dangereux.
    -> markout **par côté**, sur le **MID**.

**#558 — L'OPEN INTEREST : détecter le trade ENCOMBRÉ.**
    OI qui monte + prix qui monte = de nouveaux LONGS entrent -> **trade encombré**.
    OI qui BAISSE + prix qui monte = des SHORTS se ferment -> **short squeeze**.
    ***Un trade encombré est un trade où l'on est la sortie de secours de quelqu'un d'autre.***

═══════════════════════════════════════════════════════════════════════════════════════════════
🚩 CE QUE JE DIS AVANT DE MESURER
═══════════════════════════════════════════════════════════════════════════════════════════════

**Le VPIN et l'OFI ne peuvent PAS ressusciter un signal sans information.** Le copy-trading est
mort à **−7,97 bps, même à coût ZÉRO** : mesurer la toxicité du flux **qu'on suit** ne créera
pas d'edge là où il n'y en a pas.

***Leur seule valeur : dire QUAND NE PAS TRADER.*** Un filtre de toxicité **réduit les pertes**,
il ne crée pas de gains. *Et c'est déjà quelque chose : « moins de trades, beaucoup plus propres. »*

PUR : aucun appel réseau. Aucun ordre réel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

ACHAT = "ACHAT"          # l'agresseur ACHÈTE (il tape l'ask)
VENTE = "VENTE"          # l'agresseur VEND   (il tape le bid)

# VPIN : nombre de buckets de VOLUME (pas de temps) sur lesquels on moyenne.
N_BUCKETS_VPIN = 50
MIN_TRADES = 200

# Au-delà, le flux est jugé TOXIQUE -> **NE PAS TRADER**.
SEUIL_VPIN_TOXIQUE = 0.40

MOTIF_PAS_ASSEZ = "PAS_ASSEZ_DE_TRADES"
MOTIF_FLUX_TOXIQUE = "FLUX_TOXIQUE_NE_PAS_TRADER"
MOTIF_TRADE_ENCOMBRE = "OI_ET_PRIX_MONTENT_ENSEMBLE_TRADE_ENCOMBRE"
MOTIF_SQUEEZE = "OI_BAISSE_ET_PRIX_MONTE_FERMETURE_DE_SHORTS"


@dataclass(frozen=True, slots=True)
class Trade:
    time_ms: int
    prix: float
    taille: float
    cote_agresseur: str      # ACHAT | VENTE — **jamais deviné**

    @property
    def notionnel(self) -> float:
        return self.prix * self.taille


# ── #389 / #507 — OFI ─────────────────────────────────────────────────────────────────────────
def ofi(trades: Sequence[Trade]) -> float | None:
    """Déséquilibre du flux, dans [−1, +1]. `None` = **état vide honnête**, jamais un 0 fabriqué.

    Un 0 inventé dirait « flux parfaitement équilibré » — c'est un mensonge, pas une absence.
    """
    ts = [t for t in trades if t.taille > 0 and t.cote_agresseur in (ACHAT, VENTE)]
    if not ts:
        return None
    achats = sum(t.notionnel for t in ts if t.cote_agresseur == ACHAT)
    ventes = sum(t.notionnel for t in ts if t.cote_agresseur == VENTE)
    total = achats + ventes
    return ((achats - ventes) / total) if total > 0 else None


# ── #521 — VPIN, sur HORLOGE DE VOLUME ────────────────────────────────────────────────────────
def buckets_de_volume(trades: Sequence[Trade],
                      *, n_buckets: int) -> list[list[tuple[str, float]]]:
    """🔑 **HORLOGE DE VOLUME, pas horloge de temps.** Buckets de volume ÉGAL.

    *L'information n'arrive pas à un rythme régulier : elle arrive quand ça trade.*
    Une minute calme et une minute de panique ne contiennent pas la même information —
    **les découper en temps, c'est les mélanger.**

    🔴 **UN TRADE PEUT ÊTRE FRACTIONNÉ ENTRE PLUSIEURS BUCKETS.** Un test rouge me l'a appris :
    ma 1ʳᵉ version ne fractionnait pas, et un trade géant (99,9 % du volume) occupait **UN**
    bucket au lieu de dix -> la moyenne se faisait sur **2 buckets au lieu de 10**.
    ***Un bucket de volume est un bucket de VOLUME, pas un bucket de TRADES.***

    Rend, par bucket, la liste des fragments `(côté, notionnel)`.
    """
    ts = [t for t in trades if t.taille > 0 and t.cote_agresseur in (ACHAT, VENTE)]
    if not ts or n_buckets < 1:
        return []
    total = sum(t.notionnel for t in ts)
    if total <= 0:
        return []
    cible = total / n_buckets

    out: list[list[tuple[str, float]]] = []
    courant: list[tuple[str, float]] = []
    acc = 0.0
    for t in ts:
        reste = t.notionnel
        while reste > 0:
            if len(out) >= n_buckets - 1:
                courant.append((t.cote_agresseur, reste))   # dernier bucket : il absorbe tout
                acc += reste
                reste = 0.0
                break
            place = cible - acc
            if reste < place:
                courant.append((t.cote_agresseur, reste))
                acc += reste
                reste = 0.0
            else:
                courant.append((t.cote_agresseur, place))   # ✂️ on FRACTIONNE le trade
                out.append(courant)
                courant = []
                acc = 0.0
                reste -= place
    if courant:
        out.append(courant)
    return out


def vpin(trades: Sequence[Trade], *, n_buckets: int = N_BUCKETS_VPIN,
         min_trades: int = MIN_TRADES) -> float | None:
    """VPIN ∈ [0, 1]. Plus il est haut, plus le flux est **déséquilibré donc INFORMÉ**.

    `None` si l'échantillon est trop court. *Un chiffre sur 10 trades n'est pas une mesure.*
    """
    if len(trades) < min_trades:
        return None
    bs = buckets_de_volume(trades, n_buckets=n_buckets)
    if not bs:
        return None
    parts: list[float] = []
    for b in bs:
        a = sum(n for c, n in b if c == ACHAT)
        v = sum(n for c, n in b if c == VENTE)
        tot = a + v
        if tot > 0:
            parts.append(abs(a - v) / tot)
    return (sum(parts) / len(parts)) if parts else None


# ── #516 / #529 / #535 — LA TOXICITÉ PAR CÔTÉ ─────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ToxiciteParCote:
    markout_achat_bps: float | None    # markout APRÈS un achat agressif (sur le MID)
    markout_vente_bps: float | None
    n_achat: int
    n_vente: int
    asymetrique: bool
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"markout_achat_bps": (round(self.markout_achat_bps, 3)
                                      if self.markout_achat_bps is not None else None),
                "markout_vente_bps": (round(self.markout_vente_bps, 3)
                                      if self.markout_vente_bps is not None else None),
                "n_achat": self.n_achat, "n_vente": self.n_vente,
                "asymetrique": self.asymetrique, "note": self.note,
                "real_execution": False}


def toxicite_par_cote(
    trades: Sequence[Trade],
    mids: Sequence[tuple[int, float]],       # (time_ms, MID) — 🔴 **jamais un prix de trade**
    *, horizon_ms: int = 30_000,
) -> ToxiciteParCote:
    """Le bid et l'ask n'ont **PAS** la même toxicité.

    🔴 **Sur le MID.** Un markout sur des prix de trade oscille bid↔ask et **fabrique un edge**.
    *(Ça m'est arrivé DEUX fois : T1 puis T1b. Pas une troisième.)*
    """
    if not mids:
        return ToxiciteParCote(None, None, 0, 0, False, "aucun mid : **état vide honnête**")
    mids_tries = sorted(mids)

    def _mid(t_ms: int) -> float | None:
        apres = [m for m in mids_tries if m[0] >= t_ms]
        return apres[0][1] if apres else None

    ach: list[float] = []
    ven: list[float] = []
    for t in trades:
        m0 = _mid(t.time_ms)
        m1 = _mid(t.time_ms + horizon_ms)
        if m0 is None or m1 is None or m0 <= 0:
            continue
        r = (m1 - m0) / m0 * 1e4
        # markout de l'AGRESSEUR : s'il achète, il gagne si le prix monte.
        if t.cote_agresseur == ACHAT:
            ach.append(r)
        elif t.cote_agresseur == VENTE:
            ven.append(-r)

    ma = (sum(ach) / len(ach)) if ach else None
    mv = (sum(ven) / len(ven)) if ven else None
    asym = (ma is not None and mv is not None
            and abs(ma - mv) > max(1.0, 0.5 * max(abs(ma), abs(mv))))
    note = ""
    if asym:
        cote = "ACHAT" if (ma or 0) > (mv or 0) else "VENTE"
        note = ("🔴 **Les deux côtés n'ont PAS la même toxicité** (achat %.2f bps vs vente "
                "%.2f bps). Les agresseurs à l'%s sont les mieux informés : **c'est le côté "
                "où il est dangereux de les servir.**" % (ma or 0, mv or 0, cote))
    return ToxiciteParCote(ma, mv, len(ach), len(ven), asym, note)


# ── #558 — L'OPEN INTEREST : le trade ENCOMBRÉ ────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class VerdictOI:
    delta_oi: float
    delta_prix_bps: float
    motif: str
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {"delta_oi": round(self.delta_oi, 4),
                "delta_prix_bps": round(self.delta_prix_bps, 2),
                "motif": self.motif, "note": self.note, "real_execution": False}


def lire_open_interest(oi_debut: float, oi_fin: float,
                       prix_debut: float, prix_fin: float) -> VerdictOI | None:
    """***Un trade encombré est un trade où l'on est la sortie de secours de quelqu'un d'autre.***

    `None` si les entrées sont absurdes — **jamais un verdict inventé**.
    """
    if oi_debut <= 0 or prix_debut <= 0:
        return None
    d_oi = (oi_fin - oi_debut) / oi_debut
    d_px = (prix_fin - prix_debut) / prix_debut * 1e4

    if d_oi > 0.02 and d_px > 0:
        return VerdictOI(d_oi, d_px, MOTIF_TRADE_ENCOMBRE,
                         "OI **+%.1f %%** et prix **+%.0f bps** : de NOUVEAUX longs entrent. "
                         "**Trade encombré** — on serait la sortie de secours de quelqu'un."
                         % (d_oi * 100, d_px))
    if d_oi < -0.02 and d_px > 0:
        return VerdictOI(d_oi, d_px, MOTIF_SQUEEZE,
                         "OI **%.1f %%** et prix **+%.0f bps** : des SHORTS se ferment. "
                         "Short squeeze — le mouvement est de la **couverture**, pas de la "
                         "conviction." % (d_oi * 100, d_px))
    return VerdictOI(d_oi, d_px, "RIEN_DE_NOTABLE", "")


# ── LE FILTRE : la SEULE valeur de tout ça ────────────────────────────────────────────────────
def faut_il_s_abstenir(v: float | None, *, seuil: float = SEUIL_VPIN_TOXIQUE) -> tuple[bool, str]:
    """🎯 ***La seule valeur du VPIN : dire QUAND NE PAS TRADER.***

    Il ne crée aucun gain. Il **évite des pertes**. *« Moins de trades, beaucoup plus propres. »*

    ⚠️ **DENY-BY-DEFAULT** : un VPIN **non mesurable** (`None`) fait **s'abstenir**.
    *Ne pas savoir si le flux est toxique n'est pas une raison de trader.*
    """
    if v is None:
        return True, ("%s : VPIN NON MESURABLE -> **on s'abstient.** "
                      "*Ne pas savoir n'est pas une permission.*" % MOTIF_PAS_ASSEZ)
    if v >= seuil:
        return True, ("%s : VPIN %.3f >= %.2f. Le flux est **informé** : servir ces agresseurs, "
                      "c'est être le pigeon." % (MOTIF_FLUX_TOXIQUE, v, seuil))
    return False, "VPIN %.3f < %.2f : flux non toxique." % (v, seuil)


__all__ = [
    "ACHAT", "MIN_TRADES", "MOTIF_FLUX_TOXIQUE", "MOTIF_PAS_ASSEZ", "MOTIF_SQUEEZE",
    "MOTIF_TRADE_ENCOMBRE", "N_BUCKETS_VPIN", "SEUIL_VPIN_TOXIQUE", "VENTE",
    "ToxiciteParCote", "Trade", "VerdictOI",
    "buckets_de_volume", "faut_il_s_abstenir", "lire_open_interest", "ofi",
    "toxicite_par_cote", "vpin",
]
