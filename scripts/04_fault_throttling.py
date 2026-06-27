"""
Cenário B — Throttling / Admission Control (USENIX ATC 2022, §4)

Pré-requisito: tabela deve estar em PROVISIONED 1 WCU via Terraform.
  cd terraform && terraform apply -var-file=scenarios/cenario_b.tfvars

Fluxo:
  1. Fase 1 — sem retry: 100 escritas concorrentes
     → evidencia throttling (ProvisionedThroughputExceededException)
  2. Fase 2 — com retry: repete com exponential backoff adaptativo
     → boto3 absorve os throttles; todas as escritas completam

Métricas:
  - Taxa de throttling sem retry (esperado: 70–95%)
  - Taxa de sucesso com retry   (esperado: 100%)
  - Overhead de latência do backoff

Pós-execução:
  Restaure PAY_PER_REQUEST:
    cd terraform && terraform apply
"""
import time
import boto3
import botocore.config
from concurrent.futures import ThreadPoolExecutor, as_completed
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from rich.panel import Panel
from rich.table import Table
from utils import (
    console, get_client, aguardar_tabela_ativa,
    salvar_resultado, ts_utc, percentis,
)

load_dotenv()

TABELA = "Pedidos"
REGIAO = "sa-east-1"
N_TOTAL = 100
N_WORKERS = 20


def _verificar_estado() -> None:
    """Confirma que a tabela está em PROVISIONED antes de medir."""
    resp = get_client(REGIAO).describe_table(TableName=TABELA)
    modo = resp["Table"].get("BillingModeSummary", {}).get("BillingMode", "PAY_PER_REQUEST")
    wcu = resp["Table"].get("ProvisionedThroughput", {}).get("WriteCapacityUnits", 0)
    if modo != "PROVISIONED" or wcu > 1:
        console.print(f"\n[yellow]⚠ AVISO:[/] Tabela está em modo {modo} (WCU={wcu}).")
        console.print("  Execute primeiro: [bold]cd terraform && terraform apply -var-file=scenarios/cenario_b.tfvars[/]")
        raise SystemExit(1)
    console.print(f"  [green]✓[/] Tabela em PROVISIONED {wcu} WCU — throttling esperado.")


def _tabela_com_config(cfg):
    return boto3.resource("dynamodb", region_name=REGIAO, config=cfg).Table(TABELA)


def _escrever(tabela, seq: int, prefixo: str) -> dict:
    pedido_id = f"{prefixo}-{seq:04d}"
    ts = f"2026-01-01T{seq // 3600:02d}:{(seq % 3600) // 60:02d}:{seq % 60:02d}+00:00"
    t0 = time.perf_counter()
    try:
        tabela.put_item(Item={
            "pedido_id":     pedido_id,
            "criado_em":     ts,
            "status":        "teste_throttle",
            "origem_regiao": REGIAO,
        })
        return {"ok": True, "latencia_ms": round((time.perf_counter() - t0) * 1000, 1)}
    except ClientError as e:
        codigo = e.response["Error"]["Code"]
        return {"ok": False, "codigo": codigo, "latencia_ms": round((time.perf_counter() - t0) * 1000, 1)}


def _executar_fase(tabela, prefixo: str, label: str) -> dict:
    resultados = []
    t_inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
        futuros = {ex.submit(_escrever, tabela, i, prefixo): i for i in range(N_TOTAL)}
        for f in as_completed(futuros):
            resultados.append(f.result())
    elapsed = round(time.perf_counter() - t_inicio, 2)

    sucessos  = [r for r in resultados if r["ok"]]
    throttled = [r for r in resultados if not r["ok"] and r.get("codigo") == "ProvisionedThroughputExceededException"]
    outros    = [r for r in resultados if not r["ok"] and r.get("codigo") != "ProvisionedThroughputExceededException"]
    latencias = [r["latencia_ms"] for r in resultados]
    ps = percentis(latencias)

    taxa_throttle = len(throttled) / N_TOTAL * 100
    taxa_sucesso  = len(sucessos)  / N_TOTAL * 100

    tabela_rich = Table(title=label, show_header=True)
    tabela_rich.add_column("Métrica")
    tabela_rich.add_column("Valor")
    tabela_rich.add_row("Total enviado",   str(N_TOTAL))
    tabela_rich.add_row("Sucessos",        f"[green]{len(sucessos)}[/] ({taxa_sucesso:.0f}%)")
    tabela_rich.add_row("Throttled",       f"[red]{len(throttled)}[/] ({taxa_throttle:.0f}%)")
    tabela_rich.add_row("Outros erros",    str(len(outros)))
    tabela_rich.add_row("Tempo total",     f"{elapsed}s")
    tabela_rich.add_row("Latência p50",    f"{ps['p50']} ms")
    tabela_rich.add_row("Latência p90",    f"{ps['p90']} ms")
    tabela_rich.add_row("Latência p99",    f"{ps['p99']} ms")
    console.print(tabela_rich)

    return {
        "total":             N_TOTAL,
        "sucessos":          len(sucessos),
        "throttled":         len(throttled),
        "outros_erros":      len(outros),
        "taxa_sucesso_pct":  round(taxa_sucesso, 1),
        "taxa_throttle_pct": round(taxa_throttle, 1),
        "elapsed_s":         elapsed,
        "latencia_ms":       ps,
    }


if __name__ == "__main__":
    console.print(Panel(
        "[bold]Cenário B — Throttling / Admission Control[/]\nRef: USENIX ATC 2022, §4\n"
        "[dim]Infraestrutura gerenciada por Terraform (cenario_b.tfvars)[/]",
        expand=False,
    ))

    _verificar_estado()

    resultado = {"cenario": "B_throttling", "inicio": ts_utc(), "n_escritas": N_TOTAL}

    # Terraform apply pode levar minutos, então burst capacity provavelmente já esgotou.
    # Sleep curto como margem de segurança.
    console.print("  Aguardando 5s (margem de segurança para burst capacity)...")
    time.sleep(5)

    console.print(f"\n[bold yellow]▶ FASE 1[/] Sem retry — {N_TOTAL} escritas concorrentes ({N_WORKERS} workers)")
    cfg_sem = botocore.config.Config(retries={"max_attempts": 1})
    resultado["sem_retry"] = _executar_fase(_tabela_com_config(cfg_sem), "T1", "Fase 1 — Sem Retry")

    time.sleep(3)

    console.print(f"\n[bold blue]▶ FASE 2[/] Com retry adaptativo — {N_TOTAL} escritas concorrentes ({N_WORKERS} workers)")
    cfg_com = botocore.config.Config(retries={"max_attempts": 10, "mode": "adaptive"})
    resultado["com_retry"] = _executar_fase(_tabela_com_config(cfg_com), "T2", "Fase 2 — Com Retry Adaptativo")

    resultado["fim"] = ts_utc()
    salvar_resultado("04_fault_throttling.json", resultado)

    sem = resultado["sem_retry"]
    com = resultado["com_retry"]
    passou = sem["throttled"] > 0 and com["taxa_sucesso_pct"] == 100.0
    console.print(f"\n[bold]Resultado:[/] {'[green]PASSOU[/]' if passou else '[yellow]PARCIAL[/]'}")
    console.print(f"  • Sem retry  → throttle: {sem['taxa_throttle_pct']}%  em {sem['elapsed_s']}s")
    console.print(f"  • Com retry  → sucesso:  {com['taxa_sucesso_pct']}%  em {com['elapsed_s']}s")
    fator = round(com["elapsed_s"] / sem["elapsed_s"], 1) if sem["elapsed_s"] > 0 else "N/A"
    console.print(f"  • Overhead do backoff:   {fator}× mais lento")

    console.print("\n[bold yellow]Próximo passo:[/]")
    console.print("  Restaure PAY_PER_REQUEST: [bold]cd terraform && terraform apply[/]")
