"""AWS Lambda handler for processing DynamoDB stream events and updating unit information.

This Lambda reads configuration from AWS AppConfig, processes DynamoDB stream records,
and writes/updates/deletes records in a destination DynamoDB table according to business logic.

Requires:
    - boto3
    - aws-lambda-powertools (for logging, tracing, metrics)
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from mypy_boto3_dynamodb.service_resource import Table

logger = Logger()
tracer = Tracer()

dynamodb = boto3.resource("dynamodb")
ssm = boto3.client("ssm")
appconfig = boto3.client("appconfigdata")


def get_appconfig_setting(setting_name: str) -> str:
    """Fetch a setting from AWS AppConfig via environment variable or fallback to SSM Parameter Store.

    Args:
        setting_name (str): The name of the setting to fetch.

    Returns:
        str: The value of the setting as a string.

    Raises:
        RuntimeError: If the setting cannot be found.
    """
    value = os.environ.get(setting_name)
    if value:
        return value

    try:
        param = ssm.get_parameter(Name=setting_name, WithDecryption=True)
        return str(param["Parameter"]["Value"])
    except Exception as exc:
        logger.error(f"Failed to fetch setting '{setting_name}': {exc}")
        raise RuntimeError(f"Missing required setting: {setting_name}") from exc


def get_table_names() -> Dict[str, str]:
    """Get source and destination DynamoDB table names from AppConfig.

    Returns:
        Dict[str, str]: Dictionary with 'source' and 'destination' table names.
    """
    source_table = get_appconfig_setting("sourceTable")
    destination_table = get_appconfig_setting("destinationTable")
    return {"source": source_table, "destination": destination_table}


def get_current_timestamp() -> str:
    """Return current UTC timestamp in ISO 8601 format.

    Returns:
        str: Current UTC timestamp in ISO 8601 format.
    """
    return datetime.now(timezone.utc).isoformat()


def find_matching_record(table: Table, pk_value: str, sk_value: str) -> Optional[Dict[str, Any]]:
    """Query DynamoDB for a record with the given PK and SK.

    Args:
        table (Table): DynamoDB Table resource.
        pk_value (str): Partition key value.
        sk_value (str): Sort key value.

    Returns:
        Optional[Dict[str, Any]]: The matching item if found, else None.
    """
    response = table.get_item(Key={"PK": pk_value, "SK": sk_value})
    return response.get("Item")


def build_pk_sk(record: Dict[str, Any], key_type: str) -> Optional[Dict[str, str]]:
    """Build PK and SK for the destination table based on key_type.

    Args:
        record (Dict[str, Any]): The DynamoDB record.
        key_type (str): One of 'customer', 'location', or 'account'.

    Returns:
        Optional[Dict[str, str]]: Dictionary with PK and SK if possible, else None.
    """
    unit_id = record.get("unitId")
    if not unit_id:
        return None
    if key_type == "customer":
        customer_id = record.get("customerId")
        if customer_id:
            return {"PK": f"{customer_id}|{unit_id}", "SK": "customerUnit"}
    elif key_type == "location":
        location_id = record.get("locationId")
        if location_id:
            return {"PK": f"{location_id}|{unit_id}", "SK": "locationUnit"}
    elif key_type == "account":
        account_id = record.get("accountId")
        if account_id:
            return {"PK": f"{account_id}|{unit_id}", "SK": "accountUnit"}
    return None


def process_insert(dest_table: Table, record: Dict[str, Any], timestamp: str) -> None:
    """Process an INSERT event.

    Args:
        dest_table (Table): The destination DynamoDB table.
        record (Dict[str, Any]): The new record data.
        timestamp (str): The current timestamp.
    """
    for key_type in ["customer", "location", "account"]:
        pk_sk = build_pk_sk(record, key_type)
        if pk_sk:
            match = find_matching_record(dest_table, pk_sk["PK"].split("|")[0], key_type)
            if match or key_type == "account":
                item = {
                    **pk_sk,
                    **record,
                    "createdAt": timestamp,
                }
                dest_table.put_item(Item=item)
                logger.info(f"Created record: {item}")
                return
    logger.info("Cannot create record: No matching customerId, locationId, or accountId found.")


def process_update(dest_table: Table, record: Dict[str, Any], timestamp: str) -> None:
    """Process an UPDATE event.

    Args:
        dest_table (Table): The destination DynamoDB table.
        record (Dict[str, Any]): The updated record data.
        timestamp (str): The current timestamp.
    """
    for key_type in ["customer", "location", "account"]:
        pk_sk = build_pk_sk(record, key_type)
        if pk_sk:
            match = find_matching_record(dest_table, pk_sk["PK"], pk_sk["SK"])
            if match:
                update_expr = "SET "
                expr_attr_values: Dict[str, Any] = {}
                expr_attr_names: Dict[str, str] = {}
                for k, v in record.items():
                    attr_name = f"#{k}"
                    update_expr += f"{attr_name} = :{k}, "
                    expr_attr_values[f":{k}"] = v
                    expr_attr_names[attr_name] = k
                update_expr += "#updatedAt = :updatedAt"
                expr_attr_values[":updatedAt"] = timestamp
                expr_attr_names["#updatedAt"] = "updatedAt"
                dest_table.update_item(
                    Key=pk_sk,
                    UpdateExpression=update_expr,
                    ExpressionAttributeValues=expr_attr_values,
                    ExpressionAttributeNames=expr_attr_names,
                )
                logger.info(f"Updated record: {pk_sk}")
                return
    logger.info("Cannot update record: No matching record found.")


def process_delete(dest_table: Table, record: Dict[str, Any], timestamp: str) -> None:
    """Process a DELETE event.

    Args:
        dest_table (Table): The destination DynamoDB table.
        record (Dict[str, Any]): The record data to delete.
        timestamp (str): The current timestamp.
    """
    for key_type in ["customer", "location", "account"]:
        pk_sk = build_pk_sk(record, key_type)
        if pk_sk:
            match = find_matching_record(dest_table, pk_sk["PK"], pk_sk["SK"])
            if match:
                dest_table.update_item(
                    Key=pk_sk,
                    UpdateExpression="SET deletedAt = :deletedAt",
                    ExpressionAttributeValues={":deletedAt": timestamp},
                )
                logger.info(f"Marked record as deleted: {pk_sk}")
                return
    logger.info("Cannot delete record: No matching record found.")


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def lambda_handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """Main Lambda handler for DynamoDB stream events.

    Args:
        event (Dict[str, Any]): The Lambda event payload, expected to be a DynamoDB stream event.
        context (LambdaContext): The Lambda context object.

    Returns:
        Dict[str, Any]: A response dictionary with statusCode and body.
    """
    table_names = get_table_names()
    dest_table = dynamodb.Table(table_names["destination"])
    timestamp = get_current_timestamp()

    for record in event.get("Records", []):
        event_name = record.get("eventName")
        new_image = record.get("dynamodb", {}).get("NewImage", {})
        old_image = record.get("dynamodb", {}).get("OldImage", {})
        # Convert DynamoDB types to plain dict
        new_record = {k: list(v.values())[0] for k, v in new_image.items()} if new_image else {}
        old_record = {k: list(v.values())[0] for k, v in old_image.items()} if old_image else {}

        if event_name == "INSERT":
            process_insert(dest_table, new_record, timestamp)
        elif event_name == "MODIFY":
            process_update(dest_table, new_record, timestamp)
        elif event_name == "REMOVE":
            process_delete(dest_table, old_record, timestamp)
        else:
            logger.warning(f"Unknown eventName: {event_name}")

    return {"statusCode": 200, "body": "Success"}
