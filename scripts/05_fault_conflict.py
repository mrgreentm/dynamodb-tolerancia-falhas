"""
Cenário C — Conflito de Escrita / Last-Write-Wins (USENIX ATC 2022, §3.4)

Demonstra a resolução de conflitos do DynamoDB Global Tables.
Escritas simultâneas para o mesmo item em regiões distintas são resolvidas
pelo timestamp interno do servidor (não pelo clock da aplicação): a escrita
com o timestamp mais recente prevalece em todas as réplicas após convergência.

Fluxo por rodada:
  1. Grava "versao_us" em us-east-1 e "versao_eu" em eu-west-1 simultaneamente (threads)
  2. Faz polling em todas as 3 regiões a cada 100ms
  3. Registra o tempo até todas as regiões exibirem o mesmo valor (convergência)

Métricas:
  - Taxa de convergência (esperado: 100% das rodadas)
  - Tempo de convergência p50 / p90 (esperado: < 2000 ms)
  - Valor vencedor por rodada (não-determinístico — depende de qual chegou por último)
"""
import uuid
import time
import threading
from dotenv import load_dotenv
from rich.panel import Panel
from rich.table import Table
from utils import (
    console, get_table, salvar_resultado, ts_utc, percentis,
)

load_dotenv()

TABELA = "Pedidos"
REGIOES = ["sa-east-1", "us-east-1", "eu-west-1"]
N_RODADAS = 5
TIMEOUT_S = 30       # segundos máximos aguardando convergência
POLL_MS   = 100      # intervalo de polling em ms


# ── Helpers ───────────────────────────────────────────────────────────────────

def _gravar(regiao: str, pedido_id: str, criado_em: str, valor: str, saida: dict) -> None:
    t0 = time.perf_counter()
    get_table(regiao).put_item(Item={
        "pedido_id":     pedido_id,
        "criado_em":     criado_em,
        "valor":         valor,
        "ts_aplicacao":  ts_utc(),
        "origem_regiao": regiao,
    })
    saida[regiao] = {"valor": valor, "latencia_ms": round((time.perf_counter() - t0) * 1000, 1)}


def _polling_convergencia(pedido_id: str, criado_em: str) -> dict:
    """Retorna quando todas as regiões leem o mesmo valor (ou timeout)."""
    inicio = time.perf_counter()
    while True:
        elapsed = time.perf_counter() - inicio
        if elapsed > TIMEOUT_S:
            return {"convergiu": False, "elapsed_ms": round(elapsed * 1000)}

        leituras = {}
        for regiao in REGIOES:
            resp = get_table(regiao).get_item(
                Key={"pedido_id": pedido_id, "criado_em": criado_em},
                ConsistentRead=False,
            )
            leituras[regiao] = resp.get("Item", {}).get("valor")

        valores_presentes = {v for v in leituras.values() if v is not None}
        todas_leram = all(v is not None for v in leituras.values())

        if todas_leram and len(valores_presentes) == 1:
            return {
                "convergiu":   True,
                "elapsed_ms":  round((time.perf_counter() - inicio) * 1000),
                "valor_final": next(iter(valores_presentes)),
                "leituras":    leituras,
            }

        time.sleep(POLL_MS / 1000)


# ── Rodada individual ─────────────────────────────────────────────────────────

def rodada(n: int) -> dict:
    pedido_id = f"CONFLICT-{n:02d}-{uuid.uuid4().hex[:6].upper()}"
    criado_em = ts_utc()

    escritas: dict = {}
    t_us = threading.Thread(target=_gravar, args=("us-east-1", pedido_id, criado_em, "versao_us", escritas))
    t_eu = threading.Thread(target=_gravar, args=("eu-west-1", pedido_id, criado_em, "versao_eu", escritas))

    t_us.start()
    t_eu.start()
    t_us.join()
    t_eu.join()

    lat_us = escritas.get("us-east-1", {}).get("latencia_ms", "?")
    lat_eu = escritas.get("eu-west-1", {}).get("latencia_ms", "?")
    console.print(f"  Rodada {n}: us={lat_us}ms eu={lat_eu}ms", end=" | ")

    conv = _polling_convergencia(pedido_id, criado_em)

    if conv["convergiu"]:
        console.print(f"convergência em [yellow]{conv['elapsed_ms']} ms[/] → [bold]{conv['valor_final']}[/]")
    else:
        console.print(f"[red]SEM convergência em {TIMEOUT_S}s[/]")

    return {"rodada": n, "pedido_id": pedido_id, "escritas": escritas, **conv}


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    console.print(Panel(
        "[bold]Cenário C — Conflito de Escrita (Last-Write-Wins)[/]\nRef: USENIX ATC 2022, §3.4",
        expand=False,
    ))

    resultado = {"cenario": "C_conflict_lww", "inicio": ts_utc(), "rodadas": []}

    console.print(f"\nExecutando {N_RODADAS} rodadas de conflito simultâneo (poll a cada {POLL_MS}ms)...\n")
    for i in range(1, N_RODADAS + 1):
        resultado["rodadas"].append(rodada(i))

    # Estatísticas
    convergidas = [r for r in resultado["rodadas"] if r.get("convergiu")]
    tempos = [r["elapsed_ms"] for r in convergidas]
    ps = percentis(tempos) if tempos else {}

    vencedores = {}
    for r in convergidas:
        v = r.get("valor_final", "?")
        vencedores[v] = vencedores.get(v, 0) + 1

    resultado["convergencia_rate"] = f"{len(convergidas)}/{N_RODADAS}"
    resultado["latencia_convergencia_ms"] = ps
    resultado["vencedores"] = vencedores
    resultado["fim"] = ts_utc()

    salvar_resultado("05_fault_conflict.json", resultado)

    tabela = Table(title="Resumo — Conflito LWW")
    tabela.add_column("Métrica")
    tabela.add_column("Valor")
    tabela.add_row("Rodadas com convergência", resultado["convergencia_rate"])
    tabela.add_row("Tempo p50",  f"{ps.get('p50')} ms")
    tabela.add_row("Tempo p90",  f"{ps.get('p90')} ms")
    for valor, cnt in vencedores.items():
        tabela.add_row(f"Vencedor: {valor}", str(cnt))
    console.print(tabela)

    passou = len(convergidas) == N_RODADAS
    console.print(f"\n[bold]Resultado:[/] {'[green]PASSOU[/]' if passou else '[red]FALHOU[/]'}")
    console.print("  Nota: o valor vencedor é não-determinístico (depende de latência de rede interna da AWS).")
