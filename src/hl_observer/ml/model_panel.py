"""V13 — Read-only "AI model" dashboard panel (#149), en langage SIMPLE.

Statut honnête du modèle local + des PHRASES claires (zéro jargon) pour qu'un débutant
comprenne exactement ce que fait l'IA. Lecture seule : montre l'état, jamais un ordre,
jamais un faux chiffre. État vide honnête tant qu'aucun modèle n'est entraîné.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

FEATURE_LABELS_FR = {
    "net_edge_bps": "la marge de gain (après frais)",
    "signal_age_ms": "la fraîcheur du signal",
    "consensus_wallets": "le nombre de traders d'accord",
    "liquidity_score": "la liquidité du marché",
    "bias_bps": "la tendance du marché",
    "whale_strength": "la force de la baleine",
    "leader_score": "la qualité du trader copié",
    "adverse_move_bps": "le mouvement contraire du prix",
    "price_deviation_bps": "l'écart de prix",
}

_WHAT = ("L'IA regarde chaque trade possible et lui donne une note de 0 à 100 % : "
         "la chance que ce trade rapporte de l'argent. Elle a appris cette note toute "
         "seule en observant les trades déjà terminés (ceux qui ont gagné et ceux qui ont perdu).")


def _load_history(model_path, limit: int = 20) -> list:
    if not model_path:
        return []
    hp = Path(str(model_path) + ".history.jsonl")
    if not hp.exists():
        return []
    rows = []
    try:
        for line in hp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    except Exception:
        return []
    return rows[-limit:]


def _on_ten(acc):
    try:
        return round(float(acc) * 10)
    except (TypeError, ValueError):
        return None


def _load_training_report(report_path: str | None, model_path: str) -> dict:
    candidates: list[Path] = []
    if report_path:
        candidates.append(Path(report_path))
    candidates.append(Path(model_path + ".report.json"))
    for candidate in candidates:
        try:
            if candidate.exists():
                return json.loads(candidate.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
    return {}


def _shadow_report_panel(
    report: dict,
    *,
    history: list,
    n_trainings: int,
    authoritative: bool,
    min_p: float,
    last_p_profit,
) -> dict | None:
    """Show honest learning state when training ran but no model was promoted.

    ``train_cli`` deliberately writes a report even when the model is *not*
    saved because it failed to beat the baseline. Previously the dashboard read
    only the saved model, so the user saw "IA pas encore commencee" although the
    system had actually learned from losing trades and correctly refused
    promotion. This panel keeps that distinction visible without letting an
    unpromoted model affect decisions.
    """

    try:
        n = int(report.get("n") or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return None
    ev = report.get("evaluation") or {}
    acc10 = _on_ten(ev.get("accuracy"))
    beats = ev.get("beats_baseline")
    n_win = int(report.get("n_win") or 0)
    n_loss = int(report.get("n_loss") or max(0, n - n_win))
    ready = bool(report.get("ready_for_promotion")) and beats is True and report.get("saved") is True

    plain_status = (
        f"L'IA a bien analyse {n} trades termines ({n_win} gagnants, {n_loss} perdants), "
        "mais elle n'est pas encore assez fiable pour filtrer les decisions. "
        "Elle reste en observation et ne peut ouvrir aucun trade."
    )
    if acc10 is not None:
        plain_status += f" Sur l'echantillon de test, elle a devine juste {acc10} fois sur 10."
    if beats is False:
        plain_status += " Son score ne bat pas encore la reference simple; promotion refusee."
    elif beats is True and not ready:
        plain_status += " Elle progresse, mais la promotion reste verrouillee tant qu'un modele fiable n'est pas sauvegarde."

    feature_names = list(report.get("feature_names") or [])
    plain_top = (
        "Les donnees suivies par l'IA sont : " + ", ".join(FEATURE_LABELS_FR.get(name, name) for name in feature_names[:5]) + "."
        if feature_names
        else ""
    )

    return {
        "trained": False,
        "empty": False,
        "report_only": True,
        "n_train": n,
        "n_win": n_win,
        "n_loss": n_loss,
        "ready_for_promotion": ready,
        "saved": bool(report.get("saved")),
        "authoritative": authoritative,
        "min_p": min_p,
        "last_p_profit": last_p_profit,
        "context_only": True,
        "history": history,
        "n_trainings": n_trainings,
        "brier": ev.get("brier"),
        "baseline_brier": ev.get("baseline_brier"),
        "brier_advantage": ev.get("brier_advantage"),
        "beats_baseline": beats,
        "accuracy": ev.get("accuracy"),
        "accuracy_on_ten": acc10,
        "plain_what": _WHAT,
        "plain_status": plain_status,
        "plain_progress": "Apprentissage observe, modele non promu.",
        "plain_top": plain_top,
        "plain_hint": "L'IA ne filtrera les trades que lorsqu'elle battra la baseline et sera explicitement promue.",
        "note": "Rapport d'entrainement lu; aucun modele fiable sauvegarde pour l'instant.",
    }


def build_model_panel(model, *, report_path=None, last_p_profit=None) -> dict:
    authoritative = str(os.environ.get("HYPERSMART_V13_MODEL_AUTHORITATIVE", "")).lower() in {"1", "true", "yes", "on"}
    try:
        min_p = float(os.environ.get("HYPERSMART_V13_MODEL_MIN_P", "0.5") or 0.5)
    except (TypeError, ValueError):
        min_p = 0.5

    model_path = os.environ.get("HYPERSMART_V13_MODEL_PATH") or "runtime/models/trade_model_v13.json"
    history = _load_history(model_path)
    n_trainings = len(history)
    explicit_report_path = report_path or os.environ.get("HYPERSMART_V13_MODEL_REPORT")
    report = _load_training_report(explicit_report_path, model_path) if explicit_report_path else {}

    if model is None or not getattr(model, "trained", False):
        shadow_panel = _shadow_report_panel(
            report,
            history=history,
            n_trainings=n_trainings,
            authoritative=authoritative,
            min_p=min_p,
            last_p_profit=last_p_profit,
        )
        if shadow_panel is not None:
            return shadow_panel
        return {
            "history": history, "n_trainings": n_trainings,
            "trained": False, "empty": True, "authoritative": authoritative, "min_p": min_p,
            "last_p_profit": last_p_profit, "context_only": True,
            "plain_what": _WHAT,
            "plain_status": ("L'IA n'a pas encore vu assez de trades terminés pour apprendre. "
                             "Elle attend et observe — pour l'instant elle n'agit pas. "
                             "Plus le bot fait de trades, plus elle apprendra."),
            "plain_progress": "Apprentissage pas encore commencé.",
            "note": "Aucun modèle entraîné pour le moment.",
        }

    importances = sorted(
        ({"feature": n, "label": FEATURE_LABELS_FR.get(n, n),
          "weight": round(float(w), 6), "importance": round(abs(float(w)), 6)}
         for n, w in zip(model.feature_names, model.weights)),
        key=lambda d: -d["importance"],
    )

    ev = (report.get("evaluation") or {}) if isinstance(report, dict) else {}

    n_train = int(getattr(model, "n_train", 0))
    acc10 = _on_ten(ev.get("accuracy"))
    beats = ev.get("beats_baseline")

    if authoritative:
        plain_status = ("L'IA FILTRE les trades : elle laisse passer ceux qui ont une bonne "
                        "chance de gagner et écarte les autres. Elle ne peut jamais ouvrir un "
                        "trade toute seule, seulement en refuser.")
    else:
        plain_status = (f"L'IA a appris sur {n_train} trades terminés. Pour l'instant elle OBSERVE "
                        "seulement : elle donne son avis mais ne bloque encore aucun trade.")
    if acc10 is not None:
        plain_status += f" Sur des trades qu'elle n'avait jamais vus, elle a deviné juste {acc10} fois sur 10."
    if beats is True:
        plain_status += " C'est mieux que de deviner au hasard."
    elif beats is False:
        plain_status += " Elle ne fait pas encore mieux que le hasard — elle continue d'apprendre."

    accs = [_on_ten(h.get("accuracy")) for h in history if h.get("accuracy") is not None]
    if len(accs) >= 2:
        first, last = accs[0], accs[-1]
        trend = "elle s'améliore" if last > first else ("elle reste stable" if last == first else "elle baisse un peu")
        plain_progress = f"Au début : {first} bonnes réponses sur 10. Maintenant : {last} sur 10 — {trend}."
    elif len(accs) == 1:
        plain_progress = f"Premier apprentissage enregistré : {accs[0]} bonnes réponses sur 10."
    else:
        plain_progress = "Apprentissage en cours."

    top = [i["label"] for i in importances[:3] if i["importance"] > 0]
    plain_top = ("Pour décider, l'IA regarde surtout : " + ", ".join(top) + ".") if top else ""

    plain_hint = ""
    if beats is True and not authoritative:
        plain_hint = ("L'IA est prête : pour la laisser filtrer les trades, mets "
                      "HYPERSMART_V13_MODEL_AUTHORITATIVE=1 dans le lanceur.")

    return {
        "trained": True, "empty": False, "n_train": n_train,
        "feature_importances": importances,
        "brier": ev.get("brier"), "baseline_brier": ev.get("baseline_brier"),
        "brier_advantage": ev.get("brier_advantage"), "beats_baseline": beats,
        "accuracy": ev.get("accuracy"), "accuracy_on_ten": acc10,
        "authoritative": authoritative, "min_p": min_p,
        "last_p_profit": last_p_profit, "context_only": True,
        "history": history, "n_trainings": n_trainings,
        "plain_what": _WHAT, "plain_status": plain_status,
        "plain_progress": plain_progress, "plain_top": plain_top, "plain_hint": plain_hint,
    }


__all__ = ["build_model_panel", "FEATURE_LABELS_FR"]
