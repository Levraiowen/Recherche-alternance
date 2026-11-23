"""Bascule entre modèles Gemini (sans appel réseau : client factice)."""

import pytest
from google.genai import errors as genai_errors

import ia_gemini


class ClientFactice:
    def __init__(self, reponses):
        self.reponses = reponses  # modèle -> exception à lever, ou valeur à renvoyer
        self.appels = []
        self.models = self

    def generate_content(self, *, model, contents, config):
        self.appels.append(model)
        resultat = self.reponses[model]
        if isinstance(resultat, Exception):
            raise resultat
        return resultat


def _erreur(classe, code, statut):
    return classe(code, {"error": {"code": code, "status": statut, "message": statut}})


@pytest.fixture(autouse=True)
def sans_attente(monkeypatch):
    monkeypatch.setattr(ia_gemini.time, "sleep", lambda _s: None)


def test_surcharge_503_bascule_sur_le_modele_suivant():
    surcharge = _erreur(genai_errors.ServerError, 503, "UNAVAILABLE")
    client = ClientFactice({"a": surcharge, "b": "ok"})
    reponse, modele = ia_gemini._generer_avec_secours(client, modeles=["a", "b"], contenu="x", config={})
    assert (reponse, modele) == ("ok", "b")
    assert client.appels == ["a", "a", "b"]  # une retentative sur « a », puis bascule


def test_quota_bascule_et_cle_invalide_non():
    quota = _erreur(genai_errors.ClientError, 429, "RESOURCE_EXHAUSTED")
    client = ClientFactice({"a": quota, "b": "ok"})
    assert ia_gemini._generer_avec_secours(client, modeles=["a", "b"], contenu="x", config={})[1] == "b"

    cle = _erreur(genai_errors.ClientError, 403, "PERMISSION_DENIED")
    client = ClientFactice({"a": cle, "b": "ok"})
    with pytest.raises(genai_errors.ClientError):
        ia_gemini._generer_avec_secours(client, modeles=["a", "b"], contenu="x", config={})
    assert client.appels == ["a"]


def test_tous_surcharges_message_clair():
    surcharge = _erreur(genai_errors.ServerError, 503, "UNAVAILABLE")
    client = ClientFactice({"a": surcharge, "b": surcharge})
    with pytest.raises(genai_errors.ServerError) as info:
        ia_gemini._generer_avec_secours(client, modeles=["a", "b"], contenu="x", config={})
    message = ia_gemini._message_erreur(info.value, ["a", "b"])
    assert "2 modèle(s)" in message and "a, b" in message
