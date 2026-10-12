# painelcf — Painel Calmon & Freitas Advogados

## Módulo de teses (DJEN / TJBA)

Consulta diariamente o **Diário de Justiça Eletrônico Nacional (DJEN)** do CNJ e analisa as sentenças do TJBA
proferidas nas unidades monitoradas:

- **Juizados Especiais com atendimento a demandas de consumo** — somente as 82 varas de 40 comarcas listadas em
  `config/teses.toml` (`[juizados_consumo]`). Em Salvador, apenas as 1ª a 20ª Varas do Sistema dos Juizados
  Especiais **do Consumidor**.
- **Varas de Relações de Consumo** (rito comum), inclusive as varas mistas do interior
  ("Vara dos Feitos de Relações de Consumo, Cíveis e Comerciais"). Pode ser desligado com
  `incluir_varas_relacoes_consumo = false`.
- Classes admitidas: *Procedimento Comum Cível* e *Procedimento do Juizado Especial Cível*.

Para cada sentença, identifica:

| Dado | Como |
|---|---|
| Resultado | dispositivo: procedente, parcialmente procedente, improcedente, prescrição/decadência, extinção sem mérito, acordo, embargos de declaração |
| Comarca e vara | nome do órgão; se ausente (ex.: "20ª VSJE DO CONSUMIDOR (VESPERTINO)", em Salvador), código de origem do número CNJ pela tabela `config/codigos_origem_tjba.json` |
| Juiz(a) | assinatura no teor publicado (togado e, no Juizado, também o juiz leigo) |
| Empresa(s) condenada(s) | polo passivo (`destinatarios` com polo "P"), com unificação de grupos econômicos (`[[empresas]]`) |
| Dano moral | valor em R$ mais próximo de "danos morais" no dispositivo |
| Indébito em dobro / inexistência de débito | expressões do dispositivo |
| Temas (teses) | palavras-chave configuráveis (`[temas]`): RMC/RCC, consignado, tarifas, negativação, energia etc. |

E gera, a cada execução, `relatorios/index.html` com:

1. sentenças procedentes do dia (com link para o inteiro teor);
2. ranking das **empresas mais condenadas** nos últimos 30 dias;
3. indicadores por **juiz**, **comarca**, **vara** e **tema**: condenações, taxa de procedência, dano moral mediano e % de condenação em dobro.

Também gera CSVs (abrem direto no Excel): `empresas.csv`, `juizes.csv`, `comarcas.csv` e `procedentes_AAAA-MM-DD.csv`.

### Requisitos

- Python 3.11 ou superior. Não há dependências externas.
- **Máquina com acesso à internet a partir do Brasil.** O CNJ bloqueia o DJEN para IPs estrangeiros
  (HTTP 403). Por isso a coleta não roda no GitHub Actions nem em servidores fora do país. Use o computador do
  escritório, um servidor local ou uma VPS em região brasileira.

### Uso

```sh
python -m painelcf.teses diario            # coleta os dias pendentes e gera o relatório
python -m painelcf.teses coletar --data 2026-10-09
python -m painelcf.teses coletar --inicio 2026-09-01 --fim 2026-09-30   # carga histórica
python -m painelcf.teses relatorio --dias 90                            # janela maior
python -m painelcf.teses reprocessar       # reaplica as regras após editar config/teses.toml
python -m painelcf.teses importar resposta.json   # importa JSON salvo manualmente da API
```

O banco fica em `dados/teses.db` (SQLite) e os relatórios em `relatorios/`.

### Agendamento diário

- **Windows:** Agendador de Tarefas → Criar Tarefa Básica → Diariamente, 9h →
  Iniciar programa `scripts\coleta_diaria.bat`. Antes, ajuste `PAINELCF` dentro do arquivo.
- **Linux/macOS:** `crontab -e` e adicione
  `0 9 * * * /caminho/painelcf/scripts/coleta_diaria.sh`.

O comando `diario` recupera sozinho os dias em que o computador esteve desligado (até 15 dias). Ele também
recoleta o último dia, porque a primeira execução pode ter ocorrido antes do fechamento do caderno.

### API utilizada

`GET https://comunicaapi.pje.jus.br/api/v1/comunicacao?siglaTribunal=TJBA&dataDisponibilizacaoInicio=AAAA-MM-DD&dataDisponibilizacaoFim=AAAA-MM-DD&pagina=N&itensPorPagina=100`

A API é pública e não exige autenticação. A estrutura das comunicações segue a especificação publicada pelo CNJ
(`api.swaggerhub.com/apis/cnj/pcp`). No modo `auto`, o módulo tenta antes baixar o caderno completo do dia
(`/api/v1/caderno/TJBA/AAAA-MM-DD/D`). Se o caderno não estiver disponível, consulta página a página.

### Limites da análise automática

- A classificação usa expressões regulares sobre o teor publicado. Confira o inteiro teor antes de citar uma
  sentença em peça.
- O juiz só é identificado quando a assinatura consta do texto publicado. As sentenças sem assinatura aparecem
  como "não identificado".
- Cada processo é contado uma vez nas estatísticas, pela sentença de mérito mais recente. Embargos de
  declaração não substituem a sentença.
- Para melhorar a precisão, ajuste `config/teses.toml` e rode `reprocessar`. Isso vale para incluir aliases de
  empresas, novos temas e códigos de origem de comarcas.

### Tabela de comarcas por código de origem

`config/codigos_origem_tjba.json` relaciona o código de origem do número CNJ (8.05.**OOOO**) à comarca. A
tabela é gerada a partir do DataJud e do IBGE, cobre 216 códigos e inclui as 40 comarcas da lista de Juizados.
Para atualizá-la, rode o comando abaixo. O DataJud não tem bloqueio geográfico, então ele funciona de qualquer
lugar:

```sh
python scripts/gerar_codigos_origem.py
```

### Testes

```sh
python -m unittest discover -s tests
```
