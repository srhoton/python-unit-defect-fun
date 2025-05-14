variable "aws_region" {
  description = "AWS region to deploy resources in"
  type        = string
  default     = "us-east-1"
}

variable "owner" {
  description = "Owner of the infrastructure resources"
  type        = string
  default     = "srhoton"
}

variable "environment" {
  description = "Deployment environment (e.g., dev, staging, prod)"
  type        = string
  default     = "dev"
}



variable "source_table_name" {
  description = "Name of the source DynamoDB table"
  type        = string
  default     = "unt-units-svc"
}

variable "destination_table_name" {
  description = "Name of the destination DynamoDB table"
  type        = string
  default     = "svc-defect-svc"
}

variable "lambda_function_name" {
  description = "Name for the Lambda function"
  type        = string
  default     = "python-unit-defect-fun"
}

variable "lambda_s3_bucket" {
  description = "Name of existing S3 bucket for Lambda deployment package"
  type        = string
  default     = "unit-defect-lambda-artifacts"
}

variable "lambda_s3_key" {
  description = "S3 key for Lambda deployment package"
  type        = string
  default     = "python-unit-defect-fun-lambda.zip"
}

variable "lambda_package_path" {
  description = "Local path to the Lambda deployment package zip file"
  type        = string
  default     = "./lambda.zip"
}

variable "lambda_memory_size" {
  description = "Amount of memory (in MB) to allocate to the Lambda function"
  type        = number
  default     = 256
}

variable "lambda_timeout" {
  description = "Timeout (in seconds) for the Lambda function"
  type        = number
  default     = 30
}
