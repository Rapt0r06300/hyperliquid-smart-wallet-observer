"""Genere un APERCU realiste du tableau de bord, sans reseau. Pour verifier l'affichage."""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

spec = importlib.util.spec_from_file_location("moiss", RACINE / "tools" / "moissonner_10h.py")
m = importlib.util.module_from_spec(spec)
sys.modules["moiss"] = m
spec.loader.exec_module(m)

from hl_observer.research.scan_resilience import Blessures  # noqa: E402

b = Blessures()
b.quotas_attendus = 3
b.secondes_attendues = 95.0
b.reessais = 2
b.non_lus = ["someorg/dead-repo", "other/private-thing"]

p = m.Progres(time.time() - 4200.0, 12.0, b)   # 1 h 10 ecoulees
p.canari = ("VIVANT - le pire des bons (60.6) depasse le meilleur des creux (-24.2) "
            "de 84.8 pts")
p.phase = "PHASE B - LIRE LES README (le graphe . le score DIFFERENTIEL)"
p.detail = "lecture : nkaz001/hftbacktest"
p.fait, p.total = 612, 1840
p.repos, p.par_code, p.petits, p.listes = 1840, 173, 921, 6
p.readmes = 612
p.commits = p.issues = p.constantes = 0
p.bandit_top = "funding-carry (4.2 repos/requete)"
p.note("cherche : queue position order book fill probability     +14 repo(s)")
p.note("LU  nkaz001/hftbacktest  apporte 3 concept(s) QU ON N A PAS : "
       "modele_de_file, kappa_intensite, impact_de_marche")
p.note("cherche : awesome quant                                    +187 repo(s)")

m.BATTEMENT = RACINE / "apercu_dashboard.txt"
p.ecrire()
print("Apercu ecrit dans apercu_dashboard.txt")
print((RACINE / "apercu_dashboard.txt").read_text(encoding="utf-8"))
