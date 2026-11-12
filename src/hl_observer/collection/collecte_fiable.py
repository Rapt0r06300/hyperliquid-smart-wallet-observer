"""SOCLE DE COLLECTE FIABLE — le maximum de données, SANS se faire bannir ni stocker de poubelle.

Flo (22/07) : « il nous faut une quantité EXTRAORDINAIRE de données pour trouver les meilleurs
calibrages ». Le CLAUDE.md l'autorise pleinement (collecte publique agressive 24/7). Mais « plus »
n'a de valeur que si c'est FIABLE et PROPRE :

  * se faire couper par une source = MOINS de données -> backoff avec jitter, jamais du hammering ;
  * un doublon gonfle les volumes et fausse un calibrage -> déduplication par clé stable ;
  * une écriture coupée en plein vol corrompt le fichier -> append atomique (flush+fsync) ;
  * une valeur aberrante (mauvais appariement, prix nul) empoisonne la mesure -> porte de qualité ;
  * une donnée sans origine ne se conteste pas -> chaque ligne est estampillée (source, ts, read_only).

Ce module ne fait AUCUN appel réseau : ce sont des primitives PURES, réutilisées par tous les
collecteurs (dispersion, carnet, fills, liquidations). PAPER/READ-ONLY : collecter n'est pas trader.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import random
import tempfile
import time
import urllib.error
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from hl_observer.ops.echec_silencieux import noter as _noter

# ─────────────────────────────── déduplication ───────────────────────────────

def cle_dedup(enr: dict, champs: Sequence[str]) -> str:
    """Clé stable et courte d'un enregistrement sur `champs` (ordre fixe). Un champ absent compte
    comme vide — deux enregistrements ne sont « les mêmes » que s'ils coïncident sur TOUS les champs."""
    brut = "\x1f".join(str(enr.get(c, "")) for c in champs)
    return hashlib.sha1(brut.encode("utf-8", "replace")).hexdigest()[:16]


class CacheDedup:
    """Un cache borné des clés déjà vues (FIFO). Borné pour ne jamais grossir sans fin — la
    déduplication protège contre les doublons PROCHES, pas contre l'histoire entière."""

    def __init__(self, maximum: int = 100_000) -> None:
        self.maximum = int(maximum)
        self._vus: dict[str, None] = {}

    def neuf(self, cle: str) -> bool:
        """True si la clé est nouvelle (et l'enregistre). False si déjà vue."""
        if cle in self._vus:
            return False
        self._vus[cle] = None
        if len(self._vus) > self.maximum:
            for vieux in list(self._vus)[: len(self._vus) - self.maximum]:
                self._vus.pop(vieux, None)
        return True

    def filtrer(self, enrs: Iterable[dict], champs: Sequence[str]) -> list[dict]:
        """Ne garde que les enregistrements dont la clé est neuve."""
        return [e for e in enrs if self.neuf(cle_dedup(e, champs))]


# ─────────────────────────────── écriture atomique / append sûr ───────────────────────────────

def append_jsonl(chemin: str | Path, enrs: Sequence[dict], *, fsync: bool = True) -> int:
    """Append JSONL avec flush (+fsync) : une écriture coupée ne laisse pas un fichier à moitié.
    Rend le nombre de lignes écrites. Crée le dossier au besoin."""
    p = Path(chemin)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("a", encoding="utf-8") as fh:
        for e in enrs:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
            n += 1
        fh.flush()
        if fsync:
            try:
                os.fsync(fh.fileno())
            except OSError:
                _noter("collection/collecte_fiable.py:append_jsonl_fsync")
    return n


def ecrire_atomique(
    chemin: str | Path,
    texte: str,
    *,
    tentatives: int = 8,
    delai_s: float = 0.025,
) -> None:
    """Écrit un fichier ENTIER de façon atomique (tmp + fsync + os.replace) : un lecteur ne voit
    jamais un état intermédiaire. Sous Windows, un antivirus ou un lecteur peut tenir brièvement
    la destination : on retente alors avec un délai borné. Un verrou persistant reste une erreur
    visible et le fichier temporaire unique est nettoyé. Pour les snapshots/index, pas pour les
    journaux append-only.
    """
    p = Path(chemin)
    p.parent.mkdir(parents=True, exist_ok=True)
    nombre_tentatives = max(1, int(tentatives))
    attente = max(0.0, float(delai_s))
    fd, nom_tmp = tempfile.mkstemp(
        dir=str(p.parent),
        prefix=f".{p.name}.",
        suffix=".tmp",
        text=True,
    )
    tmp = Path(nom_tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(texte)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                _noter("collection/collecte_fiable.py:ecrire_atomique_fsync")

        derniere_erreur: PermissionError | None = None
        for essai in range(nombre_tentatives):
            try:
                os.replace(tmp, p)
                return
            except PermissionError as exc:
                derniere_erreur = exc
                if essai + 1 < nombre_tentatives and attente:
                    time.sleep(attente * (essai + 1))
        assert derniere_erreur is not None
        raise derniere_erreur
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            _noter("collection/collecte_fiable.py:ecrire_atomique_nettoyage_tmp")


# ─────────────────────────────── politesse réseau (durer 3 jours, pas 3 minutes) ───────────────

def backoff_jitter(tentative: int, *, base_s: float = 0.5, plafond_s: float = 60.0) -> float:
    """Délai d'attente exponentiel AVEC jitter (± 25 %) après un échec réseau/rate-limit. Le
    jitter évite que N collecteurs re-tapent la source à la même seconde (thundering herd)."""
    t = max(0, int(tentative))
    d = min(float(plafond_s), float(base_s) * (2 ** t))
    return round(d * (0.75 + 0.5 * random.random()), 4)


class Limiteur:
    """Un limiteur de débit MINIMAL : au plus 1 action toutes `intervalle_s`. Rester SOUS la
    limite d'une source publique = durer, donc collecter PLUS au total (se faire bannir = 0)."""

    def __init__(self, intervalle_s: float) -> None:
        self.intervalle_s = max(0.0, float(intervalle_s))
        self._dernier = 0.0

    def attente(self, maintenant: float | None = None) -> float:
        """Combien de secondes attendre avant la prochaine action (0 si prête). Met à jour l'horloge."""
        t = time.time() if maintenant is None else float(maintenant)
        reste = self.intervalle_s - (t - self._dernier)
        if reste <= 0:
            self._dernier = t
            return 0.0
        self._dernier = t + reste
        return round(reste, 4)

    def patienter(self, dormir=None, maintenant: float | None = None) -> float:
        """Attend RÉELLEMENT le délai dû avant la prochaine action, puis le renvoie.

        ``attente()`` ne fait que le CALCULER : l'appeler sans dormir ne limite rien. C'est ainsi que
        quatre collecteurs envoyaient leurs requêtes sans aucune pause (cas réel du 2026-11-11 : 1 219
        fenêtres de dépôts/retraits sur 2 250 refusées en HTTP 429 lors d'un seul passage)."""
        reste = self.attente(maintenant)
        if reste > 0:
            (dormir or time.sleep)(reste)
        return reste


def prendre_la_pause(limiteur: Any, dormir=None) -> float:
    """Prend la pause due par ``limiteur``, quel qu'il soit : un ``Limiteur`` (``patienter``) ou tout
    objet qui ne sait que calculer un délai (``attente``). Renvoie le délai pris."""
    patienter = getattr(limiteur, "patienter", None)
    if callable(patienter):
        return float(patienter(dormir) or 0.0)
    reste = limiteur.attente()
    if isinstance(reste, (int, float)) and reste > 0:
        (dormir or time.sleep)(float(reste))
        return float(reste)
    return 0.0


#: Budget de débit de l'API publique Hyperliquid : 1 200 unités par minute et par adresse IP ; une
#: requête ``info`` coûte 20 unités, plus une part proportionnelle aux lignes renvoyées. Un collecteur
#: de RATTRAPAGE n'en prend qu'un douzième : deux rattrapages tournent en même temps (bougies/funding et
#: fills), et les collecteurs en direct partagent la même adresse. Mesuré le 2026-11-11 avec le vrai
#: lanceur : à la moitié du budget chacun, ils prenaient tout, et vaults, liquidations, carnet et prix
#: recevaient des « 429 ». Le suivi en direct des fills s'adapte au débit qui reste : tout ce qu'un
#: rattrapage prend, il le lui retire. Un rattrapage est incrémental : il peut être lent, pas eux.
POIDS_REQUETE_INFO = 20.0
BUDGET_POIDS_RATTRAPAGE_PAR_MINUTE = 100.0


def pause_pour_poids(poids: float, *, budget_par_minute: float = BUDGET_POIDS_RATTRAPAGE_PAR_MINUTE) -> float:
    """Secondes à laisser passer pour qu'une requête de ce poids tienne dans le budget de débit."""
    return max(0.0, float(poids)) / float(budget_par_minute) * 60.0


class CadencePonderee:
    """Tient une part du budget de débit : chaque requête attend que la précédente soit « payée ».

    La durée de la requête elle-même est déduite de l'attente : la cadence réelle est celle du budget,
    pas le budget plus la latence du réseau. La première requête part tout de suite.
    """

    def __init__(self, budget_par_minute: float, *, horloge: Callable[[], float] | None = None,
                 dormir: Callable[[float], None] | None = None) -> None:
        self.budget_par_minute = float(budget_par_minute)
        self._horloge = horloge or time.monotonic
        self._dormir = dormir
        self._libre_a = 0.0

    def attendre(self, poids: float) -> float:
        """Attend son tour pour une requête de ce poids ; rend les secondes réellement attendues."""
        maintenant = self._horloge()
        attente = max(0.0, self._libre_a - maintenant)
        if attente > 0:
            (self._dormir or time.sleep)(attente)
        self._libre_a = max(maintenant, self._libre_a) + pause_pour_poids(
            poids, budget_par_minute=self.budget_par_minute)
        return attente


#: Signal de congestion entre processus. Tous les collecteurs locaux partagent UNE adresse IP : quand un
#: collecteur EN DIRECT est refusé (429), il touche ce fichier-témoin ; les RATTRAPAGES (bougies, funding,
#: historiques de fills) le lisent avant chaque requête et attendent. Un rattrapage peut toujours attendre ;
#: une mesure en direct manquée est perdue. Inactif tant que la variable d'environnement n'est pas posée
#: (elle l'est par ``LANCER_COLLECTEURS_COPY_VAULT.cmd``) : ni les tests, ni les lanes cloud, ni un outil
#: lancé à la main ne sont concernés.
SIGNAL_DEBIT_ENV = "ALINA_SIGNAL_DEBIT"
DUREE_CONGESTION_S = 45.0


def _fichier_signal_debit() -> Path | None:
    chemin = os.environ.get(SIGNAL_DEBIT_ENV, "").strip()
    return Path(chemin) if chemin else None


def signaler_refus_de_debit() -> None:
    """Un collecteur en direct vient d'être refusé : le faire savoir aux rattrapages. Ne lève jamais."""
    chemin = _fichier_signal_debit()
    if chemin is None:
        return
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(f"{time.time():.3f}\n", encoding="utf-8")
    except OSError as exc:
        _noter("collecte_fiable.signal_debit", exc)


def congestion_restante_s(maintenant: float | None = None) -> float:
    """Secondes pendant lesquelles un rattrapage doit encore céder la place (0 si aucun refus récent)."""
    chemin = _fichier_signal_debit()
    if chemin is None:
        return 0.0
    try:
        dernier = chemin.stat().st_mtime
    except OSError:
        return 0.0
    reste = dernier + DUREE_CONGESTION_S - (time.time() if maintenant is None else float(maintenant))
    return max(0.0, min(DUREE_CONGESTION_S, reste))        # borné : une horloge décalée ne bloque jamais


def ceder_au_direct(dormir: Callable[[float], None] | None = None, maintenant: float | None = None) -> float:
    """À appeler par un RATTRAPAGE avant chaque requête : attend la fin d'une congestion signalée.

    L'attente est bornée à ``DUREE_CONGESTION_S`` par appel : même sous refus continus, un rattrapage
    avance d'une requête à chaque période, il n'est jamais bloqué indéfiniment."""
    attente = congestion_restante_s(maintenant)
    if attente > 0:
        (dormir or time.sleep)(attente)
    return attente


#: Budget de débit PARTAGÉ entre tous les collecteurs de la même adresse IP (la limite publique
#: Hyperliquid est de 1 200 unités/minute et par IP ; tous les collecteurs locaux la partagent).
#: Fenêtre glissante (horodatage, poids) dans un fichier protégé par un verrou. Posé par le lanceur
#: via cette variable ; absent → MÉCANISME INACTIF (tests, lanes cloud chacune sur sa propre IP,
#: outil lancé à la main : chacun garde sa cadence). FAIL-OPEN total : toute erreur (verrou tenu,
#: fichier corrompu, I/O) → on passe SANS attendre. L'attente est bornée à ``ATTENTE_MAX_BUDGET_S``
#: par appel : un collecteur avance toujours, jamais de blocage ni d'interblocage.
BUDGET_DEBIT_ENV = "ALINA_BUDGET_DEBIT"
SEUIL_POIDS_PARTAGE_PAR_MINUTE = 1000.0   # marge sous la limite 1 200/min/IP
FENETRE_BUDGET_S = 60.0
ATTENTE_MAX_BUDGET_S = 8.0
_STALE_VERROU_S = 3.0
_MAX_EVENEMENTS_BUDGET = 1000


def _fichier_budget() -> Path | None:
    chemin = os.environ.get(BUDGET_DEBIT_ENV, "").strip()
    return Path(chemin) if chemin else None


@contextlib.contextmanager
def _verrou_fichier(cible: Path, *, timeout_s: float = 1.0, dormir: Callable[[float], None] | None = None):
    """Verrou inter-process par création exclusive ; vole un verrou périmé ; fail-open (ne lève jamais).

    Rend ``True`` si le verrou est tenu, ``False`` sinon (l'appelant décide quand même : fail-open).
    """
    sieste = dormir or time.sleep
    verrou = cible.with_name(cible.name + ".lock")
    tenu = False
    fin = time.monotonic() + max(0.0, float(timeout_s))
    while True:
        try:
            descripteur = os.open(str(verrou), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descripteur)
            tenu = True
            break
        except FileExistsError:
            try:
                age = time.time() - verrou.stat().st_mtime
            except OSError:
                age = 0.0
            if age > _STALE_VERROU_S:                      # verrou d'un process mort : on le vole
                with contextlib.suppress(OSError):
                    verrou.unlink()
                continue
            if time.monotonic() >= fin:
                break                                      # fail-open : on n'a pas pu verrouiller
            sieste(0.01)
        except OSError:
            break                                          # fail-open
    try:
        yield tenu
    finally:
        if tenu:
            with contextlib.suppress(OSError):
                verrou.unlink()


def _lire_fenetre_budget(chemin: Path, maintenant: float) -> list[tuple[float, float]]:
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    evts: list[tuple[float, float]] = []
    for ligne in brut if isinstance(brut, list) else ():
        try:
            ts, poids = float(ligne[0]), float(ligne[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 0.0 <= maintenant - ts < FENETRE_BUDGET_S:
            evts.append((ts, poids))
    return evts


def reserver_poids(poids: float, *, maintenant: Callable[[], float] | None = None,
                   dormir: Callable[[float], None] | None = None) -> float:
    """Réserve ``poids`` unités de débit dans le budget partagé ; attend (borné) si l'IP serait saturée.

    Rend les secondes réellement attendues (0 si le mécanisme est inactif ou sur toute erreur). À
    appeler par un collecteur AVANT chaque requête. Deux phases, verrou tenu brièvement à chaque fois
    (jamais pendant le sommeil) : (1) lire la fenêtre, décider de l'attente ; (2) après l'attente,
    enregistrer la consommation. Fail-open partout.
    """
    chemin = _fichier_budget()
    poids = max(0.0, float(poids))
    if chemin is None or poids <= 0.0:
        return 0.0
    horloge = maintenant or time.time
    sieste = dormir or time.sleep
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return 0.0
    attente = 0.0
    try:
        with _verrou_fichier(chemin, dormir=sieste):
            t = horloge()
            somme = sum(w for _, w in _lire_fenetre_budget(chemin, t))
            exces = somme + poids - SEUIL_POIDS_PARTAGE_PAR_MINUTE
            if exces > 0.0:
                attente = min(ATTENTE_MAX_BUDGET_S,
                              pause_pour_poids(exces, budget_par_minute=SEUIL_POIDS_PARTAGE_PAR_MINUTE))
        if attente > 0.0:
            sieste(attente)                                # verrou relâché : on ne bloque personne
        with _verrou_fichier(chemin, dormir=sieste):
            t2 = horloge()
            fenetre = _lire_fenetre_budget(chemin, t2)
            fenetre.append((t2, poids))
            ecrire_atomique(chemin, json.dumps(fenetre[-_MAX_EVENEMENTS_BUDGET:], ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - fail-open : le débit ne doit jamais bloquer la collecte
        _noter("collecte_fiable.budget_partage", exc)
        return 0.0
    return attente


def reprendre_apres_refus_de_debit(appel: Callable[[], Any], *, essais: int = 4, attente_s: float = 3.0,
                                   dormir: Callable[[float], None] | None = None) -> Any:
    """Rend ``appel()`` ; sur un refus de débit (HTTP 429), attend puis réessaie (``essais`` au total).

    Sans cela un seul « 429 » faisait perdre le relevé (cas réel du 2026-11-11 : 6 vaults sur 69 absents
    d'une passe). L'attente suit ``Retry-After`` quand le serveur le donne (borné à 30 s), sinon elle
    double à chaque essai. Toute autre erreur, et le dernier refus, remontent tels quels.
    """
    total = max(1, int(essais))
    for essai in range(1, total + 1):
        try:
            return appel()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                signaler_refus_de_debit()                  # les rattrapages cèdent la place
            if exc.code != 429 or essai >= total:
                raise
            try:
                indique = float(exc.headers.get("Retry-After") or 0) if exc.headers else 0.0
            except (ValueError, TypeError, AttributeError):
                indique = 0.0
            (dormir or time.sleep)(indique if 0 < indique <= 30 else float(attente_s) * 2 ** (essai - 1))
    raise RuntimeError("reprise après refus de débit : aucun essai effectué")   # inatteignable


# ─────────────────────────────── provenance & qualité ───────────────────────────────

def estampiller(enr: dict, *, source: str, maintenant: float | None = None) -> dict:
    """Ajoute la PROVENANCE : source, horodatage de collecte, et les invariants read-only. Une
    donnée sans origine ne se conteste pas plus tard — donc elle finit par mentir."""
    return {**enr, "source": str(source),
            "collecte_ts": round(time.time() if maintenant is None else float(maintenant), 3),
            "read_only": True, "real_execution": False}


def qualite_ok(enr: dict, *, champs_prix: Sequence[str] = (),
               ecart_bps_max: float | None = None, champ_ecart: str = "ecart_prix_bps",
               ts_min: float = 1_577_836_800.0) -> bool:
    """Porte de QUALITÉ (deny-by-default) : rejette ce qui empoisonnerait un calibrage.
      * un prix cité doit être un nombre > 0 (jamais un 0 de remplissage) ;
      * un |écart| au-delà de `ecart_bps_max` = mauvais appariement (mémoire « base aberrante ») ;
      * un horodatage implausible (avant 2020) = fixture/erreur, pas une vraie observation.
    """
    ts = enr.get("collecte_ts") or enr.get("ts")
    if isinstance(ts, (int, float)) and float(ts) < ts_min:
        return False
    for c in champs_prix:
        v = enr.get(c)
        if not isinstance(v, (int, float)) or float(v) <= 0 or float(v) != float(v):
            return False
    if ecart_bps_max is not None:
        e = enr.get(champ_ecart)
        if isinstance(e, (int, float)) and abs(float(e)) > float(ecart_bps_max):
            return False
    return True


def collecter_proprement(enrs: Iterable[dict], *, source: str, champs_cle: Sequence[str],
                         cache: CacheDedup | None = None, **qualite: Any) -> list[dict]:
    """Le pipeline en un appel : estamper la provenance -> porte de qualité -> déduplication.
    Rend les enregistrements PROPRES, prêts à écrire. Rien d'inventé : on ne fait que filtrer."""
    cache = cache if cache is not None else CacheDedup()
    propres: list[dict] = []
    for e in enrs or ():
        est = estampiller(e, source=source)
        if not qualite_ok(est, **qualite):
            continue
        if cache.neuf(cle_dedup(est, champs_cle)):
            propres.append(est)
    return propres


def reconnect_recovery_plan(*, last_seen_ts_ms: object, reconnect_ts_ms: object, backfill_available: object) -> dict[str, Any]:
    """Choose continuation or fail-closed backfill without inventing a gap."""
    if any(type(value) is not int or value <= 0 for value in (last_seen_ts_ms, reconnect_ts_ms)):
        return {"status": "UNMEASURABLE", "reason": "RECOVERY_CLOCK_MISSING", "paper_read_only": True}
    if reconnect_ts_ms < last_seen_ts_ms:
        return {"status": "REJECTED", "reason": "RECOVERY_CLOCK_REVERSED", "paper_read_only": True}
    if backfill_available is True:
        return {"status": "BACKFILL_REQUIRED", "from_ts_ms": last_seen_ts_ms, "to_ts_ms": reconnect_ts_ms, "paper_read_only": True, "real_execution": False}
    return {"status": "UNMEASURABLE", "reason": "BACKFILL_EVIDENCE_MISSING", "paper_read_only": True, "real_execution": False}


__all__ = ["cle_dedup", "CacheDedup", "append_jsonl", "ecrire_atomique", "backoff_jitter",
           "Limiteur", "estampiller", "qualite_ok", "collecter_proprement", "reconnect_recovery_plan"]
