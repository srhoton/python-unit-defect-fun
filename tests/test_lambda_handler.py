"""Unit tests for the Lambda handler logic.

This module tests the AWS Lambda handler for DynamoDB stream processing,
including insert, update, and delete logic. Uses pytest and moto for mocking.

All test functions and helpers include type hints and Google-style docstrings.
"""

from typing import Any, Dict, Generator, Optional
import pytest
from moto.dynamodb import mock_dynamodb  # type: ignore
import boto3
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add parent directory to Python path to make src importable
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.python_unit_defect_fun import lambda_handler


# Mock Lambda context for testing
class MockLambdaContext:
    """Mock Lambda context for testing."""

    def __init__(self):
        self.function_name = "test-function"
        self.memory_limit_in_mb = 128
        self.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test-function"
        self.aws_request_id = "00000000-0000-0000-0000-000000000000"


TABLE_NAME_SRC = "source-table"
TABLE_NAME_DEST = "destination-table"


@pytest.fixture(autouse=True)
def set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set environment variables for table names and AWS credentials for all tests.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest fixture for patching environment.
    """
    # Table names
    monkeypatch.setenv("sourceTable", TABLE_NAME_SRC)
    monkeypatch.setenv("destinationTable", TABLE_NAME_DEST)

    # Mock AWS credentials
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


# Removed mock_get_appconfig_setting fixture since get_appconfig_setting no longer exists.


@pytest.fixture
def mock_get_appconfig_settings():
    """Mock the get_appconfig_settings function to return test config dict."""
    with patch(
        "src.python_unit_defect_fun.lambda_handler.get_appconfig_settings"
    ) as mock_get_settings:
        mock_get_settings.return_value = {
            "sourceTable": TABLE_NAME_SRC,
            "destinationTable": TABLE_NAME_DEST,
        }
        yield mock_get_settings


@pytest.fixture
def mock_get_table_names():
    """Mock the get_table_names function to return test table names."""
    with patch("src.python_unit_defect_fun.lambda_handler.get_table_names") as mock_table_names:
        mock_table_names.return_value = {"source": TABLE_NAME_SRC, "destination": TABLE_NAME_DEST}
        yield mock_table_names


@pytest.fixture
def mock_boto3_resource():
    """Mock boto3 resource to use our mocked DynamoDB."""
    with patch("src.python_unit_defect_fun.lambda_handler.dynamodb") as mock_resource:
        # This will be set by the dynamodb_tables fixture
        yield mock_resource


@pytest.fixture
def dynamodb_tables(
    mock_get_appconfig_settings, mock_get_table_names, mock_boto3_resource
) -> Generator[Any, None, None]:
    """Create and yield mocked DynamoDB tables for testing.

    Yields:
        Any: The destination DynamoDB table resource.
    """
    with mock_dynamodb():
        dynamodb_resource = boto3.resource("dynamodb", region_name="us-east-1")
        # Source table (not used directly, but for completeness)
        dynamodb_resource.create_table(
            TableName=TABLE_NAME_SRC,
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
        # Destination table
        dest_table = dynamodb_resource.create_table(
            TableName=TABLE_NAME_DEST,
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

        # Setup mock for lambda_handler's dynamodb
        mock_boto3_resource.Table.return_value = dest_table

        yield dest_table


def make_ddb_stream_record(
    event_name: str,
    new_image: Optional[Dict[str, Any]] = None,
    old_image: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a DynamoDB stream record in the format expected by the Lambda handler.

    Args:
        event_name (str): The event name ("INSERT", "MODIFY", "REMOVE").
        new_image (Optional[Dict[str, Any]]): The new image for the record.
        old_image (Optional[Dict[str, Any]]): The old image for the record.

    Returns:
        Dict[str, Any]: The DynamoDB stream record.
    """

    def to_ddb_format(d: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
        return {k: {"S": str(v)} for k, v in d.items()}

    record: Dict[str, Any] = {"eventName": event_name, "dynamodb": {}}
    if new_image:
        record["dynamodb"]["NewImage"] = to_ddb_format(new_image)
    if old_image:
        record["dynamodb"]["OldImage"] = to_ddb_format(old_image)
    return record


def test_insert_creates_customer_unit(dynamodb_tables: Any, mock_boto3_resource: MagicMock) -> None:
    """Test that an INSERT event creates a customerUnit record if customerId matches.

    Args:
        dynamodb_tables (Any): The mocked destination DynamoDB table.
        mock_boto3_resource (MagicMock): Mocked boto3 DynamoDB resource.
    """
    # Pre-populate destination table with customer record
    dynamodb_tables.put_item(Item={"PK": "cust123", "SK": "customer", "foo": "bar"})

    event = {
        "Records": [
            make_ddb_stream_record(
                "INSERT",
                new_image={"customerId": "cust123", "unitId": "unitA", "data": "abc"},
            )
        ]
    }
    resp = lambda_handler.lambda_handler(event, MockLambdaContext())
    assert resp["statusCode"] == 200
    # Should have created a customerUnit record
    item = dynamodb_tables.get_item(Key={"PK": "cust123|unitA", "SK": "customerUnit"}).get("Item")
    assert item is not None
    assert item["customerId"] == "cust123"
    assert item["unitId"] == "unitA"
    assert "createdAt" in item


def test_update_modifies_existing_location_unit(
    dynamodb_tables: Any, mock_boto3_resource: MagicMock
) -> None:
    """Test that a MODIFY event updates an existing locationUnit record.

    Args:
        dynamodb_tables (Any): The mocked destination DynamoDB table.
        mock_boto3_resource (MagicMock): Mocked boto3 DynamoDB resource.
    """
    # Pre-populate destination table with locationUnit record
    dynamodb_tables.put_item(Item={"PK": "loc456|unitB", "SK": "locationUnit", "data": "old"})

    event = {
        "Records": [
            make_ddb_stream_record(
                "MODIFY",
                new_image={"locationId": "loc456", "unitId": "unitB", "data": "new"},
            )
        ]
    }
    resp = lambda_handler.lambda_handler(event, MockLambdaContext())
    assert resp["statusCode"] == 200
    item = dynamodb_tables.get_item(Key={"PK": "loc456|unitB", "SK": "locationUnit"}).get("Item")
    assert item is not None
    assert item["data"] == "new"
    assert "updatedAt" in item


def test_delete_marks_account_unit_deleted(
    dynamodb_tables: Any, mock_boto3_resource: MagicMock
) -> None:
    """Test that a REMOVE event marks an accountUnit record as deleted.

    Args:
        dynamodb_tables (Any): The mocked destination DynamoDB table.
        mock_boto3_resource (MagicMock): Mocked boto3 DynamoDB resource.
    """
    # Pre-populate destination table with accountUnit record
    dynamodb_tables.put_item(Item={"PK": "acct789|unitC", "SK": "accountUnit", "data": "foo"})

    event = {
        "Records": [
            make_ddb_stream_record(
                "REMOVE",
                old_image={"accountId": "acct789", "unitId": "unitC"},
            )
        ]
    }
    resp = lambda_handler.lambda_handler(event, MockLambdaContext())
    assert resp["statusCode"] == 200
    item = dynamodb_tables.get_item(Key={"PK": "acct789|unitC", "SK": "accountUnit"}).get("Item")
    assert item is not None
    assert "deletedAt" in item
