"""Le gel V21 fixe l'horizon a 1 h. Les episodes tiennent-ils dans un horizon plus court ?

    tools/python/python.exe -X utf8 tools/balayage_horizons_labo.py

Mesure du 19/11/2026 : 209 des 353 candidats OOS sont refuses en STALE_OR_MISSING_EXIT_BOOK.
Avec un horizon d'une heure, l'episode doit tenir dans UNE connexion L2 -- or une lane vit vingt
a vingt-cinq minutes. Le labo cherche parmi huit horizons, de 30 s a 1 h : ce script les essaie
tous sur la politique gelee, pour savoir si le mur est l'horizon ou la donnee.

CE QU'IL A TROUVE LE 19/11/2026, et qui n'etait visible nulle part : a 60 minutes -- l'horizon du
gel, donc celui de la BASELINE -- **zero trade sur les trois segments**. A 30 minutes et moins,
des episodes se ferment enfin : 12 a 37 trades sur TRAIN. La baseline etait structurellement non
mesurable sur ces donnees, et c'est pour cela qu'elle rendait `None` sans jamais dire pourquoi.

ATTENTION A L'USAGE. Ce balayage affiche aussi VALIDATION et OOS, parce qu'un refus dominant se
compare mal sur un seul segment. Mais il est DESCRIPTIF : aucun choix de parametre ne doit se
faire sur ces colonnes-la, sinon c'est du tuning sur l'OOS -- exactement ce que le protocole
anti-illusion interdit. Le seul segment qui peut guider une decision est TRAIN.
"""
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "tools")
from pathlib import Path

from audit_selection_labo import BORNES_PAR_DEFAUT, gel_au_contrat

from hl_observer.backtesting.copy_vault_labo_deux_phases import entrees_de_phase_2
from hl_observer.backtesting.copy_vault_local_lab import _PARAMETER_DOMAINS
from hl_observer.backtesting.copy_vault_v21_frozen import evaluate_frozen_v21_segment
from hl_observer.simulation.economic_freeze_registry import parameter_hash

HORIZONS = tuple(dict(_PARAMETER_DOMAINS)["horizon_ms"])
metaordres, carnets, _ = entrees_de_phase_2("runtime/labo_phase1")
print(f"corpus : {len(metaordres):,} metaordres, {sum(len(v) for v in carnets.values()):,} carnets")
base = gel_au_contrat(Path("."), BORNES_PAR_DEFAUT)

print()
print(f"{'horizon':>10} {'segment':12} {'cand.':>6} {'TRADES':>7} {'jours':>6} {'net USD':>12} refus dominant")
for horizon in HORIZONS:
    noyau = dict(base["freeze"])
    params = dict(noyau["parameters"])
    params["horizon_ms"] = int(horizon)
    noyau["parameters"] = params
    noyau["parameters_sha256"] = parameter_hash(params)
    gel = {"freeze": noyau}
    for segment in ("train", "validation", "oos"):
        r = evaluate_frozen_v21_segment(metaordres, carnets, gel, segment=segment)
        st = r.get("statistics") or {}
        ra = {k: v for k, v in (r.get("replay_audit") or {}).items()
              if k.startswith("ACTUAL_PROVENANCE_REFUSAL_")}
        pire = max(ra.items(), key=lambda kv: kv[1])[0][26:] if ra else "-"
        libelle = f"{horizon//1000}s" if horizon < 60000 else f"{horizon//60000}min"
        print(f"{libelle:>10} {segment:12} {r['candidate_count']:>6} "
              f"{st.get('sample_count') or 0:>7} {st.get('distinct_days') or 0:>6} "
              f"{str(st.get('net_pnl_usd')):>12} {pire[:46]}")
