# Séries históricas municipais do IBGE

Projeto em Python para coletar séries históricas municipais diretamente da
API oficial de Pesquisas do IBGE. A implementação não depende de scraping de
HTML, navegador automatizado ou seletores sujeitos a mudanças no portal.

Os mesmos municípios cearenses do projeto original são mantidos:

- Cedro (`2303808`);
- Várzea Alegre (`2314003`);
- Lavras da Mangabeira (`2307502`);
- Aurora (`2301703`).

Os resultados são exportados nos formatos CSV e JSON, com uma observação para
cada combinação de município, indicador e período disponível. A mesma execução
também atualiza um dashboard HTML responsivo e autônomo em
`dashboards/index.html`.

## Indicadores e cobertura histórica

| ID na API | Indicador | Períodos atualmente disponíveis |
| ---: | --- | --- |
| `60045` | Escolarização de 6 a 14 anos | 2010 e 2022 |
| `329756` | IDHM | 1991, 2000 e 2010 |
| `30279` | Mortalidade infantil | Série anual desde 2006 |
| `28141` | Total de receitas brutas realizadas | Série anual desde 2013 |
| `29749` | Total de despesas brutas empenhadas | Série anual desde 2013 |
| `47001` | PIB per capita | Série anual desde 2010 |

A cobertura final é determinada pela própria API em cada execução. Novos
períodos publicados pelo IBGE são incorporados automaticamente.

## Arquitetura

O programa monta uma única requisição em lote para todos os municípios e
indicadores. A resposta agrupada por localidade é validada antes da publicação:
todos os quatro municípios e todos os seis indicadores precisam estar
presentes. Em caso de resposta parcial ou erro HTTP, os arquivos anteriores
são preservados.

Antes de publicar os resultados, o programa valida o template do dashboard e
incorpora nele a base histórica. A página funciona offline, sem bibliotecas ou
fontes externas, e oferece seleção de município e indicador, série temporal,
comparação municipal, indicadores recentes, tabela filtrável e exportação CSV.

As requisições possuem timeout e repetição automática para erros transitórios,
como HTTP 429 e falhas 5xx. Os arquivos são gravados primeiro em caminhos
temporários e publicados por substituição atômica.

## Tecnologias

- Python 3.12;
- Requests;
- API de Pesquisas do IBGE;
- Docker e Docker Compose;
- Pytest.

## Estrutura do projeto

```text
.
├── scraping_ibge_municipios.py
├── dashboard_generator.py
├── dashboards/
│   └── index.html
├── requirements.txt
├── requirements-dev.txt
├── tests/
│   └── test_scraping_ibge_municipios.py
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .gitignore
├── LICENSE
└── README.md
```

## Executando com Docker Compose

Crie o diretório de saída e execute:

```bash
mkdir -p resultados_ibge
docker compose up --build
```

Ao concluir, os arquivos estarão disponíveis em:

```text
.
├── resultados_ibge/
│   ├── municipios_ibge_historico.csv
│   └── municipios_ibge_historico.json
└── dashboards/
    └── index.html
```

Para executar novamente sem manter o contêiner:

```bash
docker compose run --rm scraper-ibge
```

## Executando sem Docker

Crie e ative um ambiente virtual com Python 3.12 ou superior:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scraping_ibge_municipios.py
```

Ao final da coleta, o dashboard é regenerado automaticamente. Para atualizá-lo
manualmente usando o JSON já existente, execute:

```bash
python dashboard_generator.py
```

## Visualizando o dashboard

Abra `dashboards/index.html` diretamente no navegador. Como alternativa, sirva
o projeto localmente e acesse `http://localhost:8000/dashboards/`:

```bash
python -m http.server 8000
```

O painel foi projetado para desktop e dispositivos móveis, possui tema claro e
escuro, navegação acessível e não envia os dados coletados a serviços externos.

No Windows PowerShell, a ativação do ambiente é feita com:

```powershell
.venv\Scripts\Activate.ps1
```

## Executando os testes

```bash
pip install -r requirements-dev.txt
pytest
```

Os testes não acessam a internet: respostas da API são simuladas para validar
URL, timeout, períodos, símbolos de indisponibilidade, falhas parciais,
equivalência entre CSV e JSON e geração segura do dashboard.

## Formato dos dados

| Campo | Descrição |
| --- | --- |
| `municipio` | Nome do município |
| `codigo_ibge` | Código oficial do município com sete dígitos |
| `indicador_id` | Identificador do indicador na API |
| `indicador` | Nome legível do indicador |
| `valor` | Valor textual retornado pela API, sem perda de precisão |
| `unidade` | Unidade de medida |
| `periodo` | Ano ou período de referência |
| `disponivel` | Indica se o valor representa um dado disponível |
| `nota` | Nota específica do período, quando fornecida |
| `fonte` | Instituição ou pesquisa responsável pelo indicador |
| `url` | URL exata utilizada na consulta em lote |

Símbolos especiais do IBGE, como `-`, `..`, `...` e `X`, são preservados em
`valor` e marcados com `disponivel: false`. Isso permite distinguir ausência de
dado de valores numéricos iguais a zero.

## Adicionando municípios

Edite o dicionário `MUNICIPIOS` no início de
`scraping_ibge_municipios.py`, informando o nome e o código IBGE de sete
dígitos:

```python
MUNICIPIOS = {
    "Cedro": "2303808",
    "Novo município": "0000000",
}
```

## Fonte dos dados

- [Serviço de dados do IBGE](https://servicodados.ibge.gov.br/api/docs/);
- [Sistema IBGE de Recuperação Automática — SIDRA](https://sidra.ibge.gov.br/).

## Licença

Distribuído sob a licença MIT. Consulte o arquivo [LICENSE](LICENSE).
