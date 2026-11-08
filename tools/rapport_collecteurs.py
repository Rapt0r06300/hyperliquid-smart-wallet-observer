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
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

# ERREURS GRAVES : plantages, exceptions, accès refusé, codes non nuls.
MOTIF_GRAVE = re.compile(
    r"traceback|exception|[a-z]+error\b|\berror\b|\berreur\b|critical|fatal|"
    r"rc=[1-9]|crash|killed|\bdenied\b|acces refuse|permission|introuvable|not found|"
    r"cannot|unable|segfault|assert|abandon",
    re.IGNORECASE,
)
# PETITS SIGNAUX : avertissements, limites, trous, pertes — tout ce qui mérite attention/optimisation.
MOTIF_SIGNAL = re.compile(
    r"\bwarn(ing)?\b|retry|backoff|reconnex|\bgap\b|\btrou\b|drop|perdu|backpressure|"
    r"429|too many requests|rate.?limit|throttl|timed? ?out|timeout|vide|empty|"
    r"quarant|rejected|rejet|non admis|noncausal|non causal|invalid|mismatch|incoher|"
    r"overflow|stale|perime|skip|ignore|\blent\b|slow|degrade|echec|failed|refus",
    re.IGNORECASE,
)
# Lignes a NE JAMAIS compter (bruit attendu, pas un probleme de collecteur).
MOTIF_IGNORER = re.compile(
    r"0 erreur|no error|sans erreur|errors?: 0\b|garde donnees|modifications locales protegees|"
    r"refusees si github|aucune erreur|^\s*#|skipped in",
    re.IGNORECASE,
)
# Fichiers logs a EXCLURE (operations git/push, pas des collecteurs, + ce rapport lui-meme).
FICHIERS_EXCLUS = re.compile(r"pousser|[/_]push|rapport_collecteurs", re.IGNORECASE)

#: Règles d'AMELIORATION : (motif, titre, recommandation). Déclenchées si >=1 occurrence.
REGLES_AMELIORATION: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"429|too many requests|rate.?limit|throttl", re.I),
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


def _section_logs(logs_dir: Path, now: float) -> tuple[list[str], list[str]]:
    """Retourne (sections_par_fichier, erreurs_globales)."""
    sections: list[str] = ["", "=" * 78, "LOGS DES COLLECTEURS (erreurs + fin de chaque log)", "=" * 78]
    globales: list[tuple[float, str, str]] = []
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
        trouves = []
        for l in lignes:
            if MOTIF_IGNORER.search(l):
                continue
            grave = bool(MOTIF_GRAVE.search(l))
            if grave or MOTIF_SIGNAL.search(l):
                trouves.append((l, grave))
                globales.append((st.st_mtime, p.name, l, grave))
        n_grave = sum(1 for _, g in trouves if g)
        rel = p.relative_to(logs_dir)
        sections.append("")
        sections.append(f"--- {rel}  ({st.st_size/1024:.0f} Ko, MAJ il y a {_ago(st.st_mtime, now)}, "
                        f"{n_grave} grave(s) + {len(trouves) - n_grave} signal(aux)) ---")
        if trouves:
            sections.append("  >> ERREURS & SIGNAUX (25 derniers) :")
            for l, g in trouves[-25:]:
                sections.append(f"     [{'GRAVE ' if g else 'signal'}] {l[:300]}")
        sections.append("  >> FIN DU LOG (6 dernieres lignes) :")
        for l in lignes[-6:]:
            sections.append(f"     {l[:300]}")
    return sections, globales


def _normaliser(ligne: str) -> str:
    """Enleve les chiffres/adresses pour regrouper les erreurs identiques repetees."""
    s = re.sub(r"0x[0-9a-fA-F]{4,}", "0x..", ligne)
    s = re.sub(r"\d{2,}", "N", s)
    return s.strip()[:200]


def _grouper(globales: list[tuple[float, str, str, bool]]) -> list[list]:
    """Regroupe les lignes identiques (fichier + forme) avec compteur. -> [mtime,nom,ligne,grave,cnt]."""
    groupes: dict[tuple[str, str], list] = {}
    for mtime, nom, ligne, grave in globales:
        cle = (nom, _normaliser(ligne))
        if cle not in groupes:
            groupes[cle] = [mtime, nom, ligne, grave, 1]
        else:
            groupes[cle][4] += 1
            groupes[cle][0] = max(groupes[cle][0], mtime)
            groupes[cle][3] = groupes[cle][3] or grave
    return sorted(groupes.values(), key=lambda g: -g[0])


def _formater_globales(globales: list[tuple[float, str, str, bool]]) -> list[str]:
    distinctes = _grouper(globales)
    graves = [g for g in distinctes if g[3]]
    signaux = [g for g in distinctes if not g[3]]
    out = ["", "#" * 78, f"ERREURS GRAVES ({len(graves)} distinctes) — A CORRIGER EN PRIORITE", "#" * 78]
    if not graves:
        out.append("  Aucune erreur grave. (ou collecteurs pas encore demarres)")
    for mtime, nom, ligne, _g, cnt in graves[:60]:
        out.append(f"  [{nom:<28}] {ligne[:250]}" + (f"  (x{cnt})" if cnt > 1 else ""))
    out += ["", "=" * 78, f"PETITS SIGNAUX / AVERTISSEMENTS ({len(signaux)} distincts) — a surveiller", "=" * 78]
    if not signaux:
        out.append("  Aucun signal.")
    for mtime, nom, ligne, _g, cnt in signaux[:60]:
        out.append(f"  [{nom:<28}] {ligne[:250]}" + (f"  (x{cnt})" if cnt > 1 else ""))
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


def generer(root: Path) -> Path:
    now = datetime.datetime.now().timestamp()
    data_dir = root / "runtime" / "data"
    logs_dir = root / "runtime" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    entete = [
        "#" * 78,
        "#  RAPPORT COLLECTEURS ALINA SMART FLOW — diagnostic complet",
        f"#  genere : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"#  racine : {root}",
        "#  PAPER / lecture seule. Objectif : tout voir pour tout reparer et optimiser.",
        "#" * 78,
    ]
    flux = _section_flux(data_dir, now)
    logs_sections, globales = _section_logs(logs_dir, now)
    analyse = _section_analyse(globales)
    erreurs_fmt = _formater_globales(globales)
    sante = _section_sante(data_dir)
    # Ordre : AMELIORATIONS d'abord (actionnable), puis erreurs, flux, sante, detail par log.
    corps = entete + analyse + erreurs_fmt + flux + sante + logs_sections
    cible = logs_dir / "rapport_collecteurs.log"
    cible.write_text("\n".join(corps) + "\n", encoding="utf-8")
    return cible


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rapport detaille de tous les collecteurs (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    args = p.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    cible = generer(Path(args.root))
    # resume console : nombre d'erreurs globales
    contenu = cible.read_text(encoding="utf-8", errors="replace")
    n_err = contenu.count("\n  [")  # lignes d'erreurs globales
    print(f"[rapport] genere : {cible}", flush=True)
    print(f"[rapport] ~{n_err} erreur(s)/avertissement(s) recense(s). Ouvre le fichier pour tout voir.",
          flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
