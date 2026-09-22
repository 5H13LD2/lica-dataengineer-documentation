"""Image evidence intake for the Runtime V7 product/service/order slice.

This module is a narrow boundary for customer-provided images and screenshots.
It detects image URLs, optionally asks a vision/OCR model to extract visible
text, and converts the result into provisional evidence refs plus advisory
background-signal candidates. It does not mutate slots and it does not turn OCR
output into trusted business facts.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Sequence
from urllib.parse import parse_qs, unquote, urlparse

from pydantic import BaseModel, Field, ValidationError, field_validator

from runtime_v7.llm_gateway import RuntimeV7ProviderCallLimitExceeded


IMAGE_EVIDENCE_SYSTEM_PROMPT = """You read customer-provided Gulong.PH images and screenshots.

Return strict JSON only:
{
  "type": "tire|car|website_product_card|product_page|conversation_screenshot|order_information|payment_proof|order_confirmation|other",
  "source_origin": "gulong_ph|other_merchant|unknown",
  "gulong_surface": "product_card|product_page|cart|checkout|order_page|order_email|payment_page|marketing_asset|other|null",
  "source_markers": ["..."],
  "tire_sizes": ["..."],
  "car_make": string|null,
  "car_model": string|null,
  "tire_brand": string|null,
  "tire_model": string|null,
  "product_title": string|null,
  "product_url": string|null,
  "service_location": string|null,
  "installation_partner": string|null,
  "service_type": string|null,
  "schedule_text": string|null,
  "branch_addons": ["..."],
  "visible_messages": ["..."],
  "human_agent_messages": ["..."],
  "promo_terms": ["..."],
  "discount_text": string|null,
  "timestamp_text": string|null,
  "order_id": string|null,
  "customer_name": string|null,
  "amount": string|null,
  "currency": string|null,
  "reference_no": string|null,
  "invoice_no": string|null,
  "payment_method": string|null,
  "paid_at": string|null,
  "merchant": string|null,
  "evidence_text": string|null,
  "notes": string|null,
  "confidence": number
}

Rules:
- Return compact JSON only. Do not reason step-by-step or explain uncertainty.
- Extract visible OCR/text only. Do not infer prices, payments, orders, service availability, or tire sizes that are not visible.
- If a tire sidewall size is readable, put every visible size in tire_sizes and include the exact visible text in evidence_text.
- Normalize metric tire sizes to 185/60R15 style. Keep commercial and flotation sizes if visible.
- Use type tire for sidewall photos, car for vehicle photos, website_product_card or product_page for product screenshots, conversation_screenshot for screenshots of chat/conversation snippets, payment_proof for receipts, and order_information/order_confirmation for order screenshots.
- Set source_origin to gulong_ph only when the image itself visibly shows Gulong.ph ownership, such as the gulong.ph logo/domain, a Gulong PH email sender, or a clearly branded Gulong order/checkout surface. Customer-message context is not enough.
- Set source_origin to other_merchant for a clearly visible different merchant, otherwise unknown.
- When source_origin is gulong_ph, classify gulong_surface from what is visibly shown. Distinguish product cards/pages, cart, checkout/payment selection, completed order pages, Gulong order emails, payment pages, and Gulong marketing assets.
- Put only short visible ownership markers in source_markers, such as "gulong.ph logo", "Gulong PH email sender", or "gulong.ph domain". Do not invent a domain or sender.
- For website product cards/pages, prioritize only visible product title, tire size, brand/model, customer-facing price/promo/payment/warranty/free-service text, and product URL if visible. Do not transcribe navigation, buttons, or page chrome unless it supports an extracted field.
- For conversation screenshots, preserve visible sender labels and short message snippets in visible_messages. If a visible sender is staff/page/admin/human agent, put that snippet in human_agent_messages too.
- For service or human-agent screenshots, capture visible branch/location,
  installation partner, requested service, schedule/date/time wording, and add-on
  service names when visible. Do not infer service availability or confirmed
  booking status from the screenshot alone.
- For payment proof screenshots, capture only visible order/invoice id, customer
  name, amount/currency, reference number, payment method, paid-at timestamp,
  merchant, and concise evidence text. Do not mark payment as verified or paid.
- Capture visible promo or discount wording in promo_terms or discount_text. Do not infer off-screen promos.
- Keep evidence_text concise. Include only the key visible OCR text needed to support extracted fields.
- Keep lists short: tire_sizes max 4, branch_addons max 5, visible_messages max 8, human_agent_messages max 5, promo_terms max 5.
- Leave fields null or empty when not clearly visible.
- confidence is 0.0 to 1.0 and should be high only when the key field is clearly readable.
- Output JSON only, with no prose or markdown.
"""


class ImageEvidenceExtractionModelClient(Protocol):
    """Model boundary for image OCR/vision extraction."""

    def extract_image_evidence(
        self,
        *,
        image_url: str,
        system_prompt: str,
        user_prompt: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return the raw model response for one image URL."""

        ...


class ImageEvidenceExtractionResponseModel(BaseModel):
    """Structured image OCR/vision response expected from the model."""

    type: Optional[str] = "other"
    source_origin: str = "unknown"
    gulong_surface: Optional[str] = None
    source_markers: List[str] = Field(default_factory=list)
    tire_sizes: List[str] = Field(default_factory=list)
    car_make: Optional[str] = None
    car_model: Optional[str] = None
    tire_brand: Optional[str] = None
    tire_model: Optional[str] = None
    product_title: Optional[str] = None
    product_url: Optional[str] = None
    service_location: Optional[str] = None
    installation_partner: Optional[str] = None
    service_type: Optional[str] = None
    schedule_text: Optional[str] = None
    branch_addons: List[str] = Field(default_factory=list)
    visible_messages: List[str] = Field(default_factory=list)
    human_agent_messages: List[str] = Field(default_factory=list)
    promo_terms: List[str] = Field(default_factory=list)
    discount_text: Optional[str] = None
    timestamp_text: Optional[str] = None
    order_id: Optional[str] = None
    customer_name: Optional[str] = None
    amount: Optional[str] = None
    currency: Optional[str] = None
    reference_no: Optional[str] = None
    invoice_no: Optional[str] = None
    payment_method: Optional[str] = None
    paid_at: Optional[str] = None
    merchant: Optional[str] = None
    evidence_text: Optional[str] = None
    notes: Optional[str] = None
    confidence: float = 0.0

    @field_validator("type")
    @classmethod
    def _normalize_type(cls, value: str) -> str:
        normalized = str(value or "other").strip().lower().replace(" ", "_")
        aliases = {
            "chat_screenshot": "conversation_screenshot",
            "conversation_snippet": "conversation_screenshot",
            "message_screenshot": "conversation_screenshot",
            "product_card": "website_product_card",
            "order_info": "order_information",
            "receipt": "payment_proof",
        }
        normalized = aliases.get(normalized, normalized)
        allowed = {
            "tire",
            "car",
            "website_product_card",
            "product_page",
            "conversation_screenshot",
            "order_information",
            "payment_proof",
            "order_confirmation",
            "other",
        }
        return normalized if normalized in allowed else "other"

    @field_validator("source_origin")
    @classmethod
    def _normalize_source_origin(cls, value: str) -> str:
        normalized = str(value or "unknown").strip().lower().replace(" ", "_")
        aliases = {
            "gulong": "gulong_ph",
            "gulong.ph": "gulong_ph",
            "gulongph": "gulong_ph",
            "external": "other_merchant",
            "other": "other_merchant",
        }
        normalized = aliases.get(normalized, normalized)
        return normalized if normalized in {"gulong_ph", "other_merchant", "unknown"} else "unknown"

    @field_validator("gulong_surface")
    @classmethod
    def _normalize_gulong_surface(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value or "").strip().lower().replace(" ", "_")
        aliases = {
            "add_to_cart": "cart",
            "shopping_cart": "cart",
            "checkout_page": "checkout",
            "order_confirmation_page": "order_page",
            "confirmation_email": "order_email",
            "order_confirmation_email": "order_email",
            "promo_asset": "marketing_asset",
        }
        normalized = aliases.get(normalized, normalized)
        allowed = {
            "product_card",
            "product_page",
            "cart",
            "checkout",
            "order_page",
            "order_email",
            "payment_page",
            "marketing_asset",
            "other",
        }
        return normalized if normalized in allowed else None

    @field_validator("tire_sizes")
    @classmethod
    def _normalize_sizes(cls, values: Sequence[str]) -> List[str]:
        normalized: List[str] = []
        for value in values or []:
            size = normalize_visible_tire_size(value)
            if size and size not in normalized:
                normalized.append(size)
        return normalized[:4]

    @field_validator(
        "branch_addons",
        "visible_messages",
        "human_agent_messages",
        "promo_terms",
        "source_markers",
    )
    @classmethod
    def _compact_string_lists(cls, values: Sequence[str], info: Any) -> List[str]:
        limits = {
            "branch_addons": 5,
            "visible_messages": 8,
            "human_agent_messages": 5,
            "promo_terms": 5,
            "source_markers": 5,
        }
        field_name = str(getattr(info, "field_name", "") or "")
        limit = limits.get(field_name, 5)
        compacted: List[str] = []
        for value in values or []:
            cleaned = _compact_extracted_text(value, max_chars=220)
            if cleaned and cleaned not in compacted:
                compacted.append(cleaned)
            if len(compacted) >= limit:
                break
        return compacted

    @field_validator(
        "tire_brand",
        "tire_model",
        "product_title",
        "product_url",
        "service_location",
        "installation_partner",
        "service_type",
        "schedule_text",
        "discount_text",
        "timestamp_text",
        "order_id",
        "customer_name",
        "amount",
        "currency",
        "reference_no",
        "invoice_no",
        "payment_method",
        "paid_at",
        "merchant",
        "evidence_text",
        "notes",
    )
    @classmethod
    def _compact_string_fields(cls, value: Optional[str], info: Any) -> Optional[str]:
        if value is None:
            return None
        field_name = str(getattr(info, "field_name", "") or "")
        max_chars = 420 if field_name == "evidence_text" else 220
        cleaned = _compact_extracted_text(value, max_chars=max_chars)
        return cleaned or None


class RuntimeV7ImageEvidenceModelClient:
    """LiteLLM/Gemini image extractor through the Runtime V7 gateway."""

    def __init__(
        self,
        *,
        model: str = "gemini/gemini-2.5-flash",
        temperature: float = 0.0,
        max_tokens: int = 2500,
        timeout_s: float = 20.0,
        metadata: Optional[Dict[str, Any]] = None,
        provider_call_guard: Optional[Any] = None,
    ) -> None:
        from runtime_v7.llm_gateway import RuntimeV7LLMGateway, RuntimeV7LLMGatewayConfig

        self.metadata = dict(metadata or {})
        self.gateway = RuntimeV7LLMGateway(
            config=RuntimeV7LLMGatewayConfig(
                model=model,
                api_key_env="GEMINI_API_KEY",
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
                enable_context_cache=False,
                provider_call_guard=provider_call_guard,
            )
        )

    def extract_image_evidence(
        self,
        *,
        image_url: str,
        system_prompt: str,
        user_prompt: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        merged_metadata = dict(self.metadata)
        merged_metadata.update(metadata or {})
        return self.gateway.complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            tools=[],
            metadata=merged_metadata,
            response_format=ImageEvidenceExtractionResponseModel,
        )


@dataclass
class ImageEvidenceExtractor:
    """Extract provisional evidence refs and advisory candidates from images."""

    model_client: Optional[ImageEvidenceExtractionModelClient] = None
    min_confidence_for_candidates: float = 0.7
    retry_attempts: int = 2

    def extract(self, image_url: str, *, image_context: str = "", metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Extract one image URL into an untrusted evidence ref."""

        cleaned_url = _normalize_image_url(image_url)
        evidence_ref = image_evidence_ref(cleaned_url)
        base = {
            "evidence_ref": evidence_ref,
            "source": "customer_image",
            "media_type": "image",
            "image_url": cleaned_url,
            "safe_for_action": False,
            "requires_validation": True,
        }
        if not cleaned_url:
            return {
                **base,
                "status": "invalid_image_url",
                "summary": "image evidence URL was empty or invalid",
                "extracted_fields": [],
            }
        if self.model_client is None:
            return {
                **base,
                "status": "detected_unprocessed",
                "summary": "customer sent an image URL; OCR/vision extraction was not configured",
                "extracted_fields": [],
            }

        user_prompt = build_image_evidence_user_prompt(image_context=image_context)
        response: Dict[str, Any] = {}
        parsed: Optional[ImageEvidenceExtractionResponseModel] = None
        retry_errors: List[str] = []
        total_attempts = max(1, 1 + int(self.retry_attempts or 0))
        for attempt in range(1, total_attempts + 1):
            try:
                response = self.model_client.extract_image_evidence(
                    image_url=cleaned_url,
                    system_prompt=IMAGE_EVIDENCE_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    metadata={
                        "component": "runtime_v7_image_evidence",
                        "evidence_ref": evidence_ref,
                        "attempt": attempt,
                        "max_attempts": total_attempts,
                        **dict(metadata or {}),
                    },
                )
                parsed = parse_image_evidence_response(response)
                if parsed is not None:
                    break
                retry_errors.append(f"attempt_{attempt}: invalid_image_evidence_json")
            except RuntimeV7ProviderCallLimitExceeded:
                # The tester guard must terminate the request rather than be
                # treated as a recoverable OCR/vision extraction failure.
                raise
            except Exception as exc:
                retry_errors.append(f"attempt_{attempt}: {exc.__class__.__name__}: {exc}")
        if parsed is None:
            return {
                **base,
                "status": "extraction_failed",
                "summary": "image evidence was detected but OCR/vision extraction did not return usable JSON",
                "extracted_fields": [],
                "model_attempts": total_attempts,
                "model_retry_errors": retry_errors,
                "model_response": _compact_model_response(response),
            }

        analysis = _model_dump(parsed)
        extracted_fields = image_extracted_fields(analysis)
        status = "extracted_unvalidated" if extracted_fields else "no_relevant_text_found"
        trusted_for_context = (
            str(analysis.get("type") or "") == "conversation_screenshot"
            and bool(analysis.get("human_agent_messages") or [])
        )
        return {
            **base,
            "status": status,
            "summary": image_evidence_summary(analysis),
            "image_type": analysis.get("type") or "other",
            "trusted_for_context": trusted_for_context,
            "trust_boundary": "customer_image_ocr_context_only" if trusted_for_context else "customer_image_unvalidated",
            "confidence": analysis.get("confidence"),
            "extracted_fields": extracted_fields,
            "analysis": analysis,
            "model_response": _compact_model_response(response),
        }


def build_image_evidence_context(
    *,
    current_user_message: str = "",
    image_urls: Optional[Sequence[str]] = None,
    extractor: Optional[ImageEvidenceExtractor] = None,
    metadata: Optional[Dict[str, Any]] = None,
    max_images: int = 3,
) -> Dict[str, Any]:
    """Detect/process image URLs and return refs plus advisory candidates."""

    urls = _unique([*(image_urls or []), *extract_image_urls(current_user_message)])
    selected_urls = urls[: max(1, int(max_images or 3))]
    evidence_extractor = extractor or ImageEvidenceExtractor()
    refs = [
        evidence_extractor.extract(
            url,
            image_context=current_user_message,
            metadata={**dict(metadata or {}), "image_index": index + 1},
        )
        for index, url in enumerate(selected_urls)
    ]
    return {
        "image_urls": selected_urls,
        "external_evidence_refs": refs,
        "background_signal_candidates": image_evidence_refs_to_signal_candidates(
            refs,
            min_confidence=evidence_extractor.min_confidence_for_candidates,
        ),
    }


def build_image_evidence_user_prompt(*, image_context: str = "") -> str:
    """Build a compact prompt for the vision/OCR model."""

    context = str(image_context or "").strip()
    return "\n".join(
        [
            "Extract visible Gulong.PH product, service, order, or payment information from this customer image.",
            "Use the surrounding customer message only as context, not as OCR truth.",
            f"Customer message: {context or '(none)'}",
            "Return JSON only.",
        ]
    )


def extract_image_urls(text: str) -> List[str]:
    """Extract likely image URLs from customer text, including Facebook redirects."""

    urls: List[str] = []
    for match in re.finditer(r"(?:https?://|data:image/)[^\s<>\"']+", str(text or ""), flags=re.IGNORECASE):
        url = _normalize_image_url(match.group(0))
        if url and _is_likely_image_url(url, text):
            urls.append(url)
    return _unique(urls)


def image_evidence_refs_to_signal_candidates(
    refs: Sequence[Dict[str, Any]],
    *,
    min_confidence: float = 0.7,
) -> List[Dict[str, Any]]:
    """Convert image evidence refs to advisory background-signal candidates."""

    candidates: List[Dict[str, Any]] = []
    for ref in refs or []:
        analysis = ref.get("analysis") if isinstance(ref, dict) else None
        if not isinstance(analysis, dict):
            continue
        confidence = _float_or_zero(analysis.get("confidence"))
        if confidence < min_confidence:
            continue
        evidence_ref = str(ref.get("evidence_ref") or "")
        image_type = str(analysis.get("type") or "other")
        evidence_text = str(analysis.get("evidence_text") or analysis.get("notes") or "")[:160]
        metadata = {
            "evidence_ref": evidence_ref,
            "image_type": image_type,
            "source_origin": str(analysis.get("source_origin") or "unknown"),
            "gulong_surface": str(analysis.get("gulong_surface") or ""),
            "source_markers": list(analysis.get("source_markers") or [])[:5],
            "safe_for_action": False,
            "requires_validation": True,
        }
        source_origin = str(analysis.get("source_origin") or "unknown").strip().lower()
        gulong_surface = str(analysis.get("gulong_surface") or "").strip().lower()
        if source_origin == "gulong_ph" and gulong_surface and gulong_surface != "marketing_asset":
            candidates.append(
                _candidate(
                    "website_inquiry_evidence",
                    f"{evidence_ref}:{gulong_surface}" if evidence_ref else gulong_surface,
                    confidence=_confidence_label(confidence),
                    status_hint="gulong_owned_image_routing_evidence",
                    evidence=evidence_text,
                    metadata=metadata,
                )
            )
        product_evidence_value = _external_product_evidence_value(analysis, evidence_ref=evidence_ref)
        if product_evidence_value:
            candidates.append(
                _candidate(
                    "external_product_evidence",
                    product_evidence_value,
                    confidence=_confidence_label(confidence),
                    status_hint="external_product_evidence_needs_validation",
                    evidence=evidence_text,
                    metadata=metadata,
                )
            )

        tire_sizes = [size for size in (analysis.get("tire_sizes") or []) if str(size or "").strip()]
        if tire_sizes:
            candidates.append(
                _candidate(
                    "tire_size",
                    ", ".join(tire_sizes),
                    confidence=_confidence_label(confidence),
                    status_hint="external_image_ocr_unvalidated",
                    evidence=evidence_text,
                    metadata=metadata,
                )
            )

        make = _clean_field(analysis.get("car_make"))
        model = _clean_field(analysis.get("car_model"))
        if make or model:
            candidates.append(
                _candidate(
                    "car_make_model",
                    " ".join(part for part in [make, model] if part),
                    confidence=_confidence_label(confidence),
                    status_hint="external_image_vision_unvalidated",
                    evidence=evidence_text,
                    metadata=metadata,
                )
            )

        if image_type in {"website_product_card", "product_page", "conversation_screenshot"}:
            brand = _clean_field(analysis.get("tire_brand"))
            product_title = _clean_field(analysis.get("product_title")) or _clean_field(analysis.get("tire_model"))
            brand_status = (
                "external_conversation_screenshot_unvalidated"
                if image_type == "conversation_screenshot"
                else "external_product_screenshot_unvalidated"
            )
            product_status = (
                "external_conversation_screenshot_needs_validation"
                if image_type == "conversation_screenshot"
                else "external_product_screenshot_needs_validation"
            )
            if brand:
                candidates.append(
                    _candidate(
                        "preferred_brands",
                        [brand],
                        confidence=_confidence_label(confidence),
                        status_hint=brand_status,
                        evidence=evidence_text,
                        metadata=metadata,
                    )
                )
            if product_title:
                candidates.append(
                    _candidate(
                        "specific_sku_model",
                        product_title,
                        confidence=_confidence_label(confidence),
                        status_hint=product_status,
                        evidence=evidence_text,
                        metadata=metadata,
                    )
                )

        if image_type == "payment_proof":
            candidates.append(
                _candidate(
                    "payment_proof_evidence",
                    str(ref.get("evidence_ref") or "").strip(),
                    confidence=_confidence_label(confidence),
                    status_hint="external_payment_screenshot_unvalidated",
                    evidence=evidence_text,
                    metadata=metadata,
                )
            )
            if _clean_field(analysis.get("payment_method")):
                candidates.append(
                    _candidate(
                        "payment_method",
                        _clean_field(analysis.get("payment_method")),
                        confidence=_confidence_label(confidence),
                        status_hint="external_payment_screenshot_unvalidated",
                        evidence=evidence_text,
                        metadata=metadata,
                    )
                )

        service_location = _clean_field(analysis.get("service_location"))
        if service_location:
            candidates.append(
                _candidate(
                    "location",
                    service_location,
                    confidence=_confidence_label(confidence),
                    status_hint="external_service_screenshot_unvalidated",
                    evidence=evidence_text,
                    metadata=metadata,
                )
            )

        installation_partner = _clean_field(analysis.get("installation_partner"))
        if installation_partner:
            candidates.append(
                _candidate(
                    "selected_installation_partner",
                    installation_partner,
                    confidence=_confidence_label(confidence),
                    status_hint="external_service_screenshot_unvalidated",
                    evidence=evidence_text,
                    metadata=metadata,
                )
            )

        service_type = _clean_field(analysis.get("service_type"))
        if service_type:
            candidates.append(
                _candidate(
                    "service_type",
                    service_type,
                    confidence=_confidence_label(confidence),
                    status_hint="external_service_screenshot_unvalidated",
                    evidence=evidence_text,
                    metadata=metadata,
                )
            )

        schedule_text = _clean_field(analysis.get("schedule_text"))
        if schedule_text:
            candidates.append(
                _candidate(
                    "chosen_schedule_slot",
                    schedule_text,
                    confidence=_confidence_label(confidence),
                    status_hint="external_service_screenshot_unvalidated",
                    evidence=evidence_text,
                    metadata=metadata,
                )
            )

        branch_addons = [str(item or "").strip() for item in analysis.get("branch_addons") or [] if str(item or "").strip()]
        if branch_addons:
            candidates.append(
                _candidate(
                    "branch_addons",
                    branch_addons,
                    confidence=_confidence_label(confidence),
                    status_hint="external_service_screenshot_unvalidated",
                    evidence=evidence_text,
                    metadata=metadata,
                )
            )
    return candidates


def _external_product_evidence_value(analysis: Dict[str, Any], *, evidence_ref: str) -> str:
    """Return a compact product-evidence marker that can expose product tools."""

    image_type = str(analysis.get("type") or "other").strip().lower()
    productish_types = {"tire", "website_product_card", "product_page", "conversation_screenshot"}
    fields: List[str] = []
    for key in ["product_title", "tire_brand", "tire_model", "product_url", "discount_text"]:
        value = _clean_field(analysis.get(key))
        if value:
            fields.append(f"{key}={value[:70]}")
    tire_sizes = [str(size or "").strip() for size in analysis.get("tire_sizes") or [] if str(size or "").strip()]
    if tire_sizes:
        fields.append("tire_size=" + ", ".join(tire_sizes[:3]))
    promo_terms = [str(term or "").strip() for term in analysis.get("promo_terms") or [] if str(term or "").strip()]
    if promo_terms:
        fields.append("promo_terms=" + "; ".join(promo_terms[:2])[:90])
    if not fields and image_type not in productish_types:
        return ""
    if not fields and image_type == "conversation_screenshot":
        messages = [str(msg or "").strip() for msg in analysis.get("human_agent_messages") or [] if str(msg or "").strip()]
        if messages and any(_looks_productish_text(message) for message in messages):
            fields.append("conversation_product_context=" + messages[0][:90])
    if not fields and image_type not in {"tire", "website_product_card", "product_page"}:
        return ""
    details = "; ".join(fields[:5]) if fields else image_type
    prefix = f"{evidence_ref}: " if evidence_ref else ""
    return (prefix + details)[:160]


def _looks_productish_text(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        token in lowered
        for token in [
            "tire",
            "gulong",
            "brand",
            "promo",
            "discount",
            "price",
            "stock",
            "available",
            "warranty",
            "dot",
            "175/",
            "185/",
            "195/",
            "205/",
            "215/",
            "225/",
            "r14",
            "r15",
            "r16",
            "r17",
            "r18",
        ]
    )


def parse_image_evidence_response(response: Dict[str, Any]) -> Optional[ImageEvidenceExtractionResponseModel]:
    """Parse and validate a model image-extraction response."""

    content = str((response or {}).get("content") or "").strip()
    parsed = _parse_json_object(content)
    if isinstance(parsed.get("analysis"), dict):
        parsed = parsed["analysis"]
    if not isinstance(parsed, dict) or not parsed:
        return None
    try:
        validator = getattr(ImageEvidenceExtractionResponseModel, "model_validate", None)
        if callable(validator):
            return validator(parsed)
        return ImageEvidenceExtractionResponseModel.parse_obj(parsed)
    except (TypeError, ValueError, ValidationError):
        return None


def image_evidence_ref(image_url: str) -> str:
    """Return a stable compact evidence ref for an image URL."""

    digest = hashlib.sha1(str(image_url or "").encode("utf-8")).hexdigest()[:12]
    return f"img_{digest}"


def image_evidence_summary(analysis: Dict[str, Any]) -> str:
    """Return a compact human-readable evidence summary."""

    image_type = str(analysis.get("type") or "other")
    fields = image_extracted_fields(analysis)
    if fields:
        return f"{image_type} image with visible fields: {', '.join(fields[:4])}"
    notes = str(analysis.get("notes") or "").strip()
    if notes:
        return f"{image_type} image: {notes[:120]}"
    return f"{image_type} image; no reliable Gulong fields extracted"


def image_extracted_fields(analysis: Dict[str, Any]) -> List[str]:
    """Return compact field names/values suitable for memory evidence refs."""

    fields: List[str] = []
    tire_sizes = [str(size).strip() for size in analysis.get("tire_sizes") or [] if str(size).strip()]
    if tire_sizes:
        fields.append(f"tire_size={', '.join(tire_sizes[:3])}")
    for key in [
        "car_make",
        "car_model",
        "tire_brand",
        "tire_model",
        "product_title",
        "service_location",
        "installation_partner",
        "service_type",
        "schedule_text",
        "order_id",
        "customer_name",
        "amount",
        "currency",
        "discount_text",
        "timestamp_text",
        "reference_no",
        "invoice_no",
        "payment_method",
        "paid_at",
        "merchant",
    ]:
        value = _clean_field(analysis.get(key))
        if value:
            fields.append(f"{key}={value[:80]}")
    for key in [
        "visible_messages",
        "human_agent_messages",
        "promo_terms",
        "branch_addons",
        "source_markers",
    ]:
        values = [str(item or "").strip() for item in analysis.get(key) or [] if str(item or "").strip()]
        if values:
            fields.append(f"{key}={'; '.join(values[:3])[:160]}")
    return fields[:12]


def normalize_visible_tire_size(value: Any) -> str:
    """Normalize common OCR tire-size variants without guessing missing parts."""

    text = str(value or "").strip().upper()
    if not text:
        return ""
    text = re.sub(r"\s+", "", text)
    text = text.replace("/R", "R")
    metric = re.search(r"(?P<section>\d{3})/?(?P<aspect>\d{2})R?(?P<rim>\d{2}C?)", text)
    if metric:
        return f"{metric.group('section')}/{metric.group('aspect')}R{metric.group('rim')}"
    flotation = re.search(r"(?P<diameter>\d{2}(?:\.\d+)?)X(?P<section>\d{1,2}(?:\.\d+)?)R(?P<rim>\d{2})", text)
    if flotation:
        return f"{flotation.group('diameter')}X{flotation.group('section')}R{flotation.group('rim')}"
    commercial = re.search(r"(?P<section>\d{3})R(?P<rim>\d{2}C?)", text)
    if commercial:
        return f"{commercial.group('section')}R{commercial.group('rim')}"
    slash_commercial = re.search(r"(?P<section>\d{3})/(?P<rim>1\d|2[0-4])C", text)
    if slash_commercial:
        return f"{slash_commercial.group('section')}R{slash_commercial.group('rim')}C"
    return ""


def _candidate(
    key: str,
    value: Any,
    *,
    confidence: str,
    status_hint: str,
    evidence: str,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "key": key,
        "value": value,
        "source": "external_evidence",
        "confidence": confidence,
        "status_hint": status_hint,
        "evidence": evidence,
        "origin": "image_evidence",
        "metadata": metadata,
    }


def _normalize_image_url(value: Any) -> str:
    url = str(value or "").strip().rstrip(").,];")
    if not url:
        return ""
    if "l.facebook.com/l.php" in url:
        parsed = urlparse(url)
        target = parse_qs(parsed.query).get("u", [""])[0]
        if target:
            return unquote(target).strip().rstrip(").,];")
    return url


def _is_likely_image_url(url: str, surrounding_text: str = "") -> bool:
    lowered = str(url or "").lower()
    if lowered.startswith("data:image/"):
        return True
    parsed = urlparse(url)
    path = parsed.path.lower()
    if re.search(r"\.(?:jpg|jpeg|png|webp|gif|heic|heif|bmp|tif|tiff)$", path):
        return True
    host_path = f"{parsed.netloc.lower()} {path}"
    if any(token in host_path for token in ["scontent", "cdn", "/image", "/images", "/photo", "/photos", "/uploads"]):
        return True
    if re.search(r"(?:format|ext|type)=(?:jpg|jpeg|png|webp|heic)", parsed.query.lower()):
        return True
    return any(token in str(surrounding_text or "").lower() for token in ["image", "photo", "picture", "screenshot", "pic"])


def _parse_json_object(content: str) -> Dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except Exception:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _compact_model_response(response: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "usage": dict((response or {}).get("usage") or {}),
        "cache_usage": dict((response or {}).get("cache_usage") or {}),
        "latency_ms": (response or {}).get("latency_ms"),
        "finish_reason": (response or {}).get("finish_reason"),
        "model": (response or {}).get("model"),
    }


def _model_dump(model: BaseModel) -> Dict[str, Any]:
    dumper = getattr(model, "model_dump", None)
    if callable(dumper):
        return dict(dumper())
    return dict(model.dict())


def _clean_field(value: Any) -> str:
    return str(value or "").strip()


def _compact_extracted_text(value: Any, *, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").strip())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(0, max_chars - 1)].rstrip() + "..."


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _confidence_label(value: float) -> str:
    if value >= 0.85:
        return "high"
    if value >= 0.7:
        return "medium"
    return "low"


def _unique(values: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    output: List[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
    return output
