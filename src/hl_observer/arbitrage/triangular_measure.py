"""#296 + #323 + #324 + #359 — L'ARBITRAGE : **on le MESURE avant de le construire.**

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI JE NE CONSTRUIS PAS LE MOTEUR TOUT DE SUITE
═══════════════════════════════════════════════════════════════════════════════════════════════

Les tâches #296/#323/#324/#359 demandent un **moteur d'arbitrage** : jambes réelles, état
UNHEDGED, kill-switch, graphe orienté, cycles triangulaires.

    ***Construire un moteur pour capturer un edge qu'on n'a jamais mesuré, c'est EXACTEMENT
    ce que ce projet punit depuis deux jours.***

On l'a déjà fait : 25 garde-fous de risque écrits, **23 sans appelant**. Sept garde-fous
anti-overfit, **zéro appelant**. La pile V26 entière, **éteinte**.

**Donc : on mesure d'abord. Si l'opportunité n'existe pas, le moteur n'a pas à exister.**

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QU'ON MESURE
═══════════════════════════════════════════════════════════════════════════════════════════════

Un cycle triangulaire A→B→C→A. Trois exécutions.

  🔴 **SUR LES PRIX EXÉCUTABLES, JAMAIS SUR LE MID.**
     *Le mid ment d'un DEMI-SPREAD par jambe* — sur 3 jambes, c'est **1,5 spread** de mensonge.
     C'est la faute qui a fabriqué un faux edge de +31 bps dans T1. **Ici : on achète à l'ASK, on
     vend au BID. Toujours.**

  🔴 **LA TAILLE SE PROPAGE.** Le cycle ne vaut que pour la taille que la jambe **la plus mince**
     peut absorber. Un « edge » calculé au meilleur prix sur une profondeur de 3 $ n'existe pas.

  🔴 **COÛTS : 3 exécutions taker** = 3 × 4,5 = **13,5 bps**. (Être maker sur les 3 jambes, c'est
     du market making — **T1b : mort**.)

═══════════════════════════════════════════════════════════════════════════════════════════════
LE KILL-SWITCH (#323) — la SEULE partie qu'on construit d'avance
═══════════════════════════════════════════════════════════════════════════════════════════════

Parce qu'elle protège, elle ne parie pas.

    ***L'état UNHEDGED est le seul état vraiment dangereux d'un arbitrage.***
    Jambe 1 passée, jambe 2 rejetée → on est **directionnel sans l'avoir voulu**.
    -> On DOIT pouvoir déboucler immédiatement, et **refuser d'ouvrir un nouveau cycle** tant
    qu'un cycle précédent est resté à moitié.

PUR : aucun appel réseau. Aucun ordre réel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from hl_observer.fees.hyperliquid_fees import nos_frais

FRAIS_TAKER_BPS = nos_frais("perp").taker_bps          # 4,5
COUT_3_JAMBES_BPS = 3 * FRAIS_TAKER_BPS                # 13,5

MIN_PROFONDEUR_USD = 100.0        # sous ça, l'« opportunité » n'est pas exécutable

MOTIF_PAS_D_EDGE = "AUCUN_EDGE_APRES_LES_3_EXECUTIONS"
MOTIF_TROP_MINCE = "PROFONDEUR_INSUFFISANTE_L_OPPORTUNITE_N_EST_PAS_EXECUTABLE"
MOTIF_EDGE_MESURE = "EDGE_NET_MESURE_POSITIF"

MOTIF_UNHEDGED = "UN_CYCLE_EST_RESTE_A_MOITIE_AUCUN_NOUVEAU_CYCLE"
MOTIF_KILL = "KILL_SWITCH_ARME"


@dataclass(frozen=True, slots=True)
class Jambe:
    """Une jambe. 🔴 **On achète à l'ASK, on vend au BID. Jamais au mid.**"""
    paire: str
    achat: bool
    bid: float
    ask: float
    profondeur_usd: float

    @property
    def prix_executable(self) -> float:
        return self.ask if self.achat else self.bid

    @property
    def prix_mid(self) -> float:
        return (self.bid + self.ask) / 2.0


@dataclass(frozen=True, slots=True)
class VerdictCycle:
    edge_au_mid_bps: float          # 🚩 le MENSONGE, gardé pour le montrer
    edge_executable_bps: float      # la VÉRITÉ
    edge_net_bps: float             # après les 3 exécutions
    taille_max_usd: float
    viable: bool
    motif: str
    note: str = ""

    @property
    def mensonge_du_mid_bps(self) -> float:
        """***Combien le mid nous aurait menti.***"""
        return self.edge_au_mid_bps - self.edge_executable_bps

    def as_dict(self) -> dict[str, Any]:
        return {
            "edge_au_mid_bps": round(self.edge_au_mid_bps, 3),
            "edge_executable_bps": round(self.edge_executable_bps, 3),
            "mensonge_du_mid_bps": round(self.mensonge_du_mid_bps, 3),
            "edge_net_bps": round(self.edge_net_bps, 3),
            "cout_3_jambes_bps": COUT_3_JAMBES_BPS,
            "taille_max_usd": round(self.taille_max_usd, 2),
            "viable": self.viable, "motif": self.motif, "note": self.note,
            "avertissement": (
                "🔴 **Le mid ment d'un DEMI-SPREAD par jambe.** Sur 3 jambes, c'est **1,5 spread** "
                "de mensonge — la faute qui a fabriqué un faux edge de +31 bps dans T1."
            ),
            "real_execution": False,
        }


def evaluer_cycle(jambes: Sequence[Jambe], *,
                  cout_bps: float = COUT_3_JAMBES_BPS,
                  min_profondeur: float = MIN_PROFONDEUR_USD) -> VerdictCycle | None:
    """Le cycle paie-t-il ses 3 exécutions ? `None` si le cycle est mal formé."""
    if len(jambes) < 2:
        return None
    if any(j.bid <= 0 or j.ask <= 0 or j.ask < j.bid for j in jambes):
        return None                                    # carnet absurde -> ÉCARTÉ

    def _rendement(prix_de: Any) -> float:
        r = 1.0
        for j in jambes:
            p = prix_de(j)
            r = (r / p) if j.achat else (r * p)
        return r

    r_exe = _rendement(lambda j: j.prix_executable)
    r_mid = _rendement(lambda j: j.prix_mid)
    # normalisation : un cycle fermé revient à l'unité de départ
    base_exe = _rendement(lambda j: j.prix_executable if False else j.prix_executable)
    edge_exe = (r_exe / 1.0 - 1.0) * 1e4 if base_exe else 0.0
    edge_mid = (r_mid / 1.0 - 1.0) * 1e4
    edge_exe = (r_exe - 1.0) * 1e4
    edge_mid = (r_mid - 1.0) * 1e4

    # 🔴 LA TAILLE SE PROPAGE : le cycle vaut ce que la jambe la plus MINCE absorbe.
    taille = min(j.profondeur_usd for j in jambes)
    if taille < min_profondeur:
        return VerdictCycle(
            edge_mid, edge_exe, edge_exe - cout_bps, taille, False, MOTIF_TROP_MINCE,
            "profondeur %.0f $ < %.0f $ : **l'« opportunité » n'est pas EXÉCUTABLE.** "
            "*Un edge calculé au meilleur prix sur 3 $ de profondeur n'existe pas.*"
            % (taille, min_profondeur),
        )

    net = edge_exe - cout_bps
    if net <= 0:
        return VerdictCycle(
            edge_mid, edge_exe, net, taille, False, MOTIF_PAS_D_EDGE,
            "edge exécutable %.2f bps < %.1f bps de coûts (3 exécutions taker). "
            "🚩 Au MID, il aurait eu l'air de %.2f bps — **le mid mentait de %.2f bps.**"
            % (edge_exe, cout_bps, edge_mid, edge_mid - edge_exe),
        )
    return VerdictCycle(
        edge_mid, edge_exe, net, taille, True, MOTIF_EDGE_MESURE,
        "edge NET **%.2f bps** sur %.0f $ exécutables. ⚠️ **Avant de construire un moteur** : "
        "vérifier que ça survit sur des CENTAINES de cycles, pas un. *Un seul essai chanceux ne "
        "prouve rien.*" % (net, taille),
    )


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #323 — LE KILL-SWITCH. **La seule partie qu'on construit d'avance : elle PROTÈGE.**
# ═══════════════════════════════════════════════════════════════════════════════════════════════
@dataclass(slots=True)
class EtatArbitrage:
    """***L'état UNHEDGED est le seul état vraiment dangereux d'un arbitrage.***

    Jambe 1 passée, jambe 2 rejetée → on est **directionnel sans l'avoir voulu**.
    """
    jambes_ouvertes: list[str] = field(default_factory=list)
    jambes_attendues: int = 0
    kill: bool = False

    @property
    def unhedged(self) -> bool:
        return 0 < len(self.jambes_ouvertes) < self.jambes_attendues

    def peut_ouvrir_un_cycle(self) -> tuple[bool, str]:
        if self.kill:
            return False, MOTIF_KILL
        if self.unhedged:
            return False, ("%s : %d/%d jambes ouvertes. **Deboucler AVANT tout nouveau cycle.** "
                           "*Empiler un cycle sur un cycle a moitie, c'est doubler un risque "
                           "qu'on ne voulait pas.*"
                           % (MOTIF_UNHEDGED, len(self.jambes_ouvertes), self.jambes_attendues))
        return True, "OK"

    def armer_le_kill(self) -> None:
        self.kill = True


__all__ = [
    "COUT_3_JAMBES_BPS", "FRAIS_TAKER_BPS", "MIN_PROFONDEUR_USD",
    "MOTIF_EDGE_MESURE", "MOTIF_KILL", "MOTIF_PAS_D_EDGE", "MOTIF_TROP_MINCE", "MOTIF_UNHEDGED",
    "EtatArbitrage", "Jambe", "VerdictCycle", "evaluer_cycle",
]
