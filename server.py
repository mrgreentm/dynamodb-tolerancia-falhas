"""
Backend para o dashboard de pedidos DynamoDB.
Serve métricas do CloudWatch, operações CRUD na tabela e execução dos
cenários de fault tolerance (run em background thread).
"""
import re
import sys
import uuid
import threading
import subprocess
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from flask import Flask, jsonify, request
from flask.json.provider import DefaultJSONProvider
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# ── Serialização: converte Decimal → float para o JSON do Flask ───────────────
class DynamoJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

app = Flask(__name__)
app.json_provider_class = DynamoJSONProvider
app.json = DynamoJSONProvider(app)
CORS(app)

TABELA      = "Pedidos"
REGIAO_PRIM = "sa-east-1"
REGIOES     = ["sa-east-1", "us-east-1", "eu-west-1"]


def dynamo(regiao=REGIAO_PRIM):
    return boto3.resource("dynamodb", region_name=regiao).Table(TABELA)

def dynamo_client(regiao=REGIAO_PRIM):
    return boto3.client("dynamodb", region_name=regiao)

def cw(regiao=REGIAO_PRIM):
    return boto3.client("cloudwatch", region_name=regiao)

def ts_utc():
    return datetime.now(timezone.utc).isoformat()


# ── Status da tabela + PITR ───────────────────────────────────────────────────

def _contar_itens(regiao: str) -> int:
    """scan(COUNT) para contagem real — describe_table.ItemCount tem lag de ~6h."""
    total = 0
    kwargs = {"Select": "COUNT"}
    table = dynamo(regiao)
    while True:
        resp = table.scan(**kwargs)
        total += resp["Count"]
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return total


@app.get("/api/status")
def status():
    resultado = {}
    for regiao in REGIOES:
        client = dynamo_client(regiao)
        entry = {}

        # Describe table
        try:
            resp = client.describe_table(TableName=TABELA)
            t = resp["Table"]
            entry["status"]   = t["TableStatus"]
            entry["replicas"] = [
                {"region": r["RegionName"], "status": r["ReplicaStatus"]}
                for r in t.get("Replicas", [])
            ]
            # Contagem real via scan(COUNT) — describe_table.ItemCount tem cache de ~6h
            entry["items"] = _contar_itens(regiao)
        except ClientError as e:
            entry["status"] = "ERRO"
            entry["items"]  = 0
            entry["detail"] = e.response["Error"]["Message"]

        # PITR
        try:
            pitr_resp = client.describe_continuous_backups(TableName=TABELA)
            pitr = pitr_resp["ContinuousBackupsDescription"]["PointInTimeRecoveryDescription"]
            entry["pitr"] = pitr["PointInTimeRecoveryStatus"] == "ENABLED"
            earliest = pitr.get("EarliestRestorableDateTime")
            latest   = pitr.get("LatestRestorableDateTime")
            entry["pitr_earliest"] = earliest.isoformat() if earliest else None
            entry["pitr_latest"]   = latest.isoformat()   if latest   else None
        except Exception:
            entry["pitr"] = False
            entry["pitr_earliest"] = None
            entry["pitr_latest"]   = None

        resultado[regiao] = entry
    return jsonify(resultado)


# ── Métricas CloudWatch ───────────────────────────────────────────────────────

def _cw_stat(regiao, metric_name, stat, dimensions, period=300):
    now = datetime.now(timezone.utc)
    try:
        resp = cw(regiao).get_metric_statistics(
            Namespace="AWS/DynamoDB",
            MetricName=metric_name,
            Dimensions=dimensions,
            StartTime=now - timedelta(minutes=30),
            EndTime=now,
            Period=period,
            Statistics=[stat],
        )
        pontos = sorted(resp["Datapoints"], key=lambda x: x["Timestamp"])
        return pontos[-1][stat] if pontos else None
    except Exception:
        return None


@app.get("/api/metrics")
def metrics():
    resultado = {}
    for regiao in REGIOES:
        dims = [{"Name": "TableName", "Value": TABELA}]

        latencia  = _cw_stat(regiao, "SuccessfulRequestLatency", "Average",
                             dims + [{"Name": "Operation", "Value": "PutItem"}])
        throttle  = _cw_stat(regiao, "ThrottledRequests", "Sum", dims)
        erros     = _cw_stat(regiao, "SystemErrors",      "Sum", dims)
        user_errs = _cw_stat(regiao, "UserErrors",        "Sum", dims)

        resultado[regiao] = {
            "latency_ms":  round(latencia, 1) if latencia  is not None else None,
            "throttled":   int(throttle)      if throttle  is not None else 0,
            "errors":      int(erros)         if erros     is not None else 0,
            "user_errors": int(user_errs)     if user_errs is not None else 0,
            "source": "cloudwatch",
        }

    # ReplicationLatency: métrica disponível na região primária, por região receptora
    for dest in ["us-east-1", "eu-west-1"]:
        val = _cw_stat(
            REGIAO_PRIM, "ReplicationLatency", "Average",
            [{"Name": "TableName",      "Value": TABELA},
             {"Name": "ReceivingRegion","Value": dest}],
        )
        resultado[dest]["replication_latency_ms"] = round(val, 1) if val is not None else None

    return jsonify(resultado)


# ── CRUD pedidos ──────────────────────────────────────────────────────────────

@app.get("/api/orders")
def list_orders():
    try:
        resp = dynamo().scan(Limit=100)
        itens = resp.get("Items", [])
        itens.sort(key=lambda x: x.get("criado_em", ""), reverse=True)
        return jsonify(itens)
    except ClientError as e:
        return jsonify({"error": e.response["Error"]["Message"]}), 500


@app.post("/api/orders")
def create_order():
    data = request.json or {}
    item = {
        "pedido_id":     str(uuid.uuid4()),
        "criado_em":     ts_utc(),
        "produto":       data.get("produto", "Produto Genérico"),
        "cliente":       data.get("cliente", "Cliente"),
        "valor":         Decimal(str(data.get("valor", "0.00"))),
        "status":        "pendente",
        "origem_regiao": REGIAO_PRIM,
    }
    try:
        dynamo().put_item(Item=item)
        return jsonify(item), 201
    except ClientError as e:
        return jsonify({"error": e.response["Error"]["Message"]}), 500


@app.delete("/api/orders/<pedido_id>")
def delete_order(pedido_id):
    criado_em = request.args.get("criado_em")
    if not criado_em:
        return jsonify({"error": "criado_em obrigatório"}), 400
    try:
        dynamo().delete_item(Key={"pedido_id": pedido_id, "criado_em": criado_em})
        return jsonify({"deleted": pedido_id}), 200
    except ClientError as e:
        return jsonify({"error": e.response["Error"]["Message"]}), 500


# ── Execução de cenários de fault tolerance ───────────────────────────────────

SCRIPTS_DIR  = Path(__file__).parent / "scripts"
RESULTS_DIR  = Path(__file__).parent / "results"
_ANSI        = re.compile(r"\x1b\[[0-9;]*[mGKH]")
_scenario_lock = threading.Lock()

_scenario: dict = {
    "running":   None,   # "region" | "throttle" | "conflict" | "recovery" | None
    "logs":      [],
    "result":    None,
    "started":   None,
    "exit_code": None,
}

_SCRIPT_MAP = {
    "region":   "03_fault_region.py",
    "throttle": "04_fault_throttling.py",
    "conflict": "05_fault_conflict.py",
    "recovery": "06_validate_recovery.py",
    "seed":     "02_seed_data.py",
}

_RESULT_MAP = {
    "region":   "03_fault_region.json",
    "throttle": "04_fault_throttling.json",
    "conflict": "05_fault_conflict.json",
    "recovery": "06_validate_recovery.json",
}


def _exec_scenario(key: str, script: str):
    import json as _json
    proc = subprocess.Popen(
        [sys.executable, "-u", str(SCRIPTS_DIR / script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True, bufsize=1,
        cwd=str(SCRIPTS_DIR),
    )
    for raw in proc.stdout:
        line = _ANSI.sub("", raw).rstrip()
        if line:
            _scenario["logs"].append(line)
            if len(_scenario["logs"]) > 400:
                _scenario["logs"] = _scenario["logs"][-400:]
    proc.wait()
    _scenario["exit_code"] = proc.returncode

    rf = _RESULT_MAP.get(key)
    if rf:
        path = RESULTS_DIR / rf
        if path.exists():
            try:
                _scenario["result"] = _json.loads(path.read_text())
            except Exception:
                pass

    _scenario["running"] = None


@app.post("/api/run/<key>")
def run_scenario(key):
    if key not in _SCRIPT_MAP:
        return jsonify({"error": "cenário desconhecido"}), 400
    with _scenario_lock:
        if _scenario["running"]:
            return jsonify({"error": f"cenário '{_scenario['running']}' em execução"}), 409
        _scenario.update({
            "running":   key,
            "logs":      [f"Iniciando {key} → {_SCRIPT_MAP[key]}"],
            "result":    None,
            "started":   ts_utc(),
            "exit_code": None,
        })
    threading.Thread(target=_exec_scenario, args=(key, _SCRIPT_MAP[key]), daemon=True).start()
    return jsonify({"started": key}), 202


@app.get("/api/run/status")
def run_status():
    return jsonify({
        "running":   _scenario["running"],
        "started":   _scenario["started"],
        "exit_code": _scenario["exit_code"],
        "logs":      _scenario["logs"][-100:],
        "result":    _scenario["result"],
    })


if __name__ == "__main__":
    print("Backend iniciado → http://localhost:8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
