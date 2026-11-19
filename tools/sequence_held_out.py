"""(f) La sequence TRAIN -> VALIDATION -> OOS, ouverte DANS L'ORDRE et pas autrement.

    tools/python/python.exe -X utf8 tools/sequence_held_out.py

LA REGLE, qui est aussi la raison d'etre de cet outil : « Failure of an earlier gate keeps later
data unopened ». On n'ouvre VALIDATION que si TRAIN passe, et OOS que si VALIDATION passe. Un
coup d'oeil « pour voir » brule la seule donnee capable de trancher plus tard, et il n'existe
aucun moyen de la reconstituer.

CE QUI REND CET OUTIL POSSIBLE AUJOURD'HUI. Jusqu'au 19/11/2026 la porte `FUNDING_PNL_UNMEASURABLE`
refusait **100 % des candidats** : son seul statut acceptant etait « aucun reglement de funding
traverse », impossible avec un reglement horaire et des horizons allant jusqu'a une heure. Le
statut `MEASURED` etait accepte ailleurs dans le moteur mais aucune ligne ne le produisait. La
mesure existe desormais (`copy_vault_funding_realise`, branchee dans l'evaluateur via
`taux_funding_par_coin`), et cette porte peut donc etre franchie par un candidat qui paie
reellement son portage.

Les taux viennent de `REST_FUNDING_HISTORY` et portent `causal_forward_eligible: False` : ils ne
servent jamais a DECIDER une entree, seulement a chiffrer apres coup ce qu'un episode deja clos a
paye. C'est de la comptabilite de cout, au meme titre que les frais.
"""

from __future__ import annotations

import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[1]
for _chemin in (_RACINE / "src", _RACINE):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

from audit_selection_labo import BORNES_PAR_DEFAUT, gel_au_contrat  # noqa: E402

from hl_observer.backtesting import copy_vault_funding_realise as fr  # noqa: E402
from hl_observer.backtesting.copy_vault_labo_deux_phases import (  # noqa: E402
    entrees_de_phase_2,
)
from hl_observer.backtesting.copy_vault_local_lab import _PARAMETER_DOMAINS  # noqa: E402
from hl_observer.backtesting.copy_vault_v21_frozen import (  # noqa: E402
    evaluate_frozen_v21_segment,
)
from hl_observer.simulation.economic_freeze_registry import parameter_hash  # noqa: E402

#: Combien de candidats archives on reevalue, les meilleurs d'abord par borne basse corrigee.
COMBIEN_DE_CANDIDATS = 4


def candidats_archives(racine: Path, combien: int = COMBIEN_DE_CANDIDATS) -> list[dict]:
    """Les meilleurs candidats archives, avec leurs VINGT parametres, relus tels quels.

    PIEGE EVITE (19/11/2026) : une premiere version de cet outil ne recopiait que trois
    parametres -- horizon, notionnel minimum, desequilibre minimum -- et laissait les dix-sept
    autres a la valeur du gel. Les resultats obtenus (-0,44 et -2,38 USD) n'etaient donc PAS ceux
    des candidats archives (+1,48 et +0,68 USD/jour) : c'etait le gel avec trois reglages changes.
    Un candidat se rejoue avec l'intégralité de ses parametres, ou pas du tout.
    """
    import json

    fichiers = sorted(
        (racine / "runtime/codex_research/copy_vault_continuous_lab").glob("*/TRIALS.jsonl"),
        key=lambda x: x.stat().st_mtime, reverse=True)
    if not fichiers:
        return []
    retenus = []
    with open(fichiers[0], "rb") as flux:
        for brut in flux:
            brut = brut.strip()
            if not brut:
                continue
            try:
                t = json.loads(brut.decode("utf-8", "replace"))
            except ValueError:
                continue
            lcb = t.get("daily_lcb_usd_per_active_day")
            if int(t.get("active_day_count") or 0) >= 3 and isinstance(lcb, (int, float)):
                retenus.append((float(lcb), t))
    retenus.sort(key=lambda kv: -kv[0])
    sortie = []
    for lcb, t in retenus[:combien]:
        params = dict(t.get("parameters") or {})
        params["nom"] = (f"archive n{t.get('trial_number')} · LCB {lcb:+.4f} · "
                         f"TRAIN annonce {t.get('daily_mean_usd_per_active_day'):+.4f} USD/j")
        sortie.append(params)
    return sortie


UTC_JOUR_MS = 86_400_000


def bornes_alignees_utc(bornes: dict) -> dict:
    """Les memes fenetres, mais alignees sur les frontieres de journee UTC.

    DEFAUT MESURE LE 19/11/2026. Les bornes declarent `split_unit: "UTC_DAY"` et ne sont PAS
    alignees sur des journees UTC : TRAIN finit le 15/11 a 22:58. Or `_evaluate_segment` ne
    retient comme « journee complete » que celles entierement contenues dans le segment -- le
    15/11 en est donc exclu, pendant que des trades s'y ferment. D'ou
    `TRADE_OUTSIDE_COMPLETE_UTC_DAY_COVERAGE`, donc `CALENDAR_PNL_UNMEASURABLE`, donc un recu de
    funding `SEGMENT_COVERAGE_UNMEASURABLE` : **deux portes sur trois tombaient a cause d'un
    desalignement de 62 minutes**.

    On aligne vers l'INTERIEUR : debut remonte au jour suivant si besoin, fin ramenee a la
    derniere journee pleinement contenue. Un alignement vers l'exterieur inventerait de
    l'observation qu'on n'a pas.
    """
    alignees = dict(bornes)
    for prefixe in ("train", "validation", "oos"):
        d, f = int(bornes[f"{prefixe}_start_ms"]), int(bornes[f"{prefixe}_end_ms"])
        debut = ((d + UTC_JOUR_MS - 1) // UTC_JOUR_MS) * UTC_JOUR_MS
        fin = ((f + 1) // UTC_JOUR_MS) * UTC_JOUR_MS - 1
        if fin > debut:
            alignees[f"{prefixe}_start_ms"], alignees[f"{prefixe}_end_ms"] = debut, fin
    return alignees


def journees_utc_completes(racine: Path) -> list[int]:
    """Les debuts de journees UTC que la collecte couvre de bout en bout.

    DERNIER VERROU LEVE (19/11/2026). `summarize_complete_utc_days` rend
    `UNMEASURABLE / COMPLETE_UTC_DAY_COVERAGE_MISSING` quand on ne lui declare pas ces journees,
    et ce refus se propage : `CALENDAR_PNL_UNMEASURABLE`, puis le recu de funding bascule en
    `SEGMENT_COVERAGE_UNMEASURABLE` -- donc `FUNDING_PNL_UNMEASURABLE` aussi. Deux portes sur
    trois tombaient pour une liste jamais calculee.

    Elle ne s'invente pas : on l'etablit a partir des fenetres des tranches PREPAREES, qui disent
    exactement ce que la phase 1 a lu. Une journee ne compte que si l'union de ses tranches la
    couvre sans trou -- une couverture partielle declaree complete gonflerait une moyenne
    journaliere en la divisant par des journees a moitie observees.
    """
    import json

    fenetres = []
    for manifeste in sorted((racine / "runtime/labo_phase1").glob("*/MANIFESTE.json")):
        try:
            m = json.loads(manifeste.read_text(encoding="utf-8"))
            fenetres.append((int(m["tranche_debut_ms"]), int(m["tranche_fin_ms"])))
        except (OSError, ValueError, KeyError):
            continue
    if not fenetres:
        return []
    fenetres.sort()
    fusionnees = [list(fenetres[0])]
    for debut, fin in fenetres[1:]:
        # +1 ms : deux tranches jointives se touchent a la milliseconde pres.
        if debut <= fusionnees[-1][1] + 1:
            fusionnees[-1][1] = max(fusionnees[-1][1], fin)
        else:
            fusionnees.append([debut, fin])
    premier = (fusionnees[0][0] // UTC_JOUR_MS) * UTC_JOUR_MS
    dernier = (fusionnees[-1][1] // UTC_JOUR_MS) * UTC_JOUR_MS
    completes = []
    jour = premier
    while jour <= dernier:
        if any(d <= jour and jour + UTC_JOUR_MS - 1 <= f for d, f in fusionnees):
            completes.append(jour)
        jour += UTC_JOUR_MS
    return completes


def gel_du_candidat(racine: Path, surcharges: dict, bornes: dict | None = None) -> dict:
    base = gel_au_contrat(racine, bornes or BORNES_PAR_DEFAUT)
    noyau = dict(base["freeze"])
    params = dict(noyau["parameters"])
    for cle, valeur in surcharges.items():
        if cle != "nom":
            params[cle] = valeur
    noyau["parameters"] = params
    noyau["parameters_sha256"] = parameter_hash(params)
    return {"freeze": noyau}


def evaluer(metaordres, carnets, gel, segment, taux, journees=None):
    r = evaluate_frozen_v21_segment(
        metaordres, carnets, gel, segment=segment, taux_funding_par_coin=taux,
        complete_utc_day_starts_ms=journees)
    st = r.get("statistics") or {}
    recu = r.get("funding_receipt") or {}
    return {
        "eligible": r.get("eligible") is True,
        "refus": list(r.get("reasons") or []),
        "trades": st.get("sample_count") or 0,
        "jours": st.get("distinct_days") or 0,
        "net": st.get("net_pnl_usd"),
        "funding_status": recu.get("status"),
        "funding_usd": recu.get("carry_pnl_usd"),
        "funding_raison": recu.get("reason"),
    }


def rendre(nom: str, segment: str, v: dict) -> None:
    net = "-" if v["net"] is None else f"{float(v['net']):+.4f}"
    carry = "-" if v["funding_usd"] is None else f"{float(v['funding_usd']):+.4f}"
    print(f"    {segment:11} trades {v['trades']:>4} · jours {v['jours']} · net {net:>10} USD "
          f"· funding {v['funding_status']} {carry:>9}")
    if v["funding_raison"]:
        print(f"                raison du funding : {v['funding_raison']}")
    print(f"                {'ELIGIBLE' if v['eligible'] else 'refus (' + str(len(v['refus'])) + ')'}"
          f" : {', '.join(v['refus'][:4]) or '-'}")


def main() -> int:
    racine = Path(".").resolve()
    metaordres, carnets, _ = entrees_de_phase_2(racine / "runtime/labo_phase1")
    print(f"corpus : {len(metaordres):,} metaordres, "
          f"{sum(len(v) for v in carnets.values()):,} carnets")

    # Les taux couvrent les TROIS fenetres : il faut pouvoir chiffrer un segment avant de savoir
    # s'il sera ouvert, sinon la lecture elle-meme deviendrait un signal.
    taux, audit = fr.taux_du_coffre(
        racine, coins=None,
        debut_ms=int(BORNES_PAR_DEFAUT["train_start_ms"]) - 3_600_000,
        fin_ms=int(BORNES_PAR_DEFAUT["oos_end_ms"]) + 3_600_000)
    print(f"funding : {audit.get('reglements_gardes', 0):,} reglements sur "
          f"{audit.get('coins', 0)} coins · provenance {audit.get('provenance')}")

    BORNES = bornes_alignees_utc(BORNES_PAR_DEFAUT)
    import datetime as _d
    for _p in ("train", "validation", "oos"):
        a, b = BORNES_PAR_DEFAUT[f'{_p}_end_ms'], BORNES[f'{_p}_end_ms']
        if a != b:
            print(f"  {_p:11} fin alignee : "
                  f"{_d.datetime.fromtimestamp(a/1000, _d.timezone.utc):%m-%d %H:%M} "
                  f"-> {_d.datetime.fromtimestamp(b/1000, _d.timezone.utc):%m-%d %H:%M}")
    journees = journees_utc_completes(racine)
    import datetime as _dt
    libelles = [_dt.datetime.fromtimestamp(j / 1000, _dt.timezone.utc).strftime("%m-%d")
                for j in journees]
    print(f"journees UTC completes declarees : {len(journees)} ({', '.join(libelles)})")

    horizons = tuple(dict(_PARAMETER_DOMAINS)["horizon_ms"])
    essais = [
        {"nom": f"baseline V21 (horizon {h // 60_000 or h // 1000}"
                f"{'min' if h >= 60_000 else 's'})", "horizon_ms": h}
        for h in horizons
    ] + candidats_archives(racine)

    ouvertures = {"validation": 0, "oos": 0}
    for surcharges in essais:
        nom = surcharges["nom"]
        gel = gel_du_candidat(racine, surcharges, BORNES)
        print(f"\n  === {nom} ===")
        train = evaluer(metaordres, carnets, gel, "train", taux, journees)
        rendre(nom, "TRAIN", train)
        if not train["eligible"]:
            print("                VALIDATION reste FERMEE (la porte amont n'est pas passee)")
            continue
        ouvertures["validation"] += 1
        validation = evaluer(metaordres, carnets, gel, "validation", taux, journees)
        rendre(nom, "VALIDATION", validation)
        if not validation["eligible"]:
            print("                OOS reste FERME (la porte amont n'est pas passee)")
            continue
        ouvertures["oos"] += 1
        rendre(nom, "OOS", evaluer(metaordres, carnets, gel, "oos", taux, journees))

    print("\n===== VERDICT (f) =====")
    print(f"  VALIDATION ouverte pour {ouvertures['validation']} candidat(s), "
          f"OOS pour {ouvertures['oos']}")
    if not ouvertures["validation"]:
        print("  Aucun candidat ne franchit TRAIN : les donnees tenues a l'ecart n'ont pas ete")
        print("  lues, et c'est le resultat -- pas une omission. Verdict : pas d'edge demontre.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
