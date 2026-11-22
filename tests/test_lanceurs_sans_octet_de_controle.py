"""AUCUN OCTET DE CONTROLE dans un lanceur — le defaut invisible a grep.

MESURE DU 22/11/2026. En cablant `tools/avancement_rattrapage.py` dans l'ecran d'etat, mon
script generateur a ecrit `"...tools\\avancement..."` dans un heredoc qui a mange un
antislash. Python a donc lu `\\a` = **BELL (0x07)**, et le lanceur a recu :

```
if exist "%CV_ROOT%tools<BEL>vancement_rattrapage.py" (
```

Le `a` avait disparu DANS l'octet de controle. Consequences :

* le `if exist` ne trouvait jamais le fichier -> l'appel ne s'executait pas, **en silence** ;
* `grep avancement_rattrapage.py` ne voyait rien dans la ligne active, donc mon propre
  validateur de chaine declarait le maillon `NON_CABLE` apres que je l'avais cable -- et
  j'aurais pu croire mon outil plutot que les octets ;
* aucun affichage d'erreur : un `.cmd` passe simplement a la ligne suivante.

C'est la famille `echappement_dans_du_code_genere` : `\\a`, `\\b`, `\\f`, `\\v`, `\\t` hors
chaine brute deviennent des octets de controle. Cette garde les refuse pour tous les
lanceurs, parce qu'un defaut invisible a l'oeil et a grep ne se trouve que par une mesure.

Note sur la TABULATION : elle est licite dans un `.cmd` (indentation), donc elle n'est pas
refusee -- on ne refuse que ce qui n'a aucune raison d'etre la.
"""
from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

#: Octets qu'aucun lanceur n'a de raison de porter. La TAB (0x09) est volontairement
#: absente : elle sert a indenter. Le CR (0x0D) et le LF (0x0A) sont les fins de ligne.
OCTETS_INTERDITS = {
    0x00: "NUL", 0x07: "BEL", 0x08: "BACKSPACE", 0x0B: "VTAB", 0x0C: "FORMFEED",
    0x1A: "SUB (fin de fichier DOS)", 0x1B: "ESCAPE",
}


def _lanceurs() -> list[Path]:
    return sorted(RACINE.glob("*.cmd"))


def test_il_y_a_bien_des_lanceurs_a_verifier():
    """Une garde qui ne verifie rien passe au vert pour rien."""
    assert len(_lanceurs()) >= 10


def test_aucun_lanceur_ne_porte_un_octet_de_controle():
    coupables: list[str] = []
    for lanceur in _lanceurs():
        octets = lanceur.read_bytes()
        for valeur, nom in OCTETS_INTERDITS.items():
            compte = octets.count(bytes([valeur]))
            if compte:
                position = octets.find(bytes([valeur]))
                autour = octets[max(0, position - 40):position + 20]
                coupables.append(
                    f"{lanceur.name} : {compte}x {nom} (0x{valeur:02X}) vers l'octet"
                    f" {position} — {autour!r}")
    assert not coupables, "octet(s) de controle dans un lanceur :\n- " + "\n- ".join(coupables)


def test_le_chemin_du_suivi_de_rattrapage_est_INTACT():
    """Le cas precis : `tools\\avancement_rattrapage.py` avait perdu son `a` dans un BEL.

    On verifie le chemin COMPLET, pas la presence du nom : c'est le separateur et la
    premiere lettre qui avaient ete manges, et un test sur le nom seul serait reste vert.
    """
    lanceur = RACINE / "LANCER_COLLECTEURS_COPY_VAULT.cmd"
    octets = lanceur.read_bytes()
    attendu = b"tools" + b"\\" + b"avancement_rattrapage.py"
    assert attendu in octets, "le chemin du suivi de rattrapage est abime ou absent"
    assert bytes([7]) not in octets


def test_les_lanceurs_restent_en_CRLF_sans_double_retour():
    """Piege connu du depot : 358 fins `\\r\\r\\n` avaient deja ete reparees ici."""
    for lanceur in _lanceurs():
        octets = lanceur.read_bytes()
        assert b"\r\r\n" not in octets, f"{lanceur.name} : double CR"
        assert octets.count(b"\n") == octets.count(b"\r\n"), f"{lanceur.name} : LF orphelin"
