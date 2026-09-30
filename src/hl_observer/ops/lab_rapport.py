"""[LAB α] RAPPORT final automatique. Écrit RAPPORT_LATEST.md + une copie horodatée, un JSON complet et un
manifeste des fichiers consommés (avec hashes). Le rapport affiche : sources trouvées/utilisées, couverture et
trous, état de chaque câblage, résultats Copy-Vault/Cross-Venue/Lead-Lag, meilleures configs, PnL/ROI
IS-OOS-FORWARD, coûts complets, capacité/concentration, candidats tués + raisons, meilleur candidat réellement
démontré, et le VERDICT : POSITIF / NÉGATIF / NON MESURABLE. Aucun chiffre fabriqué : le verdict vient de la
recherche sur données réelles (synthétique exclu). Pur/écriture fichiers ; 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_VERDICT = {
    "POSITIF": "POSITIF",
    "NEGATIF": "NEGATIF",
    "NON_MESURABLE": "NON MESURABLE",
    "NON_ECONOMIQUE_SYNTHETIQUE": "NON MESURABLE (synthetique exclu du verdict)",
}


def verdict_affiche(verdict_global: Any) -> str:
    return _VERDICT.get(str(verdict_global), "NON MESURABLE")


def _section_sources(inv: dict[str, Any]) -> list[str]:
    out = ["## Sources de données", "", "| Dossier | Présent | Fichiers | Octets |", "|---|---|---|---|"]
    for d in inv.get("dossiers", []):
        out.append("| %s | %s | %s | %s |" % (d.get("dossier"), "oui" if d.get("present") else "NON",
                                              d.get("n_fichiers", "-"), d.get("octets", "-")))
    out += ["", "Fichiers consommables: %d (lisibles %d, bloqués %d), total %d octets." % (
        inv.get("total_fichiers", 0), inv.get("lisibles", 0), inv.get("bloques", 0),
        inv.get("total_octets", 0)), ""]
    return out


def _section_audit(audit: dict[str, Any]) -> list[str]:
    out = ["## État des câblages", "", "| Brique | Statut |", "|---|---|"]
    for b in audit.get("bricks", []):
        out.append("| %s | %s |" % (b.get("brique"), b.get("statut")))
    return out + [""]


def _section_recherche(rech: dict[str, Any]) -> list[str]:
    out = ["## Recherche d'alpha (chemin canonique unique)", "",
           "Évaluations: %d — cache réutilisé: %d — candidats: %d — zones prometteuses: %d." % (
               rech.get("evalues", 0), rech.get("caches", 0), rech.get("n_candidats", 0),
               rech.get("prometteuses", 0)), ""]
    meilleur = rech.get("meilleur")
    if meilleur:
        m = meilleur.get("metriques", {})
        seg = meilleur.get("segments", {})
        out += ["### Meilleur candidat démontré", "",
                "- config: `%s`" % json.dumps(meilleur.get("config", {}), sort_keys=True),
                "- verdict: **%s**" % meilleur.get("verdict"),
                "- net IS: %s — OOS: %s — FORWARD: %s" % (m.get("net_pnl"), m.get("oos_net"), m.get("forward_net")),
                "- ADVERSE_P95 net: %s — ADVERSE_P99 net: %s" % (m.get("adverse_p95_net"), m.get("adverse_p99_net")),
                "- ROI IS: %s — Profit Factor: %s — drawdown: %s" % (m.get("roi"), m.get("profit_factor"),
                                                                    m.get("drawdown")),
                "- LCB: %s — Expected Shortfall: %s — placebo net: %s" % (m.get("lcb"),
                                                                         m.get("expected_shortfall"),
                                                                         meilleur.get("placebo_net")),
                "- turnover: %s — concentration HHI: %s — capacité: %s" % (m.get("turnover"),
                                                                          m.get("concentration_hhi"),
                                                                          m.get("capacite")),
                "- fees: %s — épisodes: %s — réconcilié: %s" % (m.get("fees"), m.get("n_episodes"),
                                                               m.get("reconcilie")),
                "- fills IS: %s — missed/MORE_DATA IS: %s" % (seg.get("IS", {}).get("fills"),
                                                             seg.get("IS", {}).get("missed")), ""]
    tues = [c for c in rech.get("candidats", []) if c.get("verdict") in ("KILL", "MORE_DATA", "UNMEASURABLE")]
    if tues:
        out += ["### Candidats tués / non promus (%d)" % len(tues), ""]
        for c in tues[:15]:
            out.append("- `%s` → %s" % (json.dumps(c.get("config", {}), sort_keys=True), c.get("verdict")))
        out.append("")
    return out


# AUD-101 : hiérarchie explicite PAR NIVEAU DE PREUVE. Le rapport ne se contente plus de séparer
# "meilleur démontré" / "tués" : il classe TOUS les candidats du niveau de preuve le plus FORT au plus
# faible, selon un ordre canonique (un verdict inconnu retombe au plus bas — deny-by-default).
_ORDRE_PREUVE = (
    "VALIDATED_POSITIVE_PAPER", "OR", "ARGENT", "PROMU", "POSITIF", "VALIDE_PARTIEL",
    "MORE_DATA", "KILL", "UNMEASURABLE", "NON_ECONOMIQUE_SYNTHETIQUE",
)


def rang_preuve(verdict: Any) -> int:
    """Rang du niveau de preuve : 0 = le plus FORT. Verdict inconnu -> plus bas (fail-closed)."""
    v = str(verdict).upper()
    return _ORDRE_PREUVE.index(v) if v in _ORDRE_PREUVE else len(_ORDRE_PREUVE)


def _section_hierarchie_preuve(rech: dict[str, Any]) -> list[str]:
    cands = list(rech.get("candidats", []) or [])
    if not cands:
        return []
    groupes: dict[str, list] = {}
    for c in cands:
        groupes.setdefault(str(c.get("verdict")), []).append(c)
    out = ["## Hiérarchie par niveau de preuve", "",
           "Tous les candidats, regroupés du niveau de preuve le PLUS FORT au plus faible "
           "(VALIDATED > VALIDE_PARTIEL > MORE_DATA > KILL > UNMEASURABLE).", ""]
    for v in sorted(groupes, key=rang_preuve):
        lot = groupes[v]
        out.append("### %s (%d) — rang preuve %d" % (v, len(lot), rang_preuve(v)))
        for c in lot[:10]:
            out.append("- `%s`" % json.dumps(c.get("config", {}), sort_keys=True))
        out.append("")
    return out


def construire_markdown(*, horodatage: str, source: str, periode: Any, inv: dict[str, Any],
                        audit: dict[str, Any], rech: dict[str, Any], eta_final: Any = None) -> str:
    verdict = verdict_affiche(rech.get("verdict_global"))
    lignes = [
        "# Laboratoire de recherche d'alpha — RAPPORT", "",
        "- Horodatage: %s" % horodatage,
        "- Source des données: **%s** (synthétique exclu du verdict économique)" % source,
        "- Période analysée: %s" % (periode or "n/d"),
        "- ETA final réel: %s" % (eta_final or "n/d"),
        "", "## VERDICT ÉCONOMIQUE : **%s**" % verdict, "",
        "Règle de promotion: net>0 ET OOS>0 ET FORWARD>0 ET LCB>0 ET ADVERSE_P95>0 ET ledger réconcilié ET "
        "échantillon suffisant ET capacité mesurable — sinon KILL / MORE_DATA / UNMEASURABLE.", "",
    ]
    lignes += _section_sources(inv)
    lignes += _section_audit(audit)
    lignes += _section_recherche(rech)
    lignes += _section_hierarchie_preuve(rech)
    lignes += ["## Sécurité", "", "Paper strict : 0 ordre réel, 0 clé privée, 0 signature, aucun appel /exchange.",
               ""]
    return "\n".join(lignes)


def ecrire_rapport(sortie_dir: str | Path, *, horodatage: str, inventaire: dict[str, Any],
                   audit: dict[str, Any], recherche: dict[str, Any], eta_final: Any = None,
                   source: str = "REEL", periode: Any = None,
                   checkpoints: list[str] | None = None) -> dict[str, Any]:
    """Écrit RAPPORT_LATEST.md + copie horodatée + rapport.json + manifeste.json. Retourne les chemins + verdict."""
    d = Path(sortie_dir)
    d.mkdir(parents=True, exist_ok=True)
    manifeste = {"total_octets": inventaire.get("total_octets", 0),
                 "total_fichiers": inventaire.get("total_fichiers", 0),
                 "fichiers": [{"rel": f.get("rel"), "format": f.get("format"), "octets": f.get("octets"),
                               "hash": f.get("hash"), "lisible": f.get("lisible"), "raison": f.get("raison")}
                              for f in inventaire.get("fichiers", [])]}
    (d / "manifeste.json").write_text(json.dumps(manifeste, indent=2, ensure_ascii=False), encoding="utf-8")
    plein = {"horodatage": horodatage, "source": source, "periode": periode,
             "verdict": verdict_affiche(recherche.get("verdict_global")),
             "inventaire_resume": {k: inventaire.get(k) for k in
                                   ("total_fichiers", "total_octets", "lisibles", "bloques", "dossiers")},
             "audit": audit, "recherche": recherche, "checkpoints": checkpoints or [], "eta_final": eta_final}
    (d / "rapport.json").write_text(json.dumps(plein, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    md = construire_markdown(horodatage=horodatage, source=source, periode=periode, inv=inventaire,
                             audit=audit, rech=recherche, eta_final=eta_final)
    latest = d / "RAPPORT_LATEST.md"
    latest.write_text(md, encoding="utf-8")
    horodate = d / ("RAPPORT_%s.md" % str(horodatage).replace(":", "-").replace(" ", "_"))
    horodate.write_text(md, encoding="utf-8")
    return {"latest": str(latest), "horodate": str(horodate), "json": str(d / "rapport.json"),
            "manifeste": str(d / "manifeste.json"), "verdict": plein["verdict"]}


__all__ = ["verdict_affiche", "construire_markdown", "ecrire_rapport"]
