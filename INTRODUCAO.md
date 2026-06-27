# Conceitos Fundamentais — Sistemas Distribuídos

> **Duração estimada de leitura:** 10 minutos  
> **Paper de referência:** *Amazon DynamoDB: A Scalable, Predictably Performant, and Fully Managed NoSQL Database Service* — USENIX ATC 2022

Este documento apresenta os conceitos teóricos necessários para compreender o laboratório experimental que será demonstrado. Cada secção introduz uma ideia que aparecerá concretamente nos três cenários de fault tolerance.

---

## 1. O Problema Central dos Sistemas Distribuídos

Um sistema distribuído é um conjunto de computadores independentes que, do ponto de vista do utilizador, se comportam como um único sistema coerente. O desafio fundamental não é fazer os nós comunicarem — é fazê-los **concordar** quando algo corre mal.

Imagine uma base de dados replicada em três datacenters: São Paulo, Virginia e Irlanda. Quando um cliente escreve um pedido em São Paulo, o que acontece se a ligação para a Irlanda cair nesse momento? O sistema tem três opções:

1. **Recusar a escrita** até a ligação ser restaurada (prioriza consistência, perde disponibilidade)
2. **Aceitar a escrita** e sincronizar a Irlanda mais tarde (prioriza disponibilidade, aceita inconsistência temporária)
3. **Fingir que o problema não existe** (comportamento indefinido — a pior opção)

O DynamoDB escolhe explicitamente a opção 2. Perceber *porquê* e *o que isso implica* é o objectivo deste laboratório.

---

## 2. O Teorema CAP

O **Teorema CAP**, formulado por Eric Brewer em 2000 e provado formalmente por Gilbert e Lynch em 2002, afirma que qualquer sistema distribuído com replicação de dados pode garantir **no máximo duas** das três propriedades seguintes em simultâneo:

```
          Consistência (C)
              /\
             /  \
            /    \
           /      \
          /________\
Disponibilidade (A)  Tolerância a Partições (P)
```

### Consistência (C — Consistency)
Todos os nós do sistema veem **exactamente os mesmos dados ao mesmo tempo**. Depois de uma escrita ser confirmada, qualquer leitura subsequente — em qualquer nó — devolve o valor actualizado. Não há versões antigas à solta.

### Disponibilidade (A — Availability)
O sistema **responde sempre** às requisições, mesmo que alguns nós estejam em falha. Não há timeouts nem erros de indisponibilidade do sistema em si (pode haver erros de negócio, como "item não encontrado").

### Tolerância a Partições (P — Partition Tolerance)
O sistema **continua a funcionar** mesmo quando a rede entre nós falha e os nós ficam temporariamente incomunicáveis entre si (partição de rede).

### A escolha inevitável

Em qualquer sistema distribuído que opere na internet, as partições de rede são uma realidade, não uma hipótese. Cabos cortam-se, routers falham, datacenters perdem conectividade. Por isso, **P não é opcional** — qualquer sistema real tem de tolerar partições.

O que significa é que a escolha real é entre **CP** e **AP**:

| Sistema | Escolha | Comportamento numa partição |
|---------|---------|------------------------------|
| HBase, Zookeeper | CP | Recusa pedidos até a partição se resolver |
| Cassandra, DynamoDB | AP | Aceita pedidos, sincroniza depois |
| PostgreSQL standalone | CA | Não se aplica — não há replicação distribuída |

> **O DynamoDB é um sistema AP.** Esta é a decisão de design mais importante do paper, e cada um dos três cenários do laboratório demonstra uma consequência prática desta escolha.

---

## 3. Consistência Eventual

A **consistência eventual** (*eventual consistency*) é o modelo de consistência adoptado por sistemas AP. A garantia é simples:

> Se nenhuma nova escrita ocorrer, eventualmente todos os nós convergirão para o mesmo valor.

Não há garantia de *quando* isso acontece — pode ser em milissegundos ou em segundos — mas acontece sempre. O sistema não perde dados: adia a sincronização.

### Consistência forte vs. eventual na prática

```
Consistência Forte (CP):
  Cliente A escreve "status=entregue" → sistema bloqueia até todos os nós confirmarem
  Cliente B lê de qualquer nó         → garante ver "status=entregue"
  Custo: latência alta, indisponível durante partição

Consistência Eventual (AP):
  Cliente A escreve "status=entregue" em sa-east-1 → confirmação imediata
  Replicação para us-east-1 e eu-west-1 ocorre em background (ms a segundos)
  Cliente B lê de eu-west-1 imediatamente → pode ver o valor anterior ainda
  Custo: janela de inconsistência, mas sempre disponível
```

O DynamoDB permite ao cliente escolher por leitura: **eventually consistent reads** (padrão, mais barato) ou **strongly consistent reads** (mais caro, só funciona na região primária).

---

## 4. Replicação Assíncrona e Global Tables

O mecanismo que concretiza a consistência eventual no DynamoDB são as **Global Tables**: uma tabela que existe simultaneamente em múltiplas regiões AWS, cada uma sendo uma réplica completa e aceitando tanto leituras como escritas.

### Como funciona a replicação

```
Escrita em sa-east-1:
  1. Cliente → put_item("pedido_123", status="pago") → sa-east-1
  2. sa-east-1 confirma ao cliente [t=0ms]
  3. DynamoDB propaga o item para us-east-1 e eu-west-1 em background
  4. us-east-1 recebe e aplica o item [t~50-200ms]
  5. eu-west-1 recebe e aplica o item [t~100-300ms]
```

A confirmação ao cliente acontece **antes** da replicação completar. Isto é o que torna o sistema disponível e rápido — e é também o que cria a janela de inconsistência.

### Multi-Paxos por partição

Internamente, cada partição de dados do DynamoDB usa uma variante do algoritmo **Multi-Paxos** para coordenar as réplicas locais dentro de uma região. O paper (§5) descreve como a eleição de líder e a replicação de log de operações garantem durabilidade sem sacrificar disponibilidade. Quando uma réplica falha, as outras continuam a operar sem necessidade de eleição global.

---

## 5. Resolução de Conflitos — Last-Write-Wins

Com escritas aceites em múltiplas regiões simultaneamente, surge inevitavelmente a questão: **o que acontece se dois clientes escrevem o mesmo item em regiões diferentes ao mesmo tempo?**

O DynamoDB resolve conflitos com a estratégia **Last-Write-Wins (LWW)** baseada em timestamps internos do servidor.

### Como o LWW funciona

```
t=0ms: Cliente A escreve pedido_123 → us-east-1  (valor: "versao_us")
t=5ms: Cliente B escreve pedido_123 → eu-west-1  (valor: "versao_eu")

us-east-1 e eu-west-1 trocam os dois writes durante a replicação.
DynamoDB compara os timestamps internos de cada escrita:
  → a escrita com timestamp mais recente vence e substitui a outra
  → todas as réplicas convergem para o mesmo vencedor
```

### Propriedades do LWW

**Garante:** convergência — todas as réplicas acabam com o mesmo valor.  
**Não garante:** qual das versões conflituantes vence — o resultado é não-determinístico do ponto de vista da aplicação.

**Ponto crítico:** o DynamoDB usa o *seu próprio relógio interno*, não o relógio do cliente. Isto protege contra clocks dessincronizados nas máquinas que fazem as escritas.

### Quando o LWW não é suficiente

O LWW funciona bem para operações comutativas: actualizar um status, registar um evento, sobrescrever uma configuração. Falha para operações onde a **ordem importa**:

- Transferências bancárias (débito + crédito devem ser atómicos)
- Inventário (dois clientes a comprar o último item em stock)
- Qualquer operação que dependa de ler-e-modificar atomicamente

Para estes casos, o DynamoDB oferece **transações ACID** com coordenação multi-região — mas ao custo de maior latência e complexidade.

---

## 6. Admission Control e Throttling

Disponibilidade não significa capacidade ilimitada. O DynamoDB implementa **admission control** — mecanismos que protegem o sistema de sobrecarga aceitando apenas o tráfego que consegue processar.

### Capacidade provisionada vs. Pay-per-request

O DynamoDB opera em dois modos:

| Modo | Comportamento | Custo |
|------|--------------|-------|
| **PAY_PER_REQUEST** | Escala automaticamente, sem limites explícitos | Por operação |
| **PROVISIONED** | Capacidade fixa em WCUs/RCUs definida pelo utilizador | Por capacidade reservada |

**WCU (Write Capacity Unit):** capacidade para escrever 1 item de até 1 KB por segundo.

### O que acontece quando o limite é excedido

Em modo PROVISIONED, quando o ritmo de escritas ultrapassa a capacidade configurada, o DynamoDB devolve a excepção:

```
ProvisionedThroughputExceededException
```

Esta é uma decisão de design deliberada: **o sistema rejeita explicitamente em vez de degradar silenciosamente**. O §4 do paper descreve isto como "predictable performance under overload" — o comportamento em sobrecarga é previsível e tratável.

### Backoff Exponencial

A resposta correcta a um throttle é o **backoff exponencial com jitter**: o cliente aguarda um tempo crescente entre tentativas, adicionando aleatoriedade para evitar que múltiplos clientes se sincronizem e criem picos.

```
Tentativa 1: falha → aguarda 100ms
Tentativa 2: falha → aguarda 200ms + jitter aleatório
Tentativa 3: falha → aguarda 400ms + jitter aleatório
Tentativa 4: sucesso ✓
```

O SDK boto3 (Python) implementa isto automaticamente em modo adaptativo. Um cliente *sem* retry programado perde as escritas; um cliente *com* backoff exponencial consegue 100% de sucesso — apenas mais devagar.

---

## 7. Tolerância a Falhas e Alta Disponibilidade

A **tolerância a falhas** é a capacidade de um sistema continuar a operar correctamente quando componentes individuais falham. No contexto de bases de dados distribuídas, o objectivo é que a falha de uma réplica não torne os dados inacessíveis.

### O que o DynamoDB garante durante uma falha de região

Quando uma réplica inteira (ex.: `eu-west-1`) fica inacessível:

1. As restantes regiões (`sa-east-1`, `us-east-1`) **continuam a aceitar leituras e escritas** — sem interrupção.
2. Os dados escritos durante a partição são **persistidos localmente** e **replicados quando a réplica voltar**.
3. Quando `eu-west-1` é restaurada, o DynamoDB **sincroniza automaticamente** todos os dados escritos durante a sua ausência.

Este comportamento é o que o §5 do paper chama de **high availability** — a propriedade A do teorema CAP em acção.

### Convergência pós-falha

O tempo entre a restauração de uma réplica e o momento em que ela tem todos os dados actualizados chama-se **tempo de convergência**. No DynamoDB, este valor é tipicamente inferior a 30 segundos para volumes moderados de dados.

---

## 8. Para Além do CAP — O Modelo PACELC

O teorema CAP captura uma trade-off importante, mas é incompleto: só descreve o que acontece *durante* uma partição. O modelo **PACELC** (2012, Daniel Abadi) estende esta análise:

```
Se Partição (P): escolhe entre Availability (A) e Consistency (C)
Else (E — sem partição): escolhe entre Latency (L) e Consistency (C)
```

O DynamoDB é classificado como **PA/EL**: em partição escolhe disponibilidade; em operação normal, escolhe baixa latência em vez de consistência forte. Esta segunda dimensão é relevante: mesmo sem falhas, a replicação assíncrona introduz uma janela de inconsistência porque confirmar ao cliente *antes* de replicar é mais rápido do que esperar pela confirmação de todas as réplicas.

---

## Resumo dos Conceitos e sua Conexão ao Laboratório

| Conceito | Demonstrado no |
|----------|---------------|
| Teorema CAP — escolha AP | Todos os cenários (premissa do sistema) |
| Consistência eventual + convergência | Cenário A (falha de região) e Cenário C (conflito LWW) |
| Replicação assíncrona multi-região | Cenário A — medição do tempo de convergência pós-recovery |
| Last-Write-Wins | Cenário C — escrita simultânea em duas regiões, valor não-determinístico |
| Admission control e throttling | Cenário B — `ProvisionedThroughputExceededException` com 1 WCU |
| Backoff exponencial | Cenário B — comparação sem retry (falhas) vs. com retry (100% sucesso) |
| Alta disponibilidade durante partição | Cenário A — 100% de escritas aceites com réplica removida |

---

## Referência Bibliográfica

```
Vig, Nikhil; Jain, Akshat; Wagle, Samir; et al.
"Amazon DynamoDB: A Scalable, Predictably Performant, and
Fully Managed NoSQL Database Service."
USENIX Annual Technical Conference (ATC), 2022.

Brewer, Eric. "Towards Robust Distributed Systems." PODC Keynote, 2000.
Gilbert, Seth; Lynch, Nancy. "Brewer's Conjecture and the Feasibility of
Consistent, Available, Partition-Tolerant Web Services." ACM SIGACT, 2002.
Abadi, Daniel. "Consistency Tradeoffs in Modern Distributed Database System Design." IEEE Computer, 2012.
```
