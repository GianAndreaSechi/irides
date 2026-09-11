from unittest.mock import Mock

from core.db_connector.connectors.athena import AthenaConnector


def test_describe_table_uses_default_glue_catalog():
    connector = AthenaConnector.__new__(AthenaConnector)
    connector.region = "us-east-1"
    connector.cache_manager = Mock()
    connector.cache_manager.get_cached_data.return_value = None
    connector._glue = Mock()
    connector._glue.get_table.return_value = {
        "Table": {"StorageDescriptor": {"Columns": []}}
    }

    connector.describe_table(
        instance_name="AwsDataCatalog",
        schema_name="databi_be_dynamodb",
        table_name="be_abstrack",
    )

    connector._glue.get_table.assert_called_once_with(
        DatabaseName="databi_be_dynamodb",
        Name="be_abstrack",
    )
