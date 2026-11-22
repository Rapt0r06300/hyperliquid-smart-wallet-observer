r"""PERIME LE 22/11/2026 : CE SCRIPT MESURE UNE REGLE QUE LE DEPOT N'APPLIQUE PAS.

Ne pas se servir de ses chiffres. Il suppose que `une_seule_connexion_par_coin` ne garde
que la connexion MAJORITAIRE ; elle trie en fait par DUREE et garde PLUSIEURS connexions
par coin tant que leurs intervalles NE SE RECOUVRENT PAS. Resultat : il annonce 83 %% de
carnets ecartes la ou la vraie regle en ecarte 24,7 %%, et 92 %% de trous comblables la ou
la mesure honnete en trouve 20,9 %%.

La mesure juste, qui APPELLE la vraie fonction au lieu de la reimplementer :
    runtime/diagnostics/mesure_regle_reelle_connexions.py

Conserve pour la tracabilite de l'erreur. La lecon : appeler le code teste, jamais
reecrire sa regle de memoire pour en mesurer le cout.

--- texte d'origine, desormais faux ---------------------------------------------------

Franchir deux connexions dont le TROU est prouve court : combien de carnets sauves ?

LA REGLE ACTUELLE, et sa raison. Le labo ne garde, par coin, que la connexion L2 PORTANT LE
PLUS de carnets ; les autres sont ecartees comme « minoritaires ». C'est VOULU : un episode
ne doit pas traverser deux flux dont le raccord cache peut-etre des mises a jour perdues.

CE QU'ELLE COUTE, mesure du 22/11/2026 : **83 %** des carnets certifies sont ecartes
(425 544 sur 512 654), et a l'instant de sortie d'une position le trou qui reste tue
l'episode -- 1 045 `STALE_OR_MISSING_EXIT_BOOK` sur 1 613 candidats, donc **zero trade
ferme** et `economically_proven = false`.

CE QUE CETTE MESURE TRANCHE. Une connexion WS porte BEAUCOUP de coins : les 297
« connexions de BTC » sont 297 connexions ayant chacune porte quelques carnets de BTC
(4 lanes x de nombreuses reconnexions sur plusieurs jours). Les carnets d'un coin sont donc
EPARPILLES, pas discontinus. La question devient :

    si l'on autorisait un episode a franchir deux connexions dont le TROU mesure
    <= 30 s (la fraicheur deja exigee, `MAX_TARGET_LAG_MS`), combien de carnets
    redeviendraient utilisables -- et combien de trous resteraient trop longs ?

Si les trous sont majoritairement courts, la regle actuelle jette de la donnee valide et le
correctif vaut la peine. S'ils sont longs, elle protege quelque chose de reel et il ne faut
PAS y toucher. On mesure avant de decider ; aucune modification n'est faite ici.

LECTURE SEULE, bornee en octets.
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
RUBANS = (
    "runtime/data/copy_vault_l2_tape.jsonl",
    "runtime/labo_tranches_20261121/workspace/runtime/data/copy_vault_l2_tape.jsonl",
)
BUDGET_OCTETS = 400 * 1024 * 1024
#: La fraicheur deja exigee autour de chaque evenement copie : 30 s.
SEUIL_TROU_MS = 30_000


def trouver() -> pathlib.Path | None:
    for relatif in RUBANS:
        chemin = RACINE / relatif
        if chemin.is_file():
            return chemin
    return None


def lire(chemin: pathlib.Path, *, budget: int) -> dict[str, list[tuple[int, str]]]:
    """Par coin : la suite (instant, connexion) de ses carnets, triee."""
    par_coin: dict[str, list[tuple[int, str]]] = collections.defaultdict(list)
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
            coin = ligne.get("coin")
            conn = ligne.get("connection_id")
            ts = ligne.get("received_at_ms") or ligne.get("ts_ms")
            if not isinstance(coin, str) or not isinstance(conn, str) or not isinstance(ts, int):
                continue
            par_coin[coin.upper()].append((ts, conn))
    for serie in par_coin.values():
        serie.sort()
    return par_coin


def analyser(par_coin: dict[str, list[tuple[int, str]]], *, seuil_ms: int) -> dict:
    """Combien de carnets la regle actuelle jette, et combien un raccord court sauverait ?

    On parcourt les carnets d'un coin dans l'ordre. Un CHANGEMENT de connexion est un
    raccord : on mesure le trou (l'ecart entre les deux carnets qui l'encadrent). Un raccord
    de trou <= `seuil_ms` ne cache aucune mise a jour utile a l'echelle ou le labo travaille.
    """
    total = gardes_majoritaire = 0
    raccords_courts = raccords_longs = 0
    trous: list[int] = []
    sauves_si_raccord_court = 0
    par_coin_detail: list[dict] = []

    for coin, serie in par_coin.items():
        total += len(serie)
        compte = collections.Counter(c for _ts, c in serie)
        majoritaire = compte.most_common(1)[0][0] if compte else None
        gardes_majoritaire += compte[majoritaire] if majoritaire else 0

        courts = longs = 0
        sauves = 0
        segment_courant_ok = True
        for i in range(1, len(serie)):
            ts_a, conn_a = serie[i - 1]
            ts_b, conn_b = serie[i]
            if conn_a == conn_b:
                if segment_courant_ok and conn_b != majoritaire:
                    sauves += 1
                continue
            trou = ts_b - ts_a
            trous.append(trou)
            if trou <= seuil_ms:
                courts += 1
                segment_courant_ok = True
                if conn_b != majoritaire:
                    sauves += 1
            else:
                longs += 1
                segment_courant_ok = False
        raccords_courts += courts
        raccords_longs += longs
        sauves_si_raccord_court += sauves
        par_coin_detail.append({
            "coin": coin, "carnets": len(serie), "connexions": len(compte),
            "majoritaire": compte[majoritaire] if majoritaire else 0,
            "raccords_courts": courts, "raccords_longs": longs,
            "sauves_si_raccord_court": sauves,
        })

    trous.sort()
    def quantile(q: float) -> int:
        return trous[int(q * (len(trous) - 1))] if trous else -1

    par_coin_detail.sort(key=lambda d: -d["sauves_si_raccord_court"])
    return {
        "carnets_total": total,
        "gardes_par_la_regle_actuelle": gardes_majoritaire,
        "ecartes_par_la_regle_actuelle": total - gardes_majoritaire,
        "raccords_courts": raccords_courts, "raccords_longs": raccords_longs,
        "seuil_trou_ms": seuil_ms,
        "trou_median_s": round(quantile(0.5) / 1000.0, 2),
        "trou_p90_s": round(quantile(0.9) / 1000.0, 2),
        "trou_p99_s": round(quantile(0.99) / 1000.0, 2),
        "carnets_sauves_si_raccord_court": sauves_si_raccord_court,
        "detail": par_coin_detail[:20],
    }


def main() -> int:
    flux = sys.stdout
    try:  # noqa: SIM105
        flux.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    chemin = trouver()
    if chemin is None:
        print("RUBAN L2 INTROUVABLE — rien a mesurer.")
        return 2
    print(f"  ruban : {chemin.name} ({chemin.stat().st_size / 2 ** 30:.2f} Go,"
          f" borne a {BUDGET_OCTETS / 2 ** 20:.0f} Mo)")
    par_coin = lire(chemin, budget=BUDGET_OCTETS)
    if not par_coin:
        print("  AUCUN carnet lisible avec (coin, connexion, instant).")
        return 2
    bilan = analyser(par_coin, seuil_ms=SEUIL_TROU_MS)
    total = bilan["carnets_total"]
    print()
    print(f"  carnets lus                         : {total:,} sur {len(par_coin)} coins")
    print(f"  gardes par la regle ACTUELLE        : {bilan['gardes_par_la_regle_actuelle']:,}"
          f"  ({100.0 * bilan['gardes_par_la_regle_actuelle'] / total:.1f} %)")
    print(f"  ECARTES par la regle actuelle       : {bilan['ecartes_par_la_regle_actuelle']:,}"
          f"  ({100.0 * bilan['ecartes_par_la_regle_actuelle'] / total:.1f} %)")
    print()
    print(f"  raccords entre connexions, TROU <= {SEUIL_TROU_MS / 1000:.0f} s :"
          f" {bilan['raccords_courts']:,}")
    print(f"  raccords TROP LONGS                 : {bilan['raccords_longs']:,}")
    print(f"  trou median {bilan['trou_median_s']} s"
          f" | p90 {bilan['trou_p90_s']} s | p99 {bilan['trou_p99_s']} s")
    print()
    sauves = bilan["carnets_sauves_si_raccord_court"]
    print(f"  => carnets RECUPERABLES en franchissant les raccords courts : {sauves:,}"
          f"  (+{100.0 * sauves / total:.1f} points)")
    utilisables = bilan["gardes_par_la_regle_actuelle"] + sauves
    print(f"     utilisables : {bilan['gardes_par_la_regle_actuelle']:,}"
          f" -> {utilisables:,}  ({100.0 * utilisables / total:.1f} % du ruban)")
    print()
    print("  --- les 10 coins qui gagneraient le plus ---")
    print("    coin        carnets  conn  major.  courts  longs   sauves")
    for d in bilan["detail"][:10]:
        print(f"    {d['coin']:<10} {d['carnets']:>8,} {d['connexions']:>5}"
              f" {d['majoritaire']:>7,} {d['raccords_courts']:>7,}"
              f" {d['raccords_longs']:>6,} {d['sauves_si_raccord_court']:>8,}")
    sortie = RACINE / "runtime" / "reports" / "trous_entre_connexions_20261122.json"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps(bilan, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print(f"  rapport : {sortie.relative_to(RACINE).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
