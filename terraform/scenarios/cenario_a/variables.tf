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

variable "n_escritas" {
  description = "Número de itens gravados durante a partição"
  type        = number
  default     = 20
}
