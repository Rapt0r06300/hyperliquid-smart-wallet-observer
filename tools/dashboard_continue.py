"""DASHBOARD du labo CONTINU (Flo 26/07). Rend l'état (LIVE-RESEARCH-STATE.json) en un écran multi-zones :
en-tête, DONNÉES, RECHERCHE, PISTES INTÉRESSANTES, REJETS, FORWARD PAPER, LOGS/opportunités ratées, SYSTÈME.
Tous les compteurs viennent des VRAIS fichiers (jamais décoratifs). Rich Live si disponible ; sinon un rendu
texte/markdown portable (utilisé aussi pour LIVE-RESEARCH-DASHBOARD.md et les tests headless). 0 réseau.

Ne mélange JAMAIS discovery / validation / holdout / forward : une piste exploratoire est affichée comme
intéressante mais JAMAIS comme validée.
"""
from __future__ import annotations

import json
from pathlib import Path


def _duree(d: dict) -> str:
    u = d.get("duree", {})
    return "%dj %02dh %02dm %02ds" % (u.get("jours", 0), u.get("heures", 0), u.get("minutes", 0), u.get("secondes", 0))


def rendre_texte(etat: dict) -> str:
    t = etat.get("totaux", {})
    L = []
    L.append("=" * 70)
    L.append(" HYPERSMART — RECHERCHE CONTINUE — PAPER ONLY")
    L.append("=" * 70)
    L.append(" run_id        : %s" % etat.get("run_id"))
    L.append(" etat          : %s     cycle : %s   (termines : %s)" % (etat.get("etat"), etat.get("cycle_actuel"), etat.get("cycles_termines")))
    L.append(" demarrage     : %s" % etat.get("demarrage_iso"))
    L.append(" duree travail : %s   (%.0f s)" % (_duree(etat), etat.get("duree_totale_s", 0)))
    L.append(" tache         : %s   depuis %.1fs   | cycle depuis %.1fs" % (etat.get("phase"), etat.get("duree_tache_s", 0), etat.get("duree_cycle_s", 0)))
    L.append(" checkpoint    : %s" % etat.get("dernier_checkpoint"))
    L.append("-" * 70)
    L.append(" [DONNEES]  sources detectees/utilisees : %s / %s   events utilises : %s" % (
        t.get("sources_detectees", 0), t.get("sources_utilisees", 0), t.get("events_utilises", 0)))
    L.append(" [RECHERCHE] prereg : %s   resultats : %s   fast-screen : %s   exact : %s" % (
        t.get("preregistres", 0), t.get("resultats", 0), t.get("fast_screen", 0), t.get("exact_replays", 0)))
    L.append("            survivants : %s   forward events : %s   PASS forward : %s" % (
        t.get("survivants", 0), t.get("forward_events", 0), t.get("n_pass", 0)))
    L.append("-" * 70)
    L.append(" [PISTES INTERESSANTES]  (exploratoire/holdout SEPARES — jamais 'valide' a la legere)")
    L.append(" %-4s %-20s %-6s %-9s %-10s %s" % ("rang", "candidate_id", "coin", "horizon", "net_bps", "statut"))
    pistes = etat.get("pistes_interessantes", [])
    for i, p in enumerate(pistes[:12], 1):
        L.append(" %-4d %-20s %-6s %-9s %-10s %s" % (i, str(p.get("candidate_id"))[:20], p.get("coin"),
                                                     p.get("horizon_ms"), round(p.get("net_bps", 0), 2), p.get("statut")))
    if not pistes:
        L.append("   (aucune piste positive au holdout pour l'instant — recherche en cours)")
    L.append("-" * 70)
    L.append(" [REJETS]  total : %s" % etat.get("rejets", {}).get("total", 0))
    L.append(" [FORWARD PAPER]  events cumules : %s   (positions/PnL detaillees dans le rapport)" % t.get("forward_events", 0))
    L.append(" [SYSTEME]  paper_only=%s read_only=%s   %s" % (etat.get("paper_only"), etat.get("read_only"), etat.get("securite")))
    L.append("=" * 70)
    return "\n".join(L) + "\n"


def rendre_markdown(etat: dict) -> str:
    t = etat.get("totaux", {})
    L = ["# LIVE-RESEARCH-DASHBOARD — HYPERSMART recherche continue (paper-only)\n",
         "- run_id : `%s` · état : **%s** · cycle : %s (terminés %s)" % (etat.get("run_id"), etat.get("etat"), etat.get("cycle_actuel"), etat.get("cycles_termines")),
         "- démarrage : %s · durée : **%s**" % (etat.get("demarrage_iso"), _duree(etat)),
         "- tâche : %s · dernier checkpoint : %s\n" % (etat.get("phase"), etat.get("dernier_checkpoint")),
         "## Données", "- sources détectées/utilisées : %s / %s · events utilisés : %s\n" % (
             t.get("sources_detectees", 0), t.get("sources_utilisees", 0), t.get("events_utilises", 0)),
         "## Recherche", "- prereg %s · résultats %s · fast-screen %s · exact %s · survivants %s · forward %s · PASS %s\n" % (
             t.get("preregistres", 0), t.get("resultats", 0), t.get("fast_screen", 0), t.get("exact_replays", 0),
             t.get("survivants", 0), t.get("forward_events", 0), t.get("n_pass", 0)),
         "## Pistes intéressantes (exploratoire ≠ validé)",
         "| rang | candidate_id | coin | horizon | net bps | statut |", "|---|---|---|---:|---:|---|"]
    for i, p in enumerate(etat.get("pistes_interessantes", [])[:15], 1):
        L.append("| %d | %s | %s | %s | %s | %s |" % (i, p.get("candidate_id"), p.get("coin"),
                                                      p.get("horizon_ms"), round(p.get("net_bps", 0), 2), p.get("statut")))
    L.append("\n## Sécurité\n%s · paper_only=%s · read_only=%s\n" % (etat.get("securite"), etat.get("paper_only"), etat.get("read_only")))
    return "\n".join(L) + "\n"


def afficher_live(rundir: str | Path, *, stop_event=None, intervalle_s: float = 5.0) -> None:
    """Boucle d'affichage Rich Live si disponible (sinon impression texte). Lit LIVE-RESEARCH-STATE.json."""
    import time
    rundir = Path(rundir)
    try:
        from rich.live import Live  # type: ignore
        from rich.text import Text
        with Live(refresh_per_second=1, screen=False) as live:
            while stop_event is None or not stop_event.is_set():
                etat = _lire(rundir)
                live.update(Text(rendre_texte(etat)))
                time.sleep(intervalle_s)
    except Exception:  # noqa: BLE001 — pas de Rich -> impression texte simple
        while stop_event is None or not stop_event.is_set():
            print("\033c" + rendre_texte(_lire(rundir)), flush=True)
            time.sleep(intervalle_s)


def _lire(rundir: Path) -> dict:
    try:
        return json.loads((Path(rundir) / "LIVE-RESEARCH-STATE.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


__all__ = ["rendre_texte", "rendre_markdown", "afficher_live"]
