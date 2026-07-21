import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hl_observer.decision_engine.noyau_unique import Contexte, decider
from hl_observer.edge.carry_edge_source import edge_de_carry_bps
e, m, p = edge_de_carry_bps("PURR", "CARRY")
print("edge_de_carry_bps('PURR','CARRY') -> edge=%s motif=%s" % (e, m))
print("  fichier teste :", p.get("fichier") or p.get("source"))
d = decider(Contexte(strategie="CARRY", coin="PURR", direction="SHORT", notional_usd=500.0))
print("\ndecider() -> %s / %s" % (d.verdict, d.raison))
print("  edge_source dans la preuve :", d.preuve.get("edge_source"))
