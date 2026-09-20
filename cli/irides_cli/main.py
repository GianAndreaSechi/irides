"""CLI composition root and process-level error handling."""

import json
import sys
from pathlib import Path
from typing import Any, List, Optional
from dotenv import load_dotenv

from irides_cli.controllers.init_controller import InitController
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
    if args.command == "init":
        return InitController().execute(fmt=args.format, force=args.force)
    if args.command == "metadata":
        return MetadataController().execute(args)

    config_file = getattr(args, "config_file", None)
    controller = IntrospectionController(config_file=config_file)
    result = controller.execute(args)
    if args.command == "configurations" and isinstance(result, list) and len(result) == 0:
        print(
            "irides: notice: no database targets configured. Run 'irides init' to generate a configuration template or check your .env.",
            file=sys.stderr,
        )
    return result


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    load_dotenv(dotenv_path=Path.cwd() / ".env")

    env_file = getattr(args, "env_file", None)
    if env_file:
        load_dotenv(dotenv_path=env_file, override=True)

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
