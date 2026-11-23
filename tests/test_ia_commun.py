import json

import pytest

from cv_editor import BlocTexte
from ia_commun import (
    ErreurGeneration,
    construire_message_utilisateur,
    construire_resultat,
    extraire_json,
    valider_entrees,
)

DONNEES = {
    "entreprise": "Exemple SA",
    "poste": "Data Analyst",
    "lettre": {
        "objet": "  Candidature  ",
        "formule_appel": "Madame, Monsieur,",
        "paragraphes": ["Un.", "  ", "Deux."],
        "formule_politesse": "",
    },
    "cv_adaptations": [{"id": "p1", "nouveau_texte": " Nouveau "}, {"id": "", "nouveau_texte": "x"}, "invalide"],
}


def test_resultat_nettoye():
    resultat = construire_resultat(json.loads(json.dumps(DONNEES)), modele="gemini-test")
    assert resultat.objet == "Candidature"
    assert resultat.paragraphes == ["Un.", "Deux."]
    assert resultat.cv_adaptations == {"p1": "Nouveau"}
    assert resultat.formule_politesse  # formule par défaut si l'IA l'a oubliée
    assert resultat.modele == "gemini-test"


def test_nom_saisi_prioritaire():
    resultat = construire_resultat(DONNEES, entreprise_indiquee="Exemple Groupe", poste_indique="Analyste")
    assert (resultat.entreprise, resultat.poste) == ("Exemple Groupe", "Analyste")


def test_reponse_incomplete():
    with pytest.raises(ErreurGeneration):
        construire_resultat({"entreprise": "X"})
    with pytest.raises(ErreurGeneration):
        construire_resultat({**DONNEES, "lettre": {**DONNEES["lettre"], "paragraphes": ["", " "]}})


def test_extraire_json_tolerant():
    assert extraire_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extraire_json('Voici : {"b": 2} !') == {"b": 2}
    with pytest.raises(ValueError):
        extraire_json("pas de json")


def test_message_contient_les_contraintes_de_longueur():
    blocs = [BlocTexte("p0", "PROFIL", 6, modifiable=False), BlocTexte("p1", "Texte", 5)]
    message = construire_message_utilisateur(blocs_cv=blocs, texte_annonce="Annonce", contexte_academique="L3")
    assert '"modifiable": false' in message and '"longueur_max": 11' in message


def test_annonce_trop_courte():
    with pytest.raises(ErreurGeneration):
        valider_entrees("Data analyst", [BlocTexte("p1", "x", 1)])
