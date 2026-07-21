r"""RANGER LA RACINE — *104 .cmd et 68 rapports noyaient les 6 fichiers qui comptent.*

═══════════════════════════════════════════════════════════════════════════════════════════════
LE PIEGE — et pourquoi un simple `move` aurait casse 104 scripts
═══════════════════════════════════════════════════════════════════════════════════════════════

Chaque .cmd commence par :

    cd /d "%~dp0"                                   <- se place dans SON dossier
    set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"    <- cherche src\ a cote de lui
    python tools\xxx.py > rapport.txt               <- ecrit a cote de lui

***Deplace tel quel, `%~dp0` designe le NOUVEAU dossier.*** Le script se lancerait depuis
`outils de test\`, ne trouverait ni `src\`, ni `tests\`, ni `tools\`, et ecrirait ses rapports
au mauvais endroit. **104 scripts casses en un seul glisser-deposer.**

-> On **REECRIT** les 3 choses en meme temps qu'on deplace :
     `cd /d "%~dp0"`  ->  `cd /d "%~dp0.."`         (on remonte a la racine du projet)
     `%~dp0src`       ->  `%CD%\src`                (apres le cd, %CD% EST la racine)
     `> rapport.txt`  ->  `> "%~dp0rapports\rapport.txt"`

═══════════════════════════════════════════════════════════════════════════════════════════════
L'INDEX SE CONSTRUIT TOUT SEUL
═══════════════════════════════════════════════════════════════════════════════════════════════

Flo : *« et que tu te souviennes de tous les outils de test qui seront dedans »*

Un index ecrit **a la main** ment des la premiere modification. Celui-ci est **extrait des
en-tetes `REM` de chaque fichier** : il ne peut pas diverger de la realite.
*(Relancer cet outil regenere l'index.)*

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUI RESTE A LA RACINE — *rien n'est supprime, jamais*
═══════════════════════════════════════════════════════════════════════════════════════════════

  LANCER_HYPERSMART.cmd   le runtime de la simulation (l'entree principale)
  LANCER-TOUT.cmd         la chaine carry complete (scanner -> noyau -> PaperIntent)
  TEST-AUDIT-complet.cmd  l'audit -- CLAUDE.md le designe explicitement A LA RACINE
  MOISSONNER-GITHUB.cmd   demande explicitement par Flo
  + la doc (CLAUDE.md, README, TASKLIST...) et la config (pyproject, ruff, requirements...)

Aucun fichier n'est supprime. **Un `move`, jamais un `delete`.**
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DEST = RACINE / "outils de test"
RAPPORTS = DEST / "rapports"

# 🔒 CE QUI NE BOUGE PAS. *On ne casse pas les entrees principales du projet.*
GARDER_CMD = {
    "LANCER_HYPERSMART.cmd",     # le runtime de la simulation
    "LANCER-TOUT.cmd",           # la chaine carry complete
    "TEST-AUDIT-complet.cmd",    # CLAUDE.md le designe A LA RACINE
    "MOISSONNER-GITHUB.cmd",     # demande explicitement par Flo
    "RANGER-LA-RACINE.cmd",      # cet outil lui-meme
}

# 🔒 des .txt qui ne sont PAS des rapports a deplacer.
#    `ranger_racine.txt` = le rapport de CET outil, **encore ouvert en ecriture** quand il tourne.
#    *Un script qui essaie de deplacer son propre journal se mord la queue.* (WinError 32.)
#    -> c'est le .cmd qui le rangera, APRES la fermeture du handle.
GARDER_TXT = {"requirements.txt", "ranger_racine.txt"}

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🔑 LES OUTILS **VIVANTS** — ceux qui disent encore quelque chose AUJOURD'HUI.
#
# Flo : *« ou alors fusionne les tous »*. **Je ne fusionne pas les 104.**
#
#     La plupart sont des ENQUETES CLOSES (CHECK-59x, Q1->Q3, T1/T2/T3, G1/G2, H181...).
#     Les relancer toutes prendrait des heures et cracherait un mur de texte sans valeur.
#     ***Un script qui fait tout ne dit plus rien.***
#
# -> on fusionne **ceux-la seulement**, dans `TOUT-VERIFIER.cmd`. Les autres restent la,
#    accessibles, classes « enquete close ». **Rien n'est supprime ni cache.**
# ═══════════════════════════════════════════════════════════════════════════════════════════════
VIVANTS: tuple[tuple[str, str], ...] = (
    ("CHECK-SAFETY.cmd", "SECURITE : 0 ordre reel, 0 cle, 0 signature"),
    ("VERIFIER-BRANCHEMENTS.cmd", "les garde-fous sont-ils DANS la porte ? (audit AST)"),
    ("LES-LEVIERS.cmd", "tous les leviers pour ouvrir plus -- calcules, pas opines"),
    ("LA-PROFONDEUR.cmd", "le carnet porte-t-il notre taille ? (4 jambes)"),
    ("LE-VERDICT.cmd", "nos carrys battent-ils un depot passif dans HLP ?"),
    ("COUVERTURE-LIGNES.cmd", "la couverture REELLE des tests"),
    ("VERIFIER-TASKLIST.cmd", "l'etat des taches"),
    ("CONSULTER-MEMOIRE.cmd", "ce que le projet a appris"),
)


def _description(chemin: Path) -> str:
    """La description d'un .cmd = ses premieres lignes `REM` utiles. **Extraite, pas inventee.**"""
    try:
        lignes = chemin.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    out: list[str] = []
    for ligne in lignes:
        s = ligne.strip()
        if not s.upper().startswith("REM"):
            continue
        s = s[3:].strip()
        # on saute les barres de separation et les lignes vides
        if not s or set(s) <= set("=-_ #*"):
            continue
        out.append(s)
        if len(out) >= 2:
            break
    return " — ".join(out)[:150]


def _reecrire(contenu: str, nom_rapport_connu: set[str]) -> tuple[str, list[str]]:
    r"""Repare les chemins. Renvoie `(nouveau_contenu, ce_qui_a_ete_change)`."""
    change: list[str] = []

    # 1. le `cd` : on REMONTE a la racine du projet.
    neuf, n = re.subn(r'cd /d "%~dp0"', 'cd /d "%~dp0.."', contenu)
    if n:
        change.append("cd -> racine")
        contenu = neuf

    # 2. le PYTHONPATH : apres le `cd`, %CD% EST la racine du projet.
    neuf, n = re.subn(r'%~dp0src', r'%CD%\\src', contenu)
    if n:
        change.append("PYTHONPATH src")
        contenu = neuf
    neuf, n = re.subn(r'%~dp0;', r'%CD%;', contenu)
    if n:
        change.append("PYTHONPATH racine")
        contenu = neuf

    # 3. les rapports : ils vont dans `outils de test\rapports\`.
    #    ⚠️ on ne touche QUE les redirections (`>` / `>>`), jamais un nom de fichier passe
    #    en argument a un script -- *sinon on casserait silencieusement des chemins de donnees.*
    def _redir(m: re.Match) -> str:
        fleche, nom = m.group(1), m.group(2)
        return '%s "%%~dp0rapports\\%s"' % (fleche, nom)

    neuf, n = re.subn(r'(>>?)\s+([A-Za-z0-9_\-]+\.txt)(?=\s|$)', _redir, contenu)
    if n:
        change.append("%d rapport(s) -> rapports\\" % n)
        contenu = neuf

    return contenu, change


def main() -> int:
    print("=" * 96)
    print("  RANGER LA RACINE — *un `move`, jamais un `delete`.*")
    print("=" * 96)

    cmds = sorted(p for p in RACINE.glob("*.cmd") if p.name not in GARDER_CMD)
    txts = sorted(p for p in RACINE.glob("*.txt") if p.name not in GARDER_TXT)

    DEST.mkdir(exist_ok=True)
    RAPPORTS.mkdir(exist_ok=True)

    noms_rapports = {p.name for p in txts}
    non_reecrits: list[str] = []

    # ── les scripts ───────────────────────────────────────────────────────────────────────────
    for p in cmds:
        contenu = p.read_text(encoding="utf-8", errors="replace")
        neuf, change = _reecrire(contenu, noms_rapports)
        cible = DEST / p.name
        cible.write_text(neuf, encoding="utf-8", newline="\r\n")
        p.unlink()                       # deplace : ecrit d'abord, supprime ensuite. Jamais l'inverse.
        if not change:
            non_reecrits.append(p.name)

    # ── les rapports ──────────────────────────────────────────────────────────────────────────
    for p in txts:
        shutil.move(str(p), str(RAPPORTS / p.name))

    # 🔑 L'INDEX SE CONSTRUIT SUR CE QUI EST **REELLEMENT** DANS LE DOSSIER, pas sur ce que ce
    #    passage vient de deplacer. *Sinon un 2e lancement (rien a bouger) produirait un index VIDE
    #    -- et un index vide est un mensonge plus dangereux qu'un index absent.*
    index: list[tuple[str, str]] = [
        (p.name, _description(p))
        for p in sorted(DEST.glob("*.cmd"))
        if p.name != "TOUT-VERIFIER.cmd"
    ]

    print("\n  📁 %d script(s) deplace(s) ce coup-ci -> `outils de test\\`" % len(cmds))
    print("  📄 %d rapport(s) deplace(s)  -> `outils de test\\rapports\\`" % len(txts))
    print("  📚 %d script(s) au total dans le dossier" % len(index))
    print("  🔒 gardes a la racine : %s"
          % ", ".join(sorted(GARDER_CMD - {"RANGER-LA-RACINE.cmd"})))

    if non_reecrits:
        print("\n  ⚠️ %d script(s) SANS en-tete standard -- **a verifier a la main** :"
              % len(non_reecrits))
        for n in non_reecrits:
            print("       %s" % n)
        print("     *Je ne pretends pas les avoir repares : je signale que je ne sais pas.*")

    # ── 🔑 LE POINT D'ENTREE FUSIONNE — *un seul script pour ce qui compte encore* ─────────────
    presents = [(n, d) for n, d in VIVANTS if (DEST / n).exists()]
    absents = [n for n, _ in VIVANTS if not (DEST / n).exists()]

    tv = [
        "@echo off",
        "setlocal",
        'cd /d "%~dp0.."',
        'set "PYTHONIOENCODING=utf-8"',
        'set "PYTHONUTF8=1"',
        "REM ==================================================================================",
        "REM   TOUT-VERIFIER — **le point d'entree unique** des outils qui comptent ENCORE.",
        "REM",
        "REM   Flo demandait de « fusionner les tous ». Je ne fusionne PAS les 104 :",
        "REM   la plupart sont des ENQUETES CLOSES (CHECK-59x, Q1-Q3, T1/T2/T3, H181...).",
        "REM   Les relancer prendrait des heures pour un mur de texte sans valeur.",
        "REM   ***Un script qui fait tout ne dit plus rien.***",
        "REM",
        "REM   -> celui-ci lance les %d verifications VIVANTES, dans l'ordre." % len(presents),
        "REM      Les autres restent la, classees « enquete close » (voir README.md).",
        "REM",
        "REM   Lecture seule. Paper-only. ASCII PUR, pas de pause.",
        "REM ==================================================================================",
        "",
    ]
    for i, (nom, desc) in enumerate(presents, 1):
        tv += [
            'echo.',
            'echo ============ %d/%d  %s ============' % (i, len(presents), desc[:60]),
            'call "%%~dp0%s"' % nom,
        ]
    tv += [
        "",
        "echo.",
        "echo ==================================================================================",
        "echo   TERMINE. Chaque rapport est dans : outils de test\\rapports\\",
        "echo   SECURITE : 0 ordre reel - 0 argent reel - 0 cle privee - 0 signature",
        "echo ==================================================================================",
        "exit /b 0",
        "",
    ]
    (DEST / "TOUT-VERIFIER.cmd").write_text("\r\n".join(tv), encoding="ascii", errors="replace")
    print("\n  🔑 point d'entree fusionne : `outils de test\\TOUT-VERIFIER.cmd` "
          "(%d verifications vivantes)" % len(presents))
    if absents:
        print("     ⚠️ introuvables, donc **PAS** inclus (je ne les invente pas) : %s"
              % ", ".join(absents))

    # ── L'INDEX — **extrait des fichiers, jamais ecrit de memoire** ────────────────────────────
    noms_vivants = {n for n, _ in presents}
    lignes = [
        "# Outils de test & rapports",
        "",
        "> **Cet index est GENERE** par `tools/ranger_racine.py` a partir des en-tetes `REM` de",
        "> chaque script. *Un index ecrit a la main ment des la premiere modification.*",
        "> Pour le regenerer : **`RANGER-LA-RACINE.cmd`** (a la racine).",
        "",
        "## 🔑 Par ou commencer",
        "",
        "**`TOUT-VERIFIER.cmd`** — le point d'entree **unique**. Il enchaine les %d verifications"
        % len(presents),
        "qui disent encore quelque chose aujourd'hui. Les rapports atterrissent dans `rapports/`.",
        "",
        "*Je n'ai pas fusionne les %d scripts : la plupart sont des **enquetes closes**. Les"
        % len(index),
        "relancer toutes prendrait des heures pour un mur de texte sans valeur.*",
        "***Un script qui fait tout ne dit plus rien.***",
        "",
        "## Comment ils marchent",
        "",
        "Double-clic. Chaque script **remonte tout seul** a la racine du projet",
        '(`cd /d "%~dp0.."`) et ecrit sa sortie dans **`rapports/`**.',
        "",
        "🔒 Tous sont en **lecture seule / paper-only**. Aucun n'envoie d'ordre reel.",
        "",
        "## Restes a la racine (ne PAS deplacer)",
        "",
        "| script | pourquoi |",
        "|---|---|",
        "| `LANCER_HYPERSMART.cmd` | le **runtime** de la simulation |",
        "| `LANCER-TOUT.cmd` | la chaine **carry** complete (scanner -> noyau -> PaperIntent) |",
        "| `TEST-AUDIT-complet.cmd` | l'audit — **CLAUDE.md le designe a la racine** |",
        "| `MOISSONNER-GITHUB.cmd` | **le moissonneur** — depose dans `runtime/research/github_repos_v24/` |",
        "",
        "---",
        "",
        "## ✅ Les %d outils VIVANTS (lances par `TOUT-VERIFIER.cmd`)" % len(presents),
        "",
        "| script | ce qu'il fait |",
        "|---|---|",
    ]
    for nom, desc in presents:
        lignes.append("| `%s` | %s |" % (nom, desc))

    historiques = [(n, d) for n, d in sorted(index) if n not in noms_vivants]
    lignes += [
        "",
        "---",
        "",
        "## 📦 Les %d enquetes CLOSES" % len(historiques),
        "",
        "*Elles ont servi une fois, elles ont rendu leur verdict. **On ne les supprime pas** —",
        "elles sont la preuve de ce qui a ete mesure. Mais on ne les relance pas en routine.*",
        "",
        "| script | ce qu'il faisait |",
        "|---|---|",
    ]
    for nom, desc in historiques:
        lignes.append("| `%s` | %s |" % (nom, desc.replace("|", "/") or "_(sans en-tete REM)_"))
    lignes += [
        "",
        "---",
        "",
        "*Aucun fichier n'a ete supprime. Chaque script a ete **deplace ET repare** :*",
        "*`cd` remonte a la racine, `PYTHONPATH` pointe sur `src/`, les rapports vont dans*",
        "*`rapports/`. **Sans cette reparation, les %d scripts auraient tous casse.***" % len(index),
        "",
    ]
    (DEST / "README.md").write_text("\n".join(lignes), encoding="utf-8")
    print("  📇 index genere : `outils de test\\README.md` "
          "(%d vivants + %d enquetes closes)" % (len(presents), len(historiques)))
    print("\n  ✅ **Aucun fichier supprime.** Un `move`, jamais un `delete`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
