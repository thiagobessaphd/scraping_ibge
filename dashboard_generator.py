"""Gera o dashboard HTML autônomo a partir das séries históricas coletadas."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


MARCADOR_INICIO = "/* DASHBOARD_DATA_START */"
MARCADOR_FIM = "/* DASHBOARD_DATA_END */"
ARQUIVO_DADOS = Path("resultados_ibge/municipios_ibge_historico.json")
ARQUIVO_DASHBOARD = Path("dashboards/index.html")
CAMPOS_OBRIGATORIOS = frozenset(
    {
        "municipio",
        "codigo_ibge",
        "indicador_id",
        "indicador",
        "valor",
        "unidade",
        "periodo",
        "disponivel",
        "fonte",
    }
)


def _validar_registros(registros: Sequence[Mapping[str, Any]]) -> None:
    if not registros:
        raise ValueError("O dashboard não pode ser gerado sem registros.")

    for indice, registro in enumerate(registros):
        ausentes = CAMPOS_OBRIGATORIOS - registro.keys()
        if ausentes:
            raise ValueError(
                f"Registro {indice} sem campos obrigatórios: "
                + ", ".join(sorted(ausentes))
            )


def gerar_conteudo_dashboard(
    registros: Sequence[Mapping[str, Any]], template: str
) -> str:
    """Incorpora registros no template sem permitir encerrar o script de dados."""
    _validar_registros(registros)
    if template.count(MARCADOR_INICIO) != 1 or template.count(MARCADOR_FIM) != 1:
        raise ValueError("Template do dashboard sem marcadores de dados válidos.")

    dados = json.dumps(list(registros), ensure_ascii=False, separators=(",", ":"))
    dados = dados.replace("<", "\\u003c")
    dados = dados.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    bloco = f"{MARCADOR_INICIO}\n{dados}\n    {MARCADOR_FIM}"
    padrao = re.compile(
        re.escape(MARCADOR_INICIO) + r".*?" + re.escape(MARCADOR_FIM),
        re.DOTALL,
    )
    return padrao.sub(lambda _resultado: bloco, template, count=1)


def escrever_atomico(caminho: Path, conteudo: str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
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


def atualizar_dashboard(
    arquivo_dados: Path = ARQUIVO_DADOS,
    caminho_dashboard: Path = ARQUIVO_DASHBOARD,
) -> Path:
    """Regenera o dashboard usando um JSON histórico já existente."""
    registros = json.loads(arquivo_dados.read_text(encoding="utf-8"))
    if not isinstance(registros, list):
        raise ValueError("O arquivo de dados precisa conter uma lista JSON.")
    template = caminho_dashboard.read_text(encoding="utf-8")
    escrever_atomico(
        caminho_dashboard, gerar_conteudo_dashboard(registros, template)
    )
    return caminho_dashboard


if __name__ == "__main__":
    caminho = atualizar_dashboard()
    print(f"Dashboard atualizado em: {caminho.resolve()}")
