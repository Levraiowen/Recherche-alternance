"""Conversion via Word (simulée : Word n'existe pas sur les machines de test)."""

import sys
import threading
import types
from pathlib import Path

import pytest

import pdf_export


@pytest.fixture
def faux_word(monkeypatch):
    appels: list[str] = []

    def convert(source, destination):
        appels.append("conversion")
        if "panne" in source:
            raise RuntimeError("Word a planté")
        Path(destination).write_bytes(b"%PDF-1.7")

    monkeypatch.setitem(sys.modules, "pythoncom", types.SimpleNamespace(
        CoInitialize=lambda: appels.append("init COM"), CoUninitialize=lambda: appels.append("fin COM")))
    monkeypatch.setitem(sys.modules, "docx2pdf", types.SimpleNamespace(convert=convert))
    monkeypatch.setattr(pdf_export, "_word_disponible", lambda: True)
    monkeypatch.setattr(pdf_export, "_sous_windows", lambda: True)
    return appels


def test_word_initialise_com_dans_chaque_fil(faux_word, tmp_path: Path):
    # Streamlit exécute chaque affichage dans un nouveau fil : COM doit être
    # initialisé à chaque conversion, et Word jamais piloté par deux fils à la fois.
    fils = [threading.Thread(target=pdf_export._via_word, args=(tmp_path / "lettre.docx", tmp_path / f"{i}.pdf"))
            for i in range(3)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join()
    assert faux_word == ["init COM", "conversion", "fin COM"] * 3


def test_com_libere_meme_si_word_plante(faux_word, tmp_path: Path):
    with pytest.raises(RuntimeError):
        pdf_export._via_word(tmp_path / "panne.docx", tmp_path / "panne.pdf")
    assert faux_word == ["init COM", "conversion", "fin COM"]
    assert not pdf_export.VERROU_WORD.locked()
