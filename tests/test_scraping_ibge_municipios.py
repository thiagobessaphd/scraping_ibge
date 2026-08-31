from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

import scraping_ibge_municipios as scraper


def _tag(html: str):
    return BeautifulSoup(html, "html.parser").find()


def _card(
    titulo: str,
    valor: str,
    *,
    unidade: str = "",
    periodo: str = "",
    fonte: str = "",
) -> str:
    return f"""
    <article class="indicador">
      <div class="indicador__titulo">{titulo}</div>
      <div class="indicador__valor">{valor}</div>
      <div class="indicador__unidade">{unidade}</div>
      <div class="indicador__periodo">{periodo}</div>
      <div class="indicador__fonte">{fonte}</div>
    </article>
    """


def test_texto_normaliza_espacos_inclusive_nbsp() -> None:
    elemento = _tag("<span>  Índice\n de\t desenvolvimento\xa0 humano  </span>")

    assert scraper.texto(elemento) == "Índice de desenvolvimento humano"
    assert scraper.texto(None) == ""


def test_extrair_indicadores_ignora_cards_incompletos() -> None:
    html = (
        _card("PIB per capita", "R$ 27.500,10 [2023]")
        + _card("", "123")
        + _card("Escolarização", "")
        + _card("Mesmo conteúdo", "Mesmo conteúdo")
    )

    indicadores = scraper.extrair_indicadores(html)

    assert len(indicadores) == 1
    assert indicadores[0]["indicador"] == "PIB per capita"


def test_extrair_indicadores_separa_valor_unidade_e_periodo_embutidos() -> None:
    indicadores = scraper.extrair_indicadores(
        _card("População no último censo", "22.344 pessoas [2022]")
    )

    assert indicadores == [
        {
            "indicador": "População no último censo",
            "valor": "22.344",
            "unidade": "pessoas",
            "periodo": "2022",
            "fonte": "",
        }
    ]


def test_campos_explicitos_prevalecem_sobre_metadados_embutidos() -> None:
    indicadores = scraper.extrair_indicadores(
        _card(
            "Escolarização 6 a 14 anos",
            "97,5 % [2010]",
            unidade="percentual",
            periodo="Censo 2022",
            fonte="IBGE",
        )
    )

    assert indicadores[0] == {
        "indicador": "Escolarização 6 a 14 anos",
        "valor": "97,5",
        "unidade": "percentual",
        "periodo": "Censo 2022",
        "fonte": "IBGE",
    }


def test_deduplicacao_considera_periodo() -> None:
    html = (
        _card("PIB per capita", "20.000 reais", periodo="2022")
        + _card("PIB per capita", "20.000 reais", periodo="2023")
        + _card("PIB per capita", "20.000 reais", periodo="2023")
    )

    indicadores = scraper.extrair_indicadores(html)

    assert [(item["valor"], item["periodo"]) for item in indicadores] == [
        ("20.000", "2022"),
        ("20.000", "2023"),
    ]


@pytest.mark.parametrize(
    "titulo",
    [
        "Escolarização",
        "IDHM Índice de desenvolvimento humano municipal",
        "Mortalidade infantil",
        "Total de receitas brutas realizadas",
        "Total de despesas brutas empenhadas",
        "PIB per capita",
    ],
)
def test_extrai_indicadores_adicionais(titulo: str) -> None:
    indicadores = scraper.extrair_indicadores(
        _card(titulo, "123,45", unidade="unidade", periodo="2023")
    )

    assert indicadores[0]["indicador"] == titulo


def test_salvar_resultados_gera_json_e_csv_equivalentes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pasta_saida = tmp_path / "resultados"
    monkeypatch.setattr(scraper, "PASTA_SAIDA", pasta_saida)
    registros = [
        {
            "municipio": "Várzea Alegre",
            "indicador": "PIB per capita",
            "valor": "27.500,10",
            "unidade": "R$",
            "periodo": "2023",
            "fonte": "IBGE",
            "url": "https://example.test/varzea-alegre",
        }
    ]

    scraper.salvar_resultados(registros)

    arquivo_json = pasta_saida / "municipios_ibge.json"
    arquivo_csv = pasta_saida / "municipios_ibge.csv"
    assert json.loads(arquivo_json.read_text(encoding="utf-8")) == registros
    with arquivo_csv.open(encoding="utf-8-sig", newline="") as arquivo:
        assert list(csv.DictReader(arquivo)) == registros


def test_coletar_municipios_reporta_falhas_sem_descartar_sucessos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    municipios = {
        "Município OK": "https://example.test/ok",
        "Município com falha": "https://example.test/falha",
    }

    def carregar(_page, url: str) -> str:
        if url.endswith("/falha"):
            raise RuntimeError("serviço indisponível")
        return _card("PIB per capita", "123 reais [2023]")

    monkeypatch.setattr(scraper, "carregar_pagina", carregar)

    registros, falhas = scraper.coletar_municipios(object(), municipios)

    assert len(registros) == 1
    assert registros[0]["municipio"] == "Município OK"
    assert registros[0]["url"] == "https://example.test/ok"
    assert falhas.keys() == {"Município com falha"}
    assert "indisponível" in falhas["Município com falha"]


class _FakeBrowser:
    def new_context(self, **_kwargs):
        return self

    def new_page(self):
        return SimpleNamespace()

    def close(self) -> None:
        pass


class _FakePlaywright:
    def __init__(self) -> None:
        self.chromium = self

    def launch(self, **_kwargs):
        return _FakeBrowser()


class _FakePlaywrightContext:
    def __enter__(self):
        return _FakePlaywright()

    def __exit__(self, *_args) -> None:
        pass


def test_falha_parcial_nao_publica_resultados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    municipios = {
        "Município OK": "https://example.test/ok",
        "Município com falha": "https://example.test/falha",
    }
    monkeypatch.setattr(scraper, "MUNICIPIOS", municipios)
    monkeypatch.setattr(
        scraper, "sync_playwright", lambda: _FakePlaywrightContext()
    )

    def carregar(_page, url: str) -> str:
        if url.endswith("/falha"):
            raise RuntimeError("indisponível")
        return _card("PIB per capita", "123 reais [2023]")

    monkeypatch.setattr(scraper, "carregar_pagina", carregar)
    gravacoes: list[list[dict[str, str]]] = []
    monkeypatch.setattr(scraper, "salvar_resultados", gravacoes.append)

    with pytest.raises(RuntimeError, match="falha|incompleta|parcial"):
        scraper.main()

    assert gravacoes == []
