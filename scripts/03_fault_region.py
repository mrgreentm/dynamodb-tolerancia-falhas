"""
Cenário A — Falha de Região (USENIX ATC 2022, §5 — Availability)

Demonstra que o DynamoDB mantém disponibilidade de escrita mesmo durante
a indisponibilidade simulada de uma réplica regional.

Fluxo:
  1. Remove réplica eu-west-1 (simula partição de rede)
  2. Continua gravando em us-east-1 durante a "falha" — espera 100% de sucesso
  3. Restaura eu-west-1 e aguarda ficar ACTIVE
  4. Mede o tempo até todos os itens escritos durante a partição aparecerem em eu-west-1

Métricas:
  - Disponibilidade de escrita durante partição (esperado: 100%)
  - Tempo de convergência pós-recovery (esperado: < 30 s)
"""
import uuid
import time
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from rich.panel import Panel
from utils import (
    console, get_client, get_table,
    aguardar_replicas, salvar_resultado, ts_utc,
)

load_dotenv()

TABELA = "Pedidos"
REGIAO_ATIVA = "us-east-1"
REGIAO_FALHA = "eu-west-1"
N_ESCRITAS = 20  # itens gravados durante a partição


# ── Helpers ───────────────────────────────────────────────────────────────────

def _replicas_ativas(regiao: str) -> set:
    resp = get_client(regiao).describe_table(TableName=TABELA)
    return {r["RegionName"] for r in resp["Table"].get("Replicas", [])}


# ── Etapas ────────────────────────────────────────────────────────────────────

def remover_replica() -> None:
    console.print(f"\n[bold red]● FAULT[/] Removendo réplica de {REGIAO_FALHA}...")
    get_client(REGIAO_ATIVA).update_table(
        TableName=TABELA,
        ReplicaUpdates=[{"Delete": {"RegionName": REGIAO_FALHA}}],
    )
    with console.status(f"Aguardando remoção de {REGIAO_FALHA}..."):
        for _ in range(60):
            if REGIAO_FALHA not in _replicas_ativas(REGIAO_ATIVA):
                console.print(f"  [green]✓[/] Réplica de {REGIAO_FALHA} removida.")
                return
            time.sleep(5)
    console.print("  [yellow]⚠[/] Remoção pode ainda estar em andamento.")


def gravar_durante_particao() -> dict:
    """
    Grava N_ESCRITAS itens em REGIAO_ATIVA.
    A disponibilidade deve ser 100% pois eu-west-1 não faz parte do quórum.
    """
    console.print(f"\n[bold yellow]▶ PARTIÇÃO[/] Gravando {N_ESCRITAS} itens em {REGIAO_ATIVA}...")
    tabela = get_table(REGIAO_ATIVA)
    itens_escritos = []
    sucessos = 0
    erros = 0

    for i in range(N_ESCRITAS):
        pedido_id = f"FALHA-{uuid.uuid4().hex[:8].upper()}"
        ts = ts_utc()
        try:
            tabela.put_item(Item={
                "pedido_id":     pedido_id,
                "criado_em":     ts,
                "status":        "criado_durante_particao",
                "origem_regiao": REGIAO_ATIVA,
                "seq":           i,
            })
            itens_escritos.append({"pedido_id": pedido_id, "criado_em": ts})
            sucessos += 1
        except ClientError as e:
            erros += 1
            console.print(f"  [red]✗[/] Erro {i}: {e.response['Error']['Code']}")

    disponibilidade = sucessos / N_ESCRITAS * 100
    cor = "green" if disponibilidade == 100 else "red"
    console.print(f"  [{cor}]Disponibilidade: {disponibilidade:.0f}%[/] ({sucessos}/{N_ESCRITAS} escritas bem-sucedidas)")
    return {
        "itens_escritos": itens_escritos,
        "sucessos": sucessos,
        "erros": erros,
        "disponibilidade_pct": round(disponibilidade, 1),
    }


def restaurar_replica() -> None:
    console.print(f"\n[bold green]● RECOVERY[/] Restaurando réplica em {REGIAO_FALHA}...")
    get_client(REGIAO_ATIVA).update_table(
        TableName=TABELA,
        ReplicaUpdates=[{"Create": {"RegionName": REGIAO_FALHA}}],
    )
    aguardar_replicas([REGIAO_FALHA])
    console.print(f"  [green]✓[/] Réplica de {REGIAO_FALHA} restaurada e ACTIVE.")


def medir_convergencia(itens: list) -> dict:
    """
    Faz polling em eu-west-1 até que todos os itens escritos durante a partição
    sejam visíveis. Mede o tempo total de convergência.
    """
    console.print(f"\n[bold blue]▶ CONVERGÊNCIA[/] Verificando replicação de {len(itens)} itens em {REGIAO_FALHA}...")
    tabela_eu = get_table(REGIAO_FALHA)
    inicio = time.perf_counter()
    timeout = 120

    while True:
        elapsed = time.perf_counter() - inicio
        if elapsed > timeout:
            console.print(f"  [red]✗[/] Timeout após {timeout}s — convergência não atingida.")
            return {"convergiu": False, "elapsed_s": round(elapsed, 1)}

        encontrados = sum(
            1 for item in itens
            if tabela_eu.get_item(
                Key={"pedido_id": item["pedido_id"], "criado_em": item["criado_em"]},
                ConsistentRead=False,
            ).get("Item")
        )

        if encontrados == len(itens):
            elapsed_ms = round((time.perf_counter() - inicio) * 1000)
            console.print(f"  [green]✓[/] Todos os {len(itens)} itens replicados em {elapsed_ms} ms.")
            return {"convergiu": True, "elapsed_ms": elapsed_ms, "itens_replicados": encontrados}

        pct = encontrados / len(itens) * 100
        console.print(f"  ... {encontrados}/{len(itens)} ({pct:.0f}%) — {elapsed:.0f}s", end="\r")
        time.sleep(2)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    console.print(Panel(
        "[bold]Cenário A — Falha de Região[/]\nRef: USENIX ATC 2022, §5 — Availability",
        expand=False,
    ))

    resultado = {"cenario": "A_fault_region", "inicio": ts_utc()}

    remover_replica()
    resultado["replica_removida_em"] = ts_utc()

    dados_particao = gravar_durante_particao()
    resultado.update({k: v for k, v in dados_particao.items() if k != "itens_escritos"})
    resultado["itens_escritos"] = dados_particao["itens_escritos"]
    resultado["particao_fim_em"] = ts_utc()

    restaurar_replica()
    resultado["replica_restaurada_em"] = ts_utc()

    convergencia = medir_convergencia(dados_particao["itens_escritos"])
    resultado["convergencia"] = convergencia
    resultado["fim"] = ts_utc()

    salvar_resultado("03_fault_region.json", resultado)

    passou = dados_particao["disponibilidade_pct"] == 100.0 and convergencia.get("convergiu", False)
    console.print(f"\n[bold]Resultado:[/] {'[green]PASSOU[/]' if passou else '[red]FALHOU[/]'}")
    console.print(f"  • Disponibilidade durante partição: {dados_particao['disponibilidade_pct']}%")
    if convergencia.get("convergiu"):
        console.print(f"  • Convergência pós-recovery: {convergencia['elapsed_ms']} ms")
