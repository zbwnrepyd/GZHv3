import json
import os
from jsonschema import Draft202012Validator, ValidationError

_SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), '..', '..', 'contracts', 'render_contract.schema.json'
)


class ContractValidator:
    """Validates a RenderContract dict against render_contract.schema.json.

    Uses JSON Schema Draft 2020-12 via jsonschema.
    """

    _schema = None

    @classmethod
    def _load_schema(cls):
        if cls._schema is None:
            with open(_SCHEMA_PATH, 'r') as f:
                cls._schema = json.load(f)
        return cls._schema

    @classmethod
    def validate(cls, contract_dict: dict):
        """Validate a render contract dict.

        Returns True if valid, otherwise raises jsonschema.ValidationError.
        """
        schema = cls._load_schema()
        validator = Draft202012Validator(schema)
        errors = list(validator.iter_errors(contract_dict))
        if errors:
            raise ValidationError(
                f"RenderContract validation failed with {len(errors)} error(s): "
                + "; ".join(str(e) for e in errors)
            )
        return True
