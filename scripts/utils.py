import boto3
import time
import json
import statistics
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

console = Console()

TABELA = "Pedidos"
REGIOES = ["sa-east-1", "us-east-1", "eu-west-1"]
RESULTS_DIR = Path(__file__).parent.parent / "results"


def get_client(regiao: str):
    return boto3.client("dynamodb", region_name=regiao)


def get_resource(regiao: str):
    return boto3.resource("dynamodb", region_name=regiao)


def get_table(regiao: str):
    return get_resource(regiao).Table(TABELA)


def get_table_sem_retry(regiao: str):
    import botocore.config
    cfg = botocore.config.Config(retries={"max_attempts": 1})
    return boto3.resource("dynamodb", region_name=regiao, config=cfg).Table(TABELA)


def get_table_com_retry(regiao: str, max_attempts: int = 10):
    import botocore.config
    cfg = botocore.config.Config(retries={"max_attempts": max_attempts, "mode": "adaptive"})
    return boto3.resource("dynamodb", region_name=regiao, config=cfg).Table(TABELA)


@contextmanager
def cronometrar():
    """Retorna dict com chave 'ms' preenchida após o bloco."""
    t = {}
    inicio = time.perf_counter()
    try:
        yield t
    finally:
        t["ms"] = round((time.perf_counter() - inicio) * 1000, 1)


def percentis(valores: list, ps=(50, 90, 95, 99)) -> dict:
    if not valores:
        return {f"p{p}": None for p in ps}
    s = sorted(valores)
    n = len(s)
    result = {}
    for p in ps:
        idx = max(0, int(p / 100 * n) - 1)
        result[f"p{p}"] = round(s[idx], 1)
    return result


def aguardar_tabela_ativa(regiao: str, nome: str = TABELA, intervalo: int = 5, tentativas: int = 60):
    client = get_client(regiao)
    with console.status(f"Aguardando tabela ACTIVE em {regiao}..."):
        for _ in range(tentativas):
            try:
                resp = client.describe_table(TableName=nome)
                if resp["Table"]["TableStatus"] == "ACTIVE":
                    return True
            except client.exceptions.ResourceNotFoundException:
                pass
            time.sleep(intervalo)
    raise TimeoutError(f"Tabela {nome} não ficou ACTIVE em {regiao} após {tentativas * intervalo}s")


def aguardar_replicas(regioes: list, nome: str = TABELA, intervalo: int = 10, tentativas: int = 60):
    client = get_client("us-east-1")
    pendentes = set(regioes)
    with console.status(f"Aguardando réplicas ACTIVE: {pendentes}..."):
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
            "gsis": [
                {"nome": g["IndexName"], "status": g["IndexStatus"]}
                for g in t.get("GlobalSecondaryIndexes", [])
            ],
        }
    except Exception as e:
        return {"status": "ERRO", "detalhe": str(e)}
