# Main Terraform configuration for python-unit-defect-fun
# - AppConfig for Lambda configuration
# - DynamoDB tables (source and destination)
# - Lambda function deployment
# - S3 bucket for Lambda artifacts



locals {
  project_name = "python-unit-defect-fun"
  environment  = var.environment
  tags = {
    Project     = local.project_name
    Environment = local.environment
    ManagedBy   = "Terraform"
    Owner       = var.owner
  }
}

# S3 Bucket for Lambda deployment artifacts
resource "aws_s3_bucket" "lambda_artifacts" {
  bucket = var.lambda_s3_bucket

  tags = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "lambda_artifacts_versioning" {
  bucket = aws_s3_bucket.lambda_artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lambda_artifacts_encryption" {
  bucket = aws_s3_bucket.lambda_artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "lambda_artifacts_block" {
  bucket                  = aws_s3_bucket.lambda_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}



# AppConfig Application
resource "aws_appconfig_application" "lambda_app" {
  name        = "${local.project_name}-app"
  description = "AppConfig application for Lambda configuration"
  tags        = local.tags
}

# AppConfig Environment
resource "aws_appconfig_environment" "lambda_env" {
  application_id = aws_appconfig_application.lambda_app.id
  name           = "${local.project_name}-env"
  description    = "AppConfig environment for Lambda"
  tags           = local.tags
}

# AppConfig Configuration Profile
resource "aws_appconfig_configuration_profile" "lambda_config_profile" {
  application_id = aws_appconfig_application.lambda_app.id
  name           = "${local.project_name}-config-profile"
  location_uri   = "hosted"
  type           = "AWS.Freeform"
  description    = "Configuration profile for Lambda"
  tags           = local.tags
}

# AppConfig Hosted Configuration Version
resource "aws_appconfig_hosted_configuration_version" "lambda_config_version" {
  application_id           = aws_appconfig_application.lambda_app.id
  configuration_profile_id = aws_appconfig_configuration_profile.lambda_config_profile.id
  content_type             = "application/json"
  description              = "Initial config for Lambda"
  content = jsonencode({
    sourceTable      = data.aws_dynamodb_table.source_table.name
    destinationTable = data.aws_dynamodb_table.destination_table.name
  })
}

# AppConfig Deployment Strategy (create "AllAtOnce" strategy if not using AWS managed one)
resource "aws_appconfig_deployment_strategy" "quick" {
  name                           = "AllAtOnce"
  description                    = "All-at-once deployment strategy for Lambda AppConfig"
  deployment_duration_in_minutes = 0
  growth_factor                  = 100
  final_bake_time_in_minutes     = 0
  replicate_to                   = "NONE"
  growth_type                    = "LINEAR"
}

# AppConfig Deployment
resource "aws_appconfig_deployment" "lambda_config_deployment" {
  application_id           = aws_appconfig_application.lambda_app.id
  environment_id           = aws_appconfig_environment.lambda_env.environment_id
  configuration_profile_id = aws_appconfig_configuration_profile.lambda_config_profile.id
  configuration_version    = aws_appconfig_hosted_configuration_version.lambda_config_version.version_number
  deployment_strategy_id   = aws_appconfig_deployment_strategy.quick.id
  description              = "Deploy Lambda config to AppConfig environment"
}



# Lambda Function
resource "aws_lambda_function" "unit_defect_fun" {
  function_name = "${local.project_name}-lambda"
  description   = "Lambda function for updating unit information in defect service"
  role          = aws_iam_role.lambda_exec_role.arn
  handler       = "python_unit_defect_fun.lambda_handler.lambda_handler"
  runtime       = "python3.13"
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory_size

  # Lambda deployment package from S3
  s3_bucket        = aws_s3_bucket.lambda_artifacts.bucket
  s3_key           = var.lambda_s3_key
  source_code_hash = filebase64sha256(var.lambda_package_path)

  environment {
    variables = {
      APPCONFIG_APPLICATION_ID    = aws_appconfig_application.lambda_app.id
      APPCONFIG_ENVIRONMENT_ID    = aws_appconfig_environment.lambda_env.environment_id
      APPCONFIG_CONFIG_PROFILE_ID = aws_appconfig_configuration_profile.lambda_config_profile.id
    }
  }

  tags = local.tags

  depends_on = [
    aws_appconfig_deployment.lambda_config_deployment
  ]
}

# Lambda Event Source Mapping for DynamoDB Stream
resource "aws_lambda_event_source_mapping" "ddb_stream" {
  event_source_arn  = data.aws_dynamodb_table.source_table.stream_arn
  function_name     = aws_lambda_function.unit_defect_fun.arn
  starting_position = "LATEST"
  enabled           = true
}
