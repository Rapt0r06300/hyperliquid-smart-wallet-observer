"""LA PORTE DE PROMOTION — comment le labo parle au moteur sans en faire une machine a surapprendre.

LA QUESTION POSEE : « si le labo trouve une meilleure strategie, le moteur doit s'en servir
tout de suite, c'est logique ». **Oui — mais l'automatiser naivement serait la pire chose a
construire**, et il faut dire pourquoi.

LE LABO EST UNE MACHINE A SELECTIONNER
--------------------------------------
Il teste beaucoup de candidats. Le MEILLEUR de `N` candidats parait bon **par pur hasard** : c'est
le mecanisme exact du PBO de 0,81 mesure sur ce labo. Promouvoir le mieux mesure, c'est promouvoir
le plus CHANCEUX, pas le meilleur. La session du 14/11 l'a montre trois fois :

* `k=3` ressemblait a un pic de bruit (+80,4 % entoure de +28,8 % et +44,0 %) jusqu'a verification
  sur trois tiers, ou il s'est revele le plus STABLE ;
* le `mmr` suppose a 5 % valait **12,32 %** une fois mesure — **-34 % sur le resultat** ;
* le repli calcule par periode donnait du levier par chance a toute periode courte.

LES QUATRE CONDITIONS DE LA PORTE
--------------------------------
1. **Le nombre d'essais est DECLARE.** Sans lui, aucune correction de multiplicite n'est possible.
   C'est le meme contrat que `test_transversal.tester(..., essais=)` : ne pas le declarer est un
   refus, jamais un `essais=1` suppose.
2. **La fenetre de jugement commence APRES le gel.** Un candidat ne se juge pas sur les donnees qui
   l'ont choisi. La porte compare les instants et refuse tout recouvrement.
3. **Assez d'observations INDEPENDANTES.** Des fenetres qui se chevauchent gonflent le compte sans
   que l'information suive : le labo doit declarer le nombre independant, pas le nombre de lignes.
4. **Le resultat hors echantillon doit etre positif ET COHERENT avec l'annonce.** Un ecart enorme
   **dans les deux sens** est suspect : trop bas = surapprentissage ; trop haut = une erreur de
   mesure ou une fuite. Un candidat qui fait cinq fois mieux que promis n'est pas une bonne
   nouvelle, c'est un bug a trouver.

CE QUE LA PORTE NE FAIT PAS
---------------------------
Elle ne classe pas, ne choisit pas, ne cherche pas. Elle **juge un candidat deja gele** et rend
`PROMU`, `REFUSE` ou `PAS_ENCORE`. Le labo propose, la porte filtre, le moteur n'ouvre que du
`PROMU`. Aucune de ces trois couches ne peut court-circuiter les deux autres.

PAPER / lecture seule.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

PROMU = "PROMU"
REFUSE = "REFUSE"
PAS_ENCORE = "PAS_ENCORE"

MOTIF_ESSAIS_NON_DECLARES = "NOMBRE_D_ESSAIS_NON_DECLARE"
MOTIF_FENETRE_CONTAMINEE = "FENETRE_DE_JUGEMENT_ANTERIEURE_AU_GEL"
MOTIF_PAS_ASSEZ_D_OBSERVATIONS = "PAS_ASSEZ_D_OBSERVATIONS_INDEPENDANTES"
MOTIF_NEGATIF = "RESULTAT_HORS_ECHANTILLON_NEGATIF"
MOTIF_INCOHERENT = "ECART_INCOHERENT_AVEC_L_ANNONCE"
MOTIF_EMPREINTE = "EMPREINTE_DU_CANDIDAT_MODIFIEE"
MOTIF_T_ABSENT = "T_DE_LA_SERIE_NON_FOURNI"
MOTIF_PAS_DISTINGUABLE = "PAS_DISTINGUABLE_DE_LA_CHANCE"

#: Minimum d'observations INDEPENDANTES. 8 n'est pas une science exacte, c'est le seuil en dessous
#: duquel une seule periode defavorable pese plus d'un huitieme du verdict — ce qui s'est produit
#: pour de vrai le 14/11 (une detention a -22,8 % ecrasait les cinq autres sur six).
OBSERVATIONS_MINIMUM = 8

#: Au-dela de ce rapport, l'ecart a l'annonce est juge incoherent. Un candidat qui fait 3x mieux
#: que promis n'est pas une bonne nouvelle : c'est une fuite ou une erreur de mesure.
RAPPORT_MAXIMUM = 3.0


@dataclass(frozen=True, slots=True)
class Candidat:
    """Un candidat GELE par le labo. L'empreinte rend toute retouche detectable."""

    strategy_id: str
    version: int
    parametres: tuple[tuple[str, str], ...]
    gel_instant_h: int
    #: Ce que le labo ANNONCE avoir mesure sur la fenetre de selection.
    annonce_par_periode: float
    #: Combien de candidats le labo a essayes AVANT de proposer celui-ci. **Obligatoire.**
    essais: int | None
    note: str = ""

    def empreinte(self) -> str:
        charge = json.dumps({"id": self.strategy_id, "v": int(self.version),
                             "p": [list(x) for x in self.parametres],
                             "gel": int(self.gel_instant_h),
                             "annonce": round(float(self.annonce_par_periode), 10),
                             "essais": self.essais}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(charge.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class ResultatHorsEchantillon:
    """Ce que la fenetre reservee a reellement donne."""

    debut_instant_h: int
    observations_independantes: int
    net_moyen_par_periode: float
    part_positive: float
    #: Le `t` de Student de la serie hors echantillon. C'est LUI qui ferme la porte, pas la part
    #: positive — voir `t_de_student`. S'il est absent, la porte REFUSE : elle ne le suppose pas.
    t: float | None = None
    empreinte_candidat: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def _z_bonferroni(essais: int) -> float:
    """Seuil de `t` exige, corrige par Bonferroni pour `N` essais declares.

    Avec `N` candidats essayes, la chance seule produit un bon `t` dans environ `N x alpha` cas. On
    divise donc le risque : `alpha_corrige = 0,05 / N`, et on exige le quantile normal bilateral
    correspondant. 1 essai -> **1,96** | 9 -> 2,77 | 25 -> 3,02 | 450 -> **3,86**.

    C'est la correction STANDARD, pas une formule maison — et c'est important : un seuil invente se
    discute, un Bonferroni ne se discute pas.
    """
    n = max(1, int(essais))
    alpha = 0.05 / n
    # Quantile normal bilateral par l'inverse de l'erreur complementaire : z = sqrt(2) * erfcinv(a).
    # `math.erfc` n'a pas d'inverse en bibliotheque standard -> dichotomie, 80 iterations suffisent
    # a la precision machine sur [0, 10] et evitent une dependance a scipy.
    bas, haut = 0.0, 10.0
    for _ in range(80):
        milieu = (bas + haut) / 2.0
        if math.erfc(milieu / math.sqrt(2.0)) > alpha:
            bas = milieu
        else:
            haut = milieu
    return (bas + haut) / 2.0


def t_de_student(nets: Sequence[float]) -> float | None:
    """`moyenne / (ecart-type / sqrt(n))`. `None` si non calculable.

    **POURQUOI LE `t` ET PAS LE TAUX DE REUSSITE.** La premiere version de cette porte exigeait une
    PART POSITIVE croissante avec le nombre d'essais. C'etait un defaut : j'avais moi-meme mesure
    que l'edge de ce livre vient de l'**ASYMETRIE** (de gros gains, de petites pertes) et non de la
    frequence — sa part positive vaut 0,58, a peine mieux qu'un pile ou face. Un suiveur de tendance
    gagne 40 % du temps et fait fortune : **juger sur la frequence penalise exactement le bon type
    d'edge.** Le `t` utilise la moyenne ET la dispersion, donc il recompense l'asymetrie.
    La part positive reste PUBLIEE comme diagnostic, mais elle ne ferme plus la porte.
    """
    valeurs = [float(x) for x in nets if isinstance(x, (int, float)) and math.isfinite(float(x))]
    # 15/11 — MINIMUM PORTE DE 2 A `OBSERVATIONS_MINIMUM`. En acceptant 2 points, cette fonction
    # rendait des `t` spectaculaires et vides : mesure du jour sur la base, **t = 4,25 sur TROIS
    # observations disjointes**, et son miroir a -4,74. Avec si peu de points, le `t` n'a presque
    # pas de degres de liberte et un ecart-type minuscule le fait exploser. La porte exigeait deja
    # 8 observations independantes, mais l'AFFICHAGE, lui, montrait le 4,25 sans reserve — et un
    # chiffre spectaculaire qu'on ne peut pas croire est plus dangereux qu'un refus.
    if len(valeurs) < OBSERVATIONS_MINIMUM:
        return None
    moyenne = sum(valeurs) / len(valeurs)
    variance = sum((x - moyenne) ** 2 for x in valeurs) / (len(valeurs) - 1)
    if variance <= 0:
        return None
    return moyenne / (math.sqrt(variance) / math.sqrt(len(valeurs)))


def juger(candidat: Candidat, resultat: ResultatHorsEchantillon) -> dict[str, Any]:
    """`PROMU` / `REFUSE` / `PAS_ENCORE`, avec le motif. La porte ne choisit pas, elle filtre."""
    if candidat.essais is None:
        return {"verdict": REFUSE, "motif": MOTIF_ESSAIS_NON_DECLARES,
                "lecture": ("le labo n'a pas declare combien de candidats il a essayes. Sans ce "
                            "nombre, aucune correction de multiplicite n'est possible, et "
                            "supposer un seul essai reviendrait a promouvoir le plus chanceux.")}
    attendue = candidat.empreinte()
    if resultat.empreinte_candidat and resultat.empreinte_candidat != attendue:
        return {"verdict": REFUSE, "motif": MOTIF_EMPREINTE,
                "lecture": (f"empreinte {resultat.empreinte_candidat} au lieu de {attendue} : le "
                            "candidat a ete modifie entre le gel et le jugement. Un protocole "
                            "reecrit apres coup ne prouve rien.")}
    if int(resultat.debut_instant_h) < int(candidat.gel_instant_h):
        return {"verdict": REFUSE, "motif": MOTIF_FENETRE_CONTAMINEE,
                "lecture": (f"jugement a partir de {resultat.debut_instant_h}, gel a "
                            f"{candidat.gel_instant_h} : un candidat ne se juge pas sur les "
                            "donnees qui l'ont choisi.")}
    if int(resultat.observations_independantes) < OBSERVATIONS_MINIMUM:
        return {"verdict": PAS_ENCORE, "motif": MOTIF_PAS_ASSEZ_D_OBSERVATIONS,
                "lecture": (f"{resultat.observations_independantes} observation(s) independante(s), "
                            f"il en faut {OBSERVATIONS_MINIMUM}. En dessous, une seule periode "
                            "defavorable decide du verdict.")}
    if float(resultat.net_moyen_par_periode) <= 0:
        return {"verdict": REFUSE, "motif": MOTIF_NEGATIF,
                "lecture": (f"net hors echantillon {resultat.net_moyen_par_periode:+.4%} : la "
                            "fenetre reservee refute le candidat.")}
    seuil_t = _z_bonferroni(candidat.essais)
    if resultat.t is None:
        return {"verdict": REFUSE, "motif": MOTIF_T_ABSENT, "seuil_t": seuil_t,
                "lecture": ("le `t` de la serie hors echantillon n'est pas fourni. La porte ne le "
                            "SUPPOSE pas : sans dispersion, on ne distingue pas un edge d'une "
                            "serie chanceuse.")}
    if float(resultat.t) < seuil_t:
        return {"verdict": REFUSE, "motif": MOTIF_PAS_DISTINGUABLE,
                "seuil_t": seuil_t, "t": float(resultat.t),
                "lecture": (f"t = {resultat.t:.2f} sous le seuil Bonferroni {seuil_t:.2f} exige "
                            f"pour {candidat.essais} essai(s) : le candidat ne se distingue pas "
                            f"assez de la chance. (part positive {resultat.part_positive:.0%}, "
                            "publiee comme diagnostic mais elle ne ferme pas la porte.)")}
    annonce = abs(float(candidat.annonce_par_periode))
    obtenu = abs(float(resultat.net_moyen_par_periode))
    if annonce > 0:
        rapport = max(obtenu / annonce, annonce / obtenu)
        if rapport > RAPPORT_MAXIMUM:
            return {"verdict": REFUSE, "motif": MOTIF_INCOHERENT, "rapport": rapport,
                    "lecture": (f"ecart d'un facteur {rapport:.1f} entre l'annonce "
                                f"({candidat.annonce_par_periode:+.4%}) et le hors echantillon "
                                f"({resultat.net_moyen_par_periode:+.4%}). Un candidat qui fait "
                                "bien MIEUX que promis n'est pas une bonne nouvelle : c'est une "
                                "fuite ou une erreur de mesure a trouver.")}
    return {"verdict": PROMU, "motif": None, "empreinte": attendue, "seuil_t": seuil_t,
            "t": float(resultat.t),
            "lecture": (f"{resultat.observations_independantes} observations independantes apres le "
                        f"gel, net {resultat.net_moyen_par_periode:+.4%}, t = {resultat.t:.2f} >= "
                        f"{seuil_t:.2f} exige pour {candidat.essais} essai(s) -> PROMU. "
                        f"(part positive {resultat.part_positive:.0%}, diagnostic.)")}


# ----------------------------------------------------------------- la chaine labo -> moteur

#: Ou vivent les propositions gelees et les promotions. Un seul endroit, pour qu'il n'y ait jamais
#: deux verites sur ce que le moteur a le droit d'ouvrir.
DOSSIER = "runtime/data/promotions"
SCHEMA_PROPOSITION = "hypersmart.candidat_gele.v1"
SCHEMA_PROMOTION = "hypersmart.strategie_promue.v1"


def ecrire_proposition(racine, candidat: Candidat) -> dict[str, Any]:
    """COTE LABO : geler un candidat. C'est le seul point d'entree vers le moteur.

    Le labo doit appeler ceci AVANT que la fenetre de jugement n'existe. L'empreinte est calculee
    ici et relue au jugement : une retouche posterieure devient donc detectable, et c'est tout
    l'interet. Si `essais` n'est pas renseigne, la porte refusera plus tard — on l'ecrit quand meme
    plutot que de bloquer ici, pour que le refus soit TRACE au lieu d'etre silencieux.
    """
    from pathlib import Path as _P
    dossier = _P(racine) / DOSSIER
    dossier.mkdir(parents=True, exist_ok=True)
    empreinte = candidat.empreinte()
    charge = {"_schema": SCHEMA_PROPOSITION, "empreinte": empreinte,
              "strategy_id": candidat.strategy_id, "version": int(candidat.version),
              "parametres": [list(x) for x in candidat.parametres],
              "gel_instant_h": int(candidat.gel_instant_h),
              "annonce_par_periode": float(candidat.annonce_par_periode),
              "essais": candidat.essais, "note": candidat.note}
    chemin = dossier / f"candidat_{candidat.strategy_id}_v{int(candidat.version)}.json"
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps(charge, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(chemin)
    return {"chemin": str(chemin), "empreinte": empreinte}


def lire_proposition(chemin) -> Candidat | None:
    """Relit un candidat gele et **verifie son empreinte**. Toute retouche -> `None`."""
    from pathlib import Path as _P
    try:
        d = json.loads(_P(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if d.get("_schema") != SCHEMA_PROPOSITION:
        return None
    try:
        candidat = Candidat(
            strategy_id=str(d["strategy_id"]), version=int(d["version"]),
            parametres=tuple(tuple(x) for x in d["parametres"]),
            gel_instant_h=int(d["gel_instant_h"]),
            annonce_par_periode=float(d["annonce_par_periode"]),
            essais=(None if d.get("essais") is None else int(d["essais"])),
            note=str(d.get("note", "")))
    except (KeyError, TypeError, ValueError):
        return None
    # Le fichier porte l'empreinte ; si elle ne correspond plus au contenu, le fichier a ete
    # retouche a la main. On refuse de le rendre plutot que de juger un candidat maquille.
    return candidat if d.get("empreinte") == candidat.empreinte() else None


def enregistrer_promotion(racine, candidat: Candidat, verdict: dict[str, Any]) -> str | None:
    """Ecrit la promotion que le moteur lira. **Seul un `PROMU` est ecrit.**"""
    if verdict.get("verdict") != PROMU:
        return None
    from pathlib import Path as _P
    dossier = _P(racine) / DOSSIER
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"promue_{candidat.strategy_id}.json"
    charge = {"_schema": SCHEMA_PROMOTION, "strategy_id": candidat.strategy_id,
              "version": int(candidat.version), "empreinte": candidat.empreinte(),
              "parametres": [list(x) for x in candidat.parametres],
              "essais": candidat.essais, "lecture": verdict.get("lecture", "")}
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps(charge, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(chemin)
    return str(chemin)


def strategies_autorisees(racine) -> dict[str, dict[str, Any]]:
    """COTE MOTEUR : ce qu'il a le droit d'ouvrir. **Deny-by-default.**

    Un dossier absent, vide ou illisible rend `{}` — donc AUCUNE strategie autorisee. C'est
    volontaire : en cas de doute, le moteur n'ouvre rien. Un systeme qui ouvre par defaut quand il
    ne sait pas est un systeme qui trade sur une erreur de lecture de fichier.
    """
    from pathlib import Path as _P
    dossier = _P(racine) / DOSSIER
    sortie: dict[str, dict[str, Any]] = {}
    if not dossier.is_dir():
        return sortie
    for chemin in sorted(dossier.glob("promue_*.json")):
        try:
            d = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("_schema") == SCHEMA_PROMOTION and d.get("strategy_id"):
            sortie[str(d["strategy_id"])] = d
    return sortie


__all__ = ["PROMU", "REFUSE", "PAS_ENCORE", "Candidat", "ResultatHorsEchantillon", "juger",
           "OBSERVATIONS_MINIMUM", "RAPPORT_MAXIMUM", "MOTIF_ESSAIS_NON_DECLARES",
           "MOTIF_FENETRE_CONTAMINEE", "MOTIF_PAS_ASSEZ_D_OBSERVATIONS", "MOTIF_NEGATIF",
           "MOTIF_INCOHERENT", "MOTIF_EMPREINTE", "MOTIF_T_ABSENT", "MOTIF_PAS_DISTINGUABLE",
           "t_de_student", "_z_bonferroni", "DOSSIER", "ecrire_proposition",
           "lire_proposition", "enregistrer_promotion", "strategies_autorisees"]
