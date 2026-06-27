# Cenário B — Throttling / Admission Control (USENIX ATC 2022, §4)
#
# Cria tabela temporária com 1 WCU PROVISIONED (~10s para ACTIVE),
# testa throttling sem/com retry, depois apaga a tabela.
# Evita aguardar 2-3 min do alter billing mode na tabela principal.
#
# Uso:
#   terraform apply -var-file=../../terraform.tfvars -auto-approve

terraform {
  required_version = ">= 1.5"
  required_providers {
    null = { source = "hashicorp/null", version = "~> 3.0" }
  }
}

locals {
  env = {
    AWS_ACCESS_KEY_ID     = var.aws_access_key
    AWS_SECRET_ACCESS_KEY = var.aws_secret_key
    AWS_DEFAULT_REGION    = "sa-east-1"
  }
  tabela_teste = "PedidosThrottleTest"
}

# ── Step 1: Criar tabela PROVISIONED 1 WCU e aguardar ACTIVE ─────────────────

resource "null_resource" "criar_tabela_teste" {
  triggers = { run = timestamp() }

  provisioner "local-exec" {
    environment = local.env
    command     = <<-EOT
      echo ""
      echo "══════════════════════════════════════════════════════════════"
      echo "  Cenário B — Throttling / Admission Control  (USENIX ATC §4)"
      echo "══════════════════════════════════════════════════════════════"
      echo ""
      echo "▶ [1/4] Criando tabela de teste com 1 WCU PROVISIONED..."

      aws dynamodb delete-table --table-name ${local.tabela_teste} --output none 2>/dev/null || true
      # aguarda deleção se existia
      until ! aws dynamodb describe-table --table-name ${local.tabela_teste} --output none 2>/dev/null; do
        echo "  ... aguardando deleção anterior"
        sleep 3
      done

      aws dynamodb create-table \
        --table-name ${local.tabela_teste} \
        --attribute-definitions AttributeName=id,AttributeType=S \
        --key-schema AttributeName=id,KeyType=HASH \
        --billing-mode PROVISIONED \
        --provisioned-throughput ReadCapacityUnits=1,WriteCapacityUnits=1 \
        --output none

      until [ "$(aws dynamodb describe-table \
          --table-name ${local.tabela_teste} \
          --query Table.TableStatus --output text 2>/dev/null)" = "ACTIVE" ]; do
        echo "  ... aguardando ACTIVE"
        sleep 3
      done
      echo "  ✓ Tabela ${local.tabela_teste} ACTIVE (1 WCU)"
    EOT
  }
}

# ── Step 2: Fase 1 — escritas paralelas SEM retry ────────────────────────────

resource "null_resource" "fase1_sem_retry" {
  triggers = { run = null_resource.criar_tabela_teste.id }

  provisioner "local-exec" {
    environment = local.env
    command     = <<-EOT
      echo ""
      echo "▶ [2/4] Fase 1 — ${var.n_escritas} escritas paralelas SEM retry..."
      rm -f /tmp/tf_b_f1_ok /tmp/tf_b_f1_thr /tmp/tf_b_f1_err
      INICIO=$(date +%s)

      for i in $(seq 0 $((${var.n_escritas} - 1))); do
        (
          KEY=$(printf '%04d' $i)
          EOUT=$(AWS_MAX_ATTEMPTS=1 aws dynamodb put-item \
            --table-name ${local.tabela_teste} \
            --item "{\"id\":{\"S\":\"f1-$KEY\"}}" 2>&1 1>/dev/null)
          RC=$?
          if [ $RC -eq 0 ]; then
            echo "1" >> /tmp/tf_b_f1_ok
          elif echo "$EOUT" | grep -q "ProvisionedThroughputExceededException"; then
            echo "1" >> /tmp/tf_b_f1_thr
          else
            echo "1" >> /tmp/tf_b_f1_err
          fi
        ) &
      done
      wait

      ELAPSED=$(( $(date +%s) - INICIO ))
      N_OK=$(grep -c "." /tmp/tf_b_f1_ok 2>/dev/null); OK=$${N_OK:-0}
      N_THR=$(grep -c "." /tmp/tf_b_f1_thr 2>/dev/null); THROTTLED=$${N_THR:-0}
      N_ERR=$(grep -c "." /tmp/tf_b_f1_err 2>/dev/null); ERRS=$${N_ERR:-0}
      rm -f /tmp/tf_b_f1_ok /tmp/tf_b_f1_thr /tmp/tf_b_f1_err

      echo "  • Sucesso   : $OK/${var.n_escritas} ($((OK * 100 / ${var.n_escritas}))%)"
      echo "  • Throttled : $THROTTLED/${var.n_escritas} ($((THROTTLED * 100 / ${var.n_escritas}))%)"
      echo "  • Erros     : $ERRS"
      echo "  • Tempo     : $${ELAPSED}s"
      [ $THROTTLED -gt 0 ] && echo "  ✓ Throttling confirmado (§4)" || echo "  ⚠ Nenhum throttle — tabela pode ainda estar em UPDATING"
    EOT
  }

  depends_on = [null_resource.criar_tabela_teste]
}

# ── Step 3: Fase 2 — escritas paralelas COM retry adaptativo ─────────────────

resource "null_resource" "fase2_com_retry" {
  triggers = { run = null_resource.criar_tabela_teste.id }

  provisioner "local-exec" {
    environment = local.env
    command     = <<-EOT
      echo ""
      echo "▶ [3/4] Fase 2 — ${var.n_escritas} escritas paralelas COM retry adaptativo..."
      rm -f /tmp/tf_b_f2_ok /tmp/tf_b_f2_err
      INICIO=$(date +%s)

      for i in $(seq 0 $((${var.n_escritas} - 1))); do
        (
          KEY=$(printf '%04d' $i)
          if AWS_MAX_ATTEMPTS=10 AWS_RETRY_MODE=adaptive aws dynamodb put-item \
            --table-name ${local.tabela_teste} \
            --item "{\"id\":{\"S\":\"f2-$KEY\"}}" --output none 2>/dev/null; then
            echo "1" >> /tmp/tf_b_f2_ok
          else
            echo "1" >> /tmp/tf_b_f2_err
          fi
        ) &
      done
      wait

      ELAPSED=$(( $(date +%s) - INICIO ))
      N_OK=$(grep -c "." /tmp/tf_b_f2_ok 2>/dev/null); OK=$${N_OK:-0}
      N_ERR=$(grep -c "." /tmp/tf_b_f2_err 2>/dev/null); ERRS=$${N_ERR:-0}
      rm -f /tmp/tf_b_f2_ok /tmp/tf_b_f2_err

      echo "  • Sucesso   : $OK/${var.n_escritas} ($((OK * 100 / ${var.n_escritas}))%)"
      echo "  • Falhas    : $ERRS"
      echo "  • Tempo     : $${ELAPSED}s"
      [ $OK -eq ${var.n_escritas} ] && echo "  ✓ 100% com backoff exponencial (§4)" || echo "  ⚠ $ERRS falhas"
    EOT
  }

  depends_on = [null_resource.fase1_sem_retry]
}

# ── Step 4: Apagar tabela temporária ─────────────────────────────────────────

resource "null_resource" "apagar_tabela_teste" {
  triggers = { run = null_resource.criar_tabela_teste.id }

  provisioner "local-exec" {
    environment = local.env
    command     = <<-EOT
      echo ""
      echo "▶ [4/4] Removendo tabela de teste..."
      aws dynamodb delete-table --table-name ${local.tabela_teste} --output none 2>/dev/null || true
      echo "  ✓ Cenário B concluído. Tabela de teste removida."
    EOT
  }

  depends_on = [null_resource.fase2_com_retry]
}
