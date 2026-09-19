# Radar EM — monitor de literatura científica em esclerose múltipla

O **Radar EM** é uma aplicação web local em **Python + Flask + SQLite** para acompanhar literatura científica recente sobre **esclerose múltipla (EM)**.

A descoberta é feita por **três fontes complementares**:

- **PubMed / NCBI**;
- **Crossref**;
- **Europe PMC**.

Os registros encontrados são consolidados em um único banco local, deduplicados principalmente por **PMID, DOI e PMCID**, classificados por tópicos e exibidos em um painel para triagem bibliográfica.

O projeto também oferece enriquecimento opcional com metadados estruturados e com **BeautifulSoup** para páginas HTML públicas de editoras, sem contornar paywalls, autenticação, CAPTCHA ou `robots.txt`.

---

## Por que usar várias fontes?

Um artigo pode aparecer no site da editora ou no Crossref antes de receber um PMID ou aparecer na busca do PubMed. Por isso, o Radar EM não depende de uma única base para descobrir trabalhos recentes.

```text
                  PubMed
                    │
                  Crossref
                    │
                Europe PMC
                    │
                    ▼
             normalização comum
                    │
                    ▼
               deduplicação
          PMID / DOI / PMCID / título
                    │
                    ▼
              enriquecimento
                    │
                    ▼
            classificação temática
                    │
                    ▼
                  SQLite
                    │
                    ▼
                   Flask
                    │
                    ▼
                Radar EM
```

Se o mesmo artigo for primeiro descoberto pelo Crossref e depois aparecer no PubMed, o Radar tenta **atualizar o mesmo registro**, em vez de criar uma duplicata.

## Filtro de especificidade para esclerose múltipla

A descoberta multi-fonte aumenta a sensibilidade, mas pode trazer registros que apenas mencionam esclerose múltipla de forma periférica. Por isso, antes de entrar no feed principal, cada registro passa por uma etapa separada de **elegibilidade para EM**.

O filtro considera principalmente:

- `multiple sclerosis` no título;
- MeSH específico de esclerose múltipla;
- keywords/author keywords específicas;
- posição e repetição da expressão no abstract;
- acrônimos específicos como `RRMS`, `SPMS` e `PPMS`.

O termo curto **`MS` isolado não é usado como evidência**, porque pode significar mass spectrometry, manuscript, milliseconds e outros termos.

Os registros recebem um estado:

- **high** — alta especificidade para EM;
- **moderate** — evidência suficiente para entrar no feed;
- **pending** — metadados ainda insuficientes, comum em artigos Crossref muito recentes;
- **excluded** — evidência insuficiente após avaliação;
- **manual** — artigo importado explicitamente por DOI pelo usuário enquanto os metadados ainda são incompletos.

Por padrão, o painel mostra apenas `high`, `moderate` e `manual`. Pendentes e excluídos ficam fora do feed principal, mas podem ser auditados pelos filtros do painel.

Um artigo recém-publicado sem abstract pode permanecer como `pending`; quando PMID, abstract ou keywords forem adicionados posteriormente, ele é reavaliado e pode passar automaticamente para `high` ou `moderate`.

---

## Funcionalidades

- descoberta recente no PubMed;
- descoberta recente no Crossref;
- descoberta recente no Europe PMC;
- tolerância a falha parcial: uma fonte indisponível não impede necessariamente as demais;
- deduplicação entre fontes;
- atualização posterior de PMID/DOI/PMCID quando novos identificadores aparecem;
- importação direta por DOI;
- armazenamento local em SQLite;
- migração automática de bancos criados por versões anteriores do Radar EM;
- classificação por tópicos usando título, resumo, MeSH, keywords e metadados complementares;
- filtro de especificidade para EM antes do feed principal;
- escore independente de especificidade para EM;
- escore de relevância para triagem temática;
- filtros por período, tópico, fonte, especificidade para EM, texto, favoritos, não lidos, Open Access e registros enriquecidos;
- favoritos e status de leitura persistentes;
- links para PubMed, DOI, editora e texto completo quando disponíveis;
- página individual de detalhes de cada artigo;
- enriquecimento por Crossref e Europe PMC;
- BeautifulSoup opcional para HTML público da editora;
- detecção de links de material suplementar quando explicitamente expostos no HTML;
- detecção de graphical abstract quando indicado nos metadados HTML;
- interface responsiva e escura;
- histórico de execuções e contagem por fonte.

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
│   ├── crossref.py
│   ├── db.py
│   ├── enrichment.py
│   ├── eligibility.py
│   ├── europe_pmc.py
│   ├── merge.py
│   ├── models.py
│   ├── pipeline.py
│   └── pubmed.py
│
├── config/
│   └── topics.yaml
│
├── templates/
│   ├── base.html
│   ├── index.html
│   └── article.html
│
├── static/
│   ├── app.js
│   └── style.css
│
├── tests/
│   └── ...
│
└── data/
    └── .gitkeep
```

---

# Requisitos

Recomenda-se **Python 3.10 ou superior**. O desenvolvimento e os testes foram preparados para funcionar com Python moderno, incluindo Python 3.12.

Dependências principais:

```text
Flask>=3.0,<4
requests>=2.32,<3
PyYAML>=6.0,<7
python-dotenv>=1.0,<2
beautifulsoup4>=4.12,<5
```

---

# Instalação

## Conda

```bash
conda create -n radar-em python=3.12 -y
conda activate radar-em
```

Instalação pelo `conda-forge`:

```bash
conda install -c conda-forge \
  "flask>=3,<4" \
  "requests>=2.32,<3" \
  "pyyaml>=6,<7" \
  "python-dotenv>=1,<2" \
  "beautifulsoup4>=4.12,<5"
```

Ou com `pip`:

```bash
python -m pip install -r requirements.txt
```

## venv

Linux / WSL:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

---

# Configuração

Copie o exemplo:

Linux / WSL:

```bash
cp .env.example .env
```

Windows:

```powershell
copy .env.example .env
```

Exemplo:

```env
PUBMED_EMAIL=seu_email@exemplo.com
NCBI_API_KEY=
CROSSREF_EMAIL=seu_email@exemplo.com

DISCOVERY_QUERY=multiple sclerosis
PUBMED_DISCOVERY_ENABLED=true
CROSSREF_DISCOVERY_ENABLED=true
EUROPE_PMC_DISCOVERY_ENABLED=true

PUBMED_RETMAX=250
PUBMED_BATCH_SIZE=150
CROSSREF_RETMAX=250
EUROPE_PMC_RETMAX=250
CROSSREF_DISCOVERY_INCLUDE_CREATED=true

MS_ELIGIBILITY_ENABLED=true
MS_HIGH_THRESHOLD=9
MS_MODERATE_THRESHOLD=6
MS_STORE_PENDING=true
MS_REASSESS_ON_STARTUP=true

LOOKBACK_DAYS=45
DEFAULT_VIEW_DAYS=5

ENRICHMENT_ENABLED=true
CROSSREF_ENABLED=true
EUROPE_PMC_ENABLED=true
PUBLISHER_HTML_ENABLED=false
ENRICHMENT_MAX_ARTICLES=50
ENRICHMENT_TIMEOUT=20
ENRICHMENT_PAUSE_SECONDS=0.15
HTML_MAX_BYTES=2000000

SECRET_KEY=troque-esta-chave
HOST=127.0.0.1
PORT=5050
DEBUG=false
```

Nunca envie `.env` ou uma chave de API para um repositório público.

---

# Atualizar a literatura

Para procurar artigos nos últimos 7 dias nas três fontes:

```bash
python app.py --update --days 7
```

Exemplo de saída:

```text
{
  'ok': True,
  'articles_seen': 87,
  'raw_seen': 142,
  'inserted': 21,
  'updated': 66,
  'deduplicated': 55,
  'ms_eligible': 74,
  'ms_high': 52,
  'ms_moderate': 22,
  'ms_pending': 8,
  'excluded_not_ms': 5,
  'sources': {
    'PubMed': 48,
    'Crossref': 57,
    'Europe PMC': 37
  }
}
```

`raw_seen` é a soma bruta dos registros vindos das fontes. `articles_seen` é o total restante depois da consolidação entre fontes.

---

## Selecionar fontes no terminal

Somente PubMed:

```bash
python app.py --update --days 7 --sources pubmed
```

PubMed + Crossref:

```bash
python app.py --update --days 7 --sources pubmed,crossref
```

Crossref + Europe PMC:

```bash
python app.py --update --days 7 --sources crossref,europe_pmc
```

Todas:

```bash
python app.py --update --days 7 --sources pubmed,crossref,europe_pmc
```

---

# Reavaliar registros já existentes

Ao abrir um banco antigo, registros ainda não avaliados são classificados automaticamente. Se você alterar os limiares de especificidade ou quiser refazer a triagem de todo o banco, use:

```bash
python app.py --reassess-ms
```

Exemplo de saída:

```text
{'high': 120, 'moderate': 34, 'pending': 8, 'excluded': 19, 'manual': 1}
```

A reavaliação **não apaga** registros. Ela apenas atualiza o estado de especificidade; o feed padrão passa a esconder os que forem `pending` ou `excluded`.

---

# Importar diretamente por DOI

Se você conhece um DOI e quer colocá-lo no Radar imediatamente, mesmo antes de ele aparecer no PubMed:

```bash
python app.py --add-doi 10.1021/acsomega.6c06047
```

Também existe um campo **“Importar DOI”** no próprio painel web.

O Radar consulta o Crossref e tenta complementar o registro com Europe PMC. Se posteriormente surgir um PMID para o mesmo DOI, a atualização normal tenta anexá-lo ao registro existente.

Para incluir HTML público da editora na importação:

```bash
python app.py --add-doi 10.1021/acsomega.6c06047 --publisher-html
```

A importação direta é uma ação explícita do usuário. Se os metadados ainda não forem suficientes para provar a relação com EM, o artigo é mantido como `manual` até que novas informações permitam reclassificá-lo.

---

# Enriquecimento

Atualização normal com enriquecimento estruturado:

```bash
python app.py --update --days 7 --enrich
```

Sem enriquecimento adicional:

```bash
python app.py --update --days 7 --no-enrich
```

Com HTML público / BeautifulSoup:

```bash
python app.py --update --days 7 --publisher-html
```

BeautifulSoup é uma camada complementar. O código verifica `robots.txt` e não tenta contornar mecanismos de acesso.

---

# Executar o painel

```bash
python app.py
```

Com a configuração padrão:

```text
http://127.0.0.1:5050
```

ou:

```text
http://localhost:5050
```

---

# Filtros do painel

O painel permite filtrar por:

- período;
- tópico;
- fonte de descoberta;
- texto;
- não lidos;
- favoritos;
- Open Access;
- metadados enriquecidos.

Períodos disponíveis incluem hoje, 3, 5, 7, 15, 30, 60 e 90 dias, além de todo o histórico.

Exemplo:

```text
http://127.0.0.1:5050/?days=5
```

Todo o histórico:

```text
http://127.0.0.1:5050/?days=all
```

---

# Como funciona a deduplicação

O Radar tenta reconhecer o mesmo trabalho usando, nesta ordem, identificadores bibliográficos fortes:

1. PMID;
2. DOI normalizado;
3. PMCID;
4. fingerprint de título e ano como fallback conservador.

Exemplo:

```text
Crossref
DOI 10.xxxx/abc
      │
      ▼
registro criado
      │
      │ dias depois
      ▼
PubMed
PMID 12345678
DOI 10.xxxx/abc
      │
      ▼
mesmo DOI detectado
      │
      ▼
registro atualizado
PMID anexado
```

Favoritos e status de leitura são preservados quando um registro existente é atualizado.

---

# Como cada fonte é utilizada

## PubMed

Usa NCBI ESearch + EFetch para recuperar PMID, título, resumo, autores, periódico, MeSH, keywords e identificadores relacionados.

## Crossref

É utilizado tanto para **descoberta** quanto para enriquecimento. A busca usa a expressão bibliográfica configurada e janelas de data. Por padrão, o Radar consulta trabalhos com data de publicação recente e também registros recentemente depositados no Crossref.

Isso ajuda a encontrar artigos que já possuem DOI e registro de editora, mas ainda não receberam PMID.

## Europe PMC

Também participa da descoberta. Pode complementar DOI/PMID/PMCID, resumo, keywords, MeSH, Open Access e links de texto completo, conforme disponíveis.

## BeautifulSoup

É utilizado apenas quando explicitamente ativado. Extrai metadados públicos e genéricos do HTML, como:

- `citation_*`;
- JSON-LD de `ScholarlyArticle`;
- keywords;
- instituições;
- links públicos de PDF/full text indicados no HTML;
- links de material suplementar;
- graphical abstract quando marcado explicitamente.

---

# Banco SQLite e migração

O banco fica em:

```text
data/radar.sqlite3
```

O projeto detecta a estrutura anterior baseada em PMID como chave primária e migra os registros para um identificador interno independente da fonte.

Isso é necessário porque artigos descobertos no Crossref podem ainda não possuir PMID.

Antes de substituir o projeto, é recomendável fazer backup:

```bash
cp data/radar.sqlite3 data/radar.sqlite3.backup
```

O banco não deve ser enviado ao GitHub.

---

# Personalizar tópicos

Edite:

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
    "EBNA1": 4.0
    "molecular mimicry": 3.0
```

A classificação utiliza título, resumo, MeSH, keywords, subjects e outros metadados disponíveis.

---

# Escore de relevância

O escore serve apenas para **triagem bibliográfica**.

Ele combina:

- pertinência ao universo de busca;
- força da correspondência temática;
- recência;
- tipo de publicação.

Ele **não mede** qualidade metodológica, força de evidência, fator de impacto ou importância científica definitiva.

---

# Atualização diária

Uma rotina prática é:

```bash
python app.py --update --days 7
```

A sobreposição de sete dias ajuda a recuperar registros que entram nas bases com algum atraso. A deduplicação evita que isso gere cópias do mesmo trabalho.

---

# Testes

Se `pytest` estiver instalado:

```bash
python -m pytest -q
```

Os testes cobrem, entre outros pontos:

- parsing de Crossref;
- parsing de Europe PMC;
- deduplicação por DOI;
- consolidação Crossref → PubMed;
- migração do banco legado;
- filtro temporal;
- parser HTML do BeautifulSoup.

---

# Limitações

- nenhuma fonte garante indexação instantânea de todos os artigos;
- os metadados disponíveis variam entre editoras e bases;
- Crossref pode não conter resumo ou keywords para determinados trabalhos;
- Europe PMC e PubMed têm seus próprios tempos de indexação;
- páginas de editoras podem mudar a estrutura HTML;
- o módulo BeautifulSoup é best-effort;
- a classificação temática depende da qualidade dos metadados e das regras em `topics.yaml`;
- o Radar não substitui estratégias formais de busca usadas em revisões sistemáticas.

---

# Segurança e privacidade

O Radar EM é executado localmente. Favoritos, status de leitura e o banco bibliográfico ficam no computador do usuário.

Durante a atualização, requisições são enviadas somente às fontes bibliográficas configuradas e, se ativado, às páginas públicas das editoras.

---

# Licença

MIT License. Consulte `LICENSE`.

---

# Autor

**Levy Bueno Alves**

Projeto voltado ao monitoramento e à triagem de literatura científica sobre esclerose múltipla.
