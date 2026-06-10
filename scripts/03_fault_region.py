"""
Cenário A — Falha de região.

Simula a indisponibilidade de eu-west-1 removendo sua réplica da Global Table,
grava dados durante o período de 'falha', restaura a réplica e verifica que
os dados foram replicados após o recovery.

Ref: paper USENIX ATC 2022, §5 — Availability.
"""
import boto3
import time
from dotenv import load_dotenv
from utils import get_client, get_table, aguardar_replicas, salvar_resultado, ts_utc

load_dotenv()

TABELA = "Pedidos"
REGIAO_PRIMARIA = "us-east-1"
REGIAO_FALHA = "eu-west-1"
ITEM_KEY = {"pedido_id": "FALHA-001", "criado_em": "2026-06-07T00:00:00+00:00"}


def remover_replica():
    print(f"[FALHA] Removendo réplica de {REGIAO_FALHA}...")
    get_client(REGIAO_PRIMARIA).update_table(
        TableName=TABELA,
        ReplicaUpdates=[{"Delete": {"RegionName": REGIAO_FALHA}}],
    )
    # Aguardar confirmação da remoção
    for _ in range(30):
        resp = get_client(REGIAO_PRIMARIA).describe_table(TableName=TABELA)
        replicas = {r["RegionName"] for r in resp["Table"].get("Replicas", [])}
        if REGIAO_FALHA not in replicas:
            print(f"  Réplica de {REGIAO_FALHA} removida.")
            return
        time.sleep(5)
    print(f"  Aviso: remoção pode estar em andamento ainda.")


def gravar_durante_falha():
    print(f"[TESTE] Gravando item durante 'falha' de {REGIAO_FALHA}...")
    get_table(REGIAO_PRIMARIA).put_item(Item={
        **ITEM_KEY,
        "status": "criado_durante_falha",
        "origem_regiao": REGIAO_PRIMARIA,
        "gravado_em": ts_utc(),
    })
    print("  Item gravado em us-east-1 com sucesso.")


def restaurar_replica():
    print(f"[RECOVERY] Restaurando réplica em {REGIAO_FALHA}...")
    get_client(REGIAO_PRIMARIA).update_table(
        TableName=TABELA,
        ReplicaUpdates=[{"Create": {"RegionName": REGIAO_FALHA}}],
    )
    print("  Aguardando réplica ficar ACTIVE (pode levar 2-5 min)...")
    aguardar_replicas([REGIAO_FALHA])
    print("  Réplica restaurada.")


def validar_replicacao():
    print(f"[VALIDAR] Verificando replicação pós-recovery em {REGIAO_FALHA}...")
    for tentativa in range(30):
        resp = get_table(REGIAO_FALHA).get_item(Key=ITEM_KEY, ConsistentRead=False)
        if resp.get("Item"):
            print(f"  SUCESSO: Item replicado para {REGIAO_FALHA} (tentativa {tentativa + 1}).")
            return True
        time.sleep(2)
    print(f"  FALHA: Item não encontrado em {REGIAO_FALHA} após 60s.")
    return False


if __name__ == "__main__":
    resultado = {"inicio": ts_utc()}
    remover_replica()
    resultado["replica_removida"] = ts_utc()

    gravar_durante_falha()
    resultado["item_gravado"] = ts_utc()

    restaurar_replica()
    resultado["replica_restaurada"] = ts_utc()

    sucesso = validar_replicacao()
    resultado["replicacao_validada"] = sucesso
    resultado["fim"] = ts_utc()

    salvar_resultado("03_fault_region.json", resultado)
    print(f"\nResultado: {'PASSOU' if sucesso else 'FALHOU'}")
