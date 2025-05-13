output "appconfig_application_id" {
  description = "The ID of the AWS AppConfig application."
  value       = aws_appconfig_application.lambda_app.id
}

output "appconfig_environment_id" {
  description = "The ID of the AWS AppConfig environment."
  value       = aws_appconfig_environment.lambda_env.environment_id
}

output "appconfig_configuration_profile_id" {
  description = "The ID of the AWS AppConfig configuration profile."
  value       = aws_appconfig_configuration_profile.lambda_config_profile.id
}

output "appconfig_configuration_version" {
  description = "The latest version of the AppConfig configuration."
  value       = aws_appconfig_hosted_configuration_version.lambda_config_version.version_number
}

output "lambda_function_name" {
  description = "The name of the deployed Lambda function."
  value       = aws_lambda_function.unit_defect_fun.function_name
}

output "lambda_function_arn" {
  description = "The ARN of the deployed Lambda function."
  value       = aws_lambda_function.unit_defect_fun.arn
}
