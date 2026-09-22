"""
RAG index builder and retrieval helpers.
Embeddings are built offline via a rebuild endpoint and loaded from disk at runtime.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple
import json
import math
import os
import time
import hashlib
import uuid
import logging

from runtime.utils.time_utils import now_manila_str

try:  # Optional dependency in some environments.
    from google.cloud import storage
except Exception:  # pragma: no cover - runtime dependency
    storage = None

logger = logging.getLogger(__name__)


def _base_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _rag_root() -> str:
    return os.path.join(_base_dir(), "data", "rag_index")


def _bu_dir(bu: str) -> str:
    return os.path.join(_rag_root(), bu)


def _current_path(bu: str) -> str:
    return os.path.join(_bu_dir(bu), "current.json")


def _index_path(bu: str, version: str) -> str:
    return os.path.join(_bu_dir(bu), version, "index.json")


def _meta_path(bu: str, version: str) -> str:
    return os.path.join(_bu_dir(bu), version, "meta.json")


def _gcs_bucket_name() -> str:
    return os.getenv("RAG_INDEX_BUCKET", "lica-gulong-chatbot-embeddings").strip()


def _gcs_prefix() -> str:
    return os.getenv("RAG_INDEX_PREFIX", "rag_index").strip().strip("/")


def _gcs_object_path(bu: str, *parts: str) -> str:
    prefix = _gcs_prefix()
    return "/".join([p for p in [prefix, bu, *parts] if p])


def _gcs_client() -> Optional[Any]:
    if storage is None:
        return None
    try:
        return storage.Client()
    except Exception:
        return None


def _safe_read_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _safe_read_json_gcs(bucket_name: str, object_path: str) -> Optional[Any]:
    client = _gcs_client()
    if not client:
        return None
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_path)
        if not blob.exists():
            return None
        payload = blob.download_as_text(encoding="utf-8")
        return json.loads(payload)
    except Exception:
        return None


def _safe_write_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)


def _safe_write_json_gcs(bucket_name: str, object_path: str, payload: Any) -> None:
    client = _gcs_client()
    if not client:
        logger.warning("GCS client unavailable; skipping write to %s/%s", bucket_name, object_path)
        return
    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_path)
        blob.upload_from_string(
            json.dumps(payload, ensure_ascii=True, indent=2),
            content_type="application/json",
        )
        logger.info("Wrote GCS object %s/%s", bucket_name, object_path)
    except Exception as exc:
        logger.warning("GCS write failed for %s/%s: %s", bucket_name, object_path, exc)
        return


def _hash_text(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def _normalize_text(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "\n".join([line.strip() for line in cleaned.split("\n") if line.strip()])
    return cleaned


def _chunk_text(text: str, max_chars: int = 800, overlap: int = 120) -> List[str]:
    text = _normalize_text(text)
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks


def _load_faqs(path: str) -> List[Dict[str, Any]]:
    data = _safe_read_json(path)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [item for item in data.get("items") if isinstance(item, dict)]
    return []


def _load_faq_meta(path: str) -> Dict[str, Any]:
    data = _safe_read_json(path)
    return data if isinstance(data, dict) else {}


def _load_docs_from_dir(path: str) -> List[Dict[str, Any]]:
    docs = []
    if not os.path.isdir(path):
        return docs
    for filename in os.listdir(path):
        if not filename.lower().endswith((".md", ".txt")):
            continue
        full_path = os.path.join(path, filename)
        try:
            with open(full_path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except Exception:
            continue
        docs.append({
            "doc_id": filename,
            "title": filename,
            "text": text,
            "source": "file",
        })
    return docs


def _embed_batch(
    texts: List[str],
    client,
    model: str,
    *,
    embedding_gateway: Optional[Any] = None,
    embedding_fallback_chain: Optional[List[Tuple[str, str]]] = None,
) -> List[List[float]]:
    if not texts:
        return []
    if embedding_gateway is None:
        raise RuntimeError("Embedding gateway is required for RAG rebuild.")

    from runtime.shared.llm_types import LLMEmbeddingRequest

    # Gemini batch embeddings cap at 100 inputs per request.
    batch_size = int(os.getenv("RAG_EMBEDDING_BATCH_SIZE", "100"))
    batch_size = max(1, min(batch_size, 100))
    vectors: List[List[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        resp = embedding_gateway.embed(
            LLMEmbeddingRequest(
                request_id=str(uuid.uuid4()),
                texts=batch,
                model=model,
                metadata={"task_type": "rag_embedding"},
            ),
            fallback_chain=embedding_fallback_chain,
        )
        vectors.extend(resp.vectors)
    return vectors


def build_rag_index(
    bu: str,
    *,
    openai_client: Any,
    embedding_model: str,
    faqs_path: str,
    faqs_meta_path: str,
    docs_path: str,
    chunk_size: int = 800,
    embedding_gateway: Optional[Any] = None,
    embedding_fallback_chain: Optional[List[Tuple[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Build and persist a RAG index for a BU (offline path).

    Example:
        build_rag_index(
            bu="gulong",
            openai_client=None,
            embedding_model="text-embedding-3-small",
            faqs_path="runtime/bu/gulong/rag/faqs.json",
            faqs_meta_path="runtime/bu/gulong/rag/faqs_meta.json",
            docs_path="docs/rag_sources",
            embedding_gateway=embedding_gateway,
        )
    """
    bu_key = (bu or "").strip().lower()
    if not bu_key:
        return {"status": "error", "message": "Missing BU"}

    faq_items = _load_faqs(faqs_path)
    faq_meta = _load_faq_meta(faqs_meta_path)
    faq_version = faq_meta.get("version") or "unknown"

    docs = []
    for item in faq_items:
        q = item.get("question") or ""
        a = item.get("answer") or ""
        if not q and not a:
            continue
        docs.append({
            "doc_id": _hash_text(q + a),
            "title": q[:120],
            "text": f"Q: {q}\nA: {a}",
            "source": "faqs",
        })
    docs.extend(_load_docs_from_dir(docs_path))
    logger.info(
        "RAG rebuild inputs loaded: bu=%s faqs=%d docs=%d docs_path=%s",
        bu_key,
        len(faq_items),
        len(docs),
        docs_path,
    )

    chunks = []
    for doc in docs:
        for idx, chunk in enumerate(_chunk_text(doc.get("text", ""), max_chars=chunk_size)):
            chunks.append({
                "chunk_id": f"{doc.get('doc_id')}-{idx}",
                "doc_id": doc.get("doc_id"),
                "title": doc.get("title"),
                "source": doc.get("source"),
                "text": chunk,
            })

    texts = [c.get("text", "") for c in chunks]
    vectors = []
    if texts:
        logger.info(
            "RAG embeddings start: bu=%s chunks=%d model=%s",
            bu_key,
            len(texts),
            embedding_model,
        )
        vectors = _embed_batch(
            texts,
            openai_client,
            embedding_model,
            embedding_gateway=embedding_gateway,
            embedding_fallback_chain=embedding_fallback_chain,
        )
    for chunk, vector in zip(chunks, vectors):
        chunk["vector"] = vector

    version = str(int(time.time()))
    meta = {
        "bu": bu_key,
        "version": version,
        "faq_version": faq_version,
        "embedding_model": embedding_model,
        "created_at": now_manila_str(),
        "count": len(chunks),
    }

    _safe_write_json(_index_path(bu_key, version), {"chunks": chunks})
    _safe_write_json(_meta_path(bu_key, version), meta)
    _safe_write_json(_current_path(bu_key), {"version": version})

    bucket_name = _gcs_bucket_name()
    if bucket_name:
        logger.info(
            "RAG GCS upload start: bucket=%s prefix=%s bu=%s version=%s",
            bucket_name,
            _gcs_prefix(),
            bu_key,
            version,
        )
        _safe_write_json_gcs(
            bucket_name,
            _gcs_object_path(bu_key, version, "index.json"),
            {"chunks": chunks},
        )
        _safe_write_json_gcs(
            bucket_name,
            _gcs_object_path(bu_key, version, "meta.json"),
            meta,
        )
        _safe_write_json_gcs(
            bucket_name,
            _gcs_object_path(bu_key, "current.json"),
            {"version": version},
        )

    return {
        "status": "success",
        "version": version,
        "faq_version": faq_version,
        "count": len(chunks),
    }


_index_cache: Dict[str, Dict[str, Any]] = {}
_current_version_cache: Dict[str, Dict[str, Any]] = {}


def _current_version_cache_ttl_s() -> float:
    try:
        return max(0.0, float(os.getenv("RAG_CURRENT_CACHE_TTL_S", "30") or 30))
    except Exception:
        return 30.0


def load_rag_index(bu: str) -> Optional[Dict[str, Any]]:
    """Load the current RAG index for a BU from disk."""
    bu_key = (bu or "").strip().lower()
    if not bu_key:
        return None

    # Fast-path: reuse recently resolved current version to avoid repeated
    # local/GCS lookups on hot FAQ paths.
    now = time.time()
    cached_current = _current_version_cache.get(bu_key)
    if isinstance(cached_current, dict):
        cached_version = str(cached_current.get("version") or "").strip()
        cached_ts = float(cached_current.get("ts") or 0.0)
        if cached_version and (now - cached_ts) <= _current_version_cache_ttl_s():
            cache_key = f"{bu_key}:{cached_version}"
            cached_payload = _index_cache.get(cache_key)
            if cached_payload:
                return cached_payload

    # Prefer local current/index for latency and resilience; fallback to GCS.
    bucket_name = _gcs_bucket_name()
    current = _safe_read_json(_current_path(bu_key))
    if current is None and bucket_name:
        current = _safe_read_json_gcs(bucket_name, _gcs_object_path(bu_key, "current.json"))
    if not isinstance(current, dict) or not current.get("version"):
        return None
    version = str(current.get("version"))
    _current_version_cache[bu_key] = {"version": version, "ts": now}
    cache_key = f"{bu_key}:{version}"
    cached = _index_cache.get(cache_key)
    if cached:
        return cached
    index = None
    meta = None
    index = _safe_read_json(_index_path(bu_key, version))
    meta = _safe_read_json(_meta_path(bu_key, version))
    if index is None and bucket_name:
        index = _safe_read_json_gcs(bucket_name, _gcs_object_path(bu_key, version, "index.json"))
    if meta is None and bucket_name:
        meta = _safe_read_json_gcs(bucket_name, _gcs_object_path(bu_key, version, "meta.json"))
    if not isinstance(index, dict) or "chunks" not in index:
        return None
    payload = {
        "version": version,
        "meta": meta if isinstance(meta, dict) else {},
        "chunks": index.get("chunks", []),
    }
    _index_cache[cache_key] = payload
    return payload


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _lexical_score(query: str, text: str) -> float:
    if not query or not text:
        return 0.0
    q_tokens = {t for t in query.lower().split() if len(t) > 2}
    t_tokens = {t for t in text.lower().split() if len(t) > 2}
    if not q_tokens:
        return 0.0
    return len(q_tokens.intersection(t_tokens)) / float(len(q_tokens))


def retrieve_rag_chunks(
    query: str,
    *,
    bu: str,
    top_k: int = 4,
    min_score: float = 0.18,
    openai_client: Optional[Any] = None,
    embedding_model: Optional[str] = None,
    query_vector: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """
    Retrieve top RAG chunks for a query using lexical or vector scoring.

    Example:
        result = retrieve_rag_chunks("delivery fee", bu="gulong", top_k=3)
    """
    index = load_rag_index(bu)
    if not index:
        return {"chunks": [], "meta": {}, "version": ""}

    chunks = index.get("chunks", []) or []
    if query_vector is None and openai_client:
        meta_model = (index.get("meta") or {}).get("embedding_model")
        effective_model = embedding_model or meta_model
        if meta_model and embedding_model and embedding_model != meta_model:
            embedding_model = meta_model
        else:
            embedding_model = effective_model
    if query_vector is None and openai_client and embedding_model:
        try:
            resp = openai_client.embeddings.create(model=embedding_model, input=[query])
            data = getattr(resp, "data", [])
            if data:
                query_vector = list(data[0].embedding)
        except Exception:
            query_vector = None

    scored = []
    for chunk in chunks:
        text = chunk.get("text", "")
        score = _lexical_score(query, text)
        if query_vector and chunk.get("vector"):
            score = _cosine(query_vector, chunk.get("vector"))
        scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    picked = [item for item in scored if item[0] >= min_score][:top_k]
    return {
        "chunks": [{"score": s, **c} for s, c in picked],
        "meta": index.get("meta", {}),
        "version": index.get("version", ""),
    }
