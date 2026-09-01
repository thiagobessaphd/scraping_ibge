from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import requests

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
    monkeypatch.setattr(coletor, "PASTA_SAIDA", tmp_path)
    registros = coletor.normalizar_historico(
        _payload_completo(),
        "https://api.test",
        MUNICIPIOS_TESTE,
        INDICADORES_TESTE,
    )

    coletor.salvar_resultados(registros)

    arquivo_json = tmp_path / "municipios_ibge_historico.json"
    arquivo_csv = tmp_path / "municipios_ibge_historico.csv"
    assert json.loads(arquivo_json.read_text(encoding="utf-8")) == registros
    with arquivo_csv.open(encoding="utf-8-sig", newline="") as arquivo:
        linhas = list(csv.DictReader(arquivo))
    assert len(linhas) == len(registros)
    assert linhas[0]["municipio"] == "Cedro"
    assert linhas[0]["disponivel"] == "True"


def test_main_nao_publica_quando_api_falha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def falhar() -> list[coletor.Registro]:
        raise RuntimeError("API indisponível")

    gravacoes: list[list[coletor.Registro]] = []
    monkeypatch.setattr(coletor, "coletar_historico", falhar)
    monkeypatch.setattr(coletor, "salvar_resultados", gravacoes.append)

    with pytest.raises(RuntimeError, match="API indisponível"):
        coletor.main()

    assert gravacoes == []
