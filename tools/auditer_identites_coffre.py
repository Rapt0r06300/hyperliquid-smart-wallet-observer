r"""Le coffre jette-t-il comme « doublons » des lignes qui ne portent PAS la même information ?

Origine (22/11/2026) : deux pertes silencieuses de même forme, trouvées une par une —
* des carnets LIÉS à un signal (`checkpoint_id`) jetés comme doublons de leur observation nue
  (28 990 preuves absentes du coffre) ;
* la bougie 1 min COMPLÈTE jetée comme doublon de sa première version partielle.

Ce contrôle les cherche toutes à la fois. Pour chaque ruban (sessions archivées par défaut), chaque
ligne est certifiée comme le ferait le scelleur, puis regroupée par son identité de déduplication.
Dans un groupe de plus d'une ligne, on liste les champs dont la valeur DIFFÈRE. Un champ de pure
réception (heure de réception, identité de connexion…) peut différer sans perte ; tout autre champ
qui diffère veut dire : le coffre n'en garde qu'une version, la première.

Une collision n'est pas forcément un défaut (une re-diffusion peut changer un champ cosmétique) :
le contrôle RAPPORTE, il ne tranche pas. LECTURE SEULE : rien n'est écrit hors du rapport.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for _p in (RACINE / "src", RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from hl_observer.datasets import coffre_certifie as CC  # noqa: E402

#: Champs qui décrivent la RÉCEPTION, pas l'observation : qu'ils diffèrent ne perd rien.
CHAMPS_DE_RECEPTION = frozenset({
    "received_at_ms", "received_at_ms_raw", "observed_at_ms", "recv_mono_ns", "processed_at_ms", "recu_ms",
    "connection_id", "l2_gap_epoch", "writer_run_id", "run_id", "tier", "reconciliation_status",
    "presignal_age_ms", "observation_field", "lag_ms", "latence_ms", "clean_epoch_ms", "collected_at_ms",
    "retard_reception_ms", "collector_protocol", "socket_id", "shard_index", "source_id",
})


def _lignes(chemin: Path, limite: int):
    ouvrir = gzip.open if chemin.suffix == ".gz" else open
    with ouvrir(chemin, "rt", encoding="utf-8", errors="replace") as f:
        for i, ligne in enumerate(f):
            if i >= limite:
                return
            if ligne.strip():
                try:
                    yield json.loads(ligne)
                except ValueError:
                    continue


def _empreinte(valeur) -> str:
    return json.dumps(valeur, sort_keys=True, ensure_ascii=False, default=str)


def auditer_fichier(chemin: Path, *, limite: int = 400_000, now_ms: int = 4_102_444_800_000) -> dict | None:
    info = CC.detecter_famille(chemin.name)
    if not info:
        return None
    famille, source = info
    groupes: dict = {}
    differents: collections.Counter = collections.Counter()
    exemples: dict[str, list] = {}
    lues = certifiees = collisions = collisions_metier = 0
    for brut in _lignes(chemin, limite):
        lues += 1
        try:
            norm, decision, _ = CC.certifier_record(brut, famille=famille, source=source, now_ms=now_ms)
        except Exception:  # noqa: BLE001 - un certificateur qui plante sur une ligne : compté, pas fatal
            continue
        if decision == CC.QUARANTAINE or norm is None:
            continue
        certifiees += 1
        cle = CC.identite(norm, famille)
        premiere = groupes.get(cle)
        if premiere is None:
            groupes[cle] = norm
            continue
        collisions += 1
        champs = {k for k in set(premiere) | set(norm)
                  if _empreinte(premiere.get(k)) != _empreinte(norm.get(k))}
        metier = sorted(champs - CHAMPS_DE_RECEPTION)
        if metier:
            collisions_metier += 1
            for k in metier:
                differents[k] += 1
                if len(exemples.setdefault(k, [])) < 2:
                    exemples[k].append([premiere.get(k), norm.get(k)])
    return {"fichier": str(chemin), "famille": famille, "lues": lues, "certifiees": certifiees,
            "collisions": collisions, "collisions_avec_perte": collisions_metier,
            "champs_perdus": dict(differents.most_common(12)),
            "exemples": {k: v for k, v in exemples.items() if k in dict(differents.most_common(6))}}


def auditer_session(dossier: Path, *, limite: int = 400_000, now_ms: int = 4_102_444_800_000) -> list[dict]:
    """ENTRE FICHIERS, comme le scelleur : par famille, fichiers dans l'ordre alphabétique, un seul
    ensemble de « déjà vus ». La première perte réelle était de cette forme : le carnet du moteur
    (`copy_vault_l2_tape`) perdu contre la copie de la lane (`copy_vault_l2_lane`), traitée avant."""
    par_famille: dict[str, list[tuple[Path, str]]] = collections.defaultdict(list)
    for f in sorted((x for x in Path(dossier).iterdir() if x.is_file()), key=lambda e: e.name):
        info = CC.detecter_famille(f.name)
        if info:
            par_famille[info[0]].append((f, info[1]))
    rapport = []
    for famille, fichiers in sorted(par_famille.items()):
        if len(fichiers) < 2:
            continue
        gagnant: dict = {}
        paires: dict[tuple[str, str], collections.Counter] = collections.defaultdict(collections.Counter)
        n_paires: collections.Counter = collections.Counter()
        for chemin, source in fichiers:
            for brut in _lignes(chemin, limite):
                try:
                    norm, decision, _ = CC.certifier_record(brut, famille=famille, source=source, now_ms=now_ms)
                except Exception:  # noqa: BLE001
                    continue
                if decision == CC.QUARANTAINE or norm is None:
                    continue
                cle = CC.identite(norm, famille)
                deja = gagnant.get(cle)
                if deja is None:
                    gagnant[cle] = (chemin.name, norm)
                    continue
                if deja[0] == chemin.name:
                    continue                     # collision interne : couverte par auditer_fichier
                champs = {k for k in set(deja[1]) | set(norm)
                          if _empreinte(deja[1].get(k)) != _empreinte(norm.get(k))}
                paire = (deja[0], chemin.name)
                n_paires[paire] += 1
                paires[paire].update(champs)
        for (g, perdant), n in sorted(n_paires.items(), key=lambda kv: -kv[1]):
            rapport.append({"famille": famille, "gagne": g, "perd": perdant, "lignes_perdues": n,
                            "champs_qui_different": dict(paires[(g, perdant)].most_common(10))})
    return rapport


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--dossier", default="runtime/archive", help="où chercher les rubans (récursif)")
    p.add_argument("--limite", type=int, default=400_000, help="lignes lues au plus par fichier")
    p.add_argument("--par-nom", type=int, default=3, help="au plus N fichiers par nom (les plus récents)")
    p.add_argument("--json", default="", help="écrire le rapport complet ici")
    p.add_argument("--session", default="", help="auditer ENTRE fichiers une session (ex. runtime/archive/session_x)")
    args = p.parse_args(argv)
    if args.session:
        lignes = auditer_session(Path(args.racine) / args.session, limite=args.limite)
        print(f"  {'famille':<16}{'gagne (garde au coffre)':<36}{'perd':<36}{'lignes':>8}  champs qui different")
        for r in lignes:
            champs = ", ".join(f"{k}x{n}" for k, n in list(r["champs_qui_different"].items())[:7])
            print(f"  {r['famille'][:15]:<16}{r['gagne'][:35]:<36}{r['perd'][:35]:<36}{r['lignes_perdues']:>8}  {champs}")
        if args.json:
            Path(args.json).write_text(json.dumps(lignes, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return 0
    base = Path(args.racine) / args.dossier
    par_nom: dict[str, list[Path]] = collections.defaultdict(list)
    for f in sorted(base.rglob("*.jsonl*"), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and f.stat().st_size and len(par_nom[f.name]) < args.par_nom:
            par_nom[f.name].append(f)
    rapport = []
    for nom in sorted(par_nom):
        cumul = None
        for f in par_nom[nom]:
            r = auditer_fichier(f, limite=args.limite)
            if r is None:
                break
            if cumul is None:
                cumul = {**r, "fichier": nom, "fichiers": 1}
                continue
            cumul["fichiers"] += 1
            for k in ("lues", "certifiees", "collisions", "collisions_avec_perte"):
                cumul[k] += r[k]
            c = collections.Counter(cumul["champs_perdus"]); c.update(r["champs_perdus"])
            cumul["champs_perdus"] = dict(c.most_common(12))
            for k, v in r["exemples"].items():
                cumul["exemples"].setdefault(k, v)
        if cumul:
            rapport.append(cumul)
    print(f"  {'ruban':<40}{'famille':<16}{'lues':>9}{'collis.':>9}{'AVEC PERTE':>11}  champs qui different")
    for r in sorted(rapport, key=lambda x: -x["collisions_avec_perte"]):
        champs = ", ".join(f"{k}x{n}" for k, n in list(r["champs_perdus"].items())[:6])
        print(f"  {r['fichier'][:39]:<40}{r['famille'][:15]:<16}{r['lues']:>9}{r['collisions']:>9}"
              f"{r['collisions_avec_perte']:>11}  {champs}")
    if args.json:
        Path(args.json).write_text(json.dumps(rapport, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
