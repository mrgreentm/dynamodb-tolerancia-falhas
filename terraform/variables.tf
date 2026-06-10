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

variable "tags" {
  description = "Tags aplicadas a todos os recursos"
  type        = map(string)
  default = {
    Project     = "sistemas-distribuidos"
    Environment = "lab"
    Reference   = "USENIX-ATC-2022"
  }
}
