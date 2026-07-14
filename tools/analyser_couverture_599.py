"""#599 — QUE VALENT LES 16 % DE LIGNES JAMAIS EXECUTEES ?

Un pourcentage de couverture ne dit RIEN d'utile tout seul. « 84 % » peut vouloir dire
« les 16 % restants sont du code mort inoffensif » ou « les 16 % restants sont le RiskEngine ».
Ce sont deux mondes.

Cet outil ne juge pas. Il TRIE, et il nomme :

  1. les modules a **0,00 %** -> jamais executes du tout (candidats code mort / non branches) ;
  2. les modules du **chemin de decision** (edge, risk, signals, paper_trading, copying,
     opportunities, funding, arbitrage) ranges par lignes manquantes -> le vrai risque ;
  3. le reste (ui, cli, outils d'analyse) -> mesure, mais moins critique.

⚠️ HONNETETE SUR MA PROPRE HYPOTHESE (2026-07-13)
J'ai d'abord suppose que la mesure de 14:07 (83,83 %) etait FAUSSE, calculee sur une suite
tronquee par le Ctrl-C fantome (#600). **C'etait faux.** Relancee sur la suite complete
(3 526 tests), elle rend exactement le meme 83,83 %. Le Ctrl-C tuait le `.cmd` APRES pytest,
pas pytest. La mesure etait bonne ; c'est mon hypothese qui ne l'etait pas.
-> Les modules a 0 % sont donc **reellement** a 0 %, et cette liste est a prendre au serieux.

Lecture seule. Aucun ordre.
"""

from __future__ import annotations

import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
COVERAGE = RACINE / "coverage.json"

CHEMIN_DE_DECISION = (
    "edge", "risk", "signals", "paper_trading", "copying",
    "opportunities", "funding", "arbitrage", "decision",
)


def _charger() -> dict:
    return json.loads(COVERAGE.read_text(encoding="utf-8"))


def main() -> int:
    if not COVERAGE.exists():
        print("coverage.json absent -> lancer d'abord `python tools/couverture_de_lignes.py`.")
        return 2
    d = _charger()
    t = d["totals"]
    print("=" * 86)
    print("  #599 -- OU VIVENT LES %d LIGNES JAMAIS EXECUTEES (sur %d) ?"
          % (t["missing_lines"], t["num_statements"]))
    print("  couverture globale : %.2f %%" % t["percent_covered"])
    print("=" * 86)

    zero, decision, reste = [], [], []
    for p, v in d["files"].items():
        q = p.replace("\\", "/")
        if not q.startswith("src/hl_observer/"):
            continue
        s = v["summary"]
        if s["num_statements"] == 0:
            continue
        paquet = q.split("/")[2]
        ligne = (s["missing_lines"], s["percent_covered"], q, s["num_statements"])
        if s["percent_covered"] == 0.0:
            zero.append(ligne)
        elif paquet in CHEMIN_DE_DECISION and s["missing_lines"] > 0:
            decision.append(ligne)
        elif s["missing_lines"] > 0:
            reste.append(ligne)

    zero.sort(reverse=True)
    decision.sort(reverse=True)
    reste.sort(reverse=True)

    print("\n### 1. JAMAIS EXECUTES DU TOUT (0,00 %%) -- %d modules, %d lignes"
          % (len(zero), sum(z[0] for z in zero)))
    print("    Un module a 0 %% n'est pas « peu teste ». Il n'a JAMAIS tourne, pas meme a l'import.")
    for m, _pc, q, n in zero:
        print("    %5d lignes  %s" % (m, q))

    print("\n### 2. CHEMIN DE DECISION -- %d modules, %d lignes manquantes"
          % (len(decision), sum(x[0] for x in decision)))
    print("    C'est ICI que 16 %% non executes fait mal : une branche de refus jamais parcourue")
    print("    est un refus dont on ne sait pas s'il fonctionne.")
    for m, pc, q, n in decision[:20]:
        print("    %5d lignes  (%5.1f %% couvert)  %s" % (m, pc, q))

    print("\n### 3. LE RESTE (ui, cli, outils) -- %d modules, %d lignes manquantes"
          % (len(reste), sum(x[0] for x in reste)))
    for m, pc, q, n in reste[:10]:
        print("    %5d lignes  (%5.1f %% couvert)  %s" % (m, pc, q))

    rapport = RACINE / "data" / "reports" / "couverture_599.json"
    rapport.parent.mkdir(parents=True, exist_ok=True)
    rapport.write_text(
        json.dumps(
            {
                "pct_lignes": t["percent_covered"],
                "lignes_manquantes": t["missing_lines"],
                "modules_a_zero": [{"module": q, "lignes": n} for _m, _pc, q, n in zero],
                "chemin_de_decision": [
                    {"module": q, "manquantes": m, "pct": pc} for m, pc, q, _n in decision
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print("\n-> %s" % rapport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
