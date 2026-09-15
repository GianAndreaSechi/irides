"""CLI composition root and process-level error handling."""

import json
import sys
from typing import Any, List, Optional

from irides_cli.controllers.introspection_controller import IntrospectionController
from irides_cli.controllers.metadata_controller import MetadataController
from irides_cli.presentation.parser import build_parser


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"): return value.model_dump(mode="json")
    if hasattr(value, "dict"): return value.dict()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def print_json(data: Any) -> None:
    print(json.dumps(data, default=_json_default, ensure_ascii=False, indent=2))


def run(args: Any) -> Any:
    return MetadataController().execute(args) if args.command == "metadata" else IntrospectionController().execute(args)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
        if result is None: raise ValueError("No metadata found.")
        print_json(result)
        return 0
    except (ConnectionError, ValueError, json.JSONDecodeError) as error:
        print(f"irides: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"irides: unexpected error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
