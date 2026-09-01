from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import requests

import dashboard_generator
import scraping_ibge_municipios as coletor

MUNICIPIOS_TESTE = {
    "Cedro": "2303808",
    "Aurora": "2301703",
}
INDICADORES_TESTE = {
    1: coletor.Indicador("Indicador A", "%", "Fonte A"),
    2: coletor.Indicador("Indicador B", "R$", "Fonte B"),
}


def _payload_completo() -> list[dict[str, object]]:
    return [
        {
            "localidade": "230380",
            "res": [
                {
                    "indicador": 1,
                    "res": {"2010": "10.5", "2022": "-"},
                    "notas": {"2010": None, "2022": "Não disponível"},
                },
                {
                    "indicador": 2,
                    "res": {"2021": "1000.00"},
                    "notas": {"2021": None},
                },
            ],
        },
        {
            "localidade": "230170",
            "res": [
                {
                    "indicador": 1,
                    "res": {"2010": "20.0"},
                    "notas": {"2010": None},
                },
                {
                    "indicador": 2,
                    "res": {"2021": "2000.00"},
                    "notas": {"2021": None},
                },
            ],
        },
    ]


class RespostaFalsa:
    def __init__(self, payload: object, url: str = "https://api.test/consulta"):
        self._payload = payload
        self.url = url

    def raise_for_status(self) -> None:
        pass

    def json(self) -> object:
        return self._payload


class SessaoFalsa:
    def __init__(self, resposta: RespostaFalsa):
        self.resposta = resposta
        self.chamadas: list[tuple[str, object]] = []

    def get(self, url: str, timeout: object) -> RespostaFalsa:
        self.chamadas.append((url, timeout))
        return self.resposta


def test_montar_url_agrupa_municipios_e_indicadores() -> None:
    url = coletor.montar_url(MUNICIPIOS_TESTE, INDICADORES_TESTE)

    assert "/1|2/resultados/2303808|2301703" in url
    assert url.endswith("?groupBy=localidade")


def test_normalizar_historico_preserva_periodos_notas_e_indisponibilidade() -> None:
    registros = coletor.normalizar_historico(
        _payload_completo(),
        "https://api.test/consulta",
        MUNICIPIOS_TESTE,
        INDICADORES_TESTE,
    )

    assert len(registros) == 5
    assert registros[0] == {
        "municipio": "Cedro",
        "codigo_ibge": "2303808",
        "indicador_id": 1,
        "indicador": "Indicador A",
        "valor": "10.5",
        "unidade": "%",
        "periodo": "2010",
        "disponivel": True,
        "nota": "",
        "fonte": "Fonte A",
        "url": "https://api.test/consulta",
    }
    indisponivel = registros[1]
    assert indisponivel["valor"] == "-"
    assert indisponivel["disponivel"] is False
    assert indisponivel["nota"] == "Não disponível"


def test_normalizar_historico_rejeita_municipio_ausente() -> None:
    with pytest.raises(coletor.RespostaAPIInvalida, match="Municípios ausentes"):
        coletor.normalizar_historico(
            _payload_completo()[:1],
            "https://api.test",
            MUNICIPIOS_TESTE,
            INDICADORES_TESTE,
        )


def test_normalizar_historico_rejeita_indicador_ausente() -> None:
    payload = _payload_completo()
    payload[1]["res"] = payload[1]["res"][:1]  # type: ignore[index]

    with pytest.raises(coletor.RespostaAPIInvalida, match="Indicadores ausentes"):
        coletor.normalizar_historico(
            payload,
            "https://api.test",
            MUNICIPIOS_TESTE,
            INDICADORES_TESTE,
        )


def test_consultar_api_usa_timeout_e_url_final() -> None:
    sessao = SessaoFalsa(RespostaFalsa(_payload_completo()))

    conteudo, url = coletor.consultar_api(
        sessao,  # type: ignore[arg-type]
        MUNICIPIOS_TESTE,
        INDICADORES_TESTE,
    )

    assert conteudo == _payload_completo()
    assert url == "https://api.test/consulta"
    assert sessao.chamadas[0][1] == coletor.TIMEOUT_API


def test_consultar_api_converte_erro_http_em_erro_de_dominio() -> None:
    class SessaoComFalha:
        def get(self, _url: str, timeout: object) -> object:
            raise requests.Timeout(f"timeout {timeout}")

    with pytest.raises(RuntimeError, match="Falha ao consultar"):
        coletor.consultar_api(
            SessaoComFalha(),  # type: ignore[arg-type]
            MUNICIPIOS_TESTE,
            INDICADORES_TESTE,
        )


def test_salvar_resultados_gera_json_e_csv_equivalentes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pasta_resultados = tmp_path / "resultados"
    caminho_dashboard = tmp_path / "dashboards" / "index.html"
    caminho_dashboard.parent.mkdir()
    caminho_dashboard.write_text(
        "<main>layout preservado</main><script>"
        f"{dashboard_generator.MARCADOR_INICIO}[]"
        f"{dashboard_generator.MARCADOR_FIM}</script>",
        encoding="utf-8",
    )
    monkeypatch.setattr(coletor, "PASTA_SAIDA", pasta_resultados)
    monkeypatch.setattr(coletor, "CAMINHO_DASHBOARD", caminho_dashboard)
    registros = coletor.normalizar_historico(
        _payload_completo(),
        "https://api.test",
        MUNICIPIOS_TESTE,
        INDICADORES_TESTE,
    )

    coletor.salvar_resultados(registros)

    arquivo_json = pasta_resultados / "municipios_ibge_historico.json"
    arquivo_csv = pasta_resultados / "municipios_ibge_historico.csv"
    assert json.loads(arquivo_json.read_text(encoding="utf-8")) == registros
    with arquivo_csv.open(encoding="utf-8-sig", newline="") as arquivo:
        linhas = list(csv.DictReader(arquivo))
    assert len(linhas) == len(registros)
    assert linhas[0]["municipio"] == "Cedro"
    assert linhas[0]["disponivel"] == "True"
    dashboard = caminho_dashboard.read_text(encoding="utf-8")
    assert "layout preservado" in dashboard
    assert '"municipio":"Cedro"' in dashboard


def test_dashboard_escapa_fechamento_de_script() -> None:
    registro = {
        "municipio": "Cidade </script><script>alert(1)</script>",
        "codigo_ibge": "0000000",
        "indicador_id": 1,
        "indicador": "Teste",
        "valor": "1",
        "unidade": "%",
        "periodo": "2025",
        "disponivel": True,
        "fonte": "Fonte",
    }
    template = (
        f"<script>{dashboard_generator.MARCADOR_INICIO}[]"
        f"{dashboard_generator.MARCADOR_FIM}</script>"
    )

    resultado = dashboard_generator.gerar_conteudo_dashboard(
        [registro], template
    )

    assert resultado.count("</script>") == 1
    assert "\\u003c/script>" in resultado


def test_template_invalido_preserva_resultados_anteriores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pasta_resultados = tmp_path / "resultados"
    pasta_resultados.mkdir()
    caminho_json = pasta_resultados / "municipios_ibge_historico.json"
    caminho_csv = pasta_resultados / "municipios_ibge_historico.csv"
    caminho_json.write_text("dados anteriores", encoding="utf-8")
    caminho_csv.write_text("csv anterior", encoding="utf-8")
    caminho_dashboard = tmp_path / "index.html"
    caminho_dashboard.write_text("sem marcadores", encoding="utf-8")
    monkeypatch.setattr(coletor, "PASTA_SAIDA", pasta_resultados)
    monkeypatch.setattr(coletor, "CAMINHO_DASHBOARD", caminho_dashboard)

    with pytest.raises(ValueError, match="marcadores"):
        coletor.salvar_resultados(
            coletor.normalizar_historico(
                _payload_completo(),
                "https://api.test",
                MUNICIPIOS_TESTE,
                INDICADORES_TESTE,
            )
        )

    assert caminho_json.read_text(encoding="utf-8") == "dados anteriores"
    assert caminho_csv.read_text(encoding="utf-8") == "csv anterior"


def test_main_nao_publica_quando_api_falha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def falhar(
        municipios: object, indicadores: object
    ) -> list[coletor.Registro]:
        raise RuntimeError("API indisponível")

    gravacoes: list[list[coletor.Registro]] = []
    monkeypatch.setattr(coletor, "coletar_historico", falhar)
    monkeypatch.setattr(coletor, "salvar_resultados", gravacoes.append)

    with pytest.raises(RuntimeError, match="API indisponível"):
        coletor.main([])  # type: ignore[arg-type]

    assert gravacoes == []


def test_carregar_config_parseia_municipios_e_indicadores(
    tmp_path: Path,
) -> None:
    arquivo = tmp_path / "config.json"
    arquivo.write_text(
        json.dumps(
            {
                "municipios": {"Cedro": "2303808"},
                "indicadores": [
                    {
                        "id": 60045,
                        "nome": "Escolarização 6 a 14 anos",
                        "unidade": "%",
                        "fonte": "IBGE — Censos Demográficos",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    municipios, indicadores = coletor.carregar_config(str(arquivo))

    assert municipios == {"Cedro": "2303808"}
    assert set(indicadores) == {60045}
    assert indicadores[60045].nome == "Escolarização 6 a 14 anos"
    assert indicadores[60045].unidade == "%"


def test_carregar_config_rejeita_municipios_com_tipo_invalido(
    tmp_path: Path,
) -> None:
    arquivo = tmp_path / "config.json"
    arquivo.write_text(
        json.dumps(
            {
                "municipios": {"Cedro": 2303808},
                "indicadores": [{"id": 1, "nome": "A", "unidade": "", "fonte": ""}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(TypeError, match="municipios"):
        coletor.carregar_config(str(arquivo))


def test_carregar_config_rejeita_indicador_sem_id(tmp_path: Path) -> None:
    arquivo = tmp_path / "config.json"
    arquivo.write_text(
        json.dumps({"municipios": {}, "indicadores": [{"nome": "A"}]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="id"):
        coletor.carregar_config(str(arquivo))


def test_carregar_config_rejeita_ausencia_de_indicadores(
    tmp_path: Path,
) -> None:
    arquivo = tmp_path / "config.json"
    arquivo.write_text(json.dumps({"municipios": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="Nenhum indicador"):
        coletor.carregar_config(str(arquivo))


def test_carregar_config_arquivo_ausente(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        coletor.carregar_config(str(tmp_path / "nao_existe.json"))


def test_resolver_config_usando_arquivo(tmp_path: Path) -> None:
    arquivo = tmp_path / "config.json"
    arquivo.write_text(
        json.dumps(
            {"municipios": {"Aurora": "2301703"}, "indicadores": [{"id": 1}]}
        ),
        encoding="utf-8",
    )

    municipios, indicadores = coletor._resolver_config(str(arquivo))
    assert municipios == {"Aurora": "2301703"}
    assert set(indicadores) == {1}


def test_resolver_config_usando_padroes() -> None:
    municipios, indicadores = coletor._resolver_config(None)
    assert municipios == coletor.MUNICIPIOS
    assert set(indicadores) == set(coletor.INDICADORES)


def test_main_com_versao_exibe_e_sai(capsys: pytest.CaptureFixture[str]) -> None:
    coletor.main(["--versao"])
    saida = capsys.readouterr().out
    assert f"scraping-ibge v{coletor.VERSION}" in saida


def test_parser_expoe_opcoes_cli() -> None:
    parser = coletor._criar_parser()
    acoes = {acao.dest for acao in parser._actions}
    assert {"config", "saida", "dashboard", "versao"} <= acoes


def test_salvar_resultados_dashboard_novo_usa_template_do_repositorio(
    tmp_path: Path,
) -> None:
    pasta_resultados = tmp_path / "resultados"
    template_dir = tmp_path / "template_dash"
    template_dir.mkdir()
    template = template_dir / "index.html"
    template.write_text(
        "<main>template</main><script>"
        f"{dashboard_generator.MARCADOR_INICIO}[]"
        f"{dashboard_generator.MARCADOR_FIM}</script>",
        encoding="utf-8",
    )
    destino = tmp_path / "dash_app" / "novo.html"
    registros = coletor.normalizar_historico(
        _payload_completo(),
        "https://api.test",
        MUNICIPIOS_TESTE,
        INDICADORES_TESTE,
    )

    coletor.salvar_resultados(
        registros,
        pasta_saida=pasta_resultados,
        caminho_dashboard=destino,
        template_dashboard=template,
    )

    assert destino.exists()
    conteudo = destino.read_text(encoding="utf-8")
    assert "template" in conteudo
    assert '"municipio":"Cedro"' in conteudo
