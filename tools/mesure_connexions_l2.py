r"""Combien de connexions L2 par coin, et pourquoi ? Lecture BORNEE du vrai ruban.

CE QUE CETTE MESURE DOIT TRANCHER. L'audit du labo dit : « une seule connexion L2 par coin
-> 125 544 carnets gardes, 205 940 ecartes comme connexion minoritaire (**2/175 coins n'en
avaient qu'une**) ». Donc 173 coins sur 175 portent PLUSIEURS connexions, et 62 % des carnets
collectes sont structurellement inutilisables : a l'instant de sortie d'une position, le trou
tue l'episode (1 045 `STALE_OR_MISSING_EXIT_BOOK` sur 1 613 candidats).

DEUX CAUSES TRES DIFFERENTES donnent ce meme symptome, et le correctif n'est pas le meme :

  (a) des connexions COURTES qui se reconnectent souvent -> chaque reconnexion cree une
      identite, donc N connexions pour un coin sur la duree. Correctif : des sockets qui
      tiennent (resilience), ou l'usage des fenetres de trou deja enregistrees.
  (b) PLUSIEURS SOURCES collectant le meme coin en parallele (lanes + collecteur PC) ->
      deux connexions simultanees. Correctif : une affectation coin -> lane exclusive.

On les distingue en regardant si les intervalles de vie des connexions d'un coin se
RECOUVRENT (b) ou se SUCCEDENT (a).

LECTURE SEULE, bornee en octets : 7 Go ne se lisent pas pour compter des identifiants.
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
#: 400 Mo de tete : assez pour des milliers de connexions, assez peu pour tenir en memoire.
BUDGET_OCTETS = 400 * 1024 * 1024


def trouver() -> pathlib.Path | None:
    for relatif in RUBANS:
        chemin = RACINE / relatif
        if chemin.is_file():
            return chemin
    return None


def mesurer(chemin: pathlib.Path, *, budget: int = BUDGET_OCTETS) -> dict:
    """Par (coin, connexion) : premier et dernier instant, nombre de carnets."""
    vies: dict[tuple[str, str], list] = {}
    lues = sans_coin = sans_conn = 0
    octets = 0
    with chemin.open("rb") as flux:
        for brut in flux:
            octets += len(brut)
            if octets > budget:
                break
            lues += 1
            try:
                ligne = json.loads(brut)
            except ValueError:
                continue
            if not isinstance(ligne, dict):
                continue
            coin = ligne.get("coin")
            if not isinstance(coin, str) or not coin:
                sans_coin += 1
                continue
            conn = ligne.get("connection_id")
            if not isinstance(conn, str) or not conn.strip():
                sans_conn += 1
                continue
            ts = ligne.get("received_at_ms") or ligne.get("ts_ms")
            if not isinstance(ts, int):
                continue
            cle = (coin.upper(), conn)
            vie = vies.get(cle)
            if vie is None:
                vies[cle] = [ts, ts, 1]
            else:
                vie[0] = min(vie[0], ts)
                vie[1] = max(vie[1], ts)
                vie[2] += 1
    return {"vies": vies, "lignes_lues": lues, "sans_coin": sans_coin,
            "sans_connexion": sans_conn, "octets_lus": octets}


def analyser(vies: dict) -> dict:
    par_coin: dict[str, list] = collections.defaultdict(list)
    for (coin, conn), (debut, fin, n) in vies.items():
        par_coin[coin].append((debut, fin, n, conn))

    recouvrants = 0
    successifs = 0
    detail: list[dict] = []
    for coin, liste in par_coin.items():
        liste.sort()
        chevauche = False
        for i in range(len(liste) - 1):
            # Recouvrement = deux connexions VIVANTES en meme temps -> plusieurs sources.
            if liste[i + 1][0] <= liste[i][1]:
                chevauche = True
                break
        if len(liste) > 1:
            (recouvrants if chevauche else successifs).__class__  # noqa: B018
            if chevauche:
                recouvrants += 1
            else:
                successifs += 1
        durees = [(f - d) / 1000.0 for d, f, _n, _c in liste]
        detail.append({
            "coin": coin, "connexions": len(liste),
            "chevauchement": chevauche,
            "duree_max_s": round(max(durees), 1) if durees else 0.0,
            "duree_mediane_s": round(sorted(durees)[len(durees) // 2], 1) if durees else 0.0,
            "carnets": sum(n for _d, _f, n, _c in liste),
            "carnets_majoritaire": max((n for _d, _f, n, _c in liste), default=0),
        })
    detail.sort(key=lambda x: -x["connexions"])
    une_seule = sum(1 for d in detail if d["connexions"] == 1)
    return {
        "coins": len(par_coin), "coins_une_seule_connexion": une_seule,
        "coins_plusieurs": len(par_coin) - une_seule,
        "coins_avec_CHEVAUCHEMENT": recouvrants,
        "coins_SUCCESSIFS_sans_chevauchement": successifs,
        "detail": detail,
    }


def main() -> int:
    flux = sys.stdout
    try:  # noqa: SIM105
        flux.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    chemin = trouver()
    if chemin is None:
        print("RUBAN L2 INTROUVABLE — rien a mesurer, et ce n'est pas un zero.")
        return 2
    print(f"  ruban : {chemin.relative_to(RACINE).as_posix()}"
          f"  ({chemin.stat().st_size / 2 ** 30:.2f} Go, lecture bornee a"
          f" {BUDGET_OCTETS / 2 ** 20:.0f} Mo)")
    brut = mesurer(chemin)
    if not brut["vies"]:
        print("  AUCUNE paire (coin, connexion) lisible.")
        print(f"  lignes lues {brut['lignes_lues']:,} | sans coin {brut['sans_coin']:,}"
              f" | sans connexion {brut['sans_connexion']:,}")
        return 2
    bilan = analyser(brut["vies"])
    print(f"  lignes lues : {brut['lignes_lues']:,}"
          f" | sans connexion_id : {brut['sans_connexion']:,}")
    print()
    print(f"  coins                              : {bilan['coins']}")
    print(f"  avec UNE SEULE connexion           : {bilan['coins_une_seule_connexion']}")
    print(f"  avec PLUSIEURS connexions          : {bilan['coins_plusieurs']}")
    print(f"     dont connexions QUI SE RECOUVRENT (plusieurs sources) :"
          f" {bilan['coins_avec_CHEVAUCHEMENT']}")
    print(f"     dont connexions SUCCESSIVES (reconnexions)            :"
          f" {bilan['coins_SUCCESSIFS_sans_chevauchement']}")
    print()
    print("  --- les 12 coins les plus fragmentes ---")
    print("    coin        conn  chevauche  duree_max  duree_med   carnets  major.")
    for d in bilan["detail"][:12]:
        print(f"    {d['coin']:<10} {d['connexions']:>5}  {str(d['chevauchement']):>9}"
              f"  {d['duree_max_s']:>8.0f}s  {d['duree_mediane_s']:>8.0f}s"
              f"  {d['carnets']:>8,}  {d['carnets_majoritaire']:>6,}")
    print()
    perdus = sum(d["carnets"] - d["carnets_majoritaire"] for d in bilan["detail"])
    total = sum(d["carnets"] for d in bilan["detail"])
    print(f"  carnets ECARTES si on ne garde que la majoritaire : {perdus:,} / {total:,}"
          f"  ({100.0 * perdus / max(1, total):.1f} %)")
    sortie = RACINE / "runtime" / "reports" / "connexions_l2_20261122.json"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps({k: v for k, v in bilan.items() if k != "detail"}
                                 | {"detail": bilan["detail"][:60]},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  rapport : {sortie.relative_to(RACINE).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
