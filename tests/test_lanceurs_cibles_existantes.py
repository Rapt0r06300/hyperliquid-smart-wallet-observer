"""Un lanceur ne doit jamais APPELER une cible qui n'existe pas.

MESURE DU 21/11/2026. L'audit de cablage des 12 lanceurs `.cmd` de la racine a lu
127 references de scripts. Une seule cible nommee est absente du depot ET de l'arbre
`HEAD` : `ENTRAINER_IA_AUTO.cmd`, citee par `LANCER_HYPERSMART.cmd` -- mais dans une ligne
`REM`, donc jamais executee. Elle est desormais marquee perimee sur place plutot
qu'effacee (le contrat du depot interdit de supprimer).

CE QUE CETTE GARDE AJOUTE. Rien ne verifiait qu'un `call` ou un `start` de lanceur pointe
vers un fichier reel. Un appel vers une cible absente ne casse pas toujours bruyamment :
`cmd` continue a la ligne suivante, le lanceur finit << sans erreur >>, et l'etape est
comptee comme faite. C'est exactement le faux succes que la mission interdit. La garde vit
DANS la suite, parce qu'une regle qui ne vit que dans un script d'audit ne garde rien --
quatre violations injectees avaient deja passe 49 verts le 21/11/2026.
"""
from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

#: `call "%~dp0X.cmd"`, `start "" "%ROOT%tools\\y.py"`, `cmd /c z.cmd` ...
#: Les `%` et `~` font PARTIE du chemin : sans eux, `"%~dp0POUSSER-GITHUB.cmd"` etait
#: capture `dp0POUSSER-GITHUB.cmd` et la garde accusait un lanceur juste. Mesure du
#: 21/11/2026 -- la garde a attrape mon propre motif, ce qui est son travail.
APPEL = re.compile(
    r"^\s*(?:@)?(?:call|start|cmd\s+/c)\b[^\r\n]*?"
    r"([A-Za-z0-9_%~][A-Za-z0-9_.%~\\/-]*\.(?:cmd|bat|py))",
    re.IGNORECASE | re.MULTILINE,
)

#: Prefixes de variables `cmd` qu'on retire avant de resoudre le chemin. Les plus longs
#: d'abord : `%~dp0` doit etre essaye avant `%~1`.
PREFIXES = ("%~dp0", "%ROOT%", "%CD%", "%~1", ".\\", "./")


def _lanceurs() -> list[Path]:
    return sorted(RACINE.glob("*.cmd"))


def _cible_existe(brut: str) -> bool:
    chemin = brut
    for prefixe in PREFIXES:
        if chemin.upper().startswith(prefixe.upper()):
            chemin = chemin[len(prefixe):]
    chemin = chemin.replace("\\", "/").lstrip("/")
    if (RACINE / chemin).exists():
        return True
    # Un lanceur peut citer un nom seul, resolu par le PATH du projet.
    nom = chemin.rsplit("/", 1)[-1].lower()
    for dossier in ("tools", "scripts", "src"):
        base = RACINE / dossier
        if base.is_dir() and any(p.name.lower() == nom for p in base.rglob(nom)):
            return True
    return (RACINE / nom).exists()


def test_les_lanceurs_existent_et_sont_lisibles():
    lanceurs = _lanceurs()
    assert len(lanceurs) >= 10, f"seulement {len(lanceurs)} lanceur(s) .cmd a la racine"
    for lanceur in lanceurs:
        octets = lanceur.read_bytes()
        assert octets, f"{lanceur.name} est vide"
        assert b"\r\r\n" not in octets, f"{lanceur.name} : double CR (piege connu du depot)"


def test_aucun_lanceur_n_APPELLE_une_cible_absente():
    """Un `call` vers un fichier absent laisse `cmd` continuer : faux succes silencieux."""
    manquantes: list[str] = []
    for lanceur in _lanceurs():
        texte = lanceur.read_bytes().decode("cp1252", errors="replace")
        for brut in sorted(set(APPEL.findall(texte))):
            if not _cible_existe(brut):
                manquantes.append(f"{lanceur.name} -> {brut}")
    assert not manquantes, "appel(s) vers une cible absente : " + "; ".join(manquantes)


def test_une_cible_citee_en_commentaire_n_est_PAS_un_appel():
    """`REM ... ENTRAINER_IA_AUTO.cmd ...` ne doit pas declencher la garde.

    Sans cette distinction, la garde crierait sur une note destinee a l'operateur et on
    apprendrait a l'ignorer -- le pire sort pour une garde.
    """
    assert not APPEL.findall("REM lance ENTRAINER_IA_AUTO.cmd a cote\r\n")
    assert not APPEL.findall("@REM voir DIAGNOSTIC_LANCEUR.cmd pour le detail\r\n")
    # Mais un vrai appel, lui, est bien vu.
    assert APPEL.findall('call "%~dp0POUSSER-GITHUB.cmd"\r\n')


def test_la_garde_voit_les_trois_formes_d_appel():
    """`call`, `start` et `cmd /c` : les trois formes presentes dans le depot."""
    for ligne, attendu in (
        ('call "%~dp0tools\\launcher_log.cmd"', "launcher_log.cmd"),
        ('start "" "%ROOT%tools\\run_bounded_collector.py"', "run_bounded_collector.py"),
        ("cmd /c ALINA_SYNC_COMPLETE.cmd", "ALINA_SYNC_COMPLETE.cmd"),
    ):
        trouve = APPEL.findall(ligne + "\r\n")
        assert trouve, ligne
        assert trouve[0].endswith(attendu), (ligne, trouve)


#: Tout script `tools\X.py` cite par un lanceur, QUELLE QUE SOIT la forme de l'appel. Le motif
#: `APPEL` ne voit que `call` / `start` / `cmd /c` : un lanceur qui execute Python directement
#: (`"!PYTHON!" "%ROOT%tools\x.py"`) lui echappait entierement.
SCRIPT_TOOLS = re.compile(r"tools[\/]([A-Za-z0-9_]+\.py)\b", re.IGNORECASE)


def test_aucun_octet_de_controle_dans_un_lanceur():
    """23/11/2026 : `tools\reconcilier_sources.py` etait devenu `tools` + 0x0D + `econcilier...`.

    Un `\r` ecrit dans une chaine Python NON brute devient un vrai retour chariot. `cmd` a cherche
    `toolseconcilier_sources.py`, l'etape echouait a chaque lancement d'AlinaSync, et le motif de
    la garde ci-dessus (`[^\r\n]*?`) s'arretait justement sur ce caractere.
    """
    fautes = []
    for lanceur in _lanceurs():
        octets = lanceur.read_bytes()
        for k, o in enumerate(octets):
            cr_isole = o == 13 and (k + 1 >= len(octets) or octets[k + 1] != 10)
            if cr_isole or (o < 32 and o not in (9, 10, 13)):
                fautes.append(f"{lanceur.name} octet {k} = 0x{o:02X} : {octets[max(0, k - 30):k + 10]!r}")
    assert not fautes, "octets de controle dans un lanceur :\n" + "\n".join(fautes[:10])


def test_tout_script_tools_cite_par_un_lanceur_existe():
    manquants = []
    for lanceur in _lanceurs():
        for ligne in lanceur.read_text(encoding="utf-8", errors="replace").splitlines():
            if ligne.lstrip().lower().startswith(("rem ", "::")):
                continue
            for nom in SCRIPT_TOOLS.findall(ligne):
                if not (RACINE / "tools" / nom).is_file():
                    manquants.append(f"{lanceur.name} : tools/{nom}")
    assert not manquants, "scripts cites mais absents :\n" + "\n".join(sorted(set(manquants)))
