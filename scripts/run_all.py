"""
Orquestrador — executa todos os cenários em sequência e exibe um resumo final.

Uso:
  cd scripts && python run_all.py
"""
import sys
import json
import subprocess
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.rule import Rule

console = Console()
SCRIPTS_DIR = Path(__file__).parent
RESULTS_DIR = SCRIPTS_DIR.parent / "results"

PASSOS = [
    ("01_setup_table.py",      None,                      "Validação de infraestrutura"),
    ("02_seed_data.py",        None,                      "Carga de dados de teste"),
    ("03_fault_region.py",     "03_fault_region.json",    "Cenário A — Falha de região"),
    ("04_fault_throttling.py", "04_fault_throttling.json","Cenário B — Throttling"),
    ("05_fault_conflict.py",   "05_fault_conflict.json",  "Cenário C — Conflito LWW"),
    ("06_validate_recovery.py","06_validate_recovery.json","Health check"),
]


def executar(script: str) -> tuple:
    resultado = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script)],
        capture_output=True, text=True, cwd=str(SCRIPTS_DIR),
    )
    return resultado.returncode == 0, resultado.stdout, resultado.stderr


def ler_json(arquivo: str) -> dict:
    caminho = RESULTS_DIR / arquivo
    if caminho and caminho.exists():
        try:
            return json.loads(caminho.read_text())
        except Exception:
            pass
    return {}


def detalhe_cenario(dados: dict) -> str:
    cenario = dados.get("cenario", "")
    if cenario == "A_fault_region":
        dispon = dados.get("disponibilidade_pct", "?")
        conv   = dados.get("convergencia", {}).get("elapsed_ms", "?")
        return f"disponib={dispon}% | convergência={conv}ms"
    if cenario == "B_throttling":
        sem = dados.get("sem_retry", {})
        com = dados.get("com_retry", {})
        return (f"sem retry throttle={sem.get('taxa_throttle_pct')}% | "
                f"com retry sucesso={com.get('taxa_sucesso_pct')}% em {com.get('elapsed_s')}s")
    if cenario == "C_conflict_lww":
        taxa = dados.get("convergencia_rate", "?")
        ps   = dados.get("latencia_convergencia_ms", {})
        return f"convergência={taxa} | p50={ps.get('p50')}ms p90={ps.get('p90')}ms"
    return ""


if __name__ == "__main__":
    console.print(Panel(
        "[bold]DynamoDB Fault Tolerance Lab[/]\n"
        "Ref: Amazon DynamoDB — USENIX ATC 2022\n"
        "3 cenários: disponibilidade · throttling · last-write-wins",
        expand=False,
    ))

    execucoes = []
    for script, arquivo_resultado, descricao in PASSOS:
        console.print(Rule(f"[bold]{descricao}[/]"))
        ok, stdout, stderr = executar(script)
        if stdout:
            console.print(stdout, end="")
        if stderr and not ok:
            console.print(f"[red]{stderr}[/]", end="")
        execucoes.append((script, descricao, ok, arquivo_resultado))

    # ── Resumo final ─────────────────────────────────────────────────────────
    console.print(Rule("[bold]Resumo Final[/]"))
    tabela = Table(title="Resultados dos Cenários", show_lines=True)
    tabela.add_column("Script",    min_width=28)
    tabela.add_column("Descrição", min_width=30)
    tabela.add_column("Status",    min_width=10)
    tabela.add_column("Detalhe",   min_width=50)

    todos_ok = True
    for script, descricao, ok, arquivo in execucoes:
        status_str = "[green]OK[/]" if ok else "[red]ERRO[/]"
        if not ok:
            todos_ok = False
        dados = ler_json(arquivo) if arquivo else {}
        det = detalhe_cenario(dados)
        tabela.add_row(script, descricao, status_str, det)

    console.print(tabela)
    console.print()

    if todos_ok:
        console.print("[bold green]Todos os cenários concluídos com sucesso.[/]")
    else:
        console.print("[bold red]Um ou mais cenários falharam — verifique os logs acima.[/]")
        sys.exit(1)
