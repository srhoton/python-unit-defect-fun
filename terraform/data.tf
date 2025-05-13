# Data sources for existing infrastructure

data "aws_dynamodb_table" "source_table" {
  name = var.source_table_name
}

data "aws_dynamodb_table" "destination_table" {
  name = var.destination_table_name
}
