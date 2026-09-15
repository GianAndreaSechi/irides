"""Controller for metadata commands and payload validation."""

import argparse
import json
from typing import Any

from irides_cli.dto.requests import MetadataUpdateRequest, PageRequest
from irides_cli.services.metadata_service import MetadataService


class MetadataController:
    def __init__(self, service: MetadataService | None = None) -> None:
        self.service = service or MetadataService()

    def execute(self, args: argparse.Namespace) -> Any:
        page = PageRequest(args.page, args.page_size) if hasattr(args, "page") else None
        if args.metadata_command == "instances": return self.service.instances(page)
        if args.metadata_command == "databases": return self.service.databases(args.instance, page)
        if args.metadata_command == "tables": return self.service.tables(args.instance, args.database, page)
        if args.metadata_command == "get": return self.service.get(args.instance, args.database, args.table)
        payload = json.loads(args.payload)
        if not isinstance(payload, dict): raise ValueError("Metadata payload must be a JSON object.")
        return self.service.update(MetadataUpdateRequest(args.instance, args.database, args.table, payload))
