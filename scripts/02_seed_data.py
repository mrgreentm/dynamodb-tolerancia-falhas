"""
Popula a tabela Pedidos com dados realistas de teste.
"""
import uuid
import random
from decimal import Decimal
from dotenv import load_dotenv
from utils import console, get_table, salvar_resultado, ts_utc

load_dotenv()

REGIAO = "sa-east-1"
N_ITENS = 50

PRODUTOS = [
    "Notebook Pro 15", "Teclado Mecânico", "Mouse Gamer", "Monitor 4K",
    "Headset Bluetooth", "Webcam HD", "Hub USB-C", "SSD 1TB",
    "Memória RAM 32GB", "Placa de Vídeo RTX", "Cadeira Ergonômica",
    "Desk Lamp LED", "Microfone Condensador", "Impressora Laser",
]

CLIENTES = [f"cliente_{i:03d}@empresa.com" for i in range(1, 21)]
STATUSES = ["pendente", "processando", "enviado", "entregue", "cancelado"]
REGIOES_ORIGEM = ["sa-east-1", "us-east-1", "eu-west-1"]


def popular(n: int = N_ITENS):
    console.print(f"[bold]Inserindo {n} pedidos em {REGIAO}...[/]")
    tabela = get_table(REGIAO)
    itens = []

    with tabela.batch_writer() as batch:
        for i in range(n):
            item = {
                "pedido_id":     str(uuid.uuid4()),
                "criado_em":     ts_utc(),
                "produto":       random.choice(PRODUTOS),
                "cliente":       random.choice(CLIENTES),
                "valor":         Decimal(str(round(random.uniform(29.90, 4999.00), 2))),
                "quantidade":    random.randint(1, 5),
                "status":        STATUSES[i % len(STATUSES)],
                "origem_regiao": random.choice(REGIOES_ORIGEM),
            }
            batch.put_item(Item=item)
            itens.append(item)

    console.print(f"  [green]✓[/] {n} pedidos inseridos.")
    caminho = salvar_resultado("seed_data.json", {"total": n, "itens": itens})
    console.print(f"  Log salvo em: {caminho}")
    return itens


if __name__ == "__main__":
    popular()
