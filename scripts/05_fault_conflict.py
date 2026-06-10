"""
Cenário C — Conflito de escrita (last-write-wins).

Grava o mesmo item em duas regiões com intervalo de 100ms entre as escritas.
Aguarda a convergência e verifica em todas as regiões qual valor prevaleceu.

O DynamoDB Global Tables usa last-write-wins baseado no timestamp do servidor
(não no timestamp da aplicação), portanto o valor gravado por último deve
prevalecer em todas as réplicas após convergência.

Ref: paper USENIX ATC 2022, §3.4 — Conflict Resolution.
"""
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from utils import get_table, salvar_resultado, ts_utc

load_dotenv()

TABELA = "Pedidos"
REGIOES = ["us-east-1", "sa-east-1", "eu-west-1"]
ITEM_KEY = {
    "pedido_id": "CONFLITO-001",
    "criado_em": "2026-06-07T12:00:00+00:00",
}
ESPERA_CONVERGENCIA = 10  # segundos


def gravar_versao(regiao: str, valor: str) -> str:
    ts = ts_utc()
    get_table(regiao).put_item(Item={
        **ITEM_KEY,
        "valor": valor,
        "ts_aplicacao": ts,
        "origem_regiao": regiao,
    })
    print(f"  [{regiao}] gravou '{valor}' às {ts}")
    return ts


def ler_versao(regiao: str) -> dict:
    resp = get_table(regiao).get_item(Key=ITEM_KEY, ConsistentRead=False)
    item = resp.get("Item", {})
    return {
        "regiao": regiao,
        "valor": item.get("valor"),
        "ts_aplicacao": item.get("ts_aplicacao"),
        "origem_regiao": item.get("origem_regiao"),
    }


def simular_conflito() -> dict:
    print("[CONFLITO] Gravando versões conflitantes em regiões distintas...")
    ts_us = gravar_versao("us-east-1", "versao_us")
    time.sleep(0.1)  # 100ms para garantir ordering observável
    ts_eu = gravar_versao("eu-west-1", "versao_eu")

    print(f"\n[AGUARDAR] Convergência ({ESPERA_CONVERGENCIA}s)...")
    time.sleep(ESPERA_CONVERGENCIA)

    print("\n[RESULTADO] Leitura eventual em todas as regiões:")
    leituras = []
    for regiao in REGIOES:
        leitura = ler_versao(regiao)
        leituras.append(leitura)
        print(f"  [{regiao}] valor={leitura['valor']} | ts={leitura['ts_aplicacao']}")

    valores = {l["valor"] for l in leituras if l["valor"]}
    convergiu = len(valores) == 1
    valor_final = next(iter(valores)) if valores else None

    print(f"\nConvergência: {'SIM' if convergiu else 'NÃO (ainda divergindo)'}")
    print(f"Valor prevalente: {valor_final}")
    print("Esperado: 'versao_eu' (escrita mais recente = last-write-wins)")

    return {
        "ts_us": ts_us,
        "ts_eu": ts_eu,
        "leituras": leituras,
        "convergiu": convergiu,
        "valor_final": valor_final,
        "resultado": "PASSOU" if valor_final == "versao_eu" else "DIVERGINDO",
    }


if __name__ == "__main__":
    resultado = {"inicio": ts_utc()}
    dados = simular_conflito()
    resultado.update(dados)
    resultado["fim"] = ts_utc()
    salvar_resultado("05_fault_conflict.json", resultado)
    print(f"\nResultado: {resultado['resultado']}")
