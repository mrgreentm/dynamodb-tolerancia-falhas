"""
Cenário A — Convergência pós-recovery (USENIX ATC 2022, §5)

Pré-requisito: eu-west-1 deve ter sido restaurada via Terraform.
  cd terraform && terraform apply

Carrega os itens gravados durante a partição (results/cenario_a_itens.json)
e faz polling em eu-west-1 até que todos apareçam, medindo o tempo de convergência.

Resultado esperado: todos os itens convergem em < 30 s.
"""
import time
import json
from pathlib import Path
from dotenv import load_dotenv
from rich.panel import Panel
from utils import (
    console, get_client, get_table,
    salvar_resultado, ts_utc,
)

load_dotenv()

TABELA = "Pedidos"
REGIAO_FALHA = "eu-west-1"
REGIAO_REF   = "us-east-1"
TIMEOUT_S    = 120
ITENS_FILE   = Path(__file__).parent.parent / "results" / "cenario_a_itens.json"


def _verificar_replica_ativa() -> None:
    resp = get_client(REGIAO_REF).describe_table(TableName=TABELA)
    replicas = {r["RegionName"] for r in resp["Table"].get("Replicas", [])}
    status = next(
        (r["ReplicaStatus"] for r in resp["Table"].get("Replicas", []) if r["RegionName"] == REGIAO_FALHA),
        None,
    )
    if REGIAO_FALHA not in replicas or status != "ACTIVE":
        console.print(f"\n[red]✗[/] Réplica {REGIAO_FALHA} não está ACTIVE (status={status}).")
        console.print("  Execute primeiro: [bold]cd terraform && terraform apply[/]")
        raise SystemExit(1)
    console.print(f"  [green]✓[/] Réplica {REGIAO_FALHA} está ACTIVE.")


def _carregar_itens() -> list:
    if not ITENS_FILE.exists():
        console.print(f"[red]✗[/] Arquivo não encontrado: {ITENS_FILE}")
        console.print("  Execute primeiro: [bold]python scripts/03_fault_region.py[/]")
        raise SystemExit(1)
    data = json.loads(ITENS_FILE.read_text())
    itens = data.get("itens", [])
    console.print(f"  [green]✓[/] {len(itens)} itens carregados de cenario_a_itens.json")
    return itens


def medir_convergencia(itens: list) -> dict:
    console.print(f"\n[bold blue]▶ CONVERGÊNCIA[/] Verificando {len(itens)} itens em {REGIAO_FALHA}...")
    tabela_eu = get_table(REGIAO_FALHA)
    inicio = time.perf_counter()

    while True:
        elapsed = time.perf_counter() - inicio
        if elapsed > TIMEOUT_S:
            console.print(f"  [red]✗[/] Timeout após {TIMEOUT_S}s — convergência não atingida.")
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


if __name__ == "__main__":
    console.print(Panel(
        "[bold]Cenário A — Convergência pós-recovery[/]\nRef: USENIX ATC 2022, §5 — Availability\n"
        "[dim]Infraestrutura restaurada por Terraform (terraform apply)[/]",
        expand=False,
    ))

    _verificar_replica_ativa()
    itens = _carregar_itens()

    resultado = {"cenario": "A_convergencia", "inicio": ts_utc()}
    convergencia = medir_convergencia(itens)
    resultado["convergencia"] = convergencia
    resultado["fim"] = ts_utc()

    salvar_resultado("03b_fault_convergencia.json", resultado)

    passou = convergencia.get("convergiu", False)
    console.print(f"\n[bold]Resultado:[/] {'[green]PASSOU[/]' if passou else '[red]FALHOU[/]'}")
    if convergencia.get("convergiu"):
        console.print(f"  • Convergência pós-recovery: {convergencia['elapsed_ms']} ms")
