"""VÉRIFIER TOUT — un seul point d'entrée, un seul verdict.

POURQUOI (demande de Flo, 19/07) : « y'a trop de fichiers à la racine, on devrait faire un
mégafichier qui teste tout ». Il y avait 24 `.cmd` à la racine, dont une dizaine de petits
vérificateurs qui chacun lançaient deux lignes de Python et écrivaient son propre `.txt`.
Résultat : pour savoir si le bot va bien, il fallait se souvenir de QUEL fichier lancer.

Ce module regroupe tous ces contrôles en SECTIONS, avec un verdict par section et un résumé
final. Le moissonneur reste à part (décision explicite de Flo) : c'est un outil de recherche,
pas un contrôle de santé du bot.

RÈGLE DE LECTURE — trois états, jamais deux :
    OK           le contrôle passe
    ÉCHEC        quelque chose est cassé, il faut agir
    INSUFFISANT  on n'a pas de quoi juger — ce n'est NI un succès NI un échec
Ce troisième état est le plus important. Confondre « pas de données » et « tout va bien » est
exactement ce qui a produit le faux « 1 sur 1M » : un résultat calculé sur du vide.

Read-only : ce module lit des fichiers et lance des tests. Aucun ordre, aucune clé, aucune
signature, aucun appel d'exécution.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

OK, ECHEC, INSUFF = "OK", "ECHEC", "INSUFFISANT"

#: les tests qui gardent les invariants du projet (rapides, ciblés). La suite COMPLÈTE reste
#: `TEST-AUDIT-complet.cmd` — on ne la duplique pas, on y renvoie.
TESTS_CIBLES = [
    "tests/test_no_real_trade_foundations.py",
    "tests/test_paper_ledger.py",
    "tests/test_echec_silencieux.py",
    "tests/test_carry_anti_churn.py",
    "tests/test_carry_marge_dynamique.py",
    "tests/test_carry_ouverture_gates.py",
    "tests/test_carry_positions_store.py",
    "tests/test_carry_position_lifecycle.py",
    "tests/test_marks_tous_coins.py",
    "tests/test_replay_doctor.py",
    "tests/test_collecter_liquidations.py",
    "tests/test_dashboard_v2_coherence.py",
    "tests/test_risk_guards_no_limbo.py",
    "tests/test_invariants_securite_imports.py",
    "tests/test_marqueurs_audit_fixture.py",
]


class Section:
    def __init__(self, titre: str) -> None:
        self.titre, self.etat, self.lignes = titre, OK, []

    def dire(self, txt: str) -> None:
        self.lignes.append(txt)

    def echouer(self, txt: str) -> None:
        self.etat = ECHEC
        self.lignes.append(txt)

    def insuffisant(self, txt: str) -> None:
        if self.etat != ECHEC:
            self.etat = INSUFF
        self.lignes.append(txt)


def _py(args: list[str], timeout: float = 900.0) -> tuple[int, str]:
    """Lance python avec PYTHONPATH=src. Ne lève jamais : un contrôle qui plante est un ÉCHEC
    de contrôle, pas une exception qui interrompt la vérification des autres."""
    import os
    env = dict(os.environ, PYTHONPATH=str(RACINE / "src"), PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run([sys.executable] + args, cwd=str(RACINE), env=env,
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT apres %.0f s" % timeout
    except Exception as exc:  # noqa: BLE001
        return 1, "%s: %s" % (type(exc).__name__, exc)


# ------------------------------------------------------------------ 1. tests

def section_tests() -> Section:
    s = Section("1. TESTS — les invariants du projet")
    code, sortie = _py(["-m", "pytest", "-q", "-p", "no:cacheprovider"] + TESTS_CIBLES)
    derniere = [l for l in sortie.strip().splitlines() if l.strip()][-1:]
    resume = derniere[0] if derniere else "(pas de sortie)"
    s.dire(resume.strip())
    if code != 0:
        s.echouer("des tests ECHOUENT -> voir le detail ci-dessus")
        for l in sortie.splitlines():
            if l.startswith("FAILED") or l.startswith("ERROR"):
                s.dire("   " + l.strip())
    s.dire("suite COMPLETE (plus longue) : TEST-AUDIT-complet.cmd")
    return s


# ------------------------------------------------------------------ 2. replay

def section_replay() -> Section:
    s = Section("2. REPLAY — assez de donnees pour mesurer ?")
    try:
        from hl_observer.backtesting.replay_doctor import diagnostiquer_base
        r = diagnostiquer_base(str(RACINE / "runtime" / "replay"))
    except Exception as exc:  # noqa: BLE001
        s.echouer("docteur replay indisponible : %s" % exc)
        return s
    s.dire("candidats %d (%d coins) · marks %d (%d coins) · couverture %.0f%%"
           % (r.n_candidats, r.n_coins_candidats, r.n_marks, r.n_coins_marks,
              r.couverture_marks * 100))
    if not r.suffisant:
        s.insuffisant("INSUFFISANT : " + ", ".join(r.raisons))
        s.dire("-> laisser tourner : ici, attendre a du sens (les donnees s'accumulent).")
    else:
        s.dire("le replay A/B peut tourner sans fabriquer de resultat.")
        s.dire("ATTENTION : « suffisant » = seuils franchis, PAS « on peut conclure sur un edge ».")
    return s


# ------------------------------------------------------------------ 3. carry

def section_carry() -> Section:
    s = Section("3. CARRY — positions, PnL, churn")
    try:
        from hl_observer.funding.carry_positions_store import diagnostic_churn, etat_carry
        e = etat_carry(RACINE)
        d = diagnostic_churn(RACINE, fenetre_h=24.0)
    except Exception as exc:  # noqa: BLE001
        s.echouer("etat carry illisible : %s" % exc)
        return s
    s.dire("positions ouvertes %s · realise %.4f $ · funding accru %.6f $"
           % (e.get("positions_ouvertes"), float(e.get("realized_net_pnl_usdc") or 0.0),
              float(e.get("funding_accru_ouvert_usdt") or 0.0)))
    tot_o = sum(int(v.get("opens") or 0) for v in (d.get("par_coin") or {}).values())
    tot_c = sum(int(v.get("closes") or 0) for v in (d.get("par_coin") or {}).values())
    s.dire("cycles 24 h : %d ouvertures / %d fermetures" % (tot_o, tot_c))
    if d.get("churn_detecte"):
        motifs = {}
        for v in (d.get("par_coin") or {}).values():
            for k, n in (v.get("motifs") or {}).items():
                motifs[k] = motifs.get(k, 0) + n
        # NE PAS CRIER AU LOUP. La fenetre de 24 h contient encore les fermetures d'AVANT
        # l'anti-churn du 19/07. Elles portent l'ancien motif `COIN_PLUS_DANS_SHORTLIST`, qui
        # n'existe PLUS dans le code : une absence breve ne ferme plus rien. Les compter comme
        # une panne actuelle apprendrait a Flo a ignorer l'alerte -- et une alerte qu'on ignore
        # ne protege plus de rien.
        s.dire("motifs : " + ", ".join("%s x%d" % (k, n) for k, n in motifs.items()))
        # TOUTE FERMETURE N'EST PAS DU CHURN. Confondre les deux, c'est crier au loup -- et une
        # alerte qu'on apprend a ignorer ne protege plus de rien.
        #   * BASE_CONVERGEE_PREMIUM_CAPTURE : on ENCAISSE le premium. C'est le but, pas un defaut.
        #   * SORTIE_LIQUIDATION / SORTIE_FUNDING : sorties JUSTIFIEES (danger, ou plus rentable).
        #   * DONNEE_ABSENTE_PROLONGEE : l'anti-churn a TOLERE l'absence puis tranche. Il travaille.
        #   * COIN_PLUS_DANS_SHORTLIST : l'ANCIEN motif, celui qui coutait 17 bps sur un fichier
        #     ecrit en retard. Il n'existe PLUS dans le code depuis le 19/07 -- s'il reapparait
        #     apres demain, c'est que le correctif a saute.
        LEGITIMES = {"BASE_CONVERGEE_PREMIUM_CAPTURE", "SORTIE_LIQUIDATION", "SORTIE_FUNDING",
                     "SORTIE_AGE", "DONNEE_ABSENTE_PROLONGEE"}
        legacy = motifs.get("COIN_PLUS_DANS_SHORTLIST", 0)
        nuisibles = sum(n for k, n in motifs.items()
                        if k not in LEGITIMES and k != "COIN_PLUS_DANS_SHORTLIST")
        if nuisibles > 3:
            s.echouer("CHURN ACTUEL sur %s (%d fermetures non justifiees) — chaque aller-retour "
                      "coute ~17 bps." % (", ".join(d.get("coins_en_churn") or []), nuisibles))
        elif legacy:
            s.dire("churn HISTORIQUE : %d fermetures sur l'ANCIEN motif, d'avant l'anti-churn "
                   "du 19/07. Elles sortiront seules de la fenetre 24 h." % legacy)
            s.dire("-> rien a faire aujourd'hui. Les autres fermetures sont justifiees "
                   "(premium encaisse, danger, ou donnee vraiment disparue).")
        else:
            s.dire("les fermetures de la fenetre sont toutes JUSTIFIEES — pas du churn.")
    return s


# ------------------------------------------------------------------ 4. liquidations

def section_liquidations() -> Section:
    s = Section("4. LIQUIDATIONS — la piste #3")
    try:
        from hl_observer.market.liquidation_recorder import resume_historique
        h = resume_historique(root=str(RACINE))
    except Exception as exc:  # noqa: BLE001
        s.echouer("historique illisible : %s" % exc)
        return s
    s.dire("snapshots %s · coins %s · heures couvertes %s"
           % (h.get("snapshots"), h.get("coins"), h.get("heures_couvertes")))
    if not h.get("snapshots"):
        s.insuffisant("AUCUN historique.")
        log = RACINE / "runtime" / "logs" / "liq-collector.log"
        texte = ""
        try:
            texte = log.read_text(encoding="utf-8", errors="ignore")[-3000:]
        except OSError:
            pass
        if "POURQUOI 0 GRAPPE" in texte:
            s.dire("-> le collecteur TOURNE et lit des positions reelles, mais les filtres les")
            s.dire("   rejettent (population du leaderboard trop peu leveragee).")
            s.dire("   ATTENDRE NE SERT A RIEN. Detail : tools\\mesurer_edge_liquidation.py")
        elif texte:
            s.dire("-> le collecteur tourne, rien d'ecrit pour l'instant.")
        else:
            s.dire("-> le collecteur n'a jamais tourne (aucun runtime\\logs\\liq-collector.log).")
    return s


# ------------------------------------------------------------------ 4bis. cross-venue

def section_venues() -> Section:
    """LA DERNIERE PISTE OUVERTE. Barres fixees AVANT la donnee :
    docs/audit/PROTOCOLE_CROSS_VENUE.md. Si elle tombe, la conclusion honnete sera que ce bot
    ne produit pas de PnL positif en paper sur les angles accessibles."""
    s = Section("4bis. CROSS-VENUE — la derniere piste non refutee")
    code, sortie = _py(["tools/mesurer_dispersion_venues.py", "--root", str(RACINE)], timeout=180)
    try:
        rap = json.loads(sortie[sortie.index("{"):sortie.rindex("}") + 1])
    except (ValueError, IndexError):
        s.insuffisant("verdict illisible (le collecteur n'a peut-etre jamais tourne)")
        return s
    v = rap.get("verdict")
    if v == "INSUFFISANT":
        s.insuffisant("INSUFFISANT — %s" % rap.get("motif", ""))
        s.dire("-> ici, attendre a du SENS : les barres exigent >= 72 h et >= 5 coins.")
        return s
    s.dire("dispersion mediane %.5f bps/h (seuil utile %.5f) · %.1f h · %d coins"
           % (rap.get("dispersion_mediane_bps_h", 0), rap.get("seuil_utile_bps_h", 0),
              rap.get("heures_observees", 0), rap.get("coins", 0)))
    s.dire("rendement NET %.2f %%/an  (carry mono-venue : 0,82 %%/an)"
           % rap.get("rendement_net_annuel_pct", 0))
    for b in rap.get("barres") or []:
        s.dire("  [%s] %s — %s" % ("OK" if b["passee"] else "RATEE", b["barre"], b["mesure"]))
    if v == "REJETE":
        s.dire("REJETE : %s. On l'enterre comme les autres — les barres etaient ecrites AVANT."
               % ", ".join(rap.get("barres_ratees") or []))
    else:
        s.dire("EXPLOITABLE : les trois barres passent. Prochaine etape = paper.")
    return s


# ------------------------------------------------------------------ 5. collecteurs

def section_collecteurs() -> Section:
    s = Section("5. COLLECTEURS — tournent-ils ?")
    maintenant = time.time()
    for nom, limite_min in (("carry-feeder", 15.0), ("marks-collector", 5.0),
                            ("liq-collector", 20.0), ("venues-collector", 20.0)):
        p = RACINE / "runtime" / "logs" / ("%s.log" % nom)
        if not p.exists():
            s.echouer("%-16s AUCUN log -> ne tourne pas" % nom)
            continue
        age_min = (maintenant - p.stat().st_mtime) / 60.0
        if age_min > limite_min:
            s.echouer("%-16s log fige depuis %.0f min (limite %.0f)" % (nom, age_min, limite_min))
        else:
            s.dire("%-16s actif (derniere ecriture il y a %.1f min)" % (nom, age_min))
    return s


# ------------------------------------------------------------------ 6. cablage

def section_cablage() -> Section:
    s = Section("6. CABLAGE — code ecrit mais jamais appele")
    try:
        from hl_observer.audit.dette_cablage import DETTE_CABLAGE, PLAFOND_DETTE
    except Exception as exc:  # noqa: BLE001
        s.echouer("registre de dette illisible : %s" % exc)
        return s
    s.dire("dette DECLAREE : %d modules (plafond %d) — ecrits, testes, appeles par PERSONNE"
           % (len(DETTE_CABLAGE), PLAFOND_DETTE))
    if len(DETTE_CABLAGE) > PLAFOND_DETTE:
        s.echouer("la dette REMONTE : on branche ou on enterre, on ne declare pas de plus.")
    else:
        s.dire("-> ces modules ne protegent rien et ne rapportent rien AUJOURD'HUI.")
    return s


# ------------------------------------------------------------------ 7. securite

def section_securite() -> Section:
    s = Section("7. SECURITE — 0 ordre reel")
    code, sortie = _py(["-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "tests/test_no_real_trade_foundations.py",
                        "tests/test_invariants_securite_imports.py"], timeout=300)
    if code != 0:
        s.echouer("LES INVARIANTS DE SECURITE ECHOUENT — a traiter AVANT tout le reste.")
        s.dire(sortie.strip().splitlines()[-1] if sortie.strip() else "")
    else:
        s.dire("aucun appel d'execution reelle, aucune lib de signature, aucun cycle interdit.")
    return s


# ------------------------------------------------------------------ rapport

def executer(sections_demandees: list[str] | None = None) -> int:
    toutes = [("tests", section_tests), ("replay", section_replay), ("carry", section_carry),
              ("liquidations", section_liquidations), ("venues", section_venues),
              ("collecteurs", section_collecteurs),
              ("cablage", section_cablage), ("securite", section_securite)]
    if sections_demandees:
        toutes = [(n, f) for n, f in toutes if n in sections_demandees]

    debut = time.time()
    resultats = []
    for nom, fonction in toutes:
        print("  ... %s" % nom, flush=True)
        try:
            resultats.append(fonction())
        except Exception as exc:  # noqa: BLE001
            s = Section(nom)
            s.echouer("le controle lui-meme a plante : %s: %s" % (type(exc).__name__, exc))
            resultats.append(s)

    lignes = ["", "=" * 74, "  VERIFICATION COMPLETE — %s" % time.strftime("%d/%m/%Y %H:%M:%S"),
              "=" * 74, ""]
    for s in resultats:
        lignes.append("%-58s [%s]" % (s.titre, s.etat))
        for l in s.lignes:
            lignes.append("     " + l)
        lignes.append("")

    echecs = [s.titre for s in resultats if s.etat == ECHEC]
    insuff = [s.titre for s in resultats if s.etat == INSUFF]
    lignes.append("-" * 74)
    if echecs:
        lignes.append("  VERDICT : %d SECTION(S) EN ECHEC" % len(echecs))
        for t in echecs:
            lignes.append("     - " + t)
    elif insuff:
        lignes.append("  VERDICT : rien de casse, mais %d section(s) sans assez de donnees "
                      "pour juger" % len(insuff))
        for t in insuff:
            lignes.append("     - " + t)
    else:
        lignes.append("  VERDICT : TOUT PASSE")
    lignes.append("")
    lignes.append("  Rappel : « suffisant » ne veut jamais dire « rentable ». Aucun de ces")
    lignes.append("  controles ne promet un PnL — ils verifient que les chiffres sont HONNETES.")
    lignes.append("  Duree : %.0f s" % (time.time() - debut))
    lignes.append("-" * 74)

    texte = "\n".join(lignes)
    print(texte)
    try:
        (RACINE / "resultat-verification.txt").write_text(texte, encoding="utf-8")
        print("\n  Rapport ecrit : resultat-verification.txt")
    except OSError:
        pass
    return 1 if echecs else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Verifie TOUT le bot en une passe (lecture seule).")
    p.add_argument("--sections", nargs="*", default=None,
                   help="tests replay carry liquidations collecteurs cablage securite")
    p.add_argument("--json", action="store_true", help="sortie machine")
    a = p.parse_args(argv)
    if a.json:
        code = executer(a.sections)
        print(json.dumps({"code": code}))
        return code
    return executer(a.sections)


if __name__ == "__main__":
    raise SystemExit(main())
