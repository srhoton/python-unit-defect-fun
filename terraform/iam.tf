# IAM resources and policies for Lambda execution

data "aws_iam_policy_document" "lambda_assume_role_policy" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "lambda_policy" {
  statement {
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:DescribeTable"
    ]
    resources = [
      data.aws_dynamodb_table.source_table.arn,
      data.aws_dynamodb_table.destination_table.arn
    ]
  }
  statement {
    actions = [
      "appconfig:GetConfiguration",
      "appconfig:StartConfigurationSession"
    ]
    resources = [
      aws_appconfig_application.lambda_app.arn,
      aws_appconfig_environment.lambda_env.arn,
      aws_appconfig_configuration_profile.lambda_config_profile.arn
    ]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = ["arn:aws:logs:*:*:*"]
  }
}

resource "aws_iam_role" "lambda_exec_role" {
  name               = "${local.project_name}-lambda-exec-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role_policy.json
  tags               = local.tags
}

resource "aws_iam_policy" "lambda_policy" {
  name        = "${local.project_name}-lambda-policy"
  description = "Policy for Lambda to access DynamoDB and AppConfig"
  policy      = data.aws_iam_policy_document.lambda_policy.json
}

resource "aws_iam_role_policy_attachment" "lambda_policy_attach" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.lambda_policy.arn
}
