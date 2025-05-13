"""Unit tests for the Python Unit Defect function Lambda handler.

These tests use the moto library to mock AWS services, particularly DynamoDB.
"""

import os
import json
import sys
from datetime import datetime, timezone
from unittest import mock
from typing import Dict, Any, List, Optional

import boto3
import pytest
from botocore.exceptions import ClientError

# Handle different moto import styles across different versions
try:
    # Try moto 4.x style import (from specific service module)
    from moto.dynamodb import mock_dynamodb

    print("Using moto.dynamodb import style")
except ImportError:
    try:
        # Try moto direct import style
        from moto import mock_dynamodb

        print("Using direct moto import style")
    except ImportError:
        # Fall back to newer mock_aws approach
        from moto import mock_aws

        mock_dynamodb = mock_aws
        print("Using mock_aws fallback for dynamodb")

from python_unit_defect_fun.lambda_handler import (
    get_table_names,
    get_current_timestamp,
    find_matching_record,
    build_pk_sk,
    process_insert,
    process_update,
    process_delete,
    lambda_handler,
)


@pytest.fixture
def aws_credentials():
    """Set up mock AWS credentials for tests."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["AWS_REGION"] = "us-east-1"


@pytest.fixture
def appconfig_env_vars():
    """Set up AppConfig environment variables for tests."""
    # Save original values
    original_values = {}
    for key in [
        "APPCONFIG_APPLICATION_ID",
        "APPCONFIG_ENVIRONMENT_ID",
        "APPCONFIG_CONFIG_PROFILE_ID",
    ]:
        original_values[key] = os.environ.get(key)

    # Set test values
    os.environ["APPCONFIG_APPLICATION_ID"] = "test-app-id"
    os.environ["APPCONFIG_ENVIRONMENT_ID"] = "test-env-id"
    os.environ["APPCONFIG_CONFIG_PROFILE_ID"] = "test-profile-id"

    yield

    # Restore original values
    for key, value in original_values.items():
        if value is not None:
            os.environ[key] = value
        else:
            if key in os.environ:
                del os.environ[key]


def setup_dynamodb_tables():
    """Create and setup DynamoDB tables for testing."""
    # Create source table
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    source_table = dynamodb.create_table(
        TableName="source-table",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
        StreamSpecification={
            "StreamEnabled": True,
            "StreamViewType": "NEW_AND_OLD_IMAGES",
        },
    )

    # Create destination table
    dest_table = dynamodb.create_table(
        TableName="destination-table",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    # Add sample data to destination table
    dest_table.put_item(
        Item={
            "PK": "customer123",
            "SK": "customer",
            "name": "Test Customer",
            "email": "test@example.com",
        }
    )

    dest_table.put_item(
        Item={
            "PK": "location456",
            "SK": "location",
            "name": "Test Location",
            "address": "123 Test St",
        }
    )

    dest_table.put_item(
        Item={
            "PK": "account789",
            "SK": "account",
            "name": "Test Account",
            "status": "active",
        }
    )

    # Add an existing unit record for update/delete testing
    dest_table.put_item(
        Item={
            "PK": "customer123|unit456",
            "SK": "customerUnit",
            "unitId": "unit456",
            "customerId": "customer123",
            "model": "Test Model",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
    )

    return {"source": source_table, "destination": dest_table}


@pytest.fixture
def mock_appconfig():
    """Mock AppConfig client and responses."""
    with mock.patch("boto3.client") as mock_client:
        mock_appconfig = mock.MagicMock()
        mock_client.return_value = mock_appconfig

        # Mock start_configuration_session
        mock_appconfig.start_configuration_session.return_value = {
            "InitialConfigurationToken": "test-token"
        }

        # Mock get_latest_configuration
        config = {
            "sourceTable": "source-table",
            "destinationTable": "destination-table",
        }
        mock_appconfig.get_latest_configuration.return_value = {
            "Configuration": json.dumps(config).encode("utf-8")
        }

        yield mock_appconfig


def create_dynamodb_event(
    event_name: str,
    new_image: Optional[Dict[str, Any]] = None,
    old_image: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a mock DynamoDB Stream event.

    Args:
        event_name: The event type (INSERT, MODIFY, REMOVE)
        new_image: New image data (for INSERT and MODIFY)
        old_image: Old image data (for MODIFY and REMOVE)

    Returns:
        A dictionary representing a DynamoDB Stream event
    """
    event: Dict[str, Any] = {
        "Records": [{"eventID": "test-event-id", "eventName": event_name, "dynamodb": {}}]
    }

    if new_image:
        event["Records"][0]["dynamodb"]["NewImage"] = {
            k: {"S": v} if isinstance(v, str) else {"N": str(v)} for k, v in new_image.items()
        }

    if old_image:
        event["Records"][0]["dynamodb"]["OldImage"] = {
            k: {"S": v} if isinstance(v, str) else {"N": str(v)} for k, v in old_image.items()
        }

    return event


@mock_dynamodb
class TestLambdaHelperFunctions:
    """Test case for Lambda helper functions."""

    def test_get_table_names(self, mock_appconfig, appconfig_env_vars):
        """Test getting table names from AppConfig."""
        # Directly mock get_appconfig_settings to return the expected configuration
        with mock.patch(
            "python_unit_defect_fun.lambda_handler.get_appconfig_settings"
        ) as mock_get_config:
            mock_get_config.return_value = {
                "sourceTable": "source-table",
                "destinationTable": "destination-table",
            }

            table_names = get_table_names()
            assert table_names["source"] == "source-table"
            assert table_names["destination"] == "destination-table"

    def test_get_current_timestamp(self):
        """Test current timestamp generation."""
        timestamp = get_current_timestamp()
        assert isinstance(timestamp, str)
        # Verify ISO 8601 format with timezone info
        datetime.fromisoformat(timestamp)

    def test_find_matching_record_exists(self, aws_credentials):
        """Test finding an existing record."""
        tables = setup_dynamodb_tables()
        table = tables["destination"]
        record = find_matching_record(table, "customer123", "customer")
        assert record is not None
        assert record["PK"] == "customer123"
        assert record["SK"] == "customer"

    def test_find_matching_record_not_exists(self, aws_credentials):
        """Test finding a non-existent record."""
        tables = setup_dynamodb_tables()
        table = tables["destination"]
        record = find_matching_record(table, "nonexistent", "customer")
        assert record is None

    def test_build_pk_sk_customer(self):
        """Test building PK/SK for customer."""
        record = {"customerId": "customer123", "unitId": "unit456"}
        pk_sk = build_pk_sk(record, "customer")
        assert pk_sk == {"PK": "customer123|unit456", "SK": "customerUnit"}

    def test_build_pk_sk_location(self):
        """Test building PK/SK for location."""
        record = {"locationId": "location456", "unitId": "unit456"}
        pk_sk = build_pk_sk(record, "location")
        assert pk_sk == {"PK": "location456|unit456", "SK": "locationUnit"}

    def test_build_pk_sk_account(self):
        """Test building PK/SK for account."""
        record = {"accountId": "account789", "unitId": "unit456"}
        pk_sk = build_pk_sk(record, "account")
        assert pk_sk == {"PK": "account789|unit456", "SK": "accountUnit"}

    def test_build_pk_sk_missing_unit_id(self):
        """Test building PK/SK with missing unit ID."""
        record = {"customerId": "customer123"}
        pk_sk = build_pk_sk(record, "customer")
        assert pk_sk is None

    def test_build_pk_sk_missing_parent_id(self):
        """Test building PK/SK with missing parent ID."""
        record = {"unitId": "unit456"}
        pk_sk = build_pk_sk(record, "customer")
        assert pk_sk is None


@mock_dynamodb
class TestProcessInsert:
    """Test case for process_insert function."""

    def test_process_insert_customer(self, aws_credentials):
        """Test inserting a record with customer association."""
        tables = setup_dynamodb_tables()
        dest_table = tables["destination"]
        record = {
            "unitId": "unit789",
            "customerId": "customer123",
            "model": "Test Model",
            "serialNumber": "SN12345",
        }
        timestamp = get_current_timestamp()

        process_insert(dest_table, record, timestamp)

        # Verify record was created
        response = dest_table.get_item(Key={"PK": "customer123|unit789", "SK": "customerUnit"})
        assert "Item" in response
        assert response["Item"]["unitId"] == "unit789"
        assert response["Item"]["customerId"] == "customer123"
        assert "createdAt" in response["Item"]

    def test_process_insert_location(self, aws_credentials):
        """Test inserting a record with location association."""
        tables = setup_dynamodb_tables()
        dest_table = tables["destination"]
        record = {
            "unitId": "unit789",
            "locationId": "location456",
            "model": "Test Model",
            "serialNumber": "SN12345",
        }
        timestamp = get_current_timestamp()

        process_insert(dest_table, record, timestamp)

        # Verify record was created
        response = dest_table.get_item(Key={"PK": "location456|unit789", "SK": "locationUnit"})
        assert "Item" in response
        assert response["Item"]["unitId"] == "unit789"
        assert response["Item"]["locationId"] == "location456"
        assert "createdAt" in response["Item"]

    def test_process_insert_account(self, aws_credentials):
        """Test inserting a record with account association."""
        tables = setup_dynamodb_tables()
        dest_table = tables["destination"]
        record = {
            "unitId": "unit789",
            "accountId": "account789",
            "model": "Test Model",
            "serialNumber": "SN12345",
        }
        timestamp = get_current_timestamp()

        process_insert(dest_table, record, timestamp)

        # Verify record was created
        response = dest_table.get_item(Key={"PK": "account789|unit789", "SK": "accountUnit"})
        assert "Item" in response
        assert response["Item"]["unitId"] == "unit789"
        assert response["Item"]["accountId"] == "account789"
        assert "createdAt" in response["Item"]

    def test_process_insert_priority_order(self, aws_credentials):
        """Test inserting with multiple IDs respects priority (customer > location > account)."""
        tables = setup_dynamodb_tables()
        dest_table = tables["destination"]
        record = {
            "unitId": "unit789",
            "customerId": "customer123",
            "locationId": "location456",
            "accountId": "account789",
            "model": "Test Model",
        }
        timestamp = get_current_timestamp()

        process_insert(dest_table, record, timestamp)

        # Verify customer record was created (highest priority)
        response = dest_table.get_item(Key={"PK": "customer123|unit789", "SK": "customerUnit"})
        assert "Item" in response

        # Verify location record was NOT created
        response = dest_table.get_item(Key={"PK": "location456|unit789", "SK": "locationUnit"})
        assert "Item" not in response

        # Verify account record was NOT created
        response = dest_table.get_item(Key={"PK": "account789|unit789", "SK": "accountUnit"})
        assert "Item" not in response

    def test_process_insert_no_match(self, aws_credentials):
        """Test inserting a record with no matching parent IDs."""
        tables = setup_dynamodb_tables()
        dest_table = tables["destination"]
        record = {
            "unitId": "unit789",
            "customerId": "nonexistent",
            "locationId": "nonexistent",
            "model": "Test Model",
        }
        timestamp = get_current_timestamp()

        process_insert(dest_table, record, timestamp)

        # Verify no record was created for customer
        response = dest_table.get_item(Key={"PK": "nonexistent|unit789", "SK": "customerUnit"})
        assert "Item" not in response

        # Verify no record was created for location
        response = dest_table.get_item(Key={"PK": "nonexistent|unit789", "SK": "locationUnit"})
        assert "Item" not in response


@mock_dynamodb
class TestProcessUpdate:
    """Test case for process_update function."""

    def test_process_update_existing_record(self, aws_credentials):
        """Test updating an existing record."""
        tables = setup_dynamodb_tables()
        dest_table = tables["destination"]
        record = {
            "unitId": "unit456",
            "customerId": "customer123",
            "model": "Updated Model",
            "serialNumber": "SN-UPDATED",
        }
        timestamp = get_current_timestamp()

        process_update(dest_table, record, timestamp)

        # Verify record was updated
        response = dest_table.get_item(Key={"PK": "customer123|unit456", "SK": "customerUnit"})
        assert "Item" in response
        assert response["Item"]["model"] == "Updated Model"
        assert response["Item"]["serialNumber"] == "SN-UPDATED"
        assert "updatedAt" in response["Item"]

    def test_process_update_nonexistent_record(self, aws_credentials):
        """Test updating a non-existent record."""
        tables = setup_dynamodb_tables()
        dest_table = tables["destination"]
        record = {"unitId": "nonexistent", "customerId": "customer123", "model": "Updated Model"}
        timestamp = get_current_timestamp()

        process_update(dest_table, record, timestamp)

        # Verify no record was created or updated
        response = dest_table.get_item(Key={"PK": "customer123|nonexistent", "SK": "customerUnit"})
        assert "Item" not in response


@mock_dynamodb
class TestProcessDelete:
    """Test case for process_delete function."""

    def test_process_delete_existing_record(self, aws_credentials):
        """Test deleting (marking as deleted) an existing record."""
        tables = setup_dynamodb_tables()
        dest_table = tables["destination"]
        record = {"unitId": "unit456", "customerId": "customer123"}
        timestamp = get_current_timestamp()

        process_delete(dest_table, record, timestamp)

        # Verify record was marked as deleted
        response = dest_table.get_item(Key={"PK": "customer123|unit456", "SK": "customerUnit"})
        assert "Item" in response
        assert "deletedAt" in response["Item"]

    def test_process_delete_nonexistent_record(self, aws_credentials):
        """Test deleting a non-existent record."""
        tables = setup_dynamodb_tables()
        dest_table = tables["destination"]
        record = {"unitId": "nonexistent", "customerId": "customer123"}
        timestamp = get_current_timestamp()

        process_delete(dest_table, record, timestamp)

        # Verify no record was created or updated
        response = dest_table.get_item(Key={"PK": "customer123|nonexistent", "SK": "customerUnit"})
        assert "Item" not in response


@mock_dynamodb
class TestLambdaHandler:
    """Test case for the main Lambda handler."""

    @mock.patch("python_unit_defect_fun.lambda_handler.get_table_names")
    @mock.patch("python_unit_defect_fun.lambda_handler.dynamodb")
    def test_lambda_handler_insert(
        self, mock_dynamodb_resource, mock_get_table_names, aws_credentials, appconfig_env_vars
    ):
        """Test Lambda handler with INSERT event."""
        # Set up tables first
        tables = setup_dynamodb_tables()
        dynamodb_resource = boto3.resource("dynamodb")

        # Make the mock DynamoDB resource use our boto3 resource
        mock_dynamodb_resource.Table.side_effect = lambda name: dynamodb_resource.Table(name)

        mock_get_table_names.return_value = {
            "source": "source-table",
            "destination": "destination-table",
        }

        event = create_dynamodb_event(
            "INSERT",
            new_image={
                "unitId": "unit999",
                "customerId": "customer123",
                "model": "New Model",
                "serialNumber": "SN999",
            },
        )

        context = mock.MagicMock()

        response = lambda_handler(event, context)

        assert response["statusCode"] == 200

        # Verify record was created using the same dynamodb resource
        dest_table = dynamodb_resource.Table("destination-table")
        response = dest_table.get_item(Key={"PK": "customer123|unit999", "SK": "customerUnit"})
        assert "Item" in response
        assert response["Item"]["model"] == "New Model"

    @mock.patch("python_unit_defect_fun.lambda_handler.get_table_names")
    @mock.patch("python_unit_defect_fun.lambda_handler.dynamodb")
    def test_lambda_handler_modify(
        self, mock_dynamodb_resource, mock_get_table_names, aws_credentials, appconfig_env_vars
    ):
        """Test Lambda handler with MODIFY event."""
        # Set up tables first
        tables = setup_dynamodb_tables()
        dynamodb_resource = boto3.resource("dynamodb")

        # Make the mock DynamoDB resource use our boto3 resource
        mock_dynamodb_resource.Table.side_effect = lambda name: dynamodb_resource.Table(name)

        mock_get_table_names.return_value = {
            "source": "source-table",
            "destination": "destination-table",
        }

        event = create_dynamodb_event(
            "MODIFY",
            new_image={
                "unitId": "unit456",
                "customerId": "customer123",
                "model": "Updated via Lambda",
                "serialNumber": "SN-LAMBDA",
            },
        )

        context = mock.MagicMock()

        response = lambda_handler(event, context)

        assert response["statusCode"] == 200

        # Verify record was updated using the same dynamodb resource
        dest_table = dynamodb_resource.Table("destination-table")
        response = dest_table.get_item(Key={"PK": "customer123|unit456", "SK": "customerUnit"})
        assert "Item" in response
        assert response["Item"]["model"] == "Updated via Lambda"

    @mock.patch("python_unit_defect_fun.lambda_handler.get_table_names")
    @mock.patch("python_unit_defect_fun.lambda_handler.dynamodb")
    def test_lambda_handler_remove(
        self, mock_dynamodb_resource, mock_get_table_names, aws_credentials, appconfig_env_vars
    ):
        """Test Lambda handler with REMOVE event."""
        # Set up tables first
        tables = setup_dynamodb_tables()
        dynamodb_resource = boto3.resource("dynamodb")

        # Make the mock DynamoDB resource use our boto3 resource
        mock_dynamodb_resource.Table.side_effect = lambda name: dynamodb_resource.Table(name)

        mock_get_table_names.return_value = {
            "source": "source-table",
            "destination": "destination-table",
        }

        event = create_dynamodb_event(
            "REMOVE",
            old_image={"unitId": "unit456", "customerId": "customer123", "model": "Test Model"},
        )

        context = mock.MagicMock()

        response = lambda_handler(event, context)

        assert response["statusCode"] == 200

        # Verify record was marked as deleted using the same dynamodb resource
        dest_table = dynamodb_resource.Table("destination-table")
        response = dest_table.get_item(Key={"PK": "customer123|unit456", "SK": "customerUnit"})
        assert "Item" in response
        assert "deletedAt" in response["Item"]

    @mock.patch("python_unit_defect_fun.lambda_handler.get_table_names")
    @mock.patch("python_unit_defect_fun.lambda_handler.dynamodb")
    def test_lambda_handler_unknown_event(
        self, mock_dynamodb_resource, mock_get_table_names, aws_credentials, appconfig_env_vars
    ):
        """Test Lambda handler with unknown event type."""
        # Set up tables first
        tables = setup_dynamodb_tables()
        dynamodb_resource = boto3.resource("dynamodb")

        # Make the mock DynamoDB resource use our boto3 resource
        mock_dynamodb_resource.Table.side_effect = lambda name: dynamodb_resource.Table(name)

        mock_get_table_names.return_value = {
            "source": "source-table",
            "destination": "destination-table",
        }

        event = {"Records": [{"eventID": "test-event-id", "eventName": "UNKNOWN", "dynamodb": {}}]}

        context = mock.MagicMock()

        response = lambda_handler(event, context)

        assert response["statusCode"] == 200

    @mock.patch("python_unit_defect_fun.lambda_handler.get_table_names")
    @mock.patch("python_unit_defect_fun.lambda_handler.dynamodb")
    def test_lambda_handler_exception(
        self, mock_dynamodb_resource, mock_get_table_names, appconfig_env_vars
    ):
        """Test Lambda handler error handling."""
        # Set up dynamodb mock
        dynamodb_resource = boto3.resource("dynamodb")
        mock_dynamodb_resource.Table.side_effect = lambda name: dynamodb_resource.Table(name)

        mock_get_table_names.side_effect = Exception("Test exception")

        event = {"Records": []}
        context = mock.MagicMock()

        response = lambda_handler(event, context)

        assert response["statusCode"] == 500
        assert "Error" in response["body"]
