import boto3
import time
import json
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TABELA = "Pedidos"
REGIOES = ["sa-east-1", "us-east-1", "eu-west-1"]
RESULTS_DIR = Path(__file__).parent.parent / "results"


def get_client(regiao: str):
    return boto3.client("dynamodb", region_name=regiao)


def get_resource(regiao: str):
    return boto3.resource("dynamodb", region_name=regiao)


def get_table(regiao: str):
    return get_resource(regiao).Table(TABELA)


def aguardar_tabela_ativa(regiao: str, nome: str = TABELA, intervalo: int = 5, tentativas: int = 60):
    client = get_client(regiao)
    for _ in range(tentativas):
        try:
            resp = client.describe_table(TableName=nome)
            if resp["Table"]["TableStatus"] == "ACTIVE":
                return True
        except client.exceptions.ResourceNotFoundException:
            pass
        time.sleep(intervalo)
    raise TimeoutError(f"Tabela {nome} não ficou ACTIVE em {regiao} após {tentativas * intervalo}s")


def aguardar_replicas(regioes: list[str], nome: str = TABELA, intervalo: int = 10, tentativas: int = 60):
    client = get_client("us-east-1")
    pendentes = set(regioes)
    for _ in range(tentativas):
        resp = client.describe_table(TableName=nome)
        replicas = resp["Table"].get("Replicas", [])
        ativos = {r["RegionName"] for r in replicas if r["ReplicaStatus"] == "ACTIVE"}
        pendentes -= ativos
        if not pendentes:
            return True
        time.sleep(intervalo)
    raise TimeoutError(f"Réplicas {pendentes} não ficaram ACTIVE após {tentativas * intervalo}s")


def salvar_resultado(nome_arquivo: str, dados: dict):
    RESULTS_DIR.mkdir(exist_ok=True)
    caminho = RESULTS_DIR / nome_arquivo
    caminho.write_text(json.dumps(dados, indent=2, default=str), encoding="utf-8")
    return caminho


def ts_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def status_tabela(regiao: str, nome: str = TABELA) -> dict:
    try:
        resp = get_client(regiao).describe_table(TableName=nome)
        t = resp["Table"]
        return {
            "status": t["TableStatus"],
            "itens": t.get("ItemCount", 0),
            "bytes": t.get("TableSizeBytes", 0),
            "replicas": [
                {"regiao": r["RegionName"], "status": r["ReplicaStatus"]}
                for r in t.get("Replicas", [])
            ],
        }
    except Exception as e:
        return {"status": "ERRO", "detalhe": str(e)}
