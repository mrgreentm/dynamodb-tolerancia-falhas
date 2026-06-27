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
  description = "Número de escritas concorrentes por fase"
  type        = number
  default     = 100
}

variable "n_workers" {
  description = "Paralelismo máximo de escritas simultâneas"
  type        = number
  default     = 20
}
