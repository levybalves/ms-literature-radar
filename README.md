# Radar EM — Monitor de literatura científica em esclerose múltipla

O **Radar EM** é uma aplicação web local desenvolvida em **Python, Flask e SQLite** para acompanhar literatura científica recente sobre **esclerose múltipla (EM)** a partir do PubMed.

A aplicação consulta registros bibliográficos por meio das **NCBI E-utilities**, armazena os artigos localmente, classifica os trabalhos em tópicos de interesse e disponibiliza uma interface web para triagem e acompanhamento da literatura.

O objetivo é facilitar o monitoramento contínuo de novas publicações, reduzindo o trabalho manual de busca e permitindo organizar os artigos por área temática, período, relevância, status de leitura e favoritos.

---

## Funcionalidades

O Radar EM inclui:

- consulta automatizada ao PubMed;
- busca por período de publicação;
- recuperação em lote por meio do NCBI EFetch;
- armazenamento local utilizando SQLite;
- deduplicação automática por PMID;
- classificação temática baseada em palavras-chave ponderadas;
- classificação multi-tópico;
- identificação de um tópico principal para cada artigo;
- escore de relevância para auxiliar a triagem;
- busca textual em títulos, resumos e periódicos;
- filtro por período;
- filtro por tópico;
- filtro de artigos não lidos;
- sistema de favoritos;
- marcação de artigos como lidos;
- links diretos para PubMed;
- links diretos para DOI quando disponíveis;
- estatísticas do conjunto de artigos;
- histórico local cumulativo;
- interface web responsiva;
- layout escuro;
- tratamento de erros temporários da API;
- mecanismo de retry/backoff em respostas HTTP como `429` e erros de servidor.

---

## Visão geral

O fluxo do Radar EM pode ser representado da seguinte forma:

```text
                PubMed / NCBI
                      │
                      ▼
                   ESearch
                      │
                 lista de PMIDs
                      │
                      ▼
                   EFetch
                      │
             metadados + abstract
                      │
                      ▼
             classificação temática
                      │
                      ▼
             escore de relevância
                      │
                      ▼
                  SQLite
                      │
                      ▼
                  Flask
                      │
                      ▼
             Interface web local
```

A etapa de coleta e a etapa de visualização são independentes.

Os artigos permanecem armazenados no banco local e podem posteriormente ser visualizados utilizando diferentes janelas temporais.

---

## Fonte dos dados

O Radar EM utiliza o **PubMed**, por meio das **NCBI E-utilities**, como fonte principal de metadados bibliográficos.

A busca central utiliza registros associados à esclerose múltipla, considerando termos MeSH e ocorrências em título ou resumo.

Exemplo conceitual da consulta:

```text
"multiple sclerosis"[MeSH Terms]
OR
"multiple sclerosis"[Title/Abstract]
```

O projeto não realiza scraping direto das páginas das editoras.

Essa abordagem foi escolhida porque páginas de periódicos podem mudar sua estrutura HTML, utilizar JavaScript dinâmico, cookies e diferentes sistemas de acesso.

A API do NCBI fornece uma interface estruturada e mais adequada para recuperação programática de registros científicos.

---

# Estrutura do projeto

```text
ms-literature-radar/
│
├── app.py
├── requirements.txt
├── README.md
├── LICENSE
├── .gitignore
├── .env.example
│
├── radar/
│   ├── __init__.py
│   ├── classifier.py
│   ├── config.py
│   ├── db.py
│   ├── models.py
│   ├── pipeline.py
│   └── pubmed.py
│
├── config/
│   └── topics.yaml
│
├── templates/
│   ├── base.html
│   └── index.html
│
├── static/
│   ├── app.js
│   └── style.css
│
└── data/
    └── .gitkeep
```

---

# Requisitos

Recomenda-se:

- Python 3.10 ou superior;
- Python 3.12 para reproduzir o ambiente utilizado no desenvolvimento;
- acesso à internet para consultar o PubMed;
- navegador web moderno.

As principais dependências são:

```text
Flask>=3.0,<4
requests>=2.32,<3
PyYAML>=6.0,<7
python-dotenv>=1.0,<2
```

---

# Instalação

## Opção 1 — Conda

Crie um ambiente:

```bash
conda create -n radar-em python=3.12 -y
```

Ative:

```bash
conda activate radar-em
```

As dependências podem ser instaladas pelo `conda-forge`:

```bash
conda install -c conda-forge \
  "flask>=3,<4" \
  "requests>=2.32,<3" \
  "pyyaml>=6,<7" \
  "python-dotenv>=1,<2"
```

Também é possível utilizar o `pip` dentro do ambiente:

```bash
python -m pip install -r requirements.txt
```

---

## Opção 2 — venv

No Linux ou WSL:

```bash
python3 -m venv .venv
```

Ative:

```bash
source .venv/bin/activate
```

Instale as dependências:

```bash
python -m pip install -r requirements.txt
```

No Windows:

```powershell
python -m venv .venv
```

Depois:

```powershell
.venv\Scripts\activate
```

e:

```powershell
python -m pip install -r requirements.txt
```

---

# Configuração

O projeto utiliza um arquivo `.env` para armazenar configurações locais.

No Linux ou WSL:

```bash
cp .env.example .env
```

No Windows:

```powershell
copy .env.example .env
```

Um exemplo de configuração é:

```env
PUBMED_EMAIL=seu_email@exemplo.com

NCBI_API_KEY=

LOOKBACK_DAYS=45
PUBMED_RETMAX=250
PUBMED_BATCH_SIZE=150

DEFAULT_VIEW_DAYS=5

SECRET_KEY=troque-esta-chave

HOST=127.0.0.1
PORT=5050

DEBUG=false
```

---

## PUBMED_EMAIL

Recomenda-se informar um endereço de e-mail válido:

```env
PUBMED_EMAIL=seu_email@exemplo.com
```

O NCBI recomenda que aplicações que utilizam as E-utilities sejam identificadas.

---

## NCBI_API_KEY

A chave da API é opcional:

```env
NCBI_API_KEY=
```

Caso possua uma chave do NCBI, ela pode ser adicionada:

```env
NCBI_API_KEY=sua_chave
```

Nunca publique sua chave de API em um repositório público.

O arquivo `.env` deve permanecer listado no `.gitignore`.

---

## Porta do servidor

A porta pode ser definida no `.env`.

Exemplo:

```env
PORT=5050
```

Nesse caso, o painel ficará disponível em:

```text
http://127.0.0.1:5050
```

Se preferir outra porta:

```env
PORT=5000
```

ou:

```env
PORT=8000
```

---

# Primeira coleta de artigos

Para preencher o banco inicialmente com os artigos encontrados nos últimos 60 dias:

```bash
python app.py --update --days 60
```

Um resultado possível é:

```text
{'ok': True, 'articles_seen': 250, 'inserted': 250, 'updated': 0}
```

Os campos representam:

- `articles_seen`: número de registros recuperados do PubMed;
- `inserted`: artigos novos adicionados ao banco;
- `updated`: registros que já existiam e foram atualizados.

---

# Atualizando a literatura

Para consultar publicações recentes:

```bash
python app.py --update --days 7
```

Outros exemplos:

```bash
python app.py --update --days 1
```

```bash
python app.py --update --days 5
```

```bash
python app.py --update --days 15
```

```bash
python app.py --update --days 30
```

A atualização não apaga o histórico.

Registros que já existem são identificados pelo PMID e atualizados em vez de duplicados.

---

# Executando o painel

Inicie o servidor:

```bash
python app.py
```

Se o `.env` contiver:

```env
PORT=5050
```

abra no navegador:

```text
http://127.0.0.1:5050
```

ou:

```text
http://localhost:5050
```

---

# Filtro temporal

Por padrão, o painel pode ser configurado para mostrar os últimos 5 dias:

```env
DEFAULT_VIEW_DAYS=5
```

A interface permite selecionar diferentes períodos, como:

- hoje;
- últimos 3 dias;
- últimos 5 dias;
- últimos 7 dias;
- últimos 15 dias;
- últimos 30 dias;
- últimos 60 dias;
- últimos 90 dias;
- todo o histórico.

Também é possível informar o período diretamente na URL.

### Últimos 5 dias

```text
http://127.0.0.1:5050/?days=5
```

### Últimos 7 dias

```text
http://127.0.0.1:5050/?days=7
```

### Últimos 30 dias

```text
http://127.0.0.1:5050/?days=30
```

### Todo o histórico

```text
http://127.0.0.1:5050/?days=all
```

---

# Coleta e visualização são independentes

É importante distinguir a janela de coleta da janela de visualização.

O comando:

```bash
python app.py --update --days 7
```

consulta o PubMed e adiciona ou atualiza artigos encontrados nos últimos sete dias.

Já:

```text
/?days=5
```

apenas modifica quais registros armazenados são exibidos no painel.

Nenhum artigo é removido do banco ao alterar o filtro de visualização.

Por exemplo:

```text
PubMed
   │
   │ coleta: últimos 7 dias
   ▼
SQLite
   │
   ├── visualização: últimos 5 dias
   ├── visualização: últimos 30 dias
   └── visualização: todo o histórico
```

---

# Pesquisa textual

O campo de pesquisa permite localizar artigos utilizando termos encontrados em:

- título;
- resumo;
- nome do periódico.

A pesquisa pode ser combinada com os demais filtros.

---

# Filtros por tópico

Os artigos são classificados em categorias temáticas.

A configuração padrão inclui:

- HLA e apresentação antigênica;
- EBV e virologia;
- imunologia e patogênese;
- genética e epigenética;
- biomarcadores e ômicas;
- neurodegeneração e remielinização;
- tratamento e ensaios clínicos;
- imagem e neuroimagem;
- epidemiologia e fatores de risco;
- biologia computacional e estrutural;
- curso clínico e prognóstico.

Os identificadores internos incluem:

```text
hla_antigen
ebv_virology
immunology
genetics
biomarkers_omics
neurodegeneration
therapy_trials
imaging
epidemiology
computational
clinical_course
```

É possível utilizar esses identificadores diretamente na URL.

Exemplo:

```text
http://127.0.0.1:5050/?days=30&topic=ebv_virology
```

Outro exemplo:

```text
http://127.0.0.1:5050/?days=30&topic=hla_antigen
```

---

# Personalização dos tópicos

Os tópicos são configurados em:

```text
config/topics.yaml
```

Exemplo:

```yaml
- id: ebv_virology
  label: "EBV & virologia"
  icon: "🦠"

  keywords:
    "Epstein-Barr": 4.0
    "EBV": 4.0
    "EBNA1": 4.0
    "infectious mononucleosis": 3.0
    "molecular mimicry": 3.0
```

Cada expressão possui um peso.

Valores maiores indicam maior importância daquele termo para a classificação temática.

---

# Classificação temática

A classificação considera diferentes componentes dos registros bibliográficos:

- título;
- resumo;
- termos MeSH;
- palavras-chave.

Correspondências no título recebem maior peso.

Termos MeSH e keywords também recebem peso elevado por serem metadados mais controlados.

Correspondências apenas no resumo contribuem com peso menor.

Conceitualmente:

```text
termo no título
      │
      ▼
peso elevado

termo em MeSH / keywords
      │
      ▼
peso intermediário-alto

termo no resumo
      │
      ▼
peso padrão
```

Um artigo pode apresentar correspondência com vários tópicos.

O tópico com maior pontuação é utilizado como categoria principal para organização do painel.

---

# Escore de relevância

Cada artigo recebe um escore utilizado exclusivamente para auxiliar a triagem bibliográfica.

O escore considera fatores como:

- pertinência à busca sobre esclerose múltipla;
- correspondência com os tópicos configurados;
- força das palavras-chave encontradas;
- recência;
- tipo de publicação.

O escore é limitado a uma escala de 0 a 100.

Ele **não representa**:

- qualidade metodológica;
- força de evidência;
- fator de impacto;
- qualidade do periódico;
- importância científica definitiva;
- recomendação de leitura.

O objetivo é apenas ajudar a priorizar artigos durante a triagem.

---

# Favoritos

Os artigos podem ser marcados como favoritos diretamente no painel.

Essa informação fica armazenada no SQLite e continua disponível após reiniciar a aplicação.

---

# Artigos lidos e não lidos

O Radar EM também permite marcar artigos como lidos.

É possível filtrar apenas os registros ainda não revisados.

Isso permite utilizar o painel como uma pequena ferramenta de acompanhamento contínuo de literatura.

---

# Banco de dados

O banco local fica em:

```text
data/radar.sqlite3
```

Ele armazena:

- PMID;
- DOI;
- título;
- resumo;
- periódico;
- data de publicação;
- autores;
- tipos de publicação;
- termos MeSH;
- keywords;
- classificação temática;
- escore de relevância;
- favoritos;
- status de leitura;
- data de primeira identificação;
- data da última atualização.

---

# Backup do banco

Antes de alterações importantes no projeto, recomenda-se copiar o banco:

```bash
cp data/radar.sqlite3 data/radar.sqlite3.backup
```

O banco de dados não deve ser incluído no GitHub.

O `.gitignore` deve conter:

```gitignore
data/*.sqlite3
data/*.sqlite3-wal
data/*.sqlite3-shm
data/*.db
```

---

# Limite de registros por consulta

A quantidade máxima de registros recuperados pode ser configurada por:

```env
PUBMED_RETMAX=250
```

Por exemplo:

```env
PUBMED_RETMAX=500
```

ou:

```env
PUBMED_RETMAX=1000
```

Esse valor determina quantos registros podem ser recuperados em uma execução da busca.

---

# Atualização diária

Uma estratégia prática é consultar diariamente os últimos sete dias:

```bash
python app.py --update --days 7
```

A sobreposição temporal ajuda a recuperar trabalhos que tenham sido adicionados ou atualizados no PubMed com algum atraso.

Como o banco utiliza o PMID como identificador, artigos já existentes não são duplicados.

---

# Automação no Linux / WSL

É possível utilizar `cron`.

Exemplo:

```cron
15 7 * * * /caminho/python /caminho/ms-literature-radar/app.py --update --days 7
```

Esse exemplo executa a atualização diariamente às 07:15.

Certifique-se de informar o caminho correto do Python utilizado pelo ambiente.

Exemplo:

```bash
which python
```

---

# Automação no Windows

Também é possível utilizar o **Agendador de Tarefas do Windows**.

Programa:

```text
C:\caminho\para\python.exe
```

Argumentos:

```text
C:\caminho\para\ms-literature-radar\app.py --update --days 7
```

Diretório inicial:

```text
C:\caminho\para\ms-literature-radar
```

---

# Observações sobre datas

O filtro utiliza a data de publicação disponível no registro recuperado do PubMed.

Nem todos os registros apresentam o mesmo nível de precisão.

Alguns podem conter:

```text
2026-09-18
```

outros:

```text
2026-09
```

e alguns registros podem possuir apenas:

```text
2026
```

Por esse motivo, janelas temporais muito curtas podem não incluir determinados registros quando o PubMed ainda não disponibilizou uma data completa.

Também é importante distinguir:

- data de publicação;
- data de indexação no PubMed;
- data de publicação eletrônica;
- data da edição impressa.

O Radar utiliza a melhor data de publicação disponível no registro recuperado.

---

# Segurança e privacidade

O Radar EM é executado localmente.

O histórico de leitura, favoritos e banco de artigos permanecem no computador do usuário.

O projeto não envia essas informações para um servidor próprio.

Entretanto, durante a atualização, requisições são realizadas aos serviços do NCBI/PubMed para recuperar os registros bibliográficos.

Nunca publique arquivos contendo:

```text
.env
```

ou:

```text
NCBI_API_KEY
```

em repositórios públicos.

---

# Arquivos que não devem ser enviados ao GitHub

Um `.gitignore` recomendado é:

```gitignore
# Environment
.env

# Python
__pycache__/
*.py[cod]
*$py.class

# Virtual environments
.venv/
venv/
env/

# Conda
.conda/

# Database
data/*.sqlite3
data/*.sqlite3-wal
data/*.sqlite3-shm
data/*.db

# Keep directory
!data/.gitkeep

# Cache
.pytest_cache/
.coverage
htmlcov/

# IDEs
.vscode/
.idea/

# Operating system
.DS_Store
Thumbs.db

# Temporary files
*.log
*.tmp
*.bak
```

---

# Possíveis extensões

A arquitetura permite adicionar novas funcionalidades futuramente, como:

- Europe PMC como fonte complementar;
- integração com Crossref;
- feeds RSS de periódicos;
- exportação BibTeX;
- exportação CSV;
- integração com Zotero;
- gráficos de número de publicações por período;
- tendências temáticas;
- comparação entre tópicos;
- classificação semântica por embeddings;
- modelos de linguagem para resumo de artigos;
- identificação automática de artigos altamente relacionados;
- alertas por e-mail;
- alertas por Telegram;
- painel de periódicos mais frequentes;
- acompanhamento de autores;
- acompanhamento de termos específicos;
- busca por DOI;
- classificação por tipo de estudo;
- análise de tendências temporais;
- integração com Europe PMC para informações de acesso aberto;
- sincronização opcional com bancos bibliográficos externos.

---

# Limitações

O Radar EM deve ser entendido como uma ferramenta de apoio à triagem bibliográfica.

A classificação automática depende das palavras-chave e pesos definidos em:

```text
config/topics.yaml
```

Portanto, artigos multidisciplinares podem ser atribuídos a um tópico principal mesmo quando apresentam forte relação com outras categorias.

O escore de relevância também não substitui avaliação crítica do artigo.

A ausência de um artigo no painel não significa necessariamente ausência do trabalho no PubMed ou na literatura científica.

O conjunto recuperado depende:

- da consulta configurada;
- do período utilizado;
- do limite de registros;
- da disponibilidade dos metadados;
- do estado de indexação no PubMed.

---

# Uso científico

O Radar EM foi desenvolvido para facilitar o acompanhamento de literatura científica sobre esclerose múltipla.

A ferramenta pode ser utilizada como apoio para:

- revisão diária ou semanal da literatura;
- identificação de novas publicações;
- acompanhamento de áreas específicas;
- preparação de revisões bibliográficas;
- identificação de tendências temáticas;
- triagem inicial de artigos;
- acompanhamento de tópicos relacionados a projetos de pesquisa.

O sistema não substitui estratégias formais de busca bibliográfica utilizadas em revisões sistemáticas.

---

# Data source

Bibliographic information is retrieved from:

**PubMed / National Center for Biotechnology Information (NCBI)**

por meio das **NCBI Entrez Programming Utilities (E-utilities)**.

O Radar EM não possui afiliação oficial com o NCBI, NIH ou PubMed.

Resumos e demais conteúdos bibliográficos permanecem sujeitos aos direitos e condições associados aos respectivos autores, periódicos, editoras e bases de dados.

---

# Contribuições

Sugestões, correções e contribuições são bem-vindas.

Para mudanças maiores, recomenda-se abrir primeiro uma issue descrevendo a proposta.

Possíveis contribuições incluem:

- novos tópicos;
- melhoria dos classificadores;
- novos filtros;
- novas fontes bibliográficas;
- melhorias de interface;
- exportação bibliográfica;
- testes automatizados;
- documentação.

---

# Licença

Este projeto pode ser distribuído sob a **MIT License**.

Consulte o arquivo:

```text
LICENSE
```

para os termos completos.

---

# Autor

**Levy Bueno Alves**

Pesquisador em bioinformática estrutural, simulação molecular e aprendizado de máquina aplicado a sistemas biomoleculares.

---

## Citation

Se o Radar EM for utilizado em um projeto acadêmico, publicação ou material científico, uma forma de citação específica poderá ser adicionada futuramente ao repositório.

Até que uma versão arquivada com DOI seja disponibilizada, recomenda-se citar o repositório do GitHub.

---

## Aviso

O Radar EM é uma ferramenta de monitoramento e triagem de literatura.

Os resultados apresentados pelo sistema devem ser avaliados criticamente pelo usuário antes de serem utilizados em contexto científico, clínico ou acadêmico.