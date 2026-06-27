# Cenário C — Conflito de Escrita / Last-Write-Wins (USENIX ATC 2022, §3.4)
#
# O Terraform executa escrita_us e escrita_eu em paralelo (sem depends_on entre si),
# simulando o conflito. medir_convergencia faz polling nas 3 regiões em paralelo.
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
  env_sa = {
    AWS_ACCESS_KEY_ID     = var.aws_access_key
    AWS_SECRET_ACCESS_KEY = var.aws_secret_key
    AWS_DEFAULT_REGION    = "sa-east-1"
  }
  pedido_id = "CONFLICT-C-LWW"
  criado_em = "2026-06-26T00:00:00Z"
}

# ── Escritas simultâneas (Terraform executa em paralelo) ─────────────────────

resource "null_resource" "escrita_us" {
  triggers = { run = timestamp() }

  provisioner "local-exec" {
    environment = local.env_us
    command     = <<-EOT
      echo ""
      echo "══════════════════════════════════════════════════════════════"
      echo "  Cenário C — Last-Write-Wins  (USENIX ATC 2022, §3.4)"
      echo "══════════════════════════════════════════════════════════════"
      for rodada in $(seq 1 ${var.n_rodadas}); do
        ITEM="{\"pedido_id\":{\"S\":\"${local.pedido_id}-$rodada\"},\"criado_em\":{\"S\":\"${local.criado_em}\"},\"valor\":{\"S\":\"versao_us\"},\"origem_regiao\":{\"S\":\"us-east-1\"}}"
        aws dynamodb put-item --table-name ${var.table_name} --item "$ITEM" --output none
        echo "  [us-east-1] rodada $rodada → versao_us"
      done
    EOT
  }
}

resource "null_resource" "escrita_eu" {
  triggers = { run = timestamp() }

  provisioner "local-exec" {
    environment = local.env_eu
    command     = <<-EOT
      for rodada in $(seq 1 ${var.n_rodadas}); do
        ITEM="{\"pedido_id\":{\"S\":\"${local.pedido_id}-$rodada\"},\"criado_em\":{\"S\":\"${local.criado_em}\"},\"valor\":{\"S\":\"versao_eu\"},\"origem_regiao\":{\"S\":\"eu-west-1\"}}"
        aws dynamodb put-item --table-name ${var.table_name} --item "$ITEM" --output none
        echo "  [eu-west-1] rodada $rodada → versao_eu"
      done
    EOT
  }
}

# ── Polling de convergência com queries em paralelo ───────────────────────────

resource "null_resource" "medir_convergencia" {
  triggers = { run = timestamp() }

  provisioner "local-exec" {
    environment = local.env_sa
    command     = <<-EOT
      echo ""
      echo "▶ Medindo convergência (queries nas 3 regiões em paralelo)..."
      echo ""

      # ms portável: funciona em macOS e Linux
      ms() { python3 -c "import time; print(int(time.time()*1000))"; }

      CONVERGIDAS=0
      MAX_MS=0

      for rodada in $(seq 1 ${var.n_rodadas}); do
        KEY="{\"pedido_id\":{\"S\":\"${local.pedido_id}-$rodada\"},\"criado_em\":{\"S\":\"${local.criado_em}\"}}"
        INICIO=$(ms)
        CONVERGIU=0
        TIMEOUT_MS=$((${var.timeout_convergencia_s} * 1000))

        while true; do
          ELAPSED=$(( $(ms) - INICIO ))
          [ $ELAPSED -gt $TIMEOUT_MS ] && echo "  Rodada $rodada: ✗ Timeout" && break

          # Queries em paralelo via temp files
          TMPDIR=$(mktemp -d)
          aws dynamodb get-item --table-name ${var.table_name} --region us-east-1 \
            --key "$KEY" --query "Item.valor.S" --output text > "$TMPDIR/us" 2>/dev/null &
          aws dynamodb get-item --table-name ${var.table_name} --region eu-west-1 \
            --key "$KEY" --query "Item.valor.S" --output text > "$TMPDIR/eu" 2>/dev/null &
          aws dynamodb get-item --table-name ${var.table_name} --region sa-east-1 \
            --key "$KEY" --query "Item.valor.S" --output text > "$TMPDIR/sa" 2>/dev/null &
          wait

          VUS=$(cat "$TMPDIR/us"); VEU=$(cat "$TMPDIR/eu"); VSA=$(cat "$TMPDIR/sa")
          rm -rf "$TMPDIR"

          if [ -n "$VUS" ] && [ "$VUS" != "None" ] && [ "$VUS" = "$VEU" ] && [ "$VUS" = "$VSA" ]; then
            echo "  Rodada $rodada: ✓ $${ELAPSED}ms → vencedor: $VUS"
            CONVERGIDAS=$((CONVERGIDAS + 1))
            [ $ELAPSED -gt $MAX_MS ] && MAX_MS=$ELAPSED
            CONVERGIU=1
            break
          fi
          sleep 0.2
        done

        [ $CONVERGIU -eq 0 ] && echo "  Rodada $rodada: ✗ Sem convergência"
      done

      echo ""
      echo "  • Convergidas : $CONVERGIDAS/${var.n_rodadas}"
      echo "  • Tempo máx   : $${MAX_MS}ms"
      [ $MAX_MS -lt 2000 ] && echo "  ✓ < 2000ms — conforme esperado (§3.4)"
      echo "  • Nota: vencedor não-determinístico (timestamp interno da AWS)"
      [ $CONVERGIDAS -eq ${var.n_rodadas} ] && echo "  ✓ PASSOU" || echo "  ✗ FALHOU"
    EOT
  }

  depends_on = [
    null_resource.escrita_us,
    null_resource.escrita_eu,
  ]
}
