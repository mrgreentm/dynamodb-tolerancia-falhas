import boto3
import uuid
from decimal import Decimal
from datetime import datetime, timezone
from dotenv import load_dotenv
from utils import get_table, salvar_resultado, ts_utc

load_dotenv()

TABELA = "Pedidos"
REGIAO = "sa-east-1"

PRODUTOS = [
    "Notebook", "Teclado", "Mouse", "Monitor", "Headset",
    "Webcam", "Hub USB", "SSD", "Memória RAM", "Placa de Vídeo",
]

STATUSES = ["pendente", "processando", "enviado", "entregue"]


def popular_dados(n: int = 20):
    tabela = get_table(REGIAO)
    itens_inseridos = []

    print(f"Inserindo {n} itens de teste em {REGIAO}...")
    with tabela.batch_writer() as batch:
        for i in range(n):
            item = {
                "pedido_id": str(uuid.uuid4()),
                "criado_em": ts_utc(),
                "produto": PRODUTOS[i % len(PRODUTOS)],
                "valor": Decimal(str(round(10.0 + i * 5.5, 2))),
                "quantidade": (i % 5) + 1,
                "status": STATUSES[i % len(STATUSES)],
                "origem_regiao": REGIAO,
                "cliente_id": f"CLIENTE-{(i % 10) + 1:03d}",
            }
            batch.put_item(Item=item)
            itens_inseridos.append(item)

    print(f"  {n} itens inseridos com sucesso.")
    caminho = salvar_resultado("seed_data.json", {"total": n, "itens": itens_inseridos})
    print(f"  Log salvo em: {caminho}")


if __name__ == "__main__":
    popular_dados()
