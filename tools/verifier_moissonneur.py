r"""VERIFIER LE MOISSONNEUR — *les 3 defauts mesures sont-ils reellement corriges ?*

Ce fichier existe parce qu'un `python -c "..."` bourre de guillemets **dans un .cmd** est
fragile : `cmd.exe` avale les `%` comme des variables d'environnement. *Ca vient de casser
ce controle au premier essai.* -> un vrai fichier, verifiable, testable.

Aucun reseau. Aucune moisson lancee. **Lecture seule.**
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

CONCEPTS = RACINE / "tools" / "moissonner_concepts.py"
LIRE = RACINE / "tools" / "moissonner_lire_le_code.py"
SIGNAUX = RACINE / "src" / "hl_observer" / "research" / "github_signals.py"

# 🚨 Ce qu'on ne veut JAMAIS voir dans un outil qui telecharge du code d'inconnus.
#    *On LIT du texte. On ne lance RIEN.*
INTERDITS = ("subprocess", "os.system", "exec(", "eval(", "git clone", "importlib",
             "pickle.load", "__import__")


def _ok(bon: bool, msg: str) -> bool:
    print("  %s %s" % ("OK   " if bon else "ECHEC", msg))
    return bon


def main() -> int:
    print("=" * 96)
    print("  VERIFIER LE MOISSONNEUR v3 — les 3 defauts MESURES sont-ils corriges ?")
    print("=" * 96)
    tout = True

    # ── DEFAUT 1 : il perdait 235 README EN SILENCE, dont hftbacktest (notre cible n°1) ────────
    print("\n  [1] LE BUG DES README — 235 repos perdus, dont hftbacktest (4270 etoiles)")
    if not CONCEPTS.exists():
        tout = _ok(False, "moissonner_concepts.py INTROUVABLE") and tout
    else:
        s = CONCEPTS.read_text(encoding="utf-8", errors="replace")
        tout &= _ok("api.github.com/repos/" in s and "/readme" in s,
                    "l'API /repos/{o}/{r}/readme est utilisee (elle resout nom+ext+branche)")
        tout &= _ok("README.rst" in s, "le repli tente d'autres EXTENSIONS (.rst, .txt...)")
        tout &= _ok("develop" in s, "le repli tente d'autres BRANCHES (develop, dev, trunk)")
        tout &= _ok('RAW = "https://raw.githubusercontent.com/%s/%s/README.md"' not in s,
                    "l'ancienne URL en dur (README.md seulement) a DISPARU")

    # ── DEFAUT 2 : le tri mesurait la VERBOSITE, pas la substance ──────────────────────────────
    print("\n  [2] LE TRI — il recompensait celui qui CITE le plus de mots")
    if not SIGNAUX.exists():
        tout = _ok(False, "github_signals.py INTROUVABLE") and tout
    else:
        sys.path.insert(0, str(RACINE / "src"))
        from hl_observer.research.github_signals import (  # noqa: PLC0415
            POIDS_AVEU,
            POIDS_FORMULE,
            analyser,
            score,
        )

        bavard = ("A library covering market making, Avellaneda-Stoikov, queue position, "
                  "adverse selection, market impact, funding, liquidation, mempool, latency, "
                  "lookahead bias, kappa. Guaranteed profit!")  # audit:fixture — texte BAVARD que le trieur doit REJETER (bourrage de mots-clés) : échantillon négatif
        substantiel = ("lambda(delta) = A * exp(-kappa * delta). "
                       "Limitations: this is not a substitute for real L3 data. "
                       "Measured edge: -7.97 bps over 24133 out-of-sample signals. It didn't work.")

        s_bav = score(analyser(bavard), etoiles=5)
        s_sub = score(analyser(substantiel), etoiles=3)
        tout &= _ok(s_sub > s_bav,
                    "le README SUBSTANTIEL (%.1f) passe devant le BAVARD (%.1f)" % (s_sub, s_bav))
        tout &= _ok(POIDS_AVEU > POIDS_FORMULE,
                    "l'AVEU DE LIMITE reste le signal le plus fort "
                    "(la seule chose qu'un menteur ne peut pas simuler)")
        creux_celebre = score(analyser("An awesome fast trading bot."), etoiles=20_000)
        tout &= _ok(s_sub > creux_celebre,
                    "20 000 etoiles sans substance (%.1f) ne battent pas 3 etoiles avec (%.1f)"
                    % (creux_celebre, s_sub))

    # ── DEFAUT 3 : il ne lisait JAMAIS le code ─────────────────────────────────────────────────
    print("\n  [3] LIRE LE CODE — il s'arretait au README (= la page de vente)")
    if not LIRE.exists():
        tout = _ok(False, "moissonner_lire_le_code.py INTROUVABLE — la phase 3 n'existe pas")
        tout = False
    else:
        s = LIRE.read_text(encoding="utf-8", errors="replace")
        tout &= _ok("git/trees" in s, "il ouvre l'ARBRE du repo (sans cloner)")
        tout &= _ok("liste_de_lecture" in s,
                    "il produit une LISTE DE LECTURE (repo / fichier / LIGNE / pourquoi)")

        # 🚨 SECURITE — on telecharge du code d'inconnus. **On ne l'execute JAMAIS.**
        trouves = [m for m in INTERDITS if m in s]
        tout &= _ok(not trouves,
                    "aucun exec / clone / subprocess : **on LIT du texte, on ne lance RIEN**"
                    + ("  -> TROUVE : %s" % ", ".join(trouves) if trouves else ""))

    print("\n" + "=" * 96)
    if tout:
        print("  ✅ **LES 3 DEFAUTS SONT CORRIGES.**")
        print("     🚩 Rappel : *trier ne remplacera jamais lire.* 8 passes de tri sur 5 617")
        print("        repos -> 3 idees. 20 min a lire UN repo -> 5 bugs dans notre simu.")
    else:
        print("  🔴 **AU MOINS UN DEFAUT SUBSISTE.** Voir ci-dessus.")
    print("=" * 96)
    return 0 if tout else 1


if __name__ == "__main__":
    raise SystemExit(main())
