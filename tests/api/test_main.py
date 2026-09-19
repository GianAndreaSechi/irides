import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from core.db_connector.models import Instance, Schema, Table
from core.db_connector.models.table_details import TableDescription
from core.db_connector.models.scan_job import ScanJob, ScanScope, ScanStatus
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Shared mocks applied before the app module is imported
# ---------------------------------------------------------------------------

_FAKE_INSTANCE = Instance(name="db.host.local")
_FAKE_SCHEMA = Schema(name="mydb")
_FAKE_TABLE = Table(name="users", schema_name="mydb")
_FAKE_TABLE_DESC = TableDescription(
    instance_name="db.host.local",
    schema_name="mydb",
    table_name="users",
    columns=[],
)
_FAKE_JOB = ScanJob(
    job_id="test-job-id",
    status=ScanStatus.PENDING,
    scope=ScanScope(config_name="cfg"),
    created_at=datetime.now(timezone.utc),
)

_FAKE_INSTANCES_PAGE = {"items": ["db.host.local"], "total": 1, "page": 1, "page_size": 20, "pages": 1}
_FAKE_DATABASES_PAGE = {"items": ["mydb"], "total": 1, "page": 1, "page_size": 20, "pages": 1}
_FAKE_TABLES_PAGE = {"items": ["users"], "total": 1, "page": 1, "page_size": 20, "pages": 1}
_FAKE_TABLE_META = {
    "metadata_key": "cfg::db.host.local::mydb::users",
    "config_name": "cfg",
    "instance_name": "db.host.local",
    "schema_name": "mydb",
    "table_name": "users",
    "updated_at": "2024-01-01T00:00:00+00:00",
    "schema_description": {},
    "ai_documentation": None,
}
_EMPTY_PAGE = {"items": [], "total": 0, "page": 1, "page_size": 20, "pages": 0}


@pytest.fixture(scope="module")
def client():
    mock_config_service = MagicMock()
    mock_config_service.get_available_configurations.return_value = ["mysql_dev"]
    mock_config_service.test_connection.return_value = {"message": "Successfully connected to all hosts in mysql_dev."}

    mock_instance_service = MagicMock()
    mock_instance_service.list_instances.return_value = [_FAKE_INSTANCE]

    mock_schema_service = MagicMock()
    mock_schema_service.list_schemas.return_value = [_FAKE_SCHEMA]

    mock_table_service = MagicMock()
    mock_table_service.list_tables.return_value = [_FAKE_TABLE]

    mock_describe_service = MagicMock()
    mock_describe_service.describe_table.return_value = [_FAKE_TABLE_DESC]

    mock_scan_service = MagicMock()
    mock_scan_service.enqueue_scan.return_value = _FAKE_JOB
    mock_scan_service.get_job.return_value = _FAKE_JOB
    mock_scan_service.get_job_results.return_value = []
    mock_scan_service.list_jobs.return_value = [_FAKE_JOB]

    mock_metadata_service = MagicMock()
    mock_metadata_service.list_instances.return_value = _FAKE_INSTANCES_PAGE
    mock_metadata_service.list_databases.return_value = _FAKE_DATABASES_PAGE
    mock_metadata_service.list_tables.return_value = _FAKE_TABLES_PAGE
    mock_metadata_service.get_table.return_value = _FAKE_TABLE_META
    mock_metadata_service.update_table.return_value = _FAKE_TABLE_META

    with (
        patch("api.irides_api.main.CacheManager"),
        patch("api.irides_api.main.ConnectorManager"),
        patch("api.irides_api.main.ConfigService", return_value=mock_config_service),
        patch("api.irides_api.main.InstanceService", return_value=mock_instance_service),
        patch("api.irides_api.main.SchemaService", return_value=mock_schema_service),
        patch("api.irides_api.main.TableService", return_value=mock_table_service),
        patch("api.irides_api.main.DescribeTableService", return_value=mock_describe_service),
        patch("api.irides_api.main.JobStore"),
        patch("api.irides_api.main.ScanService", return_value=mock_scan_service),
        patch("api.irides_api.routers.metadata_router._metadata_service", mock_metadata_service),
    ):
        from api.irides_api.main import app
        yield TestClient(app)


class TestHealthEndpoints:
    def test_root_returns_200(self, client):
        resp = client.get("/api/v1/")
        assert resp.status_code == 200
        assert "message" in resp.json()

    def test_ping_returns_pong(self, client):
        resp = client.get("/api/v1/ping")
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Pong!"
        assert data["data"]["status"] == "success"


class TestConfigurationsEndpoint:
    def test_returns_config_names(self, client):
        resp = client.get("/api/v1/configurations")
        assert resp.status_code == 200
        assert "mysql_dev" in resp.json()["data"]


class TestConnectEndpoint:
    def test_successful_connection(self, client):
        resp = client.post("/api/v1/connect", json={"config_name": "mysql_dev"})
        assert resp.status_code == 200
        assert "Successfully connected" in resp.json()["data"]["message"]

    def test_unknown_config_returns_400(self, client):
        with patch("api.irides_api.main.config_service") as mock_cs:
            mock_cs.test_connection.side_effect = ValueError("not found")
            resp = client.post("/api/v1/connect", json={"config_name": "unknown"})
        assert resp.status_code == 400


class TestInstancesEndpoint:
    def test_returns_instances(self, client):
        resp = client.post("/api/v1/instances", json={"config_name": "mysql_dev"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["name"] == "db.host.local"

    def test_no_cache_header_accepted(self, client):
        resp = client.post(
            "/api/v1/instances",
            json={"config_name": "mysql_dev"},
            headers={"no-cache": "true"},
        )
        assert resp.status_code == 200


class TestSchemasEndpoint:
    def test_returns_schemas(self, client):
        resp = client.post(
            "/api/v1/schemas",
            json={"config_name": "mysql_dev", "instance_name": "db.host.local"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data[0]["name"] == "mydb"


class TestTablesEndpoint:
    def test_returns_tables(self, client):
        resp = client.post(
            "/api/v1/tables",
            json={
                "config_name": "mysql_dev",
                "instance_name": "db.host.local",
                "schema_name": "mydb",
            },
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data[0]["name"] == "users"


class TestDescribeEndpoint:
    def test_returns_table_description(self, client):
        resp = client.post(
            "/api/v1/describe",
            json={
                "config_name": "mysql_dev",
                "instance_name": "db.host.local",
                "schema_name": "mydb",
                "table_name": "users",
            },
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data[0]["table_name"] == "users"

    def test_only_if_changed_param_accepted(self, client):
        resp = client.post(
            "/api/v1/describe",
            json={
                "config_name": "mysql_dev",
                "instance_name": "db.host.local",
                "schema_name": "mydb",
                "table_name": "users",
                "only_if_changed": True,
            },
        )
        assert resp.status_code == 200

    def test_export_opt_out_is_accepted(self, client):
        resp = client.post(
            "/api/v1/describe",
            json={"export_options": {"formats": [], "preformat": False}},
        )
        assert resp.status_code == 200


class TestScanEndpoints:
    def test_enqueue_returns_202(self, client):
        resp = client.post(
            "/api/v1/scan",
            json={"config_name": "mysql_dev"},
        )
        assert resp.status_code == 202
        assert resp.json()["data"]["job_id"] == "test-job-id"

    def test_default_scope_exposes_both_exports(self, client):
        resp = client.post("/api/v1/scan", json={"config_name": "mysql_dev"})
        options = resp.json()["data"]["scope"]["export_options"]
        assert options == {"formats": ["markdown", "okf"], "preformat": True}

    def test_get_scan_job(self, client):
        resp = client.get("/api/v1/scan/test-job-id")
        assert resp.status_code == 200
        assert resp.json()["data"]["job_id"] == "test-job-id"

    def test_get_scan_job_not_found(self, client):
        with patch("api.irides_api.main.scan_service") as mock_ss:
            mock_ss.get_job.return_value = None
            resp = client.get("/api/v1/scan/nonexistent")
        assert resp.status_code == 404

    def test_list_scans(self, client):
        resp = client.get("/api/v1/scans")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1

    def test_get_scan_with_results(self, client):
        resp = client.get("/api/v1/scan/test-job-id?include_results=true")
        assert resp.status_code == 200
        assert "results" in resp.json()["data"]


class TestMetadataEndpoints:
    def test_list_instances_returns_200(self, client):
        resp = client.get("/api/v1/metadata")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["items"] == ["db.host.local"]
        assert data["total"] == 1

    def test_list_instances_pagination_params_accepted(self, client):
        resp = client.get("/api/v1/metadata?page=1&page_size=10")
        assert resp.status_code == 200

    def test_list_databases_returns_200(self, client):
        resp = client.get("/api/v1/metadata/db.host.local")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "mydb" in data["items"]

    def test_list_databases_returns_404_when_empty(self, client):
        import api.irides_api.routers.metadata_router as meta_router
        with patch.object(meta_router, "_metadata_service") as mock:
            mock.list_databases.return_value = _EMPTY_PAGE
            resp = client.get("/api/v1/metadata/unknown_host")
        assert resp.status_code == 404

    def test_list_tables_returns_200(self, client):
        resp = client.get("/api/v1/metadata/db.host.local/mydb")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "users" in data["items"]

    def test_list_tables_returns_404_when_empty(self, client):
        import api.irides_api.routers.metadata_router as meta_router
        with patch.object(meta_router, "_metadata_service") as mock:
            mock.list_tables.return_value = _EMPTY_PAGE
            resp = client.get("/api/v1/metadata/db.host.local/nonexistent_db")
        assert resp.status_code == 404

    def test_get_table_detail_returns_200(self, client):
        resp = client.get("/api/v1/metadata/db.host.local/mydb/users")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["table_name"] == "users"
        assert data["instance_name"] == "db.host.local"

    def test_get_table_detail_returns_404(self, client):
        import api.irides_api.routers.metadata_router as meta_router
        with patch.object(meta_router, "_metadata_service") as mock:
            mock.get_table.return_value = None
            resp = client.get("/api/v1/metadata/db.host.local/mydb/nonexistent")
        assert resp.status_code == 404

    def test_patch_table_returns_200(self, client):
        resp = client.patch(
            "/api/v1/metadata/db.host.local/mydb/users",
            json={"owner": "data-team", "tags": ["pii"]},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["table_name"] == "users"

    def test_patch_table_returns_422_for_empty_payload(self, client):
        resp = client.patch(
            "/api/v1/metadata/db.host.local/mydb/users",
            json={},
        )
        assert resp.status_code == 422

    def test_patch_table_returns_404_when_not_found(self, client):
        import api.irides_api.routers.metadata_router as meta_router
        with patch.object(meta_router, "_metadata_service") as mock:
            mock.update_table.return_value = None
            resp = client.patch(
                "/api/v1/metadata/db.host.local/mydb/nonexistent",
                json={"owner": "team"},
            )
        assert resp.status_code == 404


class TestUIEndpoint:
    def test_ui_returns_html(self, client):
        with patch("api.irides_api.main._UI_FILE") as mock_file:
            mock_file.read_text.return_value = "<html><body>UI</body></html>"
            resp = client.get("/ui")
        assert resp.status_code == 200
        assert "html" in resp.headers["content-type"]
