"""Collecteur causal par poll REST « forward » des fills de leaders.

Casse le plafond WebSocket (~10 userFills/IP de Hyperliquid) en suivant des
leaders SUPPLÉMENTAIRES via le endpoint REST ``info/userFillsByTime`` (non soumis
au cap WS), avec une discipline anti-look-ahead stricte (voir
``hl_observer.collection.forward_poll_fills``) :

- 1re observation d'un leader -> fixe le high-water, n'émet AUCUN fill causal
  (fills préexistants = snapshot) ;
- passes suivantes -> n'émet que les fills strictement nouveaux, estampillés à
  l'instant RÉEL du poll (``observed_at_ms``), source ``LIVE_POLL``.

LECTURE SEULE / PAPER : aucune clé, aucun ordre, aucune signature. Produit un
flux de fills causaux (``source_id = hyperliquid_public_userfills_poll``) que le
pipeline de shards SAFE ingère exactement comme les autres collecteurs ; la
matérialisation les classe ``LIVE_POLL`` (causal, à parité avec ``LIVE_WS``).
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from hl_observer.collection.forward_poll_fills import (
    LIVE_POLL_SOURCE,
    RESPONSE_PAGE_CAP,
    LeaderCooldown,
    LeaderWatermark,
    TokenBucket,
    CADENCE_ARCHIVE,
    cadence_plan,
    class_interval_s,
    staggered_first_due_ms,
    collector_stream_health,
    partition_forward_fills,
    prioritize_leaders,
    shard_leaders,
)

URL_HL = "https://api.hyperliquid.xyz/info"
POLL_SOURCE_ID = "hyperliquid_public_userfills_poll"
RACINE = Path(__file__).resolve().parents[1]
OUT_FILLS = Path("runtime") / "data" / "vault_fills_poll.jsonl"
STATE_PATH = Path("runtime") / "data" / "userfills_poll_watermarks.json"
# Fenêtre d'amorçage à la 1re observation : assez pour fixer un high-water récent
# sans jamais émettre ces fills comme causaux.
BOOTSTRAP_LOOKBACK_MS = 3_600_000  # 1 h
BESOINS_COLLECTE = Path("runtime") / "data" / "copy_vault_besoins_collecte.json"
CADENCE_AUDIT = Path("runtime") / "data" / "poll_cadence_plan.ndjson"  # pas « .jsonl » : ce n est pas un flux de collecte
ARCHIVE_SAMPLE_MS = 120_000  # fenêtre relue pour un leader en cadence d'archive


def charger_plan_cadence(root: Path, leaders: list[str]) -> tuple[dict[str, str], dict[str, Any]]:
    """Plan de cadence du labo pour les leaders suivis + trace d'audit.

    ``ALINA_POLL_CADENCE_LABO=0`` désactive le plan (cadence adaptative historique). Le plan
    est une préférence de budget : absent, illisible ou désactivé, rien n'est bloqué. Chaque
    application est journalisée (``poll_cadence_plan.ndjson``) pour que tout écart de densité
    d'observation entre leaders reste traçable par le labo (aucun biais de sélection caché).
    """
    audit: dict[str, Any] = {"applique": False, "raison": "plan_absent"}
    if os.environ.get("ALINA_POLL_CADENCE_LABO", "1").strip() == "0":
        audit["raison"] = "desactive_par_operateur"
        return {}, audit
    try:
        besoins = json.loads((root / BESOINS_COLLECTE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, audit
    plan_complet = cadence_plan(besoins)
    plan = {v: plan_complet[v.lower()] for v in leaders if v.lower() in plan_complet}
    par_classe: dict[str, int] = {}
    for classe in plan.values():
        par_classe[classe] = par_classe.get(classe, 0) + 1
    audit = {
        "applique": bool(plan), "raison": "plan_labo" if plan else "aucun_leader_classe",
        "experiment_id": besoins.get("experiment_id") if isinstance(besoins, dict) else None,
        "leaders": len(leaders), "classes": dict(sorted(par_classe.items())),
        "non_classes": len(leaders) - len(plan),
    }
    return plan, audit


def _journaliser_cadence(root: Path, audit: dict[str, Any]) -> None:
    try:
        chemin = root / CADENCE_AUDIT
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with chemin.open("a", encoding="utf-8") as flux:
            flux.write(json.dumps({"ts_ms": int(time.time() * 1000), **audit}, ensure_ascii=False) + "\n")
    except OSError:
        pass  # l'audit ne doit jamais arrêter la collecte


# Le débit est désormais régulé par ``TokenBucket`` (global, maximise les
# requêtes sous le plafond HL) + ``LeaderCooldown`` (backoff 429 par leader),
# tous deux importés de ``forward_poll_fills`` et prouvés par tests.


_UA_POLL = {"Content-Type": "application/json", "User-Agent": "alina-smart-flow/poll (read-only)"}


def _retry_after_s(exc: Any) -> float | None:
    """Secondes demandées par le serveur via l'en-tête Retry-After (bornées)."""
    try:
        h = getattr(exc, "headers", None)
        v = h.get("Retry-After") if h else None
        s = float(v) if v else None
        return s if (s is not None and 0 < s <= 60) else None
    except (ValueError, AttributeError, TypeError):
        return None


def _post_userfills(vault: str, start_ms: int, end_ms: int, *, timeout_s: float = 10.0,
                    tentatives: int = 2) -> Any:
    """userFillsByTime avec retry des blips RÉSEAU transitoires (timeout/URLError).
    Les HTTPError (dont 429) remontent telles quelles : l'AIMD global DOIT les voir
    pour ralentir. Aucun ordre, aucune clé, aucune signature."""
    corps = json.dumps(
        {"type": "userFillsByTime", "user": vault,
         "startTime": int(start_ms), "endTime": int(end_ms)}
    ).encode("utf-8")
    derniere: Exception | None = None
    for essai in range(1, max(1, tentatives) + 1):
        req = urllib.request.Request(URL_HL, data=corps, headers=_UA_POLL)
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as rep:  # noqa: S310 (URL constante)
                return json.loads(rep.read().decode("utf-8"))
        except urllib.error.HTTPError:
            raise  # 429 & co. DOIVENT remonter a l'AIMD (ne jamais masquer le signal)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            derniere = exc
            if essai < tentatives:
                time.sleep(0.4 * essai)  # blip transitoire -> courte attente puis retry
                continue
            raise
    if derniere is not None:
        raise derniere
    raise RuntimeError("userFillsByTime: tentatives epuisees")


def _load_state(path: Path) -> dict[str, LeaderWatermark]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(vault): LeaderWatermark.from_state(state)
        for vault, state in raw.items()
        if isinstance(state, dict)
    }


def _save_state(path: Path, state: dict[str, LeaderWatermark]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {vault: wm.to_state() for vault, wm in state.items()}
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _append_fills(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps({**row, "source_id": POLL_SOURCE_ID}, ensure_ascii=False) + "\n")


def poll_once(
    root: Path,
    leaders: list[str],
    state: dict[str, LeaderWatermark],
    *,
    poster=_post_userfills,
    now_ms: int | None = None,
    bucket=None,
    cooldown=None,
    echantillon_ms: dict[str, int] | None = None,
) -> int:
    """Une passe de poll sur tous les leaders. Renvoie le nombre de fills causaux
    émis. Pur vis-à-vis de l'horloge/HTTP via ``poster``/``now_ms`` (testable).
    ``bucket`` (TokenBucket) régule le débit global ; ``cooldown`` (LeaderCooldown)
    met en pause un leader fautif (429) sans pénaliser les autres.

    ``echantillon_ms`` (leader -> fenêtre en ms) : pour un leader en cadence d'archive, on ne
    relit qu'une fenêtre RÉCENTE et bornée (2 pages max) au lieu de rattraper tout
    l'intervalle : c'est un échantillon assumé de son activité, pas un flux complet. Les fills
    émis restent causaux (observés dans la fenêtre) ; ceux d'entre deux relevés ne sont pas
    collectés — jamais reconstitués après coup."""
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    emitted = 0
    n_429 = 0           # throttles serveur (comportement adaptatif, PAS une erreur)
    n_blip = 0          # blips reseau transitoires
    dernier_blip = ""
    retry_after_max = 0.0
    for vault in leaders:
        if cooldown is not None and not cooldown.due(vault, now_ms):
            continue  # #3 ce leader est en backoff 429 -> on passe au suivant
        wm = state.get(vault, LeaderWatermark())
        # Plancher dur : jamais démarrer plus de BOOTSTRAP_LOOKBACK avant maintenant.
        # Sinon un high_water périmé (ex. 0) ferait tirer des MOIS d'historique et
        # l'émettrait comme « causal » — la pollution que l'on élimine ici.
        fenetre = (echantillon_ms or {}).get(vault)
        lookback = BOOTSTRAP_LOOKBACK_MS if not fenetre else max(1_000, min(int(fenetre), BOOTSTRAP_LOOKBACK_MS))
        floor_start = max(1, now_ms - lookback)
        start_ms = max(wm.high_water_ms, floor_start) if wm.initialised else floor_start
        # Amorçage : une seule page suffit à fixer le high-water (fills exclus).
        # Forward : pagination complète pour ne perdre aucun nouveau fill
        # (échantillon d'archive : 2 pages au plus, coût borné).
        max_pages = 1 if not wm.initialised else (2 if fenetre else 8)
        try:
            fills = _fetch_all_fills(poster, vault, start_ms, now_ms, max_pages=max_pages, bucket=bucket)
        except Exception as exc:  # noqa: BLE001 (collecteur résilient, fail-soft)
            if cooldown is not None:
                cooldown.penalize(vault, now_ms)  # 429/erreur -> backoff ce leader
            if getattr(exc, "code", None) == 429:
                n_429 += 1
                if bucket is not None:
                    bucket.penalize()  # 429 = limite IP globale -> pause TOUT le poll
                ra = _retry_after_s(exc)
                if ra:
                    retry_after_max = max(retry_after_max, ra)
            else:
                n_blip += 1
                dernier_blip = f"{vault[:10]} {type(exc).__name__}: {str(exc)[:50]}"
            continue
        if cooldown is not None:
            cooldown.reset(vault)  # succès -> on réarme le leader
        if bucket is not None:
            bucket.reward()  # requête OK -> on relâche progressivement la pause
        for fill in fills:
            if isinstance(fill, dict):
                fill.setdefault("vault", vault)
        causal, new_wm = partition_forward_fills(wm, fills, observed_at_ms=now_ms)
        state[vault] = new_wm
        _append_fills(root / OUT_FILLS, causal)
        _LAST_FILL_COUNT[vault] = len(causal)
        emitted += len(causal)
    # Log GROUPÉ et propre : un 429 géré par l'AIMD est un THROTTLE (flow control),
    # pas une erreur. On n'écrit qu'une ligne/passe au lieu d'une par leader.
    if n_429:
        extra = f" (serveur demande ~{retry_after_max:.0f}s)" if retry_after_max else ""
        print(f"[poll] throttle 429 x{n_429} — pause adaptative AIMD{extra}", flush=True)
    if n_blip:
        print(f"[poll] {n_blip} blip(s) reseau transitoire(s) — ex: {dernier_blip}", flush=True)
    # Respecte le Retry-After du serveur (borné) : on ne re-tape pas avant l'heure.
    if retry_after_max:
        time.sleep(min(retry_after_max, 10.0))
    return emitted


#: Nombre de fills causaux émis au dernier poll par leader (pour la cadence adaptative S2).
_LAST_FILL_COUNT: dict[str, int] = {}


def _fetch_all_fills(poster, vault: str, start_ms: int, now_ms: int, *, max_pages: int = 8, bucket=None) -> list[dict[str, Any]]:
    """Solution #1 — pagination complète : si une page atteint le cap de réponse,
    on continue à paginer jusqu'à capturer TOUS les nouveaux fills (aucun perdu).
    La déduplication finale est assurée par le high-water de ``partition_forward_fills``.
    ``bucket`` (TokenBucket) régule le débit avant chaque requête (anti-429)."""
    collected: list[dict[str, Any]] = []
    cursor = int(start_ms)
    for _ in range(max_pages):
        if bucket is not None:
            bucket.take()
        page = poster(vault, cursor, now_ms)
        if not isinstance(page, list) or not page:
            break
        collected.extend(f for f in page if isinstance(f, dict))
        if len(page) < RESPONSE_PAGE_CAP:
            break  # page non pleine -> tout est capturé
        times = [int(f["time"]) for f in page if isinstance(f.get("time"), int) and not isinstance(f.get("time"), bool)]
        if not times:
            break
        nxt = max(times)
        if nxt <= cursor:
            break  # pas de progrès -> on s'arrête (anti-boucle)
        cursor = nxt
    return collected


DEFAULT_LEADERS_FILE = "runtime/data/copy_whitelist.json"


def _extract_vaults(data: Any) -> list[str]:
    """Extrait des adresses de leaders depuis divers formats (robuste, fail-soft)."""
    if isinstance(data, dict):
        for key in ("vaults", "whitelist", "adresses", "addresses", "retenus", "leaders",
                    "candidats", "actifs"):
            if key in data:
                return _extract_vaults(data[key])
        # dict {adresse: ...} -> les clés qui ressemblent à une adresse
        return [str(k).strip() for k in data if str(k).strip().lower().startswith("0x")]
    if isinstance(data, list):
        out: list[str] = []
        for item in data:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                for key in ("address", "adresse", "vault", "user", "leader"):
                    val = item.get(key)
                    if isinstance(val, str) and val.strip():
                        out.append(val.strip())
                        break
        return out
    return []


#: Solution #5 — couverture maximale : à défaut de liste explicite, le poll
#: fusionne toutes les sources de leaders disponibles (whitelist prédictive +
#: vaults scorés + vaults suivis + liste ADAPTATIVE curés+actifs) pour suivre le
#: plus de leaders candidats. ``config/copy_vault_leaders.json`` est produit par
#: ``fusionner_leaders_actifs.py`` (base curée + traders ACTIFS découverts par
#: l'explorer) : c'est ce qui diversifie les fills au lieu de suivre des leaders inactifs.
_DEFAULT_LEADER_SOURCES = (
    DEFAULT_LEADERS_FILE,
    "runtime/data/vaults_scores.json",
    "runtime/data/vaults_suivis.json",
    "config/copy_vault_leaders.json",
    "config/copy_vault_leaders_candidats.json",
)


def _lire_fichier_leaders(chemin: Path) -> list[str]:
    try:
        return _extract_vaults(json.loads(chemin.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return []


def _lire_archives(args: argparse.Namespace, root: Path) -> list[str]:
    """Adresses que la fusion a rangées en cadence d'archive (clé ``vaults_archive``)."""
    if args.leaders:
        return []
    sources = [args.leaders_file] if args.leaders_file else list(_DEFAULT_LEADER_SOURCES)
    vus: dict[str, None] = {}
    for src in sources:
        try:
            data = json.loads((root / src).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("vaults_archive"), list):
            for v in data["vaults_archive"]:
                if isinstance(v, str) and v.strip().lower().startswith("0x") and len(v.strip()) >= 10:
                    vus.setdefault(v.strip(), None)
    return list(vus)


def archives_a_suivre(root: Path, suivis: list[str], archives: list[str]) -> list[str]:
    """Archives réellement suivies : seulement celles que le plan du labo, présent ICI, classe
    ``ARCHIVE``. Sans plan (lane cloud, plan désactivé ou illisible) : aucune — interrogées à
    pleine cadence, elles prendraient le budget des leaders utiles."""
    if not archives:
        return []
    plan, _audit = charger_plan_cadence(root, archives)
    deja = {v.lower() for v in suivis}
    return [v for v in archives if plan.get(v) == CADENCE_ARCHIVE and v.lower() not in deja]


def _lire_retenus(root: Path) -> list[str]:
    """#2 Leaders « retenus » (scorés/forte valeur) depuis vaults_scores.json."""
    try:
        data = json.loads((root / "runtime/data/vaults_scores.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    ret = data.get("retenus") if isinstance(data, dict) else None
    return [str(v) for v in ret] if isinstance(ret, list) else []


#: Flux surveillés par la page de santé : (nom, chemin, intervalle attendu ms).
#: L'intervalle attendu DÉPEND de la cadence réelle du flux : au-delà, STALE ;
#: au-delà de 10x, FIGÉ. Un flux « backfill » (cadence 4 h) ne doit PAS être
#: signalé figé après 2 min — d'où les intervalles par flux.
_MIN = 60_000.0
_STREAMS_SURVEILLES = (
    ("Fills poll (LIVE_POLL)", "runtime/data/vault_fills_poll.jsonl", 3 * _MIN),
    ("Fills live (LIVE_WS)", "runtime/data/vault_fills_live.jsonl", 5 * _MIN),
    ("Carnets BBO", "runtime/data/bbo_tape.jsonl", 3 * _MIN),
    ("Carnets L2 copy-vault", "runtime/data/copy_vault_l2_tape.jsonl", 3 * _MIN),
    ("Carnets venues", "runtime/data/carnet_venues.jsonl", 5 * _MIN),
    ("Fills journal", "runtime/data/fills_journal.jsonl", 5 * _MIN),
    ("Snapshots vaults", "runtime/data/vault_snapshots.jsonl", 10 * _MIN),
    # Sorties de BACKFILL (cadence ~4 h) : intervalle large, sinon faux « FIGÉ ».
    ("Vault fills (backfill ~4h)", "runtime/data/vault_fills.jsonl", 360 * _MIN),
    ("Vault épisodes (backfill ~4h)", "runtime/data/vault_episodes.jsonl", 360 * _MIN),
)


def _streams_health(root: Path, now_ms: float) -> list[dict[str, Any]]:
    """#5 Santé de chaque flux collecté : taille, dernier écrit, âge, verdict.
    Répond directement à « est-ce que ça monte ? » sans deviner."""
    out: list[dict[str, Any]] = []
    for nom, rel, intervalle_ms in _STREAMS_SURVEILLES:
        p = root / rel
        try:
            st = p.stat()
            mtime_ms = st.st_mtime * 1000.0
            taille = st.st_size
        except OSError:
            mtime_ms, taille = 0.0, 0
        verdict = collector_stream_health(mtime_ms, now_ms, expected_interval_ms=intervalle_ms)
        # Âge borné à 0 : un mtime légèrement « futur » (écrit pendant la passe)
        # ne doit pas afficher un âge négatif.
        age_s = max(0.0, round((now_ms - mtime_ms) / 1000.0, 1)) if mtime_ms else None
        out.append({
            "nom": nom, "fichier": rel, "taille_octets": taille,
            "dernier_ecrit_ms": int(mtime_ms), "age_s": age_s, "verdict": verdict,
        })
    return out


def _fmt_octets(n: float) -> str:
    taille = float(n)
    for unite in ("o", "Ko", "Mo", "Go"):
        if taille < 1024.0 or unite == "Go":
            return f"{taille:.0f} {unite}" if unite == "o" else f"{taille:.1f} {unite}"
        taille /= 1024.0
    return f"{taille:.1f} Go"


def _ecrire_page_sante(root: Path, now_ms: float, resume: dict[str, Any]) -> None:
    """Écrit une page HTML + un JSON de santé des collecteurs (la « page du
    collecteur » : ce qui monte, ce qui est figé, et le débit du poll)."""
    streams = _streams_health(root, now_ms)
    snap = {"genere_ms": int(now_ms), "resume_poll": resume, "flux": streams}
    page_dir = root / "runtime" / "data"
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "collecteurs_sante.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")

    couleur = {"FRESH": "#39d98a", "STALE": "#f5a623", "DEAD": "#ff5c5c", "ABSENT": "#8892a0"}
    etiquette = {"FRESH": "MONTE", "STALE": "EN RETARD", "DEAD": "FIGÉ", "ABSENT": "ABSENT"}
    lignes = []
    for s in streams:
        c = couleur.get(s["verdict"], "#8892a0")
        age = f"{s['age_s']:.0f} s" if s["age_s"] is not None else "—"
        lignes.append(
            f"<tr><td>{s['nom']}</td><td style='text-align:right'>{_fmt_octets(s['taille_octets'])}</td>"
            f"<td style='text-align:right'>{age}</td>"
            f"<td style='text-align:center'><b style='color:{c}'>{etiquette.get(s['verdict'], s['verdict'])}</b></td></tr>"
        )
    html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="5">
<title>Santé collecteurs</title><style>
:root{{color-scheme:dark}}body{{margin:0;background:#0d1117;color:#e6edf3;font:14px/1.5 system-ui,sans-serif;padding:24px}}
h1{{font-size:20px;margin:0 0 4px}}.sub{{color:#8892a0;margin:0 0 20px}}
table{{width:100%;max-width:760px;border-collapse:collapse}}th,td{{padding:8px 10px;border-bottom:1px solid #222b36}}
th{{text-align:left;color:#8892a0;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:0 0 20px}}.card{{background:#161b22;border:1px solid #222b36;border-radius:10px;padding:12px 16px;min-width:120px}}
.card .v{{font-size:22px;font-weight:700}}.card .l{{color:#8892a0;font-size:12px}}</style></head><body>
<h1>Santé des collecteurs</h1>
<p class="sub">Généré à {time.strftime('%H:%M:%S', time.localtime(now_ms/1000))} — rafraîchissement auto 5 s. « MONTE » = écrit dans les 2 dernières min.</p>
<div class="cards">
<div class="card"><div class="v">{resume.get('leaders', 0)}</div><div class="l">leaders suivis</div></div>
<div class="card"><div class="v">{resume.get('polles', 0)}</div><div class="l">pollés (dernière passe)</div></div>
<div class="card"><div class="v">{resume.get('fills_emis', 0)}</div><div class="l">fills causaux (passe)</div></div>
<div class="card"><div class="v">{resume.get('en_backoff', 0)}</div><div class="l">leaders en backoff 429</div></div>
</div>
<table><thead><tr><th>Flux collecté</th><th style="text-align:right">Taille</th><th style="text-align:right">Âge</th><th style="text-align:center">État</th></tr></thead>
<tbody>{''.join(lignes)}</tbody></table>
<p class="sub" style="margin-top:20px">Lecture seule / PAPER. Fills poll causaux (discipline high-water), source {LIVE_POLL_SOURCE}.</p>
</body></html>"""
    (page_dir / "collecteurs_sante.html").write_text(html, encoding="utf-8")


def _lire_leaders(args: argparse.Namespace, root: Path) -> list[str]:
    if args.leaders:
        vaults = [v.strip() for v in args.leaders.split(",") if v.strip()]
    elif args.leaders_file:
        vaults = _lire_fichier_leaders(root / args.leaders_file)
    else:
        vaults = []
        for src in _DEFAULT_LEADER_SOURCES:
            vaults += _lire_fichier_leaders(root / src)
    # Déduplique en conservant l'ordre, ne garde que des adresses plausibles.
    vus: dict[str, None] = {}
    for v in vaults:
        if v.lower().startswith("0x") and len(v) >= 10:
            vus.setdefault(v, None)
    return list(vus)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Poll causal userFillsByTime (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--leaders", default="", help="liste de vaults séparés par des virgules")
    p.add_argument("--leaders-file", default="", help="JSON {\"vaults\": [...]} relatif à root")
    p.add_argument("--intervalle", type=float, default=5.0, help="cadence de poll de base (s)")
    p.add_argument("--shard-count", type=int, default=1, help="nb de lanes (IP) distinctes")
    p.add_argument("--shard-index", type=int, default=0, help="index de cette lane [0, count)")
    p.add_argument("--max-requests-per-min", type=float, default=55.0,
                   help="débit MAX de requêtes/min (token-bucket AIMD, anti-429). HL ~60/min")
    p.add_argument("--max-leaders", type=int, default=0,
                   help="0=illimité ; sinon ne suit que les N leaders de plus forte valeur "
                        "(polls fiables -> fills FRAIS), le reste va sur d'autres lanes/IP")
    p.add_argument("--min-request-interval", type=float, default=0.0,
                   help="(déprécié) remplacé par --max-requests-per-min")
    p.add_argument("--une-fois", action="store_true")
    args = p.parse_args(argv)
    root = Path(args.root)
    # S3 : cette lane ne suit qu'une tranche disjointe des leaders.
    suivis = _lire_leaders(args, root)
    suivis += archives_a_suivre(root, suivis, _lire_archives(args, root))   # jamais sans plan labo
    leaders = shard_leaders(suivis, args.shard_count, args.shard_index)
    # #2 priorisation : les leaders retenus (forte valeur) sont pollés en premier.
    leaders = prioritize_leaders(leaders, _lire_retenus(root))
    if args.max_leaders and args.max_leaders > 0:
        leaders = leaders[:args.max_leaders]  # focalise le budget sur les meilleurs
    if not leaders:
        print("[poll] aucun leader à suivre (voir --leaders / --leaders-file / --shard-*)", flush=True)
        return 0
    state = _load_state(root / STATE_PATH)
    base = max(2.0, float(args.intervalle))
    # #1 débit régulé par token-bucket (maximise les requêtes sous le plafond HL).
    rpm = max(1.0, float(args.max_requests_per_min))
    bucket = TokenBucket(rate_per_s=rpm / 60.0, burst=min(10.0, max(1.0, rpm / 6.0)))
    cooldown = LeaderCooldown()  # #3 backoff 429 par leader
    due_ms: dict[str, float] = {v: 0.0 for v in leaders}
    # Budget piloté par le labo : les robots HFT (non copiables) et les clones d'un même
    # opérateur passent en cadence d'archive ; le budget libéré profite aux opérateurs lents.
    plan, audit_cadence = charger_plan_cadence(root, leaders)
    _journaliser_cadence(root, audit_cadence)
    print(f"[poll] cadence labo: {audit_cadence}", flush=True)
    echantillon_ms = {v: ARCHIVE_SAMPLE_MS for v, classe in plan.items() if classe == CADENCE_ARCHIVE}
    due_ms = staggered_first_due_ms(leaders, plan, time.time() * 1000.0)   # archives étalées sur 30 min
    # Pidfile : le lanceur tue CE PID au nettoyage (le poll tourne sans fenêtre).
    pid_path = root / "runtime" / "data" / "poll_leaders.pid"
    try:
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    # Écrit la page de santé immédiatement pour qu'elle existe à l'ouverture auto.
    try:
        _ecrire_page_sante(root, time.time() * 1000.0,
                           {"leaders": len(leaders), "polles": 0, "fills_emis": 0, "en_backoff": 0})
    except Exception:  # noqa: BLE001
        pass
    while True:
        now = time.time() * 1000.0
        # S2 : ne poll que les leaders « dus » ; cadence adaptative à l'activité.
        a_poller = [v for v in leaders if due_ms.get(v, 0.0) <= now]
        emitted = poll_once(root, a_poller, state, now_ms=int(now), bucket=bucket, cooldown=cooldown,
                            echantillon_ms=echantillon_ms) if a_poller else 0
        for v in a_poller:
            interval = class_interval_s(base, _LAST_FILL_COUNT.get(v, 0), plan.get(v))
            due_ms[v] = now + interval * 1000.0
        _save_state(root / STATE_PATH, state)  # #9 flush de l'état à chaque passe
        en_backoff = sum(1 for v in leaders if not cooldown.due(v, now))
        resume = {"leaders": len(leaders), "polles": len(a_poller), "fills_emis": emitted,
                  "en_backoff": en_backoff, "shard": f"{args.shard_index}/{args.shard_count}"}
        try:  # #5/#10 page de santé (fail-soft : ne doit jamais arrêter la collecte)
            _ecrire_page_sante(root, now, resume)
        except Exception as exc:  # noqa: BLE001
            print(f"[poll] page sante KO: {type(exc).__name__}", flush=True)
        print(
            f"[poll] {time.strftime('%H:%M:%S')} leaders={len(leaders)} pollés={len(a_poller)} "
            f"fills_causaux_emis={emitted} backoff={en_backoff} "
            f"shard={args.shard_index}/{args.shard_count} source={LIVE_POLL_SOURCE}",
            flush=True,
        )
        if args.une_fois:
            return 0
        time.sleep(min(base, 5.0))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
