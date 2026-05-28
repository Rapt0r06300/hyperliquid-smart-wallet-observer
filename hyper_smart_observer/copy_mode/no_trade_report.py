from __future__ import annotations

import json
import csv
from collections import Counter
from pathlib import Path

from hyper_smart_observer.copy_mode.copy_models import NoTradeDecision, NoTradeReason, SignalCandidate, SignalDecision, stable_hash, to_jsonable, utc_now


REASON_TEXT: dict[str, tuple[str, str, str]] = {
    NoTradeReason.TRUNCATED_ADDRESS_REJECTED.value: (
        "Adresse tronquee observee.",
        "Une adresse avec ... ne peut pas etre revalidee ni suivie.",
        "Importer une adresse complete 0x + 40 caracteres hexadecimaux.",
    ),
    NoTradeReason.INVALID_ADDRESS_REJECTED.value: (
        "Adresse invalide observee.",
        "Le format ne respecte pas 0x + 40 caracteres hexadecimaux.",
        "Corriger la source ou importer un fichier propre.",
    ),
    NoTradeReason.INSUFFICIENT_HISTORY.value: (
        "Historique trop court.",
        "Le wallet n'a pas assez de jours observables pour etre shortliste.",
        "Attendre plus de donnees ou garder en watch-only.",
    ),
    NoTradeReason.INSUFFICIENT_CLOSED_PNL.value: (
        "Pas assez de points closed PnL.",
        "L'edge du leader n'est pas mesurable sans echantillon suffisant.",
        "Collecter plus de fills userFillsByTime.",
    ),
    NoTradeReason.PNL_CONCENTRATION_TOO_HIGH.value: (
        "PnL trop concentre.",
        "Le resultat semble dependre d'un seul gros trade.",
        "Refuser jusqu'a preuve de regularite.",
    ),
    NoTradeReason.ONE_BIG_WIN_RISK.value: (
        "Risque one-big-win.",
        "Un seul gain explique trop le PnL total.",
        "Analyser plus de cycles et de coins.",
    ),
    NoTradeReason.LOW_CONSISTENCY.value: (
        "Consistance trop faible.",
        "Les resultats ne sont pas assez repetables.",
        "Garder en observation recherche.",
    ),
    NoTradeReason.MAX_DRAWDOWN_TOO_HIGH.value: (
        "Drawdown trop eleve.",
        "Le profil de pertes depasse le seuil configure.",
        "Refuser le suivi paper.",
    ),
    NoTradeReason.STALE_SIGNAL.value: (
        "Signal trop vieux.",
        "Le retard degrade trop l'hypothese de copie.",
        "Reduire le delai de collecte ou passer WS read-only shortlist.",
    ),
    NoTradeReason.EDGE_UNMEASURABLE.value: (
        "Edge non mesurable.",
        "Le leader_expected_edge_bps manque.",
        "Calculer l'edge depuis un echantillon local plus riche.",
    ),
    NoTradeReason.EDGE_REMAINING_TOO_LOW.value: (
        "Edge restant insuffisant.",
        "Apres frais, spread, slippage, retard et liquidite, l'edge restant est trop faible.",
        "Ne rien simuler et attendre un meilleur contexte.",
    ),
    NoTradeReason.SPREAD_TOO_WIDE.value: (
        "Spread trop large.",
        "Le cout d'entree paper serait trop defavorable.",
        "Attendre un carnet plus propre.",
    ),
    NoTradeReason.SLIPPAGE_TOO_HIGH.value: (
        "Slippage trop haut.",
        "Le prix paper pessimiste degrade trop la simulation.",
        "Reduire notional ou attendre plus de liquidite.",
    ),
    NoTradeReason.LIQUIDITY_TOO_LOW.value: (
        "Liquidite trop faible.",
        "Le carnet ne semble pas assez profond pour une simulation honnete.",
        "Bloquer ce coin ou diminuer la taille paper.",
    ),
    NoTradeReason.COPY_DEGRADATION_TOO_HIGH.value: (
        "Degradation copy trop haute.",
        "Retard, couts et penalites depassent le seuil.",
        "Ne pas suivre cette observation.",
    ),
    NoTradeReason.UNKNOWN_DELTA.value: (
        "Delta ambigu.",
        "Open/add/reduce/close n'est pas classable avec confiance.",
        "Garder UNKNOWN et collecter un snapshot/fill complementaire.",
    ),
    NoTradeReason.REDUCE_OR_CLOSE_NOT_ENTRY.value: (
        "Reduction ou fermeture observee.",
        "Ce batch ne cree pas d'entree paper depuis une sortie leader.",
        "Verifier s'il existe une position paper correspondante avant une fermeture future.",
    ),
    NoTradeReason.NO_MATCHING_PAPER_POSITION_FOR_CLOSE.value: (
        "Pas de position paper a fermer.",
        "Une fermeture leader ne peut pas fermer une simulation inexistante.",
        "Ignorer ou reconciler les positions paper.",
    ),
    NoTradeReason.DUPLICATE_FILL.value: (
        "Fill deja vu.",
        "Le duplicate guard evite une double simulation.",
        "Conserver le curseur resume.",
    ),
    NoTradeReason.BLOCKED_ASSET.value: (
        "Asset bloque.",
        "Le coin est interdit par configuration risque.",
        "Retirer du signal ou reviser la liste bloquees.",
    ),
    NoTradeReason.MAX_OPEN_PAPER_TRADES_REACHED.value: (
        "Nombre max de paper trades atteint.",
        "Le portefeuille paper local est deja au plafond.",
        "Fermer/reconciler des simulations ou augmenter prudemment le plafond.",
    ),
    NoTradeReason.NETWORK_READ_DISABLED.value: (
        "Lecture reseau desactivee.",
        "Aucun appel /info ou WS n'est lance sans accord explicite.",
        "Relancer avec --network-read pour une collecte read-only bornee.",
    ),
    NoTradeReason.SOURCE_UNAVAILABLE.value: (
        "Source indisponible.",
        "Aucune donnee locale exploitable n'a ete trouvee.",
        "Importer un CSV ou collecter en lecture seule.",
    ),
    NoTradeReason.RATE_LIMIT_GUARD.value: (
        "Rate limit guard.",
        "Le run s'arrete pour eviter une boucle ou trop de requetes.",
        "Reprendre plus tard avec des bornes plus basses.",
    ),
    NoTradeReason.OPEN_ORDERS_CONTEXT_ONLY.value: (
        "Ordres ouverts observes.",
        "Un openOrder est un contexte, pas une preuve de fill execute.",
        "Attendre un fill ou un changement de position confirme.",
    ),
    NoTradeReason.API_RESPONSE_INVALID.value: (
        "Reponse API invalide.",
        "La reponse /info ne respecte pas le format attendu.",
        "Verifier la source et conserver le raw_json pour diagnostic.",
    ),
    NoTradeReason.PAGINATION_STOPPED.value: (
        "Pagination arretee.",
        "La collecte s'est arretee sur une limite, une page vide ou un timestamp non progressif.",
        "Reprendre avec un curseur ou des bornes plus petites.",
    ),
    NoTradeReason.WEBSOCKET_LIMIT_GUARD.value: (
        "Limite WebSocket.",
        "Le plan depasse les limites de duree, subscriptions ou users uniques.",
        "Reduire la shortlist ou fixer une duree bornee.",
    ),
    NoTradeReason.ARCHIVE_DIRTY_ROOT_ZIP.value: (
        "Archive sale a la racine.",
        "Un ZIP/7Z/RAR dans le projet peut contenir des runtime files.",
        "Supprimer l'archive racine et utiliser le bouton d'archive propre Desktop.",
    ),
    NoTradeReason.LEADER_EQUITY_MISSING.value: (
        "Equity leader manquante.",
        "Le ratio de copie leader/follower n'est pas mesurable sans accountValue leader.",
        "Collecter clearinghouseState avec marginSummary ou garder en observation.",
    ),
    NoTradeReason.LEADER_POSITION_NOTIONAL_UNMEASURABLE.value: (
        "Notional leader non mesurable.",
        "La taille ou le prix de reference leader manque.",
        "Attendre un fill/position complet avant toute simulation paper.",
    ),
    NoTradeReason.COPY_NOTIONAL_TOO_SMALL.value: (
        "Notional paper trop faible.",
        "Le sizing proportionnel tombe sous le minimum local configure.",
        "Refuser cette observation ou ajuster prudemment les bornes paper.",
    ),
    NoTradeReason.COPY_NOTIONAL_CAPPED.value: (
        "Notional paper plafonne.",
        "Le sizing proportionnel depasse le cap local et doit etre rabote.",
        "Conserver le cap; ne jamais augmenter automatiquement.",
    ),
    NoTradeReason.PAPER_SIZING_INVALID.value: (
        "Sizing paper invalide.",
        "Une borne de portefeuille paper ou une equity locale est invalide.",
        "Corriger la configuration paper avant de simuler.",
    ),
}


def decision_from_reason(
    reason: str | NoTradeReason,
    *,
    observed: str,
    leader_wallet: str | None = None,
    coin: str | None = None,
    candidate_id: str | None = None,
    context: dict | None = None,
) -> NoTradeDecision:
    reason_value = reason.value if isinstance(reason, NoTradeReason) else str(reason)
    _, why, next_action = REASON_TEXT.get(
        reason_value,
        ("Observation refusee.", "La raison n'est pas assez documentee.", "Inspecter les details techniques."),
    )
    return NoTradeDecision(
        decision_id="nt:" + stable_hash(f"{reason_value}:{observed}:{leader_wallet}:{coin}:{candidate_id}")[:24],
        created_at=utc_now(),
        reason=NoTradeReason(reason_value) if reason_value in NoTradeReason._value2member_map_ else NoTradeReason.SOURCE_UNAVAILABLE,
        observed=observed,
        why_not_simulable=why,
        missing_data=_missing_data(reason_value),
        next_action=next_action,
        leader_wallet=leader_wallet,
        coin=coin,
        candidate_id=candidate_id,
        context=context or {},
    )


def decisions_from_signal(signal: SignalCandidate) -> list[NoTradeDecision]:
    if signal.decision == SignalDecision.ACCEPT_PAPER:
        return []
    return [
        decision_from_reason(
            reason,
            observed=f"{signal.action_type.value} {signal.coin} observe sur leader {signal.leader_wallet}",
            leader_wallet=signal.leader_wallet,
            coin=signal.coin,
            candidate_id=signal.candidate_id,
            context={"edge_remaining_bps": signal.edge_remaining_bps, "copy_degradation_bps": signal.copy_degradation_bps},
        )
        for reason in (signal.refusal_reasons or [NoTradeReason.EDGE_UNMEASURABLE.value])
    ]


def write_no_trade_reports(decisions: list[NoTradeDecision], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "no_trade_report.json"
    md_path = output_dir / "no_trade_report.md"
    csv_path = output_dir / "no_trade_report.csv"
    json_path.write_text(json.dumps(to_jsonable(decisions), indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(format_no_trade_markdown(decisions), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "decision_id",
                "created_at",
                "reason",
                "risk_level",
                "component",
                "leader_wallet",
                "coin",
                "candidate_id",
                "observed",
                "why_not_simulable",
                "missing_data",
                "next_action",
            ],
        )
        writer.writeheader()
        for decision in decisions:
            writer.writerow(
                {
                    "decision_id": decision.decision_id,
                    "created_at": decision.created_at.isoformat(),
                    "reason": decision.reason.value,
                    "risk_level": decision.risk_level,
                    "component": decision.component,
                    "leader_wallet": decision.leader_wallet,
                    "coin": decision.coin,
                    "candidate_id": decision.candidate_id,
                    "observed": decision.observed,
                    "why_not_simulable": decision.why_not_simulable,
                    "missing_data": decision.missing_data,
                    "next_action": decision.next_action,
                }
            )
    return json_path, md_path


def generate_markdown_report(decisions: list[NoTradeDecision]) -> str:
    """Alias for format_no_trade_markdown."""
    return format_no_trade_markdown(decisions)


def format_no_trade_markdown(decisions: list[NoTradeDecision]) -> str:
    lines = [
        "# Rapport No-Trade",
        "",
        "Mode: observation / paper mock USDC uniquement. Aucun ordre reel.",
        "",
    ]
    if not decisions:
        lines.append("Aucun refus stocke pour le moment.")
        return "\n".join(lines)
    counts = Counter(decision.reason.value for decision in decisions)
    lines.append("## Synthese")
    for reason, count in sorted(counts.items()):
        lines.append(f"- {reason}: {count}")
    lines.append("")
    lines.append("## Details")
    for decision in decisions:
        lines.extend(
            [
                f"### {decision.reason.value}",
                f"- Wallet: `{decision.leader_wallet}`",
                f"- Coin: {decision.coin}",
                f"- Observe: {decision.observed}",
                f"- Pourquoi: {decision.why_not_simulable}",
                f"- Donnee manquante: {decision.missing_data}",
                f"- Risque: {decision.risk_level}",
                f"- Composant: {decision.component}",
                f"- Action suivante: {decision.next_action}",
                "",
            ]
        )
    return "\n".join(lines)


def _missing_data(reason: str) -> str:
    if reason in {NoTradeReason.EDGE_UNMEASURABLE.value, NoTradeReason.INSUFFICIENT_CLOSED_PNL.value}:
        return "closedPnl/edge mesurable insuffisant"
    if reason == NoTradeReason.UNKNOWN_DELTA.value:
        return "snapshot ou fill coherent"
    if reason == NoTradeReason.NETWORK_READ_DISABLED.value:
        return "autorisation explicite --network-read"
    if reason == NoTradeReason.SOURCE_UNAVAILABLE.value:
        return "source locale/import exploitable"
    if reason == NoTradeReason.LEADER_EQUITY_MISSING.value:
        return "marginSummary.accountValue du leader"
    if reason == NoTradeReason.LEADER_POSITION_NOTIONAL_UNMEASURABLE.value:
        return "taille position leader et prix de reference"
    if reason in {NoTradeReason.COPY_NOTIONAL_TOO_SMALL.value, NoTradeReason.PAPER_SIZING_INVALID.value}:
        return "bornes de sizing paper mock USDC coherentes"
    return "aucune donnee supplementaire obligatoire, refus par risque"
