r"""Mesurer la VRAIE regle, pas celle que j'avais supposee. Puis : d'ou vient le trou de sortie ?

MON ERREUR, A CORRIGER AVANT TOUT. J'ai mesure « on ne garde que la connexion MAJORITAIRE »
et annonce 83 % de carnets ecartes, recuperables a 92,6 % en franchissant des raccords de
2,84 s. **Le code ne fait pas ca.** `une_seule_connexion_par_coin` trie les connexions par
DUREE et en garde PLUSIEURS par coin, tant que leurs intervalles ne se RECOUVRENT pas :

    « Ce que le replay exige n'est pas une connexion unique, c'est qu'un EPISODE n'en
      traverse pas deux. »

Et cette forme vient deja d'une refutation du 19/11/2026 : garder la plus longue globalement
laissait « un seul coin couvert le 13/11 et treize le 14 », 365 819 carnets tombant a 64 024.

Donc ce qui est ecarte l'est par **RECOUVREMENT** -- deux observateurs en meme temps -- et pas
par un raccord court. Franchir des raccords courts ne repondrait pas a la bonne question.

CE QUE CETTE MESURE ETABLIT, en rejouant la VRAIE regle :

1. combien de carnets elle garde et ecarte (a comparer au 62 % de l'audit du labo) ;
2. parmi les ecartes, combien le sont pour RECOUVREMENT ;
3. et la question qui decide : **aux instants ou le replay ne trouve pas de carnet frais sur
   la connexion retenue, un carnet existait-il sur une connexion ECARTEE ?** Si oui, le
   verdict est bloque par un choix d'observateur, pas par une absence d'observation.

LECTURE SEULE, bornee. Aucune modification du labo.
"""
import collections
import json
import pathlib
import sys

#: Range dans `tools/` le 22/11/2026 : `runtime/` est un dossier PROTEGE par le pousseur
#: (`_protected`), donc ce script ne voyageait pas et ne survivrait pas a un clone. Le
#: contrat exige de conserver les PREUVES : une mesure rejouable est une preuve.
#: La racine passe de `parents[2]` a `parents[1]` -- un cran de moins depuis `tools/`.
RACINE = pathlib.Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting.copy_vault_coffre_vers_labo import (  # noqa: E402
    une_seule_connexion_par_coin,
)

RUBANS = (
    "runtime/data/copy_vault_l2_tape.jsonl",
    "runtime/labo_tranches_20261121/workspace/runtime/data/copy_vault_l2_tape.jsonl",
)
BUDGET_OCTETS = 400 * 1024 * 1024
SEUIL_FRAICHEUR_MS = 30_000          # MAX_TARGET_LAG_MS : la fraicheur deja exigee


def trouver() -> pathlib.Path | None:
    for relatif in RUBANS:
        chemin = RACINE / relatif
        if chemin.is_file():
            return chemin
    return None


def lire(chemin: pathlib.Path, *, budget: int) -> dict[str, list[dict]]:
    par_coin: dict[str, list[dict]] = collections.defaultdict(list)
    octets = 0
    with chemin.open("rb") as flux:
        for brut in flux:
            octets += len(brut)
            if octets > budget:
                break
            try:
                ligne = json.loads(brut)
            except ValueError:
                continue
            if not isinstance(ligne, dict):
                continue
            coin, conn = ligne.get("coin"), ligne.get("connection_id")
            ts = ligne.get("received_at_ms") or ligne.get("ts_ms")
            if not isinstance(coin, str) or not isinstance(conn, str):
                continue
            if not isinstance(ts, int):
                continue
            par_coin[coin.upper()].append({"ts_ms": ts, "connection_id": conn})
    return dict(par_coin)


def plus_proche_avant(serie: list[int], instant: int) -> int | None:
    """Le dernier instant <= `instant`, par dichotomie. `None` s'il n'y en a pas."""
    import bisect

    index = bisect.bisect_right(serie, instant) - 1
    return serie[index] if index >= 0 else None


def main() -> int:
    flux = sys.stdout
    try:  # noqa: SIM105
        flux.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    chemin = trouver()
    if chemin is None:
        print("RUBAN L2 INTROUVABLE.")
        return 2
    print(f"  ruban : {chemin.name}  (borne a {BUDGET_OCTETS / 2 ** 20:.0f} Mo)")
    par_coin = lire(chemin, budget=BUDGET_OCTETS)
    total = sum(len(v) for v in par_coin.values())
    if not total:
        print("  AUCUN carnet lisible.")
        return 2

    gardes, audit = une_seule_connexion_par_coin(par_coin)
    gardes_n = sum(len(v) for v in gardes.values())
    print()
    print("  --- la VRAIE regle (intervalles non recouvrants, les plus longs d'abord) ---")
    print(f"  carnets lus    : {total:,} sur {len(par_coin)} coins")
    print(f"  GARDES         : {gardes_n:,}  ({100.0 * gardes_n / total:.1f} %)")
    print(f"  ECARTES        : {audit['ecartes_connexion_minoritaire']:,}"
          f"  ({100.0 * audit['ecartes_connexion_minoritaire'] / total:.1f} %)")
    print(f"  coins a connexion unique : {audit['coins_a_connexion_unique']}"
          f" / {audit['coins']}")

    # --- la question qui decide : un carnet ecarte aurait-il servi la ou il manque ?
    #
    # On simule le besoin du replay : a chaque instant de carnet GARDE, le replay cherche un
    # carnet a <= 30 s. On regarde les instants ou la serie GARDEE a un TROU plus long que la
    # fraicheur, et on demande si la serie COMPLETE en avait un dedans.
    trous_combles = 0
    trous_restants = 0
    exemples: list[dict] = []
    for coin, complets in par_coin.items():
        serie_gardee = sorted(int(x["ts_ms"]) for x in gardes.get(coin, ()))
        if len(serie_gardee) < 2:
            continue
        serie_complete = sorted(int(x["ts_ms"]) for x in complets)
        for i in range(1, len(serie_gardee)):
            trou = serie_gardee[i] - serie_gardee[i - 1]
            if trou <= SEUIL_FRAICHEUR_MS:
                continue
            # Un instant au MILIEU du trou : le replay n'y trouverait rien de frais.
            milieu = serie_gardee[i - 1] + trou // 2
            proche_complet = plus_proche_avant(serie_complete, milieu)
            if (proche_complet is not None
                    and milieu - proche_complet <= SEUIL_FRAICHEUR_MS):
                trous_combles += 1
                if len(exemples) < 6:
                    exemples.append({
                        "coin": coin, "trou_s": round(trou / 1000.0, 1),
                        "comble_par_un_carnet_a_s": round((milieu - proche_complet) / 1000.0, 1),
                    })
            else:
                trous_restants += 1

    print()
    print("  --- les trous de la serie GARDEE seraient-ils combles par les ECARTES ? ---")
    print(f"  trous > {SEUIL_FRAICHEUR_MS / 1000:.0f} s COMBLES par un carnet ecarte :"
          f" {trous_combles:,}")
    print(f"  trous > {SEUIL_FRAICHEUR_MS / 1000:.0f} s qui RESTERAIENT vides   :"
          f" {trous_restants:,}")
    if trous_combles + trous_restants:
        part = 100.0 * trous_combles / (trous_combles + trous_restants)
        print(f"  part des trous que l'observation COUVRAIT deja : {part:.1f} %")
    for e in exemples:
        print(f"    {e['coin']:<10} trou {e['trou_s']:>8.1f} s"
              f"  -> un carnet ecarte a {e['comble_par_un_carnet_a_s']} s du milieu")
    sortie = RACINE / "runtime" / "reports" / "regle_reelle_connexions_20261122.json"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps({
        "carnets_lus": total, "gardes": gardes_n, "audit": audit,
        "trous_combles_par_un_ecarte": trous_combles,
        "trous_restants_vides": trous_restants,
        "seuil_fraicheur_ms": SEUIL_FRAICHEUR_MS, "exemples": exemples,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print(f"  rapport : {sortie.relative_to(RACINE).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
