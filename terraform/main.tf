terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# ── Providers ─────────────────────────────────────────────────────────────────

provider "aws" {
  alias      = "sa"
  region     = "sa-east-1"
  access_key = var.aws_access_key
  secret_key = var.aws_secret_key
}

provider "aws" {
  alias      = "us"
  region     = "us-east-1"
  access_key = var.aws_access_key
  secret_key = var.aws_secret_key
}

provider "aws" {
  alias      = "eu"
  region     = "eu-west-1"
  access_key = var.aws_access_key
  secret_key = var.aws_secret_key
}

# ── Tabela principal (São Paulo — primária) ───────────────────────────────────

resource "aws_dynamodb_table" "pedidos" {
  provider     = aws.sa
  name         = var.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pedido_id"
  range_key    = "criado_em"

  attribute {
    name = "pedido_id"
    type = "S"
  }
  attribute {
    name = "criado_em"
    type = "S"
  }
  attribute {
    name = "status"
    type = "S"
  }
  attribute {
    name = "cliente"
    type = "S"
  }
  attribute {
    name = "origem_regiao"
    type = "S"
  }

  global_secondary_index {
    name            = "status-criado_em-index"
    hash_key        = "status"
    range_key       = "criado_em"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "cliente-criado_em-index"
    hash_key        = "cliente"
    range_key       = "criado_em"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "origem_regiao-criado_em-index"
    hash_key        = "origem_regiao"
    range_key       = "criado_em"
    projection_type = "ALL"
  }

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  point_in_time_recovery {
    enabled = true
  }

  replica {
    region_name            = "us-east-1"
    point_in_time_recovery = true
  }
  replica {
    region_name            = "eu-west-1"
    point_in_time_recovery = true
  }

  tags = var.tags
}
