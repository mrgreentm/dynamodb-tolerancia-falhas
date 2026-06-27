# DynamoDB Fault Tolerance Lab

Laboratório baseado no paper **Amazon DynamoDB: A Scalable, Predictably Performant, and Fully Managed NoSQL Database Service** (USENIX ATC 2022).

Demonstra, com evidências mensuráveis, três garantias centrais do DynamoDB Global Tables usando **exclusivamente Terraform**:

| # | Cenário | Propriedade testada | Seção |
|---|---------|---------------------|-------|
| A | `scenarios/cenario_a/` | Alta disponibilidade multi-região durante partição | §5 |
| B | `scenarios/cenario_b/` | Admission control e exponential backoff | §4 |
| C | `scenarios/cenario_c/` | Last-write-wins com convergência eventual | §3.4 |

Cada cenário é um módulo Terraform independente que injeta o fault, executa o teste e restaura o estado — sem scripts externos.

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

- Terraform ≥ 1.5
- AWS CLI v2
- Conta AWS com permissões: `dynamodb:*`, `cloudwatch:GetMetricStatistics`
- Python 3.11+ (apenas para o dashboard)

```bash
pip install -r requirements.txt
```

---

## Setup

### 1. Credenciais

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# edite terraform.tfvars com suas credenciais AWS
```

### 2. Infraestrutura base

```bash
cd terraform
terraform init
terraform apply
```

Cria a tabela `Pedidos` com réplicas em `us-east-1` e `eu-west-1`, 3 GSIs e PITR ativado.

### 3. Popular dados

```bash
cd scripts
python 01_setup_table.py   # valida que as 3 regiões estão ACTIVE
python 02_seed_data.py     # insere 50 pedidos de teste
```

---

## Cenários de Fault Tolerance

Cada cenário é executado com `terraform apply` dentro do seu diretório. Credenciais são lidas do `terraform.tfvars` da raiz do módulo base.

### Cenário A — Falha de Região

Remove `eu-west-1`, grava 20 itens em `us-east-1`, restaura a réplica e mede o tempo de convergência. Tudo em uma única execução de `terraform apply`.

```bash
cd terraform/scenarios/cenario_a
terraform init
terraform apply -var-file=../../terraform.tfvars
```

**Resultados esperados:**
- Disponibilidade de escrita durante partição: **100%**
- Convergência pós-recovery: **< 30 s**

---

### Cenário B — Throttling / Admission Control

Converte a tabela para `PROVISIONED 1 WCU`, executa 100 escritas paralelas sem retry (mede throttling), repete com backoff adaptativo (mede sucesso), e restaura `PAY_PER_REQUEST`.

```bash
cd terraform/scenarios/cenario_b
terraform init
terraform apply -var-file=../../terraform.tfvars
```

**Resultados esperados:**
- Sem retry: **70–95%** das escritas throttled
- Com retry (backoff exponencial): **100%** de sucesso

---

### Cenário C — Conflito LWW (Last-Write-Wins)

O Terraform executa em paralelo dois `null_resource` — um grava `versao_us` em `us-east-1`, outro grava `versao_eu` em `eu-west-1` para o mesmo item. Um terceiro resource faz polling nas 3 regiões até convergência.

```bash
cd terraform/scenarios/cenario_c
terraform init
terraform apply -var-file=../../terraform.tfvars
```

**Resultados esperados:**
- Todas as rodadas convergem para um único valor
- Tempo de convergência: **< 2 000 ms**

---

## Dashboard

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
├── server.py                    # Flask API (backend do dashboard)
├── dashboard.html               # visualização em tempo real
├── terraform/
│   ├── main.tf                  # tabela + réplicas + GSIs (estado normal)
│   ├── variables.tf
│   ├── outputs.tf
│   ├── terraform.tfvars.example
│   └── scenarios/
│       ├── cenario_a/           # Cenário A: remove réplica → grava → restaura → convergência
│       │   ├── main.tf
│       │   └── variables.tf
│       ├── cenario_b/           # Cenário B: PROVISIONED 1WCU → throttle → retry → restaura
│       │   ├── main.tf
│       │   └── variables.tf
│       └── cenario_c/           # Cenário C: escritas paralelas LWW → polling convergência
│           ├── main.tf
│           └── variables.tf
├── scripts/
│   ├── utils.py
│   ├── 01_setup_table.py        # valida infraestrutura
│   ├── 02_seed_data.py          # popula dados de teste
│   └── 06_validate_recovery.py  # health check + latência de replicação
└── results/                     # JSONs de resultado (gerados)
```

---

## Como os cenários funcionam em Terraform

Cada cenário usa `null_resource` com `local-exec` e AWS CLI para executar todas as etapas. O Terraform gerencia a sequência via `depends_on`:

```
cenario_a:
  null_resource.remover_replica
       ↓ depends_on
  null_resource.gravar_durante_particao
       ↓ depends_on
  null_resource.restaurar_replica
       ↓ depends_on
  null_resource.medir_convergencia

cenario_b:
  null_resource.provisioned_mode
       ↓ depends_on
  null_resource.fase1_sem_retry
       ↓ depends_on
  null_resource.fase2_com_retry
       ↓ depends_on
  null_resource.restaurar_pay_per_request

cenario_c:
  null_resource.escrita_us  ──┐  (paralelo — sem depends_on entre si)
  null_resource.escrita_eu  ──┤
                              ↓ depends_on
              null_resource.medir_convergencia
```

---

## Referência

```
Vig, Nikhil et al. "Amazon DynamoDB: A Scalable, Predictably Performant,
and Fully Managed NoSQL Database Service."
USENIX Annual Technical Conference (ATC), 2022.
```
