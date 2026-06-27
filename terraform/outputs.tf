output "table_name" {
  value = aws_dynamodb_table.pedidos.name
}

output "table_arn_sa" {
  value = aws_dynamodb_table.pedidos.arn
}

output "stream_arn" {
  value = aws_dynamodb_table.pedidos.stream_arn
}

output "replicas" {
  value       = [for r in aws_dynamodb_table.pedidos.replica : r.region_name]
  description = "Regiões com réplica ativa"
}

output "global_secondary_indexes" {
  value = [for gsi in aws_dynamodb_table.pedidos.global_secondary_index : {
    name      = gsi.name
    hash_key  = gsi.hash_key
    range_key = gsi.range_key
  }]
}
