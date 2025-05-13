# Terraform Infrastructure for python-unit-defect-fun

This directory contains Terraform code to provision AWS infrastructure for the `python-unit-defect-fun` Lambda function, including AppConfig, DynamoDB tables, and deployment resources.

## Structure

- `main.tf` – Main resources and module calls
- `variables.tf` – Input variables with descriptions and types
- `outputs.tf` – Outputs for key resources
- `providers.tf` – Provider and backend configuration
- `versions.tf` – Required provider and Terraform versions

## Features

- **Remote State:** Uses S3 backend (`srhoton-tfstate`) for storing Terraform state securely.
- **AppConfig:** Provisions AWS AppConfig application, environment, and configuration profile for Lambda configuration.
- **DynamoDB:** Creates source and destination DynamoDB tables.
- **Lambda:** Builds and deploys the Lambda function, granting necessary IAM permissions.
- **Best Practices:** Follows naming, tagging, security, and formatting best practices.

## Usage

1. **Initialize Terraform:**
   ```sh
   terraform init
   ```

2. **Validate the configuration:**
   ```sh
   terraform validate
   ```

3. **Plan the deployment:**
   ```sh
   terraform plan
   ```

4. **Apply the changes:**
   ```sh
   terraform apply
   ```

## Variables

See `variables.tf` for all configurable inputs, including:

- `lambda_function_name`
- `appconfig_application_name`
- `source_table_name`
- `destination_table_name`
- `aws_region`
- And more...

## Outputs

See `outputs.tf` for available outputs, such as:

- Lambda function ARN
- AppConfig configuration profile ID
- DynamoDB table names

## Requirements

- Terraform >= 1.3.0
- AWS provider >= 5.0
- Access to an AWS account with permissions to create the required resources

## Formatting & Linting

- Run `terraform fmt` before committing changes.
- Use `tflint` and `terraform validate` for best practices and error checking.

## Security

- No credentials or secrets are stored in code.
- IAM roles follow least privilege.
- DynamoDB and S3 state are encrypted.

## Tagging

All resources are tagged with:
- `Project`
- `Environment`
- `Owner`
- `ManagedBy`

## State Backend

State is stored in the S3 bucket: `srhoton-tfstate`.

## License

MIT License. See [../LICENSE](../LICENSE).

---

For more details, see comments in each `.tf` file.