"""Coleta séries históricas municipais na API oficial do IBGE."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from dashboard_generator import gerar_conteudo_dashboard


API_BASE = "https://servicodados.ibge.gov.br/api/v1/pesquisas/indicadores"
TIMEOUT_API = (10, 60)

# Os códigos são os identificadores oficiais de sete dígitos dos municípios.
MUNICIPIOS: dict[str, str] = {
    "Cedro": "2303808",
    "Várzea Alegre": "2314003",
    "Lavras da Mangabeira": "2307502",
    "Aurora": "2301703",
}


@dataclass(frozen=True)
class Indicador:
    nome: str
    unidade: str
    fonte: str


INDICADORES: dict[int, Indicador] = {
    60045: Indicador(
        "Escolarização 6 a 14 anos",
        "%",
        "IBGE — Censos Demográficos",
    ),
    329756: Indicador(
        "IDHM Índice de desenvolvimento humano municipal",
        "índice",
        "Programa das Nações Unidas para o Desenvolvimento — PNUD",
    ),
    30279: Indicador(
        "Mortalidade infantil",
        "óbitos por mil nascidos vivos",
        "Ministério da Saúde — DATASUS",
    ),
    28141: Indicador(
        "Total de receitas brutas realizadas",
        "R$",
        "Siconfi — Secretaria do Tesouro Nacional",
    ),
    29749: Indicador(
        "Total de despesas brutas empenhadas",
        "R$",
        "Siconfi — Secretaria do Tesouro Nacional",
    ),
    47001: Indicador(
        "PIB per capita",
        "R$",
        "IBGE — Produto Interno Bruto dos Municípios",
    ),
}

SIMBOLOS_INDISPONIVEIS = frozenset({"", "-", "..", "...", "X"})
PASTA_SAIDA = Path("resultados_ibge")
CAMINHO_DASHBOARD = Path("dashboards/index.html")
CAMPOS_SAIDA = [
    "municipio",
    "codigo_ibge",
    "indicador_id",
    "indicador",
    "valor",
    "unidade",
    "periodo",
    "disponivel",
    "nota",
    "fonte",
    "url",
]

Registro = dict[str, str | int | bool]


class RespostaAPIInvalida(RuntimeError):
    """Indica que a API respondeu sem o conjunto completo esperado."""


def montar_url(
    municipios: Mapping[str, str] = MUNICIPIOS,
    indicadores: Mapping[int, Indicador] = INDICADORES,
) -> str:
    """Monta uma única consulta em lote para municípios e indicadores."""
    ids_indicadores = "|".join(str(codigo) for codigo in indicadores)
    ids_municipios = "|".join(municipios.values())
    return (
        f"{API_BASE}/{ids_indicadores}/resultados/{ids_municipios}"
        "?groupBy=localidade"
    )


def criar_sessao() -> requests.Session:
    """Cria uma sessão HTTP com tentativas para erros transitórios."""
    repeticao = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adaptador = HTTPAdapter(max_retries=repeticao)
    sessao = requests.Session()
    sessao.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": "scraping-ibge-historico/1.0",
        }
    )
    sessao.mount("https://", adaptador)
    return sessao


def consultar_api(
    sessao: requests.Session | None = None,
    municipios: Mapping[str, str] = MUNICIPIOS,
    indicadores: Mapping[int, Indicador] = INDICADORES,
) -> tuple[list[object], str]:
    """Consulta a API e devolve o JSON bruto e a URL efetivamente utilizada."""
    sessao_propria = sessao is None
    cliente = sessao or criar_sessao()
    try:
        resposta = cliente.get(
            montar_url(municipios, indicadores), timeout=TIMEOUT_API
        )
        resposta.raise_for_status()
        conteudo = resposta.json()
        if not isinstance(conteudo, list):
            raise RespostaAPIInvalida("A resposta da API não é uma lista.")
        return conteudo, resposta.url
    except requests.RequestException as erro:
        raise RuntimeError(f"Falha ao consultar a API do IBGE: {erro}") from erro
    finally:
        if sessao_propria:
            cliente.close()


def _codigo_completo(
    codigo_api: str, municipios: Mapping[str, str]
) -> tuple[str, str] | None:
    """Relaciona o código de seis dígitos da resposta ao código oficial."""
    for nome, codigo in municipios.items():
        if codigo[:-1] == codigo_api:
            return nome, codigo
    return None


def normalizar_historico(
    conteudo: Sequence[object],
    url: str,
    municipios: Mapping[str, str] = MUNICIPIOS,
    indicadores: Mapping[int, Indicador] = INDICADORES,
) -> list[Registro]:
    """Converte a resposta agrupada da API em registros históricos tabulares."""
    registros: list[Registro] = []
    localidades_encontradas: set[str] = set()
    indicadores_encontrados: dict[str, set[int]] = {
        codigo: set() for codigo in municipios.values()
    }

    for bloco in conteudo:
        if not isinstance(bloco, dict):
            raise RespostaAPIInvalida("Bloco de localidade em formato inválido.")

        localidade = _codigo_completo(str(bloco.get("localidade", "")), municipios)
        if localidade is None:
            continue
        municipio, codigo_ibge = localidade
        localidades_encontradas.add(codigo_ibge)

        respostas = bloco.get("res")
        if not isinstance(respostas, list):
            raise RespostaAPIInvalida(
                f"Séries ausentes para o município {municipio}."
            )

        for serie in respostas:
            if not isinstance(serie, dict):
                continue
            try:
                indicador_id = int(serie.get("indicador", ""))
            except (TypeError, ValueError):
                continue
            metadados = indicadores.get(indicador_id)
            if metadados is None:
                continue

            valores = serie.get("res")
            notas = serie.get("notas") or {}
            if not isinstance(valores, dict) or not isinstance(notas, dict):
                raise RespostaAPIInvalida(
                    f"Série {indicador_id} inválida para {municipio}."
                )
            indicadores_encontrados[codigo_ibge].add(indicador_id)

            periodos = sorted(
                valores, key=lambda item: (len(str(item)), str(item))
            )
            for periodo in periodos:
                valor_bruto = valores[periodo]
                valor = "" if valor_bruto is None else str(valor_bruto).strip()
                nota_bruta = notas.get(periodo)
                registros.append(
                    {
                        "municipio": municipio,
                        "codigo_ibge": codigo_ibge,
                        "indicador_id": indicador_id,
                        "indicador": metadados.nome,
                        "valor": valor,
                        "unidade": metadados.unidade,
                        "periodo": str(periodo),
                        "disponivel": valor not in SIMBOLOS_INDISPONIVEIS,
                        "nota": "" if nota_bruta is None else str(nota_bruta),
                        "fonte": metadados.fonte,
                        "url": url,
                    }
                )

    codigos_esperados = set(municipios.values())
    if localidades_encontradas != codigos_esperados:
        ausentes = codigos_esperados - localidades_encontradas
        raise RespostaAPIInvalida(
            "Municípios ausentes na resposta: " + ", ".join(sorted(ausentes))
        )

    ids_esperados = set(indicadores)
    for municipio, codigo in municipios.items():
        ausentes = ids_esperados - indicadores_encontrados[codigo]
        if ausentes:
            raise RespostaAPIInvalida(
                f"Indicadores ausentes para {municipio}: "
                + ", ".join(str(item) for item in sorted(ausentes))
            )

    ordem_municipios = {
        codigo: indice for indice, codigo in enumerate(municipios.values())
    }
    ordem_indicadores = {
        codigo: indice for indice, codigo in enumerate(indicadores)
    }
    registros.sort(
        key=lambda item: (
            ordem_municipios[str(item["codigo_ibge"])],
            ordem_indicadores[int(item["indicador_id"])],
            str(item["periodo"]),
        )
    )
    return registros


def coletar_historico(
    sessao: requests.Session | None = None,
    municipios: Mapping[str, str] = MUNICIPIOS,
    indicadores: Mapping[int, Indicador] = INDICADORES,
) -> list[Registro]:
    """Consulta e valida todas as séries históricas configuradas."""
    conteudo, url = consultar_api(sessao, municipios, indicadores)
    return normalizar_historico(conteudo, url, municipios, indicadores)


def _escrever_atomico(caminho: Path, conteudo: str, encoding: str) -> None:
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


def salvar_resultados(registros: list[Registro]) -> None:
    """Publica as séries históricas e atualiza o dashboard autônomo."""
    caminho_json = PASTA_SAIDA / "municipios_ibge_historico.json"
    caminho_csv = PASTA_SAIDA / "municipios_ibge_historico.csv"

    conteudo_json = json.dumps(registros, ensure_ascii=False, indent=2)
    buffer_csv = io.StringIO(newline="")
    escritor = csv.DictWriter(buffer_csv, fieldnames=CAMPOS_SAIDA)
    escritor.writeheader()
    escritor.writerows(registros)

    # O dashboard é validado antes da publicação dos dados. Assim, um template
    # corrompido não substitui arquivos de resultados que ainda estejam válidos.
    template_dashboard = CAMINHO_DASHBOARD.read_text(encoding="utf-8")
    conteudo_dashboard = gerar_conteudo_dashboard(
        registros, template_dashboard
    )

    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    CAMINHO_DASHBOARD.parent.mkdir(parents=True, exist_ok=True)
    _escrever_atomico(caminho_json, conteudo_json, "utf-8")
    _escrever_atomico(caminho_csv, buffer_csv.getvalue(), "utf-8-sig")
    _escrever_atomico(CAMINHO_DASHBOARD, conteudo_dashboard, "utf-8")
    print(f"JSON salvo em: {caminho_json.resolve()}")
    print(f"CSV salvo em:  {caminho_csv.resolve()}")
    print(f"Dashboard salvo em: {CAMINHO_DASHBOARD.resolve()}")


def main() -> None:
    print("Consultando séries históricas na API do IBGE...")
    registros = coletar_historico()
    if not registros:
        raise RuntimeError(
            "Nenhuma série histórica foi retornada; nada foi publicado."
        )

    for municipio in MUNICIPIOS:
        quantidade = sum(item["municipio"] == municipio for item in registros)
        print(f"  {municipio}: {quantidade} observações históricas.")
    salvar_resultados(registros)


if __name__ == "__main__":
    main()
