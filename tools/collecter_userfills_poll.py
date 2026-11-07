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
import time
import urllib.request
from pathlib import Path
from typing import Any

from hl_observer.collection.forward_poll_fills import (
    LIVE_POLL_SOURCE,
    RESPONSE_PAGE_CAP,
    LeaderCooldown,
    LeaderWatermark,
    TokenBucket,
    adaptive_interval_s,
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


# Le débit est désormais régulé par ``TokenBucket`` (global, maximise les
# requêtes sous le plafond HL) + ``LeaderCooldown`` (backoff 429 par leader),
# tous deux importés de ``forward_poll_fills`` et prouvés par tests.


def _post_userfills(vault: str, start_ms: int, end_ms: int, *, timeout_s: float = 10.0) -> Any:
    corps = json.dumps(
        {"type": "userFillsByTime", "user": vault,
         "startTime": int(start_ms), "endTime": int(end_ms)}
    ).encode("utf-8")
    req = urllib.request.Request(URL_HL, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:  # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


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
) -> int:
    """Une passe de poll sur tous les leaders. Renvoie le nombre de fills causaux
    émis. Pur vis-à-vis de l'horloge/HTTP via ``poster``/``now_ms`` (testable).
    ``bucket`` (TokenBucket) régule le débit global ; ``cooldown`` (LeaderCooldown)
    met en pause un leader fautif (429) sans pénaliser les autres."""
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    emitted = 0
    for vault in leaders:
        if cooldown is not None and not cooldown.due(vault, now_ms):
            continue  # #3 ce leader est en backoff 429 -> on passe au suivant
        wm = state.get(vault, LeaderWatermark())
        # Plancher dur : jamais démarrer plus de BOOTSTRAP_LOOKBACK avant maintenant.
        # Sinon un high_water périmé (ex. 0) ferait tirer des MOIS d'historique et
        # l'émettrait comme « causal » — la pollution que l'on élimine ici.
        floor_start = max(1, now_ms - BOOTSTRAP_LOOKBACK_MS)
        start_ms = max(wm.high_water_ms, floor_start) if wm.initialised else floor_start
        # Amorçage : une seule page suffit à fixer le high-water (fills exclus).
        # Forward : pagination complète pour ne perdre aucun nouveau fill.
        max_pages = 1 if not wm.initialised else 8
        try:
            fills = _fetch_all_fills(poster, vault, start_ms, now_ms, max_pages=max_pages, bucket=bucket)
        except Exception as exc:  # noqa: BLE001 (collecteur résilient, fail-soft)
            if cooldown is not None:
                cooldown.penalize(vault, now_ms)  # 429/erreur -> backoff ce leader
            if bucket is not None and getattr(exc, "code", None) == 429:
                bucket.penalize()  # 429 = limite IP globale -> pause TOUT le poll
            print(f"[poll] {vault[:10]} erreur {type(exc).__name__}: {str(exc)[:80]}", flush=True)
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
        for key in ("vaults", "whitelist", "adresses", "addresses", "retenus", "leaders"):
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
#: vaults scorés + vaults suivis) pour suivre le plus de leaders candidats.
_DEFAULT_LEADER_SOURCES = (
    DEFAULT_LEADERS_FILE,
    "runtime/data/vaults_scores.json",
    "runtime/data/vaults_suivis.json",
)


def _lire_fichier_leaders(chemin: Path) -> list[str]:
    try:
        return _extract_vaults(json.loads(chemin.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return []


def _lire_retenus(root: Path) -> list[str]:
    """#2 Leaders « retenus » (scorés/forte valeur) depuis vaults_scores.json."""
    try:
        data = json.loads((root / "runtime/data/vaults_scores.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    ret = data.get("retenus") if isinstance(data, dict) else None
    return [str(v) for v in ret] if isinstance(ret, list) else []


#: Flux surveillés par la page de santé (nom lisible -> chemin relatif).
_STREAMS_SURVEILLES = {
    "Fills poll (LIVE_POLL)": "runtime/data/vault_fills_poll.jsonl",
    "Fills live (LIVE_WS)": "runtime/data/vault_fills_live.jsonl",
    "Carnets BBO": "runtime/data/bbo_tape.jsonl",
    "Carnets L2 copy-vault": "runtime/data/copy_vault_l2_tape.jsonl",
    "Carnets venues": "runtime/data/carnet_venues.jsonl",
    "Fills journal": "runtime/data/fills_journal.jsonl",
    "Vault fills (agrégé)": "runtime/data/vault_fills.jsonl",
    "Vault épisodes": "runtime/data/vault_episodes.jsonl",
    "Snapshots vaults": "runtime/data/vault_snapshots.jsonl",
}

#: Au-delà de 2 min sans écriture -> STALE ; au-delà de 20 min -> DEAD.
_SANTE_INTERVALLE_MS = 120_000.0


def _streams_health(root: Path, now_ms: float) -> list[dict[str, Any]]:
    """#5 Santé de chaque flux collecté : taille, dernier écrit, âge, verdict.
    Répond directement à « est-ce que ça monte ? » sans deviner."""
    out: list[dict[str, Any]] = []
    for nom, rel in _STREAMS_SURVEILLES.items():
        p = root / rel
        try:
            st = p.stat()
            mtime_ms = st.st_mtime * 1000.0
            taille = st.st_size
        except OSError:
            mtime_ms, taille = 0.0, 0
        verdict = collector_stream_health(mtime_ms, now_ms, expected_interval_ms=_SANTE_INTERVALLE_MS)
        out.append({
            "nom": nom, "fichier": rel, "taille_octets": taille,
            "dernier_ecrit_ms": int(mtime_ms), "age_s": round((now_ms - mtime_ms) / 1000.0, 1) if mtime_ms else None,
            "verdict": verdict,
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
                   help="débit max de requêtes/min (token-bucket, anti-429). HL ~60/min")
    p.add_argument("--min-request-interval", type=float, default=0.0,
                   help="(déprécié) remplacé par --max-requests-per-min")
    p.add_argument("--une-fois", action="store_true")
    args = p.parse_args(argv)
    root = Path(args.root)
    # S3 : cette lane ne suit qu'une tranche disjointe des leaders.
    leaders = shard_leaders(_lire_leaders(args, root), args.shard_count, args.shard_index)
    # #2 priorisation : les leaders retenus (forte valeur) sont pollés en premier.
    leaders = prioritize_leaders(leaders, _lire_retenus(root))
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
    while True:
        now = time.time() * 1000.0
        # S2 : ne poll que les leaders « dus » ; cadence adaptative à l'activité.
        a_poller = [v for v in leaders if due_ms.get(v, 0.0) <= now]
        emitted = poll_once(root, a_poller, state, now_ms=int(now), bucket=bucket, cooldown=cooldown) if a_poller else 0
        for v in a_poller:
            interval = adaptive_interval_s(base, _LAST_FILL_COUNT.get(v, 0))
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
