from runtime_v7.api_runtime import (
    _runtime_v7_component_context_cache_enabled,
    _runtime_v7_context_cache_ttl,
    _runtime_v7_main_context_cache_enabled,
)


def test_runtime_v7_context_cache_defaults_off(monkeypatch):
    for name in [
        "RUNTIME_V7_ENABLE_CONTEXT_CACHE",
        "RUNTIME_V7_MAIN_ENABLE_CONTEXT_CACHE",
        "RUNTIME_V7_MEMORY_ENABLE_CONTEXT_CACHE",
        "RUNTIME_V7_BACKGROUND_SIGNAL_ENABLE_CONTEXT_CACHE",
        "RUNTIME_V7_CONTEXT_CACHE_TTL",
    ]:
        monkeypatch.delenv(name, raising=False)

    assert _runtime_v7_main_context_cache_enabled() is False
    assert _runtime_v7_component_context_cache_enabled("RUNTIME_V7_MEMORY_ENABLE_CONTEXT_CACHE") is False
    assert _runtime_v7_component_context_cache_enabled("RUNTIME_V7_BACKGROUND_SIGNAL_ENABLE_CONTEXT_CACHE") is False
    assert _runtime_v7_context_cache_ttl() == "300s"


def test_runtime_v7_context_cache_component_flags_are_scoped(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_ENABLE_CONTEXT_CACHE", "1")
    monkeypatch.delenv("RUNTIME_V7_MAIN_ENABLE_CONTEXT_CACHE", raising=False)
    monkeypatch.delenv("RUNTIME_V7_MEMORY_ENABLE_CONTEXT_CACHE", raising=False)
    monkeypatch.setenv("RUNTIME_V7_BACKGROUND_SIGNAL_ENABLE_CONTEXT_CACHE", "1")
    monkeypatch.setenv("RUNTIME_V7_CONTEXT_CACHE_TTL", "600s")

    assert _runtime_v7_main_context_cache_enabled() is True
    assert _runtime_v7_component_context_cache_enabled("RUNTIME_V7_MEMORY_ENABLE_CONTEXT_CACHE") is False
    assert _runtime_v7_component_context_cache_enabled("RUNTIME_V7_BACKGROUND_SIGNAL_ENABLE_CONTEXT_CACHE") is True
    assert _runtime_v7_context_cache_ttl() == "600s"


def test_runtime_v7_main_context_cache_flag_overrides_legacy_global(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_ENABLE_CONTEXT_CACHE", "1")
    monkeypatch.setenv("RUNTIME_V7_MAIN_ENABLE_CONTEXT_CACHE", "0")

    assert _runtime_v7_main_context_cache_enabled() is False
