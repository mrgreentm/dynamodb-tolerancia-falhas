variable "aws_access_key" {
  description = "AWS Access Key ID"
  type        = string
  sensitive   = true
}

variable "aws_secret_key" {
  description = "AWS Secret Access Key"
  type        = string
  sensitive   = true
}

variable "table_name" {
  description = "Nome da tabela DynamoDB"
  type        = string
  default     = "Pedidos"
}

variable "n_rodadas" {
  description = "Número de rodadas de conflito simultâneo"
  type        = number
  default     = 5
}

variable "timeout_convergencia_s" {
  description = "Tempo máximo aguardando convergência por rodada (segundos)"
  type        = number
  default     = 30
}
