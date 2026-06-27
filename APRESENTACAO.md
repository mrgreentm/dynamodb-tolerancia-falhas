# Roteiro de Apresentação — DynamoDB Fault Tolerance Lab

**Trabalho:** Sistemas Distribuídos — USENIX ATC 2022  
**Duração total:** 30 minutos  
**Paper base:** *Amazon DynamoDB: A Scalable, Predictably Performant, and Fully Managed NoSQL Database Service* (USENIX ATC 2022)

---

## Preparação antes da apresentação

Execute estes comandos com pelo menos 10 minutos de antecedência:

```bash
# 1. Subir a infraestrutura base AWS
cd terraform
terraform init
terraform apply -auto-approve

# 2. Inicializar os cenários (só na primeira vez)
cd scenarios/cenario_a && terraform init
cd ../cenario_b       && terraform init
cd ../cenario_c       && terraform init
cd ../../..

# 3. Popular a tabela
pip install -r requirements.txt
python3 scripts/01_setup_table.py   # valida que as 3 regiões estão ACTIVE
python3 scripts/02_seed_data.py     # insere 50 pedidos de teste

# 4. Subir o servidor Flask (backend do dashboard)
python3 server.py                   # roda em http://localhost:8080

# 5. Abrir o dashboard no navegador
open dashboard.html
```

Deixe o dashboard aberto no navegador e a tabela populada antes de começar.

---

## Roteiro (30 minutos)

---

### Bloco 1 — Introdução e Contexto (0–4 min)

**O que falar:**

> "O trabalho que vou apresentar implementa um laboratório experimental baseado no paper da Amazon publicado no USENIX ATC de 2022, que descreve como o DynamoDB garante alta disponibilidade em escala global."

**Ponto central a transmitir:** sistemas distribuídos precisam escolher entre consistência e disponibilidade. O DynamoDB faz essa escolha explicitamente — e este lab comprova isso com evidências mensuráveis.

**Conceito-chave para mencionar — Teorema CAP:**
- **C**onsistência: todos os nós veem os mesmos dados ao mesmo tempo
- **A**vailability: o sistema sempre responde às requisições
- **P**artition tolerance: o sistema continua funcionando mesmo com falha de rede entre nós

> "O DynamoDB opta por **AP** — disponibilidade e tolerância a partições — sacrificando consistência forte em favor de consistência eventual. Vamos demonstrar isso ao vivo."

---

### Bloco 2 — Arquitetura do Sistema (4–9 min)

**O que mostrar:** desenhe ou explique o diagrama abaixo no quadro ou nos slides.

```
┌─────────────────────────────────────────────────────────────┐
│               DynamoDB Global Table "Pedidos"               │
│                                                             │
│  ┌──────────────┐            ┌──────────────────────────┐  │
│  │  sa-east-1   │◄──────────►│       us-east-1          │  │
│  │  (primária)  │            └──────────────────────────┘  │
│  └──────────────┘                        ▲                  │
│         ▲                    replicação  │                  │
│         └──────────────────────────────►│                  │
│                                         ▼                  │
│                                  ┌──────────────┐          │
│                                  │  eu-west-1   │          │
│                                  └──────────────┘          │
└─────────────────────────────────────────────────────────────┘
              ▲
              │  REST API + CloudWatch
        ┌─────┴──────┐
        │  server.py │  Flask → localhost:8080
        └─────┬──────┘
              │
       ┌──────┴───────┐
       │ dashboard.html│  tempo real
       └──────────────┘
```

**Pontos a explicar:**

1. **Global Tables:** a tabela `Pedidos` existe simultaneamente em 3 regiões AWS (São Paulo, Virginia, Irlanda). Cada região é uma réplica completa, aceitando leituras e escritas.

2. **Replicação assíncrona:** quando você escreve em `sa-east-1`, o DynamoDB replica o dado para `us-east-1` e `eu-west-1` em segundo plano — não bloqueia a escrita original.

3. **Estrutura da tabela:**
   - Chave de partição: `pedido_id` (UUID)
   - Chave de ordenação: `criado_em` (timestamp ISO 8601)
   - 3 GSIs (por status, por cliente, por região de origem)
   - PITR (Point-In-Time Recovery) ativado

4. **O dashboard:** mostra status das 3 regiões, métricas do CloudWatch e permite executar os 3 cenários de fault tolerance ao vivo.

**Mostrar ao vivo:** abra o dashboard, aponte o status das 3 regiões como ACTIVE e o número de itens replicados igualmente nas 3.

---

### Bloco 3 — Cenário A: Falha de Região (9–16 min)

**Referência no paper:** §5 — Availability  
**Terraform:** `terraform/scenarios/cenario_a/`  
**Duração do teste:** ~5 min (inclui restaurar a réplica)

**O que falar antes de executar:**

> "O primeiro cenário simula o que acontece quando uma região inteira fica inacessível — uma partição de rede, uma falha catastrófica de datacenter. Vamos remover programaticamente a réplica da Irlanda (eu-west-1) e continuar gravando pedidos em Virginia. Depois medimos quanto tempo leva para os dados voltarem a ser visíveis na Irlanda."

**Executar no terminal:**

```bash
cd terraform/scenarios/cenario_a
terraform apply -var-file=../../terraform.tfvars -auto-approve
```

**O que acontece internamente (explicar enquanto roda):**

1. Remove a réplica `eu-west-1` da Global Table via API AWS
2. Grava 20 itens em `us-east-1` durante a "partição"
3. Restaura a réplica `eu-west-1` e aguarda ficar ACTIVE
4. Faz polling até todos os 20 itens aparecerem na Irlanda
5. Registra o tempo de convergência

**Resultados esperados a destacar:**

| Métrica | Valor esperado | O que prova |
|---------|---------------|-------------|
| Disponibilidade durante partição | **100%** | AP: sistema continua aceitando escritas |
| Tempo de convergência | **< 30 s** | Consistência eventual funciona |

**Conexão com o paper:**

> "O §5 do paper descreve como o DynamoDB usa replicação Multi-Paxos por partição de dados. Quando uma réplica cai, as outras continuam aceitando escritas sem interrupção. Ao voltar, a sincronização acontece automaticamente. Isso é o que acabamos de medir."

---

### Bloco 4 — Cenário B: Throttling e Admission Control (16–22 min)

**Referência no paper:** §4 — Durability and Correctness  
**Terraform:** `terraform/scenarios/cenario_b/`  
**Duração do teste:** ~3 min

**O que falar antes de executar:**

> "O segundo cenário mostra o que acontece quando tentamos sobrecarregar o banco. Vamos converter a tabela para capacidade provisionada mínima — 1 WCU (Write Capacity Unit) por segundo — e depois disparar 100 escritas simultâneas. Isso vai saturar completamente a capacidade."

**Executar no terminal:**

```bash
cd terraform/scenarios/cenario_b
terraform apply -var-file=../../terraform.tfvars -auto-approve
```

**O que acontece internamente (explicar enquanto roda):**

1. Converte tabela para `PROVISIONED` com **1 WCU** (cria gargalo intencional)
2. **Fase 1 — Sem retry:** 100 escritas concorrentes com 20 threads, sem retry automático  
   → A maioria recebe `ProvisionedThroughputExceededException`
3. **Fase 2 — Com retry adaptativo:** repete com `max_attempts=10` e modo adaptativo do boto3  
   → backoff exponencial absorve os throttles; todas as escritas completam
4. Restaura modo `PAY_PER_REQUEST`

**Resultados esperados a destacar:**

| Fase | Taxa de throttling | Taxa de sucesso | Tempo total |
|------|--------------------|-----------------|-------------|
| Sem retry | **70–95%** | 5–30% | ~1–2s |
| Com retry | **0%** | **100%** | ~5–15s (3–10× mais lento) |

**Conexão com o paper:**

> "O §4 descreve o admission control do DynamoDB. A propriedade fundamental é: o sistema não descarta dados silenciosamente — ele rejeita explicitamente com uma exceção tratável. O cliente que implementa backoff exponencial consegue 100% de sucesso, apenas mais devagar. O paper chama isso de 'predictable performance under overload'."

---

### Bloco 5 — Cenário C: Conflito Last-Write-Wins (22–27 min)

**Referência no paper:** §3.4 — Conflict Resolution  
**Terraform:** `terraform/scenarios/cenario_c/`  
**Duração do teste:** ~1 min (5 rodadas)

**O que falar antes de executar:**

> "O terceiro cenário é o mais sutil. Vamos escrever o mesmo item ao mesmo tempo em duas regiões diferentes — eu-west-1 e us-east-1 — com valores distintos. Qual versão vai vencer? Quem vai decidir?"

**Executar no terminal:**

```bash
cd terraform/scenarios/cenario_c
terraform apply -var-file=../../terraform.tfvars -auto-approve
```

**O que acontece internamente (explicar enquanto roda):**

1. Duas threads disparam `put_item` simultâneos para o mesmo `pedido_id`
   - Thread 1 → `us-east-1` com `valor = "versao_us"`
   - Thread 2 → `eu-west-1` com `valor = "versao_eu"`
2. Faz polling nas 3 regiões a cada 100ms até todas lerem o mesmo valor
3. Repete por 5 rodadas e coleta estatísticas

**Resultados esperados a destacar:**

| Métrica | Valor esperado | O que prova |
|---------|---------------|-------------|
| Taxa de convergência | **5/5 rodadas** | Conflitos sempre se resolvem |
| Tempo de convergência p50 | **200–800 ms** | Consistência eventual é rápida |
| Valor vencedor | **não-determinístico** | LWW por timestamp interno da AWS |

**Conexão com o paper:**

> "O §3.4 descreve que o DynamoDB usa Last-Write-Wins baseado no timestamp do servidor — não do cliente. Isso é crítico: o clock da aplicação pode estar errado, mas o DynamoDB usa seu próprio relógio interno para desempatar. O resultado converge, mas é não-determinístico — às vezes vence us, às vezes eu, dependendo de qual chegou por último na visão interna da AWS."

**Ponto polêmico para mencionar:**

> "LWW é simples e funciona bem para commutatividade (contadores, status de pedido). Para cenários onde a ordem de operações importa (como transferências bancárias), precisaríamos de consistência forte — o DynamoDB suporta isso com transações ACID, mas ao custo de coordenação multi-região mais cara."

---

### Bloco 6 — Conclusão e Encerramento (27–30 min)

**Resumo do que foi provado:**

| Propriedade | Como foi provada |
|-------------|-----------------|
| Alta disponibilidade (§5) | 100% de escritas durante remoção de réplica |
| Admission control (§4) | Throttling explícito + 100% de sucesso com backoff |
| Consistência eventual (§3.4) | Convergência em < 2s após conflito simultâneo |

**Frase de fechamento:**

> "O DynamoDB não é um banco de dados comum — é um sistema distribuído gerenciado que implementa décadas de pesquisa em consistência e disponibilidade. O paper do USENIX 2022 documenta isso. O que fizemos aqui foi operacionalizar esses conceitos em código executável, com métricas reais na infraestrutura da AWS. Cada cenário é uma verificação experimental de uma propriedade teórica descrita no paper."

**Deixar aberto para perguntas:**

- "Por que usar DynamoDB e não Cassandra ou CockroachDB para o mesmo fim?"
- "O teorema CAP é suficiente para modelar as trade-offs que vimos, ou precisamos do PACELC?"
- "Como o PITR (Point-In-Time Recovery) se integra com consistência eventual?"

---

## Estrutura de tempo (resumo visual)

```
00:00 ████ Introdução + CAP theorem               [4 min]
04:00 █████ Arquitetura + dashboard ao vivo        [5 min]
09:00 ███████ Cenário A: Falha de Região           [7 min]
16:00 ██████ Cenário B: Throttling                 [6 min]
22:00 █████ Cenário C: Conflito LWW                [5 min]
27:00 ███ Conclusão + perguntas                    [3 min]
30:00 ■ Fim
```

---

## Dicas práticas

- **Se o Cenário A demorar mais de 10 minutos:** a restauração da réplica pode levar mais tempo que o esperado. O Terraform aguarda até 6 minutos pelo status ACTIVE — mencione o timeout e mostre o output do terminal com o progresso.
- **Se o dashboard não mostrar métricas do CloudWatch:** o CloudWatch tem delay de ~5 minutos. Explique que as métricas são coletadas em janelas de 5 minutos por padrão.
- **Se a tabela não existir:** rode `terraform apply` antes. O estado atual (3 regiões com 0 recursos) indica que a infra foi destruída após o último uso.
- **Backup dos resultados:** após rodar os testes, os JSONs ficam em `results/`. Você pode mostrar resultados pré-salvos se a demo ao vivo falhar.

---

## Referência bibliográfica

```
Vig, Nikhil; Jain, Akshat; Wagle, Samir; et al.
"Amazon DynamoDB: A Scalable, Predictably Performant, and
Fully Managed NoSQL Database Service."
USENIX Annual Technical Conference (ATC), 2022.
```
