"""SONDE DE CONFIRMATION WS — diagnostic de TRANSPORT strictement lecture seule (rectif Flo 24/07).

Pour chacun des vaults d'un shard (par défaut le shard B, le « calme »), on ouvre une socket DIAGNOSTIC
TEMPORAIRE et on s'abonne à SON userFills, puis on attend :
  1) le `subscriptionResponse` correspondant (ACK), OU
  2) le premier `userFills` avec `data.user` correct et `isSnapshot=true` (SNAPSHOT).
Un vrai fill live (isSnapshot=false) du bon user est une preuve encore plus forte (FILL).
Sinon → TIMEOUT → le vault reste **PENDING** (jamais « confirmé » juste parce qu'il est calme).

Croisement REST (curseur) : on interroge `POST /info {"type":"userFills"}` et on garde le catch-up par
curseur. Si REST voit un fill PLUS RÉCENT que le curseur WS (et assez vieux pour que le WS ait dû le
recevoir), c'est que le WS l'a raté → le shard est **DÉFAILLANT** (à reconnecter immédiatement).

Cadence : sondes SÉQUENTIELLES espacées → très largement sous 30 nouvelles connexions/minute.
Aucun ordre, aucune clé, aucune signature, aucun /exchange : uniquement des abonnements PUBLICS en
lecture seule + un POST /info public. Diagnostic de transport SEULEMENT : ne touche AUCUN paramètre
stratégique (config_hash inchangé).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.collection import userfills_live as UL  # noqa: E402

WS_URL = "wss://api.hyperliquid.xyz/ws"
URL_HL_INFO = "https://api.hyperliquid.xyz/info"
CURSEURS_RELPATH = Path("runtime") / "data" / "userfills_curseurs.json"
SONDE_RELPATH = Path("runtime") / "data" / "sonde_confirmation.json"

CONN_MAX_PAR_MIN = 30                 # plafond DUR HL (nouvelles connexions/minute)
DELAI_ENTRE_SONDES_S = 4.0            # ≥ 60/15 : ≤ 15 nouvelles conn/min => TRÈS largement sous 30
TIMEOUT_SONDE_S = 12.0               # attente ACK/snapshot par vault avant PENDING
AGE_MIN_RETARD_MS = 45_000           # un fill REST doit être vieux d'au moins ça pour accuser le WS (anti-course)

CONFIRME = ("ACK", "SNAPSHOT", "FILL")


# ─────────────────────────────── cœur PUR (testable sans réseau) ───────────────────────────────

def classer_message(msg, vault_lc: str) -> str | None:
    """Classe un message WS pour une sonde ciblant `vault_lc` (déjà en minuscule) :
    "ACK" (subscriptionResponse userFills, user correspondant),
    "SNAPSHOT" (userFills isSnapshot=true, user correspondant),
    "FILL" (userFills isSnapshot=false, user correspondant : preuve live encore plus forte),
    None sinon. Tolérant à tout message hors-sujet."""
    if not isinstance(msg, dict):
        return None
    data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
    ch = msg.get("channel")
    if ch == "subscriptionResponse":
        sub = data.get("subscription") or {}
        if sub.get("type") == "userFills" and str(sub.get("user") or "").lower() == vault_lc:
            return "ACK"
        return None
    if ch == "userFills":
        if str(data.get("user") or "").lower() == vault_lc:
            return "SNAPSHOT" if data.get("isSnapshot") else "FILL"
    return None


def fills_rest_normalises(vault: str, rep) -> list[dict]:
    """Normalise une réponse REST `userFills` (liste brute de fills) via le MÊME parser que le WS
    (enveloppée comme un message userFills snapshot). Rend [] si illisible (jamais inventé)."""
    if not isinstance(rep, list):
        return []
    return UL.parser_message_userfills({"channel": "userFills",
                                        "data": {"user": vault, "isSnapshot": True, "fills": rep}}, vault=vault)


def fills_rest_en_retard(fills_rest: list[dict], curseur_ts, *, age_min_ms: float = AGE_MIN_RETARD_MS,
                         maintenant_ms: float | None = None) -> list[dict]:
    """Fills REST STRICTEMENT plus récents que le curseur WS ET assez vieux (le WS a eu le temps de les
    recevoir : âge ≥ age_min_ms). NON-VIDE ⇒ le WS a raté un fill que REST voit ⇒ shard DÉFAILLANT.
    `curseur_ts` None/0 (vault jamais entendu par le WS) ⇒ [] : on n'accuse pas sur l'historique."""
    cur = float(curseur_ts or 0)
    if cur <= 0:                                                  # pas de curseur => aucune base d'accusation
        return []
    now = maintenant_ms if maintenant_ms is not None else time.time() * 1000
    return [f for f in fills_rest
            if float(f.get("ts_ms") or 0) > cur and (now - float(f.get("ts_ms") or 0)) >= age_min_ms]


def verdict_global(resultats: list[dict]) -> dict:
    """Agrège les résultats de sonde : confirmés (ACK/SNAPSHOT/FILL) vs PENDING, + défauts éventuels."""
    conf = [r for r in resultats if r.get("verdict") in CONFIRME]
    pend = [r for r in resultats if r.get("verdict") not in CONFIRME]
    defauts = [r["vault"] for r in resultats if r.get("shard_defaillant")]
    return {"n_total": len(resultats), "n_confirmes": len(conf), "n_pending": len(pend),
            "confirmes": [r["vault"] for r in conf], "pending": [r["vault"] for r in pend],
            "shards_defaillants": defauts}


def intervalle_debit_s(n_max_par_min: int = CONN_MAX_PAR_MIN, *, marge: float = 2.0) -> float:
    """Délai minimal entre 2 nouvelles connexions pour rester sous `n_max_par_min`, avec marge (défaut ×2)."""
    return (60.0 / max(1, n_max_par_min)) * marge


def cle_fill(f) -> tuple | None:
    """CLÉ COMPOSITE d'un fill = (time, hash, tid, oid, coin) — robuste aux PLUSIEURS fills au même timestamp
    (même hash de tx mais tid distincts). Fonctionne sur un fill BRUT HL (WS ou REST userFillsByTime). None si
    illisible. `tid` (trade id) est l'identifiant réellement unique ; les autres composants le renforcent."""
    if not isinstance(f, dict):
        return None
    def g(*noms):
        for n in noms:
            if f.get(n) is not None:
                return f.get(n)
        return None
    t = g("time", "ts_ms")                                           # brut HL = 'time' ; toléré 'ts_ms' si déjà normalisé
    coin = g("coin")
    return (int(t) if t is not None else None, g("hash"), g("tid"), g("oid"),
            str(coin).upper() if coin else None)


def fills_manquants_par_id(fills_rest: list, cles_ws, *, age_min_ms: float = AGE_MIN_RETARD_MS,
                           maintenant_ms: float | None = None) -> list:
    """REST − WS PAR IDENTIFIANT : fills REST dont la CLÉ COMPOSITE n'est PAS dans l'ensemble des clés reçues
    par le WS, ET assez vieux (âge ≥ age_min_ms : le WS a eu le temps de les recevoir). NON-VIDE ⇒ le WS a
    raté un ou plusieurs fills que REST voit ⇒ shard DÉFAILLANT. Compare des ENSEMBLES, pas un simple curseur
    (détecte les fills au même timestamp)."""
    vus = {k for k in (cle_fill(x) if not isinstance(x, tuple) else x for x in cles_ws) if k is not None}
    now = maintenant_ms if maintenant_ms is not None else time.time() * 1000
    out = []
    for f in fills_rest:
        k = cle_fill(f)
        if k is None:
            continue
        t = k[0] or 0
        if k not in vus and (now - t) >= age_min_ms:
            out.append(f)
    return out


def fenetre_debut_ms(curseur_ts, demarrage_ms, maintenant_ms, *, overlap_ms: float = 60_000.0,
                     lookback_max_ms: float = 900_000.0) -> int:
    """startTime de `userFillsByTime` pour la réconciliation : depuis (curseur − chevauchement), mais JAMAIS
    avant le DÉMARRAGE (les clés WS en mémoire n'existent que depuis là → sinon faux « manquant » sur
    l'historique), ni au-delà d'un lookback max (borne le poids REST et reste sous la capacité de `_WS_KEYS`)."""
    plancher = max(float(demarrage_ms or 0.0), float(maintenant_ms) - lookback_max_ms)
    return int(max(float(curseur_ts or 0.0) - overlap_ms, plancher))


def poids_rest_estime(n_appels: int, *, poids_par_appel: int = 20, fenetre_s: float = 90.0,
                      limite_ip_par_min: int = 1200) -> dict:
    """Poids REST ESTIMÉ du garde (visibilité budget IP HL ≈ 1200 poids/min/IP). `userFillsByTime` ≈ 20 poids/
    appel (hypothèse prudente, labellisée « estimé »). Rend n_appels, poids/min estimé et la limite IP pour
    comparer — afin que ce garde, AJOUTÉ aux autres collecteurs, ne menace jamais la limite."""
    par_min = (n_appels / max(fenetre_s, 1.0)) * 60.0 * poids_par_appel
    return {"n_appels": n_appels, "poids_par_appel": poids_par_appel,
            "poids_estime_par_min": round(par_min, 1), "limite_ip_par_min": limite_ip_par_min}


# ─────────────────────────────── réseau (lecture seule, borné, poli) ───────────────────────────────

def _curseurs(root: Path) -> dict:
    try:
        return json.loads((root / CURSEURS_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def userfills_rest(vault: str, *, timeout_s: float = 8.0):
    """POST /info {"type":"userFills","user":vault} PUBLIC (lecture seule). Rend la liste brute ou []."""
    corps = json.dumps({"type": "userFills", "user": vault}).encode("utf-8")
    req = urllib.request.Request(URL_HL_INFO, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:  # noqa: S310 (URL constante publique)
        return json.loads(rep.read().decode("utf-8"))


def userfills_by_time_rest(vault: str, start_ms: int, *, timeout_s: float = 8.0):
    """POST /info {"type":"userFillsByTime","user":vault,"startTime":start_ms} PUBLIC (lecture seule). FENÊTRE
    BORNÉE depuis le dernier curseur (avec léger chevauchement) → peu de fills → poids REST faible. Rend la
    liste brute ou []. À dédupliquer/comparer par CLÉ COMPOSITE côté appelant."""
    corps = json.dumps({"type": "userFillsByTime", "user": vault, "startTime": int(start_ms)}).encode("utf-8")
    req = urllib.request.Request(URL_HL_INFO, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:  # noqa: S310 (URL constante publique)
        return json.loads(rep.read().decode("utf-8"))


async def sonder_un_vault(vault: str, *, timeout_s: float = TIMEOUT_SONDE_S, socket_id: str = "diag") -> dict:
    """Ouvre une socket DIAGNOSTIC temporaire, s'abonne au userFills du seul `vault`, attend ACK/snapshot/
    fill ou TIMEOUT, puis se désabonne (poli) et ferme. Lecture seule. Rend {vault,socket,heure,verdict,
    latence_ms}."""
    import websockets
    vlc = vault.lower()
    t0 = time.monotonic()
    heure = time.strftime("%H:%M:%S")
    verdict, latence_ms = "TIMEOUT", None
    try:
        async with websockets.connect(WS_URL, ping_interval=20, max_size=2 ** 22) as ws:
            await ws.send(json.dumps({"method": "subscribe",
                                      "subscription": {"type": "userFills", "user": vault}}))
            fin = t0 + timeout_s
            while True:
                reste = fin - time.monotonic()
                if reste <= 0:
                    break
                try:
                    brut = await asyncio.wait_for(ws.recv(), timeout=reste)
                except asyncio.TimeoutError:
                    break
                try:
                    msg = json.loads(brut)
                except ValueError:
                    continue
                c = classer_message(msg, vlc)
                if c:
                    verdict, latence_ms = c, round((time.monotonic() - t0) * 1000)
                    try:                                          # désabonnement poli avant fermeture
                        await ws.send(json.dumps({"method": "unsubscribe",
                                                  "subscription": {"type": "userFills", "user": vault}}))
                    except Exception:  # noqa: BLE001
                        pass
                    break
    except Exception as exc:  # noqa: BLE001 — le réseau ne doit jamais faire crasher la sonde
        verdict = "ERREUR:%s" % str(exc)[:40]
    return {"vault": vault, "socket": socket_id, "heure": heure, "verdict": verdict, "latence_ms": latence_ms}


async def sonder_sequentiel(root: Path, vaults: list[str], *, timeout_s: float = TIMEOUT_SONDE_S,
                            delai_s: float = DELAI_ENTRE_SONDES_S, socket_id: str = "diagB") -> dict:
    """Sonde SÉQUENTIELLEMENT chaque vault (espacé → << 30 conn/min), croise REST par curseur, journalise
    chaque ligne, écrit le rapport JSON. Rend le verdict global. Lecture seule."""
    cur = _curseurs(root)
    resultats: list[dict] = []
    print("[sonde] %d vaults à confirmer (timeout %.0fs, délai %.1fs → ≤ %.0f conn/min)"
          % (len(vaults), timeout_s, delai_s, 60.0 / max(delai_s, 0.001)), flush=True)
    for i, v in enumerate(vaults):
        r = await sonder_un_vault(v, timeout_s=timeout_s, socket_id=socket_id)
        try:                                                      # croisement REST (lecture seule, poli)
            rep = userfills_rest(v)
            fr = fills_rest_normalises(v, rep)
            retard = fills_rest_en_retard(fr, cur.get(v))
            r["curseur_ws"] = cur.get(v)
            r["rest_n_fills"] = len(fr)
            r["rest_dernier_ts"] = max((f["ts_ms"] for f in fr), default=None)
            r["rest_en_retard"] = len(retard)
            r["shard_defaillant"] = bool(retard)                  # REST voit un fill que le WS a raté
        except Exception as exc:  # noqa: BLE001
            r["rest_erreur"] = str(exc)[:60]
            r["shard_defaillant"] = False
        marque = "✓" if r["verdict"] in CONFIRME else ("⛔DÉFAUT" if r.get("shard_defaillant") else "PENDING")
        print("[sonde] %2d/%d %s socket=%s %s verdict=%s lat=%sms rest=%s dernier_ts=%s %s"
              % (i + 1, len(vaults), v[:12], r["socket"], r["heure"], r["verdict"], r.get("latence_ms"),
                 r.get("rest_n_fills"), r.get("rest_dernier_ts"), marque), flush=True)
        resultats.append(r)
        if i + 1 < len(vaults):
            await asyncio.sleep(delai_s)
    vg = verdict_global(resultats)
    rapport = {"ts_ms": int(time.time() * 1000), "socket_cible": socket_id, "transport": "sonde_diag_v1",
               "resultats": resultats, **vg}
    p = root / SONDE_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    print("[sonde] VERDICT : %d/%d confirmés · %d PENDING · défauts=%s → %s"
          % (vg["n_confirmes"], vg["n_total"], vg["n_pending"], vg["shards_defaillants"] or "aucun", p), flush=True)
    return rapport


def _vaults_shard(root: Path, lettre: str) -> list[str]:
    """Vaults du shard demandé (A/B/…) calculés par le MÊME sharding déterministe que le collecteur."""
    import collecter_userfills_vaults as C
    vaults = [v for v, _r, _w in C.vaults_et_roles(root)]
    for sid, grp in C._shards_userfills(vaults):
        if sid == lettre.upper():
            return grp
    return []


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Sonde de confirmation WS (diagnostic transport, lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--shard", default="B", help="shard à sonder (défaut B = candidats calmes)")
    p.add_argument("--vaults", default="", help="liste explicite séparée par des virgules (sinon = shard)")
    p.add_argument("--timeout", type=float, default=TIMEOUT_SONDE_S)
    a = p.parse_args(argv)
    root = Path(a.root)
    vaults = [v.strip() for v in a.vaults.split(",") if v.strip()] or _vaults_shard(root, a.shard)
    if not vaults:
        print("[sonde] aucun vault à sonder (shard %s vide)" % a.shard, flush=True)
        return 0
    asyncio.run(sonder_sequentiel(root, vaults, timeout_s=a.timeout, socket_id="diag" + a.shard.upper()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
