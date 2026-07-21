r"""UN SCAN NE DOIT **JAMAIS** MOURIR — *et « ne pas mourir » n'est pas « ignorer les erreurs ».*

═══════════════════════════════════════════════════════════════════════════════════════════════
LA DISTINCTION QUI DÉCIDE DE TOUT
═══════════════════════════════════════════════════════════════════════════════════════════════

Flo : *« un scan ne doit jamais mourir »*. Il a raison. Mais il y a **deux façons** de ne pas
mourir, et **une seule est acceptable** :

  🔴 **LA MAUVAISE** : avaler toutes les erreurs, continuer en silence, finir avec un fichier de
     résultats qui a l'air complet.
     ***C'est exactement le bug qui a perdu 235 README — dont hftbacktest, notre cible n°1.***
     Un `except: pass` transforme « je n'ai pas su lire » en « il n'y avait rien ».
     **Un scan qui ne meurt jamais ET qui ne se plaint jamais est un scan qui MENT.**

  ✅ **LA BONNE** : **survivre à tout**, mais **compter chaque blessure**, **réessayer ce qui est
     réessayable**, **sauver l'état après CHAQUE requête**, et **DIRE à la fin ce qu'on n'a pas
     su lire**.

    ***Ne jamais mourir, jamais mentir.***

═══════════════════════════════════════════════════════════════════════════════════════════════
LA POLITIQUE
═══════════════════════════════════════════════════════════════════════════════════════════════

  429 / 403 quota   -> **ATTENDRE** (on respecte `Retry-After` / `X-RateLimit-Reset`) puis
                       **RÉESSAYER À L'INFINI**. *Se faire bannir = MOINS de données, pas plus.*
  5xx               -> backoff exponentiel + **jitter**, jusqu'à `MAX_ESSAIS`.
  réseau / timeout  -> idem.
  422 (syntaxe)     -> **ABANDONNER cette requête** — la réessayer ne changera rien.
  404               -> **ABANDONNER** — mais on **NOTE** qu'on n'a pas su lire.
  autre             -> ABANDONNER, **et le compter**.

Le **jitter** n'est pas cosmétique : sans lui, tous les réessais retombent en même temps et on
se refait jeter. *Une tempête de réessais synchronisés est une auto-attaque.*

PUR : aucun réseau, aucune horloge bloquante. Ce module **DÉCIDE**. L'appelant agit.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

# Réessayer ~indéfiniment sur le quota (c'est temporaire, par définition).
# Mais **borner** sur les erreurs serveur : si GitHub est cassé, on ne le répare pas en insistant.
MAX_ESSAIS_SERVEUR = 6
ATTENTE_BASE = 2.0
ATTENTE_MAX = 900.0            # 15 min : le quota GitHub se réarme à l'heure

ATTENDRE = "ATTENDRE"          # le quota : on patiente, puis on RÉESSAIE. Sans limite d'essais.
REESSAYER = "REESSAYER"        # erreur transitoire : backoff + jitter
ABANDONNER = "ABANDONNER"      # définitif : insister ne changera rien
REUSSI = "REUSSI"


@dataclass(frozen=True, slots=True)
class Decision:
    """Ce qu'il faut faire. **Chaque décision porte sa raison.**"""
    action: str
    attente_s: float
    raison: str
    fatal_pour_cette_requete: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.action, "attente_s": round(self.attente_s, 1),
                "raison": self.raison, "abandonne": self.fatal_pour_cette_requete}


def _backoff(essai: int, *, base: float = ATTENTE_BASE, plafond: float = ATTENTE_MAX,
             alea: float | None = None) -> float:
    """Exponentiel **+ jitter**.

    ***Le jitter n'est pas cosmétique.*** Sans lui, tous les réessais retombent au même instant
    et on se refait jeter. *Une tempête de réessais synchronisés est une auto-attaque.*
    """
    brut = min(base * (2 ** max(0, essai)), plafond)
    j = random.random() if alea is None else alea      # noqa: S311 — pas de crypto ici
    return brut * (0.5 + 0.5 * j)                      # entre 50 % et 100 % du délai


def decider(statut: int | None, *, essai: int = 0,
            retry_after: float | None = None,
            reset_dans_s: float | None = None,
            alea: float | None = None) -> Decision:
    """**La politique.** `statut=None` = échec réseau (timeout, DNS, connexion coupée).

    🔒 Le quota n'est **jamais** une raison d'abandonner : c'est une raison d'**attendre**.
    """
    # ── succès ────────────────────────────────────────────────────────────────────────────────
    if statut is not None and 200 <= statut < 300:
        return Decision(REUSSI, 0.0, "ok")

    # ── LE QUOTA : on attend le temps qu'il faut. **On ne renonce JAMAIS pour ça.** ────────────
    if statut in (403, 429):
        # GitHub dit lui-même quand revenir. *On écoute la source plutôt que de deviner.*
        attente = None
        for x in (retry_after, reset_dans_s):
            if x is not None and x >= 0:
                attente = max(attente or 0.0, float(x))
        if attente is None:
            attente = _backoff(essai, base=30.0, plafond=ATTENTE_MAX, alea=alea)
        attente = min(max(attente + 1.0, 1.0), ATTENTE_MAX)
        return Decision(
            ATTENDRE, attente,
            "quota (%s) — **on attend %.0f s, puis on RÉESSAIE.** *Se faire bannir = MOINS de "
            "données, pas plus.*" % (statut, attente),
        )

    # ── 422 : GitHub refuse la requête elle-même. La réessayer ne changera rien. ───────────────
    if statut == 422:
        return Decision(ABANDONNER, 0.0,
                        "422 — requête refusée par l'API (syntaxe). *Insister ne changera rien.* "
                        "**Comptée comme non lue, pas comme vide.**", True)

    if statut == 404:
        return Decision(ABANDONNER, 0.0,
                        "404 — introuvable. **Et on le NOTE** : *« je n'ai pas su lire » n'est "
                        "pas « il n'y avait rien ».*", True)

    if statut == 401:
        return Decision(ABANDONNER, 0.0,
                        "401 — le token est refusé. *On ne fait pas semblant : on le DIT.*", True)

    # ── serveur cassé / réseau : backoff, mais borné. *On ne répare pas GitHub en insistant.* ──
    if statut is None or statut >= 500 or statut == 408:
        if essai >= MAX_ESSAIS_SERVEUR:
            return Decision(ABANDONNER, 0.0,
                            "abandon après %d essais (%s). **Compté comme NON LU.**"
                            % (essai, statut or "réseau"), True)
        a = _backoff(essai, alea=alea)
        return Decision(REESSAYER, a,
                        "%s — backoff %.1f s (essai %d/%d), avec **jitter** pour ne pas "
                        "resynchroniser la tempête."
                        % (statut or "réseau", a, essai + 1, MAX_ESSAIS_SERVEUR))

    return Decision(ABANDONNER, 0.0,
                    "statut %s inattendu — **compté comme non lu**, jamais comme vide."
                    % statut, True)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LE JOURNAL DES BLESSURES — *un scan qui ne se plaint jamais est un scan qui ment.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
@dataclass
class Blessures:
    """Tout ce qu'on n'a **pas** su lire. **Ça se publie**, ça ne se cache pas."""
    non_lus: list[str] = field(default_factory=list)
    quotas_attendus: int = 0
    secondes_attendues: float = 0.0
    reessais: int = 0
    abandons: dict[str, str] = field(default_factory=dict)

    def note(self, cle: str, d: Decision) -> None:
        if d.action == ATTENDRE:
            self.quotas_attendus += 1
            self.secondes_attendues += d.attente_s
        elif d.action == REESSAYER:
            self.reessais += 1
        elif d.action == ABANDONNER:
            if cle not in self.abandons:
                self.abandons[cle] = d.raison
                self.non_lus.append(cle)

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_non_lus": len(self.non_lus),
            "non_lus": self.non_lus[:200],
            "quotas_attendus": self.quotas_attendus,
            "minutes_attendues": round(self.secondes_attendues / 60.0, 1),
            "reessais": self.reessais,
            "abandons": self.abandons,
            "avertissement": (
                "🔴 **Ces %d sources n'ont PAS été lues.** Elles ne sont **pas** vides : "
                "**je n'ai pas su les lire.** *C'est exactement la confusion qui a perdu 235 "
                "README — dont hftbacktest, notre cible n°1.*" % len(self.non_lus)
            ),
        }

    def rapport(self) -> str:
        if not self.non_lus and not self.quotas_attendus:
            return "✅ aucune blessure : tout a été lu."
        return (
            "⚠️ **%d source(s) NON LUE(S)** · %d attente(s) de quota (%.1f min) · %d réessai(s).\n"
            "   *« Je n'ai pas su lire » n'est PAS « il n'y avait rien ». Le scan n'est pas mort — "
            "mais il n'est pas complet, et il le DIT.*"
            % (len(self.non_lus), self.quotas_attendus,
               self.secondes_attendues / 60.0, self.reessais)
        )


__all__ = [
    "ABANDONNER", "ATTENDRE", "ATTENTE_BASE", "ATTENTE_MAX", "MAX_ESSAIS_SERVEUR",
    "REESSAYER", "REUSSI",
    "Blessures", "Decision", "decider",
]
