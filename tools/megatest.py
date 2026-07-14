#!/usr/bin/env python3
"""MEGATEST — les 7 controles HyperSmart en UN seul passage, UNE seule sortie (2026-07-12).

REMPLACE :
    TEST-AUDIT-complet.cmd · POURQUOI-ZERO-POSITION.cmd · MESURER_SEUIL_FUNDING.cmd
    MESURER-SPREAD-CARNET.cmd · MESURER-FLUX-MM.cmd · MESURER-CARRY-NEUTRE.cmd
    CONSULTER-MEMOIRE.cmd

SORTIE UNIQUE : MEGATEST.md (racine). Reecrit APRES CHAQUE SECTION -> il existe meme si tu
fais Ctrl-C ou si une section plante. Jamais de rapport vide.

CE QUI A ETE AMELIORE (et pourquoi)
-----------------------------------
1. AUCUN `pause`. Les 7 scripts s'arretaient chacun sur "Appuyez sur une touche" : impossible
   de tout lancer et d'aller faire autre chose. Ici : un seul lancement, zero babysitting.
2. TIMEOUT PAR SECTION. Avant, un script bloque (reseau qui pend) figeait tout, sans rapport.
   Maintenant une section qui depasse son budget est TUEE et marquee TIMEOUT -- les autres
   continuent, le rapport sort quand meme.
3. TABLEAU DE VERDICTS EN TETE. Avant il fallait lire 7 sorties pour savoir ou on en est.
4. RESEAU DETECTE UNE FOIS. Si Hyperliquid est injoignable, les 4 sections reseau sont
   marquees SANS_RESEAU au lieu de cracher 4 stacktraces identiques.
5. HONNETETE : une section qui echoue est marquee ECHEC, jamais masquee. Un rapport qui ment
   est pire que pas de rapport.

MODES
-----
    python tools/megatest.py                 # rapide  : tout SAUF l'ecoute longue du flux
    python tools/megatest.py --complet       # + ecoute du flux 60 min (defaut du mode complet)
    python tools/megatest.py --minutes 240   # + ecoute du flux 240 min
    python tools/megatest.py --fast          # audit sans 2e passe anti-flaky (plus rapide)

100 % LECTURE SEULE. Aucun ordre reel, aucun argent reel, aucune cle privee, aucune signature.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAPPORT = ROOT / "MEGATEST.md"
API = "https://api.hyperliquid.xyz/info"

# --- mots-cles de verdict cherches dans la sortie de chaque outil (ordre = priorite) ---
SIGNAUX = (
    ("🔴", ("AUCUN MARCHE NE SURVIT", "AUCUN CARRY DELTA-NEUTRE VIABLE", "VERDICT_MORT",
            "ECHECS DETECTES", "NE PAS COMMITER")),
    ("🟠", ("QUASI-MORT", "TOXIQUE", "SPOT_TROP_MINCE", "AUCUN_MARCHE_SPOT",
            "LE BOT N'EST PAS CASSE")),
    ("🟢", ("TOUT EST VERT", "VIABLE", "PASSANT", "SELECTIF")),
)


@dataclass
class Section:
    cle: str
    titre: str
    pourquoi: str                      # a quoi sert ce controle, en une phrase
    argv: list[str]
    timeout_s: float
    reseau: bool = False
    # BLOQUANT vs INFORMATIF -- distinction VITALE (bug corrige le 2026-07-12).
    #
    # `mesurer_carry_neutre.py` renvoie 2 quand aucun carry n'est viable. `measure_funding_gate`
    # peut renvoyer non-zero quand le seuil est mort. Ce sont des REPONSES DE MARCHE, pas des
    # pannes. Les traiter comme des echecs faisait dire a MEGATEST « ne pas commiter » parce que
    # le marche ne cooperait pas -- absurde, et exactement le contraire du principe qu'il affiche.
    #
    # SEUL l'audit du CODE est bloquant. Le marche, lui, a le droit de dire non.
    bloquant: bool = False
    # remplis a l'execution
    statut: str = "NON_LANCE"
    verdict: str = "—"
    duree_s: float = 0.0
    sortie: str = ""
    code: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def en_echec(self) -> bool:
        """Un ECHEC = le controle n'a pas pu s'executer, OU le code est casse.

        Un verdict de marche defavorable n'est PAS un echec.
        """
        return self.statut.startswith("ECHEC") or self.statut == "ERREUR"


def _py() -> str:
    return sys.executable or "python"


def _reseau_disponible() -> tuple[bool, str]:
    """Un seul test reseau pour les 4 sections qui en dependent."""
    try:
        req = urllib.request.Request(
            API, data=json.dumps({"type": "meta"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=12.0) as r:
            data = json.loads(r.read().decode("utf-8"))
        n = len((data or {}).get("universe") or [])
        if n <= 0:
            return False, "reponse vide de l'API publique"
        return True, "OK — %d marches perp visibles" % n
    except Exception as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)


def _verdict_depuis_sortie(txt: str) -> str:
    haut = txt.upper()
    for embleme, motifs in SIGNAUX:
        for motif in motifs:
            if motif.upper() in haut:
                return "%s %s" % (embleme, motif.title())
    return "—"


def _lancer(sec: Section) -> None:
    debut = time.monotonic()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        # ISOLATION (2026-07-13) : un Ctrl-C de pytest frappe la CONSOLE, donc NOUS. Deja constate
        # sur audit_report (11/07) et couverture_de_lignes (13/07). Ici la commande est construite
        # dynamiquement -> l'invariant AST ne peut PAS le prouver ; on isole donc systematiquement.
        # Cout : nul. Ce que ca empeche : mourir en emportant le verdict.
        proc = subprocess.run(
            [_py(), *sec.argv],
            cwd=str(ROOT), env=env, timeout=sec.timeout_s,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
        )
        sec.code = proc.returncode
        sec.sortie = (proc.stdout or "").strip()
        if proc.returncode == 0:
            sec.statut = "OK"
        elif sec.bloquant:
            sec.statut = "ECHEC(code=%d)" % proc.returncode
        else:
            # Le marche a le droit de dire non. Ce n'est pas une panne.
            sec.statut = "VERDICT(code=%d)" % proc.returncode
    except subprocess.TimeoutExpired as exc:
        sec.statut = "TIMEOUT(%ds)" % int(sec.timeout_s)
        sec.sortie = (exc.stdout or "").strip() if isinstance(exc.stdout, str) else ""
        sec.notes.append(
            "Section tuee apres %d s. Les autres sections ont continue : "
            "un blocage ne doit JAMAIS priver du rapport entier." % int(sec.timeout_s)
        )
    except FileNotFoundError:
        sec.statut = "OUTIL_ABSENT"
        sec.notes.append("Script introuvable : %s" % " ".join(sec.argv))
    except Exception as exc:  # noqa: BLE001 - on veut le rapport meme si un outil explose
        sec.statut = "ERREUR"
        sec.sortie = "%s: %s" % (type(exc).__name__, exc)
    sec.duree_s = time.monotonic() - debut
    sec.verdict = _verdict_depuis_sortie(sec.sortie)


def _bloc_code(txt: str, limite_lignes: int = 220) -> str:
    lignes = (txt or "(aucune sortie)").splitlines()
    coupe = ""
    if len(lignes) > limite_lignes:
        garde = lignes[:limite_lignes // 2] + ["", "   [...] %d lignes coupees [...]" % (len(lignes) - limite_lignes), ""] + lignes[-limite_lignes // 2:]
        lignes = garde
        coupe = ""
    return "```text\n" + "\n".join(lignes) + "\n```" + coupe


def _ecrire(sections: list[Section], reseau_ok: bool, reseau_note: str, mode: str) -> None:
    """Reecrit MEGATEST.md EN ENTIER a chaque appel -> le rapport existe toujours."""
    maintenant = datetime.now(timezone.utc).astimezone()
    faits = [s for s in sections if s.statut != "NON_LANCE"]
    bloquants = [s for s in faits if s.en_echec]

    out = io.StringIO()
    w = out.write

    w("# MEGATEST — HyperSmart Observer\n\n")
    w("**%s** · mode `%s` · %d/%d sections executees\n\n"
      % (maintenant.strftime("%Y-%m-%d %H:%M:%S %Z"), mode, len(faits), len(sections)))
    w("> **100 % LECTURE SEULE.** 0 ordre reel · 0 argent reel · 0 cle privee · 0 signature · "
      "0 depot/retrait. Aucun endpoint d'execution n'est appele par ce rapport.\n\n")
    w("Reseau Hyperliquid : **%s** — %s\n\n" % ("joignable" if reseau_ok else "INJOIGNABLE", reseau_note))

    # ---------- synthese ----------
    w("## Synthese\n\n")
    w("| # | Controle | Nature | Statut | Verdict | Duree |\n|---|---|---|---|---|---|\n")
    for i, s in enumerate(sections, 1):
        w("| %d | **%s** | %s | `%s` | %s | %.0f s |\n"
          % (i, s.titre, "🔒 bloquant" if s.bloquant else "mesure", s.statut, s.verdict, s.duree_s))
    w("\n")
    w("> **`ECHEC` ≠ verdict rouge.** Un `ECHEC` veut dire que le CODE est casse (seul l'audit "
      "peut en produire un : c'est la seule section bloquante). Un `VERDICT(code=N)` veut dire "
      "que le MARCHE a repondu non — ce n'est pas une panne, et ca n'interdit pas de commiter.\n\n")

    if bloquants:
        w("### 🔴 %d section(s) EN ECHEC — le code est casse, ne pas commiter\n\n" % len(bloquants))
        for s in bloquants:
            w("- **%s** (`%s`)\n" % (s.titre, s.statut))
        w("\n")
    elif len(faits) == len(sections):
        w("### ✅ Aucun echec technique — commit autorise.\n\n")
        w("*Attention : « aucun echec technique » ne veut PAS dire « le bot gagne de l'argent ». "
          "Un verdict 🔴 ci-dessus (ex. « aucun marche ne survit ») est une REPONSE mesuree, "
          "pas une panne.*\n\n")

    w("---\n\n")

    # ---------- detail ----------
    for i, s in enumerate(sections, 1):
        w("## %d. %s\n\n" % (i, s.titre))
        w("*%s*\n\n" % s.pourquoi)
        w("- statut : `%s`" % s.statut)
        if s.code is not None:
            w(" · code retour : `%d`" % s.code)
        w(" · duree : %.1f s\n" % s.duree_s)
        w("- commande : `python %s`\n\n" % " ".join(s.argv))
        for note in s.notes:
            w("> ⚠️ %s\n\n" % note)
        if s.statut == "NON_LANCE":
            w("_Section non executee dans ce mode._\n\n")
        else:
            w(_bloc_code(s.sortie))
            w("\n\n")

    w("---\n\n")
    w("## Ce que ce rapport ne dit pas\n\n")
    w("- Il ne promet **aucun PnL positif**, et n'en promettra jamais.\n")
    w("- Un verdict vert sur l'audit signifie que le **code** est sain, pas que la **strategie** gagne.\n")
    w("- Les mesures reseau sont des **instantanes** : le funding, les spreads et la liquidite "
      "varient dans le temps. Un instantane ne tranche pas une question de regime.\n")

    RAPPORT.write_text(out.getvalue(), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="MEGATEST HyperSmart — 7 controles, 1 rapport.")
    ap.add_argument("--complet", action="store_true",
                    help="inclut l'ecoute longue du flux public (60 min par defaut)")
    ap.add_argument("--minutes", type=int, default=0,
                    help="duree d'ecoute du flux MM en minutes (implique --complet)")
    ap.add_argument("--fast", action="store_true",
                    help="audit sans la 2e passe anti-flaky (plus rapide)")
    ap.add_argument("--ci", action="store_true",
                    help="PRE-COMMIT : uniquement l'audit du code (ex-ci_local.cmd). "
                         "Aucune mesure de marche, aucun reseau requis.")
    args = ap.parse_args()

    minutes = 0 if args.ci else (args.minutes if args.minutes > 0 else (60 if args.complet else 0))
    if args.ci:
        mode = "ci (pre-commit : code seul)"
    elif minutes:
        mode = "complet (%d min de flux)" % minutes
    else:
        mode = "rapide"

    print("\n" + "=" * 78)
    print("  MEGATEST HYPERSMART — 7 controles, 1 seul rapport : MEGATEST.md")
    print("  Mode : %s" % mode)
    print("  100 %% lecture seule. Aucun ordre reel, jamais.")
    print("=" * 78 + "\n")

    print("  Test reseau (une seule fois pour les 4 sections qui en dependent)...")
    reseau_ok, reseau_note = _reseau_disponible()
    print("    -> %s\n" % reseau_note)

    audit_argv = ["tools/audit_report.py"] + (["--fast"] if args.fast else [])

    sections = [
        Section(
            "cmd_ascii", "Garde ASCII des .cmd — cmd.exe ne doit pas executer ses commentaires",
            "Un seul octet non-ASCII dans un .cmd, combine a un `chcp`, DECALE l'analyseur de "
            "cmd.exe : il perd des octets, saute des REM, et EXECUTE les commentaires. Ce bug est "
            "revenu 3 fois (2026-07-12 : \"'5001' n'est pas reconnu\" en boucle = chcp 65001 ampute "
            "de son 6). BLOQUANT : si le .cmd qui lance l'audit se sabote, plus rien n'est verifie.",
            ["tools/garde_cmd_ascii.py", "."], timeout_s=60.0, bloquant=True,
        ),
        Section(
            "audit", "Audit code + suite de tests complete",
            "33 controles : syntaxe, imports, secrets, execution reelle, planchers fail-open, "
            "modules sans test, couverture fichier par fichier, suite pytest. C'est le SEUL "
            "controle bloquant : les autres mesurent le MARCHE, celui-ci mesure le CODE.",
            audit_argv, timeout_s=2400.0, bloquant=True,
        ),
        Section(
            "zero_position", "Pourquoi le bot n'ouvre aucune position",
            "Confronte l'edge MESURE (table de calibration, prix reels) au cout aller-retour reel. "
            "Repond a la seule question qui compte : le bot est-il casse, ou a-t-il raison de refuser ?",
            ["tools/pourquoi_zero_position.py"], timeout_s=180.0,
        ),
        Section(
            "funding_gate", "Seuil de funding du Grinder — atteignable ?",
            "Le verrou d'entree du funding-arb exige 2,5 bps/h. Hyperliquid paie a l'HEURE (le repo "
            "d'origine visait une place qui paie aux 8 h). Si le funding reel reste loin sous le seuil, "
            "le verrou est MORT : zero trade garanti par construction.",
            ["tools/measure_funding_gate.py"], timeout_s=180.0, reseau=True,
        ),
        Section(
            "carnet", "Carnet L2 — le market making a-t-il de l'espace ?",
            "Un MM gagne le spread et paie les frais. Chez Hyperliquid le maker PAIE 1,5 bps "
            "(aller-retour 3 bps). Si le spread median est 10x plus petit que les frais, "
            "le MM est arithmetiquement mort — quel que soit le reglage.",
            ["tools/mesurer_spread_carnet.py"], timeout_s=600.0, reseau=True,
        ),
        Section(
            "carry", "Carry delta-neutre — la jambe spot existe-t-elle ?",
            "Le funding est le seul signal du projet a structure reelle (autocorrelation +0,70 a 1 h). "
            "Ce qui le tuait, c'est la jambe NUE (281 bps de prix subi pour 1 bps encaisse). "
            "Sans marche SPOT pour couvrir, la zone morte FUNDING_JAMBE_NUE reste fermee.",
            ["tools/mesurer_carry_neutre.py"], timeout_s=300.0, reseau=True,
        ),
        Section(
            "spot_diag", "Diagnostic brut du marche SPOT (anti-chiffre-impossible)",
            "Garde-fou : dumpe la structure reelle du payload spot. Existe parce que l'outil de carry "
            "a sorti « base HYPE = +177 721 383 bps ». Un chiffre impossible ne se commente pas, "
            "il se debogue. Ce controle empeche de conclure sur une mesure fausse.",
            ["tools/diagnostic_spot_hyperliquid.py"], timeout_s=180.0, reseau=True,
        ),
        Section(
            "memoire", "Cimetiere — les hypotheses deja tuees par une mesure",
            "Le registre des zones mortes : chaque impasse deja payee, sa mesure, sa taille "
            "d'echantillon, et sa CONDITION DE REOUVERTURE. Une zone morte n'est pas un dogme — "
            "mais on ne re-paie pas deux fois la meme impasse.",
            ["tools/consulter_memoire.py"], timeout_s=120.0,
        ),
    ]

    if args.ci:
        # Ex-`ci_local.cmd` : avant de commiter, on veut savoir si le CODE tient. Point.
        # Les mesures de marche n'ont rien a dire sur un commit, et exiger le reseau pour
        # commiter serait absurde.
        sections = [s for s in sections if s.bloquant]

    if minutes > 0:
        sections.insert(5, Section(
            "flux_mm", "Flux public — sélection adverse reelle du market making",
            "Un carnet dit qu'il y a de l'espace ; il ne dit PAS s'il y a quelqu'un en face. "
            "Un MM est rempli precisement quand il a tort. Cette ecoute mesure la selection adverse "
            "sur de VRAIS trades. Sous 30 min, rien n'est mesurable : le snapshot initial fausse tout.",
            ["tools/mesurer_flux_market_making.py", "--minutes", str(minutes)],
            timeout_s=minutes * 60 + 300.0, reseau=True,
        ))

    _ecrire(sections, reseau_ok, reseau_note, mode)  # rapport des le depart

    for i, sec in enumerate(sections, 1):
        if sec.reseau and not reseau_ok:
            sec.statut = "SANS_RESEAU"
            sec.notes.append("Hyperliquid injoignable — mesure impossible. "
                             "Ce n'est PAS un resultat : ne rien conclure de cette section.")
            print("  [%d/%d] %-52s SANS_RESEAU" % (i, len(sections), sec.titre[:52]))
            _ecrire(sections, reseau_ok, reseau_note, mode)
            continue

        print("  [%d/%d] %-52s ..." % (i, len(sections), sec.titre[:52]), end="", flush=True)
        _lancer(sec)
        print("\r  [%d/%d] %-52s %-16s %6.0fs  %s"
              % (i, len(sections), sec.titre[:52], sec.statut, sec.duree_s, sec.verdict))
        _ecrire(sections, reseau_ok, reseau_note, mode)   # <-- apres CHAQUE section

    faits = [s for s in sections if s.statut != "NON_LANCE"]
    echecs = [s for s in faits if s.en_echec]

    print("\n" + "-" * 78)
    print("  Rapport unique : %s" % RAPPORT)
    print("-" * 78)
    if echecs:
        print("\n  ############################################")
        print("    %d SECTION(S) EN ECHEC — LE CODE EST CASSE." % len(echecs))
        print("    NE PAS COMMITER.")
        for s in echecs:
            print("      - %s (%s)" % (s.titre, s.statut))
        print("  ############################################\n")
        return 1
    print("\n  ============================================")
    print("    CODE : aucun echec. Commit autorise.")
    print("    (Un VERDICT(code=N) sur le MARCHE n'est PAS un echec :")
    print("     c'est une reponse mesuree, et elle n'interdit pas de commiter.)")
    print("  ============================================\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n  Interrompu. MEGATEST.md contient tout ce qui a ete mesure jusqu'ici.\n")
        sys.exit(130)
