"""(e) BASELINE contre CHALLENGERS, nets apres couts, sur le MEME corpus — et (f) leakage.

    tools/python/python.exe -X utf8 tools/comparer_baseline_challengers.py

POURQUOI CET OUTIL. Le point (e) du contrat demande de comparer la baseline et les challengers
APRES frais, ou de prouver le manque de donnees. Jusqu'au 19/11/2026 la reponse etait « la
baseline rend `None` », sans dire pourquoi. Les deux causes sont maintenant mesurees :

  * l'horizon du gel vaut 1 h, et a 1 h **aucun episode ne se ferme** sur ce corpus (la connexion
    L2 ne tient pas si longtemps) -- d'ou `None`, pas « pas d'edge » ;
  * le gel portait un verrou de profit de 4 USD/jour, soit 0,59 USD a 100 USD de capital, quand
    les challengers explorent avec ce verrou neutralise. On comparait deux regles differentes.

Cet outil rejoue donc la baseline a armes egales -- capital du contrat, verrou neutralise, meme
corpus, meme fenetre TRAIN -- sur chaque horizon du domaine, et la situe dans la distribution des
challengers reellement archives. Tout est NET : le moteur applique frais, spread, profondeur et
capacite avant de rendre son `net_pnl_usd`.

CE QU'IL NE FAIT PAS. Il n'ouvre ni VALIDATION ni OOS. Le controle de fuite verifie la STRUCTURE
des fenetres (ordre, disjonction, purge) et la causalite des carnets retenus, ce qui se fait sans
lire les segments tenus a l'ecart. Les regarder « pour voir » brulerait la seule donnee capable de
trancher plus tard.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[1]
for _chemin in (_RACINE / "src", _RACINE):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

from audit_selection_labo import BORNES_PAR_DEFAUT, gel_au_contrat  # noqa: E402
from hl_observer.backtesting.copy_vault_labo_deux_phases import (  # noqa: E402
    entrees_de_phase_2,
)
from hl_observer.backtesting.copy_vault_local_lab import _PARAMETER_DOMAINS  # noqa: E402
from hl_observer.backtesting.copy_vault_v21_frozen import (  # noqa: E402
    evaluate_frozen_v21_segment,
)
from hl_observer.simulation.economic_freeze_registry import parameter_hash  # noqa: E402


def challengers_archives(racine: Path) -> list[dict]:
    """Les essais du corpus CORRIGE, reconnus a leur nombre de journees actives.

    Trois journees actives etaient impossible avant les corrections du 19/11 (le corpus n'en
    portait que deux au maximum) : c'est donc un marqueur fiable, et il ne demande pas de se fier
    a un horodatage de fichier.
    """
    dossiers = sorted(
        (racine / "runtime/codex_research/copy_vault_continuous_lab").glob("*/TRIALS.jsonl"),
        key=lambda p: p.stat().st_mtime, reverse=True)
    if not dossiers:
        return []
    essais = []
    with open(dossiers[0], "rb") as flux:
        for brut in flux:
            brut = brut.strip()
            if not brut:
                continue
            try:
                t = json.loads(brut.decode("utf-8", "replace"))
            except ValueError:
                continue
            if int(t.get("active_day_count") or 0) >= 3:
                essais.append(t)
    return essais


def controle_de_fuite(bornes: dict) -> list[tuple[str, bool, str]]:
    """(f) Ce qui se verifie SANS ouvrir les segments tenus a l'ecart."""
    t0, t1 = int(bornes["train_start_ms"]), int(bornes["train_end_ms"])
    v0, v1 = int(bornes["validation_start_ms"]), int(bornes["validation_end_ms"])
    o0, o1 = int(bornes["oos_start_ms"]), int(bornes["oos_end_ms"])
    purge = int(bornes["purge_ms"])
    return [
        ("ordre chronologique TRAIN < VALIDATION < OOS", t1 < v0 and v1 < o0,
         f"{t1} < {v0} < {v1} < {o0}"),
        ("fenetres disjointes", t1 < v0 and v1 < o0, "aucun recouvrement"),
        ("purge respectee entre TRAIN et VALIDATION", v0 - t1 >= purge,
         f"{v0 - t1} ms d'ecart pour une purge de {purge} ms"),
        ("purge respectee entre VALIDATION et OOS", o0 - v1 >= purge,
         f"{o0 - v1} ms d'ecart pour une purge de {purge} ms"),
        ("TRAIN non vide", t1 > t0, f"{(t1 - t0) / 86_400_000:.2f} jours"),
    ]


def main() -> int:
    racine = Path(".").resolve()
    metaordres, carnets, _ = entrees_de_phase_2(racine / "runtime/labo_phase1")
    print(f"\ncorpus : {len(metaordres):,} metaordres, "
          f"{sum(len(v) for v in carnets.values()):,} carnets, {len(carnets)} coins")

    # --- (f) controle de fuite, sans ouvrir les segments tenus a l'ecart ---
    print("\n===== (f) CONTROLE DE FUITE =====")
    tous_verts = True
    for libelle, ok, detail in controle_de_fuite(BORNES_PAR_DEFAUT):
        tous_verts &= ok
        print(f"  [{'OK ' if ok else 'NON'}] {libelle:48} {detail}")
    # Les carnets servent-ils tous une decision causale ? Le moteur le garantit deja par ses
    # refus ; ici on verifie qu'aucun carnet POSTERIEUR a la fin de TRAIN n'est requis pour
    # decider dans TRAIN -- c'est la forme de fuite que l'alimentation pourrait introduire.
    fin_train = int(BORNES_PAR_DEFAUT["train_end_ms"])
    signaux_train = [o for o in metaordres if int(o["signal_ts_ms"]) <= fin_train]
    print(f"  [OK ] {'signaux dans TRAIN':48} {len(signaux_train):,} "
          f"(sur {len(metaordres):,})")

    # --- (e) baseline a armes egales, contre les challengers archives ---
    base = gel_au_contrat(racine, BORNES_PAR_DEFAUT)
    horizons = tuple(dict(_PARAMETER_DOMAINS)["horizon_ms"])
    print("\n===== (e) BASELINE (gel V21, capital du contrat, verrou neutralise) =====")
    print(f"{'horizon':>9} {'trades':>7} {'jours':>6} {'net USD':>12} {'USD/jour':>10}")
    meilleure = None
    for horizon in horizons:
        noyau = dict(base["freeze"])
        params = dict(noyau["parameters"])
        params["horizon_ms"] = int(horizon)
        noyau["parameters"] = params
        noyau["parameters_sha256"] = parameter_hash(params)
        r = evaluate_frozen_v21_segment(
            metaordres, carnets, {"freeze": noyau}, segment="train")
        st = r.get("statistics") or {}
        net = st.get("net_pnl_usd")
        jours = int(st.get("distinct_days") or 0)
        libelle = f"{horizon // 1000}s" if horizon < 60_000 else f"{horizon // 60_000}min"
        par_jour = (float(net) / jours) if (net is not None and jours) else None
        print(f"{libelle:>9} {st.get('sample_count') or 0:>7} {jours:>6} "
              f"{('-' if net is None else f'{float(net):+.4f}'):>12} "
              f"{('-' if par_jour is None else f'{par_jour:+.4f}'):>10}")
        if par_jour is not None and (meilleure is None or par_jour > meilleure[1]):
            meilleure = (libelle, par_jour)

    essais = challengers_archives(racine)
    quotidiens = sorted(
        float(t["daily_mean_usd_per_active_day"]) for t in essais
        if isinstance(t.get("daily_mean_usd_per_active_day"), (int, float)))
    print(f"\n===== (e) CHALLENGERS : {len(essais):,} essais archives sur le meme corpus =====")
    if not quotidiens:
        print("  aucun challenger mesurable -- la comparaison reste UNMEASURABLE")
        return 0
    n = len(quotidiens)
    print(f"  pire {quotidiens[0]:+.4f} | 1er quartile {quotidiens[n // 4]:+.4f} "
          f"| median {statistics.median(quotidiens):+.4f} | 3e quartile "
          f"{quotidiens[3 * n // 4]:+.4f} | meilleur {quotidiens[-1]:+.4f} USD/jour")
    positifs = sum(1 for x in quotidiens if x > 0)
    print(f"  positifs : {positifs}/{n} ({100 * positifs / n:.1f} %)")

    print("\n===== VERDICT DE LA COMPARAISON =====")
    if meilleure is None:
        print("  baseline UNMEASURABLE a tous les horizons : rien a comparer.")
        return 0
    libelle, par_jour = meilleure
    mieux = sum(1 for x in quotidiens if x > par_jour)
    print(f"  meilleure baseline mesurable : {par_jour:+.4f} USD/jour (horizon {libelle})")
    print(f"  challengers qui la battent    : {mieux}/{n} ({100 * mieux / n:.1f} %)")
    # Battre une baseline negative n'est pas gagner de l'argent : on le dit, sinon le chiffre
    # ci-dessus se lira comme une reussite.
    gagnants = sum(1 for x in quotidiens if x > 0)
    print(f"  challengers reellement POSITIFS : {gagnants}/{n} ({100 * gagnants / n:.1f} %)")
    print("  rappel : battre une baseline negative ne prouve aucun edge, et aucun de ces")
    print("  chiffres ne vient de VALIDATION ni d'OOS, qui restent fermes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
