"""Unit tests for the Python Unit Defect function Lambda handler.

This testing approach uses standard unittest mocking to test the Lambda handler
without relying directly on moto's functionality, making it compatible with CI/CD.
"""

import json
import os
from datetime import datetime
from unittest import mock

import pytest

# This import is included only for CI pipeline compatibility
# It isn't actually used in tests directly, but will be replaced by the pipeline's sed command
try:
    from moto import mock_dynamodb
except ImportError:
    # Just define a dummy decorator for local testing
    def mock_dynamodb(func):
        return func


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


def create_dynamodb_event(event_name, new_image=None, old_image=None):
    """Create a mock DynamoDB Stream event."""
    event = {"Records": [{"eventID": "test-event-id", "eventName": event_name, "dynamodb": {}}]}

    if new_image:
        event["Records"][0]["dynamodb"]["NewImage"] = {
            k: {"S": v} if isinstance(v, str) else {"N": str(v)} for k, v in new_image.items()
        }

    if old_image:
        event["Records"][0]["dynamodb"]["OldImage"] = {
            k: {"S": v} if isinstance(v, str) else {"N": str(v)} for k, v in old_image.items()
        }

    return event


class TestBasicFunctions:
    """Test basic utility functions."""

    def test_get_current_timestamp(self):
        """Test current timestamp generation."""
        timestamp = get_current_timestamp()
        assert isinstance(timestamp, str)
        # Verify ISO 8601 format with timezone info
        datetime.fromisoformat(timestamp)

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


class TestAppConfigFunctions:
    """Test AppConfig interactions."""

    def test_get_table_names(self, mock_appconfig, appconfig_env_vars):
        """Test getting table names from AppConfig."""
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


class TestDynamoDBFunctions:
    """Test DynamoDB functions with mocks."""

    def test_find_matching_record_exists(self):
        """Test finding an existing record."""
        # Create mock table
        mock_table = mock.MagicMock()
        mock_response = {"Item": {"PK": "customer123", "SK": "customer", "data": "value"}}
        mock_table.get_item.return_value = mock_response

        # Test function
        result = find_matching_record(mock_table, "customer123", "customer")

        # Verify results
        mock_table.get_item.assert_called_with(Key={"PK": "customer123", "SK": "customer"})
        assert result == mock_response["Item"]

    def test_find_matching_record_not_exists(self):
        """Test finding a non-existent record."""
        # Create mock table
        mock_table = mock.MagicMock()
        mock_table.get_item.return_value = {}  # No Item

        # Test function
        result = find_matching_record(mock_table, "nonexistent", "customer")

        # Verify results
        mock_table.get_item.assert_called_with(Key={"PK": "nonexistent", "SK": "customer"})
        assert result is None

    def test_process_insert(self):
        """Test process_insert function."""
        # Create mock table
        mock_table = mock.MagicMock()
        mock_table.get_item.side_effect = [
            {"Item": {"PK": "customer123", "SK": "customer"}},  # Parent record exists
            {},  # No existing record
        ]

        # Test data
        record = {"unitId": "unit789", "customerId": "customer123", "model": "Test Model"}
        timestamp = "2025-05-01T12:00:00Z"

        # Test function
        with mock.patch("python_unit_defect_fun.lambda_handler.find_matching_record") as mock_find:
            mock_find.return_value = {"PK": "customer123", "SK": "customer"}
            process_insert(mock_table, record, timestamp)

        # Verify put_item was called with correct data
        expected_item = {
            "PK": "customer123|unit789",
            "SK": "customerUnit",
            "unitId": "unit789",
            "customerId": "customer123",
            "model": "Test Model",
            "createdAt": timestamp,
        }

        # Check if put_item was called with the expected item
        call_args = mock_table.put_item.call_args
        assert call_args is not None
        actual_item = call_args[1]["Item"]
        assert actual_item["PK"] == expected_item["PK"]
        assert actual_item["SK"] == expected_item["SK"]
        assert actual_item["createdAt"] == expected_item["createdAt"]

    def test_process_update(self):
        """Test process_update function."""
        # Create mock table
        mock_table = mock.MagicMock()

        # Test data
        record = {"unitId": "unit456", "customerId": "customer123", "model": "Updated Model"}
        timestamp = "2025-05-01T12:00:00Z"

        # Test function
        with mock.patch("python_unit_defect_fun.lambda_handler.find_matching_record") as mock_find:
            mock_find.return_value = {"PK": "customer123|unit456", "SK": "customerUnit"}
            process_update(mock_table, record, timestamp)

        # Verify update_item was called
        assert mock_table.update_item.called

        # Check update expression includes the timestamp
        update_expr = mock_table.update_item.call_args[1]["UpdateExpression"]
        assert "#updatedAt = :updatedAt" in update_expr

    def test_process_delete(self):
        """Test process_delete function."""
        # Create mock table
        mock_table = mock.MagicMock()

        # Test data
        record = {"unitId": "unit456", "customerId": "customer123"}
        timestamp = "2025-05-01T12:00:00Z"

        # Test function
        with mock.patch("python_unit_defect_fun.lambda_handler.find_matching_record") as mock_find:
            mock_find.return_value = {"PK": "customer123|unit456", "SK": "customerUnit"}
            process_delete(mock_table, record, timestamp)

        # Verify update_item was called with deletedAt
        update_expr = mock_table.update_item.call_args[1]["UpdateExpression"]
        assert "deletedAt = :deletedAt" in update_expr

        # Check that the timestamp was passed
        expr_values = mock_table.update_item.call_args[1]["ExpressionAttributeValues"]
        assert expr_values[":deletedAt"] == timestamp


class TestLambdaHandler:
    """Test the Lambda handler with mocked dependencies."""

    def test_lambda_handler_exception(self, appconfig_env_vars):
        """Test Lambda handler error handling."""
        with mock.patch(
            "python_unit_defect_fun.lambda_handler.get_table_names"
        ) as mock_get_table_names:
            # Simulate an exception
            mock_get_table_names.side_effect = Exception("Test exception")

            event = {"Records": []}
            context = mock.MagicMock()

            response = lambda_handler(event, context)

            assert response["statusCode"] == 500
            assert "Error" in response["body"]

    def test_lambda_handler_insert(self, appconfig_env_vars):
        """Test Lambda handler processes INSERT event."""
        with (
            mock.patch(
                "python_unit_defect_fun.lambda_handler.get_table_names"
            ) as mock_get_table_names,
            mock.patch("python_unit_defect_fun.lambda_handler.dynamodb") as mock_dynamodb,
            mock.patch(
                "python_unit_defect_fun.lambda_handler.process_insert"
            ) as mock_process_insert,
            mock.patch(
                "python_unit_defect_fun.lambda_handler.process_update"
            ) as mock_process_update,
            mock.patch(
                "python_unit_defect_fun.lambda_handler.process_delete"
            ) as mock_process_delete,
        ):
            # Mock table names
            mock_get_table_names.return_value = {
                "source": "source-table",
                "destination": "destination-table",
            }

            # Mock dynamodb Table object
            mock_table = mock.MagicMock()
            mock_dynamodb.Table.return_value = mock_table

            # Test INSERT event
            insert_event = create_dynamodb_event(
                "INSERT", new_image={"unitId": "unit123", "customerId": "customer456"}
            )

            context = mock.MagicMock()
            response = lambda_handler(insert_event, context)

            # Check Lambda handler successfully called process_insert
            mock_process_insert.assert_called_once()
            assert mock_process_update.call_count == 0
            assert mock_process_delete.call_count == 0
            assert response["statusCode"] == 200

    def test_lambda_handler_modify(self, appconfig_env_vars):
        """Test Lambda handler processes MODIFY event."""
        with (
            mock.patch(
                "python_unit_defect_fun.lambda_handler.get_table_names"
            ) as mock_get_table_names,
            mock.patch("python_unit_defect_fun.lambda_handler.dynamodb") as mock_dynamodb,
            mock.patch(
                "python_unit_defect_fun.lambda_handler.process_insert"
            ) as mock_process_insert,
            mock.patch(
                "python_unit_defect_fun.lambda_handler.process_update"
            ) as mock_process_update,
            mock.patch(
                "python_unit_defect_fun.lambda_handler.process_delete"
            ) as mock_process_delete,
        ):
            # Mock table names
            mock_get_table_names.return_value = {
                "source": "source-table",
                "destination": "destination-table",
            }

            # Mock dynamodb Table object
            mock_table = mock.MagicMock()
            mock_dynamodb.Table.return_value = mock_table

            # Test MODIFY event
            modify_event = create_dynamodb_event(
                "MODIFY", new_image={"unitId": "unit123", "customerId": "customer456"}
            )

            context = mock.MagicMock()
            response = lambda_handler(modify_event, context)

            # Check Lambda handler successfully called process_update
            assert mock_process_insert.call_count == 0
            mock_process_update.assert_called_once()
            assert mock_process_delete.call_count == 0
            assert response["statusCode"] == 200

    def test_lambda_handler_remove(self, appconfig_env_vars):
        """Test Lambda handler processes REMOVE event."""
        with (
            mock.patch(
                "python_unit_defect_fun.lambda_handler.get_table_names"
            ) as mock_get_table_names,
            mock.patch("python_unit_defect_fun.lambda_handler.dynamodb") as mock_dynamodb,
            mock.patch(
                "python_unit_defect_fun.lambda_handler.process_insert"
            ) as mock_process_insert,
            mock.patch(
                "python_unit_defect_fun.lambda_handler.process_update"
            ) as mock_process_update,
            mock.patch(
                "python_unit_defect_fun.lambda_handler.process_delete"
            ) as mock_process_delete,
        ):
            # Mock table names
            mock_get_table_names.return_value = {
                "source": "source-table",
                "destination": "destination-table",
            }

            # Mock dynamodb Table object
            mock_table = mock.MagicMock()
            mock_dynamodb.Table.return_value = mock_table

            # Test REMOVE event
            remove_event = create_dynamodb_event(
                "REMOVE", old_image={"unitId": "unit123", "customerId": "customer456"}
            )

            context = mock.MagicMock()
            response = lambda_handler(remove_event, context)

            # Check Lambda handler successfully called process_delete
            assert mock_process_insert.call_count == 0
            assert mock_process_update.call_count == 0
            mock_process_delete.assert_called_once()
            assert response["statusCode"] == 200

    def test_lambda_handler_unknown_event(self, appconfig_env_vars):
        """Test Lambda handler processes UNKNOWN event."""
        with (
            mock.patch(
                "python_unit_defect_fun.lambda_handler.get_table_names"
            ) as mock_get_table_names,
            mock.patch("python_unit_defect_fun.lambda_handler.dynamodb") as mock_dynamodb,
            mock.patch(
                "python_unit_defect_fun.lambda_handler.process_insert"
            ) as mock_process_insert,
            mock.patch(
                "python_unit_defect_fun.lambda_handler.process_update"
            ) as mock_process_update,
            mock.patch(
                "python_unit_defect_fun.lambda_handler.process_delete"
            ) as mock_process_delete,
        ):
            # Mock table names
            mock_get_table_names.return_value = {
                "source": "source-table",
                "destination": "destination-table",
            }

            # Mock dynamodb Table object
            mock_table = mock.MagicMock()
            mock_dynamodb.Table.return_value = mock_table

            # Test unknown event type with full structure
            unknown_event = {
                "Records": [
                    {
                        "eventID": "test-event-id",
                        "eventName": "UNKNOWN",
                        "dynamodb": {"NewImage": {}, "OldImage": {}},
                    }
                ]
            }

            context = mock.MagicMock()
            response = lambda_handler(unknown_event, context)

            # Should return success but not call any process functions
            assert response["statusCode"] == 200
            assert mock_process_insert.call_count == 0
            assert mock_process_update.call_count == 0
            assert mock_process_delete.call_count == 0
