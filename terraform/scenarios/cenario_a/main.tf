# Cenário A — Consistência Eventual / Falha de Região (USENIX ATC 2022, §5)
#
# Escreve N itens em us-east-1 e mede o tempo até todos aparecerem em eu-west-1.
# Demonstra consistência eventual sem bloqueio de escrita — propriedade AP do DynamoDB.
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
  env_us = {
    AWS_ACCESS_KEY_ID     = var.aws_access_key
    AWS_SECRET_ACCESS_KEY = var.aws_secret_key
    AWS_DEFAULT_REGION    = "us-east-1"
  }
  env_eu = {
    AWS_ACCESS_KEY_ID     = var.aws_access_key
    AWS_SECRET_ACCESS_KEY = var.aws_secret_key
    AWS_DEFAULT_REGION    = "eu-west-1"
  }
  # Sort key fixo para que write e read usem o mesmo valor
  criado_em = "2026-06-26T00:00:00Z"
}

# ── Step 1: Gravar N itens em us-east-1 em paralelo ──────────────────────────

resource "null_resource" "gravar_em_us" {
  triggers = { run = timestamp() }

  provisioner "local-exec" {
    environment = local.env_us
    command     = <<-EOT
      echo ""
      echo "══════════════════════════════════════════════════════"
      echo "  Cenário A — Consistência Eventual  (USENIX ATC §5)"
      echo "══════════════════════════════════════════════════════"
      echo ""
      echo "▶ [1/2] Gravando ${var.n_escritas} itens em us-east-1 (paralelo)..."
      rm -f /tmp/tf_a_ok /tmp/tf_a_err

      for i in $(seq 0 $((${var.n_escritas} - 1))); do
        (
          KEY=$(printf '%02d' $i)
          ITEM="{\"pedido_id\":{\"S\":\"CE-A-$KEY\"},\"criado_em\":{\"S\":\"${local.criado_em}\"},\"status\":{\"S\":\"escrito_us\"},\"origem_regiao\":{\"S\":\"us-east-1\"}}"
          if aws dynamodb put-item --table-name ${var.table_name} --item "$ITEM" --output none 2>/dev/null; then
            echo "1" >> /tmp/tf_a_ok
          else
            echo "1" >> /tmp/tf_a_err
          fi
        ) &
      done
      wait

      N_OK=$(grep -c "." /tmp/tf_a_ok 2>/dev/null); OK=$${N_OK:-0}
      N_ERR=$(grep -c "." /tmp/tf_a_err 2>/dev/null); ERRS=$${N_ERR:-0}
      rm -f /tmp/tf_a_ok /tmp/tf_a_err

      echo "  ✓ Gravados: $OK/${var.n_escritas} em us-east-1  (erros: $ERRS)"
      echo "  → us-east-1 aceitou escritas imediatamente (disponibilidade AP)"
    EOT
  }
}

# ── Step 2: Medir convergência em eu-west-1 ───────────────────────────────────

resource "null_resource" "medir_convergencia" {
  triggers = { run = null_resource.gravar_em_us.id }

  provisioner "local-exec" {
    environment = local.env_eu
    command     = <<-EOT
      echo ""
      echo "▶ [2/2] Medindo convergência em eu-west-1..."
      TOTAL=${var.n_escritas}
      INICIO=$(date +%s)
      TIMEOUT=60

      while true; do
        AGORA=$(date +%s)
        ELAPSED=$((AGORA - INICIO))
        [ $ELAPSED -gt $TIMEOUT ] && echo "  ✗ Timeout $${TIMEOUT}s sem convergência total" && exit 1

        WDIR=$(mktemp -d)
        for i in $(seq 0 $((TOTAL - 1))); do
          KEY=$(printf '%02d' $i)
          (aws dynamodb get-item \
            --table-name ${var.table_name} \
            --key "{\"pedido_id\":{\"S\":\"CE-A-$KEY\"},\"criado_em\":{\"S\":\"${local.criado_em}\"}}" \
            --query "Item.pedido_id.S" --output text 2>/dev/null > "$WDIR/$i") &
        done
        wait

        ENCONTRADOS=$(grep -rl "CE-A-" "$WDIR" 2>/dev/null | wc -l | tr -d ' ')
        rm -rf "$WDIR"

        if [ "$ENCONTRADOS" -ge "$TOTAL" ]; then
          echo "  ✓ Todos $TOTAL itens replicados em $${ELAPSED}s"
          [ $ELAPSED -lt 30 ] && echo "  ✓ PASSOU (< 30s — consistência eventual §5)" || echo "  ⚠ Convergência em $${ELAPSED}s (> 30s)"
          break
        fi
        echo "  ... $ENCONTRADOS/$TOTAL em eu-west-1 ($${ELAPSED}s)"
        sleep 2
      done
    EOT
  }

  depends_on = [null_resource.gravar_em_us]
}
