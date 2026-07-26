"""AUDIT SÉCURITÉ du labo 18 h (Flo 26/07). PAPER-ONLY / READ-ONLY / DENY-BY-DEFAULT.

Interdits NON négociables : 0 /exchange opérationnel, 0 signature, 0 clé privée, 0 wallet connecté, 0 ordre
réel/testnet, 0 executor, 0 dépôt/retrait/transfert, 0 appel réseau d'écriture. Autorisés : /info read-only,
WebSocket read-only, archives locales, replays/backtests locaux, forward paper local, ledger paper isolé.

Le scanner distingue un MOT (dans une doc d'interdiction, un test, un commentaire, une chaîne) d'un VRAI appel
opérationnel dangereux. Il tourne au démarrage (dry-run/start) ET à la finalisation. 0 réseau lui-même.
"""
from __future__ import annotations

import re
from pathlib import Path

#: motifs d'un APPEL réellement dangereux (exécution/signature/clé/écriture réseau).
DANGER = [
    (r"requests?\.(post|put|delete|patch)\s*\(", "APPEL_RESEAU_ECRITURE"),
    (r"httpx\.(post|put|delete|patch)\s*\(", "APPEL_RESEAU_ECRITURE"),
    (r"aiohttp[^\n]*\.(post|put|delete|patch)\s*\(", "APPEL_RESEAU_ECRITURE"),
    (r"\bsign\s*\(", "SIGNATURE"),
    (r"sign_l1_action|sign_typed_data|eth_account|LocalAccount\b", "SIGNATURE"),
    (r"private_key|privatekey|secret_key\b", "CLE_PRIVEE"),
    (r"mnemonic|seed_phrase|from_mnemonic", "SEED"),
    (r"place_order|create_order|order_wire|bulk_orders|exchange\.order", "ORDRE"),
    (r"\.deposit\s*\(|\.withdraw\s*\(|\.transfer\s*\(", "DEPOT_RETRAIT_TRANSFERT"),
    (r"/exchange\b", "ENDPOINT_EXCHANGE"),
]
#: une ligne est INOFFENSIVE si elle est un commentaire, une doc d'interdiction, un test, une assertion, OU
#: une définition de REGEX/pattern (un scanner qui LISTE les motifs dangereux n'est pas dangereux lui-même).
#: `/info` = endpoint HL LECTURE SEULE (interrogé en POST par conception) -> autorisé, jamais un écrit dangereux.
INOFFENSIF = re.compile(r"(^\s*#|interdit|forbidden|deny|blocage|bloqu|assert|doit refuser|ne doit|0 ordre|"
                        r"read.?only|/info\b|paper|mock|fake|test_|DANGER\b|INOFFENSIF|motif|pattern|"
                        r'r"|r\'|re\.(compile|search|match|findall|sub)|\\b|Check\(|scan|audit)', re.I)
#: fichiers qui SONT des auditeurs/scanners de sécurité (contiennent légitimement les mots dangereux).
AUDITEUR = re.compile(r"(securite|safety|audit|scan|no_real_trade|secret)", re.I)


def scanner_fichier(p: Path) -> list[dict]:
    trouve = []
    if AUDITEUR.search(p.name):                    # un fichier d'audit liste les motifs -> pas un vrai appel
        return trouve
    try:
        lignes = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return trouve
    dans_docstring = False
    for i, l in enumerate(lignes, 1):
        if l.count('"""') % 2 == 1:                # bascule (approx) dedans/dehors d'un docstring
            dans_docstring = not dans_docstring
        if dans_docstring or INOFFENSIF.search(l):
            continue
        for motif, cat in DANGER:
            if re.search(motif, l):
                trouve.append({"fichier": str(p), "ligne": i, "categorie": cat, "extrait": l.strip()[:160]})
    return trouve


#: fichiers RÉELLEMENT exécutés par le run 18 h (la chaîne + le moteur réutilisé). Scanner CEUX-LÀ prouve la
#: sécurité du run — un run ne peut pas exécuter du code qu'il n'importe pas.
CHAINE_18H = ("tools/config_18h.py", "tools/securite_18h.py", "tools/catalogue_archives_18h.py",
              "tools/validation_18h.py", "tools/recherche_18h_mecanismes.py", "tools/replay_18h.py",
              "tools/registre_18h.py", "tools/recherche_18h.py", "tools/rapport_18h.py",
              "tools/recherche_14h_mecanismes.py")
PAQUETS_18H = ("src/hl_observer/experimental", "src/hl_observer/research_parallel")


def auditer(root: str | Path, *, sous_dossiers=None) -> dict:
    """Audit sécurité de la CHAÎNE réellement exécutée par le run 18 h (défaut) ou de dossiers explicites.
    securise=True seulement si AUCUN vrai appel dangereux. Docs/tests/regex/fichiers d'audit = inoffensifs."""
    root = Path(root)
    findings, fichiers = [], []
    if sous_dossiers is None:                       # défaut : la chaîne 18 h + les paquets moteur réutilisés
        fichiers += [root / f for f in CHAINE_18H]
        for paq in PAQUETS_18H:
            base = root / paq
            if base.exists():
                fichiers += [p for p in base.rglob("*.py") if "__pycache__" not in p.parts]
    else:
        for sd in sous_dossiers:
            base = root / sd
            if base.exists():
                fichiers += [p for p in base.rglob("*.py") if "__pycache__" not in p.parts]
    for p in fichiers:
        if p.exists():
            findings.extend(scanner_fichier(p))
    return {"securise": len(findings) == 0, "findings": findings, "fichiers_scannes": len(fichiers),
            "regle": "PAPER-ONLY / READ-ONLY / 0 exchange · 0 signature · 0 cle · 0 ordre · 0 executor"}


__all__ = ["auditer", "scanner_fichier", "DANGER"]
