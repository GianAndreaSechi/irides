import pytest
from unittest.mock import MagicMock, patch
from core.db_connector.models import Schema, Table
from core.db_connector.models.table_details import TableDescription, PrimaryKey
from core.db_connector.exporting import ExportOptions
from worker.irides_worker.services.scan_executor_service import ScanExecutorService


def _make_table_desc(schema: str, table: str) -> TableDescription:
    return TableDescription(
        instance_name="host",
        schema_name=schema,
        table_name=table,
        columns=[],
        primary_key=None,
    )


@pytest.fixture
def job_store():
    js = MagicMock()
    return js


@pytest.fixture
def config_service():
    cs = MagicMock()
    cs.get_available_configurations.return_value = ["cfg1"]
    cs.resolve_instance_names.return_value = ["host"]
    connector = MagicMock()
    connector.list_schemas.return_value = [Schema(name="mydb")]
    connector.list_tables.return_value = [Table(name="users", schema_name="mydb")]
    connector.describe_table.return_value = _make_table_desc("mydb", "users")
    cs._get_connector_for_host.return_value = connector
    return cs


@pytest.fixture
def executor(job_store, config_service):
    return ScanExecutorService(job_store, config_service)


class TestExecuteBasic:
    def test_counts_described_tables(self, executor, config_service):
        result = executor.execute("job-1", "cfg1", "host", "mydb")
        assert result.count == 1
        assert result.errors == []

    def test_appends_result_to_job_store(self, executor, job_store):
        executor.execute("job-1", "cfg1", "host", "mydb")
        job_store.append_result.assert_called_once()
        call_kwargs = job_store.append_result.call_args[0]
        assert call_kwargs[0] == "job-1"
        assert call_kwargs[1]["table_name"] == "users"

    def test_resolves_all_configs_when_none(self, executor, config_service):
        config_service.get_available_configurations.return_value = ["cfg1", "cfg2"]
        config_service.resolve_instance_names.return_value = ["host"]
        connector = MagicMock()
        connector.list_schemas.return_value = [Schema(name="db")]
        connector.list_tables.return_value = [Table(name="t", schema_name="db")]
        connector.describe_table.return_value = _make_table_desc("db", "t")
        config_service._get_connector_for_host.return_value = connector

        result = executor.execute("job-1", None, None, None)
        assert result.count == 2

    def test_filters_configs_by_explicit_instance(self, executor, config_service):
        # Replace these generic values only in local integration tests that need real targets.
        config_service.get_available_configurations.return_value = ["primary", "secondary"]
        config_service.configuration_matches_instance.side_effect = (
            lambda config, instance, no_cache: config == "primary"
        )

        result = executor.execute("job-1", None, "db-primary.example.internal", "mydb")

        assert result.count == 1
        config_service.resolve_instance_names.assert_called_once_with(
            "primary", "db-primary.example.internal", False
        )

    def test_multiple_tables_all_counted(self, executor, config_service):
        connector = config_service._get_connector_for_host.return_value
        connector.list_tables.return_value = [
            Table(name="users", schema_name="mydb"),
            Table(name="orders", schema_name="mydb"),
        ]
        connector.describe_table.side_effect = [
            _make_table_desc("mydb", "users"),
            _make_table_desc("mydb", "orders"),
        ]
        result = executor.execute("job-1", "cfg1", "host", "mydb")
        assert result.count == 2


class TestExecuteErrors:
    def test_single_table_error_recorded(self, executor, config_service):
        connector = config_service._get_connector_for_host.return_value
        connector.describe_table.side_effect = RuntimeError("connection lost")
        result = executor.execute("job-1", "cfg1", "host", "mydb")
        assert result.count == 0
        assert len(result.errors) == 1
        assert "connection lost" in result.errors[0]

    def test_error_on_one_table_continues_to_next(self, executor, config_service):
        connector = config_service._get_connector_for_host.return_value
        connector.list_tables.return_value = [
            Table(name="bad", schema_name="mydb"),
            Table(name="good", schema_name="mydb"),
        ]
        connector.describe_table.side_effect = [
            RuntimeError("bad table"),
            _make_table_desc("mydb", "good"),
        ]
        result = executor.execute("job-1", "cfg1", "host", "mydb")
        assert result.count == 1
        assert len(result.errors) == 1

    def test_config_level_error_recorded(self, executor, config_service):
        config_service.resolve_instance_names.side_effect = RuntimeError("no such config")
        result = executor.execute("job-1", "cfg1", "host", "mydb")
        assert result.count == 0
        assert len(result.errors) == 1


class TestExecuteAiDocs:
    def test_ai_docs_attached_when_enabled(self, executor, job_store):
        ai_doc = {"summary": "User table", "column_descriptions": {}}
        mock_ai_service = MagicMock()
        mock_ai_service.generate_table_documentation.return_value = ai_doc
        mock_ai_service.last_error = None

        with patch(
            "worker.irides_worker.services.scan_executor_service.AIDocumentationService",
            return_value=mock_ai_service,
        ):
            executor.execute("job-1", "cfg1", "host", "mydb", generate_ai_docs=True)

        call_args = job_store.append_result.call_args[0][1]
        assert call_args["ai_documentation"] == ai_doc
        assert call_args["ai_generation_status"] == "generated"

    def test_ai_failure_sets_status_failed(self, executor, job_store):
        mock_ai_service = MagicMock()
        mock_ai_service.generate_table_documentation.return_value = None
        mock_ai_service.last_error = "API error"

        with patch(
            "worker.irides_worker.services.scan_executor_service.AIDocumentationService",
            return_value=mock_ai_service,
        ):
            executor.execute("job-1", "cfg1", "host", "mydb", generate_ai_docs=True)

        call_args = job_store.append_result.call_args[0][1]
        assert call_args["ai_generation_status"] == "failed"
        assert call_args["ai_generation_error"] == "API error"

    def test_ai_docs_not_in_result_when_disabled(self, executor, job_store):
        executor.execute("job-1", "cfg1", "host", "mydb", generate_ai_docs=False)
        call_args = job_store.append_result.call_args[0][1]
        assert "ai_documentation" not in call_args


class TestExecuteMetadata:
    def test_metadata_saved_when_enabled(self, executor):
        mock_store = MagicMock()
        with patch(
            "worker.irides_worker.services.scan_executor_service.get_metadata_store",
            return_value=mock_store,
        ):
            executor.execute("job-1", "cfg1", "host", "mydb", save_metadata=True)

        mock_store.save_table_metadata.assert_called_once()

    def test_store_not_used_when_metadata_and_exports_are_disabled(self, executor):
        mock_store = MagicMock()
        with patch(
            "worker.irides_worker.services.scan_executor_service.get_metadata_store",
            return_value=mock_store,
        ):
            executor.execute(
                "job-1",
                "cfg1",
                "host",
                "mydb",
                save_metadata=False,
                export_options=ExportOptions(formats=[]),
            )

        mock_store.save_table_metadata.assert_not_called()

    def test_exports_run_when_metadata_is_disabled(self, executor):
        mock_store = MagicMock()
        with patch(
            "worker.irides_worker.services.scan_executor_service.get_metadata_store",
            return_value=mock_store,
        ):
            executor.execute("job-1", "cfg1", "host", "mydb", save_metadata=False)

        mock_store.save_table_metadata.assert_called_once()
        assert mock_store.save_table_metadata.call_args.kwargs["save_metadata"] is False
