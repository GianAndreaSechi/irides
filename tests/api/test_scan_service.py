from unittest.mock import MagicMock

import pytest

from api.irides_api.services.scan_service import ScanService


def test_enqueue_resolves_unique_configuration_from_instance():
    job_store = MagicMock()
    config_service = MagicMock()
    # Replace these generic values only in local integration tests that need a real target.
    config_service.resolve_configurations_for_instance.return_value = ["mysql_primary"]
    service = ScanService(job_store, config_service)

    service.enqueue_scan(None, "db-primary.example.internal", "example_schema")

    scope = job_store.enqueue.call_args.args[0]
    assert scope.config_name == "mysql_primary"
    assert scope.instance_name == "db-primary.example.internal"


def test_enqueue_rejects_unknown_instance():
    job_store = MagicMock()
    config_service = MagicMock()
    config_service.resolve_configurations_for_instance.return_value = []
    service = ScanService(job_store, config_service)

    with pytest.raises(ValueError, match="does not belong"):
        service.enqueue_scan(None, "unknown-host", None)
