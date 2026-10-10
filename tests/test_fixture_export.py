import json

from sahi.fixtures import export_check_fixtures
from sahi.store import Store
from sahi.web.app import seed_demo_check


def test_export_writes_only_scrubbed_receipts_used_by_check(db_path, tmp_path):
    store = Store(db_path)
    check_id = seed_demo_check(store)
    exported = export_check_fixtures(store, check_id, tmp_path / "recorded")
    assert exported
    for path in exported:
        payload = json.loads(path.read_text())
        rendered = json.dumps(payload)
        assert "api_key" not in rendered
        assert "user" not in rendered
        assert payload["_sahi_fixture"]["cache_key"]
        assert payload["response"]["search_metadata"]["status"] == "Success"
