r"""Moteur de decouverte CopyVault -- l'outil du labo (27/11/2026). PAPER, lecture seule du coffre certifie.

Trois gestes, dans cet ordre quand on lance sans option (c'est ce que fait le lanceur du labo) :

  --banc      la methode de recherche se compare a ses voisines sur des mondes a VERITE CONNUE (graines neuves) ;
              elle n'est remplacee que si une variante decouvre plus sans fabriquer de faux gagnants, et revient en
              arriere si elle-meme en fabrique. Journal : runtime/research_lab/decouverte/METHODES.ndjson ;
  --campagne  genere les cellules (grammaire + memoire), les PRE-ENREGISTRE dans runtime/data/registre_essais.jsonl,
              les juge (DSR avec TOUS les essais anterieurs, PBO), gele au plus 5 candidats, met a jour la memoire
              scientifique, ecrit le rapport et une ligne du registre des experiences (le planificateur la lit) ;
  --suivi     juge chaque candidat gele sur les seules decisions posterieures a son gel : promotion, invalidation,
              retour arriere. Sortie : une RECOMMANDATION PAPER, jamais appliquee au moteur.

Donnees : episodes de fills des leaders (famille fills_backfill, ``vault_episodes``), bougies 1 h Hyperliquid
certifiees (jamais les bougies externes), historique de funding, demi-ecarts mesures sur les carnets (sinon une
valeur prudente declaree). Les dates d'entree des vaults dans la liste suivie viennent de l'historique Git de
``config/copy_vault_leaders.json`` (garde en cache : sans Git, le cache ; sans cache, aucune validation).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
for _chemin in (RACINE / "src", RACINE / "tools"):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

import pandas as pd  # noqa: E402

import etude_copiabilite as E  # noqa: E402
from hl_observer.backtesting import copy_vault_champion_challenger as CC  # noqa: E402
from hl_observer.backtesting import copy_vault_decouverte as D  # noqa: E402
from hl_observer.backtesting import copy_vault_decouverte_banc as B  # noqa: E402
from hl_observer.backtesting.copy_vault_copiability_entrees import build_candle_panel  # noqa: E402
from hl_observer.experimental import registre_essais as RE  # noqa: E402

ETAT_DIR = Path("runtime/research_lab/decouverte")
CACHE_DIR = Path("runtime/research_lab/data/decouverte_cache")
RAPPORTS = Path("runtime/reports/copy_vault_quant_lab/decouverte")
CONFIG_LEADERS = "config/copy_vault_leaders.json"
#: Hypotheses DECLAREES : un mecanisme vu en exploration, inscrit UNE fois avec sa date, juge SEULEMENT sur des
#: decisions posterieures a sa declaration, par les memes regles de promotion que tout challenger (30 jours, IC95 > 0,
#: Benjamini-Hochberg, mieux que le champion). Ajouter une ligne ici = une hypothese de plus dans la correction BH.
HYPOTHESES_DECLAREES = (
    {"direction": "suivre", "horizon_h": 24, "predicats": (("tendance", "contre"),), "declaree_le": "2026-11-27",
     "pourquoi": "mecanisme recurrent des campagnes 2 et 3 : le leader qui va CONTRE la tendance 24 h du coin "
                 "(+18,8 bps par decision en selection, +32,2 post-entree, 38 leaders) ; non prouve (PBO > 0,5)"},
)
COST_MODEL = "taker4.5+demi_ecart_mesure_ou_8+glissement1+funding_porte.v1"
EXEC_MODEL = "backfill_obs+60s+60s_bougie_1h_suivante.v1"


def _lire_json(chemin: Path, defaut: Any) -> Any:
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaut


def _ecrire_json(chemin: Path, valeur: Any) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(chemin.suffix + ".tmp")
    tmp.write_text(json.dumps(valeur, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(chemin)


def entrees_suivi(root: Path) -> dict[str, int]:
    """Vault -> premier instant (ms) ou il apparait dans la liste suivie, d'apres l'historique Git (cache garde)."""
    cache_path = root / ETAT_DIR / "entree_suivi.json"
    connu: dict[str, int] = {k: int(v) for k, v in _lire_json(cache_path, {}).items()}
    try:
        log = subprocess.run(["git", "-C", str(root), "log", "--reverse", "--format=%H %at", "--", CONFIG_LEADERS],
                             capture_output=True, text=True, timeout=120, check=True).stdout
        for ligne in filter(None, log.splitlines()):
            sha, ts = ligne.split()
            contenu = subprocess.run(["git", "-C", str(root), "show", f"{sha}:{CONFIG_LEADERS}"], capture_output=True,
                                     text=True, encoding="utf-8", timeout=60).stdout.lower()
            for vault in set(re.findall(r"0x[0-9a-f]{40}", contenu)):
                instant = int(ts) * 1000
                if vault not in connu or instant < connu[vault]:
                    connu[vault] = instant
    except (OSError, subprocess.SubprocessError, ValueError):
        pass                                     # sans Git : le cache seul (et sans cache : aucune validation)
    if connu:
        _ecrire_json(cache_path, dict(sorted(connu.items())))
    return connu


def _lire_gz(shards: list[dict[str, Any]]):
    for item in shards:
        with gzip.open(item["path"], "rt", encoding="utf-8") as h:
            for ligne in h:
                try:
                    r = json.loads(ligne)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    yield r


def bougies_1h(shards: list[dict[str, Any]]):
    """Bougies 1 h Hyperliquid certifiees ; les shards et lignes EXTERNES (Ironflow...) sont ecartes."""
    for r in _lire_gz([s for s in shards if "candles_1h" in s["shard"] and "externe" not in s["shard"]]):
        if r.get("interval") == "1h" and "IRONFLOW" not in str(r.get("source") or "").upper():
            yield str(r.get("coin") or ""), r.get("open_ts_ms"), r.get("close")


def construire_table(root: Path, *, config: D.DecouverteConfig, ecarts_mesures: bool = True) -> tuple[pd.DataFrame, dict[str, Any]]:
    wanted = {"fills_backfill": "vault_episodes", "candle": "candles_1h", "funding_history": ""}
    if ecarts_mesures:
        wanted.update({"book_l2": "", "bbo": "", "micro_bbo": ""})
    shards, exclus = E.select_shards(root, wanted)
    entrees = entrees_suivi(root)
    materiel = {fam: sorted(s["sha256"] for s in shards[fam]) for fam in sorted(shards)}
    cle = hashlib.sha256(json.dumps({"m": materiel, "e": entrees, "c": config.as_dict(),
                                     "code": E._sha256_file(Path(D.__file__)), "ecarts": ecarts_mesures},
                                    sort_keys=True).encode()).hexdigest()[:24]
    meta = {"cle": cle, "shards": {f: len(v) for f, v in shards.items()}, "exclus_integrite": len(exclus),
            "vaults_dates": len(entrees), "shards_detail": shards}
    cache = root / CACHE_DIR / f"table_{cle}.parquet"
    if cache.is_file():
        table = pd.read_parquet(cache)
        meta["cache"] = "RELU"
        meta.update(_lire_json(cache.with_suffix(".json"), {}))
        return table, meta
    if not shards["fills_backfill"]:
        return pd.DataFrame(), {**meta, "raison": "aucun episode de leader au coffre"}
    t = time.time()
    dec, rejets = D.decisions_depuis_episodes(_lire_gz(shards["fills_backfill"]), entree_suivi_ms=entrees, config=config)
    print(f"[decouverte] {len(dec):,} decisions de {dec['unit'].nunique() if len(dec) else 0} leaders "
          f"({time.time() - t:.0f} s)", flush=True)
    panel = build_candle_panel(bougies_1h(shards["candle"]), interval_ms=D.HEURE_MS)
    coins = set(dec["coin"].unique()) if len(dec) else set()
    debut_h = int(dec["t0"].min()) // D.HEURE_MS - 48 if len(dec) else 0
    funding: dict[tuple[str, int], float] = {}
    for coin, ts, taux in E.load_funding(shards["funding_history"], cache_dir=root / E.CACHE_DIR):
        if coin in coins and isinstance(ts, int) and ts // D.HEURE_MS >= debut_h:
            funding.setdefault((coin, ts // D.HEURE_MS), float(taux))
    demi = {}
    if ecarts_mesures:
        try:
            demi = E.load_half_spreads(E.spread_shards(shards), cache_dir=root / E.CACHE_DIR)
        except MemoryError:
            return pd.DataFrame(), {**meta, "raison": "memoire insuffisante pour lire les ecarts mesures : rien n'est "
                                                     "ecrit (jamais de repli silencieux sur l'ecart par defaut)"}
    table, rejets_e = D.enrichir(dec, panel, bar_ms=D.HEURE_MS, funding=funding, demi_ecarts=demi, config=config)
    table = D.attribuer_populations(table, coupure_ms=None, config=config)
    extra = {"rejets": {**rejets, **rejets_e}, "coupure_ms": table.attrs.get("coupure_ms"),
             "couts": "MESURES (carnets du coffre)" if ecarts_mesures else "PAR DEFAUT (8 bps) : aucune refutation",
             "donnees_jusqu_a_ms": int(table["t0"].max()) if len(table) else None,
             "seuil_volatilite_bps": table.attrs.get("seuil_volatilite_bps"), "coins_avec_ecart_mesure": len(demi),
             "heures_de_funding": len(funding), "bougies_1h_heures": int(len(panel.ts))}
    cache.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(cache, index=False)
    _ecrire_json(cache.with_suffix(".json"), extra)
    meta.update(extra)
    meta["cache"] = "CALCULE"
    return table, meta


def _essais_anterieurs(root: Path, ids_courants: set[str]) -> tuple[int, list[float]]:
    """N du DSR : les experiences des AUTRES etudes du registre + les cellules DISTINCTES deja jugees par ce moteur
    et absentes de la campagne en cours (elles, comptees par ``juger_campagne``). Rejuger la meme cellule n'ajoute
    pas d'essai ; l'inventer en ajoute un."""
    ledger = root / E.REPORT_DIR / "EXPERIENCES.ndjson"
    autres = 0
    if ledger.is_file():
        for x in ledger.read_text(encoding="utf-8").splitlines():
            if x.strip() and f'"{D.HYPOTHESE}"' not in x:
                autres += 1
    dernier: dict[str, dict] = {}
    for e in RE.charger(root):
        if e.get("family") == D.FAMILLE and e.get("phase") == "resultat" and e.get("variant") not in ids_courants:
            dernier[e["variant"]] = e
    return autres + len(dernier), RE.sharpes_tous_essais(list(dernier.values()), family=D.FAMILLE)


def methode_courante(root: Path) -> D.Methode:
    brut = _lire_json(root / ETAT_DIR / "METHODE_COURANTE.json", None)
    try:
        m = D.Methode(**brut) if isinstance(brut, dict) else D.Methode()
    except TypeError:
        m = D.Methode()
    return m if m.respecte_les_garde_fous() else D.Methode()


def faire_banc(root: Path, table: pd.DataFrame, *, config: D.DecouverteConfig, write: bool, mondes: int,
               confirmer: str | None = None) -> dict[str, Any]:
    journal = root / ETAT_DIR / "METHODES.ndjson"
    version_banc = (sum(1 for x in journal.read_text(encoding="utf-8").splitlines() if x.strip()) + 1) if journal.is_file() else 1
    t = time.time()
    courante = methode_courante(root)
    variantes = None
    if confirmer:                                   # « champ=valeur » : UNE hypothese de methode annoncee avant le test
        champ, _, brut = confirmer.partition("=")
        valeur = {"true": True, "false": False}.get(brut.strip().lower(), brut.strip())
        if champ not in courante.as_dict() or champ == "version":
            raise ValueError(f"--confirmer : champ de methode inconnu {champ!r}")
        typ = type(getattr(courante, champ))
        variantes = [replace(courante, **{champ: valeur if typ is bool else typ(valeur)}, version=courante.version + 1)]
    decision = B.ameliorer_methode(table, courante, config, version_banc=version_banc, mondes=mondes, variantes=variantes)
    decision["confirmation"] = confirmer
    retenue = D.Methode(**decision["methode_retenue"])
    decision["puissance"] = B.puissance(table, retenue, config, graines=list(range(version_banc * 1000 + 500,
                                        version_banc * 1000 + 500 + max(4, mondes // 2))),
                                        calibrage=decision.get("calibrage"))
    decision["secondes"] = round(time.time() - t, 1)
    decision["ts_ms"] = int(time.time() * 1000)
    b = decision["banc_courante"]
    print(f"[banc] calibrage (ecart-type journalier de la copie naive, reel / synthetique) : "
          f"{decision['verification_calibrage']}", flush=True)
    print(f"[banc] methode v{decision['courante']['version']} : rappel {b.get('rappel')}, fausses decouvertes "
          f"{b.get('fdr')}, mondes nuls avec faux {b.get('mondes_nuls_avec_faux')} -> {decision['decision']} "
          f"({decision['secondes']} s) ; effet minimal detectable : "
          f"{decision['puissance']['effet_minimal_detectable_bps']} bps/decision "
          f"(courbe {decision['puissance']['courbe']})", flush=True)
    if write:
        journal.parent.mkdir(parents=True, exist_ok=True)
        with journal.open("a", encoding="utf-8") as h:
            h.write(json.dumps(decision, ensure_ascii=False, default=str) + "\n")
        _ecrire_json(root / ETAT_DIR / "METHODE_COURANTE.json", decision["methode_retenue"])
    return decision


def faire_campagne(root: Path, table: pd.DataFrame, meta: dict[str, Any], *, config: D.DecouverteConfig,
                   write: bool) -> dict[str, Any]:
    methode = methode_courante(root)
    memoire = _lire_json(root / ETAT_DIR / "MEMOIRE_SCIENTIFIQUE.json", None)
    signature = {"cle_donnees": meta.get("cle"), "methode": methode.as_dict(), "juge": D.JUGE_VERSION}
    derniere = _lire_json(root / ETAT_DIR / "DERNIERE_CAMPAGNE.json", {})
    if write and derniere.get("signature") == signature:
        print("[campagne] rien de neuf depuis la derniere (memes donnees, meme methode, meme juge) : aucun essai "
              "de plus, rien d'ecrit.", flush=True)
        return {"rien_de_neuf": True, "signature": signature}
    numero = len((memoire or {}).get("campagnes", [])) + 1
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-decouverte"
    cellules = D.generer_cellules(methode, config, memoire=memoire, graine=numero)
    if write:                                          # PRE-enregistrement : avant toute mesure
        for c in cellules:
            RE.enregistrer(root, {"family": D.FAMILLE, "variant": c["id"], "params": {k: c[k] for k in ("direction", "horizon_h", "predicats")},
                                  "data_cutoff": meta.get("donnees_jusqu_a_ms"),
                                  "universe": f"vaults suivis (episodes backfill) | table {meta.get('cle')}",
                                  "horizon": c["horizon_h"], "cost_model_version": COST_MODEL,
                                  "execution_model_version": EXEC_MODEL, "phase": "preregistration"})
    essais, sharpes = _essais_anterieurs(root, {c["id"] for c in cellules})
    rapport = D.juger_campagne(table, cellules, methode, config, essais_anterieurs=essais, sharpes_anterieurs=sharpes)
    verdict = D.verdict_campagne(rapport)
    prim = D.primaire(rapport)
    print(f"[campagne {numero}] {rapport['n_cellules']} cellules, N DSR = {rapport['n_essais_dsr']}, PBO = "
          f"{rapport['pbo'].get('pbo')}, {len(rapport['geles'])} gele(s), {rapport['jours_exploration']} j "
          f"d'exploration, {rapport['jours_validation']} j de validation", flush=True)
    resultat = {"run_id": run_id, "evidence_tier": D.EVIDENCE_TIER, "config": config.as_dict(),
                "table": {k: v for k, v in meta.items() if k != "shards_detail"}, "rapport": rapport,
                "verdict": verdict, "primary": prim, "paper_read_only": True, "real_execution": False}
    if not write:
        return resultat
    for r in rapport["resultats"]:
        RE.enregistrer(root, {"family": D.FAMILLE, "variant": r["id"], "params": {"direction": r["direction"],
                              "horizon_h": r["horizon_h"], "predicats": r["predicats"]},
                              "data_cutoff": meta.get("donnees_jusqu_a_ms"), "horizon": r["horizon_h"],
                              "universe": f"vaults suivis (episodes backfill) | table {meta.get('cle')}",
                              "cost_model_version": COST_MODEL, "execution_model_version": EXEC_MODEL,
                              "result": r["statut"], "pass_kill": r["statut"] != "REFUTEE", "phase": "resultat",
                              "sharpe": r["selection"].get("sharpe_jour")})
    _ecrire_json(root / ETAT_DIR / "MEMOIRE_SCIENTIFIQUE.json",
                 D.mettre_a_jour_memoire(memoire, rapport, campagne=run_id, cle_donnees=meta.get("cle")))
    _ecrire_json(root / ETAT_DIR / "DERNIERE_CAMPAGNE.json", {"run_id": run_id, "signature": signature})
    etat = _lire_json(root / ETAT_DIR / "CHAMPION_CHALLENGER.json", None) or CC.etat_initial()
    gel_ms = int(time.time() * 1000)
    etat = CC.enregistrer_geles(etat, rapport["geles"], gel_ms=gel_ms, campagne=run_id,
                                methode_version=methode.version)
    actifs = sum(1 for c in etat["challengers"].values() if c["etat"] in ("GELE", "SUIVI", "CHAMPION"))
    place = max(0, 20 - actifs)                       # au plus 20 suivis actifs : la correction BH reste lisible
    etat = CC.enregistrer_geles(etat, rapport.get("surveillance", [])[:place], gel_ms=gel_ms, campagne=run_id,
                                methode_version=methode.version, palier="SURVEILLANCE")
    par_id = {r["id"]: r for r in rapport["resultats"]}
    declarees = []
    for h in HYPOTHESES_DECLAREES:
        c = D._cellule(h["direction"], h["horizon_h"], h["predicats"])
        mesure = par_id.get(c["id"], {})
        declarees.append({**c, "predicats": [list(p) for p in c["predicats"]], "selection": mesure.get("selection", {}),
                          "dsr": mesure.get("dsr")})
    etat = CC.enregistrer_geles(etat, declarees, gel_ms=gel_ms, campagne=run_id, methode_version=methode.version,
                                palier="HYPOTHESE_DECLAREE")
    _ecrire_json(root / ETAT_DIR / "CHAMPION_CHALLENGER.json", etat)
    out = root / RAPPORTS / run_id
    _ecrire_json(out / "resultat.json", E._jsonable(resultat))
    (out / "RAPPORT.md").write_text(rendre_rapport(resultat), encoding="utf-8")
    identite = E.experiment_identity(root, {k: v for k, v in meta["shards_detail"].items()}, config, "decouverte|1h")
    identite["source_sha256"]["copy_vault_decouverte.py"] = E._sha256_file(Path(D.__file__))
    ledger = {"run_id": run_id, **identite, "evidence_tier": D.EVIDENCE_TIER, "hypotheses_tested": [D.HYPOTHESE],
              "verdicts": [verdict], "config": config.as_dict(), "methode": methode.as_dict(),
              "juge_version": D.JUGE_VERSION, "couts": meta.get("couts"),
              "inputs": {"decisions": int(len(table)), "cellules": rapport["n_cellules"],
                         "jours_selection": rapport["jours_selection"],
                         "jours_exploration": rapport["jours_exploration"], "jours_validation": rapport["jours_validation"]},
              "primary": prim, "result_path": (RAPPORTS / run_id / "resultat.json").as_posix(),
              "paper_read_only": True, "real_execution": False, "economically_proven": False}
    resultat["ledger_record_sha256"] = E.append_ledger(root / E.REPORT_DIR / "EXPERIENCES.ndjson", E._jsonable(ledger))
    print(f"[campagne] rapport : {out / 'RAPPORT.md'}", flush=True)
    return resultat


def faire_suivi(root: Path, table: pd.DataFrame, *, config: D.DecouverteConfig, write: bool) -> dict[str, Any]:
    etat = _lire_json(root / ETAT_DIR / "CHAMPION_CHALLENGER.json", None) or CC.etat_initial()
    nouvel, evenements = CC.evaluer(etat, table, now_ms=int(time.time() * 1000), config=config)
    actifs = [c for c in nouvel["challengers"].values() if c["etat"] in ("GELE", "SUIVI", "CHAMPION")]
    print(f"[suivi] champion PAPER : {nouvel['champion']} ; {len(actifs)} challenger(s) actif(s) ; "
          f"{len(evenements)} evenement(s) : {[e['evenement'] for e in evenements]}", flush=True)
    if write:
        _ecrire_json(root / ETAT_DIR / "CHAMPION_CHALLENGER.json", nouvel)
    return nouvel


def _fmt(x: Any, d: int = 1) -> str:
    return "n/d" if x is None or (isinstance(x, float) and x != x) else (f"{x:+.{d}f}" if isinstance(x, (int, float)) else str(x))


def rendre_rapport(resultat: dict[str, Any]) -> str:
    r, v, t = resultat["rapport"], resultat["verdict"], resultat["table"]
    tri = sorted(r["resultats"], key=lambda x: -(x["dsr"] or 0.0))
    lignes = [
        "# Moteur de decouverte CopyVault -- campagne", "",
        f"- Verdict `{v['hypothesis']}` : **{v['status']}** -- {v['reason']}.",
        f"- Statut des preuves : **{resultat['evidence_tier']}** (episodes REST de backfill : instant d'observation "
        "SUPPOSE a fill + 60 s ; entree a la cloture 1 h suivante).",
        f"- Selection sur {r['jours_selection']} jours : {r['jours_exploration']} d'EXPLORATION (avant la 1re entree d'un "
        "vault dans la liste suivie : biaisee en faveur de « suivre ») et "
        f"{r['jours_validation']} POST-ENTREE (leader deja suivi). La preuve viendra du SUIVI apres gel.",
        f"- Couts : **{t.get('couts')}** ; juge `{r.get('juge_version')}` (v2 ecrite apres avoir vu le reel, declaree).",
        f"- {r['n_cellules']} cellules pre-enregistrees ; N du DSR = {r['n_essais_dsr']} (tous les essais anterieurs "
        f"compris, cellules deja jugees non recomptees) ; PBO par (direction, horizon) = "
        f"{ {k: v.get('pbo') for k, v in r.get('pbo_par_groupe', {}).items()} } ; methode v{r['methode']['version']}.",
        f"- Table : {t.get('cache')} ; rejets {t.get('rejets')} ; {t.get('coins_avec_ecart_mesure')} coins a ecart mesure.", "",
        "## Candidats geles (porte DSR passee ; suivi PAPER a partir de maintenant)", "",
    ]
    if r["geles"]:
        lignes += ["| cellule | direction | horizon | predicats | DSR | selection bps | post-entree bps (IC95) |", "|---|---|---|---|---:|---:|---|"]
        for g in r["geles"]:
            val = g.get("validation", {})
            lignes.append(f"| `{g['id']}` | {g['direction']} | {g['horizon_h']} h | {g['predicats']} | {g['dsr']} | "
                          f"{_fmt(g['selection'].get('moyenne_bps'))} | {_fmt(val.get('moyenne_bps'))} {val.get('ic95')} |")
    else:
        lignes.append("Aucun : aucune cellule ne passe le DSR deflate par tous les essais, ou la porte PBO est fermee.")
    surv = resultat["rapport"].get("surveillance", [])
    lignes += ["", f"## En SURVEILLANCE ({len(surv)}) -- reperees, suivies en PAPER, promues seulement par le suivi", ""]
    lignes += [f"- `{x['id']}` {x['direction']} {x['horizon_h']} h {x['predicats']} : selection "
               f"{_fmt(x['selection'].get('moyenne_bps'))} bps sur {x['selection'].get('n_jours')} j, post-entree "
               f"{_fmt(x.get('validation', {}).get('moyenne_bps'))} bps, DSR {x['dsr']}" for x in surv]
    lignes += ["", "## Les 15 meilleures cellules au DSR (pour information, jamais une preuve)", "",
               "| direction | horizon | predicats | jours selection | selection bps | DSR | post-entree jours | post-entree bps | statut |",
               "|---|---|---|---:|---:|---:|---:|---:|---|"]
    for x in tri[:15]:
        e, val = x["selection"], x.get("validation", {})
        lignes.append(f"| {x['direction']} | {x['horizon_h']} h | {x['predicats'] or 'aucun filtre'} | {e.get('n_jours', 0)} | "
                      f"{_fmt(e.get('moyenne_bps'))} | {x['dsr']} | {val.get('n_jours', 0)} | {_fmt(val.get('moyenne_bps'))} | {x['statut']} |")
    refutees = [x for x in r["resultats"] if x["statut"] == "REFUTEE"]
    lignes += ["", f"## Refutees ({len(refutees)}) -- connaissance acquise, plus de calcul", ""]
    lignes += [f"- {x['direction']} {x['horizon_h']} h {x['predicats'] or 'aucun filtre'} : explo "
               f"{_fmt(x['exploration'].get('moyenne_bps'))} bps, IC95 {x['exploration'].get('ic95')}" for x in refutees[:20]]
    naifs = [x for x in r["resultats"] if not x["predicats"]]
    lignes += ["", "## References : copie naive (sans filtre) et absence de trade (0)", ""]
    lignes += [f"- {x['direction']} {x['horizon_h']} h : selection {_fmt(x['selection'].get('moyenne_bps'))} bps/decision-jour, "
               f"exploration {_fmt(x['exploration'].get('moyenne_bps'))}, "
               f"valid {_fmt(x.get('validation', {}).get('moyenne_bps'))}" for x in naifs]
    lignes += ["", "## Hypotheses declarees", "",
               "- instant d'observation des episodes de backfill SUPPOSE (fill + 60 s) ; entree a la cloture 1 h suivante "
               "(jusqu'a 61 min apres : prudent pour un suivi lent, aveugle aux signaux rapides) ;",
               "- demi-ecart mesure sur les carnets quand il existe, sinon 8 bps (prudent) ; glissement 1 bp par cote ;",
               "- pas de file d'attente ni de fill partiel (ordres taker de 20 USD sur 100 USD) ; funding porte inclus ;",
               "- les clones d'un meme operateur ne sont pas regroupes en mode episodes (38 vaults) ;",
               "- SURVIVANT : l'historique de la liste suivie compte 317 adresses, le coffre n'a d'episodes que pour les "
               "vaults encore suivis ; les decisions post-entree des vaults retires depuis manquent (biais pro-survivants) ;",
               "- une position par (leader, coin, sens) : une decision prise pendant qu'une copie est tenue est ignoree.", ""]
    return "\n".join(lignes)


def periodique(root: Path, *, maintenant: float | None = None, lancer=None, ram_min_go: float = 2.0) -> dict[str, Any]:
    """Faut-il un passage maintenant ? Coffre change (au plus toutes les 30 min), sinon toutes les 6 h. Le passage
    tourne dans un SOUS-PROCESSUS (memoire rendue a chaque fois) et n'est lance que si la machine a au moins
    ``ram_min_go`` Go libres : sinon il est REPORTE (les collecteurs passent avant). Partage par la boucle du labo
    (``alina_quant_lab_console``) et par ``--en-continu`` : un seul etat, ``BOUCLE_LABO.json``, et le verrou du passage."""
    import subprocess

    maintenant = time.time() if maintenant is None else maintenant
    etat_path = root / ETAT_DIR / "BOUCLE_LABO.json"
    index = root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    etat = _lire_json(etat_path, {})
    try:
        empreinte = f"{index.stat().st_mtime_ns}:{index.stat().st_size}"
    except OSError:
        return {"lance": False, "raison": "coffre LOCAL absent"}
    depuis = maintenant - float(etat.get("dernier_lancement", 0.0))
    neuf = empreinte != etat.get("empreinte_coffre")
    if not ((neuf and depuis >= 1800) or depuis >= 6 * 3600):
        return {"lance": False, "raison": "rien de neuf ou trop tot", "depuis_s": round(depuis)}
    if lancer is None:
        try:
            import psutil

            libre = psutil.virtual_memory().available / 1024 ** 3
        except Exception:  # noqa: BLE001 -- sans mesure, on ne bloque pas
            libre = float("inf")
        if libre < ram_min_go:
            return {"lance": False, "raison": f"memoire basse ({libre:.1f} Go libres < {ram_min_go} Go) : passage reporte"}
        lancer = lambda cmd: subprocess.run(cmd, cwd=str(root), timeout=3600, check=False).returncode  # noqa: E731
    try:
        code = lancer([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--root", str(root)])
    except Exception as erreur:  # noqa: BLE001 -- le moteur ne doit jamais interrompre la boucle qui l'appelle
        code = f"{type(erreur).__name__}: {erreur}"
    try:
        _ecrire_json(etat_path, {"dernier_lancement": maintenant, "empreinte_coffre": empreinte, "dernier_code": code})
    except OSError:
        pass
    return {"lance": True, "code": code}


def en_continu(root: Path, *, pause_s: float = 60.0) -> int:
    """Boucle LEGERE : seulement le moteur de decouverte, sans la reconstitution SAFE du labo (qui peut occuper ~9 Go
    pendant des heures). Ctrl+C ou fermer la fenetre l'arrete ; un passage en cours finit ou rend son verrou."""
    print(f"[EN CONTINU] moteur de decouverte en boucle (controle toutes les {pause_s:.0f} s ; coffre change = passage "
          "au plus toutes les 30 min, sinon toutes les 6 h ; jamais sous 2 Go libres). Ctrl+C pour arreter.", flush=True)
    try:
        while True:
            r = periodique(root)
            if r.get("lance") or "memoire basse" in str(r.get("raison")):
                print(f"[EN CONTINU] {time.strftime('%d/%m %H:%M')} {r}", flush=True)
            time.sleep(pause_s)
    except KeyboardInterrupt:
        print("[EN CONTINU] arrete.", flush=True)
        return 130


def main(argv: list[str] | None = None) -> int:
    """Une erreur inattendue est JOURNALISEE et l'etape rend 0 : les etapes suivantes du labo tournent quand meme."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=RACINE)
    parser.add_argument("--banc", action="store_true")
    parser.add_argument("--campagne", action="store_true")
    parser.add_argument("--suivi", action="store_true")
    # 27/11 : 48 mondes par taille d'avantage (96 paires) -- en dessous, le banc ne peut presque jamais prouver un gain
    # du niveau mesure pour le nombre effectif d'essais (9 contre 0 sur 96 paires) ; ~7 min, au plus toutes les 6 h.
    parser.add_argument("--mondes", type=int, default=48)
    parser.add_argument("--sans-ecarts-mesures", action="store_true", help="ne lit pas les carnets (8 bps partout)")
    parser.add_argument("--sans-ecriture", action="store_true")
    parser.add_argument("--en-continu", action="store_true",
                        help="boucle LEGERE : seulement le moteur, au rythme de la boucle du labo (Ctrl+C pour arreter)")
    parser.add_argument("--confirmer", default=None, metavar="CHAMP=VALEUR",
                        help="banc de CONFIRMATION d'une seule variante de methode annoncee (ex. essais_effectifs=true)")
    args = parser.parse_args(argv)
    if args.en_continu:
        return en_continu(args.root.resolve())
    try:
        return _main(args)
    except Exception as erreur:  # noqa: BLE001 -- l'etape ne doit jamais interrompre le lanceur du labo
        import traceback

        racine = args.root.resolve()
        try:
            (racine / ETAT_DIR).mkdir(parents=True, exist_ok=True)
            (racine / ETAT_DIR / "DERNIERE_ERREUR.txt").write_text(traceback.format_exc(), encoding="utf-8")
        except OSError:
            pass
        print(f"[ERREUR] decouverte : {type(erreur).__name__}: {erreur} -- detail dans {ETAT_DIR / 'DERNIERE_ERREUR.txt'} ; "
              "etape ignoree, le labo continue.", flush=True)
        return 0


def _main(args: argparse.Namespace) -> int:
    """Un seul passage a la fois (verrou partage du depot) : la boucle du labo et un lancement manuel ne peuvent pas
    ecrire ensemble dans le registre des essais ni dans l'etat du champion."""
    from hl_observer.ops import verrou_pid as VP

    verrou = args.root.resolve() / ETAT_DIR / "decouverte.lock"
    obtenu, pourquoi = VP.prendre(verrou, perime_s=4 * 3600, quoi="un passage du moteur de decouverte")
    if not obtenu:
        print(f"[OCCUPE] {pourquoi} : etape ignoree, le labo continue.", flush=True)
        return 0
    try:
        return _passage(args)
    finally:
        VP.rendre(verrou)


def _passage(args: argparse.Namespace) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    root = args.root.resolve()
    tous = not (args.banc or args.campagne or args.suivi)
    if not (root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").is_file():
        print("[UNMEASURABLE] coffre LOCAL absent : etape ignoree, le labo continue.")
        return 0
    config = D.DecouverteConfig()
    table, meta = construire_table(root, config=config, ecarts_mesures=not args.sans_ecarts_mesures)
    if not len(table):
        print(f"[UNMEASURABLE] {meta.get('raison', 'aucune decision mesurable')} : etape ignoree, le labo continue.")
        return 0
    pops = table["population"].value_counts().to_dict()
    print(f"[decouverte] table {meta.get('cache')} : {len(table):,} decisions {pops}", flush=True)
    write = not args.sans_ecriture
    if args.banc or tous:
        faire_banc(root, table, config=config, write=write, mondes=args.mondes, confirmer=args.confirmer)
    if args.campagne or tous:
        faire_campagne(root, table, meta, config=config, write=write)
    if args.suivi or tous:
        faire_suivi(root, table, config=config, write=write)
    print("[FIN] decouverte CopyVault (PAPER, exploratoire) : aucune rentabilite n'est prouvee par une campagne.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
