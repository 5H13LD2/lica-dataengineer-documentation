"""Runtime V7 FAQ hinting and read-only FAQ tools.

FAQ hints are intentionally answer-free. They are cheap routing hints that tell
the model an FAQ tool may be useful without injecting policy answers directly
into the prompt.
"""

from __future__ import annotations

import math
import os
import re
import time
import uuid
from hashlib import sha1
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from runtime_v7.canonical_values import CanonicalValuesProvider
from runtime_v7.contact_policy import agent_assigned_from_payload, contact_answer_for_agent
from runtime_v7.delivery_payment_policy import (
    DELIVERY_LEAD_TIME,
    order_policy_answer_for_title,
)
from runtime_v7.fulfillment_aliases import enrich_text_for_delivery_faq
from runtime_v7.order_canonicalization import (
    checkout_metadata,
    payment_option_label,
    payment_plan_hints_from_text,
    resolve_payment_option,
    resolve_payment_selection,
    resolve_transaction_for_service_path,
    truthy,
)
from runtime_v7.payment_provider_display import (
    payment_provider_names_from_row,
    payment_provider_phrase,
)


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class FAQEntry:
    """Small FAQ record used by the deterministic Runtime V7 FAQ tools."""

    faq_id: str
    domain: str
    title: str
    question: str
    answer: str
    keywords: Sequence[str] = field(default_factory=tuple)

    @property
    def suggested_tool(self) -> str:
        if self.domain == "product":
            return "answer_product_faq"
        if self.domain == "service":
            return "answer_service_faq"
        if self.domain == "order":
            return "answer_order_faq"
        return f"answer_{self.domain}_faq"

    def hint(self, *, score: float, matched_terms: Sequence[str]) -> Dict[str, Any]:
        """Return an answer-free routing hint for prompt injection."""

        return {
            "faq_id": self.faq_id,
            "domain": self.domain,
            "title": self.title,
            "question": self.question,
            "suggested_tool": self.suggested_tool,
            "score": round(float(score), 4),
            "matched_terms": list(matched_terms[:5]),
            "topic": _faq_entry_topic(self),
        }


def _faq_entry_topic(entry: FAQEntry) -> str:
    """Classify authored FAQ metadata without interpreting customer prose."""

    if entry.domain != "product":
        return ""
    authored_text = " ".join(
        [
            entry.title,
            entry.question,
            *[str(value) for value in entry.keywords],
        ]
    ).casefold()
    if any(
        term in authored_text
        for term in ("warranty", "guarantee", "factory defect")
    ):
        return "warranty"
    return ""


def _faq_id_for_question(question: str, *, domain: str = "product") -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(question or "").strip().lower()).strip("_")
    if normalized:
        return f"{domain}_{normalized[:72]}"
    digest = sha1(str(question or "").encode("utf-8")).hexdigest()[:12]
    return f"{domain}_faq_{digest}"


PRODUCT_FAQ_QUESTIONS: Dict[str, Sequence[str]] = {
    "Are your tires brand new?": ("brand new", "authentic", "legitimate", "distributor"),
    "How do I check my tire size?": ("tire size", "sidewall", "size", "check size"),
    "Can I return / exchange my tires?": ("return", "exchange", "wrong tire", "refund tire"),
    "Do your tires have a warranty?": ("warranty", "guarantee", "factory defects", "garantiya"),
    "How do I claim a warranty?": ("claim warranty", "warranty claim", "supplier investigation"),
    "Do you have ongoing promos?": ("promo", "promos", "discount", "sale"),
    "What does limited stocks mean?": ("limited stocks", "stock", "availability", "available"),
    "Do you accept trade in?": ("trade in", "trade-in", "tradein"),
    "Do you sell mags?": ("mags", "wheels", "rims"),
    "What happens if the tires I ordered are no longer available?": ("no longer available", "out of stock", "alternate tires"),
    "What kind of damages covered by warranty?": ("damage", "damages", "covered by warranty", "warranty coverage"),
    "How long does the warranty investigation take?": ("warranty investigation", "investigation", "15 business days"),
    "Do you sell motorcycle tires?": ("motorcycle", "motor tires", "motorcycle tires"),
    "What if I mistakenly ordered the wrong tire": ("wrong tire", "mistakenly ordered", "wrong size"),
    "What are run-flat tires?": ("run flat", "runflat", "no flat", "noflat", "rft", "flat tire type"),
    "How do I read the DOT manufacturing date?": (
        "dot code",
        "dot date",
        "manufacturing date",
        "manufacture date",
        "production date",
        "week and year",
        "sidewall date",
    ),
}

PRODUCT_FAQ_ALIASES: Dict[str, str] = {
    "product_warranty_tpp": "Do your tires have a warranty?",
    "product_dot_origin": "How do I read the DOT manufacturing date?",
}
_PRODUCT_FAQ_CACHE: Optional[List[FAQEntry]] = None
ORDER_FAQ_QUESTIONS: Dict[str, Sequence[str]] = {
    "Who is Gulong.ph?": (
        "who is gulong",
        "about gulong",
        "company",
        "lica automotive",
        "legit company",
    ),
    "Why should I order from Gulong.ph?": (
        "why order",
        "why should i order",
        "why gulong",
        "legit ba",
        "trusted ba",
    ),
    "Can I request a formal quotation?": (
        "formal quotation",
        "formal quote",
        "official quotation",
        "official quote",
        "company quotation",
        "company quote",
        "corporate quotation",
        "corporate quote",
        "fleet quotation",
        "fleet quote",
        "quotation for purchase order",
        "quote for purchase order",
    ),
    "Do you issue an official receipt?": (
        "official receipt",
        "official receipts",
        "official resibo",
        "resibo",
        "sales invoice",
        "sales invoices",
        "issue receipt",
        "provide receipt",
        "send receipt",
        "or after installation",
        "or after purchase",
        "o.r.",
    ),
    "How do I Pay?": (
        "how do i pay",
        "how to pay",
        "pay",
        "paano payment",
        "paano magbayad",
        "payment",
        "payment method",
        "payment option",
        "pay now",
        "pay later",
        "pay after service",
        "pay full",
        "full amount",
        "p100 discount",
        "100 discount",
        "gcash",
        "credit card",
        "cash on delivery",
        "cod",
        "2c2p",
    ),
    "Do you offer installment payments?": (
        "installment",
        "bpi",
        "metrobank",
        "credit card installment",
        "0% interest",
        "bdo",
        "eastwest",
        "hsbc",
        "china bank",
    ),
    "Why do I need to pay for a reservation fee?": (
        "reservation fee",
        "reserve fee",
        "downpayment",
        "deposit",
        "secure slot",
        "secure order",
    ),
    "Can I cancel my order?": (
        "cancel order",
        "cancel",
        "cancellation",
        "cancel appointment",
        "cancel booking",
    ),
    "How do I know when my tires will be delivered?": (
        "when delivered",
        "delivery update",
        "delivery status",
        "track delivery",
        "madideliver",
        "kelan delivery",
    ),
    "How long does delivery take?": (
        "how long delivery",
        "delivery take",
        "delivery lead time",
        "delivery time",
        "delivery eta",
        "ilang araw delivery",
        "gaano katagal delivery",
    ),
    "How much is the delivery fee?": (
        "delivery fee",
        "shipping fee",
        "delivery charge",
        "magkano delivery",
        "how much delivery",
    ),
    "What is the delivery and payment process?": (
        "delivery and payment process",
        "delivery payment process",
        "delivery payment",
        "shipping process",
        "shipping carrier",
        "courier",
        "lalamove",
        "lazada delivery",
        "lazada",
        "j&t",
        "jnt",
        "j and t",
        "lbc",
        "payment delivery",
    ),
    "Do you do same day delivery?": (
        "same day delivery",
        "deliver today",
        "delivery today",
        "padeliver today",
    ),
    "Where can I leave a review or feedback?": (
        "review",
        "feedback",
        "leave review",
        "rate",
    ),
    "How long does it take to get my refund?": (
        "refund",
        "refund timing",
        "money back",
        "ibalik bayad",
        "refund process",
    ),
}
_ORDER_FAQ_CACHE: Optional[List[FAQEntry]] = None
SERVICE_FAQ_QUESTIONS: Dict[str, Sequence[str]] = {
    "What's included when I purchase tires from Gulong.ph?": (
        "included",
        "freebies",
        "free installation inclusions",
        "mounting",
        "balancing",
        "wheel weights",
        "tire valves",
        "valves",
        "pito",
        "kasama",
    ),
    "Do you accept walk-ins?": (
        "walk in",
        "walk-in",
        "walkins",
        "punta directly",
        "pwede pumunta",
    ),
    "How can I avail the free installation?": (
        "avail free installation",
        "free installation",
        "free install",
        "installation partners",
    ),
    "Do you offer Home Installation Service?": (
        "home installation",
        "home service",
        "install sa bahay",
        "home install fee",
    ),
    "How long does the tire installation take?": (
        "installation take",
        "installation duration",
        "how long install",
        "gaano katagal install",
        "ilang oras install",
    ),
    "What should I bring with me on my installation appointment?": (
        "what should i bring",
        "bring appointment",
        "bring installation",
        "dala",
        "kailangan dalhin",
        "appointment requirements",
    ),
    "What's the earliest installation date I can book?": (
        "earliest installation",
        "earliest appointment",
        "earliest schedule",
        "lead time",
        "book earlier",
    ),
    "What if I came in late?": (
        "came in late",
        "late appointment",
        "late sa schedule",
        "malelate",
        "late ako",
    ),
    "What if I missed my appointment schedule?": (
        "missed appointment",
        "missed schedule",
        "hindi naka punta",
        "di naka punta",
        "no show",
    ),
    "Can I reschedule my appointment schedule?": (
        "reschedule",
        "reschedule appointment",
        "reschedule booking",
        "change schedule",
        "change appointment",
        "lipat schedule",
    ),
    "Do you offer wheel alignment?": (
        "wheel alignment",
        "alignment",
        "add-on service",
        "addon service",
    ),
    "Do you offer nitrogen inflation?": (
        "nitrogen",
        "nitro",
        "nitrogen inflation",
        "nitrogen air",
        "nitrogen service",
    ),
    "Can I go directly to the installation site and order my tires there?": (
        "go directly",
        "installation site",
        "order tires there",
        "direct sa installation",
        "walk in installation site",
    ),
    "Do you do same day installation?": (
        "same day installation",
        "same day install",
        "install today",
        "today install",
        "asap install",
    ),
    "How to be a Gulong.ph installation partner?": (
        "be installation partner",
        "become a partner",
        "partner application",
        "apply partner",
    ),
    "What are your serviceable areas?": (
        "serviceable areas",
        "covered areas",
        "service areas",
        "available areas",
    ),
}
_SERVICE_FAQ_CACHE: Optional[List[FAQEntry]] = None
_FAQ_QUERY_EMBEDDING_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
_FAQ_RETRIEVAL_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
_FAQ_HINT_RETRIEVAL_CACHE: Dict[str, tuple[float, List[tuple[float, FAQEntry, List[str], str]]]] = {}


SERVICE_FAQS: Sequence[FAQEntry] = tuple(
    FAQEntry(
        faq_id=_faq_id_for_question(question, domain="service"),
        domain="service",
        title=question,
        question=question,
        answer="",
        keywords=keywords,
    )
    for question, keywords in SERVICE_FAQ_QUESTIONS.items()
)


def build_faq_hints(
    current_user_message: str,
    *,
    active_working_memory: str = "",
    max_hints: int = 2,
    embedding_gateway: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Return at most two answer-free FAQ routing hints."""

    latest_text = _normalize_text(enrich_text_for_delivery_faq(current_user_message))
    memory_text = _normalize_text(active_working_memory)
    if not latest_text:
        return []
    entries = _all_faq_entries()
    scored = _rank_faq_entries_hybrid(
        latest_text,
        entries,
        memory_text=memory_text,
        embedding_gateway=embedding_gateway,
        top_k=max(2, int(max_hints or 2)),
    )
    scored = [
        row
        for row in scored
        if _faq_hint_is_latest_turn_driven(row, latest_text=latest_text)
        and not _suppress_faq_hint_for_context(row[1], latest_text=latest_text, memory_text=memory_text)
    ]
    scored = _filter_dominant_faq_domain(scored)
    return [
        {
            **entry.hint(score=score, matched_terms=terms),
            "matched_by": matched_by,
        }
        for score, entry, terms, matched_by in scored[: max(1, int(max_hints or 2))]
    ]


def _faq_hint_is_latest_turn_driven(
    row: tuple[float, FAQEntry, List[str], str],
    *,
    latest_text: str,
) -> bool:
    """Keep memory as a booster, not as the source of a new FAQ objective."""

    _score, entry, _terms, matched_by = row
    if matched_by in {"vector", "hybrid_vector"}:
        return bool(_normalize_text(latest_text))
    latest_score, _latest_terms = _score_entry(latest_text, entry)
    return latest_score > 0


def _suppress_faq_hint_for_context(entry: FAQEntry, *, latest_text: str, memory_text: str) -> bool:
    """Suppress generic FAQ hints when the turn is asking for contextual tool reasoning."""

    if (
        entry.faq_id
        == _faq_id_for_question("What does limited stocks mean?", domain="product")
        and _is_human_support_availability_context(latest_text)
    ):
        # "Available" can describe people or chat support. It is not product-
        # stock evidence when the surrounding latest-turn nouns identify a
        # human-assistance question instead.
        return True

    if (
        entry.faq_id == _faq_id_for_question("Where can I leave a review or feedback?", domain="order")
        and _is_order_summary_review_context(" ".join([latest_text or "", memory_text or ""]))
    ):
        return True

    if (
        entry.faq_id
        == _faq_id_for_question(
            "How to be a Gulong.ph installation partner?",
            domain="service",
        )
        and not _explicit_installation_partner_application_intent(latest_text)
    ):
        # Ordinary customer installation searches repeatedly mention
        # "installation partner". Do not let semantic similarity turn that
        # service context into an unsolicited B2B application objective.
        return True

    if entry.faq_id != _faq_id_for_question("How do I check my tire size?"):
        return False
    latest = str(latest_text or "").lower()
    context = " ".join([latest, str(memory_text or "").lower()])
    has_fitment_context = any(
        token in context
        for token in [
            "fitment",
            "candidate size",
            "possible tire size",
            "pang ",
            "innova",
            "wigo",
            "vios",
            "avanza",
            "fortuner",
            "montero",
        ]
    )
    asks_which_size = any(
        token in latest
        for token in [
            "what size",
            "which size",
            "ano size",
            "anong size",
            "size dapat",
            "dapat na size",
            "sakto",
        ]
    )
    asks_how_to_read_sidewall = any(
        token in latest
        for token in [
            "how do i check",
            "how to check",
            "paano makita",
            "paano tingnan",
            "saan makikita",
            "where to find",
            "read",
            "sidewall",
            "nakasulat",
        ]
    )
    return has_fitment_context and asks_which_size and not asks_how_to_read_sidewall


def _is_human_support_availability_context(text: str) -> bool:
    """Recognize people/chat availability only to suppress a product FAQ false hit."""

    normalized = _normalize_text(text)
    if not normalized:
        return False
    human_terms = (
        "anyone",
        "somebody",
        "human",
        "customer service",
        "agent",
        "representative",
        "tao",
    )
    assistance_terms = (
        "assist",
        "assistance",
        "chat",
        "help",
        "tumulong",
        "kausap",
    )
    return any(term in normalized for term in human_terms) and any(
        term in normalized for term in assistance_terms
    )


def _explicit_installation_partner_application_intent(text: str) -> bool:
    """Return whether the latest turn explicitly asks to join the partner network."""

    normalized = _normalize_text(text)
    if not normalized:
        return False
    application_phrases = (
        "be an installation partner",
        "become an installation partner",
        "become installation partner",
        "how to be a gulong ph installation partner",
        "how to become a gulong ph installation partner",
        "apply as an installation partner",
        "apply as installation partner",
        "installation partner application",
        "maging installation partner",
        "mag apply bilang installation partner",
        "magapply bilang installation partner",
        "gusto maging installation partner",
    )
    return any(phrase in normalized for phrase in application_phrases)


def _is_order_summary_review_context(text: str) -> bool:
    """Return True when "review" refers to order-summary review, not feedback."""

    normalized = _normalize_text(text)
    if not normalized:
        return False
    if "review" not in normalized:
        return False
    order_terms = {
        "order",
        "summary",
        "details",
        "payload",
        "checkout",
        "submit",
        "reserve",
        "reservation",
    }
    feedback_terms = {"feedback", "rate", "rating", "testimonial", "experience"}
    terms = set(normalized.split())
    return bool(terms.intersection(order_terms)) and not bool(terms.intersection(feedback_terms))


def answer_product_faq(payload: Dict[str, Any], *, embedding_gateway: Optional[Any] = None) -> Dict[str, Any]:
    """Return a compact product FAQ answer from the real Gulong FAQ/RAG pool."""

    return _answer_product_rag_faq(payload or {}, embedding_gateway=embedding_gateway)


def answer_service_faq(payload: Dict[str, Any], *, embedding_gateway: Optional[Any] = None) -> Dict[str, Any]:
    """Return a compact service FAQ answer from the real Gulong FAQ/RAG pool."""

    return _answer_faq(
        payload or {},
        domain="service",
        entries=service_faq_entries(),
        embedding_gateway=embedding_gateway,
    )


def answer_policy_faq(
    payload: Dict[str, Any],
    *,
    embedding_gateway: Optional[Any] = None,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Dict[str, Any]:
    """Return grounded cross-domain policy evidence with routing metadata.

    A validated ``service_type=delivery`` is a typed retrieval scope, not a
    serviceability result. It selects the authored general delivery-process
    policy when free-form wording alone has no more specific FAQ domain.
    """

    payload = payload or {}
    question = str(payload.get("question") or "").strip()
    customer_context = str(payload.get("customer_context") or "").strip()
    query = " ".join(part for part in [question, customer_context] if part).strip()
    routed_domain = _policy_domain_for_query(query)
    structured_delivery = (
        _normalize_text(payload.get("service_type")) == "delivery"
    )
    delivery_scope_fallback = not routed_domain and structured_delivery
    if delivery_scope_fallback:
        routed_domain = "order"
    if routed_domain == "order":
        routed_payload = dict(payload)
        if _looks_like_delivery_fee_policy_query(query):
            routed_payload.setdefault("faq_id", "order_how_much_is_the_delivery_fee")
            routed_payload["question"] = question or "How much is the delivery fee?"
        elif delivery_scope_fallback:
            routed_payload.setdefault(
                "faq_id",
                "order_how_long_does_delivery_take",
            )
        result = answer_order_faq(
            routed_payload,
            embedding_gateway=embedding_gateway,
            canonical_values_provider=canonical_values_provider,
        )
    elif routed_domain == "service":
        result = answer_service_faq(payload, embedding_gateway=embedding_gateway)
    elif routed_domain == "product":
        result = answer_product_faq(payload, embedding_gateway=embedding_gateway)
    else:
        result = _answer_cross_domain_policy_faq(
            payload,
            embedding_gateway=embedding_gateway,
            canonical_values_provider=canonical_values_provider,
        )

    result = deepcopy(result)
    result["matched_domain"] = result.get("domain") or routed_domain or ""
    result["policy_type"] = _policy_type_for_faq_result(result)
    result["applicability"] = "policy_general"
    if result["policy_type"] == "delivery_fee":
        policy_facts = _delivery_fee_policy_facts()
        context_application = _delivery_fee_policy_application(customer_context)
        result["requires_context"] = ["selected_product_or_category"]
        result["answer_basis"] = result.get("answer") or ""
        result["policy_facts"] = policy_facts
        result["context_policy_application"] = context_application
        result["composition_hint"] = (
            "Use this as policy evidence. Apply the fee to trusted visible or selected product "
            "brand/category context when available. Answer only the applicable fee for the active "
            "customer options; do not recite the full policy unless the customer asks for it."
        )
    elif result["policy_type"] == "delivery_process":
        result["required_answer_facts"] = [
            {
                "fact_id": "greater_manila_delivery_path",
                "canonical_text": "Greater Manila Area: Lalamove",
                "all_terms": ["greater", "manila", "area", "lalamove"],
            },
            {
                "fact_id": "delivery_lead_time",
                "canonical_text": (
                    f"Estimated delivery time: {DELIVERY_LEAD_TIME}"
                ),
                "regex": r"\b7\s*(?:-|to|hanggang)\s*10\s*(?:days?|araw)\b",
            },
        ]
        result["composition_hint"] = (
            "Answer directly that Gulong.ph offers delivery through the stated "
            "Greater Manila and outside-Metro paths. Do not confirm an exact "
            "street-address serviceability result or delivery date unless a "
            "separate validated provider supplies it."
        )
    else:
        result["composition_hint"] = (
            "Use this policy answer as grounding for the customer's situation. Compose a short "
            "direct reply; do not recite unrelated FAQ details."
        )
    return result


def answer_order_faq(
    payload: Dict[str, Any],
    *,
    embedding_gateway: Optional[Any] = None,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Dict[str, Any]:
    """Return a compact order/payment FAQ answer from the real Gulong FAQ/RAG pool."""

    return _answer_faq(
        payload or {},
        domain="order",
        entries=order_faq_entries(),
        embedding_gateway=embedding_gateway,
        canonical_values_provider=canonical_values_provider,
    )


PAYMENT_ORDER_FAQ_IDS = frozenset(
    {
        "order_how_do_i_pay",
        "order_do_you_offer_installment_payments",
        "order_what_is_the_delivery_and_payment_process",
        "order_why_do_i_need_to_pay_for_a_reservation_fee",
    }
)


def order_faq_requires_payment_scope(payload: Mapping[str, Any]) -> bool:
    """Return whether an order FAQ plan needs typed payment authorization."""

    if str((payload or {}).get("requested_payment_method") or "").strip():
        return True
    if str((payload or {}).get("requested_payment_category") or "").strip():
        return True
    faq_id = resolve_faq_id_for_payload(dict(payload or {}), domain="order")
    return faq_id in PAYMENT_ORDER_FAQ_IDS


def _policy_domain_for_query(query: str) -> str:
    lowered = _normalize_text(query)
    if not lowered:
        return ""
    if _looks_like_delivery_fee_policy_query(lowered):
        return "order"
    if _looks_like_order_domain_question(lowered):
        return "order"
    if _looks_like_nitrogen_addon_question(lowered):
        return "service"
    if any(
        token in lowered
        for token in [
            "free install",
            "installation",
            "mounting",
            "balancing",
            "valves",
            "pito",
            "walk in",
            "walk-in",
            "same day install",
            "reschedule appointment",
        ]
    ):
        return "service"
    if _looks_like_run_flat_feature_question(lowered):
        return "product"
    return ""


def _looks_like_delivery_fee_policy_query(text: str) -> bool:
    lowered = _normalize_text(text)
    return any(
        token in lowered
        for token in [
            "delivery fee",
            "shipping fee",
            "delivery charge",
            "free delivery",
            "free deliver",
            "free shipping",
            "magkano delivery",
            "how much delivery",
            "shipping",
        ]
    )


def _answer_cross_domain_policy_faq(
    payload: Dict[str, Any],
    *,
    embedding_gateway: Optional[Any] = None,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Dict[str, Any]:
    question = str(payload.get("question") or "").strip()
    customer_context = str(payload.get("customer_context") or "").strip()
    query = " ".join(part for part in [question, customer_context] if part).strip()
    entries = [*order_faq_entries(), *service_faq_entries(), *product_faq_entries()]
    matches = _rank_faq_entries_hybrid(query, entries, embedding_gateway=embedding_gateway, top_k=1) if query else []
    if not matches:
        return {
            "status": "no_match",
            "domain": "policy",
            "question": question,
            "answer": "",
            "reason": "no policy FAQ match",
            "source": "runtime_v7_policy_faq_facade",
            "generated_at": _utc_now_iso(),
            "ttl_seconds": 86400,
        }
    _score, entry, _terms, _matched_by = matches[0]
    if entry.domain == "order":
        return answer_order_faq(
            {**payload, "faq_id": entry.faq_id},
            embedding_gateway=embedding_gateway,
            canonical_values_provider=canonical_values_provider,
        )
    if entry.domain == "service":
        return answer_service_faq({**payload, "faq_id": entry.faq_id}, embedding_gateway=embedding_gateway)
    return answer_product_faq({**payload, "faq_id": entry.faq_id}, embedding_gateway=embedding_gateway)


def _policy_type_for_faq_result(result: Dict[str, Any]) -> str:
    text = _normalize_text(" ".join(str(result.get(key) or "") for key in ("faq_id", "question", "title", "answer")))
    if any(token in text for token in ["delivery fee", "shipping fee", "free delivery", "free shipping"]):
        return "delivery_fee"
    if any(
        token in text
        for token in [
            "delivery process",
            "shipping process",
            "courier",
            "how long delivery",
            "lalamove",
            "lazada",
        ]
    ):
        return "delivery_process"
    if any(token in text for token in ["payment", "pay now", "pay later", "cod", "installment"]):
        return "payment_policy"
    if any(token in text for token in ["free installation", "mounting", "balancing", "valves", "pito"]):
        return "installation_inclusions"
    return ""


def _delivery_fee_policy_facts() -> Dict[str, Any]:
    return {
        "free_delivery_categories": ["Premium"],
        "paid_delivery_categories": ["Budget", "Economy", "Mid-Range"],
        "paid_delivery_fee_php": 500,
    }


def _delivery_fee_policy_application(customer_context: str) -> Dict[str, Any]:
    normalized = _normalize_text(customer_context)
    matched_categories: List[str] = []
    if "premium" in normalized:
        matched_categories.append("Premium")
    if "budget" in normalized:
        matched_categories.append("Budget")
    if "economy" in normalized:
        matched_categories.append("Economy")
    if "mid range" in normalized or "mid-range" in normalized or "midrange" in normalized:
        matched_categories.append("Mid-Range")
    matched_categories = list(dict.fromkeys(matched_categories))
    paid_categories = {"budget", "economy", "mid-range"}
    free_categories = {"premium"}
    normalized_matches = {_normalize_text(category) for category in matched_categories}
    paid_match = bool(normalized_matches & paid_categories)
    free_match = bool(normalized_matches & free_categories)
    if paid_match and not free_match:
        applicability = "paid_delivery_fee_applies"
        delivery_fee_php: Optional[int] = 500
    elif free_match and not paid_match:
        applicability = "free_delivery_applies"
        delivery_fee_php = 0
    elif paid_match and free_match:
        applicability = "mixed_categories_need_product_choice"
        delivery_fee_php = None
    else:
        applicability = "needs_selected_product_or_category"
        delivery_fee_php = None
    return {
        "matched_categories": matched_categories,
        "applicability": applicability,
        "delivery_fee_php": delivery_fee_php,
    }


def resolve_faq_id_for_payload(payload: Dict[str, Any], *, domain: str) -> str:
    """Resolve a FAQ payload to the canonical FAQ id without returning the answer."""

    payload = payload or {}
    faq_id = str(payload.get("faq_id") or "").strip()
    entries_by_domain = {
        "product": product_faq_entries,
        "service": service_faq_entries,
        "order": order_faq_entries,
    }
    loader = entries_by_domain.get(str(domain or "").strip())
    if loader is None:
        return faq_id
    entries = loader()
    entry = _find_entry(entries, faq_id=faq_id)
    if entry is not None:
        return entry.faq_id

    question = str(payload.get("question") or "").strip()
    customer_context = str(payload.get("customer_context") or "").strip()
    query = " ".join(part for part in [question, customer_context] if part).strip()
    if not query:
        return faq_id
    matches = _rank_faq_entries_hybrid(query, entries, embedding_gateway=None, top_k=1)
    if matches:
        _score, entry, _terms, _matched_by = matches[0]
        return entry.faq_id
    return faq_id


def _answer_product_rag_faq(payload: Dict[str, Any], *, embedding_gateway: Optional[Any] = None) -> Dict[str, Any]:
    faq_id = str(payload.get("faq_id") or "").strip()
    question = str(payload.get("question") or "").strip()
    customer_context = str(payload.get("customer_context") or "").strip()
    query = question or customer_context
    entries = product_faq_entries()
    entry = _find_entry(entries, faq_id=faq_id)
    if entry is None and faq_id in PRODUCT_FAQ_ALIASES:
        entry = _find_entry(entries, faq_id=_faq_id_for_question(PRODUCT_FAQ_ALIASES[faq_id]))
    matched_by = "faq_id" if entry else ""
    if entry is None and query:
        matches = _rank_entries(query, entries)
        if matches:
            _score, entry, _terms = matches[0]
            matched_by = "question_similarity"

    if _looks_like_order_domain_question(query or question):
        return _product_faq_no_match(
            question=question,
            reason="question belongs to the order/payment or service domain, not product FAQ",
        )
    if _looks_like_nitrogen_addon_question(query or question):
        return _product_faq_no_match(
            question=question,
            reason="question asks about nitrogen service/add-on, not product FAQ",
        )
    if _looks_like_run_flat_feature_question(query or question):
        return _product_concept_faq_answer(
            question=question,
            concept_question="What are run-flat tires?",
            answer=(
                "Run-flat tires are tire models designed to keep supporting the vehicle for a limited distance "
                "after air-pressure loss or a puncture, usually at reduced speed and only within the tire/vehicle "
                "maker's limits. Regular tires are not run-flat unless the product details, model marking, or "
                "sidewall explicitly say run-flat/RFT. Nitrogen inflation is different; it is only an inflation "
                "service/add-on and does not make a tire run-flat or no-flat."
            ),
        )

    policy_answer = (
        _product_policy_answer_for_title(entry.question) if entry is not None else ""
    )
    if entry is not None and policy_answer:
        return {
            "status": "ok",
            "domain": "product",
            "faq_id": entry.faq_id,
            "evidence_ref": f"faq:product:{entry.faq_id}",
            "title": entry.title,
            "question": entry.question,
            "answer": policy_answer,
            "matched_by": matched_by or "question_similarity",
            "source": "runtime_v7_product_policy",
            "retrieval": {
                "strategy": "runtime_v7_owned_policy",
                "chunk_count": 0,
            },
            "generated_at": _utc_now_iso(),
            "ttl_seconds": 86400,
        }

    retrieval_query = question or (entry.question if entry else "") or customer_context
    chunks_payload = (
        _direct_product_faq_payload(entry.question)
        if entry is not None and faq_id and not customer_context
        else _rank_product_rag_chunks(
            retrieval_query,
            preferred_title=entry.question if entry else "",
            embedding_gateway=embedding_gateway,
        )
    )
    chunks = chunks_payload.get("chunks") or []
    chunk = chunks[0] if chunks else None
    if entry is not None and chunk is None:
        chunk = _rag_chunk_for_title(entry.question)
    if entry is None and chunk is not None:
        entry = _entry_for_title(str(chunk.get("title") or ""), entries)
        matched_by = matched_by or _matched_by_from_retrieval(chunks_payload)
    if chunk is None and entry is None:
        return _product_faq_no_match(question=question, reason="no product FAQ match")

    answer = _answer_from_chunk(chunk) if chunk else str(entry.answer if entry else "")
    selected_title = str((chunk or {}).get("title") or (entry.title if entry else "")).strip()
    selected_question = str((entry.question if entry else selected_title) or selected_title).strip()
    return {
        "status": "ok",
        "domain": "product",
        "faq_id": entry.faq_id if entry else _faq_id_for_question(selected_question),
        "evidence_ref": (
            f"faq:product:"
            f"{entry.faq_id if entry else _faq_id_for_question(selected_question)}"
        ),
        "title": selected_title or selected_question,
        "question": selected_question,
        "answer": answer,
        "matched_by": matched_by or _matched_by_from_retrieval(chunks_payload),
        "source": "runtime_v7_product_faq_rag_subset",
        "retrieval": _compact_retrieval_payload(chunks_payload, selected_chunk=chunk),
        "generated_at": _utc_now_iso(),
        "ttl_seconds": 86400,
    }


def _answer_faq(
    payload: Dict[str, Any],
    *,
    domain: str,
    entries: Sequence[FAQEntry],
    embedding_gateway: Optional[Any] = None,
    canonical_values_provider: Optional[CanonicalValuesProvider] = None,
) -> Dict[str, Any]:
    faq_id = str(payload.get("faq_id") or "").strip()
    question = str(payload.get("question") or "").strip()
    customer_context = str(payload.get("customer_context") or "").strip()
    query = " ".join(part for part in [question, customer_context] if part).strip()
    entry = _find_entry(entries, faq_id=faq_id)
    matched_by = "faq_id" if entry else ""
    if entry is None and query:
        matches = _rank_faq_entries_hybrid(
            query,
            entries,
            embedding_gateway=embedding_gateway,
            top_k=1,
        )
        if matches:
            _score, entry, _terms, matched_by = matches[0]
    if domain == "order" and not entry and str(payload.get("requested_payment_method") or "").strip():
        entry = _find_entry(
            entries,
            faq_id=_faq_id_for_question("How do I Pay?", domain="order"),
        )
        matched_by = "runtime_payment_policy_query" if entry else ""
    if (
        domain == "order"
        and entry is not None
        and entry.faq_id in PAYMENT_ORDER_FAQ_IDS
        and str(payload.get("requested_payment_method") or "").strip()
    ):
        matched_by = "runtime_payment_policy_query"
    if (
        domain == "order"
        and entry is not None
        and entry.faq_id == _faq_id_for_question("Where can I leave a review or feedback?", domain="order")
        and _is_order_summary_review_context(query)
    ):
        entry = None
        matched_by = ""
    if entry is None:
        return {
            "status": "no_match",
            "domain": domain,
            "question": question or query,
            "answer": "",
            "source": f"runtime_v7_{domain}_faq_subset",
            "generated_at": _utc_now_iso(),
            "ttl_seconds": 86400,
        }
    answer = entry.answer
    if domain == "order" and entry.question == "How do I contact Gulong.ph?":
        answer = contact_answer_for_agent(agent_assigned_from_payload(payload))
    payment_policy: Dict[str, Any] = {}
    if domain == "order" and entry.question in {
        "How do I Pay?",
        "Do you offer installment payments?",
        "What is the delivery and payment process?",
        "Why do I need to pay for a reservation fee?",
    }:
        payment_policy_payload = dict(payload)
        if not str(payment_policy_payload.get("faq_id") or "").strip():
            payment_policy_payload["faq_id"] = entry.faq_id
        payment_policy = _payment_policy_from_checkout_metadata(
            payment_policy_payload,
            canonical_values_provider=canonical_values_provider,
        )
        answer = str(payment_policy.get("answer") or "")
    result = {
        "status": "ok",
        "domain": domain,
        "faq_id": entry.faq_id,
        "evidence_ref": f"faq:{domain}:{entry.faq_id}",
        "title": entry.title,
        "question": entry.question,
        "answer": answer,
        "matched_by": matched_by,
        "source": payment_policy.get("source") or f"runtime_v7_{domain}_faq_subset",
        "generated_at": _utc_now_iso(),
        "ttl_seconds": 86400,
    }
    if payment_policy:
        result["payment_policy"] = payment_policy
        if payment_policy.get("reservation_fee_guidance"):
            result["composition_hint"] = (
                "Silently use reservation fee as the correct term in this tire-order context. "
                "Do not quote, repeat, name, define, contrast, or announce the customer's original "
                "wording. Start directly with a natural clause such as 'May reservation fee po...' "
                "Never use constructions such as 'ang tawag', 'tinatawag', 'ibig sabihin', or "
                "'equivalent to' for this normalization. State the source-backed purpose directly. "
                "When the exact amount is not "
                "available yet, do not describe a data/source gap; connect the customer to the next "
                "grounded selection or quote step needed to confirm it, and do not invent an amount."
            )
        elif payment_policy.get("requested_payment_category"):
            result["composition_hint"] = (
                "Answer the requested payment category directly from category_methods and its "
                "payment_option scope. These are current checkout catalog rows. Do not replace "
                "them with another category, infer a product/brand restriction, or ask an "
                "unrelated tire-shopping question."
            )
        elif payment_policy.get("requested_payment_method"):
            result["composition_hint"] = (
                "Answer the named payment-method question directly from requested_payment_status "
                "and requested_brand_eligibility. Do not recite the full payment catalog. If the "
                "method is unsupported, offer at most three relevant alternatives from "
                "active_methods_by_option or ask whether the customer prefers Pay Now or Pay Later. "
                "If requested_brand_eligibility is not_eligible, say the complete named checkout "
                "method is unavailable for that brand; do not narrow the negative result to only "
                "an interest rate, discount, or other method benefit."
            )
        else:
            result["composition_hint"] = (
                "Treat active_methods_by_option as a current method catalog, not proof that every "
                "method applies under both Pay Now and Pay Later. Do not assign a method to a "
                "payment option, product/brand, or service path until those checkout dimensions "
                "are present and the filtered policy or checkout surface confirms compatibility."
            )
    return result


def _payment_policy_from_checkout_metadata(
    payload: Dict[str, Any],
    *,
    canonical_values_provider: Optional[CanonicalValuesProvider],
) -> Dict[str, Any]:
    """Build payment FAQ facts from active checkout metadata, not static copy."""

    metadata = checkout_metadata(canonical_values_provider)
    service_path = _fulfillment_context_from_payload(payload)
    transaction = resolve_transaction_for_service_path(service_path, metadata)
    transaction_id = str(transaction.get("id") or "").strip()
    rows = []
    for row in metadata.get("payment_types") or []:
        if not isinstance(row, dict) or truthy(row.get("is_disabled")):
            continue
        excluded = str(row.get("exclude_transaction_type_id") or "").strip()
        if excluded and transaction_id and excluded == transaction_id:
            continue
        rows.append(dict(row))

    by_option: Dict[str, List[Dict[str, Any]]] = {}
    option_names = {
        str(row.get("id") or ""): str(row.get("name") or "").strip()
        for row in metadata.get("payment_options") or []
        if isinstance(row, dict)
    }
    for row in rows:
        option_id = str(row.get("main_payment_type_id") or "").strip()
        by_option.setdefault(option_id, []).append(row)

    reservation_fee_guidance = _reservation_fee_guidance(
        metadata.get("payment_options") or [],
        question_topics=payload.get("question_topics"),
        faq_id=payload.get("faq_id"),
    )

    requested_method = str(payload.get("requested_payment_method") or "").strip()
    requested_category = str(payload.get("requested_payment_category") or "").strip()
    requested_brand = str(payload.get("requested_product_brand") or "").strip()
    requested_status = ""
    selection: Dict[str, Any] = {}
    generic_installment_request = _is_generic_installment_request(
        requested_method,
        payload=payload,
    )
    if requested_method and not generic_installment_request:
        plan_hints = payment_plan_hints_from_text(
            requested_method,
            payload.get("question"),
            payload.get("customer_context"),
        )
        selection = resolve_payment_selection(
            payment_option=str(payload.get("payment_option") or ""),
            payment_method=requested_method,
            bank=plan_hints["bank"],
            installment_months=plan_hints["installment_months"],
            metadata={**metadata, "payment_types": rows},
        )
        requested_status = str(selection.get("status") or "")
    elif generic_installment_request:
        # A broad installment question is not a choice of the first matching
        # checkout row. Keep all applicable current terms for composition.
        requested_status = "multiple_options"

    lines: List[str] = []
    if requested_method and requested_status == "unsupported":
        lines.append(f"{requested_method} is not currently a supported payment method.")
    elif requested_method and requested_status == "conflict":
        option_label = payment_option_label(payload.get("payment_option"))
        scope = f" under {option_label}" if option_label else " in the requested combination"
        lines.append(f"{requested_method} is not currently available{scope}.")
    brand_eligibility = ""
    selected_payment_row = selection.get("payment_type_row")
    selected_payment_row = dict(selected_payment_row) if isinstance(selected_payment_row, dict) else {}
    if requested_brand and selected_payment_row:
        allowed_brands = {
            value.strip().upper()
            for value in str(selected_payment_row.get("available_brands") or "").split(",")
            if value.strip()
        }
        normalized_brand = requested_brand.upper()
        if allowed_brands:
            brand_eligibility = (
                "eligible"
                if normalized_brand in allowed_brands
                else "not_eligible"
            )
        else:
            brand_eligibility = "not_brand_restricted"
        payment_name = str(selected_payment_row.get("name") or requested_method).strip()
        if brand_eligibility in {"eligible", "not_brand_restricted"}:
            lines.append(f"{requested_brand} is eligible for {payment_name}.")
        else:
            lines.append(
                f"{requested_brand} is not currently eligible for {payment_name}."
            )
    elif requested_method and selected_payment_row:
        payment_name = str(
            selected_payment_row.get("name") or requested_method
        ).strip()
        lines.append(f"{payment_name} is currently supported.")

    active_methods_by_option: Dict[str, List[str]] = {}
    for option_id, option_rows in by_option.items():
        label = option_names.get(option_id) or f"Payment option {option_id}"
        names = list(
            dict.fromkeys(
                str(row.get("name") or row.get("label") or "").strip()
                for row in option_rows
            )
        )
        names = [name for name in names if name]
        if names:
            active_methods_by_option[label] = names
    category_rows = _payment_rows_for_category(
        rows,
        requested_category=requested_category,
        payment_option=payload.get("payment_option"),
        payment_options=metadata.get("payment_options") or [],
    )
    category_methods = list(
        dict.fromkeys(
            str(row.get("name") or row.get("label") or "").strip()
            for row in category_rows
            if str(row.get("name") or row.get("label") or "").strip()
        )
    )
    if requested_category:
        category_label = _payment_category_label(requested_category)
        option_label = payment_option_label(payload.get("payment_option"))
        scope = f" under {option_label}" if option_label else ""
        if category_methods:
            lines.append(
                f"Current {category_label}{scope}: {', '.join(category_methods)}."
            )
        else:
            lines.append(
                f"No active {category_label}{scope} were returned by the current checkout catalog."
            )
    elif (
        not requested_method
        and not reservation_fee_guidance
        and service_path
        and requested_brand
    ):
        lines.append("Current payment options:")
        for label, names in active_methods_by_option.items():
            lines.append(f"- {label}: {', '.join(names)}")
    elif not requested_method and not reservation_fee_guidance:
        requested_option_label = payment_option_label(
            payload.get("payment_option")
        )
        if (
            requested_option_label
            and active_methods_by_option.get(requested_option_label)
        ):
            lines.append(
                f"{requested_option_label} is currently available as a checkout option."
            )
            lines.append(
                "The compatible payment methods still depend on the selected "
                "tire and service option."
            )
        else:
            catalog_names = list(
                dict.fromkeys(
                    name
                    for names in active_methods_by_option.values()
                    for name in names
                )
            )
            lines.append("Current payment options:")
            if catalog_names:
                lines.append(
                    "- Current method catalog: " + ", ".join(catalog_names)
                )
            lines.append(
                "- Exact availability under Pay Now or Pay Later depends on the "
                "selected tire and service option. I can show the compatible "
                "checkout methods after those are confirmed."
            )

    installments = []
    for row in rows:
        text = " ".join(str(row.get(key) or "") for key in ("name", "label", "description"))
        if truthy(row.get("is_installment")) or "installment" in text.lower():
            installments.append(
                {
                    "payment_type_id": row.get("id"),
                    "name": row.get("name"),
                    "payment_option_id": row.get("main_payment_type_id"),
                    "available_brands": row.get("available_brands"),
                    "exclude_transaction_type_id": row.get("exclude_transaction_type_id"),
                    "updated_at": row.get("updated_at"),
                }
            )
    applicable_installment_options = (
        _applicable_installment_options(
            rows,
            requested_brand=requested_brand,
        )
        if generic_installment_request
        else []
    )
    if generic_installment_request and applicable_installment_options:
        lines.append(
            "Applicable installment options: "
            + "; ".join(
                _installment_option_customer_text(option)
                for option in applicable_installment_options
            )
            + "."
        )
    if reservation_fee_guidance:
        reservation_line = (
            str(reservation_fee_guidance.get("purpose") or "").strip()
            or "A reservation fee is required to secure the order."
        )
        if reservation_line not in lines:
            lines.append(reservation_line)
    customer_method_categories = _customer_payment_method_categories(rows)
    return {
        "source": str(metadata.get("source") or "gulong_api_checkout_metadata"),
        "metadata_generated_at_epoch_s": metadata.get("generated_at_epoch_s"),
        "metadata_ttl_seconds": metadata.get("ttl_seconds"),
        "requested_payment_method": requested_method or None,
        "requested_payment_category": requested_category or None,
        "category_methods": category_methods,
        "requested_payment_status": requested_status or None,
        "requested_product_brand": requested_brand or None,
        "requested_brand_eligibility": brand_eligibility or None,
        "requested_payment_type_id": selected_payment_row.get("id") if selected_payment_row else None,
        "requested_payment_name": (
            selected_payment_row.get("name")
            if selected_payment_row
            else None
        ),
        "requested_payment_type_updated_at": (
            selected_payment_row.get("updated_at")
            if selected_payment_row
            else None
        ),
        "payment_option": selection.get("payment_option")
        or payment_option_label(payload.get("payment_option"))
        or None,
        "service_path": service_path or None,
        "transaction_type_id": transaction.get("id") if transaction else None,
        "active_payment_type_ids": [row.get("id") for row in rows],
        "active_methods_by_option": active_methods_by_option,
        "customer_method_categories": customer_method_categories,
        "installment_options": installments,
        "applicable_installment_options": applicable_installment_options,
        "reservation_fee_guidance": reservation_fee_guidance,
        "answer": "\n".join(lines),
    }


def _is_generic_installment_request(
    requested_method: Any,
    *,
    payload: Mapping[str, Any],
) -> bool:
    """Return whether a customer asked for the available installment choices."""

    method = _normalize_text(requested_method)
    if "installment" not in method:
        return False
    hints = payment_plan_hints_from_text(
        requested_method,
        payload.get("question"),
        payload.get("customer_context"),
    )
    if hints.get("bank") or hints.get("installment_months"):
        return False
    return method in {
        "installment",
        "credit card installment",
        "card installment",
        "credit installment",
    }


def _applicable_installment_options(
    rows: Sequence[Dict[str, Any]],
    *,
    requested_brand: str = "",
) -> List[Dict[str, Any]]:
    """Project active checkout installment rows into customer-safe terms.

    The projection keeps only current checkout data, filters brand-scoped
    terms before composition, and retains the provider wording found in the
    authoritative row description. Checkout timing is deliberately omitted:
    it is internal context unless the customer asked about that distinction.
    """

    normalized_brand = str(requested_brand or "").strip().upper()
    output: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        text = " ".join(
            str(row.get(key) or "")
            for key in ("name", "label", "description")
        )
        if not (truthy(row.get("is_installment")) or "installment" in text.casefold()):
            continue
        allowed_brands = [
            value.strip().upper()
            for value in str(row.get("available_brands") or "").split(",")
            if value.strip()
        ]
        if normalized_brand and allowed_brands and normalized_brand not in allowed_brands:
            continue
        name = str(row.get("name") or row.get("label") or "").strip()
        if not name:
            continue
        providers = _installment_provider_association(row)
        identity = (name.casefold(), providers.casefold())
        if identity in seen:
            continue
        seen.add(identity)
        output.append(
            {
                "name": name,
                "providers": providers or None,
                "eligible_brands": allowed_brands or None,
                "source_payment_type_ids": [row.get("id")],
            }
        )
    return output


def _installment_provider_association(row: Mapping[str, Any]) -> str:
    """Extract a provider phrase from the authoritative checkout row."""

    return payment_provider_phrase(payment_provider_names_from_row(row))


def _installment_option_customer_text(option: Mapping[str, Any]) -> str:
    """Format one authority-backed installment term without checkout labels."""

    name = str((option or {}).get("name") or "").strip()
    providers = str((option or {}).get("providers") or "").strip()
    return f"{name} ({providers})" if providers else name


def _reservation_fee_guidance(
    payment_options: Sequence[Mapping[str, Any]],
    *,
    question_topics: Any,
    faq_id: Any,
) -> Dict[str, Any]:
    """Expose reservation-fee meaning without inventing an amount.

    In a tire-order turn, down payment/deposit is normally the reservation-fee
    question. The current payment-option metadata owns its purpose; it does
    not imply a universal amount.
    """

    topics = {
        str(value or "").strip()
        for value in (question_topics if isinstance(question_topics, list) else [])
        if str(value or "").strip()
    }
    semantic_scope = "reservation_fee" in topics or str(faq_id or "").strip() == (
        "order_why_do_i_need_to_pay_for_a_reservation_fee"
    )
    if not semantic_scope:
        return {}
    reservation_option = next(
        (
            dict(option)
            for option in payment_options or []
            if isinstance(option, Mapping)
            and "reservation fee" in _normalize_text(
                " ".join(
                    str(option.get(key) or "")
                    for key in ("name", "label", "description")
                )
            )
        ),
        {},
    )
    description = str(reservation_option.get("description") or "").strip()
    if not reservation_option:
        return {}
    return {
        "customer_term": "down payment",
        "canonical_term": "reservation fee",
        "purpose": description or None,
        "amount_available": False,
    }


def _payment_rows_for_category(
    rows: Sequence[Dict[str, Any]],
    *,
    requested_category: str,
    payment_option: Any,
    payment_options: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Filter checkout rows by a model-typed generic payment category."""

    category = str(requested_category or "").strip()
    if not category:
        return []
    option = resolve_payment_option(payment_option, {"payment_options": payment_options}) if payment_option else {}
    option_id = str(option.get("id") or "")
    scoped = [
        row
        for row in rows
        if not option_id
        or str(row.get("main_payment_type_id") or "") == option_id
    ]
    if category == "all_methods":
        return scoped

    output: List[Dict[str, Any]] = []
    for row in scoped:
        text = " ".join(
            str(row.get(key) or "").lower()
            for key in ("name", "label", "value", "description")
        )
        value = str(row.get("value") or "").strip().upper()
        is_installment = truthy(row.get("is_installment")) or "installment" in text
        matches = {
            "e_wallet": value in {"EWALLET", "GCASH"} or "e-wallet" in text or "ewallet" in text,
            "card": value == "CC" or " card" in f" {text}" or is_installment,
            "installment": is_installment,
            "bank_transfer": value == "WEBPAY" or "online banking" in text or "direct debit" in text,
            "financing": is_installment,
        }
        if matches.get(category) is True:
            output.append(row)
    return output


def _payment_category_label(category: str) -> str:
    """Return a customer-readable label for a typed payment category."""

    return {
        "e_wallet": "e-wallet options",
        "card": "card payment options",
        "installment": "installment options",
        "bank_transfer": "online banking options",
        "financing": "financing options",
        "all_methods": "payment methods",
    }.get(str(category or ""), "payment options")


def _customer_payment_method_categories(
    rows: Sequence[Dict[str, Any]],
) -> List[str]:
    """Return a compact customer-facing grouping from active checkout rows.

    Exact method names remain available in ``active_methods_by_option`` for
    named-provider and eligibility questions.  This projection exists so a
    broad "how can I pay?" reply can stay readable without making the model
    reverse-engineer internal checkout labels on every turn.
    """

    normalized_rows = [row for row in rows if isinstance(row, dict)]
    searchable = [
        " ".join(
            str(row.get(key) or "").strip().casefold()
            for key in ("name", "label", "value", "description")
        )
        for row in normalized_rows
    ]
    values = {
        str(row.get("value") or "").strip().upper()
        for row in normalized_rows
    }
    combined = " ".join(searchable)
    grouped: List[str] = []

    if "gcash" in combined or "GCASH" in values:
        grouped.append("GCash")
    elif "e-wallet" in combined or "ewallet" in combined or "EWALLET" in values:
        grouped.append("e-wallets")

    has_credit_card = "credit card" in combined
    has_debit_card = "debit card" in combined
    if has_credit_card and has_debit_card:
        grouped.append("credit/debit cards")
    elif has_credit_card:
        grouped.append("credit cards")
    elif has_debit_card:
        grouped.append("debit cards")
    elif "CC" in values or " card" in f" {combined}":
        grouped.append("card payments")

    if any(
        truthy(row.get("is_installment"))
        or "installment" in searchable[index]
        for index, row in enumerate(normalized_rows)
    ):
        grouped.append("installment")

    if "bank transfer" in combined:
        grouped.append("bank transfer")
    elif "online banking" in combined:
        grouped.append("online banking")
    elif "direct debit" in combined:
        grouped.append("direct debit")
    elif "WEBPAY" in values:
        grouped.append("online payment")

    return grouped


def _fulfillment_context_from_payload(payload: Dict[str, Any]) -> str:
    for key in (
        "service_type",
        "fulfillment_path",
        "fulfillment",
        "transaction_type",
        "service_path",
        "order_type",
    ):
        value = str((payload or {}).get(key) or "").strip()
        if value:
            return value
    return ""


def _find_entry(entries: Sequence[FAQEntry], *, faq_id: str) -> Optional[FAQEntry]:
    if not faq_id:
        return None
    for entry in entries:
        if entry.faq_id == faq_id:
            return entry
    return None


def _rank_entries(question: str, entries: Sequence[FAQEntry]) -> List[tuple[float, FAQEntry, List[str]]]:
    text = _normalize_text(question)
    scored = []
    for entry in entries:
        score, matched_terms = _score_entry(text, entry)
        if score > 0:
            scored.append((score, entry, matched_terms))
    scored.sort(key=lambda item: (-item[0], item[1].faq_id))
    return scored


def _rank_faq_entries_hybrid(
    query: str,
    entries: Sequence[FAQEntry],
    *,
    memory_text: str = "",
    embedding_gateway: Optional[Any] = None,
    top_k: int = 3,
) -> List[tuple[float, FAQEntry, List[str], str]]:
    """Rank FAQ entries with lexical matching plus optional vector fallback."""

    latest_text = _normalize_text(query)
    memory = _normalize_text(memory_text)
    lexical: List[tuple[float, FAQEntry, List[str], str]] = []
    for entry in entries:
        score, matched_terms = _score_entry_for_contexts(
            latest_text=latest_text,
            memory_text=memory,
            entry=entry,
        )
        if score > 0:
            lexical.append((score, entry, matched_terms, "lexical"))
    lexical.sort(key=lambda item: (-item[0], item[1].domain, item[1].faq_id))
    if not _should_run_faq_vector(latest_text, lexical, embedding_gateway=embedding_gateway):
        return lexical[: max(1, int(top_k or 3))]

    vector_rows = _rank_faq_entries_by_vector(
        latest_text,
        entries,
        embedding_gateway=embedding_gateway,
        top_k=max(3, int(top_k or 3)),
    )
    if not vector_rows:
        return lexical[: max(1, int(top_k or 3))]

    by_id: Dict[str, tuple[float, FAQEntry, List[str], str]] = {}
    for score, entry, terms, matched_by in lexical:
        by_id[entry.faq_id] = (score, entry, terms, matched_by)
    for vector_score, entry, terms, matched_by in vector_rows:
        weighted = max(0.0, float(vector_score)) * 8.0
        current = by_id.get(entry.faq_id)
        if current:
            score = current[0] + weighted
            by_id[entry.faq_id] = (score, entry, _merge_terms(current[2], terms), "hybrid_vector")
        else:
            by_id[entry.faq_id] = (weighted, entry, terms, matched_by)
    combined = list(by_id.values())
    combined.sort(key=lambda item: (-item[0], item[1].domain, item[1].faq_id))
    return combined[: max(1, int(top_k or 3))]


def _filter_dominant_faq_domain(
    scored: Sequence[tuple[float, FAQEntry, List[str], str]],
) -> List[tuple[float, FAQEntry, List[str], str]]:
    """Keep strong FAQ routing hints from competing across domains."""

    rows = list(scored or [])
    if len(rows) < 2:
        return rows
    top_score, top_entry, _terms, _matched_by = rows[0]
    second_score, second_entry, _second_terms, _second_matched_by = rows[1]
    if top_entry.domain == second_entry.domain:
        return rows
    if float(top_score) >= 6.0 and float(top_score) - float(second_score) >= 2.0:
        return [row for row in rows if row[1].domain == top_entry.domain]
    return rows


def _should_run_faq_vector(
    latest_text: str,
    lexical: Sequence[tuple[float, FAQEntry, List[str], str]],
    *,
    embedding_gateway: Optional[Any],
) -> bool:
    if not _embedding_gateway_available(embedding_gateway):
        return False
    if not _looks_like_faq_question(latest_text):
        return False
    if not lexical:
        return True
    if lexical[0][0] < 4.0:
        return True
    if len(lexical) >= 2 and lexical[0][0] - lexical[1][0] < 1.0:
        return True
    return False


def _looks_like_faq_question(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    if "?" in str(text or ""):
        return True
    return any(
        token in normalized
        for token in [
            "ba",
            "pwede",
            "pede",
            "paano",
            "ano",
            "saan",
            "where",
            "how",
            "included",
            "include",
            "kasama",
            "covered",
            "warranty",
            "return",
            "exchange",
            "install",
            "branch",
            "location",
            "same day",
            "today",
            "promo",
            "discount",
            "order",
            "payment",
            "pay",
            "bayad",
            "reservation fee",
            "refund",
            "cancel",
        ]
    )


def _rank_faq_entries_by_vector(
    query: str,
    entries: Sequence[FAQEntry],
    *,
    embedding_gateway: Optional[Any],
    top_k: int,
) -> List[tuple[float, FAQEntry, List[str], str]]:
    if not _embedding_gateway_available(embedding_gateway):
        return []
    query_text = str(query or "").strip()
    if not query_text:
        return []
    cache_key = _faq_hint_cache_key(query_text, entries=entries)
    cached = _cache_get_faq_hint_rows(cache_key)
    if cached is not None:
        return cached[: max(1, int(top_k or 3))]
    embed = getattr(embedding_gateway, "embed", None)
    model = str(os.getenv("RAG_EMBEDDING_MODEL") or "gemini/text-embedding-004").strip()
    texts = [query_text, *[_faq_entry_embedding_text(entry) for entry in entries]]
    try:
        response = embed(
            texts=texts,
            model=model,
            metadata={"component": "runtime_v7_faq_hints", "task_type": "faq_hint_embedding"},
        )
    except TypeError:
        return []
    except Exception:
        return []
    vectors = _extract_embedding_vectors(response)
    if len(vectors) < len(texts):
        return []
    query_vector = vectors[0]
    rows: List[tuple[float, FAQEntry, List[str], str]] = []
    for entry, vector in zip(entries, vectors[1:]):
        score = _cosine(query_vector, vector)
        if score > 0:
            rows.append((score, entry, ["semantic FAQ match"], "vector"))
    rows.sort(key=lambda item: (-item[0], item[1].domain, item[1].faq_id))
    _cache_put_faq_hint_rows(cache_key, rows)
    return rows[: max(1, int(top_k or 3))]


def _faq_entry_embedding_text(entry: FAQEntry) -> str:
    return " ".join(
        part
        for part in [
            entry.domain,
            entry.title,
            entry.question,
            " ".join(entry.keywords or []),
        ]
        if part
    )


def _faq_hint_cache_key(query: str, *, entries: Sequence[FAQEntry]) -> str:
    digest_source = "|".join(f"{entry.domain}:{entry.faq_id}:{entry.question}" for entry in entries)
    digest = sha1(digest_source.encode("utf-8")).hexdigest()[:12]
    return sha1(f"{_normalize_text(query)}|{digest}".encode("utf-8")).hexdigest()


def _cache_get_faq_hint_rows(key: str) -> Optional[List[tuple[float, FAQEntry, List[str], str]]]:
    ttl = _faq_cache_ttl_s("RUNTIME_V7_FAQ_RETRIEVAL_CACHE_TTL_S")
    if ttl <= 0:
        return None
    cached = _FAQ_HINT_RETRIEVAL_CACHE.get(key)
    if not cached:
        return None
    expires_at, rows = cached
    if expires_at < time.time():
        _FAQ_HINT_RETRIEVAL_CACHE.pop(key, None)
        return None
    return list(rows)


def _cache_put_faq_hint_rows(key: str, rows: List[tuple[float, FAQEntry, List[str], str]]) -> None:
    ttl = _faq_cache_ttl_s("RUNTIME_V7_FAQ_RETRIEVAL_CACHE_TTL_S")
    if ttl <= 0:
        return
    if len(_FAQ_HINT_RETRIEVAL_CACHE) >= _faq_cache_max_entries():
        oldest_key = min(_FAQ_HINT_RETRIEVAL_CACHE.items(), key=lambda item: item[1][0])[0]
        _FAQ_HINT_RETRIEVAL_CACHE.pop(oldest_key, None)
    _FAQ_HINT_RETRIEVAL_CACHE[key] = (time.time() + ttl, list(rows))


def _score_entry(text: str, entry: FAQEntry) -> tuple[float, List[str]]:
    if not text:
        return 0.0, []
    matched_terms: List[str] = []
    normalized_question = _normalize_text(entry.question)
    if normalized_question and (normalized_question in text or text in normalized_question):
        return 10.0, [entry.question]
    for keyword in entry.keywords:
        normalized = _normalize_text(keyword)
        if _keyword_matches_text(normalized, text):
            matched_terms.append(keyword)
    if not matched_terms:
        question_terms = _content_terms(entry.question)
        text_terms = set(_content_terms(text))
        overlap = sorted(question_terms.intersection(text_terms))
        matched_terms = overlap[:3] if len(overlap) >= 2 else []
    if not matched_terms:
        return 0.0, []
    score = len(matched_terms)
    if len(str(matched_terms[0])) >= 10:
        score += 0.25
    return float(score), matched_terms


def _keyword_matches_text(normalized_keyword: str, text: str) -> bool:
    """Match short FAQ terms as tokens so substrings do not create false hints."""

    keyword = str(normalized_keyword or "").strip()
    if not keyword or not text:
        return False
    if len(keyword) <= 4 and re.fullmatch(r"[a-z0-9]+", keyword):
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None
    return keyword in text


def _score_entry_for_contexts(*, latest_text: str, memory_text: str, entry: FAQEntry) -> tuple[float, List[str]]:
    """Score latest-turn FAQ intent ahead of older memory continuity terms."""

    latest_score, latest_terms = _score_entry(latest_text, entry)
    memory_score, memory_terms = _score_entry(memory_text, entry)
    if latest_score <= 0 and memory_score <= 0:
        return 0.0, []
    matched_terms = _merge_terms(latest_terms, memory_terms)
    if latest_score > 0:
        return latest_score * 3.0 + memory_score * 0.25 + 0.5, matched_terms
    return memory_score * 0.25, matched_terms


def _merge_terms(*term_groups: Sequence[str]) -> List[str]:
    merged: List[str] = []
    for terms in term_groups:
        for term in terms or []:
            if term and term not in merged:
                merged.append(term)
    return merged


def _content_terms(text: str) -> set[str]:
    stopwords = {
        "what",
        "does",
        "where",
        "are",
        "can",
        "your",
        "the",
        "and",
        "for",
        "with",
        "po",
        "ba",
        "how",
        "should",
    }
    return {token for token in re.findall(r"[a-z0-9]+", _normalize_text(text)) if len(token) >= 4 and token not in stopwords}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _all_faq_entries() -> List[FAQEntry]:
    return [*product_faq_entries(), *service_faq_entries(), *order_faq_entries()]


def product_faq_entries() -> List[FAQEntry]:
    """Load answerable product FAQ metadata from the current Gulong RAG pool."""

    global _PRODUCT_FAQ_CACHE
    if _PRODUCT_FAQ_CACHE is not None:
        return list(_PRODUCT_FAQ_CACHE)
    entries: List[FAQEntry] = []
    for question, keywords in PRODUCT_FAQ_QUESTIONS.items():
        chunk = _rag_chunk_for_title(question)
        answer = _product_policy_answer_for_title(question) or (
            _answer_from_chunk(chunk) if chunk else ""
        )
        entries.append(
            FAQEntry(
                faq_id=_faq_id_for_question(question),
                domain="product",
                title=question,
                question=question,
                answer=answer,
                keywords=keywords,
            )
        )
    _PRODUCT_FAQ_CACHE = entries
    return list(entries)


def order_faq_entries() -> List[FAQEntry]:
    """Load answerable order/payment FAQ metadata from the current Gulong RAG pool."""

    global _ORDER_FAQ_CACHE
    if _ORDER_FAQ_CACHE is not None:
        return list(_ORDER_FAQ_CACHE)
    chunks = _order_rag_chunks()
    entries: List[FAQEntry] = []
    for question, keywords in ORDER_FAQ_QUESTIONS.items():
        answer = order_policy_answer_for_title(question) or _combined_answer_for_title(question, chunks)
        entries.append(
            FAQEntry(
                faq_id=_faq_id_for_question(question, domain="order"),
                domain="order",
                title=question,
                question=question,
                answer=answer,
                keywords=keywords,
            )
        )
    _ORDER_FAQ_CACHE = entries
    return list(entries)


def service_faq_entries() -> List[FAQEntry]:
    """Load answerable service/installation FAQ metadata from the current Gulong RAG pool."""

    global _SERVICE_FAQ_CACHE
    if _SERVICE_FAQ_CACHE is not None:
        return list(_SERVICE_FAQ_CACHE)
    chunks = _service_rag_chunks()
    entries: List[FAQEntry] = []
    for question, keywords in SERVICE_FAQ_QUESTIONS.items():
        answer = _service_policy_answer_for_title(question) or _combined_answer_for_title(question, chunks)
        entries.append(
            FAQEntry(
                faq_id=_faq_id_for_question(question, domain="service"),
                domain="service",
                title=question,
                question=question,
                answer=answer,
                keywords=keywords,
            )
        )
    _SERVICE_FAQ_CACHE = entries
    return list(entries)


def _service_policy_answer_for_title(title: str) -> str:
    """Return V7-owned service policy answers that are not in the static FAQ corpus yet."""

    normalized = _normalize_text(title)
    if normalized == _normalize_text("Do you offer nitrogen inflation?"):
        return (
            "Nitrogen inflation uses nitrogen gas instead of regular compressed air. It can help reduce pressure "
            "fluctuation and moisture inside the tire, but it does not make the tire puncture-proof, no-flat, or "
            "run-flat. It is an add-on service, so availability and pricing can depend on the installation partner "
            "or branch and should be checked with the selected/nearby partner when the customer's area or chosen "
            "branch is known."
        )
    return ""


def _product_policy_answer_for_title(title: str) -> str:
    """Return V7-owned product guidance absent from the static FAQ corpus."""

    if _normalize_text(title) == _normalize_text(
        "How do I read the DOT manufacturing date?"
    ):
        return (
            "Makikita ang DOT code sa tire sidewall. Yung huling apat na digits ang "
            "manufacturing date: first two digits ang production week at last two "
            "digits ang year. Halimbawa, 2525 means week 25 of 2025. Nag-iiba ang "
            "exact DOT code per tire at batch, kaya kailangang i-check ang actual "
            "tire; hindi ito dapat i-assume bago ma-inspect ang unit."
        )
    return ""


def _entry_for_title(title: str, entries: Sequence[FAQEntry]) -> Optional[FAQEntry]:
    wanted = _normalize_text(title)
    for entry in entries:
        if _normalize_text(entry.title) == wanted or _normalize_text(entry.question) == wanted:
            return entry
    return None


def _product_rag_chunks() -> tuple[List[Dict[str, Any]], Dict[str, Any], str]:
    try:
        from runtime.services.rag.index import load_rag_index

        index = load_rag_index("gulong")
    except Exception:
        index = None
    if not isinstance(index, dict):
        return [], {}, ""
    chunks = [chunk for chunk in index.get("chunks") or [] if isinstance(chunk, dict)]
    product_titles = {_normalize_text(question) for question in PRODUCT_FAQ_QUESTIONS}
    product_chunks: List[Dict[str, Any]] = []
    for chunk in chunks:
        title = str(chunk.get("title") or "").strip()
        source = str(chunk.get("source") or "").strip().lower()
        title_key = _normalize_text(title)
        if source == "faqs" and title_key in product_titles:
            product_chunks.append(chunk)
            continue
        if source == "file" and _is_product_doc_title(title):
            product_chunks.append(chunk)
    return product_chunks, dict(index.get("meta") or {}), str(index.get("version") or "")


def _order_rag_chunks() -> List[Dict[str, Any]]:
    return _faq_rag_chunks_for_titles(ORDER_FAQ_QUESTIONS)


def _service_rag_chunks() -> List[Dict[str, Any]]:
    return _faq_rag_chunks_for_titles(SERVICE_FAQ_QUESTIONS)


def _faq_rag_chunks_for_titles(question_map: Dict[str, Sequence[str]]) -> List[Dict[str, Any]]:
    try:
        from runtime.services.rag.index import load_rag_index

        index = load_rag_index("gulong")
    except Exception:
        index = None
    if not isinstance(index, dict):
        return []
    wanted_titles = {_normalize_text(question) for question in question_map}
    chunks: List[Dict[str, Any]] = []
    for chunk in index.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        if str(chunk.get("source") or "").strip().lower() != "faqs":
            continue
        if _normalize_text(chunk.get("title")) in wanted_titles:
            chunks.append(chunk)
    return chunks


def _combined_answer_for_title(title: str, chunks: Sequence[Dict[str, Any]]) -> str:
    wanted = _normalize_text(title)
    parts: List[str] = []
    for chunk in chunks:
        if _normalize_text(chunk.get("title")) != wanted:
            continue
        answer = _answer_from_chunk(chunk)
        if answer:
            parts.append(answer)
    text = "\n".join(parts)
    return text[:1200].strip()


def _is_product_doc_title(title: str) -> bool:
    lowered = str(title or "").strip().lower()
    return lowered == "gulong_guarantee.md" or lowered.startswith("warranty_")


def _rag_chunk_for_title(title: str) -> Optional[Dict[str, Any]]:
    wanted = _normalize_text(title)
    chunks, _meta, _version = _product_rag_chunks()
    for chunk in chunks:
        if _normalize_text(chunk.get("title")) == wanted:
            return chunk
    return None


def _direct_product_faq_payload(title: str) -> Dict[str, Any]:
    wanted = _normalize_text(title)
    chunks, meta, version = _product_rag_chunks()
    chunk = None
    for row in chunks:
        if _normalize_text(row.get("title")) == wanted:
            chunk = row
            break
    return {
        "chunks": ([{"score": 1.0, **chunk}] if chunk else []),
        "meta": meta,
        "version": version,
        "retrieval_method": "faq_id_direct_product_classified_rag_subset",
        "embedding_status": "skipped_faq_id",
        "cache_hit": False,
    }


def _rank_product_rag_chunks(
    query: str,
    *,
    preferred_title: str = "",
    top_k: int = 3,
    embedding_gateway: Optional[Any] = None,
) -> Dict[str, Any]:
    chunks, meta, version = _product_rag_chunks()
    cache_mode = "vector" if _embedding_gateway_available(embedding_gateway) else "lexical"
    cache_key = _faq_retrieval_cache_key(
        mode=cache_mode,
        query=query,
        preferred_title=preferred_title,
        top_k=top_k,
        version=version,
        meta=meta,
    )
    cached = _cache_get(_FAQ_RETRIEVAL_CACHE, cache_key, _faq_cache_ttl_s("RUNTIME_V7_FAQ_RETRIEVAL_CACHE_TTL_S"))
    if cached:
        cached["cache_hit"] = True
        return cached

    embedding = _query_embedding_vector(
        query,
        embedding_gateway=embedding_gateway,
        meta=meta,
        chunks=chunks,
        corpus_version=version,
    )
    if embedding.get("query_vector"):
        vector_payload = _rank_product_chunks_by_vector(
            chunks,
            query_vector=embedding["query_vector"],
            preferred_title=preferred_title,
            top_k=top_k,
        )
        if vector_payload:
            result = {
                "chunks": vector_payload,
                "meta": meta,
                "version": version,
                "retrieval_method": "vector_over_product_classified_rag_subset",
                "embedding_status": "used",
                "query_embedding_model": embedding.get("model"),
                "query_embedding_provider": embedding.get("provider"),
                "query_embedding_latency_ms": embedding.get("latency_ms"),
                "query_vector_dimension": embedding.get("dimension"),
                "cache_hit": False,
            }
            _cache_put(_FAQ_RETRIEVAL_CACHE, cache_key, result, _faq_cache_max_entries())
            return result

    lexical = _rank_product_chunks_by_lexical(chunks, query, preferred_title=preferred_title, top_k=top_k)
    payload = {
        "chunks": lexical,
        "meta": meta,
        "version": version,
        "retrieval_method": "lexical_over_product_classified_rag_subset",
        "embedding_status": embedding.get("status") or "not_requested",
        "cache_hit": False,
    }
    if embedding.get("error"):
        payload["embedding_error"] = embedding["error"]
    if embedding.get("model"):
        payload["query_embedding_model"] = embedding["model"]
    if embedding.get("dimension"):
        payload["query_vector_dimension"] = embedding["dimension"]
    if payload["embedding_status"] in {"not_configured", "not_requested"}:
        _cache_put(_FAQ_RETRIEVAL_CACHE, cache_key, payload, _faq_cache_max_entries())
    return payload


def _rank_product_chunks_by_lexical(
    chunks: Sequence[Dict[str, Any]],
    query: str,
    *,
    preferred_title: str = "",
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    query_text = _normalize_text(query)
    preferred = _normalize_text(preferred_title)
    scored: List[tuple[float, Dict[str, Any]]] = []
    for chunk in chunks:
        title = _normalize_text(chunk.get("title"))
        score = _chunk_score(query_text, chunk)
        if preferred and title == preferred:
            score = max(score, 10.0)
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("source") or ""), str(item[1].get("title") or "")))
    return [{"score": round(score, 4), **chunk} for score, chunk in scored[: max(1, int(top_k or 3))]]


def _rank_product_chunks_by_vector(
    chunks: Sequence[Dict[str, Any]],
    *,
    query_vector: Sequence[float],
    preferred_title: str = "",
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    preferred = _normalize_text(preferred_title)
    scored: List[tuple[float, Dict[str, Any]]] = []
    for chunk in chunks:
        vector = chunk.get("vector") if isinstance(chunk, dict) else None
        score = _cosine(query_vector, vector if isinstance(vector, list) else [])
        title = _normalize_text(chunk.get("title"))
        if preferred and title == preferred:
            score = max(score, 1.5)
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("source") or ""), str(item[1].get("title") or "")))
    return [{"score": round(score, 4), **chunk} for score, chunk in scored[: max(1, int(top_k or 3))]]


def _query_embedding_vector(
    query: str,
    *,
    embedding_gateway: Optional[Any],
    meta: Dict[str, Any],
    chunks: Sequence[Dict[str, Any]],
    corpus_version: str = "",
) -> Dict[str, Any]:
    if not embedding_gateway:
        return {"status": "not_configured"}
    embed = getattr(embedding_gateway, "embed", None)
    if not callable(embed):
        return {"status": "not_configured"}
    model = str(meta.get("embedding_model") or os.getenv("RAG_EMBEDDING_MODEL") or "").strip()
    if not model:
        return {"status": "missing_embedding_model"}
    query_text = str(query or "").strip()
    if not query_text:
        return {"status": "missing_query", "model": model}
    dimension = _first_vector_dimension(chunks)
    cache_key = _faq_embedding_cache_key(
        query=query_text,
        model=model,
        dimension=dimension,
        corpus_version=corpus_version,
        meta=meta,
    )
    cached = _cache_get(
        _FAQ_QUERY_EMBEDDING_CACHE,
        cache_key,
        _faq_cache_ttl_s("RUNTIME_V7_FAQ_QUERY_EMBEDDING_CACHE_TTL_S"),
    )
    if cached:
        cached["cache_hit"] = True
        return cached
    try:
        response = _call_embedding_gateway(
            embed,
            query_text=query_text,
            model=model,
            dimension=dimension,
        )
        vectors = _extract_embedding_vectors(response)
        vector = vectors[0] if vectors else []
        if not vector:
            return {"status": "empty_vector", "model": model}
        if dimension and len(vector) != dimension:
            return {
                "status": "dimension_mismatch",
                "model": model,
                "dimension": len(vector),
                "expected_dimension": dimension,
            }
        result = {
            "status": "used",
            "query_vector": vector,
            "model": _embedding_response_value(response, "model") or model,
            "provider": _embedding_response_value(response, "provider"),
            "latency_ms": _embedding_response_value(response, "latency_ms"),
            "dimension": len(vector),
            "cache_hit": False,
        }
        _cache_put(_FAQ_QUERY_EMBEDDING_CACHE, cache_key, result, _faq_cache_max_entries())
        return result
    except Exception as exc:
        return {"status": "error", "model": model, "error": f"{exc.__class__.__name__}: {exc}"}


def _call_embedding_gateway(embed: Any, *, query_text: str, model: str, dimension: int) -> Any:
    try:
        return embed(
            texts=[query_text],
            model=model,
            metadata={"component": "runtime_v7_product_faq", "task_type": "rag_query_embedding"},
            dimensions=dimension or None,
        )
    except TypeError:
        from runtime.shared.llm_types import LLMEmbeddingRequest

        provider = "litellm" if model.lower().startswith("gemini") else "openai"
        request = LLMEmbeddingRequest(
            request_id=str(uuid.uuid4()),
            texts=[query_text],
            model=model,
            metadata={"component": "runtime_v7_product_faq", "task_type": "rag_query_embedding"},
        )
        return embed(request, fallback_chain=[(provider, model)])


def _extract_embedding_vectors(response: Any) -> List[List[float]]:
    if isinstance(response, dict):
        raw_vectors = response.get("vectors")
        if raw_vectors:
            return [[float(value) for value in list(vector)] for vector in raw_vectors]
        data = response.get("data") or ((response.get("raw") or {}).get("data") if isinstance(response.get("raw"), dict) else None)
        if data:
            vectors: List[List[float]] = []
            for item in data:
                embedding = item.get("embedding") if isinstance(item, dict) else None
                if embedding is not None:
                    vectors.append([float(value) for value in list(embedding)])
            return vectors
    raw_vectors = getattr(response, "vectors", None)
    if raw_vectors:
        return [[float(value) for value in list(vector)] for vector in raw_vectors]
    return []


def _embedding_response_value(response: Any, key: str) -> Any:
    if isinstance(response, dict):
        return response.get(key)
    return getattr(response, key, None)


def _first_vector_dimension(chunks: Sequence[Dict[str, Any]]) -> int:
    for chunk in chunks:
        vector = chunk.get("vector") if isinstance(chunk, dict) else None
        if isinstance(vector, list) and vector:
            return len(vector)
    return 0


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    norm_a = math.sqrt(sum(float(x) * float(x) for x in a))
    norm_b = math.sqrt(sum(float(y) * float(y) for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _matched_by_from_retrieval(payload: Dict[str, Any]) -> str:
    method = payload.get("retrieval_method")
    if method == "vector_over_product_classified_rag_subset":
        return "rag_vector_match"
    if method == "faq_id_direct_product_classified_rag_subset":
        return "faq_id"
    return "rag_lexical_match"


def _chunk_score(query_text: str, chunk: Dict[str, Any]) -> float:
    title = _normalize_text(chunk.get("title"))
    text = _normalize_text(chunk.get("text"))
    query_terms = _content_terms(query_text)
    if not query_terms:
        return 0.0
    title_terms = _content_terms(title)
    text_terms = _content_terms(text)
    overlap = len(query_terms.intersection(text_terms))
    title_overlap = len(query_terms.intersection(title_terms))
    score = overlap / float(max(1, len(query_terms)))
    score += title_overlap * 0.75
    if title and (title in query_text or query_text in title):
        score += 2.0
    return score


def _answer_from_chunk(chunk: Optional[Dict[str, Any]]) -> str:
    if not isinstance(chunk, dict):
        return ""
    text = str(chunk.get("text") or "").strip()
    if "\nA:" in text:
        text = text.split("\nA:", 1)[1].strip()
    return text[:1200].strip()


def _compact_retrieval_payload(
    payload: Dict[str, Any],
    *,
    selected_chunk: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    selected = selected_chunk if isinstance(selected_chunk, dict) else {}
    return {
        "corpus_version": payload.get("version") or "",
        "faq_version": meta.get("faq_version"),
        "embedding_model": meta.get("embedding_model"),
        "retrieval_method": payload.get("retrieval_method"),
        "embedding_status": payload.get("embedding_status"),
        "query_embedding_model": payload.get("query_embedding_model"),
        "query_embedding_provider": payload.get("query_embedding_provider"),
        "query_embedding_latency_ms": payload.get("query_embedding_latency_ms"),
        "query_vector_dimension": payload.get("query_vector_dimension"),
        "cache_hit": payload.get("cache_hit"),
        "selected_doc_id": selected.get("doc_id"),
        "selected_chunk_id": selected.get("chunk_id"),
        "selected_source": selected.get("source"),
        "selected_title": selected.get("title"),
        "candidate_count": len(payload.get("chunks") or []),
    }


def _embedding_gateway_available(embedding_gateway: Optional[Any]) -> bool:
    return callable(getattr(embedding_gateway, "embed", None))


def _faq_cache_ttl_s(env_name: str) -> int:
    try:
        return max(0, int(os.getenv(env_name, "3600") or "3600"))
    except Exception:
        return 3600


def _faq_cache_max_entries() -> int:
    try:
        return max(1, int(os.getenv("RUNTIME_V7_FAQ_CACHE_MAX_ENTRIES", "256") or "256"))
    except Exception:
        return 256


def _cache_get(cache: Dict[str, tuple[float, Dict[str, Any]]], key: str, ttl_s: int) -> Optional[Dict[str, Any]]:
    if ttl_s <= 0:
        return None
    row = cache.get(key)
    if not row:
        return None
    saved_at, payload = row
    if time.time() - saved_at > ttl_s:
        cache.pop(key, None)
        return None
    return deepcopy(payload)


def _cache_put(cache: Dict[str, tuple[float, Dict[str, Any]]], key: str, payload: Dict[str, Any], max_entries: int) -> None:
    if max_entries <= 0:
        return
    if len(cache) >= max_entries:
        oldest_key = min(cache.items(), key=lambda item: item[1][0])[0]
        cache.pop(oldest_key, None)
    cache[key] = (time.time(), deepcopy(payload))


def _faq_retrieval_cache_key(
    *,
    mode: str,
    query: str,
    preferred_title: str,
    top_k: int,
    version: str,
    meta: Dict[str, Any],
) -> str:
    return _cache_key(
        "product_faq_retrieval",
        mode,
        _normalize_text(query),
        _normalize_text(preferred_title),
        int(top_k or 3),
        version,
        meta.get("faq_version"),
        meta.get("embedding_model"),
    )


def _faq_embedding_cache_key(
    *,
    query: str,
    model: str,
    dimension: int,
    corpus_version: str,
    meta: Dict[str, Any],
) -> str:
    return _cache_key(
        "product_faq_query_embedding",
        _normalize_text(query),
        model,
        int(dimension or 0),
        corpus_version,
        meta.get("faq_version"),
    )


def _cache_key(*parts: Any) -> str:
    text = "\x1f".join(str(part or "") for part in parts)
    return sha1(text.encode("utf-8")).hexdigest()


def _looks_like_order_domain_question(text: str) -> bool:
    lowered = _normalize_text(text)
    return any(
        token in lowered
        for token in [
            "how do i pay",
            "how to pay",
            "how to order",
            "paano payment",
            "paano magbayad",
            "paano umorder",
            "paano order",
            "payment method",
            "payment option",
            "gcash",
            "credit card",
            "reservation fee",
            "downpayment",
            "deposit",
            "pay after service",
            "pay now",
            "checkout",
            "order process",
            "cancel order",
            "cancel appointment",
            "cancel booking",
            "refund",
            "installment",
            "reschedule",
            "missed appointment",
            "missed schedule",
            "late appointment",
            "delivery fee",
            "shipping fee",
            "how long delivery",
            "same day delivery",
            "delivery status",
            "track delivery",
            "official receipt",
            "official resibo",
            "sales invoice",
            "company invoice",
            "formal quotation",
            "or after installation",
            "or after purchase",
            "resibo",
        ]
    )


def _looks_like_run_flat_feature_question(text: str) -> bool:
    """Return true when the query asks about run-flat/no-flat tire technology."""

    lowered = _normalize_text(text)
    if not lowered:
        return False
    return any(
        token in lowered
        for token in [
            "run flat",
            "runflat",
            "no flat",
            "noflat",
            "flat tire type",
        ]
    )


def _looks_like_nitrogen_addon_question(text: str) -> bool:
    """Return true when the query asks about nitrogen inflation/add-on service."""

    lowered = _normalize_text(text)
    if not lowered:
        return False
    return any(
        token in lowered
        for token in [
            "nitrogen",
            "nitro",
            "nitrogen air",
            "nitrogen inflation",
        ]
    )


def _product_concept_faq_answer(*, question: str, concept_question: str, answer: str) -> Dict[str, Any]:
    """Return a V7-owned product concept answer without claiming SKU-specific facts."""

    return {
        "status": "ok",
        "domain": "product",
        "faq_id": _faq_id_for_question(concept_question),
        "title": concept_question,
        "question": concept_question,
        "answer": answer,
        "matched_by": "runtime_v7_product_concept_policy",
        "source": "runtime_v7_product_faq_rag_subset",
        "generated_at": _utc_now_iso(),
        "ttl_seconds": 86400,
    }


def _product_faq_no_match(*, question: str, reason: str) -> Dict[str, Any]:
    return {
        "status": "no_match",
        "domain": "product",
        "question": question,
        "answer": "",
        "reason": reason,
        "source": "runtime_v7_product_faq_rag_subset",
        "generated_at": _utc_now_iso(),
        "ttl_seconds": 86400,
    }


def faq_public_catalog() -> Dict[str, List[Dict[str, Any]]]:
    """Return answer-free FAQ metadata for diagnostics/tests."""

    by_domain: Dict[str, List[Dict[str, Any]]] = {"product": [], "service": [], "order": []}
    for entry in _all_faq_entries():
        by_domain.setdefault(entry.domain, []).append(
            {
                "faq_id": entry.faq_id,
                "domain": entry.domain,
                "title": entry.title,
                "question": entry.question,
                "suggested_tool": entry.suggested_tool,
                "keywords": list(entry.keywords),
            }
        )
    return deepcopy(by_domain)
