"""AUTO-AMÉLIORATION DU MOTEUR (demande de Flo, 22/11/2026) : apprendre de ses résultats, seul.

CE QUE LE MOTEUR SAVAIT DÉJÀ FAIRE. Mesurer chaque cohorte papier sur son ledger, par configuration
(`config_hash`), et se mettre en pause quand l'espérance réalisée devient négative (auto-KILL). La
cohorte RAW_PROBE est son BAC À SABLE : 20 USD papier, 10 USD par position, figée après 20 cycles
clôturés « pour décision ». Son réglage vit hors du code, dans `runtime/data/raw_probe_auto.json`.

CE QUI MANQUAIT : la décision. Une fois l'échantillon complet, personne ne choisissait la variante
suivante ; le moteur s'arrêtait d'apprendre. Ce module est cette décision, automatique :

    OBSERVER   lire les cycles clôturés du bac à sable, par variante ;
    JUGER      une variante est GAGNANTE si la borne BASSE de son résultat moyen est > 0, PERDANTE si
               la borne HAUTE est < 0, INDÉCISE sinon — intervalle élargi par le nombre de variantes
               comparées (un gagnant « par chance » sur cinq essais ne passe pas) ;
    RETENIR    une variante PERDANTE n'est JAMAIS réessayée ; tout est consigné dans un journal chaîné ;
    ESSAYER    la variante suivante : d'abord celles jamais essayées (les mieux notées en fantôme
               d'abord), puis une INDÉCISE (au plus 3 échantillons), puis la meilleure GAGNANTE ;
    S'ABSTENIR quand tout est essayé et que rien ne gagne : le bac à sable reste figé. Ne pas trader
               EST le résultat appris, pas une panne.

GARDE-FOUS, non négociables :
  * on ne change JAMAIS de variante au milieu d'un échantillon (regarder en cours de route puis
    s'arrêter quand ça arrange fabrique des gagnants) ;
  * la mesure fantôme (`raw_shadow_variantes`) ORDONNE les essais, elle ne prouve rien ;
  * trois paramètres sont explorés dans le bac à sable, UN à la fois autour de la meilleure variante
    connue : le seuil relatif (`frac_tvl`), le stop (`stop_bps`) et l'horizon (`horizon_ms`) ; au plus
    15 variantes, après quoi on s'abstient ;
  * ÉCHELLE DE PROMOTION (22/11, à la demande de Flo) : une variante GAGNANTE confirmée par un second
    échantillon (40 cycles) voit son seuil promu à PROBE ; si PROBE gagne à son tour sur 20 cycles, à
    ALPHA. Une cohorte promue qui perd est RÉTROGRADÉE à ses défauts, et ce seuil n'y est plus jamais
    promu. Chaque cohorte a son propre fichier de réglage (`<prefixe>_auto.json`) : régler l'une ne
    déplace jamais les autres ;
  * PAPER uniquement, aucun réseau, aucune clé, aucun ordre. Mêmes règles d'isolation d'écriture que
    le moteur : un test ne peut pas écrire dans le vrai runtime.

CE QUE CE MODULE NE PEUT PAS FAIRE : créer un avantage qui n'existe pas. Il empêche de perdre
longtemps et il trouve ce qui marche s'il y a quelque chose à trouver. Rien de plus.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Any

from hl_observer.experimental import cohortes as CO
from hl_observer.experimental import raw_shadow_variantes as RS
from hl_observer.experimental import cycles_fantomes as CF
from hl_observer.experimental import apprentissage_parallele as AP

ECHANTILLON = CO.RAW_BASELINE_MAX_CYCLES        # 20 cycles clôturés = un échantillon complet
GENERATIONS_MAX = 3                             # une variante INDÉCISE est rejouée au plus 3 fois (60 cycles)
VARIANTES_MAX = 15                              # au-delà, sans gagnante : on arrête de payer pour chercher
ECHANTILLONS_POUR_PROMOUVOIR = 2                # une gagnante doit l'être sur 40 cycles avant de monter
NIVEAU = 0.95
TIRAGES = 4000
GRAINE = 20_261_122
SHADOW_MIN = 30                                 # en deçà, la mesure fantôme n'ordonne rien
BUCKETS_EXECUTABLES = ("<1s", "1-2s", "2-5s")   # âges sous le plafond de sécurité de 5 s du moteur
DOSSIER = Path("runtime") / "auto_amelioration"
#: Les paramètres explorés, dans l'ordre où on les fait varier. Une variante = un triplet.
DIMENSIONS: tuple[tuple[str, tuple[float, ...]], ...] = (
    ("frac_tvl", tuple(RS.FRACS)),
    ("stop_bps", (20.0, 40.0, 80.0)),
    ("horizon_ms", (900_000.0, 3_600_000.0, 14_400_000.0)),
)
BASE = (float(CO.FRAC_TVL_SIGNIF), float(CO.RAW_PROBE.stop_bps_defaut), 3_600_000.0)   # la variante d'origine (`v1`)
ECHELLE = (CO.PROBE, CO.ALPHA)                  # ordre de promotion au-dessus du bac à sable
_ETIQUETTE = re.compile(r"^auto-f(?P<f>[0-9.eE+-]+)-s(?P<s>[0-9.eE+-]+)-h(?P<h>[0-9.eE+-]+)-g(?P<g>[0-9]+)$")
_PROMUE = re.compile(r"^promu-f(?P<f>[0-9.eE+-]+)-n(?P<n>[0-9]+)$")
Variante = tuple[float, float, float]


def etiquette(variante: Variante, generation: int) -> str:
    return "auto-f%r-s%r-h%r-g%d" % (float(variante[0]), float(variante[1]), float(variante[2]), int(generation))


def lire_etiquette(texte: str) -> tuple[Variante, int] | None:
    """(variante, génération) d'une étiquette. `v1` = la variante d'origine du moteur, génération 0."""
    if texte == "v1":
        return BASE, 0
    if str(texte).startswith("par-"):                  # réglage armé par l'apprentissage parallèle
        v = AP.lire_variante(str(texte))
        return (v, 0) if v is not None else None
    m = _ETIQUETTE.match(str(texte))
    if not m:
        return None
    try:
        return (float(m.group("f")), float(m.group("s")), float(m.group("h"))), int(m.group("g"))
    except ValueError:
        return None


def cycles_clotures(root: Path, cohorte: CO.Cohorte = CO.RAW_PROBE) -> list[dict]:
    """Les CLOSE d'une cohorte. Fichier absent = aucun cycle (pas une erreur)."""
    try:
        texte = CO._p(cohorte, Path(root), "ledger.jsonl").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    cycles = []
    for ligne in texte.splitlines():
        try:
            evt = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(evt, dict) and evt.get("evt") == "CLOSE" and evt.get("realized_usd") is not None:
            cycles.append(evt)
    return cycles


def intervalle(valeurs: list[float], *, comparaisons: int = 1) -> dict:
    """Moyenne et intervalle par bootstrap, élargi par le nombre de variantes comparées (Bonferroni)."""
    n = len(valeurs)
    if n == 0:
        return {"n": 0, "moyenne": None, "bas": None, "haut": None}
    moyenne = sum(valeurs) / n
    if n < 5:
        return {"n": n, "moyenne": moyenne, "bas": None, "haut": None}
    alpha = (1.0 - NIVEAU) / max(1, int(comparaisons))
    rng = random.Random(GRAINE)
    tires = sorted(sum(rng.choices(valeurs, k=n)) / n for _ in range(TIRAGES))
    return {"n": n, "moyenne": moyenne,
            "bas": tires[int((alpha / 2) * (TIRAGES - 1))], "haut": tires[int((1 - alpha / 2) * (TIRAGES - 1))]}


def bilan_par_variante(cycles: list[dict]) -> dict[Variante, dict]:
    """Regroupe les cycles par variante (toutes générations confondues). Étiquette inconnue = ignorée
    et COMPTÉE à part par l'appelant : on ne devine pas à quelle variante elle appartenait."""
    par_variante: dict[Variante, dict] = {}
    for c in cycles:
        lu = lire_etiquette(str(c.get("trigger_version") or ""))
        if lu is None:
            continue
        variante, generation = lu
        b = par_variante.setdefault(variante, {"pnls": [], "generations": set()})
        b["pnls"].append(float(c["realized_usd"]))
        b["generations"].add(generation)
    return par_variante


def juger(par_variante: dict[Variante, dict]) -> dict[Variante, dict]:
    comparaisons = max(1, len(par_variante))
    verdicts = {}
    for variante, b in par_variante.items():
        echantillons = len(b["pnls"]) // ECHANTILLON
        ic = intervalle(b["pnls"], comparaisons=comparaisons)
        if echantillons == 0 or ic["bas"] is None:
            statut = "EN_COURS"
        elif ic["bas"] > 0:
            statut = "GAGNANTE"
        elif ic["haut"] < 0:
            statut = "PERDANTE"
        elif len(b["generations"]) >= GENERATIONS_MAX:
            statut = "ABANDONNEE"                      # 3 échantillons sans conclure : on arrête de payer pour savoir
        else:
            statut = "INDECISE"
        verdicts[variante] = {**ic, "statut": statut, "generations": sorted(b["generations"]),
                              "echantillons": echantillons, "pnl_cumule_usd": round(sum(b["pnls"]), 6)}
    return verdicts


def mesure_fantome(root: Path) -> dict[float, dict]:
    """Par `frac_tvl` : nombre et rendement net moyen des OPEN fantômes d'âge exécutable. Sert à
    ORDONNER les essais, jamais à conclure."""
    try:
        d = json.loads((Path(root) / RS.SORTIE_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cumul: dict[float, list[float]] = {}
    for cellule in d.get("grille") or []:
        if not isinstance(cellule, dict) or cellule.get("bucket_age") not in BUCKETS_EXECUTABLES:
            continue
        n, moyenne = cellule.get("n"), cellule.get("net_bps_moyen")
        if not n or moyenne is None:
            continue
        c = cumul.setdefault(float(cellule["frac_tvl"]), [0.0, 0.0])
        c[0] += float(n)
        c[1] += float(n) * float(moyenne)
    return {frac: {"n": int(n), "net_bps_moyen": s / n} for frac, (n, s) in cumul.items() if n > 0}


def voisines(base: Variante, fantome: dict[float, dict]) -> list[Variante]:
    """Les variantes qui diffèrent de `base` par UN seul paramètre, dans l'ordre d'essai : le seuil
    d'abord (les mieux notés en fantôme d'abord), puis le stop, puis l'horizon."""
    def note(frac: float) -> tuple[float, float]:
        f = fantome.get(frac)
        return (f["net_bps_moyen"] if f is not None and f["n"] >= SHADOW_MIN else 0.0, -abs(frac - base[0]))

    sortie: list[Variante] = []
    for i, (nom, valeurs) in enumerate(DIMENSIONS):
        autres = [v for v in valeurs if v != base[i]]
        if nom == "frac_tvl":
            autres.sort(key=note, reverse=True)
        for valeur in autres:
            v = list(base)
            v[i] = float(valeur)
            sortie.append(tuple(v))
    return sortie


def decider(*, n_cycles_courants: int, verdicts: dict[Variante, dict], fantome: dict[float, dict]) -> dict:
    """La décision pour le bac à sable, PURE. `n_cycles_courants` = cycles clôturés de la configuration
    en vigueur (le compte que le moteur utilise lui-même pour figer)."""
    if n_cycles_courants < ECHANTILLON:
        return {"action": "CONTINUER", "motif": "echantillon en cours : %d/%d cycles" % (n_cycles_courants, ECHANTILLON)}
    juges = {v: x for v, x in verdicts.items() if x["statut"] != "EN_COURS"}
    if not juges:
        return {"action": "ESSAYER", "variante": BASE, "generation": 1,
                "motif": "configuration en vigueur non attribuable : on repart de la variante d'origine"}
    ordre = {"GAGNANTE": 0, "INDECISE": 1, "ABANDONNEE": 2, "PERDANTE": 3}
    classees = sorted(juges, key=lambda v: (ordre[juges[v]["statut"]], -(juges[v]["bas"] if juges[v]["statut"] == "GAGNANTE" else juges[v]["moyenne"])))
    if len(verdicts) < VARIANTES_MAX:
        # on explore autour de la meilleure variante connue ; à défaut, autour des suivantes non perdantes
        centres = [classees[0]] + [v for v in classees[1:] if juges[v]["statut"] in ("GAGNANTE", "INDECISE")]
        for centre in centres:
            for candidate in voisines(centre, fantome):
                if candidate not in verdicts:
                    return {"action": "ESSAYER", "variante": candidate, "generation": 1,
                            "motif": "voisine jamais essayee de la meilleure variante connue (%s)" % juges[centre]["statut"]}
    indecises = [v for v in classees if juges[v]["statut"] == "INDECISE"]
    if indecises:
        v = indecises[0]
        return {"action": "ESSAYER", "variante": v, "generation": max(juges[v]["generations"]) + 1,
                "motif": "variante indecise : un echantillon de plus pour trancher"}
    gagnantes = [v for v in classees if juges[v]["statut"] == "GAGNANTE"]
    if gagnantes:
        v = gagnantes[0]
        return {"action": "EXPLOITER", "variante": v, "generation": max(juges[v]["generations"]) + 1,
                "motif": "variante GAGNANTE (borne basse %.4f USD/cycle) : on la garde" % juges[v]["bas"]}
    return {"action": "S_ABSTENIR", "motif": "%d variantes essayees, aucune gagnante : le bac a sable reste fige" % len(verdicts)}


# --------------------------------------------------------------------------- échelle de promotion

def _lire_json(chemin: Path) -> dict:
    try:
        j = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return j if isinstance(j, dict) else {}


def lire_journal(root: Path) -> list[dict]:
    try:
        lignes = (Path(root) / DOSSIER / "journal.ndjson").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    sortie = []
    for ligne in lignes:
        try:
            sortie.append(json.loads(ligne))
        except ValueError:
            continue
    return sortie


def decider_echelle(*, verdicts_bac: dict[Variante, dict], reglages: dict[str, dict],
                    pnls_promus: dict[str, list[float]], retrogradees: dict[str, set[float]]) -> list[dict]:
    """Promotions et rétrogradations, PURES. Par cohorte de l'échelle (PROBE puis ALPHA) :

    * `reglages[nom]` = son réglage auto en vigueur ({} = défauts) ;
    * `pnls_promus[nom]` = résultats de SES cycles sous le réglage promu en vigueur ;
    * `retrogradees[nom]` = seuils déjà rétrogradés à ce niveau (jamais re-promus).

    Une seule action par cohorte et par passe ; la rétrogradation passe avant tout.
    """
    actions: list[dict] = []
    source_frac: float | None = None           # le seuil prouvé au niveau du dessous
    gagnantes = sorted((v for v, x in verdicts_bac.items()
                        if x["statut"] == "GAGNANTE" and x["echantillons"] >= ECHANTILLONS_POUR_PROMOUVOIR),
                       key=lambda v: verdicts_bac[v]["bas"], reverse=True)
    if gagnantes:
        source_frac = gagnantes[0][0]
    for cohorte in ECHELLE:
        nom = cohorte.nom
        promu = reglages.get(nom) or {}
        frac_promu = promu.get("frac_tvl") if _PROMUE.match(str(promu.get("variante") or "")) else None
        ic = intervalle(pnls_promus.get(nom) or [])
        if frac_promu is not None and ic["n"] >= 10 and ic["moyenne"] < 0:
            # même critère que la pause automatique du moteur (10 cycles, espérance négative) : on ne
            # laisse pas une cohorte promue en pause indéfinie, on la rend à ses défauts
            actions.append({"action": "RETROGRADER", "cohorte": nom, "frac_tvl": float(frac_promu),
                            "motif": "%d cycles sous le reglage promu, moyenne %.4f USD/cycle" % (ic["n"], ic["moyenne"])})
            source_frac = None                  # rien ne monte plus haut depuis un niveau qui vient de perdre
            continue
        if (frac_promu is None and source_frac is not None
                and source_frac not in retrogradees.get(nom, set())):
            actions.append({"action": "PROMOUVOIR", "cohorte": nom, "frac_tvl": float(source_frac),
                            "motif": "seuil prouve au niveau inferieur"})
            source_frac = None                  # un seul niveau à la fois : le suivant attend SA propre preuve
            continue
        # ce niveau ne transmet son seuil plus haut que s'il l'a lui-même prouvé
        prouve = frac_promu is not None and ic["n"] >= ECHANTILLON and ic["bas"] is not None and ic["bas"] > 0
        source_frac = float(frac_promu) if prouve else None
    return actions


def _ecrire_atomique(chemin: Path, contenu: Any) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(chemin.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(contenu, ensure_ascii=False, sort_keys=True, indent=1))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, chemin)


def _journaliser(root: Path, ligne: dict) -> str:
    """Journal CHAÎNÉ (chaque ligne porte l'empreinte de la précédente) : la mémoire de ce qui a été
    essayé et pourquoi. Ajout seulement."""
    chemin = Path(root) / DOSSIER / "journal.ndjson"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    precedent = "0" * 64
    existantes = lire_journal(root)
    if existantes:
        precedent = existantes[-1]["empreinte"]
    corps = {**ligne, "precedente": precedent}
    corps["empreinte"] = hashlib.sha256(json.dumps(corps, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    with chemin.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(corps, sort_keys=True, ensure_ascii=False) + "\n")
    return corps["empreinte"]


def _reglage_en_vigueur(root: Path) -> dict:
    """Le réglage EFFECTIF du bac à sable, tel que le moteur le lit (déclencheur + stop + horizon)."""
    p = CO._params_trigger(root, CO.RAW_PROBE)
    cfg = CO._cfg_defaut(CO.RAW_PROBE, root)
    return {**p, "stop_bps": cfg["stop_bps"], "horizon_ms": cfg["horizon_ms"]}


def cycles_fantomes_de_la_variante(root: Path, courante: dict, *, now_ms: int, ecrire: bool,
                                   tape: dict | None = None) -> dict:
    """Simule la variante EN VIGUEUR sur les fills reçus depuis sa mise en service, et rend le registre.

    22/11/2026 : le bac à sable n'ouvre jamais sans avance mesurée (garde voulue) ; sans cycles
    fantômes, cette boucle attendait des cycles qui ne pouvaient pas exister. Voir `cycles_fantomes`.
    """
    try:
        auto = json.loads(CO._p(CO.RAW_PROBE, Path(root), "auto.json").read_text(encoding="utf-8"))
        depuis = float(auto.get("active_depuis_ms") or 0.0)
    except (OSError, ValueError, AttributeError):
        depuis = 0.0
    if tape is None:
        try:
            from hl_observer.experimental.copy_edge_forward import charger_prix_tape
            tape = charger_prix_tape(Path(root)) or {}
        except Exception:  # noqa: BLE001 - sans bande de prix, rien n'est simulé (et c'est dit)
            tape = {}
    sim = CF.simuler(CF.lire_journal(root), tape, CF.tvl_par_vault(root),
                     frac_tvl=float(courante["frac_tvl"]), stop_bps=float(courante["stop_bps"]),
                     horizon_ms=float(courante["horizon_ms"]), depuis_ms=depuis, now_ms=now_ms,
                     notional_usd=float(CO.RAW_PROBE.notional_usd), etiquette=str(courante.get("variante") or "v1"))
    ajoutes = CF.ajouter_au_registre(root, sim["cycles"]) if ecrire else 0
    registre = CF.lire_registre(root)
    if not ecrire:                                     # lecture seule : montrer aussi ce qui serait ajouté
        connus = {(c.get("identite"), c.get("trigger_version")) for c in registre}
        registre += [c for c in sim["cycles"] if (c["identite"], c["trigger_version"]) not in connus]
    return {"registre": registre, "compte": sim["compte"], "ajoutes": ajoutes, "depuis_ms": depuis,
            "bande_de_prix_coins": len(tape)}


def une_passe(root: Path, *, appliquer: bool = False, now_ms: int | None = None, tape: dict | None = None) -> dict:
    """Observe, juge, décide — bac à sable puis échelle de promotion ; écrit si `appliquer`.

    Ne lève pas pour un fichier manquant : sans aucun cycle, la passe rend « CONTINUER ». Sous le vrai
    runtime, écrire exige l'autorisation du collecteur (même règle que le moteur) ; sinon la passe est
    rendue en lecture seule, et le dit.
    """
    root = Path(root)
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    permis = bool(appliquer) and CO._ecriture_permise(root)
    refus = "ECRITURE_NON_AUTORISEE_HORS_COLLECTEUR" if appliquer and not permis else None
    # 22/11/2026 — DEUX ÉTAGES, UN DÉCIDEUR CHACUN. Le bac à sable n'ouvre jamais sans avance mesurée :
    # c'est l'apprentissage PARALLÈLE (cycles fantômes, toutes les variantes à la fois) qui choisit son
    # réglage et, s'il prouve une avance, l'arme. Les cycles RÉELS qui suivent sont jugés ici, et seuls
    # eux font monter un réglage vers PROBE puis ALPHA.
    parallele = AP.une_passe(root, ecrire=permis, now_ms=now_ms, tape=tape,
                             notional_usd=float(CO.RAW_PROBE.notional_usd))
    reels = cycles_clotures(root)
    courante = _reglage_en_vigueur(root)
    cycles = reels
    hash_courant = CO.config_hash_courant(CO.RAW_PROBE, root)
    n_courants = sum(1 for c in reels if c.get("config_hash") == hash_courant)
    verdicts = juger(bilan_par_variante(cycles))
    non_attribues = sum(1 for c in cycles if lire_etiquette(str(c.get("trigger_version") or "")) is None)
    decision = decider(n_cycles_courants=n_courants, verdicts=verdicts, fantome=mesure_fantome(root))
    journal = lire_journal(root)
    ecritures: list[dict] = []

    armement = parallele.get("decision") or {}
    if armement.get("action") == "ARMER" and permis and armement.get("variante") != courante.get("variante"):
        arme = {"variante": armement["variante"], "frac_tvl": armement["frac_tvl"], "stop_bps": armement["stop_bps"],
                "horizon_ms": armement["horizon_ms"], "floor_usd": courante["floor_usd"],
                "plafond_usd": courante["plafond_usd"], "edge_brut_bps": armement["edge_brut_bps"],
                "edge_source": "FANTOME_LCB", "active_depuis_ms": now_ms}
        _ecrire_atomique(CO._p(CO.RAW_PROBE, root, "auto.json"), arme)
        ecritures.append({"ts_ms": now_ms, "niveau": CO.RAW_PROBE.nom, "decision": armement,
                          "reglage_precedent": courante})
    # La décision séquentielle (`decision`) reste CALCULÉE et publiée pour lecture, mais elle n'écrit plus
    # le réglage du bac à sable : depuis le 22/11, c'est l'apprentissage parallèle qui le choisit.

    # ---- échelle de promotion : PROBE puis ALPHA, chacune jugée sur SES propres cycles
    reglages = {c.nom: CO._reglage_auto(c, root) for c in ECHELLE}
    pnls_promus: dict[str, list[float]] = {}
    for c in ECHELLE:
        label = reglages[c.nom].get("variante")
        pnls_promus[c.nom] = [float(x["realized_usd"]) for x in cycles_clotures(root, c)
                              if label and x.get("trigger_version") == label]
    retrogradees: dict[str, set[float]] = {}
    for ligne in journal:
        d = ligne.get("decision") or {}
        if d.get("action") == "RETROGRADER":
            retrogradees.setdefault(str(d.get("cohorte")), set()).add(float(d.get("frac_tvl")))
    echelle = decider_echelle(verdicts_bac=verdicts, reglages=reglages, pnls_promus=pnls_promus,
                              retrogradees=retrogradees)
    par_nom = {c.nom: c for c in ECHELLE}
    for action in echelle:
        if not permis:
            continue
        cohorte = par_nom[action["cohorte"]]
        if action["action"] == "PROMOUVOIR":
            numero = 1 + sum(1 for x in journal if (x.get("decision") or {}).get("action") == "PROMOUVOIR"
                             and (x.get("decision") or {}).get("cohorte") == cohorte.nom)
            _ecrire_atomique(CO._p(cohorte, root, "auto.json"),
                             {"variante": "promu-f%r-n%d" % (action["frac_tvl"], numero), "frac_tvl": action["frac_tvl"]})
        else:                                   # RETROGRADER : la cohorte retrouve ses défauts (fichier neutre, pas supprimé)
            _ecrire_atomique(CO._p(cohorte, root, "auto.json"),
                             {"retrogradee_le_ms": now_ms, "seuil_retrograde": action["frac_tvl"]})
        ecritures.append({"ts_ms": now_ms, "niveau": cohorte.nom, "decision": action})

    etat = {
        "schema": "alina.auto_amelioration.v2", "ts_ms": now_ms, "paper": True, "real_execution": False,
        "reglage_du_bac_a_sable": courante, "cycles_de_la_config_en_vigueur": n_courants,
        "echantillon": ECHANTILLON, "cycles_non_attribues": non_attribues,
        "variantes_essayees": len(verdicts), "variantes_max": VARIANTES_MAX,
        "verdicts": {etiquette(v, 0)[:-3]: x for v, x in sorted(verdicts.items())},
        "decision": decision, "echelle": echelle,
        "cohortes_promues": {nom: {"reglage": reglages[nom], "cycles": len(pnls_promus[nom])} for nom in reglages},
        "appliquee": bool(ecritures), "refus": refus,
        "cycles_reels": len(reels),
        "parallele": {k: parallele.get(k) for k in ("fills_inscrits", "fills_ce_passage", "comptes_ce_passage",
                                                     "verdict", "meilleures", "decision", "debut_ms")},
    }
    if permis:
        _ecrire_atomique(root / DOSSIER / "etat.json", etat)
        for ecriture in ecritures:
            _journaliser(root, ecriture)
        if decision["action"] == "S_ABSTENIR" and not ecritures:
            derniere_bac = next((x for x in reversed(journal) if x.get("niveau") in (None, CO.RAW_PROBE.nom)), None)
            if not derniere_bac or (derniere_bac.get("decision") or {}).get("action") != "S_ABSTENIR":
                _journaliser(root, {"ts_ms": now_ms, "niveau": CO.RAW_PROBE.nom, "decision": decision})
    return etat


__all__ = ["BASE", "DIMENSIONS", "ECHANTILLON", "ECHELLE", "GENERATIONS_MAX", "VARIANTES_MAX", "bilan_par_variante",
           "cycles_clotures", "decider", "decider_echelle", "etiquette", "intervalle", "juger", "lire_etiquette",
           "lire_journal", "mesure_fantome", "une_passe", "voisines"]
