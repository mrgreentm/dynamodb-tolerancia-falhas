"""
Fase 4 — Monitoramento e validação de recovery.

Verifica o estado de saúde da tabela em todas as regiões:
- Contagem de itens e status por região
- Ativação e status do PITR
- Medição de latência de replicação entre regiões
- Exportação de relatório JSON em results/
"""
import uuid
import time
from dotenv import load_dotenv
from utils import (
    REGIOES, get_client, get_table,
    status_tabela, salvar_resultado, ts_utc,
)

load_dotenv()

TABELA = "Pedidos"


def contar_itens_por_regiao() -> list[dict]:
    print("\n=== Contagem de itens por região ===")
    resultados = []
    for regiao in REGIOES:
        info = status_tabela(regiao)
        print(f"  {regiao}: {info.get('itens', 'N/A')} itens | status: {info['status']}")
        resultados.append({"regiao": regiao, **info})
    return resultados


def ativar_pitr():
    print("\n[AÇÃO] Ativando PITR em todas as regiões...")
    for regiao in REGIOES:
        try:
            get_client(regiao).update_continuous_backups(
                TableName=TABELA,
                PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True},
            )
            print(f"  {regiao}: PITR ativado.")
        except Exception as e:
            print(f"  {regiao}: {e}")


def verificar_pitr() -> list[dict]:
    print("\n=== Status do PITR por região ===")
    resultados = []
    for regiao in REGIOES:
        try:
            resp = get_client(regiao).describe_continuous_backups(TableName=TABELA)
            pitr = resp["ContinuousBackupsDescription"]["PointInTimeRecoveryDescription"]
            status = pitr["PointInTimeRecoveryStatus"]
            mais_cedo = pitr.get("EarliestRestorableDateTime", "N/A")
            mais_recente = pitr.get("LatestRestorableDateTime", "N/A")
            print(f"  {regiao}: PITR={status} | janela: {mais_cedo} → {mais_recente}")
            resultados.append({"regiao": regiao, "pitr_status": status,
                                "earliest": str(mais_cedo), "latest": str(mais_recente)})
        except Exception as e:
            print(f"  {regiao}: {e}")
            resultados.append({"regiao": regiao, "pitr_status": "ERRO", "detalhe": str(e)})
    return resultados


def medir_latencia_replicacao() -> list[dict]:
    print("\n=== Latência de replicação ===")
    item_id = str(uuid.uuid4())
    ts = ts_utc()

    get_table("us-east-1").put_item(Item={
        "pedido_id": item_id,
        "criado_em": ts,
        "marker": "latencia_test",
    })
    inicio = time.time()

    resultados = []
    for regiao in ["sa-east-1", "eu-west-1"]:
        encontrado = False
        for _ in range(60):
            resp = get_table(regiao).get_item(
                Key={"pedido_id": item_id, "criado_em": ts},
                ConsistentRead=False,
            )
            if resp.get("Item"):
                latencia_ms = round((time.time() - inicio) * 1000)
                print(f"  us-east-1 → {regiao}: {latencia_ms}ms")
                resultados.append({"origem": "us-east-1", "destino": regiao, "latencia_ms": latencia_ms})
                encontrado = True
                break
            time.sleep(0.1)
        if not encontrado:
            print(f"  {regiao}: item não replicado em 6s")
            resultados.append({"origem": "us-east-1", "destino": regiao, "latencia_ms": None})
    return resultados


if __name__ == "__main__":
    relatorio = {"inicio": ts_utc()}

    relatorio["regioes"] = contar_itens_por_regiao()
    ativar_pitr()
    relatorio["pitr"] = verificar_pitr()
    relatorio["latencia_replicacao"] = medir_latencia_replicacao()
    relatorio["fim"] = ts_utc()

    caminho = salvar_resultado("06_validate_recovery.json", relatorio)
    print(f"\nRelatório salvo em: {caminho}")
