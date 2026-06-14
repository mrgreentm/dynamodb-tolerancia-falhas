# DynamoDB Fault Tolerance Lab

Laboratório baseado no paper **Amazon DynamoDB: A Scalable, Predictably Performant, and Fully Managed NoSQL Database Service** (USENIX ATC 2022).

Demonstra, com evidências mensuráveis, três garantias centrais do DynamoDB Global Tables:

| # | Cenário | Propriedade testada | Seção |
|---|---------|---------------------|-------|
| A | `03_fault_region.py` | Alta disponibilidade multi-região durante partição | §5 |
| B | `04_fault_throttling.py` | Admission control e exponential backoff | §4 |
| C | `05_fault_conflict.py` | Last-write-wins com convergência eventual | §3.4 |

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                   DynamoDB Global Table                      │
│                                                             │
│  ┌──────────────┐            ┌──────────────────────────┐   │
│  │  sa-east-1   │◄──────────►│       us-east-1          │   │
│  │  (primária)  │            └──────────────────────────┘   │
│  └──────────────┘                        │                   │
│         │                   replicação   │                   │
│         └──────────────────────────────►┌┴───────────────┐  │
│                                         │   eu-west-1    │  │
│                                         └────────────────┘  │
└─────────────────────────────────────────────────────────────┘
         ▲
         │  CRUD / métricas CloudWatch
   ┌─────┴──────┐
   │  server.py │  Flask → localhost:8080
   └─────┬──────┘
         │
   ┌─────┴────────┐
   │ dashboard.html│  visualização em tempo real
   └──────────────┘
```

---

## Pré-requisitos

- Python 3.11+
- Terraform ≥ 1.5
- Conta AWS com permissões: `dynamodb:*`, `cloudwatch:GetMetricStatistics`

```bash
pip install -r requirements.txt
```

---

## Setup

### 1. Credenciais

```bash
cp .env.example .env
# edite .env com suas credenciais AWS
```

### 2. Infraestrutura (Terraform)

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# edite terraform.tfvars com suas credenciais
terraform init
terraform apply
```

Cria a tabela `Pedidos` com réplicas em `us-east-1` e `eu-west-1`, 3 GSIs e PITR ativado.

### 3. Validar e popular

```bash
cd scripts
python 01_setup_table.py   # valida que as 3 regiões estão ACTIVE
python 02_seed_data.py     # insere 50 pedidos de teste
```

### 4. Executar cenários

```bash
# Todos de uma vez (recomendado):
python run_all.py

# Ou individualmente:
python 03_fault_region.py      # Cenário A — falha de região
python 04_fault_throttling.py  # Cenário B — throttling
python 05_fault_conflict.py    # Cenário C — conflito LWW
python 06_validate_recovery.py # health check geral
```

### 5. Dashboard

```bash
# Na raiz do projeto:
python server.py
# Abra dashboard.html no browser
```

---

## Estrutura

```
sistemasdistribuidos/
├── README.md
├── requirements.txt
├── .env.example
├── server.py              # Flask API (backend do dashboard)
├── dashboard.html         # visualização em tempo real
├── terraform/
│   ├── main.tf            # tabela + réplicas + GSIs
│   ├── variables.tf
│   ├── outputs.tf
│   └── terraform.tfvars.example
├── scripts/
│   ├── utils.py                # utilitários compartilhados
│   ├── 01_setup_table.py       # valida infraestrutura
│   ├── 02_seed_data.py         # popula dados de teste
│   ├── 03_fault_region.py      # Cenário A: partição de região
│   ├── 04_fault_throttling.py  # Cenário B: throttling + backoff
│   ├── 05_fault_conflict.py    # Cenário C: LWW concorrente
│   ├── 06_validate_recovery.py # health check + latência
│   └── run_all.py              # orquestrador
└── results/               # JSONs de resultado (gerados)
```

---

## O que cada cenário demonstra

### Cenário A — Falha de Região (`03_fault_region.py`)

1. Remove a réplica `eu-west-1` da Global Table (simula partição de rede)
2. Continua gravando itens em `us-east-1` durante a "falha"
3. Mede disponibilidade de escrita durante a partição
4. Restaura a réplica e mede o tempo de convergência

**Resultados esperados:**
- Disponibilidade de escrita durante partição: **100%**
- Convergência pós-recovery: **< 30s**

### Cenário B — Throttling (`04_fault_throttling.py`)

1. Converte tabela para PROVISIONED com **1 WCU** (capacidade mínima)
2. **Fase 1 — sem retry:** envia 100 escritas concorrentes; mede taxa de `ProvisionedThroughputExceededException`
3. **Fase 2 — com retry:** repete com `max_attempts=10` e modo adaptativo; mede sucesso total e latência

**Resultados esperados:**
- Sem retry: 70–95% throttled
- Com retry (backoff exponencial): 100% de sucesso, ~3–10× mais lento

### Cenário C — Conflito LWW (`05_fault_conflict.py`)

1. Grava o mesmo item em `us-east-1` e `eu-west-1` **simultaneamente** (threads)
2. Faz polling em todas as regiões a cada 100ms até convergência
3. Repete por 5 rodadas e coleta estatísticas

**Resultados esperados:**
- Todas as rodadas convergem para um único valor
- Tempo de convergência: **< 2 000ms** (tipicamente 200–800ms)
- O valor vencedor é determinado pelo timestamp interno do DynamoDB (não pela aplicação)

---

## Referência

```
Vig, Nikhil et al. "Amazon DynamoDB: A Scalable, Predictably Performant,
and Fully Managed NoSQL Database Service."
USENIX Annual Technical Conference (ATC), 2022.
```
