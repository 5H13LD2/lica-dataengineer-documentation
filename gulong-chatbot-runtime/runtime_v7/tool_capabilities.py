"""Tool capability registry for Runtime V7 context/tool compilation.

The registry describes which tools belong to each broad domain and which
normalized context signals or refs make a tool relevant. It does not decide the
customer's intent. The model still chooses exact tool calls from the exposed
schemas, while runtime validation and renderers keep tool outputs grounded.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Sequence


ToolSchemaProvider = Callable[[], Dict[str, object]]


@dataclass(frozen=True)
class ToolCapability:
    """Registry metadata for one callable model tool."""

    name: str
    domain: str
    action_kind: str
    useful_signal_keys: Sequence[str] = field(default_factory=tuple)
    requires_context_refs: Sequence[str] = field(default_factory=tuple)
    schema_provider: ToolSchemaProvider = field(default_factory=lambda: _empty_schema)


def request_capability_schema() -> Dict[str, object]:
    """Return the internal recovery tool schema available on every turn."""

    return {
        "type": "function",
        "function": {
            "name": "request_capability",
            "description": (
                "Ask the runtime to retry the same turn with another capability domain "
                "when the currently exposed tools are insufficient. Use only when a "
                "needed product, service, or order capability is unavailable."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "enum": ["product", "service", "order", "general"],
                        "description": "Capability domain needed for the current turn.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Short explanation of why the current tool surface is insufficient.",
                    },
                    "needed_context": {
                        "type": ["string", "null"],
                        "description": "Optional compact note about the missing context/tool need.",
                    },
                },
                "required": ["domain", "reason"],
                "additionalProperties": False,
            },
        },
    }


def runtime_schema_provider(tool_name: str) -> ToolSchemaProvider:
    """Return a lazy provider for one Runtime V7 tool schema.

    The import is intentionally inside the provider to avoid a module cycle with
    `model_contract`, where schemas remain defined for compatibility.
    """

    def _provider() -> Dict[str, object]:
        from runtime_v7.model_contract import ALL_RUNTIME_V7_TOOL_SCHEMAS

        for schema in ALL_RUNTIME_V7_TOOL_SCHEMAS:
            if schema.get("function", {}).get("name") == tool_name:
                return deepcopy(schema)
        raise KeyError(f"unknown Runtime V7 tool schema: {tool_name}")

    return _provider


def product_schema_provider(tool_name: str) -> ToolSchemaProvider:
    """Backward-compatible alias for product schema lookup."""

    return runtime_schema_provider(tool_name)


def _empty_schema() -> Dict[str, object]:
    return {}


TOOL_CAPABILITIES: Dict[str, ToolCapability] = {
    "get_brand_knowledge": ToolCapability(
        name="get_brand_knowledge",
        domain="product",
        action_kind="read",
        useful_signal_keys=("preferred_brands", "required_brands"),
        schema_provider=runtime_schema_provider("get_brand_knowledge"),
    ),
    "search_promo_catalog": ToolCapability(
        name="search_promo_catalog",
        domain="product",
        action_kind="read",
        useful_signal_keys=(
            "tire_size",
            "preferred_brands",
            "required_brands",
            "promo_types",
            "promo_alternative_scope",
        ),
        schema_provider=runtime_schema_provider("search_promo_catalog"),
    ),
    "present_promo_gallery": ToolCapability(
        name="present_promo_gallery",
        domain="product",
        action_kind="read",
        schema_provider=runtime_schema_provider("present_promo_gallery"),
    ),
    "get_business_contact": ToolCapability(
        name="get_business_contact",
        domain="general",
        action_kind="read",
        schema_provider=runtime_schema_provider("get_business_contact"),
    ),
    "answer_policy_faq": ToolCapability(
        name="answer_policy_faq",
        domain="general",
        action_kind="read",
        schema_provider=runtime_schema_provider("answer_policy_faq"),
    ),
    "present_serviceable_location_choices": ToolCapability(
        name="present_serviceable_location_choices",
        domain="general",
        action_kind="read",
        schema_provider=runtime_schema_provider(
            "present_serviceable_location_choices"
        ),
    ),
    "request_human_handoff": ToolCapability(
        name="request_human_handoff",
        domain="general",
        action_kind="mutate",
        schema_provider=runtime_schema_provider("request_human_handoff"),
    ),
    "product_search": ToolCapability(
        name="product_search",
        domain="product",
        action_kind="read",
        useful_signal_keys=(
            "tire_size",
            "rim_size",
            "preferred_brands",
            "required_brands",
            "brand_match_mode",
            "excluded_brands",
            "budget",
            "quantity",
            "tire_category_preference",
            "excluded_tire_categories",
            "origins",
            "excluded_origins",
            "specific_sku_model",
            "terrain_types",
            "external_product_evidence",
        ),
        schema_provider=product_schema_provider("product_search"),
    ),
    "discover_brand_buckets": ToolCapability(
        name="discover_brand_buckets",
        domain="product",
        action_kind="read",
        useful_signal_keys=(
            "tire_size",
            "rim_size",
            "excluded_brands",
            "tire_category_preference",
            "excluded_tire_categories",
            "origins",
            "excluded_origins",
        ),
        schema_provider=product_schema_provider("discover_brand_buckets"),
    ),
    "extract_compatible_fitment": ToolCapability(
        name="extract_compatible_fitment",
        domain="product",
        action_kind="read",
        useful_signal_keys=("car_make_model",),
        schema_provider=product_schema_provider("extract_compatible_fitment"),
    ),
    "answer_product_faq": ToolCapability(
        name="answer_product_faq",
        domain="product",
        action_kind="read",
        schema_provider=runtime_schema_provider("answer_product_faq"),
    ),
    "resolve_product_reference": ToolCapability(
        name="resolve_product_reference",
        domain="product",
        action_kind="read",
        requires_context_refs=("product_presentation",),
        schema_provider=product_schema_provider("resolve_product_reference"),
    ),
    "get_product_details": ToolCapability(
        name="get_product_details",
        domain="product",
        action_kind="read",
        requires_context_refs=("product_presentation",),
        schema_provider=product_schema_provider("get_product_details"),
    ),
    "answer_service_faq": ToolCapability(
        name="answer_service_faq",
        domain="service",
        action_kind="read",
        schema_provider=runtime_schema_provider("answer_service_faq"),
    ),
    "answer_order_faq": ToolCapability(
        name="answer_order_faq",
        domain="order",
        action_kind="read",
        useful_signal_keys=(
            "payment_method",
            "payment_option",
            "bank",
            "installment_months",
            "reservation_payment_method",
            "balance_payment_method",
            "invoice_to_company",
        ),
        schema_provider=runtime_schema_provider("answer_order_faq"),
    ),
    "calculate_order_quote": ToolCapability(
        name="calculate_order_quote",
        domain="order",
        action_kind="read",
        schema_provider=runtime_schema_provider("calculate_order_quote"),
    ),
    "build_order_summary": ToolCapability(
        name="build_order_summary",
        domain="order",
        action_kind="read",
        schema_provider=runtime_schema_provider("build_order_summary"),
    ),
    "build_order_payload": ToolCapability(
        name="build_order_payload",
        domain="order",
        action_kind="validate",
        schema_provider=runtime_schema_provider("build_order_payload"),
    ),
    "submit_order": ToolCapability(
        name="submit_order",
        domain="order",
        action_kind="mutate",
        schema_provider=runtime_schema_provider("submit_order"),
    ),
    "prepare_payment_request": ToolCapability(
        name="prepare_payment_request",
        domain="order",
        action_kind="mutate",
        requires_context_refs=("order_payload",),
        schema_provider=runtime_schema_provider("prepare_payment_request"),
    ),
    "match_payment_proof": ToolCapability(
        name="match_payment_proof",
        domain="order",
        action_kind="read",
        useful_signal_keys=("payment_proof_evidence",),
        schema_provider=runtime_schema_provider("match_payment_proof"),
    ),
    "get_order_details": ToolCapability(
        name="get_order_details",
        domain="order",
        action_kind="read",
        useful_signal_keys=("order_id",),
        schema_provider=runtime_schema_provider("get_order_details"),
    ),
    "find_installation_partners": ToolCapability(
        name="find_installation_partners",
        domain="service",
        action_kind="read",
        useful_signal_keys=("location", "service_type", "selected_installation_partner", "branch_addons"),
        schema_provider=runtime_schema_provider("find_installation_partners"),
    ),
    "get_branch_addons": ToolCapability(
        name="get_branch_addons",
        domain="service",
        action_kind="read",
        useful_signal_keys=("location", "service_type", "selected_installation_partner", "branch_addons"),
        schema_provider=runtime_schema_provider("get_branch_addons"),
    ),
    "find_installation_slots": ToolCapability(
        name="find_installation_slots",
        domain="service",
        action_kind="read",
        useful_signal_keys=(
            "location",
            "service_type",
            "chosen_schedule_slot",
            "selected_installation_partner",
            "branch_addons",
        ),
        schema_provider=runtime_schema_provider("find_installation_slots"),
    ),
    "validate_installation_slot": ToolCapability(
        name="validate_installation_slot",
        domain="service",
        action_kind="read",
        requires_context_refs=("service_observation",),
        schema_provider=runtime_schema_provider("validate_installation_slot"),
    ),
    "request_capability": ToolCapability(
        name="request_capability",
        domain="general",
        action_kind="read",
        schema_provider=request_capability_schema,
    ),
}


PRODUCT_ENTRY_TOOL_NAMES: Sequence[str] = (
    "search_promo_catalog",
    "present_promo_gallery",
    "product_search",
    "discover_brand_buckets",
    "extract_compatible_fitment",
    "answer_product_faq",
)


SERVICE_ENTRY_TOOL_NAMES: Sequence[str] = (
    "answer_service_faq",
    "find_installation_partners",
    "get_branch_addons",
    "find_installation_slots",
)


ORDER_ENTRY_TOOL_NAMES: Sequence[str] = (
    "answer_order_faq",
    "calculate_order_quote",
    "build_order_summary",
    "build_order_payload",
    "submit_order",
    "prepare_payment_request",
    "match_payment_proof",
    "get_order_details",
)


def schemas_for_tool_names(tool_names: Sequence[str]) -> List[Dict[str, object]]:
    """Return tool schemas in the requested order, skipping duplicates."""

    schemas: List[Dict[str, object]] = []
    seen: set[str] = set()
    for name in tool_names:
        if name in seen:
            continue
        capability = TOOL_CAPABILITIES.get(name)
        if capability is None:
            continue
        schema = capability.schema_provider()
        if schema:
            schemas.append(schema)
            seen.add(name)
    return schemas
