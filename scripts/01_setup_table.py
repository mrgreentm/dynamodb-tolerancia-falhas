"""
Valida que a tabela Pedidos está ACTIVE nas 3 regiões com seus GSIs.
A tabela deve ter sido criada previamente pelo Terraform.

Uso:
  cd terraform && terraform apply
  cd ../scripts && python 01_setup_table.py
"""
from dotenv import load_dotenv
from rich.table import Table
from rich.panel import Panel
from utils import console, REGIOES, TABELA, status_tabela

load_dotenv()


def verificar():
    console.print(Panel("[bold]Setup — Validação de Infraestrutura[/]", expand=False))

    tabela = Table(title=f"Tabela: {TABELA}")
    tabela.add_column("Região")
    tabela.add_column("Status")
    tabela.add_column("Itens")
    tabela.add_column("GSIs")
    tabela.add_column("Réplicas")

    tudo_ok = True
    for regiao in REGIOES:
        info = status_tabela(regiao)
        ok = info["status"] == "ACTIVE"
        if not ok:
            tudo_ok = False

        status_str = f"[green]{info['status']}[/]" if ok else f"[red]{info['status']}[/]"
        gsis = ", ".join(g["nome"].split("-")[0] for g in info.get("gsis", []))
        replicas = ", ".join(r["regiao"] for r in info.get("replicas", []))
        tabela.add_row(regiao, status_str, str(info.get("itens", "N/A")), gsis or "—", replicas or "—")

    console.print(tabela)

    if tudo_ok:
        console.print("[green]✓[/] Tabela ACTIVE nas 3 regiões.")
    else:
        console.print("[yellow]⚠[/] Alguma região não está ACTIVE — aguarde ou execute terraform apply.")

    return tudo_ok


if __name__ == "__main__":
    verificar()
