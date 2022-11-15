from tests.utils import alias_export


def test_alias_export(flask_client):
    alias_export(flask_client, "dashboard.alias_export_route")
