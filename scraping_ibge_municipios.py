"""Coleta séries históricas municipais na API oficial do IBGE."""

from __future__ import annotations

import argparse
import csv
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from dashboard_generator import escrever_atomico, gerar_conteudo_dashboard

VERSION = "1.1.0"
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


def salvar_resultados(
    registros: list[Registro],
    pasta_saida: Path | None = None,
    caminho_dashboard: Path | None = None,
    template_dashboard: Path | None = None,
) -> None:
    """Publica as séries históricas e atualiza o dashboard autônomo."""
    pasta_saida = pasta_saida or PASTA_SAIDA
    caminho_dashboard = caminho_dashboard or CAMINHO_DASHBOARD
    caminho_json = pasta_saida / "municipios_ibge_historico.json"
    caminho_csv = pasta_saida / "municipios_ibge_historico.csv"

    conteudo_json = json.dumps(registros, ensure_ascii=False, indent=2)
    buffer_csv = io.StringIO(newline="")
    escritor = csv.DictWriter(buffer_csv, fieldnames=CAMPOS_SAIDA)
    escritor.writeheader()
    escritor.writerows(registros)

    # O template que contém os marcadores é sempre o dashboard embutido no
    # repositório. O parâmetro ``template_dashboard`` permite apontar para um
    # arquivo alternativo; quando ausente, usa-se o próprio ``caminho_dashboard``
    # (que, na execução padrão, é o mesmo arquivo). Assim, um ``--dashboard``
    # apontando para um caminho ainda inexistente não impede a geração.
    origem_template = template_dashboard or caminho_dashboard
    conteudo_template = origem_template.read_text(encoding="utf-8")
    conteudo_dashboard = gerar_conteudo_dashboard(
        registros, conteudo_template
    )

    pasta_saida.mkdir(parents=True, exist_ok=True)
    caminho_dashboard.parent.mkdir(parents=True, exist_ok=True)
    escrever_atomico(caminho_json, conteudo_json, "utf-8")
    escrever_atomico(caminho_csv, buffer_csv.getvalue(), "utf-8-sig")
    escrever_atomico(caminho_dashboard, conteudo_dashboard, "utf-8")
    print(f"JSON salvo em: {caminho_json.resolve()}")
    print(f"CSV salvo em:  {caminho_csv.resolve()}")
    print(f"Dashboard salvo em: {caminho_dashboard.resolve()}")


def carregar_config(caminho: str) -> tuple[dict[str, str], dict[int, Indicador]]:
    """Carrega municípios e indicadores a partir de um arquivo JSON.

    Formato esperado:

    .. code-block:: json

        {
          "municipios": {"Cedro": "2303808"},
          "indicadores": [
            {"id": 60045, "nome": "Escolarização 6 a 14 anos",
             "unidade": "%", "fonte": "IBGE — Censos Demográficos"}
          ]
        }

    Retorna uma tupla ``(municipios, indicadores)`` pronta para as funções
    de consulta. Um arquivo ausente levanta ``FileNotFoundError``; conteúdo de
    tipo inesperado levanta ``TypeError``; e campos ausentes ou inválidos
    levantam ``ValueError``.
    """
    dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    if not isinstance(dados, dict):
        raise TypeError("O arquivo de configuração precisa ser um objeto JSON.")

    municipios = dados.get("municipios", {})
    if not isinstance(municipios, dict) or not all(
        isinstance(v, str) for v in municipios.values()
    ):
        raise TypeError(
            "'municipios' deve ser um objeto com códigos IBGE como strings."
        )

    indicadores: dict[int, Indicador] = {}
    for item in dados.get("indicadores", []):
        if not isinstance(item, dict):
            raise TypeError("Cada indicador deve ser um objeto.")
        try:
            identificador = int(item["id"])
        except KeyError as erro:
            raise ValueError("Cada indicador precisa de um 'id' inteiro.") from erro
        except (TypeError, ValueError) as erro:
            raise TypeError(
                "O 'id' de cada indicador precisa ser um inteiro."
            ) from erro
        indicadores[identificador] = Indicador(
            nome=str(item.get("nome", "Indicador")),
            unidade=str(item.get("unidade", "")),
            fonte=str(item.get("fonte", "")),
        )
    if not indicadores:
        raise ValueError("Nenhum indicador foi informado no arquivo.")

    return dict(municipios), indicadores


def _resolver_config(
    caminho: str | None,
) -> tuple[dict[str, str], dict[int, Indicador]]:
    """Devolve a configuração efetiva, seja do arquivo ou dos padrões embutidos."""
    if caminho:
        return carregar_config(caminho)
    return dict(MUNICIPIOS), dict(INDICADORES)


def _criar_parser() -> argparse.ArgumentParser:
    """Cria o analisador de argumentos da linha de comando."""
    parser = argparse.ArgumentParser(
        prog="scraping_ibge_municipios",
        description=(
            "Coleta séries históricas municipais na API oficial do IBGE "
            "e publica os resultados em CSV, JSON e um dashboard HTML."
        ),
    )
    parser.add_argument(
        "--config",
        metavar="ARQUIVO",
        help=(
            "Arquivo JSON opcional com municípios e indicadores personalizados. "
            "Quando ausente, usa os padrões embutidos no módulo."
        ),
    )
    parser.add_argument(
        "--saida",
        metavar="DIR",
        help="Diretório de saída dos resultados (padrão: resultados_ibge).",
    )
    parser.add_argument(
        "--dashboard",
        metavar="CAMINHO",
        help="Caminho do arquivo do dashboard (padrão: dashboards/index.html).",
    )
    parser.add_argument(
        "--versao",
        action="store_true",
        help="Exibe a versão e encerra a execução.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    argumentos = _criar_parser().parse_args(argv)

    if argumentos.versao:
        print(f"scraping-ibge v{VERSION}")
        return

    municipios, indicadores = _resolver_config(argumentos.config)
    pasta_saida = Path(argumentos.saida or PASTA_SAIDA)
    caminho_dashboard = Path(argumentos.dashboard or CAMINHO_DASHBOARD)
    # Um dashboard próprio recebe o template do arquivo embutido no repositório,
    # para que a geração funcione mesmo quando o caminho de destino é novo.
    template = (
        CAMINHO_DASHBOARD if argumentos.dashboard else None
    )

    print("Consultando séries históricas na API do IBGE...")
    registros = coletar_historico(
        municipios=municipios, indicadores=indicadores
    )
    if not registros:
        raise RuntimeError(
            "Nenhuma série histórica foi retornada; nada foi publicado."
        )

    for municipio in municipios:
        quantidade = sum(item["municipio"] == municipio for item in registros)
        print(f"  {municipio}: {quantidade} observações históricas.")
    salvar_resultados(registros, pasta_saida, caminho_dashboard, template)


if __name__ == "__main__":
    main()
