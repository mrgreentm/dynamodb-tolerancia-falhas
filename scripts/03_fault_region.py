"""
Cenário A — Falha de Região (USENIX ATC 2022, §5 — Availability)

Pré-requisito: eu-west-1 já deve estar removida via Terraform.
  cd terraform && terraform apply -var-file=scenarios/cenario_a.tfvars

Fluxo:
  1. Grava N_ESCRITAS itens em us-east-1 durante a "partição"
  2. Mede disponibilidade de escrita (esperado: 100%)
  3. Salva IDs dos itens em results/cenario_a_itens.json

Pós-execução:
  Restaure a réplica e meça convergência:
    cd terraform && terraform apply
    python scripts/03b_fault_convergencia.py
"""
import uuid
import time
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from rich.panel import Panel
from utils import (
    console, get_client, get_table,
    salvar_resultado, ts_utc,
)

load_dotenv()

TABELA = "Pedidos"
REGIAO_ATIVA = "us-east-1"
REGIAO_FALHA = "eu-west-1"
N_ESCRITAS = 20


def _verificar_estado() -> None:
    """Confirma que eu-west-1 não está entre as réplicas ativas."""
    resp = get_client(REGIAO_ATIVA).describe_table(TableName=TABELA)
    replicas = {r["RegionName"] for r in resp["Table"].get("Replicas", [])}
    if REGIAO_FALHA in replicas:
        console.print(f"\n[yellow]⚠ AVISO:[/] {REGIAO_FALHA} ainda está nas réplicas.")
        console.print(f"  Execute primeiro: [bold]cd terraform && terraform apply -var-file=scenarios/cenario_a.tfvars[/]")
        raise SystemExit(1)
    console.print(f"  [green]✓[/] Réplica {REGIAO_FALHA} ausente — partição ativa.")


def gravar_durante_particao() -> dict:
    """Grava N_ESCRITAS itens em REGIAO_ATIVA. Disponibilidade deve ser 100%."""
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


if __name__ == "__main__":
    console.print(Panel(
        "[bold]Cenário A — Falha de Região[/]\nRef: USENIX ATC 2022, §5 — Availability\n"
        "[dim]Infraestrutura gerenciada por Terraform (cenario_a.tfvars)[/]",
        expand=False,
    ))

    _verificar_estado()

    resultado = {"cenario": "A_fault_region", "inicio": ts_utc()}

    dados = gravar_durante_particao()
    resultado.update({k: v for k, v in dados.items() if k != "itens_escritos"})
    resultado["itens_escritos"] = dados["itens_escritos"]
    resultado["fim"] = ts_utc()

    salvar_resultado("03_fault_region.json", resultado)
    salvar_resultado("cenario_a_itens.json", {"itens": dados["itens_escritos"]})

    passou = dados["disponibilidade_pct"] == 100.0
    console.print(f"\n[bold]Resultado:[/] {'[green]PASSOU[/]' if passou else '[red]FALHOU[/]'}")
    console.print(f"  • Disponibilidade durante partição: {dados['disponibilidade_pct']}%")

    console.print("\n[bold yellow]Próximo passo:[/]")
    console.print("  1. Restaure eu-west-1:  [bold]cd terraform && terraform apply[/]")
    console.print("  2. Meça convergência:   [bold]python scripts/03b_fault_convergencia.py[/]")
