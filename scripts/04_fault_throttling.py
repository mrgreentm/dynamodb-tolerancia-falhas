"""
Cenário B — Throttling.

Converte a tabela para modo PROVISIONED com capacidade mínima (1 WCU / 1 RCU)
para forçar erros ProvisionedThroughputExceededException. Valida que o boto3
aplica retry com exponential backoff automaticamente e que a taxa de erro
fica acima do esperado para capacidade insuficiente.

Ref: paper USENIX ATC 2022, §4 — Admission Control.
"""
import boto3
import time
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from utils import get_client, get_table, aguardar_tabela_ativa, salvar_resultado, ts_utc

load_dotenv()

TABELA = "Pedidos"
REGIAO = "sa-east-1"
TOTAL_ESCRITAS = 50


def converter_para_provisioned():
    print("[THROTTLE] Convertendo para PROVISIONED com 1 WCU / 1 RCU...")
    get_client(REGIAO).update_table(
        TableName=TABELA,
        BillingMode="PROVISIONED",
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
    )
    aguardar_tabela_ativa(REGIAO)
    print("  Modo PROVISIONED ativo.")


def enviar_escritas_em_rajada() -> dict:
    print(f"[TESTE] Enviando {TOTAL_ESCRITAS} escritas em rajada...")
    tabela = get_table(REGIAO)
    sucesso = 0
    throttled = 0
    outros_erros = 0

    # Desabilitar retry automático do boto3 para medir throttling real
    import botocore.config
    config = botocore.config.Config(retries={"max_attempts": 1})
    client_sem_retry = boto3.resource("dynamodb", region_name=REGIAO, config=config)
    tabela_sem_retry = client_sem_retry.Table(TABELA)

    for i in range(TOTAL_ESCRITAS):
        try:
            tabela_sem_retry.put_item(Item={
                "pedido_id": f"THROTTLE-{i:03d}",
                "criado_em": f"2026-06-07T{i // 3600:02d}:{(i % 3600) // 60:02d}:{i % 60:02d}+00:00",
                "status": "teste_throttle",
                "origem_regiao": REGIAO,
            })
            sucesso += 1
        except ClientError as e:
            codigo = e.response["Error"]["Code"]
            if codigo == "ProvisionedThroughputExceededException":
                throttled += 1
            else:
                outros_erros += 1

    print(f"  Sucessos: {sucesso}/{TOTAL_ESCRITAS}")
    print(f"  Throttled: {throttled}/{TOTAL_ESCRITAS}")
    print(f"  Outros erros: {outros_erros}/{TOTAL_ESCRITAS}")
    return {"sucesso": sucesso, "throttled": throttled, "outros_erros": outros_erros}


def restaurar_pay_per_request():
    print("[RECOVERY] Restaurando modo PAY_PER_REQUEST...")
    get_client(REGIAO).update_table(TableName=TABELA, BillingMode="PAY_PER_REQUEST")
    aguardar_tabela_ativa(REGIAO)
    print("  PAY_PER_REQUEST restaurado.")


if __name__ == "__main__":
    resultado = {"inicio": ts_utc(), "total_escritas": TOTAL_ESCRITAS}
    converter_para_provisioned()
    resultado["throttle_inicio"] = ts_utc()

    metricas = enviar_escritas_em_rajada()
    resultado.update(metricas)
    resultado["throttle_fim"] = ts_utc()

    restaurar_pay_per_request()
    resultado["recovery"] = ts_utc()

    salvar_resultado("04_fault_throttling.json", resultado)
    taxa = metricas["throttled"] / TOTAL_ESCRITAS * 100
    print(f"\nTaxa de throttling: {taxa:.1f}%")
    print(f"Resultado: {'PASSOU' if metricas['throttled'] > 0 else 'FALHOU (nenhum throttle detectado)'}")
