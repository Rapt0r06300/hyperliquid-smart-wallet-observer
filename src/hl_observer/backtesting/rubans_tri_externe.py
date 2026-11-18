"""Produire un ruban de replay TRIÉ et DÉDOUBLONNÉ sans tenir le corpus entier en mémoire.

LE DÉFAUT, MESURÉ LE 17/11/2026 SUR LE REJEU RÉEL DU LABO.
``materialize_safe_workspace`` charge les deux tiers du coffre dans des dictionnaires Python —
871 130 fills et 750 263 carnets du tier SAFE, 945 504 fills et 716 706 carnets du tier LOCAL —
pour les dédoublonner par identité, les trier, puis les écrire dans huit rubans. La phase
suivante **relit ces rubans depuis le disque**. Autrement dit, le corpus n'est tenu en mémoire que
pour être trié et écrit.

Conséquence observée : le pont LOCAL s'arrête en annonçant ``MEMOIRE_CRITIQUE`` après avoir lu
452 shards sur 5 570 dans la fenêtre, et le labo conclut « trop peu de jours » alors que le tunnel
compte **onze jours exploitables sur onze** dans le même coffre. Le verdict décrivait la lecture,
pas la donnée.

CE QUE FAIT CE MODULE, ET CE QU'IL NE CHANGE PAS.
Deux passes sur la source, puis une fusion :

1. ``gagnants`` : première passe. Pour chaque identité, on retient **uniquement** l'index de la
   ligne qui doit survivre — pas la ligne. Une empreinte de 16 octets remplace le tuple
   d'identité (voir ``EMPREINTE_OCTETS``).
2. ``ecrire_ruban_trie`` : seconde passe. Les lignes gagnantes sont écrites par morceaux triés
   dans des fichiers temporaires, puis fusionnées en flux (``heapq.merge``).

**Les octets produits sont identiques à ceux de l'approche en mémoire.** C'est le contrat, et il
est vérifié par un test qui compare les deux chemins sur un corpus construit pour piéger les deux
difficultés : des clés de tri à égalité (où seul un tri STABLE donne le bon ordre) et des
doublons d'identité à préférence différente. L'index global entre dans la clé de tri en dernière
position : il rend le tri total, donc reproductible, et reproduit exactement l'ordre d'insertion
que préservait le tri stable sur un dictionnaire.

CE QUI RESTE INTERDIT : lire deux fois une source qui ne rend pas les mêmes lignes dans le même
ordre. ``fabrique`` doit être rejouable à l'identique ; sinon la passe 2 ne retrouve pas les
gagnants désignés par la passe 1. Le module le VÉRIFIE (``lignes_relues`` doit égaler
``lignes_lues``) et refuse d'écrire un ruban dont la source a bougé, au lieu de produire un ruban
incomplet en silence.

PAPER / LECTURE SEULE : aucun ordre, aucun réseau. Les rubans sont écrits atomiquement.
"""
from __future__ import annotations

import heapq
import json
import os
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from hashlib import blake2b
from pathlib import Path
from typing import Any

SCHEMA = "hypersmart.rubans_tri_externe.v1"

#: Taille de l'empreinte d'identité. 16 octets (128 bits) : pour deux millions de lignes, la
#: probabilité d'une collision est de l'ordre de 10⁻²⁷ — moins probable qu'une erreur de disque
#: non détectée. Garder les tuples d'identité coûterait plusieurs centaines de mégaoctets.
EMPREINTE_OCTETS = 16

#: Lignes gardées en mémoire avant d'écrire un morceau trié. 50 000 lignes de fill ≈ 60 Mo.
LIGNES_PAR_MORCEAU = 50_000

#: Sérialisation EXACTE des rubans de replay. Toute divergence ici change les empreintes publiées
#: dans le manifeste et donc l'identité du corpus : ce n'est pas un détail de forme.
def serialiser(ligne: Mapping[str, Any]) -> str:
    return json.dumps(ligne, ensure_ascii=False, sort_keys=True)


#: Séparateur de champs dans l'empreinte : un caractère de contrôle qu'aucune adresse, aucun
#: symbole et aucun nombre ne peut contenir. Sans lui, ("ab", "c") et ("a", "bc") se confondraient.
SEPARATEUR_DE_CHAMPS = chr(31)


def _canonique(valeur: Any) -> str:
    """Forme canonique d'un champ d'identité, avec la MÊME sémantique qu'une clé de dictionnaire.

    L'ancien chemin utilisait un tuple Python comme clé. Or en Python ``1 == 1.0 == True``, et les
    trois donnent la même entrée de dictionnaire. Une empreinte qui les distinguerait ferait
    diverger les deux chemins : deux lignes que le labo comptait pour une seule deviendraient deux
    signaux. Les grands entiers (un ``tid`` tient sur une cinquantaine de bits) ne passent JAMAIS
    par un flottant — leur exactitude passe avant la commodité.
    """
    if valeur is None:
        return "z"
    if isinstance(valeur, str):
        return "s" + valeur
    if isinstance(valeur, bool) or isinstance(valeur, int):
        return "n" + str(int(valeur))
    if isinstance(valeur, float):
        if valeur.is_integer() and abs(valeur) < 2 ** 53:
            return "n" + str(int(valeur))
        return "n" + repr(valeur)
    if isinstance(valeur, (list, tuple)):
        # L'identité d'un carnet contient ses niveaux de prix. Le labo les compare comme des
        # tuples Python, où (1,) == (1.0,) : la normalisation doit donc descendre dedans, sinon
        # deux carnets identiques pour le labo auraient deux empreintes.
        return "l" + chr(30).join(_canonique(x) for x in valeur)
    return "o" + str(valeur)


def empreinte(identite: Sequence[Any]) -> bytes:
    """Empreinte stable d'un tuple d'identité, de même sémantique qu'une clé de dictionnaire."""
    brut = SEPARATEUR_DE_CHAMPS.join(_canonique(v) for v in identite)
    return blake2b(brut.encode("utf-8", errors="surrogatepass"),
                   digest_size=EMPREINTE_OCTETS).digest()


def gagnants(fabrique: Callable[[], Iterable[Mapping[str, Any]]], *,
             cle_identite: Callable[[Mapping[str, Any]], Sequence[Any]],
             rang_preference: Callable[[Mapping[str, Any]], int] | None = None,
             ) -> dict[str, Any]:
    """Première passe : l'index de la ligne qui survit pour chaque identité.

    ``rang_preference`` : plus petit = préféré. À préférence égale, la PREMIÈRE ligne lue gagne —
    c'est la règle qu'appliquait le dictionnaire (remplacement seulement quand la nouvelle ligne
    est préférable).

    DEUX index sont retenus, et c'est la finesse du contrat : celui de la ligne **écrite** (la
    préférée) et celui de la **première** occurrence de l'identité. Car un dictionnaire Python qui
    remplace une valeur ne change PAS la position d'insertion de sa clé : le tri stable d'origine
    ordonne donc selon la première occurrence, tout en écrivant le contenu préféré. Confondre les
    deux change l'ordre du ruban dès qu'un fill vu en snapshot est remplacé par le même fill vu en
    direct — un tirage aléatoire l'a mis en évidence le 18/11/2026, avant tout branchement.
    """
    retenus: dict[bytes, tuple[int, int, int]] = {}
    lignes = 0
    for index, ligne in enumerate(fabrique()):
        lignes += 1
        cle = empreinte(cle_identite(ligne))
        rang = 0 if rang_preference is None else int(rang_preference(ligne))
        ancien = retenus.get(cle)
        if ancien is None:
            retenus[cle] = (rang, index, index)
        elif rang < ancien[0]:
            retenus[cle] = (rang, index, ancien[2])      # l'ordre reste celui de la 1re occurrence
    return {
        "schema_version": SCHEMA,
        "index_par_identite": {cle: ecrit for cle, (_rang, ecrit, _premier) in retenus.items()},
        "ordre_par_identite": {cle: premier for cle, (_rang, _ecrit, premier) in retenus.items()},
        "lignes_lues": lignes,
        "identites": len(retenus),
        "doublons": lignes - len(retenus),
    }


def _ecrire_morceau(dossier: Path, numero: int, morceau: list[tuple[tuple, str]]) -> Path:
    morceau.sort(key=lambda paire: paire[0])
    chemin = dossier / f"morceau_{numero:05d}.jsonl"
    with chemin.open("w", encoding="utf-8", newline="") as flux:
        for cle, texte in morceau:
            flux.write(json.dumps([list(cle), texte], ensure_ascii=False) + "\n")
    return chemin


def _relire_morceau(chemin: Path) -> Iterator[tuple[list, str]]:
    with chemin.open("r", encoding="utf-8", newline="") as flux:
        for brut in flux:
            cle, texte = json.loads(brut)
            yield cle, texte


def ecrire_rubans_tries(cibles: Sequence[tuple[Any, Callable[[Mapping[str, Any]], bool] | None]],
                        fabrique: Callable[[], Iterable[Mapping[str, Any]]], *,
                        cle_tri: Callable[[Mapping[str, Any]], Sequence[Any]],
                        cle_identite: Callable[[Mapping[str, Any]], Sequence[Any]],
                        rang_preference: Callable[[Mapping[str, Any]], int] | None = None,
                        dossier_temporaire: str | Path | None = None,
                        lignes_par_morceau: int = LIGNES_PAR_MORCEAU,
                        selection: Mapping[str, Any] | None = None,
                        ) -> dict[str, dict[str, Any]]:
    """Écrit PLUSIEURS rubans depuis le même corpus, en UNE seule seconde passe.

    ``cibles`` : une liste de ``(chemin, garder)``. Chaque ruban reçoit les lignes retenues par son
    filtre, après une déduplication FAITE UNE SEULE FOIS. Le labo tire ainsi deux rubans des fills
    (les snapshots, le direct causal) sans relire onze millions de lignes pour chacun — une passe
    coûtait 709 s à la mesure du 18/11/2026.

    Rend un bilan par chemin. NE TRONQUE JAMAIS EN SILENCE : si la source bouge entre les deux
    passes, aucun ruban n'est écrit.
    """
    chemins = [Path(chemin) for chemin, _garder in cibles]
    for chemin in chemins:
        if chemin.is_symlink():
            raise OSError("refus d'ecrire un ruban de replay via un lien symbolique")
    if selection is None:
        selection = gagnants(fabrique, cle_identite=cle_identite, rang_preference=rang_preference)
    retenus: Mapping[bytes, int] = selection["index_par_identite"]
    ordre: Mapping[bytes, int] = selection["ordre_par_identite"]
    base = Path(dossier_temporaire) if dossier_temporaire is not None else chemins[0].parent
    base.mkdir(parents=True, exist_ok=True)
    morceaux: list[list[Path]] = [[] for _ in cibles]
    tampons: list[list[tuple[tuple, str]]] = [[] for _ in cibles]
    ecrites = [0 for _ in cibles]
    relues = trouves = 0
    tous: list[Path] = []
    try:
        for index, ligne in enumerate(fabrique()):
            relues += 1
            cle = empreinte(cle_identite(ligne))
            if retenus.get(cle) != index:
                continue
            trouves += 1
            texte = None
            for rang, (_chemin, garder) in enumerate(cibles):
                if garder is not None and not garder(ligne):
                    continue
                if texte is None:
                    texte = serialiser(ligne)
                # L'index de la PREMIÈRE occurrence clôt la clé : tri total, et ordre identique au
                # tri stable d'origine sur un dictionnaire (voir `gagnants`).
                tampons[rang].append(((*cle_tri(ligne), ordre[cle]), texte))
                ecrites[rang] += 1
                if len(tampons[rang]) >= max(1, int(lignes_par_morceau)):
                    chemin_morceau = _ecrire_morceau(base, len(tous), tampons[rang])
                    morceaux[rang].append(chemin_morceau)
                    tous.append(chemin_morceau)
                    tampons[rang] = []
        for rang, tampon in enumerate(tampons):
            if tampon:
                chemin_morceau = _ecrire_morceau(base, len(tous), tampon)
                morceaux[rang].append(chemin_morceau)
                tous.append(chemin_morceau)
        if relues != selection["lignes_lues"]:
            raise ValueError(
                "la source a change entre les deux passes "
                f"({selection['lignes_lues']} lignes puis {relues}) : aucun ruban n'est ecrit")
        if trouves != len(retenus):
            raise ValueError(
                f"gagnants introuvables a la seconde passe ({trouves} retrouves pour "
                f"{len(retenus)} identites) : aucun ruban n'est ecrit")
        bilans: dict[str, dict[str, Any]] = {}
        for rang, chemin in enumerate(chemins):
            provisoire = chemin.with_suffix(chemin.suffix + ".partial")
            premiere = derniere = None
            with provisoire.open("w", encoding="utf-8", newline="") as ruban:
                flux = heapq.merge(*(_relire_morceau(m) for m in morceaux[rang]),
                                   key=lambda paire: paire[0])
                for cle_ecrite, texte in flux:
                    if premiere is None:
                        premiere = tuple(cle_ecrite[:-1])
                    derniere = tuple(cle_ecrite[:-1])
                    ruban.write(texte + "\n")
            os.replace(provisoire, chemin)
            bilans[str(chemin)] = {
                "schema_version": SCHEMA,
                "lignes_lues": selection["lignes_lues"],
                "lignes_ecrites": ecrites[rang],
                "lignes_retenues": trouves,
                "ecartees_par_le_filtre": trouves - ecrites[rang],
                "doublons_ecartes": selection["doublons"],
                "morceaux": len(morceaux[rang]),
                "lignes_par_morceau": int(lignes_par_morceau),
                "premiere_cle": premiere,
                "derniere_cle": derniere,
            }
        return bilans
    finally:
        for m in tous:
            try:
                m.unlink()
            except OSError:
                pass


def ecrire_ruban_trie(chemin: str | Path, fabrique: Callable[[], Iterable[Mapping[str, Any]]], *,
                      cle_tri: Callable[[Mapping[str, Any]], Sequence[Any]],
                      cle_identite: Callable[[Mapping[str, Any]], Sequence[Any]],
                      rang_preference: Callable[[Mapping[str, Any]], int] | None = None,
                      dossier_temporaire: str | Path | None = None,
                      lignes_par_morceau: int = LIGNES_PAR_MORCEAU,
                      selection: Mapping[str, Any] | None = None,
                      garder: Callable[[Mapping[str, Any]], bool] | None = None,
                      ) -> dict[str, Any]:
    """Un seul ruban : cas particulier de ``ecrire_rubans_tries``, gardé pour la lisibilité."""
    bilans = ecrire_rubans_tries(
        [(chemin, garder)], fabrique, cle_tri=cle_tri, cle_identite=cle_identite,
        rang_preference=rang_preference, dossier_temporaire=dossier_temporaire,
        lignes_par_morceau=lignes_par_morceau, selection=selection)
    return next(iter(bilans.values()))


def ecrire_ruban_en_memoire(chemin: str | Path, lignes: Iterable[Mapping[str, Any]], *,
                            cle_tri: Callable[[Mapping[str, Any]], Sequence[Any]],
                            cle_identite: Callable[[Mapping[str, Any]], Sequence[Any]],
                            rang_preference: Callable[[Mapping[str, Any]], int] | None = None,
                            ) -> dict[str, Any]:
    """L'ANCIENNE façon de faire, gardée comme RÉFÉRENCE de comparaison (et pour les petits corpus).

    Reproduit exactement ce que faisait le labo : un dictionnaire par identité, remplacement
    seulement si la nouvelle ligne est préférable, puis ``sorted`` stable et écriture.
    """
    retenus: dict[tuple, Mapping[str, Any]] = {}
    rangs: dict[tuple, int] = {}
    lues = 0
    for ligne in lignes:
        lues += 1
        cle = tuple(cle_identite(ligne))
        rang = 0 if rang_preference is None else int(rang_preference(ligne))
        if cle not in retenus or rang < rangs[cle]:
            retenus[cle] = ligne
            rangs[cle] = rang
    ordonnees = sorted(retenus.values(), key=lambda ligne: tuple(cle_tri(ligne)))
    chemin = Path(chemin)
    with chemin.open("w", encoding="utf-8", newline="") as ruban:
        ruban.writelines(serialiser(ligne) + "\n" for ligne in ordonnees)
    return {"schema_version": SCHEMA, "lignes_lues": lues, "lignes_ecrites": len(ordonnees),
            "doublons_ecartes": lues - len(ordonnees)}


__all__ = ["SCHEMA", "EMPREINTE_OCTETS", "LIGNES_PAR_MORCEAU", "SEPARATEUR_DE_CHAMPS",
           "serialiser", "empreinte",
           "gagnants", "ecrire_ruban_trie", "ecrire_rubans_tries",
           "ecrire_ruban_en_memoire"]
