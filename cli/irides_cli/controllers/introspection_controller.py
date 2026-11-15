"""Controller that maps parsed CLI arguments into introspection DTOs."""

import argparse
from typing import Any

from irides_cli.dto.requests import DescribeRequest, ScopeRequest, TablesRequest
from irides_cli.services.introspection_service import IntrospectionService


class IntrospectionController:
    def __init__(
        self,
        service: IntrospectionService | None = None,
        config_file: str | None = None,
        no_cache: bool = False,
    ) -> None:
        self.service = service or IntrospectionService(
            config_file=config_file, no_cache=no_cache
        )

    def execute(self, args: argparse.Namespace) -> Any:
        if args.command == "configurations":
            return self.service.configurations()
        if args.command == "connect":
            return self.service.connect(args.config_name)
        if args.command == "instances":
            return self.service.instances(
                ScopeRequest(config_name=args.config_name, no_cache=args.no_cache)
            )
        if args.command == "schemas":
            return self.service.schemas(
                ScopeRequest(
                    config_name=args.config_name,
                    instance_name=args.instance_name,
                    no_cache=args.no_cache,
                )
            )
        if args.command == "tables":
            return self.service.tables(
                TablesRequest(
                    config_name=args.config_name,
                    instance_name=args.instance_name,
                    no_cache=args.no_cache,
                    schema_name=args.schema_name,
                    limit=args.limit,
                    offset=args.offset,
                )
            )
        return self.service.describe(
            DescribeRequest(
                config_name=args.config_name,
                instance_name=args.instance_name,
                no_cache=args.no_cache,
                schema_name=args.schema_name,
                table_name=args.table_name,
                generate_ai_docs=args.generate_ai_docs,
                save_metadata=args.save_metadata,
                only_if_changed=args.only_if_changed,
                export_markdown=args.export_markdown,
                export_okf=args.export_okf,
                preformat=args.preformat,
            )
        )
