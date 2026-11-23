import json

import pytest

from cv_editor import BlocTexte
from ia_commun import (
    SYSTEME,
    ErreurGeneration,
    construire_message_utilisateur,
    construire_resultat,
    detecter_langue,
    extraire_json,
    schema_candidature,
    systeme_candidature,
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


ANNONCE_EN = ("We are looking for a Data Analyst apprentice to join our Customer Insights team in Paris. "
              "You will build dashboards with Power BI, work with SQL and Python, and present your findings "
              "to the business teams. What we offer: a 12-month work-study contract and a friendly team.")
ANNONCE_FR = ("Nous recherchons un alternant Data Analyst pour rejoindre notre équipe Customer Insights. Vous "
              "construirez des dashboards Power BI, travaillerez avec SQL et Python et présenterez vos analyses "
              "aux équipes métier. Le poste est basé à Paris, avec un rythme de 3 semaines en entreprise.")


def test_detection_de_la_langue_de_l_annonce():
    assert detecter_langue(ANNONCE_EN) == "en"
    assert detecter_langue(ANNONCE_FR) == "fr"  # les termes techniques anglais ne font pas basculer
    assert detecter_langue("") == "fr"


def test_consignes_selon_la_langue():
    anglais = systeme_candidature("en")
    assert "ANGLAIS" in anglais and "Dear Hiring Manager" in anglais and "française classique" not in anglais
    assert "française classique" in SYSTEME and "{" not in SYSTEME
    exemple = schema_candidature("en")["properties"]["lettre"]["properties"]["formule_appel"]["description"]
    assert "Dear Hiring Manager" in exemple
    message = construire_message_utilisateur(blocs_cv=[], texte_annonce=ANNONCE_EN, contexte_academique="",
                                             langue="en")
    assert "ANGLAIS" in message
    resultat = construire_resultat(json.loads(json.dumps(DONNEES)), langue="en")
    assert resultat.langue == "en" and resultat.formule_politesse == "Yours sincerely,"
