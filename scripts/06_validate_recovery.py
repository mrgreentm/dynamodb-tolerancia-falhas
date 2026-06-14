"""
Health Check — Validação pós-cenários.

Verifica o estado global da tabela:
  - Status e contagem de itens por região
  - Status do PITR (Point-in-Time Recovery)
  - Latência de replicação entre regiões (com percentis)
"""
import uuid
import time
from dotenv import load_dotenv
from rich.panel import Panel
from rich.table import Table
from utils import (
    console, REGIOES, get_client, get_table,
    status_tabela, salvar_resultado, ts_utc, percentis,
)

load_dotenv()

TABELA = "Pedidos"
N_AMOSTRAS_LATENCIA = 5


def verificar_regioes() -> list:
    console.print("\n[bold]▶ Status das regiões[/]")
    resultados = []
    tabela = Table()
    tabela.add_column("Região")
    tabela.add_column("Status")
    tabela.add_column("Itens (aprox.)")
    tabela.add_column("Réplicas")

    for regiao in REGIOES:
        info = status_tabela(regiao)
        ok = info["status"] == "ACTIVE"
        status_str = f"[green]{info['status']}[/]" if ok else f"[red]{info['status']}[/]"
        replicas = ", ".join(f"{r['regiao']}({r['status']})" for r in info.get("replicas", []))
        tabela.add_row(regiao, status_str, str(info.get("itens", "N/A")), replicas or "—")
        resultados.append({"regiao": regiao, **info})

    console.print(tabela)
    return resultados


def verificar_pitr() -> list:
    console.print("\n[bold]▶ Point-in-Time Recovery (PITR)[/]")
    resultados = []
    tabela = Table()
    tabela.add_column("Região")
    tabela.add_column("PITR")
    tabela.add_column("Janela de restauração")

    for regiao in REGIOES:
        try:
            resp = get_client(regiao).describe_continuous_backups(TableName=TABELA)
            pitr = resp["ContinuousBackupsDescription"]["PointInTimeRecoveryDescription"]
            ativo = pitr["PointInTimeRecoveryStatus"] == "ENABLED"
            mais_cedo = pitr.get("EarliestRestorableDateTime", "N/A")
            mais_recente = pitr.get("LatestRestorableDateTime", "N/A")
            status_str = "[green]ENABLED[/]" if ativo else "[red]DISABLED[/]"
            tabela.add_row(regiao, status_str, f"{mais_cedo} → {mais_recente}")
            resultados.append({
                "regiao": regiao, "pitr": ativo,
                "earliest": str(mais_cedo), "latest": str(mais_recente),
            })
        except Exception as e:
            tabela.add_row(regiao, "[red]ERRO[/]", str(e))
            resultados.append({"regiao": regiao, "pitr": False, "detalhe": str(e)})

    console.print(tabela)
    return resultados


def medir_latencia_replicacao() -> list:
    """
    Grava N_AMOSTRAS_LATENCIA itens em us-east-1 e mede o tempo até
    cada um aparecer em sa-east-1 e eu-west-1 (polling a cada 50ms).
    """
    console.print(f"\n[bold]▶ Latência de replicação[/] ({N_AMOSTRAS_LATENCIA} amostras, polling 50ms)")
    destinos = ["sa-east-1", "eu-west-1"]
    tempos: dict = {d: [] for d in destinos}

    for amostra in range(N_AMOSTRAS_LATENCIA):
        pedido_id = f"LAT-{uuid.uuid4().hex[:8].upper()}"
        ts = ts_utc()
        get_table("us-east-1").put_item(Item={"pedido_id": pedido_id, "criado_em": ts, "marker": "latencia"})
        inicio = time.perf_counter()

        pendentes = set(destinos)
        while pendentes:
            elapsed = time.perf_counter() - inicio
            if elapsed > 10:
                for d in pendentes:
                    tempos[d].append(None)
                break
            for dest in list(pendentes):
                resp = get_table(dest).get_item(
                    Key={"pedido_id": pedido_id, "criado_em": ts},
                    ConsistentRead=False,
                )
                if resp.get("Item"):
                    tempos[dest].append(round(elapsed * 1000))
                    pendentes.discard(dest)
            if pendentes:
                time.sleep(0.05)

        console.print(f"  Amostra {amostra + 1}: {', '.join(f'{d}={tempos[d][-1]}ms' for d in destinos)}")

    tabela = Table(title="Latência us-east-1 → destino")
    tabela.add_column("Destino")
    tabela.add_column("p50 (ms)")
    tabela.add_column("p90 (ms)")
    tabela.add_column("p95 (ms)")

    resultados = []
    for dest in destinos:
        vals = [v for v in tempos[dest] if v is not None]
        ps = percentis(vals) if vals else {}
        tabela.add_row(dest, str(ps.get("p50")), str(ps.get("p90")), str(ps.get("p95")))
        resultados.append({"origem": "us-east-1", "destino": dest, "latencias_ms": tempos[dest], "percentis": ps})

    console.print(tabela)
    return resultados


if __name__ == "__main__":
    console.print(Panel("[bold]Health Check — Validação Pós-Cenários[/]", expand=False))

    relatorio = {"inicio": ts_utc()}
    relatorio["regioes"]             = verificar_regioes()
    relatorio["pitr"]                = verificar_pitr()
    relatorio["latencia_replicacao"] = medir_latencia_replicacao()
    relatorio["fim"] = ts_utc()

    caminho = salvar_resultado("06_validate_recovery.json", relatorio)
    console.print(f"\n[green]✓[/] Relatório salvo em: {caminho}")
