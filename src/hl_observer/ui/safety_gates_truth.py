"""#292 / P6b — LE PANNEAU DE SECURITE NE DOIT PAS MENTIR (2026-07-13).

🔴 CE QUI ETAIT AFFICHE, ET POURQUOI C'EST LE PIRE BUG POSSIBLE ICI

    UiRiskGate(name="api stable", passed=True),          # <-- EN DUR. TOUJOURS VERT.

Le dashboard annoncait « **api stable ✓** » **que l'API soit stable ou non**. Ce n'etait pas un
controle : c'etait un **voyant vert soude en position verte**.

C'est exactement ce que la tache P6b nommait : *« le texte affirme des controles absents »*.
Et c'est **une donnee fabriquee presentee comme reelle** -- la SEULE chose que ce projet
interdit absolument. Sur le panneau **securite**. Devant les yeux de Flo.

🚩 ET LE MODULE QUI SAIT LA VERITE EXISTAIT DEJA : `realtime/source_health.py` (livre par P12,
« interdire le faux OK », marque **completed**) calcule un vrai statut, avec ses raisons, et
separe meme « techniquement sain » de « produit des signaux frais ».
**L'interface ne l'a jamais consomme.** 15e deguisement de la maladie du projet : *une capacite
presente, un chainon manquant, personne qui se plaint.*

LA REGLE, DESORMAIS :

    Un gate dont l'etat n'est pas MESURE ne peut PAS etre vert.
    Il est ROUGE, et il dit « NON MESURE ».

C'est le deny-by-default applique a l'AFFICHAGE. Un « je ne sais pas » honnete vaut mille fois
mieux qu'un « tout va bien » fabrique : le premier fait chercher, le second endort.

PUR : ce module ne lit ni le disque ni le reseau. On lui PASSE l'etat. C'est ce qui le rend
testable -- et c'est aussi ce qui rend son mensonge impossible a cacher.

Aucun ordre reel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

# Le motif unique, pour qu'on puisse le chercher dans les logs et dans l'UI.
NON_MESURE = "NON_MESURE"


@dataclass(frozen=True, slots=True)
class GateVerite:
    """Un gate qui porte sa PREUVE, ou son aveu d'ignorance."""

    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


def gate_mesure(name: str, ok: bool, detail: str) -> GateVerite:
    """Un gate dont on connait REELLEMENT l'etat."""
    return GateVerite(name=name, passed=bool(ok), detail=str(detail))


def gate_inconnu(name: str, pourquoi: str = "aucune mesure disponible") -> GateVerite:
    """🔴 Un gate dont on NE SAIT RIEN. Il est ROUGE. Jamais vert.

    *On n'affiche pas un feu vert sur une chose qu'on n'a pas regardee.*
    """
    return GateVerite(name=name, passed=False, detail="%s : %s" % (NON_MESURE, pourquoi))


def gates_de_securite(
    *,
    mainnet_execution_active: bool,
    testnet_execution_active: bool,
    est_en_mode_paper: bool,
    kill_switch_actif: bool,
    base_lisible: bool | None,
    sante_des_sources: Mapping[str, Any] | None,
    age_max_source_s: float | None = None,
    seuil_stale_s: float = 120.0,
) -> list[GateVerite]:
    """Les gates du panneau securite -- chacun MESURE, ou ROUGE et honnete.

    `sante_des_sources` : le `as_dict()` d'un `realtime.source_health.SourceHealth`, ou None.
    `base_lisible`      : None = on n'a pas pu regarder -> ROUGE (et pas « False » silencieux).
    """
    gates: list[GateVerite] = []

    # --- 1 a 4 : ceux-la, on les CONNAIT vraiment (ce sont des flags de config locaux).
    gates.append(gate_mesure(
        "mainnet interdit", not mainnet_execution_active,
        "aucune execution mainnet possible" if not mainnet_execution_active
        else "🔴 EXECUTION MAINNET ACTIVEE",
    ))
    gates.append(gate_mesure(
        "testnet verrouille", not testnet_execution_active,
        "aucune execution testnet" if not testnet_execution_active else "testnet ACTIF",
    ))
    gates.append(gate_mesure(
        "mode paper", est_en_mode_paper,
        "simulation locale uniquement" if est_en_mode_paper else "🔴 PAS en mode paper",
    ))
    gates.append(gate_mesure(
        "kill switch", not kill_switch_actif,
        "inactif" if not kill_switch_actif else "ACTIF : toute entree est bloquee",
    ))

    # --- 5 : LA BASE. `None` = on n'a pas pu regarder. Ce n'est PAS « ca va ».
    if base_lisible is None:
        gates.append(gate_inconnu("base de donnees", "la base n'a pas pu etre interrogee"))
    else:
        gates.append(gate_mesure(
            "base de donnees", base_lisible,
            "lisible" if base_lisible else "🔴 illisible ou vide",
        ))

    # --- 6 : LA SANTE DES SOURCES -- l'ancien « api stable: passed=True » EN DUR.
    if not sante_des_sources:
        gates.append(gate_inconnu(
            "sources de donnees",
            "aucun rapport de sante (le collecteur tourne-t-il ?)",
        ))
    else:
        statut = str(sante_des_sources.get("status") or "?")
        sain = bool(sante_des_sources.get("techniquement_sain"))
        frais = bool(sante_des_sources.get("produit_des_signaux_frais"))
        raisons = ", ".join(str(r) for r in (sante_des_sources.get("reasons") or ())) or "-"
        # ⚠️ LES DEUX QUESTIONS RESTENT SEPAREES (c'est la lecon de P12) : une source peut etre
        # techniquement saine ET ne produire aucun signal frais. Les fondre en un seul voyant
        # vert, c'est refabriquer le mensonge qu'on vient de retirer.
        gates.append(gate_mesure(
            "sources techniquement saines", sain, "%s (%s)" % (statut, raisons),
        ))
        gates.append(gate_mesure(
            "sources produisent du frais", frais,
            "signaux frais" if frais else "AUCUN signal frais -- la source vit, mais ne sert a rien",
        ))

    # --- 7 : LA FRAICHEUR, si on la connait.
    if age_max_source_s is None:
        gates.append(gate_inconnu("fraicheur des donnees", "age des sources non mesure"))
    else:
        frais = float(age_max_source_s) <= float(seuil_stale_s)
        gates.append(gate_mesure(
            "fraicheur des donnees", frais,
            "source la plus vieille : %.0f s (seuil %.0f s)" % (age_max_source_s, seuil_stale_s),
        ))

    return gates


def resume(gates: list[GateVerite]) -> dict[str, Any]:
    """Le resume honnete : on distingue « en echec » de « non mesure »."""
    echecs = [g for g in gates if not g.passed and NON_MESURE not in g.detail]
    inconnus = [g for g in gates if NON_MESURE in g.detail]
    return {
        "total": len(gates),
        "verts": sum(1 for g in gates if g.passed),
        "echecs": [g.name for g in echecs],
        "non_mesures": [g.name for g in inconnus],
        # 🔴 « SAFE » exige que TOUT soit mesure ET vert. Un inconnu suffit a sortir du vert.
        "tout_mesure_et_vert": not echecs and not inconnus,
        "real_execution": False,
    }


__all__ = ["NON_MESURE", "GateVerite", "gate_inconnu", "gate_mesure", "gates_de_securite", "resume"]
