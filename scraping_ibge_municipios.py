"""Coleta e exporta indicadores municipais exibidos pelo IBGE."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Mapping

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


MUNICIPIOS = {
    "Cedro": "https://www.ibge.gov.br/cidades-e-estados/ce/cedro.html",
    "Várzea Alegre": "https://www.ibge.gov.br/cidades-e-estados/ce/varzea-alegre.html",
    "Lavras da Mangabeira": (
        "https://www.ibge.gov.br/cidades-e-estados/ce/"
        "lavras-da-mangabeira.html"
    ),
    "Aurora": "https://www.ibge.gov.br/cidades-e-estados/ce/aurora.html",
}

INDICADORES_OBRIGATORIOS = frozenset(
    {
        "Prefeito",
        "Gentílico",
        "Área Territorial",
        "População no último censo",
        "Densidade demográfica",
        "População estimada",
        "Escolarização 6 a 14 anos",
        "IDHM Índice de desenvolvimento humano municipal",
        "Mortalidade infantil",
        "Total de receitas brutas realizadas",
        "Total de despesas brutas empenhadas",
        "PIB per capita",
    }
)

PASTA_SAIDA = Path("resultados_ibge")
CAMPOS_SAIDA = [
    "municipio",
    "indicador",
    "valor",
    "unidade",
    "periodo",
    "fonte",
    "url",
]


def texto(elemento: Tag | None) -> str:
    """Normaliza o texto visível de um elemento HTML."""
    if elemento is None:
        return ""
    return re.sub(r"\s+", " ", elemento.get_text(" ", strip=True)).strip()


def elemento_por_classe(container: Tag, termos: tuple[str, ...]) -> Tag | None:
    """Localiza um descendente cujo nome de classe contenha um dos termos."""
    return container.find(
        lambda tag: isinstance(tag, Tag)
        and any(
            termo in classe.lower()
            for classe in tag.get("class", [])
            for termo in termos
        )
    )


def _fontes_por_indicador(soup: BeautifulSoup) -> dict[str, str]:
    """Converte a tabela de fontes do IBGE em um mapa título -> fonte."""
    fontes: dict[str, str] = {}
    for celula in soup.select(".fontes-container td"):
        rotulo = celula.find("b")
        if rotulo is None:
            continue
        titulo_rotulo = texto(rotulo)
        titulo = titulo_rotulo.rstrip(":").strip()
        fonte = texto(celula)[len(titulo_rotulo) :].strip()
        if titulo and fonte:
            fontes[titulo] = fonte
    return fontes


def _separar_valor(
    valor_bruto: str, unidade_explicita: str = "", periodo_explicito: str = ""
) -> tuple[str, str, str]:
    """Separa valor, unidade e período sem converter a notação brasileira."""
    periodo_embutido = ""
    correspondencia = re.search(r"\[([^\]]+)\]\s*$", valor_bruto)
    if correspondencia:
        periodo_embutido = correspondencia.group(1).strip()
        valor_bruto = valor_bruto[: correspondencia.start()].strip()

    periodo = periodo_explicito.strip().strip("[]") or periodo_embutido
    unidade = unidade_explicita.strip()
    unidade_embutida = ""

    if valor_bruto.startswith("R$"):
        unidade_embutida = "R$"
        valor_bruto = valor_bruto[2:].strip()

    for candidata in (
        "óbitos por mil nascidos vivos",
        "hab/km²",
        "pessoas",
        "reais",
        "km²",
        "%",
        "R$",
    ):
        if valor_bruto.endswith(candidata):
            unidade_embutida = unidade_embutida or candidata
            valor_bruto = valor_bruto[: -len(candidata)].strip()
            break

    return valor_bruto, unidade or unidade_embutida, periodo


def extrair_indicadores(html: str) -> list[dict[str, str]]:
    """Extrai os cards e suas fontes do HTML renderizado pelo IBGE."""
    soup = BeautifulSoup(html, "html.parser")
    candidatos = soup.select(".indicador, [class*='indicador-card']")
    fontes = _fontes_por_indicador(soup)

    indicadores: list[dict[str, str]] = []
    vistos: set[tuple[str, str, str]] = set()

    for card in candidatos:
        titulo_elemento = card.select_one(".ind-label p") or elemento_por_classe(
            card, ("titulo", "title", "nome", "label")
        )
        valor_elemento = card.select_one(".ind-value") or elemento_por_classe(
            card, ("valor", "value", "numero", "number")
        )
        unidade_elemento = card.select_one(
            ".indicador-unidade"
        ) or elemento_por_classe(card, ("unidade", "unit"))
        periodo_elemento = (
            valor_elemento.select_one("small") if valor_elemento else None
        ) or elemento_por_classe(card, ("periodo", "ano", "year"))
        fonte_elemento = elemento_por_classe(card, ("fonte", "source"))

        titulo = texto(titulo_elemento)
        valor_bruto = texto(valor_elemento)
        unidade_explicita = texto(unidade_elemento)
        periodo_explicito = texto(periodo_elemento)
        fonte = texto(fonte_elemento) or fontes.get(titulo, "")

        if not titulo or not valor_bruto or titulo == valor_bruto:
            continue

        valor, unidade, periodo = _separar_valor(
            valor_bruto, unidade_explicita, periodo_explicito
        )
        if not valor:
            continue

        chave = (titulo, valor, periodo)
        if chave in vistos:
            continue
        vistos.add(chave)

        indicadores.append(
            {
                "indicador": titulo,
                "valor": valor,
                "unidade": unidade,
                "periodo": periodo,
                "fonte": fonte,
            }
        )

    return indicadores


def carregar_pagina(page: Page, url: str) -> str:
    """Abre a página e espera o conjunto completo de indicadores."""
    ultimo_erro = "conteúdo esperado não carregado"

    for tentativa in range(1, 3):
        try:
            resposta = page.goto(
                url, wait_until="domcontentloaded", timeout=90_000
            )
            if resposta is not None and resposta.status >= 400:
                raise RuntimeError(f"HTTP {resposta.status}")

            for rotulo in ("Aceitar todos", "Aceitar", "Concordar"):
                botao = page.get_by_role(
                    "button", name=re.compile(rotulo, re.I)
                )
                if botao.count():
                    try:
                        botao.first.click(timeout=2_000)
                    except PlaywrightTimeoutError:
                        pass
                    break

            page.locator(
                ".indicador .ind-label", has_text="PIB per capita"
            ).first.wait_for(timeout=30_000)
            page.wait_for_timeout(500)
            return page.content()
        except (PlaywrightTimeoutError, RuntimeError) as erro:
            ultimo_erro = f"{erro}; título recebido: {page.title()!r}"
            if tentativa < 2:
                page.wait_for_timeout(1_000)

    raise RuntimeError(
        f"Não foi possível carregar os indicadores de {url}: {ultimo_erro}"
    )


def coletar_municipios(
    page: Page,
    municipios: Mapping[str, str] = MUNICIPIOS,
    indicadores_obrigatorios: frozenset[str] | None = None,
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Coleta todos os municípios e devolve registros e falhas separadamente."""
    registros: list[dict[str, str]] = []
    falhas: dict[str, str] = {}

    for municipio, url in municipios.items():
        print(f"Coletando {municipio}...")
        try:
            indicadores = extrair_indicadores(carregar_pagina(page, url))
            if not indicadores:
                raise RuntimeError("nenhum indicador encontrado")

            if indicadores_obrigatorios:
                encontrados = {item["indicador"] for item in indicadores}
                ausentes = indicadores_obrigatorios - encontrados
                if ausentes:
                    raise RuntimeError(
                        "indicadores obrigatórios ausentes: "
                        + ", ".join(sorted(ausentes))
                    )

            registros.extend(
                {"municipio": municipio, **indicador, "url": url}
                for indicador in indicadores
            )
            print(f"  {len(indicadores)} indicadores encontrados.")
        except Exception as erro:
            falhas[municipio] = str(erro)
            print(f"  Erro ao coletar {municipio}: {erro}")

    return registros, falhas


def _escrever_atomico(caminho: Path, conteudo: str, encoding: str) -> None:
    """Grava em arquivo temporário e publica com substituição atômica."""
    temporario: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            newline="",
            dir=caminho.parent,
            prefix=f".{caminho.name}.",
            delete=False,
        ) as arquivo:
            temporario = Path(arquivo.name)
            arquivo.write(conteudo)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        temporario.replace(caminho)
    except Exception:
        if temporario is not None:
            temporario.unlink(missing_ok=True)
        raise


def salvar_resultados(registros: list[dict[str, str]]) -> None:
    """Publica JSON e CSV somente depois de ambos estarem serializados."""
    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    caminho_json = PASTA_SAIDA / "municipios_ibge.json"
    caminho_csv = PASTA_SAIDA / "municipios_ibge.csv"

    conteudo_json = json.dumps(registros, ensure_ascii=False, indent=2)
    buffer_csv = io.StringIO(newline="")
    escritor = csv.DictWriter(buffer_csv, fieldnames=CAMPOS_SAIDA)
    escritor.writeheader()
    escritor.writerows(registros)

    _escrever_atomico(caminho_json, conteudo_json, "utf-8")
    _escrever_atomico(caminho_csv, buffer_csv.getvalue(), "utf-8-sig")

    print(f"JSON salvo em: {caminho_json.resolve()}")
    print(f"CSV salvo em:  {caminho_csv.resolve()}")


def main() -> None:
    with sync_playwright() as playwright:
        navegador = playwright.chromium.launch(headless=True)
        contexto = navegador.new_context(
            locale="pt-BR",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        try:
            registros, falhas = coletar_municipios(
                contexto.new_page(),
                MUNICIPIOS,
                INDICADORES_OBRIGATORIOS,
            )
        finally:
            contexto.close()
            navegador.close()

    if falhas:
        detalhes = "; ".join(
            f"{municipio}: {erro}" for municipio, erro in falhas.items()
        )
        raise RuntimeError(
            "Coleta incompleta; os arquivos anteriores foram preservados. "
            + detalhes
        )
    if not registros:
        raise RuntimeError("Nenhum dado foi coletado; nada foi publicado.")

    salvar_resultados(registros)


if __name__ == "__main__":
    main()
