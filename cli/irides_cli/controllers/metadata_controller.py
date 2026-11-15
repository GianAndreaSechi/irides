"""Controller for metadata commands and payload validation."""

import argparse
import json
from typing import Any

from core.db_connector.exporting import ExportFormat, ExportOptions
from irides_cli.dto.requests import MetadataUpdateRequest, PageRequest
from irides_cli.services.metadata_service import MetadataService


class MetadataController:
    def __init__(self, service: MetadataService | None = None) -> None:
        self.service = service or MetadataService()

    def execute(self, args: argparse.Namespace) -> Any:
        config_name = getattr(args, "config_name", None)
        page = PageRequest(page=args.page, page_size=args.page_size) if hasattr(args, "page") else None
        if args.metadata_command == "instances":
            return self.service.instances(page, config_name=config_name)
        if args.metadata_command == "databases":
            return self.service.databases(args.instance, page, config_name=config_name)
        if args.metadata_command == "tables":
            return self.service.tables(args.instance, args.database, page, config_name=config_name)
        if args.metadata_command == "get":
            return self.service.get(args.instance, args.database, args.table, config_name=config_name)
        if args.metadata_command == "export":
            formats = []
            if getattr(args, "export_markdown", True):
                formats.append(ExportFormat.MARKDOWN)
            if getattr(args, "export_okf", True):
                formats.append(ExportFormat.OKF)
            options = ExportOptions(formats=formats, preformat=getattr(args, "preformat", True))
            return self.service.export_all(options=options, config_name=config_name)

        payload = json.loads(args.payload)
        if not isinstance(payload, dict):
            raise ValueError("Metadata payload must be a JSON object.")
        return self.service.update(
            MetadataUpdateRequest(
                instance_name=args.instance,
                database_name=args.database,
                table_name=args.table,
                payload=payload,
                config_name=config_name,
            )
        )
