"""LES ZONES MORTES : ce qu'on a DEJA paye pour apprendre (2026-07-12).

    fail -> investigate -> distil -> consult

C'est la piece que l'article de Horizon nomme, et la SEULE de son framework qu'on n'avait pas.
Sans elle, ecrit-il : *l'agent re-propose des variantes qu'il a deja rejetees et brule du compute
en tournant en rond.*

ON L'A VECU, ET CA NOUS A COUTE DES JOURS :

  * j'ai passe des sessions a regler le seuil `min_edge` sur un edge FABRIQUE
    (`dominance x 45`), sans jamais ouvrir la fonction qui le produisait ;
  * Codex a re-propose le bus GitHub, ecarte depuis des semaines (PF net 0,61) ;
  * on a re-teste des calibrages SL/TP dont on savait deja qu'aucun n'etait positif OOS.

Chaque impasse etait DEJA connue. Elle vivait dans une tete ou dans un fichier de notes.
Pas dans le code. Donc elle ne protegeait personne.

CE MODULE : une zone morte est une hypothese TUEE PAR UNE MESURE. Elle porte sa preuve chiffree,
la taille de son echantillon, et la condition EXACTE qui la reouvrirait. On la consulte AVANT de
proposer. On ne la contourne pas.

    UNE ZONE MORTE N'EST PAS UN AVIS. C'EST UN CADAVRE AVEC UN CERTIFICAT DE DECES.

Une hypothese sans preuve chiffree n'entre PAS ici -- sinon le registre deviendrait un dogme, et
on interdirait des pistes pour de mauvaises raisons. C'est le risque symetrique, et il est reel.

PUR (sauf lecture/ecriture JSON). Aucun ordre reel.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

CHEMIN_DEFAUT = "runtime/agent/zones_mortes.json"

# Une zone morte sans preuve chiffree est un DOGME. On refuse.
CHAMPS_PREUVE = ("mesure", "valeur", "echantillon")
MIN_ECHANTILLON = 30

# =============================================================================================
# 🔴 LE BUG LE PLUS GRAVE DE CE MODULE (trouve par Flo, 2026-07-13)
# =============================================================================================
# « Pourtant ce sont toutes des decisions que TOI tu avais choisi de garder. Ce n'est pas
#   coherent. »  -- et il avait raison.
#
# Le meme jour, sur treize idees, j'ai applique DEUX standards opposes :
#   * j'en ai ENTERRE six sans mesure sur elles, par extrapolation d'une mesure faite AILLEURS ;
#   * j'en ai GARDE sept en invoquant « pas de mesure = prejuge ».
#
# La meme situation epistemique, deux verdicts. Et le biais avait un sens : enterrer RACCOURCIT
# la liste. J'etais rigoureux la ou ca ne coutait rien, et laxiste la ou ca me faisait gagner.
#
# LA CAUSE TECHNIQUE : `consulter()` refuse sur des MOTS-CLES. Or un mot-cle est une MENTION,
# pas un MECANISME. C'est EXACTEMENT le bug grep-vs-AST que j'ai corrige deux fois dans le code
# le meme jour -- ici, il etait dans mon raisonnement.
#
# LA REGLE, DESORMAIS TESTEE :
#
#     Une zone morte ne peut refuser une idee QUE si l'idee consomme
#     LA MEME ENTREE que celle sur laquelle la mesure a ete faite.
#
# Exemple concret paye aujourd'hui : la mesure « -7,97 bps » porte sur le FILL PUBLIC D'UN
# LEADER. Elle tue donc LSTM/Transformer sur ce signal (meme entree, autre fonction). Elle ne
# dit RIEN d'un RL de politique de SORTIE, dont l'entree est l'etat APRES l'entree en position.
# J'avais quand meme enterre le second. C'etait un prejuge deguise en deduction.
ENTREE_NON_DECLAREE = ""

# 🔴 LE MOT-CLE MORT (trouve par un test ROUGE, le 2026-07-13).
# `consulter()` extrait les mots par la regex [a-z_]{3,} : un mot-cle de MOINS de 3 caracteres
# ne peut donc **JAMAIS** matcher. Il ne protege RIEN -- il donne juste l'impression d'une
# couverture. Deux existaient : "rl" (zone ML) et "mm" (zone market making).
# C'est la meme maladie que le reste du projet : *une capacite presente, un chainon manquant, et
# personne qui se plaint.* Un test l'interdit desormais (test_zones_mortes_entree_mesuree.py).
MIN_LONGUEUR_MOT_CLE = 3


@dataclass(frozen=True, slots=True)
class ZoneMorte:
    """Une hypothese TUEE par une mesure. Avec son certificat de deces."""

    id: str
    hypothese: str                  # ce qu'on croyait
    verdict: str                    # ce que la mesure a dit
    mesure: str                     # QUOI a ete mesure
    valeur: float                   # le chiffre qui tue
    unite: str
    echantillon: int                # sur combien d'observations
    date: str
    lecon: str                      # la regle GENERALE distillee (pas l'anecdote)
    condition_de_reouverture: str   # ce qui devrait changer pour re-tester. JAMAIS "jamais".
    # 🔴 L'ENTREE QUE LA MESURE A REELLEMENT CONSOMMEE. Sans elle, un refus n'est qu'un mot-cle.
    entree_mesuree: str = ENTREE_NON_DECLAREE
    mots_cles: tuple[str, ...] = ()
    # LES MOTS QUI SIGNALENT QU'ON EMPRUNTE LA VOIE DE REOUVERTURE (2026-07-12).
    # BUG QUE J'AI COMMIS EN ECRIVANT CE MODULE : le registre refusait "funding delta-neutre avec
    # une vraie jambe spot" -- alors que c'est LITTERALEMENT sa propre condition de reouverture.
    # Un registre qui bloque sa propre issue de secours n'est plus une memoire : c'est un dogme.
    mots_cles_reouverture: tuple[str, ...] = ()
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "hypothese": self.hypothese, "verdict": self.verdict,
            "mesure": self.mesure, "valeur": self.valeur, "unite": self.unite,
            "echantillon": self.echantillon, "date": self.date, "lecon": self.lecon,
            "condition_de_reouverture": self.condition_de_reouverture,
            "entree_mesuree": self.entree_mesuree,
            "mots_cles": list(self.mots_cles),
            "mots_cles_reouverture": list(self.mots_cles_reouverture),
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class Examen:
    """Le verdict du registre sur une proposition. Trois etats, pas deux.

    L'ancien `refus()` n'en connaissait que DEUX : refuse, ou libre. C'est ce binaire qui m'a
    pousse a la faute : un mot-cle qui touche mais dont l'entree ne correspond pas n'est ni un
    refus legitime, ni un feu vert. C'est **une question a instruire**.
    """

    statut: str                       # LIBRE | REFUS | A_EXAMINER
    motif: str = ""
    zones: tuple[str, ...] = ()

    @property
    def refuse(self) -> bool:
        return self.statut == "REFUS"


class PreuveInsuffisante(ValueError):
    """On refuse d'enterrer une hypothese sans l'avoir tuee par une mesure."""


def creer_zone_morte(
    *,
    id: str,
    hypothese: str,
    verdict: str,
    mesure: str,
    valeur: float,
    unite: str,
    echantillon: int,
    lecon: str,
    condition_de_reouverture: str,
    entree_mesuree: str,
    mots_cles: Iterable[str] = (),
    mots_cles_reouverture: Iterable[str] = (),
    source: str = "",
    date: str | None = None,
) -> ZoneMorte:
    """DENY-BY-DEFAULT : une zone morte exige une preuve. Sinon c'est un prejuge."""
    if int(echantillon) < MIN_ECHANTILLON:
        raise PreuveInsuffisante(
            "echantillon %d < %d : une hypothese ne se tue pas sur une impression"
            % (echantillon, MIN_ECHANTILLON)
        )
    if not str(lecon).strip():
        raise PreuveInsuffisante("sans lecon GENERALE, on n'a qu'une anecdote")
    if not str(condition_de_reouverture).strip():
        raise PreuveInsuffisante(
            "toute zone morte doit dire ce qui la REOUVRIRAIT. Une impasse definitive est un "
            "dogme, pas une mesure."
        )
    # 🔴 AJOUTE LE 2026-07-13, APRES LA FAUTE. Une zone morte doit dire SUR QUELLE ENTREE elle a
    # mesure. Sans ce champ, son refus ne repose que sur un mot-cle -- c'est-a-dire sur une
    # MENTION, pas sur un MECANISME. Le meme piege que grep-vs-AST, un etage plus haut.
    if not str(entree_mesuree).strip():
        raise PreuveInsuffisante(
            "toute zone morte doit declarer l'ENTREE que sa mesure a consommee. Sans elle, elle "
            "refuserait des idees qui ne consomment PAS cette entree -- et ce serait un prejuge "
            "deguise en deduction. (Faute commise le 2026-07-13 sur IDEA-04 et IDEA-47.)"
        )
    return ZoneMorte(
        id=str(id), hypothese=str(hypothese), verdict=str(verdict),
        mesure=str(mesure), valeur=float(valeur), unite=str(unite),
        echantillon=int(echantillon),
        date=str(date or datetime.now(timezone.utc).date()),
        lecon=str(lecon), condition_de_reouverture=str(condition_de_reouverture),
        entree_mesuree=str(entree_mesuree).strip().lower(),
        mots_cles=tuple(str(m).lower() for m in mots_cles),
        mots_cles_reouverture=tuple(str(m).lower() for m in mots_cles_reouverture),
        source=str(source),
    )


@dataclass(slots=True)
class RegistreZonesMortes:
    """Le cimetiere. On le CONSULTE avant de proposer -- on ne le contourne pas."""

    zones: list[ZoneMorte] = field(default_factory=list)

    # ------------------------------------------------------------------ consulter

    def consulter(self, proposition: str) -> list[ZoneMorte]:
        """Cette proposition tombe-t-elle dans une zone deja morte ?

        C'est le `consult` de l'article. Appele AVANT toute nouvelle recherche.
        """
        texte = str(proposition or "").lower()
        if not texte:
            return []
        mots = set(re.findall(r"[a-z_]{%d,}" % MIN_LONGUEUR_MOT_CLE, texte))
        touches = []
        for z in self.zones:
            if any(m in mots for m in z.mots_cles):
                touches.append(z)
        return touches

    def voie_de_reouverture(self, proposition: str) -> list[ZoneMorte]:
        """Cette proposition EMPRUNTE-T-ELLE la voie de reouverture d'une zone morte ?

        C'est le contraire d'un refus : c'est le chemin que la zone morte elle-meme designe.
        Un registre qui bloque sa propre issue de secours est un DOGME, pas une memoire.
        """
        texte = str(proposition or "").lower()
        if not texte:
            return []
        mots = set(re.findall(r"[a-z_]{%d,}" % MIN_LONGUEUR_MOT_CLE, texte))
        return [z for z in self.zones
                if z.mots_cles_reouverture and any(m in mots for m in z.mots_cles_reouverture)]

    def examiner(self, proposition: str, *, entree: str = ENTREE_NON_DECLAREE) -> Examen:
        """🔴 LE CORRECTIF DU 2026-07-13. Trois etats, parce que DEUX m'ont fait mentir.

        `entree` = l'entree que l'idee CONSOMME reellement (le signal qu'elle lit).

        * entree NON declaree  -> comportement historique : mot-cle touche = REFUS.
          (deny-by-default : on ne relache rien par omission)
        * entree declaree ET EGALE a celle de la zone -> REFUS. La mesure porte sur la MEME
          entree : le refus est une DEDUCTION.
        * entree declaree et DIFFERENTE -> **A_EXAMINER**. Le mot-cle a touche, mais la mesure ne
          dit RIEN de cette entree-la. Ce n'est ni un refus ni un feu vert : c'est une question.

        C'est exactement la distinction que je n'ai pas faite en enterrant IDEA-04 (RL de SORTIE :
        entree = l'etat APRES l'entree en position) et IDEA-47 (identifier la CONTREPARTIE de
        NOTRE fill) au nom d'une mesure faite sur le FILL PUBLIC D'UN LEADER.
        """
        touches = self.consulter(proposition)
        if not touches:
            return Examen(statut="LIBRE")
        motif = self.refus(proposition)
        if not motif:
            return Examen(statut="LIBRE", zones=tuple(z.id for z in touches))
        e = str(entree or "").strip().lower()
        if not e:
            return Examen(statut="REFUS", motif=motif, zones=tuple(z.id for z in touches))
        memes = [z for z in touches if z.entree_mesuree == e]
        if memes:
            return Examen(statut="REFUS", motif=motif, zones=tuple(z.id for z in memes))
        autres = ", ".join("%s (mesure sur : %s)" % (z.id, z.entree_mesuree) for z in touches)
        return Examen(
            statut="A_EXAMINER",
            motif=(
                "MOT_CLE_TOUCHE_MAIS_ENTREE_DIFFERENTE : cette idee consomme `%s`, alors que les "
                "zones touchees ont mesure une AUTRE entree -- %s. Une mesure faite sur une autre "
                "entree ne tue pas cette idee : elle n'en parle pas. INSTRUIRE, ne pas refuser."
                % (e, autres)
            ),
            zones=tuple(z.id for z in touches),
        )

    def refus(self, proposition: str) -> str:
        """Le motif de refus, avec la PREUVE. Vide si la proposition est libre OU si elle
        emprunte la voie de reouverture designee par la zone morte elle-meme.

        ⚠️ NE TIENT PAS COMPTE DE L'ENTREE. Conserve pour les appelants historiques (et parce que
        deny-by-default sans entree declaree reste le bon defaut). Pour une decision honnete,
        appeler `examiner(proposition, entree=...)`.
        """
        touches = self.consulter(proposition)
        if not touches:
            return ""
        # BUG CORRIGE (2026-07-12) -- LE REGISTRE S'AUTO-DESARMAIT.
        #
        # Avant : `if self.voie_de_reouverture(proposition)` -> N'IMPORTE QUELLE zone du registre.
        # Une proposition de COPY-TRADING qui prononce le mot « spot » etait donc blanchie par la
        # voie de reouverture du FUNDING. Une zone morte pouvait annuler le refus d'une AUTRE.
        #
        # Desormais : seule la voie de reouverture des zones REELLEMENT TOUCHEES compte.
        # Chaque zone garde son issue de secours -- et celle des autres ne la concerne pas.
        ids_touches = {z.id for z in touches}
        rouvre_les_zones_touchees = [
            z for z in self.voie_de_reouverture(proposition) if z.id in ids_touches
        ]
        if rouvre_les_zones_touchees and len(rouvre_les_zones_touchees) == len(touches):
            # TOUTES les zones touchees sont rouvertes par cette proposition -> pas de refus.
            return ""
        # Sinon on refuse au nom de la premiere zone NON rouverte.
        restantes = [z for z in touches if z.id not in {x.id for x in rouvre_les_zones_touchees}]
        z = restantes[0] if restantes else touches[0]
        return (
            "ZONE_MORTE[%s] : %s -- mesure : %s = %+.2f %s sur %d observations (%s). "
            "Lecon : %s. Pour rouvrir : %s"
            % (z.id, z.verdict, z.mesure, z.valeur, z.unite, z.echantillon, z.date,
               z.lecon, z.condition_de_reouverture)
        )

    # ------------------------------------------------------------------ enterrer

    def enterrer(self, zone: ZoneMorte) -> bool:
        if any(z.id == zone.id for z in self.zones):
            return False
        self.zones.append(zone)
        return True

    def exhumer(self, zone_id: str, *, raison: str) -> bool:
        """Une zone morte PEUT etre rouverte -- mais jamais en silence.

        Le marche change. Une mesure faite sur 6 h de donnees illiquides n'est pas une loi de la
        nature. Rouvrir exige une raison ECRITE : c'est ce qui distingue une science d'un dogme.
        """
        if not str(raison).strip():
            raise PreuveInsuffisante("on ne rouvre pas une zone morte sans raison ecrite")
        avant = len(self.zones)
        self.zones = [z for z in self.zones if z.id != zone_id]
        return len(self.zones) < avant

    # ------------------------------------------------------------------ persistance

    def as_dict(self) -> dict[str, Any]:
        return {
            "zones_mortes": [z.as_dict() for z in self.zones],
            "n": len(self.zones),
            "note": (
                "Chaque entree est une hypothese TUEE PAR UNE MESURE, avec son echantillon et "
                "la condition qui la rouvrirait. Ce n'est pas une liste d'opinions."
            ),
            "real_execution": False,
        }

    def sauver(self, chemin: str = CHEMIN_DEFAUT) -> None:
        p = Path(chemin)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def charger(cls, chemin: str = CHEMIN_DEFAUT) -> "RegistreZonesMortes":
        p = Path(chemin)
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()                    # etat vide honnete : jamais de registre invente
        zones = []
        for row in data.get("zones_mortes") or []:
            if not isinstance(row, Mapping):
                continue
            try:
                zones.append(ZoneMorte(
                    id=str(row["id"]), hypothese=str(row["hypothese"]),
                    verdict=str(row["verdict"]), mesure=str(row["mesure"]),
                    valeur=float(row["valeur"]), unite=str(row.get("unite") or ""),
                    echantillon=int(row["echantillon"]), date=str(row.get("date") or ""),
                    lecon=str(row.get("lecon") or ""),
                    condition_de_reouverture=str(row.get("condition_de_reouverture") or ""),
                    entree_mesuree=str(row.get("entree_mesuree") or ""),
                    mots_cles=tuple(row.get("mots_cles") or ()),
                    source=str(row.get("source") or ""),
                ))
            except (KeyError, TypeError, ValueError):
                continue                    # une entree cassee n'invalide pas les autres
        return cls(zones=zones)


__all__ = [
    "CHEMIN_DEFAUT", "ENTREE_NON_DECLAREE", "MIN_ECHANTILLON", "MIN_LONGUEUR_MOT_CLE",
    "Examen", "PreuveInsuffisante", "RegistreZonesMortes", "ZoneMorte", "creer_zone_morte",
]
