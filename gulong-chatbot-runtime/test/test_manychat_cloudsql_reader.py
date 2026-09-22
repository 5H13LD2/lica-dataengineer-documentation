from datetime import datetime

from runtime_v7.manychat_cloudsql_reader import (
    ManyChatCloudSQLReadConfig,
    compare_manychat_message_sets,
    load_manychat_messages_from_cloudsql,
)


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _query, params):
        self.params = params

    def fetchall(self):
        return self.rows


class _FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return _FakeCursor(self.rows)


def test_cloudsql_reader_normalizes_message_rows_without_live_database():
    rows = [
        {
            "user_id": "u1",
            "user_name": "Customer",
            "business_unit": "gulong",
            "datetime": datetime(2026, 7, 9, 10, 2, 0),
            "type": "msgout_lc",
            "role": "human_agent",
            "sender": "Jeanel",
            "message_id": "agent_1",
            "text_content": "Meron po tayong 175/65R14.",
        },
        {
            "user_id": "u1",
            "user_name": "Customer",
            "business_unit": "gulong",
            "datetime": datetime(2026, 7, 9, 10, 1, 0),
            "type": "msgin",
            "role": "user",
            "sender": "Customer",
            "message_id": "user_1",
            "text_content": "hm 175 65 14",
        },
    ]

    result = load_manychat_messages_from_cloudsql(
        user_id="u1",
        limit=10,
        config=ManyChatCloudSQLReadConfig(dsn="postgresql://runtime:test@127.0.0.1/db"),
        connect=lambda *_args, **_kwargs: _FakeConnection(rows),
    )

    assert result["status"] == "success"
    assert result["row_count"] == 2
    assert [row["message_id"] for row in result["data"]] == ["user_1", "agent_1"]
    assert result["data"][0]["source"] == "manychat_cloudsql_messages"
    assert result["data"][1]["role"] == "human_agent"


def test_cloudsql_reader_skips_when_dsn_is_absent(monkeypatch):
    for key in (
        "RUNTIME_V7_MANYCHAT_CLOUDSQL_DSN",
        "RUNTIME_ANALYTICS_POSTGRES_DSN",
        "RUNTIME_POSTGRES_DSN",
        "DATABASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    result = load_manychat_messages_from_cloudsql(user_id="u1")

    assert result["status"] == "skipped"
    assert result["data"] == []


def test_compare_manychat_message_sets_reports_current_message_coverage():
    primary = [
        {"message_id": "m1", "role": "user", "datetime": "2026-07-09 10:00:00", "content": "hm po"},
        {"message_id": "m2", "role": "assistant", "datetime": "2026-07-09 10:00:01", "content": "Sure po."},
    ]
    cloudsql = [
        {"message_id": "m1", "role": "user", "datetime": "2026-07-09 10:00:00", "content": "hm po"},
    ]

    summary = compare_manychat_message_sets(primary, cloudsql, current_message_id="m1", current_user_text="hm po")

    assert summary["match_status"] == "partial"
    assert summary["current_in_cloudsql"] is True
    assert summary["missing_in_cloudsql_count"] == 1


def test_compare_manychat_message_sets_ignores_runtime_synthetic_assistant_ids():
    primary = [
        {"message_id": "m1", "role": "user", "datetime": "2026-07-09 10:00:00", "content": "hm po"},
        {
            "message_id": "assistant_evt_abc123",
            "role": "assistant",
            "datetime": "2026-07-09 10:00:01",
            "content": "Sure po.",
        },
    ]
    cloudsql = [
        {"message_id": "m1", "role": "user", "datetime": "2026-07-09 10:00:00", "content": "hm po"},
    ]

    summary = compare_manychat_message_sets(primary, cloudsql, current_message_id="m1", current_user_text="hm po")

    assert summary["match_status"] == "covered"
    assert summary["ignored_runtime_synthetic_count"] == 1
    assert summary["missing_in_cloudsql_count"] == 0
    assert summary["latest_primary_message_id"] == "m1"


def test_compare_manychat_message_sets_keeps_numeric_current_gaps_visible():
    primary = [
        {"message_id": "m1", "role": "user", "datetime": "2026-07-09 10:00:00", "content": "hm po"},
        {"message_id": "m2", "role": "user", "datetime": "2026-07-09 10:01:00", "content": "available today?"},
    ]
    cloudsql = [
        {"message_id": "m1", "role": "user", "datetime": "2026-07-09 10:00:00", "content": "hm po"},
    ]

    summary = compare_manychat_message_sets(
        primary,
        cloudsql,
        current_message_id="m2",
        current_user_text="available today?",
    )

    assert summary["match_status"] == "current_missing_in_cloudsql"
    assert summary["missing_in_cloudsql_count"] == 1
