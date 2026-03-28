from __future__ import annotations

from typing import Any


def validate_against_json_schema(value: object, schema: dict[str, Any], path: str = "$") -> None:
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object")

        required = schema.get("required", [])
        if isinstance(required, list):
            for field_name in required:
                if field_name not in value:
                    raise ValueError(f"{path}.{field_name} is required")

        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, prop_schema in properties.items():
                if key not in value or not isinstance(prop_schema, dict):
                    continue
                validate_against_json_schema(value[key], prop_schema, f"{path}.{key}")
        return

    if schema_type == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string")
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value.strip()) < min_length:
            raise ValueError(f"{path} must be at least {min_length} characters")
        return

    if schema_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{path} must be a number")
        return

    if schema_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path} must be a boolean")
        return

    if schema_type == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate_against_json_schema(item, item_schema, f"{path}[{index}]")
