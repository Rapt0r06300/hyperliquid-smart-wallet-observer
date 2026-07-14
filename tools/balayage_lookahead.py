"""#562 / H-157 — LE BALAYAGE DIFFÉRENTIEL. **Il ne lit pas le code. Il ne peut pas être trompé.**

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI CE N'EST PAS #563 (le grep), MAIS #562 (le différentiel)
═══════════════════════════════════════════════════════════════════════════════════════════════

#563 proposait : *« GREP `.mean()` / `.std()` SANS `rolling()` = lookahead »*.

**J'ai construit ce detecteur. Il a rendu 0 signalement sur 1 233 fichiers.**
Et il ne retrouvait meme pas `garch11_variance` -- **le lookahead qu'on CONNAIT DEJA.**

    ***La raison : #563 decrit un idiome PANDAS. Notre code est du Python PUR.***
    Pas un seul `.mean()`. Les agregats s'ecrivent `sum(xs) / len(xs)`.

*L'outil qui ment, encore. Attrape uniquement parce que je l'ai teste sur le bug connu :*
***s'il ne retrouve pas le bug qu'on connait deja, il ne trouvera jamais ceux qu'on ignore.***

═══════════════════════════════════════════════════════════════════════════════════════════════
LE TEST DIFFERENTIEL — la seule arme qui ne peut pas etre trompee
═══════════════════════════════════════════════════════════════════════════════════════════════

Pour chaque fonction `f(serie) -> serie` du projet :

    complet  = f(serie)              # la serie ENTIERE
    tronque  = f(serie[:i+1])        # la serie coupee a l'instant i

    si  complet[i] != tronque[i]  ->  **LA FONCTION LIT LE FUTUR.**

Elle ne lit ni docstring, ni commentaire, ni nom de variable. **Elle appelle, et elle compare.**
Aucun idiome ne peut lui echapper. C'est exactement ce test qui a confondu `garch11_variance`.

⚠️ HONNETETE : ce balayage ne teste que les fonctions **PURES** de forme `sequence -> sequence`.
Une fonction qui prend un objet, un DataFrame ou plusieurs series n'est PAS couverte.
**On dit ce qu'on n'a pas teste.**

Aucun ordre reel. Aucun effet de bord (les modules sont importes en lecture).
"""
from __future__ import annotations

import importlib
import inspect
import json
import math
import pkgutil
import random
import sys
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.testing.lookahead_detector import lit_le_futur  # noqa: E402

# Une serie realiste : des rendements, avec un CHOC au milieu (c'est la que le lookahead se voit).
random.seed(20260713)
SERIE = [random.gauss(0.0, 0.01) for _ in range(40)]
SERIE[25] = 0.15          # le choc : une fonction qui lit le futur le « sait » AVANT
INSTANT = 12              # on juge bien AVANT le choc

# Modules a ne pas importer (effets de bord reseau / lourds).
EXCLUS = ("cli", "ui", "realtime", "collection", "hyperliquid", "__main__", "agent")

SORTIE = RACINE / "data" / "reports" / "lookahead_balayage.json"


def _candidates() -> list[tuple[str, str, Any]]:
    """Toutes les fonctions publiques `(sequence, ...) -> ...` des paquets purs."""
    out: list[tuple[str, str, Any]] = []
    base = RACINE / "src" / "hl_observer"
    for m in pkgutil.walk_packages([str(base)], prefix="hl_observer."):
        court = m.name.split(".")[1] if m.name.count(".") >= 1 else ""
        if court in EXCLUS:
            continue
        try:
            mod = importlib.import_module(m.name)
        except Exception:  # noqa: BLE001 -- un module qui ne s'importe pas n'est pas testable
            continue
        for nom, fn in vars(mod).items():
            if nom.startswith("_") or not inspect.isfunction(fn):
                continue
            if getattr(fn, "__module__", "") != m.name:
                continue
            try:
                sig = inspect.signature(fn)
            except (TypeError, ValueError):
                continue
            params = [p for p in sig.parameters.values()
                      if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
            # une seule entree positionnelle obligatoire -> candidate a `f(serie)`
            obligatoires = [p for p in params if p.default is inspect.Parameter.empty]
            if len(obligatoires) == 1:
                out.append((m.name, nom, fn))
    return out


def main() -> int:
    print("=" * 96)
    print("  #562 -- BALAYAGE DIFFERENTIEL DU LOOKAHEAD")
    print("  Il n'ouvre pas le code. Il appelle, il tronque, il compare.")
    print("=" * 96)

    cands = _candidates()
    print("\n  fonctions candidates (1 entree positionnelle) : %d" % len(cands))

    coupables: list[dict[str, Any]] = []
    testees = 0
    non_testables = 0

    for module, nom, fn in cands:
        try:
            res = lit_le_futur(fn, SERIE, i=INSTANT)
        except Exception:  # noqa: BLE001 -- signature incompatible : on le DIT, on ne l'ignore pas
            non_testables += 1
            continue
        testees += 1
        if res:
            coupables.append({"module": module, "fonction": nom})
            print("  🔴 LIT LE FUTUR : %s.%s()" % (module, nom))

    print("\n" + "-" * 96)
    print("  testees        : %d" % testees)
    print("  non testables  : %d  (signature incompatible -- **NON couvertes, on le dit**)"
          % non_testables)
    print("  🔴 COUPABLES   : %d" % len(coupables))
    print("-" * 96)

    # 🔑 LE CONTROLE DE L'OUTIL LUI-MEME : retrouve-t-il le bug CONNU ?
    print("\n  === CONTROLE : l'outil retrouve-t-il le bug qu'on connait deja ? ===")
    try:
        from hl_observer.backtesting.regime_detection import (
            garch11_variance,
            garch11_variance_causale,
        )
        bug = lit_le_futur(garch11_variance, SERIE, i=INSTANT)
        sain = lit_le_futur(garch11_variance_causale, SERIE, i=INSTANT)
        print("    garch11_variance          -> lit le futur : %s   %s"
              % (bug, "✅ ATTRAPE" if bug else "❌ **L'OUTIL EST CASSE**"))
        print("    garch11_variance_causale  -> lit le futur : %s   %s"
              % (sain, "✅ correct" if not sain else "❌ **FAUX POSITIF**"))
        if not bug:
            print("\n  🚩 L'OUTIL NE RETROUVE PAS LE BUG CONNU. **Son verdict ne vaut RIEN.**")
            print("     *S'il ne retrouve pas ce qu'on sait, il ne trouvera pas ce qu'on ignore.*")
            return 2
    except Exception as exc:  # noqa: BLE001
        print("    controle IMPOSSIBLE : %s" % exc)
        return 2

    print("\n  ✅ L'outil retrouve le bug connu ET innocente sa version causale.")
    print("     Son verdict sur le reste du code a donc une valeur.")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps({
        "testees": testees, "non_testables": non_testables,
        "coupables": coupables,
        "avertissement": (
            "Seules les fonctions PURES `(sequence) -> sequence` sont couvertes. "
            "Les fonctions a plusieurs entrees, objets ou DataFrames ne le sont PAS."
        ),
        "real_execution": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n  -> %s" % SORTIE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
