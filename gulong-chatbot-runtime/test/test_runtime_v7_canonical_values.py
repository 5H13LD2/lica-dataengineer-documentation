from runtime_v7.canonical_values import RuntimeV7CanonicalValuesProvider
from runtime_v7.model_contract import build_runtime_v7_context
from runtime_v7.order_canonicalization import (
    canonical_payment_method_with_metadata,
    checkout_metadata,
    resolve_payment_type,
)
from runtime_v7.state_signals import build_commercial_state_context


class FakeHTTPClient:
    def __init__(self):
        self.calls = []

    def get_json(self, path, *, params=None, headers=None):
        self.calls.append(path)
        if path == "/product_list_dropdown_brand":
            return [{"brand": "FRONWAY"}]
        if path == "/tire_brand":
            return [{"name": "Premium"}]
        if path == "/payment/list":
            return [
                {
                    "id": 20,
                    "main_payment_type_id": 1,
                    "name": "GCash",
                    "label": "GCash",
                    "value": "GCASH",
                    "is_installment": 0,
                },
                {
                    "id": 21,
                    "main_payment_type_id": 1,
                    "name": "Order Now, Installment Later (3 months, 0% interest)",
                    "label": "Installment",
                    "value": "INSTALLMENT",
                    "is_installment": 1,
                },
                {
                    "id": 22,
                    "main_payment_type_id": 2,
                    "name": "Straight Credit Card / Debit Card",
                    "label": "Credit Card / Debit Card",
                    "value": "CC",
                    "is_installment": 0,
                },
            ]
        if path == "/transaction_list":
            return [{"trans_type": "Install"}]
        if path == "/get_province":
            return [{"PROV_CODE": "PH-LAG", "PROV_NAME": "LAGUNA"}]
        if path == "/get_city":
            return [{"CITY_NAME": "SANTA ROSA CITY", "PROV_CODE": "PH-LAG"}]
        if path == "/all_branch":
            return [{"name": "ROADSTAR ENTERPRISES", "active": 1}]
        if path == "/branch_list_loc":
            return [{"name": "ROADSTAR ENTERPRISES", "branch_add_ons": [{"service": "Tire Rotation"}]}]
        return []


class FakeBackgroundSignalModelClient:
    def __init__(self, content):
        self.content = content
        self.user_prompt = ""

    def extract_background_signals(self, *, system_prompt, user_prompt, metadata=None):
        self.user_prompt = user_prompt
        return {"content": self.content, "usage": {}, "cache_usage": {}, "latency_ms": 1}


def test_canonical_values_provider_is_lazy_and_cached():
    http = FakeHTTPClient()
    provider = RuntimeV7CanonicalValuesProvider(http_client=http, ttl_seconds=900)

    examples = provider.prompt_examples()
    assert examples["brands"]
    assert "installation_partners" not in examples
    assert http.calls == []

    assert provider.brands() == ["FRONWAY"]
    assert provider.brands() == ["FRONWAY"]
    assert http.calls == ["/product_list_dropdown_brand"]

    locations = provider.locations()
    assert "Santa Rosa City, Laguna" in locations
    assert http.calls.count("/get_province") == 1
    assert http.calls.count("/get_city") == 1


def test_background_signals_use_lazy_provider_for_catalog_backed_values():
    http = FakeHTTPClient()
    provider = RuntimeV7CanonicalValuesProvider(http_client=http, ttl_seconds=900)
    client = FakeBackgroundSignalModelClient(
        '{"candidates":['
        '{"key":"brand","value":"fronwei","source":"latest_user_message","confidence":"medium"},'
        '{"key":"location","value":"Santa Rosa City, Laguna","source":"latest_user_message","confidence":"medium"},'
        '{"key":"installation_partner","value":"roadstar","source":"latest_user_message","confidence":"medium"},'
        '{"key":"branch_addons","value":"tire rotashon","source":"latest_user_message","confidence":"medium"}'
        "]}"
    )

    state_context = build_commercial_state_context(
        current_user_message="Fronwei sana. Santa Rosa ako, Roadstar branch, add tire rotashon.",
        model_client=client,
        canonical_values_provider=provider,
    )

    signals = {signal["key"]: signal for signal in state_context["background_signals"]}
    assert signals["preferred_brands"]["value"] == "FRONWAY"
    assert signals["location"]["value"] == "Santa Rosa City, Laguna"
    assert signals["selected_installation_partner"]["value"] == "ROADSTAR ENTERPRISES"
    assert signals["branch_addons"]["value"] == "Tire Rotation"
    assert state_context["missing_info"]["order_readiness"]["present"]["selected_installation_partner"] == "ROADSTAR ENTERPRISES"
    assert state_context["missing_info"]["order_readiness"]["present"]["branch_addons"] == "Tire Rotation"
    assert '"installation_partners"' not in client.user_prompt


def test_payment_signals_use_checkout_metadata_when_provider_is_available():
    http = FakeHTTPClient()
    provider = RuntimeV7CanonicalValuesProvider(http_client=http, ttl_seconds=900)
    client = FakeBackgroundSignalModelClient(
        '{"candidates":['
        '{"key":"tire_size","value":"175 65 14","source":"latest_user_message","confidence":"high","status_hint":"confirmed"},'
        '{"key":"quantity","value":"4 pcs","source":"latest_user_message","confidence":"high"},'
        '{"key":"reservation_payment_method","value":"GCash","source":"latest_user_message","confidence":"high"},'
        '{"key":"balance_payment_method","value":"credit card installment","source":"latest_user_message","confidence":"high"}'
        "]}",
    )

    state_context = build_commercial_state_context(
        current_user_message=(
            "Boss 175 65 14 confirmed, 4 pcs. "
            "GCash reservation then card installment sa balance."
        ),
        canonical_values_provider=provider,
        model_client=client,
    )

    signals = {signal["key"]: signal for signal in state_context["background_signals"]}
    assert signals["reservation_payment_method"]["value"] == "gcash"
    assert signals["balance_payment_method"]["value"] == "credit card installment"
    assert "branch_addons" not in signals
    assert signals["reservation_payment_method"]["resolution"]["status"] == "canonicalized"
    assert signals["reservation_payment_method"]["resolution"]["selected_ref"] == "payment_type_id:20, payment_option_id:1, Pay Later"
    assert signals["balance_payment_method"]["resolution"]["status"] == "preference_captured_not_final"
    assert signals["balance_payment_method"]["resolution"]["needs"] == "validate after product choice and fulfillment path if installment remains preferred"
    assert signals["balance_payment_method"]["resolution"]["candidate_count"] == 1
    assert signals["balance_payment_method"]["ask_timing"] == "later_after_product_and_fulfillment"

    reservation_normalization = signals["reservation_payment_method"]["metadata"]["normalization"]
    balance_normalization = signals["balance_payment_method"]["metadata"]["normalization"]
    assert reservation_normalization["status"] == "checkout_metadata_canonicalized"
    assert reservation_normalization["payment_type"]["id"] == 20
    assert reservation_normalization["payment_option"]["name"] == "Pay Later"
    assert balance_normalization["status"] == "checkout_metadata_deferred_product_installment_selection"
    assert balance_normalization["requires_product_installment_option"] is True
    assert "payment_type" not in balance_normalization
    assert balance_normalization["candidate_payment_types"][0]["id"] == 21
    assert http.calls.count("/transaction_list") == 1
    assert http.calls.count("/payment/list") == 1


def test_background_signal_and_order_payload_payment_resolution_share_checkout_metadata():
    http = FakeHTTPClient()
    provider = RuntimeV7CanonicalValuesProvider(http_client=http, ttl_seconds=900)

    value, normalization = canonical_payment_method_with_metadata(
        "GCash",
        key="reservation_payment_method",
        canonical_values_provider=provider,
    )
    metadata = checkout_metadata(provider)
    payment_option_id = (normalization["payment_option"] or {})["id"]
    payload_row = resolve_payment_type(value, metadata, payment_option_id=payment_option_id)

    assert value == "gcash"
    assert normalization["status"] == "checkout_metadata_canonicalized"
    assert normalization["payment_type"]["id"] == 20
    assert payment_option_id == 1
    assert payload_row["id"] == normalization["payment_type"]["id"]


def test_specific_installment_does_not_fall_back_to_unrelated_payment_row():
    metadata = {
        "source": "gulong_api_checkout_metadata",
        "payment_types": [
            {
                "id": 15,
                "main_payment_type_id": 2,
                "name": "Straight Credit Card / Debit Card",
                "label": "Credit Card / Debit Card",
                "value": "CC",
                "is_installment": 0,
            },
            {
                "id": 21,
                "main_payment_type_id": 2,
                "name": "3-mos Installment (0% interest)",
                "value": "3-MOS-INSTALLMENT",
                "is_installment": 1,
            },
        ],
    }

    assert (
        resolve_payment_type(
            "BPI 6 months credit card installment",
            metadata,
            payment_option_id=2,
        )
        == {}
    )


def test_distinct_named_financial_product_does_not_fuzzy_match_wallet_rail():
    metadata = {
        "source": "gulong_api_checkout_metadata",
        "payment_types": [
            {
                "id": 13,
                "main_payment_type_id": 2,
                "name": "Gcash QR Code / Ggives",
                "label": "GCash",
                "value": "GCASH",
                "is_installment": 0,
            }
        ],
    }

    assert resolve_payment_type("GCash loan", metadata) == {}


def test_context_packet_uses_compact_advisory_choice_projection():
    http = FakeHTTPClient()
    provider = RuntimeV7CanonicalValuesProvider(http_client=http, ttl_seconds=900)
    client = FakeBackgroundSignalModelClient(
        '{"candidates":['
        '{"key":"reservation_payment_method","value":"GCash","source":"latest_user_message","confidence":"high"},'
        '{"key":"balance_payment_method","value":"credit card installment","source":"latest_user_message","confidence":"high"}'
        "]}",
    )
    state_context = build_commercial_state_context(
        current_user_message="GCash reservation then card installment sa balance.",
        canonical_values_provider=provider,
        model_client=client,
    )

    context = build_runtime_v7_context(
        current_user_message="GCash reservation then card installment sa balance.",
        background_signals=state_context["background_signals"],
        missing_info=state_context["missing_info"],
    )

    assert "Advisory slot/state signals" in context
    assert "## Context Priority" in context
    assert "advisory soft drivers, not blockers" in context
    assert "resolution=preference_captured_not_final" in context
    assert "needs=validate after product choice and fulfillment path if installment remains preferred" not in context
    assert "ask_timing=later_after_product_and_fulfillment" not in context
    assert "confidence=" not in context
    assert "requires_validation=false" not in context
    assert "candidate_count=1" in context
    assert "Order Now, Installment Later" not in context
    assert "payment_type=GCash" not in context


def test_explicit_balance_installment_term_can_match_checkout_metadata():
    http = FakeHTTPClient()
    provider = RuntimeV7CanonicalValuesProvider(http_client=http, ttl_seconds=900)
    client = FakeBackgroundSignalModelClient(
        '{"candidates":['
        '{"key":"balance_payment_method","value":"credit card installment 3 mos 0%","source":"latest_user_message","confidence":"high"}'
        "]}",
    )

    state_context = build_commercial_state_context(
        current_user_message="Card installment 3 mos 0% sa balance.",
        canonical_values_provider=provider,
        model_client=client,
    )

    signals = {signal["key"]: signal for signal in state_context["background_signals"]}
    balance_normalization = signals["balance_payment_method"]["metadata"]["normalization"]
    assert signals["balance_payment_method"]["value"] == "credit card installment"
    assert balance_normalization["status"] == "checkout_metadata_canonicalized"
    assert balance_normalization["payment_type"]["id"] == 21
