# Scraper de municípios do IBGE

Projeto em Python para coletar os indicadores exibidos nas páginas de
**Cidades e Estados** do IBGE. O scraper utiliza Playwright para renderizar o
conteúdo dinâmico e Beautiful Soup para extrair os dados.

Atualmente, o projeto coleta informações dos seguintes municípios do Ceará:

- Cedro;
- Várzea Alegre;
- Lavras da Mangabeira;
- Aurora.

Os resultados são exportados nos formatos CSV e JSON.

## Tecnologias

- Python 3.12;
- Playwright;
- Beautiful Soup;
- Docker;
- Docker Compose.

## Estrutura do projeto

```text
.
├── scraping_ibge_municipios.py
├── requirements.txt
├── requirements-dev.txt
├── tests/
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .gitignore
├── LICENSE
└── README.md
```

Depois da execução, o diretório `resultados_ibge` conterá:

```text
resultados_ibge/
├── municipios_ibge.csv
└── municipios_ibge.json
```

## Pré-requisitos

Para executar com Docker, instale:

- [Docker](https://docs.docker.com/get-docker/);
- Docker Compose, já incluído nas versões atuais do Docker Desktop.

## Executando com Docker Compose

Clone o repositório e entre no diretório do projeto:

```bash
git clone git@github.com:thiagobessaphd/scraping_ibge.git
cd scraping_ibge
```

Crie o diretório de saída, construa a imagem e execute o scraper:

```bash
mkdir -p resultados_ibge
docker compose up --build
```

O processo do scraper é executado no contêiner como usuário sem privilégios.
Em Linux, se um diretório de saída já existente não permitir escrita ao seu
usuário, ajuste as permissões desse diretório antes de iniciar o Compose.

Ao terminar, o contêiner será encerrado e os arquivos estarão disponíveis em:

```text
./resultados_ibge/municipios_ibge.csv
./resultados_ibge/municipios_ibge.json
```

Nas próximas execuções, se não houver alterações na imagem, basta utilizar:

```bash
docker compose up
```

Para executar novamente sem manter o contêiner criado anteriormente:

```bash
docker compose run --rm scraper-ibge
```

## Executando sem Docker

É necessário ter o Python 3.12 ou superior instalado, a mesma versão principal
usada pela imagem Docker do projeto.

Crie e ative um ambiente virtual:

```bash
python -m venv .venv
source .venv/bin/activate
```

No Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Instale as dependências e o navegador Chromium:

```bash
pip install -r requirements.txt
playwright install chromium
```

Execute o scraper:

```bash
python scraping_ibge_municipios.py
```

## Executando os testes

Com o ambiente virtual ativo, instale as dependências de desenvolvimento e
execute a suíte:

```bash
pip install -r requirements-dev.txt
pytest
```

## Formato dos dados

Cada registro exportado contém os seguintes campos:

| Campo | Descrição |
| --- | --- |
| `municipio` | Nome do município |
| `indicador` | Nome do indicador disponibilizado pelo IBGE |
| `valor` | Valor apresentado na página |
| `unidade` | Unidade de medida, quando informada |
| `periodo` | Ano ou período de referência, quando informado |
| `fonte` | Fonte indicada pelo IBGE, quando informada |
| `url` | Página de origem do registro |

Entre os indicadores coletados estão os dados demográficos já exportados pelo
projeto e também:

- Escolarização;
- Índice de Desenvolvimento Humano Municipal (IDHM);
- Mortalidade infantil;
- Total de receitas brutas realizadas;
- Total de despesas brutas empenhadas;
- PIB per capita.

O arquivo CSV utiliza codificação UTF-8 com BOM, facilitando sua abertura no
Microsoft Excel sem perder os acentos.

## Adicionando outros municípios

Edite o dicionário `MUNICIPIOS`, no início do arquivo
`scraping_ibge_municipios.py`:

```python
MUNICIPIOS = {
    "Cedro": "https://www.ibge.gov.br/cidades-e-estados/ce/cedro.html",
    "Novo município": "URL_DA_PAGINA_DO_MUNICIPIO",
}
```

## Observações

- O scraper depende da estrutura atual das páginas do IBGE. Alterações no HTML
  podem exigir ajustes nos seletores.
- O projeto aguarda o carregamento dinâmico antes de extrair os indicadores.
- Evite execuções excessivamente frequentes. Consulte e respeite os termos de
  uso e as políticas de acesso do IBGE.
- Os dados pertencem às suas respectivas fontes oficiais. Este projeto apenas
  automatiza a coleta das informações públicas exibidas nas páginas.

## Fonte dos dados

[IBGE — Cidades e Estados](https://www.ibge.gov.br/cidades-e-estados.html)

## Licença

Distribuído sob a licença MIT. Consulte o arquivo [LICENSE](LICENSE).
