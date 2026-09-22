from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Mapping, Iterable, Tuple, cast, Callable
import json
from channels.manychat.session import ManychatSession
from runtime.storage.bigquery import bigquery_client
from apps.shared.schemas.data_update_schema import BQ_SCHEMAS
from configs.log_utils import get_logger, manila_tz

from apps.gulong.chat_analysis.main import run_chat_analysis
from apps.gulong.chat_analysis.persistence import (
    ChatAnalysisRepository,
    build_chat_analysis_record,
)

logger = get_logger(__file__, level = "WARNING")


@dataclass
class WriteOutcome:
    """Lightweight record of a single BigQuery write attempt."""

    table: str
    key_columns: Tuple[str, ...]
    rows: int
    stream_ok: bool = False
    fallback_used: bool = False
    error: Optional[str] = None


class DataUpdateMetrics:
    """
    Collects per-writer BigQuery outcomes plus optional queue depth hints.
    Keeps things testable without coupling to a specific metrics backend.
    """

    def __init__(self) -> None:
        self.writes: List[WriteOutcome] = []
        self.queue_depths: List[int] = []

    def record_write(self, outcome: WriteOutcome) -> None:
        self.writes.append(outcome)

    def record_queue_depth(self, depth: int) -> None:
        self.queue_depths.append(depth)

    def summary(self) -> Dict[str, Any]:
        return {
            "writes": [o.__dict__ for o in self.writes],
            "fallback_count": sum(1 for o in self.writes if o.fallback_used),
            "stream_success_count": sum(1 for o in self.writes if o.stream_ok),
            "queue_depth_max": max(self.queue_depths) if self.queue_depths else 0,
        }

# ---------------------------
# Helpers (module-internal)
# ---------------------------

def _now_str() -> str:
    """Manila time (GMT+8) as 'YYYY-MM-DD HH:MM:SS' for BigQuery DATETIME."""
    from datetime import datetime
    return datetime.now(manila_tz).strftime("%Y-%m-%d %H:%M:%S")


def _stream_with_fallback(
    bq: bigquery_client.BigQueryUtils,
    rows: Iterable[Dict[str, Any]] | Dict[str, Any],
    *,
    schema_name: str,
    key_columns: Sequence[str],
    table_label: Optional[str] = None,
    metrics: Optional[DataUpdateMetrics] = None,
    use_many: bool = False,
) -> WriteOutcome:
    """
    Stream rows first; on failure, fall back to an upsert and surface the outcome.
    """
    # Normalize rows into a list[dict] whether caller passed a single dict or an iterable of dicts.
    rows_list: List[Dict[str, Any]]
    if isinstance(rows, dict):
        rows_list = [cast(Dict[str, Any], rows)]
    else:
        rows_list = list(rows)

    outcome = WriteOutcome(
        table=table_label or bq.table_id or schema_name,
        key_columns=tuple(key_columns),
        rows=len(rows_list),
    )

    if not rows_list:
        if metrics:
            metrics.record_write(outcome)
        return outcome

    try:
        insert_outcome = bq.insert_rows(
            rows_list,
            schema=BQ_SCHEMAS[schema_name],
            key_columns=list(key_columns),
        )
        if isinstance(insert_outcome, dict):
            outcome.stream_ok = bool(insert_outcome.get("stream_ok"))
            outcome.fallback_used = bool(insert_outcome.get("fallback_used"))
            if insert_outcome.get("error"):
                outcome.error = str(insert_outcome.get("error"))
        else:
            outcome.stream_ok = True
    except Exception as exc:
        outcome.error = str(exc)
        outcome.fallback_used = True
        logger.warning(
            "Streaming insert failed for table=%s keys=%s rows=%s: %s",
            outcome.table,
            list(key_columns),
            len(rows_list),
            outcome.error,
        )
        if use_many or len(rows_list) > 1:
            rep = bq.upsert_many_json(
                rows_list,
                schema=BQ_SCHEMAS[schema_name],
                key_cols=list(key_columns),
            )
        else:
            rep = bq.upsert_json(
                rows_list[0],
                schema=BQ_SCHEMAS[schema_name],
                key_cols=list(key_columns),
            )
        if rep.get("status") != "success":
            if metrics:
                metrics.record_write(outcome)
            raise RuntimeError(rep.get("message", "Unknown BigQuery error"))

    if metrics:
        metrics.record_write(outcome)
    return outcome

# ---------------------------
# Session-integrated functions
# ---------------------------

def analysis_with_session(session: ManychatSession, limit: int = 150, run_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Run chat analysis via the main pipeline and adapt it to the legacy convo_analysis payload.
    """
    run_id = run_id or session.task_id or session._make_task_id(session.user_id)
    result = run_chat_analysis(
        user_id=session.user_id,
        platform="manychat",
        source=session.infer_source(),
        message_limit=limit,
        run_id=run_id,
        task_id=run_id,
        save_to_bigquery=False,
    )
    if result.get("status") != "success":
        raise RuntimeError(result.get("error_message") or "Chat analysis failed")

    payload = result.get("data") or {}
    if not isinstance(payload, dict):
        raise RuntimeError("Chat analysis produced no data")

    analysis: Dict[str, Any] = dict(payload)
    analysis["user_id"] = str(session.user_id)
    analysis["user_name"] = session.user_name
    analysis["start_datetime"] = result.get("start_datetime") or payload.get("start_datetime") or _now_str()
    analysis["end_datetime"] = result.get("end_datetime") or payload.get("end_datetime") or _now_str()
    analysis["customer_source"] = analysis.get("source") or session.infer_source()
    analysis["version"] = payload.get("version") or "v2"
    analysis["task_id"] = session.task_id
    analysis["platform"] = analysis.get("platform") or "manychat"
    analysis["run_id"] = analysis.get("run_id") or analysis.get("task_id") or f"analysis-{session.user_id}"
    analysis["extracted_data"] = analysis.get("extracted_data") or {}
    analysis["stats"] = analysis.get("stats") or {}
    analysis["gates"] = analysis.get("gates") or {}
    analysis["intent_rating"] = analysis.get("intent_rating") or {}
    analysis["tokens"] = analysis.get("tokens") or {}
    analysis["pipeline_timings"] = analysis.get("pipeline_timings") or {}
    return analysis

def save_analysis(
    analysis: Dict[str, Any],
    *,
    metrics: Optional[DataUpdateMetrics] = None,
    bq_factory: Optional[Callable[..., bigquery_client.BigQueryUtils]] = None,
) -> WriteOutcome:
    """
    Persist the chat analysis payload using the chat-analysis repository (chat_analysis_data).

    This aligns the schema with the output of run_chat_analysis instead of the legacy convo_analysis table.
    """
    if not analysis.get("user_id"):
        raise RuntimeError("analysis.user_id is missing/empty")

    analysis["user_id"] = str(analysis["user_id"])
    analysis.setdefault("run_id", analysis.get("task_id") or f"analysis-{analysis['user_id']}")
    analysis.setdefault("platform", "manychat")
    analysis.setdefault("extracted_data", {})
    analysis.setdefault("stats", {})
    analysis.setdefault("gates", {})
    intent_val = analysis.get("intent_rating") or {}
    if not isinstance(intent_val, dict):
        intent_val = {"label": str(intent_val)}
    analysis["intent_rating"] = intent_val

    tokens_val = analysis.get("tokens") or {}
    if isinstance(tokens_val, int):
        tokens_val = {"total_tokens": tokens_val}
    analysis["tokens"] = tokens_val
    analysis.setdefault("pipeline_timings", {})

    analysis_id, row = build_chat_analysis_record(analysis)
    repo = ChatAnalysisRepository()
    repo.save_run(row)

    outcome = WriteOutcome(
        table=repo.settings.runs_table_id,
        key_columns=("run_id",),
        rows=1,
        stream_ok=True,
    )
    if metrics:
        metrics.record_write(outcome)
    return outcome


def save_analysis_v1(
    analysis: Dict[str, Any],
    *,
    metrics: Optional[DataUpdateMetrics] = None,
    bq_factory: Optional[Callable[..., bigquery_client.BigQueryUtils]] = None,
) -> WriteOutcome:
    """Backwards-compatible alias for save_analysis."""
    return save_analysis(analysis, metrics=metrics, bq_factory=bq_factory)
    
def save_user_data_with_session(
    session: ManychatSession,
    *,
    metrics: Optional[DataUpdateMetrics] = None,
    bq_factory: Optional[Callable[..., bigquery_client.BigQueryUtils]] = None,
) -> Optional[Dict[str, Any]]:
    """Write user snapshot to its table using the session's cached user_info."""
    user_resp = session.get_user_info()

    status = user_resp.get("status")
    payload = user_resp.get("data")
    if status != "success" or not isinstance(payload, dict):
        logger.warning(
            "Skipping user data save for %s (%s): %s",
            session.user_name,
            session.user_id,
            user_resp.get("message") or status or "unknown error",
        )
        return None

    factory = bq_factory or bigquery_client.BigQueryUtils
    bq_util = factory(
        project_id="gulong-chatbot-459723",
        dataset_id="manychat_data",
        table_id="users",
    )
    outcome = _stream_with_fallback(
        bq_util,
        payload,
        schema_name="user_data",
        key_columns=["user_id", "user_name"],
        metrics=metrics,
    )
    if outcome.fallback_used and outcome.error:
        logger.warning("Streaming user snapshot failed for %s: %s", session.user_name, outcome.error)
    return payload


def _sync_agent_custom_fields(
    session: ManychatSession,
    agent_data: Mapping[str, Any],
    *,
    metrics: Optional[DataUpdateMetrics] = None,
    bq_factory: Optional[Callable[..., bigquery_client.BigQueryUtils]] = None,
) -> List[str]:
    """
    Ensure custom fields reflect latest agent info (Agent Assigned / Agent Last Sender).
    Behavior:
      - Skips writes when the new value is None/empty.
      - Updates existing CFs only when the value actually changes.
      - Creates CFs only when missing AND a non-empty value is provided.
      - Returns a list of warnings (non-fatal).
    """
    warnings: List[str] = []

    def _sanitize_cf_value(v: Any):
        # set_cf_by_name expects str | int | bool; convert None/complex types to an acceptable form
        if v is None:
            return ""
        if isinstance(v, (str, int, bool)):
            return v
        return str(v)

    try:
        ui = session.get_user_info()  # cached
        data = ui.get("data") or {}
        custom_fields = data.get("custom_fields") or []
        if not custom_fields:
            return warnings  # nothing to do

        agent_assigned = agent_data.get("agent_assigned")
        agent_last_sender = agent_data.get("agent_last_sender")

        found_agent_assigned = False
        found_last_sender = False
        changed = False

        for cf in custom_fields:
            name = cf.get("name")
            value = cf.get("value")
            if name == "Agent Assigned":
                found_agent_assigned = True
                if agent_assigned and agent_assigned != value:
                    safe_val = _sanitize_cf_value(agent_assigned)
                    res = session.mc.set_cf_by_name("Agent Assigned", safe_val)
                    if res.get("status") != "success":
                        raise RuntimeError(f"Error setting Agent Assigned to {agent_assigned}: {res.get('message')}")
                    changed = True

            elif name == "Agent Last Sender":
                found_last_sender = True
                if agent_last_sender and agent_last_sender != value:
                    safe_val = _sanitize_cf_value(agent_last_sender)
                    res = session.mc.set_cf_by_name("Agent Last Sender", safe_val)
                    if res.get("status") != "success":
                        raise RuntimeError(f"Error setting Agent Last Sender to {agent_last_sender}: {res.get('message')}")
                    changed = True

        # create if missing
        if not found_agent_assigned and agent_assigned:
            safe_val = _sanitize_cf_value(agent_assigned)
            res = session.mc.set_cf_by_name("Agent Assigned", safe_val)
            if res.get("status") != "success":
                raise RuntimeError(f"Error setting Agent Assigned to {agent_assigned}: {res.get('message')}")
            changed = True

        if not found_last_sender and agent_last_sender:
            safe_val = _sanitize_cf_value(agent_last_sender)
            res = session.mc.set_cf_by_name("Agent Last Sender", safe_val)
            if res.get("status") != "success":
                raise RuntimeError(f"Error setting Agent Last Sender to {agent_last_sender}: {res.get('message')}")
            changed = True

        # If CFs changed, upsert the user snapshot (reuses cached user_info)
        if changed:
            try:
                save_user_data_with_session(session, metrics=metrics, bq_factory=bq_factory)
            except Exception as e:
                warnings.append(f"User Data update warning: {e}")

    except Exception as e:
        warnings.append(str(e))

    return warnings

def save_agent_data_with_session(
    session: ManychatSession,
    *,
    metrics: Optional[DataUpdateMetrics] = None,
    bq_factory: Optional[Callable[..., bigquery_client.BigQueryUtils]] = None,
) -> Dict[str, Any]:
    """
    Save assigned agent info (+history) for a user using a single session.

    Steps
    -----
    1) Fetch agent data (reuses cached messages when possible).
    2) Sync custom fields 'Agent Assigned' and 'Agent Last Sender' if they differ.
    3) Upsert current assignment and full history to BigQuery tables:
       - manychat_live.assigned_agent

    Returns
    -------
    Dict[str, Any]
        The agent data payload that was written (current + history info).
    """
    # 1) Get agent data (this will reuse session.mc._messages_data if already loaded)
    agent_resp = session.get_agent_data()
    if agent_resp.get("status") == "error":
        raise RuntimeError(agent_resp.get("message", "Failed to fetch agent data"))

    data = agent_resp.get("data") or {}
    history = list(data.get("history") or [])

    # 2) Sync custom fields (async)
    warnings = _sync_agent_custom_fields(session, data, metrics=metrics, bq_factory=bq_factory)
    for w in warnings:
        logger.warning("Custom-field sync warning for %s: %s", session.user_name, w)

    # 3) Write to BigQuery (event history)
    if not history:
        return data

    # Newest first (you already want latest first)
    history_sorted = sorted(history, key=lambda x: x.get("assigned_datetime") or "", 
                            reverse=True)

    now = _now_str()
    rows_norm: List[Dict[str, Any]] = []
    for row in history_sorted:
        r = dict(row)
        r["updated_datetime"] = now

        # Ensure user_id is a string
        r["user_id"] = str(r.get("user_id") or session.user_id)

        # Ensure we always have a stable message_id key
        mid = r.get("message_id")
        if not mid:
            # build a surrogate key that’s stable for this event
            mid = f"assign:{r.get('assigned_datetime') or 'NA'}:{r.get('type') or 'NA'}"
        r["message_id"] = str(mid)
        r["task_id"] = session.task_id

        rows_norm.append(r)

    # Deduplicate within this batch by (user_id, message_id), keeping the first
    # (list is newest-first, so we keep the most recent)
    deduped: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for r in rows_norm:
        k = (r["user_id"], r["message_id"])
        if k in seen:
            continue
        seen.add(k)
        deduped.append(r)

    if not deduped:
        return data

    # 3) Write to BigQuery
    factory = bq_factory or bigquery_client.BigQueryUtils
    bq_hist = factory(
        project_id="gulong-chatbot-459723", 
        dataset_id="manychat_data", 
        table_id="assigned_agent"
    )

    outcome = _stream_with_fallback(
        bq_hist,
        deduped,
        schema_name="agent_data",
        key_columns=["user_id", "message_id"],
        metrics=metrics,
        use_many=True,
    )
    if outcome.fallback_used and outcome.error:
        logger.warning("Streaming agent history failed for %s: %s", session.user_name, outcome.error)

    return data

def save_tags_with_session(
    session: ManychatSession,
    *,
    metrics: Optional[DataUpdateMetrics] = None,
    bq_factory: Optional[Callable[..., bigquery_client.BigQueryUtils]] = None,
) -> None:
    """
    Upsert tag events into BigQuery (table: manychat_staging.tags_data).
    Uses session.mc.get_tags_data() which reuses cached messages when available.
    """
    resp = session.mc.get_tags_data()
    if resp.get("status") == "error":
        raise RuntimeError(resp.get("message", "Failed to fetch tags"))

    rows: List[Dict[str, Any]] = resp.get("data") or []
    if not rows:
        return

    # Dedup within this batch by (user_id, message_id); keep the last one seen
    dedup: dict[tuple[str, str], dict] = {}
    dropped_missing = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        uid = str(row.get("user_id") or "")
        mid = str(row.get("message_id") or "")
        if not uid or not mid:
            dropped_missing += 1
            continue
        rec = dict(row)
        rec["updated_datetime"] = _now_str()
        dedup[(uid, mid)] = rec

    rows = list(dedup.values())
    if not rows:
        return

    factory = bq_factory or bigquery_client.BigQueryUtils
    bq = factory(
        project_id="gulong-chatbot-459723",
        dataset_id="manychat_data",
        table_id="tags_data",
    )

    outcome = _stream_with_fallback(
        bq,
        rows,
        schema_name="tags_data",
        key_columns=["user_id", "message_id"],
        metrics=metrics,
        use_many=True,
    )
    if outcome.fallback_used and outcome.error:
        logger.warning("Streaming tag rows failed for %s: %s", session.user_name, outcome.error)

def save_cfs_with_session(
    session: ManychatSession,
    *,
    metrics: Optional[DataUpdateMetrics] = None,
    bq_factory: Optional[Callable[..., bigquery_client.BigQueryUtils]] = None,
) -> None:
    """
    Upsert custom-field set events into BigQuery (table: manychat_staging.custom_fields_history).
    Uses session.mc.get_cfs_data() which reuses cached messages when available.
    """
    resp = session.mc.get_cfs_data()
    if resp.get("status") == "error":
        raise RuntimeError(resp.get("message", "Failed to fetch custom fields"))

    rows: List[Dict[str, Any]] = resp.get("data") or []
    if not rows:
        return

    # Dedup within this batch by (user_id, message_id); keep the last one seen
    dedup: dict[tuple[str, str], dict] = {}
    dropped_missing = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        uid = str(row.get("user_id") or "")
        mid = str(row.get("message_id") or "")
        if not uid or not mid:
            dropped_missing += 1
            continue
        rec = dict(row)
        rec["updated_datetime"] = _now_str()
        dedup[(uid, mid)] = rec

    rows = list(dedup.values())
    if not rows:
        return

    factory = bq_factory or bigquery_client.BigQueryUtils
    bq = factory(
        project_id="gulong-chatbot-459723",
        dataset_id="manychat_data",
        table_id="cfs_data",
    )

    outcome = _stream_with_fallback(
        bq,
        rows,
        schema_name="cfs_data",
        key_columns=["user_id", "message_id"],
        metrics=metrics,
        use_many=True,
    )
    if outcome.fallback_used and outcome.error:
        logger.warning("Streaming custom field rows failed for %s: %s", session.user_name, outcome.error)


def normalize_message_row(msg: Mapping[str, Any], session: ManychatSession) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "updated_datetime": _now_str(),
        "datetime": msg.get("datetime"),
        "type": msg.get("type"),
        "user_id": str(msg.get("user_id") or session.user_id),
        "user_name": msg.get("user_name"),
        "sender": msg.get("sender"),
        "receiver": msg.get("receiver"),
        "role": msg.get("role"),
        "message_id": str(msg.get("message_id")) if msg.get("message_id") is not None else None,
        "content": msg.get("content"),
        "content_type": None,
        "content_text": None,
        "content_url": None,
        "content_mime": None,
        "image_width": None,
        "image_height": None,
        "image_size_bytes": None,
    }

    c = msg.get("content") or {}

    # Simple content (msgin/text or msgin/image)
    if isinstance(c, dict) and "type" in c:
        row["content_type"] = c.get("type")

        if c.get("type") == "text":
            row["content_text"] = c.get("text")

        elif c.get("type") == "image":
            row["content_url"] = c.get("url")
            row["content_mime"] = c.get("mime_type")
            sz = c.get("image_size") or {}
            row["image_width"] = sz.get("width")
            row["image_height"] = sz.get("height")
            row["image_size_bytes"] = sz.get("size")

    # Complex content (msgout_api): pick first message as helper
    # but keep full content JSON for full fidelity
    msgs = (c or {}).get("messages")
    if isinstance(msgs, list) and msgs:
        # unique types (e.g., {"text", "image"})
        # build a set[str] of message types, filtering out None and non-str values
        types_in_msgs = {
            (m or {}).get("type") for m in msgs
            if isinstance(m, dict) and isinstance((m or {}).get("type"), str)
        }
        if types_in_msgs:
            # Keep any existing content_type if already set, else join all types
            # Ensure we only sort actual str values to satisfy type checkers
            types_list = [t for t in types_in_msgs if isinstance(t, str)]
            if types_list:
                row["content_type"] = row["content_type"] or ",".join(sorted(types_list))

        # ---- TEXT: concatenate all text message contents ----
        text_chunks = []
        for m in msgs:
            if (m or {}).get("type") == "text":
                content = (m.get("content") or {})
                txt = content.get("text")
                if isinstance(txt, str) and txt:
                    text_chunks.append(txt)
        if text_chunks:
            row["content_text"] = "\n".join(text_chunks)

        # ---- IMAGE: if any image exists, populate image helper fields from the first image ----
        first_image = next((m for m in msgs if (m or {}).get("type") == "image"), None)
        if first_image:
            media = (first_image.get("content") or {})
            row["content_url"] = media.get("url")
            row["content_mime"] = media.get("mime_type")
            sz = media.get("image_size") or {}
            row["image_width"] = sz.get("width")
            row["image_height"] = sz.get("height")
            row["image_size_bytes"] = sz.get("size")
    return row


def save_messages_with_session(
    session: ManychatSession,
    *,
    metrics: Optional[DataUpdateMetrics] = None,
    bq_factory: Optional[Callable[..., bigquery_client.BigQueryUtils]] = None,
) -> None:
    """
    Upsert message events into BigQuery (table: manychat_live.messages).
    Uses session.load_messages() which reuses cached messages when available.
    """
    resp = session.load_messages()
    if resp.get("status") == "error":
        raise RuntimeError(resp.get("message", "Failed to fetch messages"))

    data_raw = resp.get("data")
    if not isinstance(data_raw, list):
        return

    rows: List[Dict[str, Any]] = [
        cast(Dict[str, Any], row) for row in data_raw if isinstance(row, dict)
    ]
    if not rows:
        return

    factory = bq_factory or bigquery_client.BigQueryUtils
    bq = factory(
        project_id="gulong-chatbot-459723",
        dataset_id="manychat_data",
        table_id="messages",
    )

    msg_rows = []
    message_whitelist = {
        "msgin",
        "msgout_api",
        "msgout_lc",
        "msgin_tiktok",
        "msgout_api_tiktok",
        "msgout_lc_tiktok",
        "msgin_instagram",
        "msgout_lc_instagram",
        "msgout_api_instagram",
    }

    for entry in rows:
        msg_type = entry.get("type")
        if msg_type not in message_whitelist:
            continue
        normalized = normalize_message_row(entry, session=session)
        message_id = normalized.get("message_id")
        if not message_id:
            continue
        msg_rows.append(normalized)

    outcome = _stream_with_fallback(
        bq,
        msg_rows,
        schema_name="messages",
        key_columns=["message_id"],
        metrics=metrics,
        use_many=True,
    )
    if outcome.fallback_used and outcome.error:
        logger.warning("Streaming message rows failed for %s: %s", session.user_name, outcome.error)


def save_pipeline_log(
    run_report: Dict[str, Any],
    *,
    metrics: Optional[DataUpdateMetrics] = None,
    bq_factory: Optional[Callable[..., bigquery_client.BigQueryUtils]] = None,
) -> WriteOutcome:
    """
    Write pipeline_logs for the dataUpdate pipeline.
    """
    run_report = dict(run_report)
    task_id = run_report.get("task_id") or run_report.get("run_id") or "run-unknown"
    run_report.setdefault("task_id", task_id)
    run_report.setdefault("run_id", task_id)
    run_report.setdefault("status", run_report.get("final_status") or "unknown")
    run_report.setdefault("request_params", {})
    run_report.setdefault("pipeline_timings", {})
    if "start_datetime" not in run_report and "started_at" in run_report:
        run_report["start_datetime"] = run_report.pop("started_at")
    if "end_datetime" not in run_report and "finished_at" in run_report:
        run_report["end_datetime"] = run_report.pop("finished_at")

    factory = bq_factory or bigquery_client.BigQueryUtils
    bq_util = factory(
        project_id="gulong-chatbot-459723",
        dataset_id="manychat_data",
        table_id="pipeline_logs",
    )
    outcome = _stream_with_fallback(
        bq_util,
        run_report,
        schema_name="pipeline_logs",
        key_columns=["task_id"],
        metrics=metrics,
        table_label="pipeline_logs",
    )
    return outcome

