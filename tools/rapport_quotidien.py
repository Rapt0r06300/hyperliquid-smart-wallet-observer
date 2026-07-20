"""RAPPORT QUOTIDIEN (R6) — la vérité du bot en UNE page, chaque matin.

POURQUOI (20/07, demande de Flo : « un bot quant de professionnel »)
--------------------------------------------------------------------
Un professionnel ne lit pas six fichiers JSON au réveil. Il lit une page qui répond à
cinq questions, dans cet ordre : ai-je perdu de l'argent, pourquoi, qu'est-ce qui est
ouvert, tout tourne-t-il, et où en sont les mesures en cours. Ce module écrit cette page
depuis les MÊMES sources que l'audit (ledger, positions, journaux) — jamais de chiffre
qui ne se remonte pas à un fichier.

RÈGLES
------
* Le PnL vient du LEDGER, ligne par ligne — pas d'un compteur.
* Une section sans données le DIT (« aucune donnée ») au lieu de disparaître.
* Jamais d'exception : un rapport qui plante au mauvais moment est un rapport qu'on
  n'a pas quand on en a besoin.
* Aucune promesse, aucun conseil. Des faits datés.

Sortie : `rapports/RAPPORT_DU_JOUR.md` + copie datée dans `rapports/archive_quotidienne/`.
Lecture seule. 0 ordre réel.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

FENETRE_H = 24.0


def _lignes_jsonl(chemin: Path) -> list[dict]:
    try:
        out = []
        for l in chemin.read_text(encoding="utf-8", errors="ignore").splitlines():
            l = l.strip()
            if not l:
                continue
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if isinstance(r, dict):
                out.append(r)
        return out
    except OSError:
        return []


def _json(chemin: Path) -> dict:
    try:
        d = json.loads(chemin.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _sec_pnl(root: Path, depuis_ms: int) -> list[str]:
    evs = _lignes_jsonl(root / "runtime" / "data" / "carry_paper_ledger.jsonl")
    closes = [e for e in evs if e.get("kind") == "CLOSE"]
    recents = [e for e in closes if int(e.get("ts_ms") or 0) >= depuis_ms]
    total_histo = sum(float(e.get("realized_net_pnl_usdc") or 0.0) for e in closes)
    out = ["## 1. PnL réalisé (dernières 24 h)", ""]
    if not recents:
        out.append("Aucune fermeture sur la fenêtre — rien réalisé, rien perdu.")
    else:
        par_motif: dict[str, list[float]] = {}
        for e in recents:
            par_motif.setdefault(str(e.get("reason")), []).append(
                float(e.get("realized_net_pnl_usdc") or 0.0))
        tot24 = 0.0
        for motif, vals in sorted(par_motif.items(), key=lambda kv: sum(kv[1])):
            tot24 += sum(vals)
            out.append("- `%s` : **%+.4f $** (×%d)" % (motif, sum(vals), len(vals)))
        out.append("")
        out.append("**Total 24 h : %+.4f $** · %d fermeture(s)" % (tot24, len(recents)))
    out.append("")
    out.append("Total historique (toutes époques, jamais maquillé) : **%+.4f $** "
               "sur %d fermetures." % (total_histo, len(closes)))
    return out


def _sec_positions(root: Path, now_ms: int) -> list[str]:
    d = _json(root / "runtime" / "data" / "carry_paper_positions.json")
    ouvertes = d.get("ouvertes") or {}
    out = ["## 2. Positions ouvertes (paper)", ""]
    if not ouvertes:
        out.append("Aucune position ouverte.")
        return out
    for coin, p in sorted(ouvertes.items()):
        if not isinstance(p, dict):
            continue
        age_h = (now_ms - int(p.get("entry_ts_ms") or now_ms)) / 3.6e6
        out.append("- **%s** : %.0f $ à %sx · âge %.1f h · funding accru %+.4f $"
                   % (coin, float(p.get("notional_usdt") or 0.0), p.get("levier"),
                      age_h, float(p.get("funding_accrued_usdt") or 0.0)))
    return out


def _sec_sante(root: Path) -> list[str]:
    out = ["## 3. Santé du système", ""]
    try:
        from hl_observer.ops.superviseur_collecteurs import etat_collecteurs
        morts = []
        for e in etat_collecteurs(root):
            if e["mort"]:
                morts.append("%s (silence %s min)" % (e["nom"], e["age_minutes"]))
        out.append("- Collecteurs : " + ("**%d MUET(S)** — %s" % (len(morts), ", ".join(morts))
                                         if morts else "4/4 vivants."))
    except Exception as exc:  # noqa: BLE001
        out.append("- Collecteurs : état illisible (%s)" % exc)
    sup = _json(root / "runtime" / "data" / "superviseur_collecteurs.json")
    relances = {k: v.get("relances_total") for k, v in sup.items()
                if isinstance(v, dict) and v.get("relances_total")}
    out.append("- Superviseur : " + ("relances cumulées %s" % relances if relances
                                     else "aucune relance nécessaire."))
    return out


def _sec_mesures(root: Path) -> list[str]:
    out = ["## 4. Mesures en cours", ""]
    ts = [float(r.get("ts") or 0.0)
          for r in _lignes_jsonl(root / "runtime" / "data" / "dispersion_venues.jsonl")]
    if len(ts) > 1:
        heures = (max(ts) - min(ts)) / 3600.0
        out.append("- Cross-venue : **%.1f h / 72 h** (%d observations) — verdict aux barres "
                   "pré-écrites, jamais avant." % (heures, len(ts)))
    else:
        out.append("- Cross-venue : aucune donnée encore.")
    return out


def _sec_refus(root: Path, depuis_ms: int) -> list[str]:
    evs = _lignes_jsonl(root / "runtime" / "data" / "carry_hype_paper_decisions.jsonl")
    recents = [e for e in evs if int(e.get("ts_ms") or 0) >= depuis_ms]
    motifs = Counter(str((e.get("decision") or {}).get("motif"))
                     for e in recents if not (e.get("decision") or {}).get("viable"))
    out = ["## 5. Refus dominants (24 h) — le bot explique pourquoi il n'ouvre pas", ""]
    if not motifs:
        out.append("Aucun refus sur la fenêtre (ou aucune décision).")
        return out
    for motif, n in motifs.most_common(5):
        out.append("- ×%d `%s`" % (n, motif))
    return out


def generer(root: str | Path = RACINE, *, now_ms: int | None = None) -> str:
    """Le rapport complet en Markdown. Ne lève JAMAIS (un rapport absent = un matin aveugle)."""
    try:
        racine = Path(root)
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        depuis = now - int(FENETRE_H * 3600 * 1000)
        quand = dt.datetime.fromtimestamp(now / 1000).strftime("%d/%m/%Y %H:%M")
        parts: list[str] = [
            "# Rapport quotidien HyperSmart — %s" % quand,
            "",
            "_Chaque chiffre se remonte à un fichier (ledger, positions, journaux). "
            "Fenêtre : dernières %.0f h._" % FENETRE_H,
            "",
        ]
        for sec in (_sec_pnl(racine, depuis), _sec_positions(racine, now),
                    _sec_sante(racine), _sec_mesures(racine), _sec_refus(racine, depuis)):
            parts += sec + [""]
        parts.append("---")
        parts.append("**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · "
                     "0 signature · 0 dépôt/retrait.**")
        return "\n".join(parts)
    except Exception as exc:  # noqa: BLE001 — le rapport dit sa propre panne plutôt que planter
        return ("# Rapport quotidien — ERREUR DE GÉNÉRATION\n\n"
                "Le générateur a échoué : `%s`.\n"
                "Un rapport qui plante est un matin aveugle — signale-le.\n" % exc)


def ecrire(root: str | Path = RACINE, *, now_ms: int | None = None) -> Path:
    racine = Path(root)
    texte = generer(racine, now_ms=now_ms)
    dossier = racine / "rapports"
    dossier.mkdir(parents=True, exist_ok=True)
    principal = dossier / "RAPPORT_DU_JOUR.md"
    principal.write_text(texte, encoding="utf-8")
    archive = dossier / "archive_quotidienne"
    archive.mkdir(parents=True, exist_ok=True)
    jour = dt.datetime.fromtimestamp(
        (now_ms or time.time() * 1000) / 1000).strftime("%Y-%m-%d")
    (archive / ("RAPPORT_%s.md" % jour)).write_text(texte, encoding="utf-8")
    return principal


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rapport quotidien (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    a = p.parse_args(argv)
    chemin = ecrire(a.root)
    print("Rapport ecrit : %s" % chemin)
    print()
    print(chemin.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
