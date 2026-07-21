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
    # L'USINE À DONNÉES (20/07, argument de Flo : « un replay A/B se fait sur des données »).
    # Le replay mange candidats + marks : leur production doit être un chiffre QUOTIDIEN —
    # une usine qui s'arrête en silence, c'est le faux « 1 sur 1M » qui revient.
    try:
        seuil = time.time() - FENETRE_H * 3600
        cand = marks = 0
        for f in (root / "runtime" / "replay").glob("*.jsonl"):
            for r in _lignes_jsonl(f):
                t = r.get("recorded_at") or r.get("ts") or r.get("_ts") or 0
                if isinstance(t, (int, float)) and (t / 1000 if t > 1e12 else t) >= seuil:
                    if "strategie" in r or "accepte" in r:
                        cand += 1
                    else:
                        marks += 1
        out.append("- Usine à données replay (24 h) : **%d candidats** · **%d marks** — "
                   "c'est le carburant du replay A/B." % (cand, marks))
    except OSError:
        out.append("- Usine à données replay : illisible ce matin.")
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


#: #186 — le PnL des refus se recalcule au plus une fois par SEMAINE (coûteux : il rejoue
#: les candidats refusés sur les marks) ; entre deux calculs, le rapport montre le cache daté.
CADENCE_PNL_REFUS_H = 7 * 24.0
CACHE_PNL_REFUS = Path("runtime") / "data" / "pnl_des_refus_hebdo.json"


def _sec_pnl_des_refus(root: Path, now_ms: int) -> list[str]:
    """## 7 — ce que les REFUS nous ont coûté/épargné (simulation sur données enregistrées).

    L'honnêteté de la section vit dans le module `pnl_des_refus` lui-même : un refus
    « coûteux » = re-mesurer la porte au replay complet, JAMAIS l'ouvrir sur ce chiffre."""
    out = ["## 7. PnL des refus (hebdo) — combien coûtent nos portes ?", ""]
    cache = root / CACHE_PNL_REFUS
    d = _json(cache)
    age_h = (now_ms - int(d.get("calcule_ts_ms") or 0)) / 3.6e6
    if not d or age_h > CADENCE_PNL_REFUS_H:
        try:
            import sys as _sys
            _sys.path.insert(0, str(root / "tools"))
            from pnl_des_refus import pnl_des_refus as _calc  # noqa: PLC0415
            r = _calc(root)
            d = {"calcule_ts_ms": now_ms, "resultat": r}
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            age_h = 0.0
        except Exception as exc:  # noqa: BLE001 — la section dit sa panne, le rapport survit
            out.append("Section indisponible cette semaine : `%s`" % exc)
            return out
    r = d.get("resultat") or {}
    pm = r.get("par_motif") or {}
    out.append("_Calculé il y a %.1f j (cadence : hebdo). Simulation sur candidats refusés "
               "enregistrés — pas une promesse._" % (age_h / 24.0))
    out.append("")
    if not pm:
        out.append("Aucun refus mesurable sur les données replay (ou données insuffisantes).")
    for motif, v in sorted(pm.items(), key=lambda kv: (kv[1] or {}).get("pnl_simule_usd", 0.0)):
        out.append("- `%s` : ×%d refus, %d mesurés, PnL simulé si on avait ouvert : %+.2f $"
                   % (motif, int(v.get("n") or 0), int(v.get("mesures") or 0),
                      float(v.get("pnl_simule_usd") or 0.0)))
    nm = int(r.get("non_mesurables") or 0)
    if nm:
        out.append("- non mesurables (pas de marks sur la fenêtre) : ×%d — comptés, jamais inventés" % nm)
    if r.get("honnetete"):
        out.append("")
        out.append("> %s" % r["honnetete"])
    return out


# ============================================================ 20/07 soir — LE RAPPORT QUI PILOTE
# Demande de Flo : « le rapport doit être parfait afin d'améliorer le bot pour un PnL positif ».
# Trois sections nouvelles, TOUTES en lecture seule (aucun effet sur la session qui tourne) :
#   8. l'ÉCONOMIE par position ($/jour, amortie ou pas, heures restantes) ;
#   9. l'UNIVERS du scan (lu dans le log du feeder) : viables + presque-viables AVEC leur verrou ;
#  10. À FAIRE — des constats dérivés des données, jamais des promesses.

def _sec_economie_positions(root: Path, now_ms: int) -> list[str]:
    out = ["## 8. Carry — l'économie de chaque position ($/jour, amortissement)", ""]
    try:
        st = _json(root / "runtime" / "data" / "carry_paper_positions.json")
        try:
            sl = json.loads((root / "runtime" / "data" / "carry_spot_shortlist.json")
                            .read_text(encoding="utf-8"))
            shortlist = {str(r.get("coin") or "").upper(): r for r in sl if isinstance(r, dict)}
        except (OSError, ValueError):
            shortlist = {}
        ouvertes = st.get("ouvertes") or {}
        if not ouvertes:
            out.append("Aucune position carry ouverte.")
            return out
        tot_rev, tot_marge = 0.0, 0.0
        out.append("| coin | marge | notional | funding b/h | $/jour | accru | coût d'entrée | amortie ? |")
        out.append("|---|---|---|---|---|---|---|---|")
        for coin, p in sorted(ouvertes.items()):
            notional = float(p.get("notional_usdt") or 0.0)
            f_now = float((shortlist.get(coin) or {}).get("funding_bps_h")
                          or p.get("funding_bps_h_entree") or 0.0)
            rev_j = notional * f_now / 1e4 * 24.0
            accru = float(p.get("funding_accrued_usdt") or 0.0)
            cout = float(p.get("cout_entree_bps") or 0.0) * notional / 1e4
            if cout <= 0:
                statut = "OUI ✅ (entrée créditrice)"
            elif accru >= cout:
                statut = "OUI ✅"
            elif rev_j > 0:
                statut = "dans ~%.0f h" % ((cout - accru) / (rev_j / 24.0))
            else:
                statut = "jamais au taux courant ⚠️"
            tot_rev += rev_j
            tot_marge += float(p.get("marge_usdt") or 0.0)
            out.append("| %s | %.0f$ | %.0f$ | %.3f | %.4f$ | %.4f$ | %.4f$ | %s |"
                       % (coin, float(p.get("marge_usdt") or 0), notional, f_now, rev_j,
                          accru, cout, statut))
        out.append("")
        out.append("**Total : %.4f $/jour au taux courant · marge engagée %.0f $** "
                   "(déploiement à comparer au capital — la réserve de 20 %% est voulue)."
                   % (tot_rev, tot_marge))
    except Exception as exc:  # noqa: BLE001
        out.append("section illisible : %s" % exc)
    return out


def _sec_univers_scan(root: Path) -> list[str]:
    """Le dernier bloc « UNIVERS CARRY » du log feeder — lecture seule, format à nous.
    Presque-viables listés AVEC leur verrou : c'est là que se cachent les déblocages mesurés."""
    out = ["## 9. Scan carry — univers, viables, et presque-viables (avec leur verrou)", ""]
    try:
        txt = (root / "runtime" / "logs" / "carry-feeder.log").read_text(
            encoding="utf-8", errors="replace")
        blocs = txt.split("=== UNIVERS CARRY")
        if len(blocs) < 2:
            out.append("Univers introuvable dans le log feeder (collecteur pas encore passé ?).")
            return out
        lignes = blocs[-1].splitlines()[2:]
        viables, bloques = [], []
        for l in lignes:
            l = l.strip()
            if not l or l.startswith("coin") or "coin(s) perp∩spot" in l:
                if "coin(s) perp∩spot" in l:
                    out.append("_%s_" % l)
                    out.append("")
                break_after = "coin(s) perp∩spot" in l
                if break_after:
                    break
                continue
            morceaux = l.split(None, 4)
            if len(morceaux) < 5:
                continue
            coin, funding, liq, pire, statut = morceaux[0], morceaux[1], morceaux[2], morceaux[3], morceaux[4]
            (viables if statut.startswith("VIABLE") else bloques).append(
                (coin, funding, liq, statut))
        if viables:
            out.append("**Viables (%d)** : %s" % (len(viables),
                       " · ".join("%s (%s, liq %s)" % (c, f, q) for c, f, q, _ in viables)))
            out.append("")
        if bloques:
            out.append("**Bloqués — et par QUOI (le verrou est une info, pas une fatalité) :**")
            out.append("")
            for c, f, q, s in bloques[:12]:
                out.append("- `%s` (%s, liq %s) → %s" % (c, f, q, s))
    except Exception as exc:  # noqa: BLE001
        out.append("section illisible : %s" % exc)
    return out


def _sec_a_faire(root: Path, now_ms: int) -> list[str]:
    """Des CONSTATS actionnables dérivés des fichiers — jamais une promesse, jamais un ordre."""
    out = ["## 13. À FAIRE — ce que les données d'aujourd'hui désignent", ""]
    actions: list[str] = []
    try:  # cross-venue : verdict possible ?
        lignes = (root / "runtime" / "data" / "dispersion_venues.jsonl").read_text(
            encoding="utf-8").splitlines()
        def _ts(l):
            r = json.loads(l)
            return float(r.get("ts_ms") or (r.get("ts") or 0) * 1000.0) / 1000.0
        h = (_ts(lignes[-1]) - _ts(lignes[0])) / 3600.0 if len(lignes) > 1 else 0.0
        if h >= 72.0:
            actions.append("**Cross-venue : 72 h atteintes (%.0f h)** → lancer "
                           "`python tools/mesurer_dispersion_venues.py` pour LE verdict (#178)." % h)
        else:
            actions.append("Cross-venue : %.1f h / 72 h — verdict dans ~%.0f h. Rien à faire." % (h, 72.0 - h))
    except Exception:  # noqa: BLE001
        actions.append("Cross-venue : collecte illisible → vérifier venues-collector (superviseur).")
    try:  # superviseur : relances anormales ?
        sup = _json(root / "runtime" / "data" / "superviseur_collecteurs.json")
        rel = {k: v.get("relances_total") for k, v in sup.items()
               if isinstance(v, dict) and v.get("relances_total")}
        if rel:
            actions.append("Relances de collecteurs au compteur : %s — si un compteur grimpe "
                           "SEUL demain, c'est lui le malade (doc R5)." % rel)
    except Exception:  # noqa: BLE001
        pass
    try:  # whitelist copy : nourrie ?
        wl = _json(root / "runtime" / "data" / "copy_whitelist.json")
        n = len(wl.get("gardes") or [])
        actions.append("Copy-whitelist : %d leader(s) prouvé(s) → copy %s." %
                       (n, "peut suivre CES leaders uniquement" if n else
                        "verrouillé (aucun leader au markout prouvé — c'est la protection, pas une panne)"))
    except Exception:  # noqa: BLE001
        pass
    try:  # replay : assez de données pour la recherche de scénario ?
        base = root / "runtime" / "replay"
        if (base / "_merged" / "candidates.jsonl").exists():
            base = base / "_merged"     # 21/07 : les consolides vivent dans _merged/
        n_cand = sum(1 for _ in (base / "candidates.jsonl").open(encoding="utf-8")) \
            if (base / "candidates.jsonl").exists() else 0
        if n_cand >= 2000:
            actions.append("Replay : %d candidats consolidés → `RECHERCHE-SCENARIO-REPLAY.cmd` "
                           "a de quoi travailler (porte deux-moitiés + plateau)." % n_cand)
        else:
            actions.append("Replay : %d candidats consolidés (< 2000) — laisser l'usine tourner." % n_cand)
    except Exception:  # noqa: BLE001
        pass
    out += ["- " + a for a in actions] if actions else ["Rien à signaler."]
    return out


def _sec_hors_plancher(root: Path) -> list[str]:
    """QUI SORT DU PLANCHER (idée #7) — 57 % de nos relevés valent exactement 0,125 bps/h.
    Classer des coins tous au plancher, c'est classer du bruit. Le vrai signal est : qui en
    sort, et combien de temps. Statistique DESCRIPTIVE d'un passé, jamais une prédiction."""
    out = ["## 11. Qui sort du plancher de funding", ""]
    try:
        import sys as _s
        _s.path.insert(0, str(root / "src"))
        from hl_observer.backtesting.carry_scan_recorder import charger
        from hl_observer.funding.funding_hors_plancher import resume
        r = resume(charger(root))
    except Exception as exc:  # noqa: BLE001
        return out + ["_indisponible : %s_" % exc]
    if r.get("vide"):
        return out + ["_%s_" % r.get("detail", "pas encore de données")]
    out += ["- part globale du temps passé **au-dessus** du plancher : **%s %%** "
            "(sur %d coin(s) exploitables)"
            % (r["part_globale_hors_plancher_pct"], r["exploitables"]),
            "- meilleur coin : **%s**" % r.get("meilleur"), "",
            "| coin | temps hors plancher |", "|---|---:|"]
    for c, pct in (r.get("classement") or []):
        out.append("| %s | %.1f %% |" % (c, pct))
    out += ["", "_%s._" % r.get("note", "")]
    return out


def _sec_lois(root: Path) -> list[str]:
    """CE QUI EST DÉJÀ TRANCHÉ — pour ne pas rouvrir dix fois le même dossier.

    Ces verdicts ne vivaient que dans la mémoire d'une session de travail : une autre session,
    un autre outil, ou un redémarrage, et on pouvait ré-implémenter une stratégie qu'on avait
    prouvée perdante. Ils sont maintenant dans le dépôt, datés, avec leur chiffre.
    """
    out = ["## 12. Ce qui est déjà tranché (lois mesurées)", ""]
    try:
        import sys as _s
        _s.path.insert(0, str(root / "src"))
        from hl_observer.research.lois_mesurees import (LOIS, VERDICT_CONFIRME, VERDICT_LIMITE,
                                                        VERDICT_REFUTE, par_verdict)
    except Exception as exc:  # noqa: BLE001
        return out + ["_registre illisible : %s_" % exc]
    out.append("_%d loi(s) : %d réfutée(s), %d limite(s), %d confirmée(s). Détail complet : "
               "`docs/LOIS_MESUREES.md`. Une loi se rouvre avec une DONNÉE neuve, pas un "
               "argument neuf._" % (len(LOIS), len(par_verdict(VERDICT_REFUTE)),
                                    len(par_verdict(VERDICT_LIMITE)),
                                    len(par_verdict(VERDICT_CONFIRME))))
    out.append("")
    for l in par_verdict(VERDICT_CONFIRME) + par_verdict(VERDICT_LIMITE):
        icone = "🟢" if l.verdict == VERDICT_CONFIRME else "🟠"
        out.append("- %s **%s** — %s" % (icone, l.titre, l.chiffre))
    refutees = par_verdict(VERDICT_REFUTE)
    if refutees:
        out += ["", "🔴 Réfutées (ne pas ré-ouvrir sans donnée neuve) : %s"
                % ", ".join("`%s`" % l.cle for l in refutees)]
    return out


def _sec_allocation(root: Path) -> list[str]:
    """OÙ VA LE CAPITAL, et est-ce qu'il va au bon endroit ? (21/07)

    Le 21/07 on a mesuré une corrélation de −0,596 entre la marge engagée et le rendement
    net : on finançait le PLUS les coins les MOINS rentables (BTC, le meilleur, avait 25 $ ;
    STABLE, parmi les pires, 126 $). Cette section existe pour que ça ne puisse plus jamais
    passer une journée entière sans être vu.
    """
    lignes = ["## 10. Où va le capital (allocation)", ""]
    d = _json(root / "runtime" / "data" / "carry_allocation.json")
    if not d:
        return lignes + ["_Aucune allocation publiée (le carry n'a pas encore tourné avec "
                         "l'allocation par rendement net — redémarrage requis)._"]
    lignes += [
        "- règle : `%s`" % d.get("regle", "?"),
        "- capital alloué : **%s $** sur %s coin(s) financé(s)"
        % (d.get("capital_alloue_usd"), d.get("coins_finances")),
        "- rendement pondéré : **%s bps/j** (part égale : %s bps/j -> **%s %%** de mieux)"
        % (d.get("rendement_pondere_bps_j"), d.get("rendement_part_egale_bps_j"),
           d.get("gain_vs_part_egale_pct")),
        "- meilleur coin : **%s**" % d.get("meilleur"),
    ]
    ecartes = d.get("coins_ecartes") or []
    if ecartes:
        lignes.append("- écartés (rendement absent ou <= 0, donc ZÉRO capital) : %s"
                      % ", ".join(map(str, ecartes)))
    marges, nets = d.get("marges_usd") or {}, d.get("rendements_bps_j") or {}
    if marges:
        lignes += ["", "| coin | rendement net (bps/j) | marge cible ($) |",
                   "|---|---:|---:|"]
        for c in sorted(marges, key=lambda c: -(nets.get(c) or 0)):
            lignes.append("| %s | %s | %s |" % (c, nets.get(c), marges[c]))
    # ce que la marge RÉELLE vaut aujourd'hui, comparé à la cible : l'écart se comble par
    # RENFORT (aucune fermeture, donc aucun frais de sortie), une position par jour maximum.
    try:
        import sys as _s
        _s.path.insert(0, str(root / "src"))
        from hl_observer.funding.carry_positions_store import charger_gestionnaire
        ouvertes = charger_gestionnaire(root, mode="LIVE").ouvertes
        retards = [(c, float(p.get("marge_usdt") or 0), float(marges.get(c) or 0))
                   for c, p in sorted(ouvertes.items())
                   if float(marges.get(c) or 0) > float(p.get("marge_usdt") or 0) * 1.4]
        if retards:
            lignes += ["", "**Positions sous-financées** (le renfort les comblera, une par "
                       "jour et par position, sans jamais fermer) :", ""]
            for c, a, cible in retards:
                lignes.append("- %s : %.2f $ -> %.2f $ (**%+.2f $**)" % (c, a, cible, cible - a))
    except Exception as exc:  # noqa: BLE001
        lignes.append("_comparaison aux positions vivantes indisponible : %s_" % exc)
    return lignes


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
        secs = [_sec_pnl(racine, depuis), _sec_positions(racine, now),
                _sec_sante(racine), _sec_mesures(racine), _sec_refus(racine, depuis)]
        # Leçons du ledger (article Roan, 20/07) : aucune perte sans explication — les
        # regressions et les pertes inexpliquees s'affichent en ROUGE, chaque matin.
        try:
            from hl_observer.ops.lecons_du_ledger import resume_markdown
            secs.append(resume_markdown(racine, depuis_ms=depuis))
        except Exception as exc:  # noqa: BLE001
            secs.append(["## 6. Leçons du ledger", "", "section illisible : %s" % exc])
        secs.append(_sec_pnl_des_refus(racine, now))   # #186 : hebdo, cache date, jamais bloquant
        # 20/07 : le rapport qui PILOTE — economie/position, univers du scan, actions du jour.
        secs.append(_sec_economie_positions(racine, now))
        secs.append(_sec_univers_scan(racine))
        secs.append(_sec_allocation(racine))
        secs.append(_sec_hors_plancher(racine))
        secs.append(_sec_lois(racine))
        secs.append(_sec_a_faire(racine, now))
        for sec in secs:
            parts += sec + [""]
        parts.append("---")
        parts.append("**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · "
                     "0 signature · 0 dépôt/retrait.**")
        return "\n".join(parts)
    except Exception as exc:  # noqa: BLE001 — le rapport dit sa propre panne plutôt que planter
        return ("# Rapport quotidien — ERREUR DE GÉNÉRATION\n\n"
                "Le générateur a échoué : `%s`.\n"
                "Un rapport qui plante est un matin aveugle — signale-le.\n" % exc)


def _ecrire_atomique(chemin: Path, texte: str) -> None:
    """ÉCRITURE ATOMIQUE (21/07, exigence de Flo : « le fichier devra être entièrement
    complet ») : on écrit dans un .tmp puis os.replace — le fichier visible est TOUJOURS
    complet, même si on l'ouvre pile pendant une régénération. Jamais de rapport tronqué."""
    import os as _os
    tmp = chemin.with_suffix(chemin.suffix + ".tmp")
    tmp.write_text(texte, encoding="utf-8")
    _os.replace(tmp, chemin)


def ecrire(root: str | Path = RACINE, *, now_ms: int | None = None) -> Path:
    """Régénère le rapport. Le rapport est une VUE : il LIT les sources (ledger append-only,
    positions, journaux) et n'écrit JAMAIS dedans — régénérer ne perd rien, par construction."""
    racine = Path(root)
    texte = generer(racine, now_ms=now_ms)
    dossier = racine / "rapports"
    dossier.mkdir(parents=True, exist_ok=True)
    principal = dossier / "RAPPORT_DU_JOUR.md"
    _ecrire_atomique(principal, texte)
    archive = dossier / "archive_quotidienne"
    archive.mkdir(parents=True, exist_ok=True)
    jour = dt.datetime.fromtimestamp(
        (now_ms or time.time() * 1000) / 1000).strftime("%Y-%m-%d")
    _ecrire_atomique(archive / ("RAPPORT_%s.md" % jour), texte)
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
