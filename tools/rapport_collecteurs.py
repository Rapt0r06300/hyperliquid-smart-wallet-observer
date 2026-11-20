#!/usr/bin/env python3
"""Rapport ULTRA-DETAILLE de TOUS les collecteurs -> un seul .log pour tout diagnostiquer.

Agrege, dans ``runtime/logs/rapport_collecteurs.log`` :
- l'etat de chaque flux de ``runtime/data`` (volume, fraicheur) ;
- les erreurs/avertissements extraits de TOUS les logs (superviseur, poll, explorer, coffre,
  watchdog, et tout autre *.log / *.jsonl de runtime/logs) ;
- les JSON de sante (``collecteurs_sante.json``, ``*_sante_*.json``) ;
- un recapitulatif global des erreurs les plus recentes, fichier par fichier.

Lecture seule. A lancer a la demande (``python tools/rapport_collecteurs.py``) ou appele par
le lanceur. Objectif : tout voir pour tout reparer et optimiser.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

# ERREURS GRAVES : plantages, exceptions, accès refusé, codes non nuls.
MOTIF_GRAVE = re.compile(
    r"traceback|exception|[a-z]+error\b|\berror\b|\berreur\b|critical|fatal|"
    r"rc=[1-9]|crash|killed|\bdenied\b|acces refuse|permission|introuvable|not found|"
    r'\bno_go\b|status="(failure|error|ko)"|\[failure\]|\bfailure ?: |'
    r"cannot|unable|segfault|assert|abandon",
    re.IGNORECASE,
)
# PETITS SIGNAUX : avertissements, limites, trous, pertes — tout ce qui mérite attention/optimisation.
MOTIF_SIGNAL = re.compile(
    r"\bwarn(ing)?\b|retry|backoff|reconnex|\bgap\b|\btrou\b|drop|perdu|backpressure|"
    r"(?:http|status|statut|code|erreur|error)[^0-9]{0,12}429\b|\b429[^0-9]{0,14}(?:too many|rate.?limit|requests?|refus)|too many requests|rate.?limit|throttl|timed? ?out|timeout|vide|empty|"
    r"quarant|rejected|rejet|non admis|noncausal|non causal|invalid|mismatch|incoher|"
    r"overflow|stale|perime|skip|ignore|\blent\b|slow|degrade|echec|failed|refus",
    re.IGNORECASE,
)
# Lignes a NE JAMAIS compter (bruit attendu, pas un probleme de collecteur).
MOTIF_IGNORER = re.compile(
    r"0 erreur|no error|sans erreur|errors?: 0\b|garde donnees|modifications locales protegees|"
    r'status="SUCCESS"|status="OK"|'
    r"refusees si github|aucune erreur|^\s*#|skipped in|"
    # 16/11/2026 — LES COMPTEURS A ZERO SONT DE LA BONNE SANTE, PAS DES AVERTISSEMENTS.
    # Mesure : 458 « petits signaux » dont la majorite etaient des lignes de progression
    # SAINES — « [contexte] vivant : 740 positions, ... 0 reconnexions » (attrapee par
    # « reconnex »), « 188 ecrits pour 94 leaders (echecs 0) » (par « echec »), « 0 refus
    # encaisse(s) » (par « refus »). Compter les bonnes nouvelles comme des alertes fait
    # exactement le meme mal que crier au loup : plus personne ne lit la liste.
    r"\b0 (reconnexions?|echecs?|refus|trous?|gaps?|pertes?|rejets?|doublons?)\b|"
    r"(reconnexions?|echecs?|refus|trous?|gaps?|pertes?|rejets?|doublons?)\s*:?\s*0\b",
    re.IGNORECASE,
)
# Fichiers logs a EXCLURE (operations git/push, pas des collecteurs, + ce rapport lui-meme).
FICHIERS_EXCLUS = re.compile(r"pousser|[/_]push|rapport_collecteurs", re.IGNORECASE)
#: BENIN PAR NATURE sur un flux WebSocket public : une reconnexion n'est PAS une panne.
#: 16/11/2026, mesure sur le rapport reel : 136 `ConnectionResetError` de native-venues et une
#: trentaine de `ResourceWarning` etaient listees en tete de « ERREURS GRAVES — A CORRIGER EN
#: PRIORITE », pendant que ce collecteur ecrivait 2,78 M de lignes avec un battement de 26 s.
#: `MOTIF_GRAVE` les attrapait par « traceback » (dans le texte du ResourceWarning) et par
#: « [a-z]+error » (dans ConnectionResetError). Ce bruit est exactement ce qui fait rater une
#: vraie panne : 163 lignes critiques sur une campagne saine, et plus personne ne les lit.
MOTIF_ROUTINE = re.compile(
    r"resourcewarning|enable tracemalloc|connectionreseterror|connection reset|"
    r"keepalive ping timeout|no close frame received|1011 \(internal error\)|"
    r"connectionclosed(error|ok)?|reconnexion \(connection|"
    r"deconnexion.{0,80}reconnexion",
    re.IGNORECASE,
)
#: Au-dela, une routine cesse d'en etre une : une tempete de reconnexions est un symptome.
SEUIL_ROUTINE = 200
#: Les journaux plus vieux que ca ne sont pas des problemes DU JOUR. Un journal du 12/11 remontait
#: dans le rapport du 16/11, en tete des priorites — quatre jours apres la fin de son run.
FENETRE_H_DEFAUT = 24.0


HORODATAGE_LIGNE = re.compile(
    r"timestamp_local=\"(\d{2})/(\d{2})/(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})"
)


def horodatage_de_la_ligne(ligne: str) -> float | None:
    """L'instant porte PAR la ligne, ou ``None``. Sert aux journaux cumulatifs.

    16/11/2026 — `ALL_LAUNCHERS.log` est append-only : son mtime est de ce matin, son contenu
    remonte au 12/11. Une fenetre par FICHIER laissait donc passer sept lignes du 12/11 en
    « A CORRIGER EN PRIORITE ». Les lignes de lanceur portent `timestamp_local="JJ/MM/AAAA ..."`.
    """
    m = HORODATAGE_LIGNE.search(ligne)
    if not m:
        return None
    j, mo, a, h, mi, sec = (int(x) for x in m.groups())
    try:
        return datetime.datetime(a, mo, j, h, mi, sec).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def classer(ligne: str) -> str | None:
    """``"GRAVE"`` / ``"signal"`` / ``"routine"`` / ``None`` (non compte). Pur : c'est le tri.

    L'ordre compte : ROUTINE passe AVANT grave, c'est une de-escalade voulue.
    """
    if MOTIF_IGNORER.search(ligne):
        return None
    if MOTIF_ROUTINE.search(ligne):
        return "routine"
    if MOTIF_GRAVE.search(ligne):
        return "GRAVE"
    if MOTIF_SIGNAL.search(ligne):
        return "signal"
    return None

#: Règles d'AMELIORATION : (motif, titre, recommandation). Déclenchées si >=1 occurrence.
REGLES_AMELIORATION: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"(?:http|status|statut|code|erreur|error)[^0-9]{0,12}429\b|\b429[^0-9]{0,14}(?:too many|rate.?limit|requests?|refus)|too many requests|rate.?limit|throttl", re.I),
     "Rate-limit REST (429 / throttling)",
     "Reduire le debit du poll (max_req_min plus bas), etaler les leaders sur PLUS de lanes/IP, "
     "ou augmenter l'intervalle. Gain : moins de pertes, couverture stable."),
    (re.compile(r"permissionerror|winerror ?5|acces refuse|access denied", re.I),
     "Conflit de fichier (lease/.tmp — acces refuse)",
     "Un 2e process ou l'antivirus verrouille le fichier. Garantir UNE seule instance (verrou), "
     "exclure runtime/data de l'antivirus, et fiabiliser l'ecriture atomique (retry sur rename)."),
    (re.compile(r"reconnex", re.I),
     "Reconnexions WebSocket frequentes",
     "Augmenter ping_interval, backoff adaptatif, verifier le cap de subscriptions (<=1000) et la "
     "repartition des users par connexion (<=5). Gain : moins de trous."),
    (re.compile(r"\bgap\b|\btrou\b|high.?water", re.I),
     "Trous de donnees (gaps)",
     "Renforcer le gap-fill REST au reconnect borne par le high-water par user. Gain : jours scoreables."),
    (re.compile(r"drop|perdu|backpressure", re.I),
     "Pertes en file (backpressure)",
     "Augmenter la file bornee / le nombre de workers, ou le debit d'ecriture (batch). Gain : zero perte."),
    (re.compile(r"invalid or noncausal|non ?causal|non admis|rejected|rejet", re.I),
     "Trames rejetees au replay (L2 non causal)",
     "Capturer un carnet FRAIS a l'instant du fill (<=60s), activer le repli BBO et le carry-forward borne. "
     "Gain direct : beaucoup plus de jours appariables pour le labo."),
    (re.compile(r"snapshot family flag mismatch|is_?snapshot", re.I),
     "Incoherence du flag snapshot",
     "Aligner isSnapshot/is_snapshot a la source et dans la normalisation. Gain : moins de quarantaine."),
    (re.compile(r"quarant", re.I),
     "Donnees mises en quarantaine",
     "Inspecter runtime/coffre_certifie/quarantine : corriger le format a la SOURCE pour certifier davantage."),
    (re.compile(r"fetch vide|vide/ko|empty|reponse vide", re.I),
     "Reponses vides (fetch KO)",
     "Transitoire si rare. Si frequent : verifier l'endpoint/les coins suivis et le backoff."),
    (re.compile(r"backoff", re.I),
     "Backoffs repetes",
     "Symptome d'echecs recurrents (429/reseau) : traiter la cause pour ne pas perdre de couverture."),
    (re.compile(r"timeout|timed? ?out", re.I),
     "Timeouts",
     "Augmenter legerement les delais, verifier la latence reseau, et confirmer que la source repond."),
]


def _ago(ts: float, now: float) -> str:
    d = max(0, int(now - ts))
    if d < 60:
        return f"{d}s"
    if d < 3600:
        return f"{d // 60}m{d % 60:02d}s"
    if d < 86400:
        return f"{d // 3600}h{(d % 3600) // 60:02d}m"
    return f"{d // 86400}j{(d % 86400) // 3600:02d}h"


def _lignes(path: Path, max_lignes: int = 4000) -> list[str]:
    """Derniere portion d'un fichier texte (robuste encodage)."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            lignes = fh.readlines()
    except OSError:
        return []
    return [l.rstrip("\n") for l in lignes[-max_lignes:]]


def _section_flux(data_dir: Path, now: float) -> list[str]:
    out = ["=" * 78, "FLUX DE DONNEES (runtime/data)", "=" * 78]
    fichiers = sorted(data_dir.glob("*.jsonl"))
    if not fichiers:
        out.append("  (aucun flux .jsonl — session fraiche ou collecteurs pas encore demarres)")
        return out
    total = 0
    for p in fichiers:
        try:
            st = p.stat()
        except OSError:
            continue
        # comptage de lignes (borne pour les tres gros fichiers)
        n = 0
        try:
            with p.open("rb") as fh:
                for _ in fh:
                    n += 1
        except OSError:
            n = -1
        total += max(0, n)
        mo = st.st_size / 1048576
        out.append(f"  {p.name:<38} {n:>10} lignes  {mo:>8.1f} Mo  MAJ il y a {_ago(st.st_mtime, now)}")
    out.append("-" * 78)
    out.append(f"  TOTAL : {total} enregistrements sur {len(fichiers)} flux")
    return out


def _section_logs(logs_dir: Path, now: float, *, fenetre_h: float = FENETRE_H_DEFAUT,
                  ) -> tuple[list[str], list[tuple[float, str, str, str]]]:
    """``(sections_par_fichier, lignes_globales)``, les globales LIMITEES a la fenetre de temps.

    Un journal plus vieux que la fenetre est resume dans une section ARCHIVES et ne remonte pas
    dans les priorites du jour : il raconte un run termine, pas l'etat present.
    """
    sections: list[str] = ["", "=" * 78, "LOGS DES COLLECTEURS (erreurs + fin de chaque log)", "=" * 78]
    globales: list[tuple[float, str, str, str]] = []
    archives: list[str] = []
    limite = now - max(0.0, float(fenetre_h)) * 3600.0
    fichiers = sorted([p for p in logs_dir.rglob("*") if p.is_file()
                       and p.suffix in (".log", ".jsonl", ".txt")
                       and not FICHIERS_EXCLUS.search(p.name)],
                      key=lambda p: -p.stat().st_mtime if p.exists() else 0)
    if not fichiers:
        sections.append("  (aucun log pour l'instant)")
        return sections, []
    for p in fichiers:
        try:
            st = p.stat()
        except OSError:
            continue
        lignes = _lignes(p)
        rel = p.relative_to(logs_dir)
        compte = {"GRAVE": 0, "signal": 0, "routine": 0}
        trouves: list[tuple[str, str]] = []
        for l in lignes:
            classe = classer(l)
            if classe is None:
                continue
            propre = horodatage_de_la_ligne(l)
            if propre is not None and propre < limite:
                continue                 # journal cumulatif : la LIGNE est hors fenetre
            compte[classe] += 1
            trouves.append((l, classe))
        hors_fenetre = st.st_mtime < limite
        if hors_fenetre:
            archives.append(f"  {str(rel):<52} MAJ il y a {_ago(st.st_mtime, now)} | "
                            f"{compte['GRAVE']} grave(s), {compte['signal']} signal(aux), "
                            f"{compte['routine']} routine(s)")
            continue
        for l, classe in trouves:
            globales.append((st.st_mtime, p.name, l, classe))
        sections.append("")
        sections.append(f"--- {rel}  ({st.st_size/1024:.0f} Ko, MAJ il y a {_ago(st.st_mtime, now)}, "
                        f"{compte['GRAVE']} grave(s) + {compte['signal']} signal(aux) + "
                        f"{compte['routine']} routine(s)) ---")
        if compte["routine"] > SEUIL_ROUTINE:
            sections.append(f"  >> {compte['routine']} lignes de ROUTINE : au-dela de "
                            f"{SEUIL_ROUTINE}, une reconnexion n'est plus de la routine. A regarder.")
        if trouves:
            sections.append("  >> ERREURS & SIGNAUX (25 derniers) :")
            for l, classe in trouves[-25:]:
                etiquette = {"GRAVE": "GRAVE  ", "signal": "signal ", "routine": "routine"}[classe]
                sections.append(f"     [{etiquette}] {l[:300]}")
        sections.append("  >> FIN DU LOG (6 dernieres lignes) :")
        for l in lignes[-6:]:
            sections.append(f"     {l[:300]}")
    if archives:
        sections += ["", "=" * 78,
                     f"ARCHIVES — journaux plus vieux que {fenetre_h:.0f} h "
                     "(PAS comptes dans les priorites du jour)", "=" * 78] + archives
    return sections, globales


def _normaliser(ligne: str) -> str:
    """Enleve les chiffres/adresses pour regrouper les erreurs identiques repetees."""
    s = re.sub(r"0x[0-9a-fA-F]{4,}", "0x..", ligne)
    s = re.sub(r"\d{2,}", "N", s)
    return s.strip()[:200]


def _grouper(globales: list[tuple[float, str, str, str]]) -> list[list]:
    """Regroupe les lignes identiques (fichier + forme). -> ``[mtime, nom, ligne, classe, cnt]``."""
    ordre = {"GRAVE": 2, "signal": 1, "routine": 0}
    groupes: dict[tuple[str, str], list] = {}
    for mtime, nom, ligne, classe in globales:
        cle = (nom, _normaliser(ligne))
        if cle not in groupes:
            groupes[cle] = [mtime, nom, ligne, classe, 1]
        else:
            groupes[cle][4] += 1
            groupes[cle][0] = max(groupes[cle][0], mtime)
            if ordre.get(classe, 0) > ordre.get(groupes[cle][3], 0):
                groupes[cle][3] = classe          # la pire classe vue gagne
    return sorted(groupes.values(), key=lambda g: -g[0])


def _formater_globales(globales: list[tuple[float, str, str, str]]) -> list[str]:
    distinctes = _grouper(globales)
    graves = [g for g in distinctes if g[3] == "GRAVE"]
    signaux = [g for g in distinctes if g[3] == "signal"]
    routines = [g for g in distinctes if g[3] == "routine"]
    out = ["", "#" * 78,
       f"ERREURS GRAVES ({len(graves)} formes, {sum(g[4] for g in graves)} lignes) — A CORRIGER EN PRIORITE",
       "#" * 78]
    if not graves:
        out.append("  Aucune erreur grave. (ou collecteurs pas encore demarres)")
    for _mtime, nom, ligne, _c, cnt in graves[:60]:
        out.append(f"  [{nom:<28}] {ligne[:250]}" + (f"  (x{cnt})" if cnt > 1 else ""))
    out += ["", "=" * 78,
        f"PETITS SIGNAUX / AVERTISSEMENTS ({len(signaux)} formes, {sum(g[4] for g in signaux)} lignes) — a surveiller",
        "=" * 78]
    if not signaux:
        out.append("  Aucun signal.")
    for _mtime, nom, ligne, _c, cnt in signaux[:60]:
        out.append(f"  [{nom:<28}] {ligne[:250]}" + (f"  (x{cnt})" if cnt > 1 else ""))
    total_routine = sum(g[4] for g in routines)
    out += ["", "-" * 78,
            f"ROUTINE DES FLUX PUBLICS ({len(routines)} formes, {total_routine} lignes) — ATTENDU",
            "-" * 78,
            "  Reconnexions WebSocket et avertissements de ressources. Ce n'est une panne que si",
            f"  le volume explose (seuil par journal : {SEUIL_ROUTINE}).",
            "-" * 78]
    for _mtime, nom, ligne, _c, cnt in routines[:15]:
        out.append(f"  [{nom:<28}] {ligne[:200]}" + (f"  (x{cnt})" if cnt > 1 else ""))
    return out


def _section_analyse(globales: list[tuple[float, str, str, bool]]) -> list[str]:
    """Analyse les signaux et propose des AMELIORATIONS concretes, priorisees par frequence."""
    out = ["", "#" * 78, "AMELIORATIONS DETECTEES (optimisations concretes, les plus frequentes d'abord)",
           "#" * 78]
    lignes = [g[2] for g in globales]
    declenchees: list[tuple[int, str, str]] = []
    for motif, titre, reco in REGLES_AMELIORATION:
        n = sum(1 for l in lignes if motif.search(l))
        if n:
            declenchees.append((n, titre, reco))
    if not declenchees:
        out.append("  Rien a optimiser dans les logs actuels. (ou collecteurs pas encore demarres)")
        return out
    declenchees.sort(key=lambda t: -t[0])
    for i, (n, titre, reco) in enumerate(declenchees, 1):
        out.append("")
        out.append(f"  {i}. {titre}  —  {n} occurrence(s)")
        out.append(f"     -> {reco}")
    return out


def _collecteurs_declares() -> set[str] | None:
    """Les noms du registre, ou ``None`` si on ne peut pas les lire (on ne juge alors personne)."""
    try:
        sys.path.insert(0, str(RACINE / "src"))
        from hl_observer.ops import collecteur_registry as CR
        noms = {str(c["nom"]) for c in CR.REGISTRE}
        noms |= {str(c["nom"]) for c in getattr(CR, "COLLECTEURS_CAMPAGNE", ())}
        return noms
    except Exception:                       # noqa: BLE001 — un rapport ne doit jamais planter
        return None


def _section_battements(root: Path, now: float, *, seuil_s: float = 180.0) -> list[str]:
    """Les battements, juges UNIQUEMENT pour les collecteurs DECLARES au registre.

    16/11/2026 — `heartbeats/lab-ctx.json` dormait depuis 112 jours : ce n'est pas un collecteur
    mort, c'est le fichier laisse par un collecteur d'un AUTRE lanceur (LANCER-RECHERCHE-14H), dont
    le role est tenu ici par `contexte-leaders`. Tout controle qui balaie le dossier le compte comme
    une panne et porte donc un faux positif permanent. On juge la liste DECLAREE, et on range les
    autres a part au lieu de les faire passer pour morts.
    """
    out = ["", "=" * 78, "BATTEMENTS (collecteurs DECLARES au registre)", "=" * 78]
    dossier = root / "runtime" / "research_lab" / "heartbeats"
    if not dossier.is_dir():
        out.append("  (aucun dossier de battements)")
        return out
    declares = _collecteurs_declares()
    vus: dict[str, float] = {}
    details: dict[str, str] = {}
    for f in sorted(dossier.glob("*.json")):
        try:
            o = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            vus[f.stem] = -1.0
            details[f.stem] = "illisible"
            continue
        ts = o.get("ts_ms") or o.get("ts_wall_ms") or 0
        if not ts:
            vus[f.stem] = -1.0
            details[f.stem] = "sans horodatage"
            continue
        vus[f.stem] = max(0.0, (time.time() * 1000.0 - float(ts)) / 1000.0)
        details[f.stem] = f"ecrites {o.get('n_ecrites_cumul', o.get('messages', '?'))}"
    if declares is None:
        out.append("  registre illisible : aucun verdict rendu (on ne declare pas mort ce qu'on "
                   "ne sait pas lire).")
        hors = sorted(vus)
    else:
        hors = sorted(n for n in vus if n not in declares)
        juges = sorted(n for n in vus if n in declares)
        if not juges:
            out.append("  aucun battement pour un collecteur declare.")
        for nom in juges:
            age = vus[nom]
            etat = "ILLISIBLE" if age < 0 else ("VIVANT" if age < seuil_s else "FIGE")
            out.append(f"  {nom:<26} {etat:<9} il y a {age:>8.0f} s | {details[nom]}")
    if hors:
        out += ["", "  HORS REGISTRE — fichiers laisses par d'autres lanceurs, PAS des pannes :"]
        for nom in hors:
            age = vus[nom]
            quand = "age inconnu" if age < 0 else f"il y a {age / 86400.0:.1f} j"
            out.append(f"     {nom:<23} {quand} (ignore)")
    return out


def _section_sante(data_dir: Path) -> list[str]:
    out = ["", "=" * 78, "SANTE (JSON)", "=" * 78]
    trouves = sorted(list(data_dir.glob("*sante*.json")) + list(data_dir.glob("*_sante_*.json")))
    if not trouves:
        out.append("  (aucun JSON de sante)")
        return out
    for p in trouves:
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        out.append(f"  {p.name} :")
        if isinstance(d, dict):
            for k, v in list(d.items())[:25]:
                if isinstance(v, (dict, list)):
                    out.append(f"     {k}: {json.dumps(v, ensure_ascii=False)[:200]}")
                else:
                    out.append(f"     {k}: {v}")
    return out


def generer(root: Path, *, fenetre_h: float = FENETRE_H_DEFAUT) -> Path:
    # 20/11/2026 : cet instant sert a mesurer l AGE des journaux (fenetre de N heures).
    # Un instant sans fuseau est naif, donc lu en heure LOCALE : pendant un changement
    # d heure, l age pouvait sauter d UNE HEURE et sortir des journaux de la fenetre.
    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    data_dir = root / "runtime" / "data"
    logs_dir = root / "runtime" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    entete = [
        "#" * 78,
        "#  RAPPORT COLLECTEURS ALINA SMART FLOW — diagnostic complet",
        f"#  genere : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"#  racine : {root}",
        f"#  fenetre : {fenetre_h:.0f} h — les journaux plus vieux sont en ARCHIVES, pas en priorite.",
        "#  PAPER / lecture seule. Objectif : tout voir pour tout reparer et optimiser.",
        "#" * 78,
    ]
    flux = _section_flux(data_dir, now)
    logs_sections, globales = _section_logs(logs_dir, now, fenetre_h=fenetre_h)
    analyse = _section_analyse(globales)
    erreurs_fmt = _formater_globales(globales)
    battements = _section_battements(root, now)
    sante = _section_sante(data_dir)
    # Ordre : AMELIORATIONS d'abord (actionnable), puis erreurs, battements, flux, sante, detail.
    corps = (entete + analyse + erreurs_fmt + battements + flux + sante + logs_sections)
    cible = logs_dir / "rapport_collecteurs.log"
    cible.write_text("\n".join(corps) + "\n", encoding="utf-8")
    return cible


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rapport detaille de tous les collecteurs (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--depuis-h", type=float, default=FENETRE_H_DEFAUT,
                   help="fenetre de temps des journaux comptes dans les priorites (defaut 24 h)")
    args = p.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    cible = generer(Path(args.root), fenetre_h=args.depuis_h)
    # Resume console HONNETE : l'ancien comptait toutes les lignes commencant par « [ », donc la
    # routine et les archives avec. Ici on lit les compteurs que le rapport a vraiment ecrits.
    contenu = cible.read_text(encoding="utf-8", errors="replace")
    def _compte(prefixe: str) -> str:
        for l in contenu.splitlines():
            if l.startswith(prefixe):
                return l.strip()
        return f"{prefixe}?"
    print(f"[rapport] genere : {cible}", flush=True)
    print(f"[rapport] {_compte('ERREURS GRAVES')}", flush=True)
    print(f"[rapport] {_compte('PETITS SIGNAUX')}", flush=True)
    print(f"[rapport] {_compte('ROUTINE DES FLUX PUBLICS')}", flush=True)
    print(f"[rapport] fenetre {args.depuis_h:.0f} h — le reste est en ARCHIVES.", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
