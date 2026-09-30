"""LE CLIQUET DU MARQUEUR `audit:fixture` — pour qu'une exemption reste une exception.

CONTEXTE (2026-07-18)
---------------------
Quatre contrôles de sécurité bloquaient l'audit sur des FAUX POSITIFS. À chaque fois, le même
motif : **le garde était accusé à la place du voleur**.

  * la blocklist des paquets interdits contenait le mot « walletconnect » ;
  * la liste des motifs interdits du moissonneur contenait la chaîne « exec( » ;
  * le canari contenait l'appât d'arnaque qu'il doit REJETER (« Guaranteed profit ») ;
  * un hash d'événement ERC-20 public avait la forme d'une clé privée (`0x` + 64 hexa).

La correction paresseuse aurait été d'exclure ces fichiers en bloc. Un fichier exclu est aveugle
POUR TOUJOURS et pour TOUT son contenu : le jour où une vraie promesse de PnL s'y glisse, plus
personne ne le voit. On a donc choisi une exemption **par ligne**, visible en relecture de diff.

CE QUE CE TEST GARANTIT
-----------------------
Le marqueur ne doit pas devenir un passe-droit qu'on colle partout. Il est donc COMPTÉ, et le
compte ne remonte pas. Un audit qu'on peut faire taire ligne à ligne, sans limite, ne mesure
plus rien — exactement le reproche qu'on fait aux garde-fous affamés.
"""
from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DOSSIERS = ("src", "tools", "hyper_smart_observer")
#: `audit_report.py` DÉFINIT le marqueur (`if "audit:fixture" in src_line`). Le compter
#: reviendrait à accuser le mécanisme d'être son propre abus — le même travers que les 4 faux
#: positifs qui ont motivé tout ceci.
FICHIERS_QUI_DEFINISSENT_LE_MARQUEUR = ("tools/audit_report.py",)

#: CLIQUET. 2026-07-18 : 2 marqueurs (canari.py, verifier_moissonneur.py), tous deux des
#: échantillons NÉGATIFS que le code doit rejeter. Il ne remonte pas.
PLAFOND_MARQUEURS = 2


def _lignes_marquees() -> list[str]:
    trouves: list[str] = []
    for dossier in DOSSIERS:
        base = RACINE / dossier
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            rel = p.relative_to(RACINE).as_posix()
            if "__pycache__" in p.parts or rel in FICHIERS_QUI_DEFINISSENT_LE_MARQUEUR:
                continue
            for i, ligne in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if "audit:fixture" in ligne.lower():
                    trouves.append("%s:%d" % (p.relative_to(RACINE).as_posix(), i))
    return trouves


def test_le_marqueur_audit_fixture_ne_prolifere_pas():
    marques = _lignes_marquees()
    assert len(marques) <= PLAFOND_MARQUEURS, (
        "LE MARQUEUR `audit:fixture` PROLIFÈRE : %d lignes exemptées (plafond %d).\n    %s\n\n"
        "Chaque marqueur AVEUGLE un contrôle de sécurité sur une ligne. Deux ou trois exceptions "
        "légitimes (un canari, une blocklist), c'est de l'ingénierie. Vingt, c'est un audit "
        "désactivé en douceur — la façon la plus courante de perdre un garde-fou."
        % (len(marques), PLAFOND_MARQUEURS, "\n    ".join(marques))
    )


def test_chaque_marqueur_est_accompagne_d_une_raison():
    """Un marqueur nu est une exemption sans procès. On exige une explication sur la ligne."""
    nus = []
    for dossier in DOSSIERS:
        base = RACINE / dossier
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            rel = p.relative_to(RACINE).as_posix()
            if "__pycache__" in p.parts or rel in FICHIERS_QUI_DEFINISSENT_LE_MARQUEUR:
                continue
            for i, ligne in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                bas = ligne.lower()
                if "audit:fixture" not in bas:
                    continue
                # après le marqueur, il doit rester une justification (pas juste le mot-clé)
                reste = bas.split("audit:fixture", 1)[1].strip(" -—:#")
                if len(reste) < 20:
                    nus.append("%s:%d" % (p.relative_to(RACINE).as_posix(), i))
    assert not nus, (
        "marqueur(s) `audit:fixture` sans justification écrite : %r\n"
        "Exempter un contrôle de sécurité sans dire POURQUOI, c'est le désactiver." % nus)
