"""Runtime V7 product observation and reference harness.

The live runtime will eventually persist observations in Firestore or another
shared store. This module keeps the first version deliberately small: it stores
compact, trusted product-search observations and validates model-proposed
follow-up references against the last presented product cards.
"""

from __future__ import annotations

import re

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from runtime_v7.canonical_values import CanonicalValuesProvider
from runtime_v7.product_search import (
    ProductSearchRunner,
    product_model_label,
    tire_protection_plan_text,
)


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ProductObservation:
    """Compact trusted product-search output saved for follow-up turns."""

    observation_ref: str
    presentation_ref: str
    created_at: str
    query_basis: Dict[str, Any] = field(default_factory=dict)
    result_pool_summary: Dict[str, Any] = field(default_factory=dict)
    presentation_strategy: Dict[str, Any] = field(default_factory=dict)
    product_cards: List[Dict[str, Any]] = field(default_factory=list)
    presented_products: List[Dict[str, Any]] = field(default_factory=list)
    best_products: List[Dict[str, Any]] = field(default_factory=list)
    facets: Dict[str, Any] = field(default_factory=dict)

    def to_public_header(self) -> Dict[str, Any]:
        """Return the small prompt-facing header for this observation."""

        return {
            "observation_ref": self.observation_ref,
            "presentation_ref": self.presentation_ref,
            "created_at": self.created_at,
            "card_count": len(self.product_cards),
            "brands": self.presentation_strategy.get("brands") or [],
            "categories": self.presentation_strategy.get("categories") or [],
            "result_pool_summary": self.result_pool_summary,
            "query_basis": self.query_basis,
        }


class ProductObservationStore:
    """In-memory observation store used by the first Runtime V7 harness."""

    def __init__(self) -> None:
        self._observations: Dict[str, ProductObservation] = {}
        self._presentation_index: Dict[str, str] = {}
        self._latest_ref: Optional[str] = None

    def save_search_result(self, result: Dict[str, Any], *, created_at: Optional[str] = None) -> ProductObservation:
        observation_ref = str(result.get("observation_ref") or "").strip()
        if not observation_ref:
            raise ValueError("product search result is missing observation_ref")
        presentation_ref = str(result.get("presentation_ref") or "").strip()
        if not presentation_ref:
            presentation_ref = observation_ref.replace("obs_", "pres_", 1)
            if presentation_ref == observation_ref:
                presentation_ref = f"pres_{observation_ref}"
        observation = ProductObservation(
            observation_ref=observation_ref,
            presentation_ref=presentation_ref,
            created_at=created_at or _utc_now_iso(),
            query_basis=deepcopy(result.get("query_basis") or {}),
            result_pool_summary=deepcopy(result.get("result_pool_summary") or {}),
            presentation_strategy=deepcopy(result.get("presentation_strategy") or {}),
            product_cards=deepcopy(result.get("product_cards") or []),
            presented_products=deepcopy(result.get("presented_products") or []),
            best_products=deepcopy(result.get("best_products") or []),
            facets=deepcopy(result.get("facets") or {}),
        )
        self._observations[observation_ref] = observation
        self._presentation_index[presentation_ref] = observation_ref
        self._latest_ref = observation_ref
        return observation

    def get(
        self,
        *,
        observation_ref: Optional[str] = None,
        presentation_ref: Optional[str] = None,
    ) -> Optional[ProductObservation]:
        if observation_ref:
            return self._observations.get(str(observation_ref))
        if presentation_ref:
            ref = self._presentation_index.get(str(presentation_ref))
            return self._observations.get(ref or "")
        return self.latest()

    def latest(self) -> Optional[ProductObservation]:
        return self._observations.get(self._latest_ref or "")

    def headers(self, *, limit: int = 3) -> List[Dict[str, Any]]:
        observations = list(self._observations.values())[-max(1, int(limit or 3)) :]
        return [observation.to_public_header() for observation in observations]


class ProductToolHarness:
    """Tool-facing harness for product search, details, and reference resolution."""

    def __init__(
        self,
        *,
        runner: Optional[ProductSearchRunner] = None,
        store: Optional[ProductObservationStore] = None,
        canonical_values_provider: Optional[CanonicalValuesProvider] = None,
    ) -> None:
        self.runner = runner or ProductSearchRunner(canonical_values_provider=canonical_values_provider)
        if runner is not None and canonical_values_provider is not None:
            self.runner.canonical_values_provider = canonical_values_provider
        self.store = store or ProductObservationStore()

    def set_canonical_values_provider(self, provider: CanonicalValuesProvider) -> None:
        """Attach a shared canonical provider to the underlying product runner."""

        self.runner.canonical_values_provider = provider

    def product_search(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Run product search and save its compact observation."""

        result = self.runner.run(dict(payload or {}))
        observation = self.store.save_search_result(result)
        result = deepcopy(result)
        result["presentation_ref"] = observation.presentation_ref
        for card in result.get("product_cards") or []:
            if isinstance(card, dict):
                card["observation_ref"] = observation.observation_ref
                card["presentation_ref"] = observation.presentation_ref
        for card in observation.product_cards:
            if isinstance(card, dict):
                card["observation_ref"] = observation.observation_ref
                card["presentation_ref"] = observation.presentation_ref
        return result

    def discover_brand_buckets(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Return deterministic brand-bucket cards without saving product refs."""

        return self.runner.discover_brand_buckets(dict(payload or {}))

    def extract_compatible_fitment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Return candidate tire sizes for vehicle text without saving cards."""

        return self.runner.extract_compatible_fitment(dict(payload or {}))

    def resolve_product_reference(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a model-proposed product reference against shown cards."""

        payload = payload or {}
        observation = self.store.get(
            observation_ref=payload.get("observation_ref"),
            presentation_ref=payload.get("presentation_ref"),
        )
        if observation is None:
            return {"status": "no_observation", "reason": "no matching product observation was found"}
        binder = ProductReferenceBinder(observation)
        return binder.resolve(
            reference_text=str(payload.get("reference_text") or payload.get("latest_user_message") or ""),
            item_ref=payload.get("item_ref"),
            card_ref=payload.get("card_ref"),
            product_id=payload.get("product_id"),
            slug=payload.get("slug"),
            ordinal=payload.get("ordinal"),
            selection_basis=payload.get("selection_basis"),
            interpreted_value=payload.get("interpreted_value"),
            candidate_card_refs=payload.get("candidate_card_refs"),
        )

    def get_product_details(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Return trusted stored details for a selected product reference."""

        resolution = self.resolve_product_reference(payload or {})
        if resolution.get("status") != "resolved":
            return {
                "status": resolution.get("status"),
                "reason": resolution.get("reason") or "product reference was not resolved",
                "resolution": resolution,
            }
        observation = self.store.get(observation_ref=resolution.get("observation_ref"))
        if observation is None:
            return {"status": "no_observation", "reason": "resolved observation is no longer available"}
        product = _find_product(observation, resolution.get("item_ref"))
        card = _find_card(observation, item_ref=resolution.get("item_ref"), card_ref=resolution.get("card_ref"))
        if not product and not card:
            return {"status": "not_found", "reason": "resolved product was not found in stored observation"}
        return {
            "status": "ok",
            "observation_ref": observation.observation_ref,
            "presentation_ref": observation.presentation_ref,
            "matched_by": resolution.get("matched_by"),
            "item_ref": resolution.get("item_ref"),
            "card_ref": resolution.get("card_ref"),
            "product": _compact_product_details(product or {}, card=card or {}),
            "card": deepcopy(card or {}),
            "selected_product_card": _selected_product_card(product or {}, card or {}),
            "selected_product_cards": [_selected_product_card(product or {}, card or {})],
            "card_runtime_insert": True,
        }


class ProductReferenceBinder:
    """Validate model-proposed references to the last presented cards.

    This class intentionally does not interpret customer language. The model is
    responsible for reading phrases such as "yun una" or "that Michelin" from
    the prompt-facing card list and proposing a concrete card_ref, item_ref, or
    ordinal. The runtime only verifies that the proposed binding exists in the
    trusted observation.
    """

    def __init__(self, observation: ProductObservation) -> None:
        self.observation = observation

    def resolve(
        self,
        *,
        reference_text: str = "",
        item_ref: Optional[Any] = None,
        card_ref: Optional[Any] = None,
        product_id: Optional[Any] = None,
        slug: Optional[Any] = None,
        ordinal: Optional[Any] = None,
        selection_basis: Optional[Any] = None,
        interpreted_value: Optional[Any] = None,
        candidate_card_refs: Optional[Sequence[Any]] = None,
    ) -> Dict[str, Any]:
        basis = str(selection_basis or "").strip().casefold()
        if basis:
            return self._resolve_selection_plan(
                selection_basis=basis,
                interpreted_value=interpreted_value,
                candidate_card_refs=candidate_card_refs,
                item_ref=item_ref,
                card_ref=card_ref,
                product_id=product_id,
                slug=slug,
                ordinal=ordinal,
            )

        direct_values_provided = any(value not in (None, "") for value in [item_ref, card_ref, product_id, slug])
        direct_matches = self._direct_candidates(item_ref=item_ref, card_ref=card_ref, product_id=product_id, slug=slug)
        if len(direct_matches) == 1:
            return self._resolved(direct_matches[0], "direct_ref", "high")
        if len(direct_matches) > 1:
            return self._ambiguous("direct reference matched multiple shown products", direct_matches)
        if direct_values_provided:
            return self._not_found("provided direct reference did not match stored product cards")

        ordinal_card = self._resolve_ordinal_value(ordinal)
        if ordinal_card:
            return self._resolved(ordinal_card, "model_interpreted_ordinal", "high")
        if ordinal not in (None, ""):
            return self._not_found("provided ordinal is outside the shown product cards")

        text = str(reference_text or "").strip()
        if text:
            return self._needs_model_resolution(text)
        return self._not_found("no product reference was provided")

    def _resolve_selection_plan(
        self,
        *,
        selection_basis: str,
        interpreted_value: Optional[Any],
        candidate_card_refs: Optional[Sequence[Any]],
        item_ref: Optional[Any],
        card_ref: Optional[Any],
        product_id: Optional[Any],
        slug: Optional[Any],
        ordinal: Optional[Any],
    ) -> Dict[str, Any]:
        """Validate a typed model plan without interpreting raw customer text."""

        if selection_basis == "ordinal":
            ordinal_card = self._resolve_ordinal_value(ordinal)
            if ordinal_card:
                return self._resolved(
                    ordinal_card,
                    "model_interpreted_ordinal",
                    "high",
                )
            return self._not_found(
                "selection_basis=ordinal requires a valid shown-card ordinal"
            )

        if selection_basis == "exact_ref":
            direct_matches = self._direct_candidates(
                item_ref=item_ref,
                card_ref=card_ref,
                product_id=product_id,
                slug=slug,
            )
            if len(direct_matches) == 1:
                return self._resolved(direct_matches[0], "direct_ref", "high")
            if len(direct_matches) > 1:
                return self._ambiguous(
                    "exact reference matched multiple shown products",
                    direct_matches,
                )
            return self._not_found(
                "selection_basis=exact_ref requires one current shown-card reference"
            )

        if selection_basis in {"brand", "model"}:
            value = _normalize_selection_value(interpreted_value)
            if not value:
                return self._invalid_plan(
                    f"selection_basis={selection_basis} requires interpreted_value"
                )
            matches = [
                card
                for card in self.observation.product_cards
                if _card_matches_interpreted_value(
                    card,
                    selection_basis=selection_basis,
                    interpreted_value=value,
                )
            ]
            if len(matches) == 1:
                return self._resolved(
                    matches[0],
                    f"unique_visible_{selection_basis}",
                    "high",
                )
            if len(matches) > 1:
                return self._ambiguous(
                    (
                        f"{selection_basis} matches multiple shown products; "
                        "ask which exact visible SKU/model"
                    ),
                    matches,
                )
            return self._not_found(
                f"interpreted {selection_basis} did not match a shown product"
            )

        if selection_basis == "attribute":
            refs = {
                str(value or "").strip()
                for value in candidate_card_refs or []
                if str(value or "").strip()
            }
            matches = [
                card
                for card in self.observation.product_cards
                if str(card.get("card_ref") or "").strip() in refs
            ]
            if len(matches) == 1:
                return self._resolved(
                    matches[0],
                    "model_interpreted_attribute",
                    "medium",
                )
            if len(matches) > 1:
                return self._ambiguous(
                    "attribute description still matches multiple shown products",
                    matches,
                )
            return self._invalid_plan(
                "selection_basis=attribute requires exactly one proposed shown-card candidate"
            )

        return self._invalid_plan(
            "selection_basis must be exact_ref, ordinal, brand, model, or attribute"
        )

    def _direct_candidates(
        self,
        *,
        item_ref: Optional[Any],
        card_ref: Optional[Any],
        product_id: Optional[Any],
        slug: Optional[Any],
    ) -> List[Dict[str, Any]]:
        card_criteria = {
            "item_ref": item_ref,
            "card_ref": card_ref,
            "product_id": product_id,
            "slug": slug,
        }
        card_criteria = {key: value for key, value in card_criteria.items() if value not in (None, "")}
        product_criteria = {
            "item_ref": item_ref,
            "product_id": product_id,
            "slug": slug,
        }
        product_criteria = {key: value for key, value in product_criteria.items() if value not in (None, "")}
        if not card_criteria:
            return []

        matches: List[Dict[str, Any]] = []
        for card in self.observation.product_cards:
            if _matches_all(card, card_criteria):
                matches.append(card)
        if matches or card_ref not in (None, ""):
            return matches

        seen_product_refs: set[tuple[str, str, str]] = set()
        for product in self.observation.presented_products + self.observation.best_products:
            if _matches_all(product, product_criteria):
                product_key = (
                    str(product.get("item_ref") or ""),
                    str(product.get("product_id") or ""),
                    str(product.get("slug") or ""),
                )
                if product_key in seen_product_refs:
                    continue
                seen_product_refs.add(product_key)
                matches.append(_card_like_from_product(product))
        return matches

    def _resolve_ordinal_value(self, ordinal: Optional[Any]) -> Optional[Dict[str, Any]]:
        if ordinal in (None, ""):
            return None
        try:
            index = int(str(ordinal).strip()) - 1
        except Exception:
            return None
        if 0 <= index < len(self.observation.product_cards):
            return self.observation.product_cards[index]
        return None

    def _resolved(self, card: Dict[str, Any], matched_by: str, confidence: str) -> Dict[str, Any]:
        return {
            "status": "resolved",
            "matched_by": matched_by,
            "confidence": confidence,
            "observation_ref": self.observation.observation_ref,
            "presentation_ref": self.observation.presentation_ref,
            "item_ref": card.get("item_ref"),
            "card_ref": card.get("card_ref"),
            "product_id": card.get("product_id"),
            "slug": card.get("slug"),
            "product_summary": _compact_card(card),
        }

    def _ambiguous(self, reason: str, cards: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "status": "ambiguous",
            "reason": reason,
            "observation_ref": self.observation.observation_ref,
            "presentation_ref": self.observation.presentation_ref,
            "candidates": [_compact_card(card) for card in cards[:4]],
        }

    def _needs_model_resolution(self, reference_text: str) -> Dict[str, Any]:
        return {
            "status": "needs_model_resolution",
            "reason": "runtime does not interpret raw customer reference text; choose a card_ref, item_ref, product_id, slug, or ordinal from shown_cards",
            "reference_text": reference_text,
            "observation_ref": self.observation.observation_ref,
            "presentation_ref": self.observation.presentation_ref,
            "shown_cards": [_compact_card(card) for card in self.observation.product_cards[:4]],
            "accepted_reference_fields": ["card_ref", "item_ref", "product_id", "slug", "ordinal"],
        }

    def _not_found(self, reason: str) -> Dict[str, Any]:
        return {
            "status": "not_found",
            "reason": reason,
            "observation_ref": self.observation.observation_ref,
            "presentation_ref": self.observation.presentation_ref,
            "shown_cards": [_compact_card(card) for card in self.observation.product_cards[:4]],
        }

    def _invalid_plan(self, reason: str) -> Dict[str, Any]:
        return {
            "status": "invalid_selection_plan",
            "reason": reason,
            "observation_ref": self.observation.observation_ref,
            "presentation_ref": self.observation.presentation_ref,
            "shown_cards": [
                _compact_card(card)
                for card in self.observation.product_cards[:4]
            ],
        }


class ProductReferenceResolver(ProductReferenceBinder):
    """Backward-compatible alias for the reference binding harness."""

    pass


def _find_product(observation: ProductObservation, item_ref: Optional[Any]) -> Optional[Dict[str, Any]]:
    if not item_ref:
        return None
    for product in observation.presented_products + observation.best_products:
        if str(product.get("item_ref")) == str(item_ref):
            return product
    return None


def _find_card(
    observation: ProductObservation,
    *,
    item_ref: Optional[Any] = None,
    card_ref: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    for card in observation.product_cards:
        if item_ref and str(card.get("item_ref")) == str(item_ref):
            return card
        if card_ref and str(card.get("card_ref")) == str(card_ref):
            return card
    return None


def _matches_all(row: Dict[str, Any], criteria: Dict[str, Any]) -> bool:
    return all(str(row.get(key)) == str(value) for key, value in criteria.items())


def _normalize_selection_value(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _card_matches_interpreted_value(
    card: Dict[str, Any],
    *,
    selection_basis: str,
    interpreted_value: str,
) -> bool:
    if selection_basis == "brand":
        return _normalize_selection_value(card.get("brand")) == interpreted_value
    model = _normalize_selection_value(
        card.get("sku_model")
        or card.get("model")
        or card.get("product_name")
        or card.get("title")
    )
    return bool(
        model
        and (
            interpreted_value == model
            or f" {interpreted_value} " in f" {model} "
        )
    )


def _compact_card(card: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "card_ref",
        "item_ref",
        "product_id",
        "slug",
        "brand",
        "category",
        "tire_size",
        "sku_model",
        "deal_price_line",
        "promo_savings_line",
        "pricing_facts",
        "image_url",
        "url",
        "why_shown",
    ]
    return {key: card.get(key) for key in keys if card.get(key) not in (None, "", [])}


def _compact_product_details(product: Dict[str, Any], *, card: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return only safe customer-facing detail fields for the model."""

    card = card or {}
    tpp = card.get("tire_protection_plan") or tire_protection_plan_text(product)
    customer_price_line = (
        card.get("deal_price_line")
        or product.get("total_price_text")
        or product.get("price_text")
    )
    promo_line = card.get("promo_savings_line") or product.get("promo_label") or product.get("promo_text")
    stock_status = "Pre-order" if product.get("pre_order") else "In stock"
    payload = {
        "item_ref": product.get("item_ref") or card.get("item_ref"),
        "product_id": product.get("product_id") or card.get("product_id"),
        "slug": product.get("slug") or card.get("slug"),
        "brand": product.get("brand") or card.get("brand"),
        "model": product.get("model") or card.get("sku_model"),
        "pattern": product.get("pattern"),
        "size": product.get("size"),
        "section_width": product.get("section_width"),
        "aspect_ratio": product.get("aspect_ratio"),
        "rim_size": product.get("rim_size"),
        "category": product.get("category") or card.get("category"),
        "customer_price_line": customer_price_line,
        "promo_line": promo_line,
        "pricing_facts": card.get("pricing_facts") or product.get("pricing_facts"),
        "image_url": product.get("image_url") or card.get("image_url"),
        "stock_status": stock_status,
        "pre_order": bool(product.get("pre_order")),
        "dot": product.get("dot") or card.get("dot"),
        "origin": product.get("origin") or card.get("origin"),
        "warranty": product.get("warranty") or card.get("warranty"),
        "warranty_years": product.get("warranty_years"),
        "tire_protection_plan": tpp,
        "installment_text": product.get("installment_text"),
        "installments": product.get("installments"),
        "ev_compatible": product.get("ev_compatible"),
        "gulong_guarantee": product.get("gulong_guarantee"),
        "url": product.get("url") or card.get("url"),
    }
    return {key: value for key, value in payload.items() if value not in (None, "", [])}


def _selected_product_card(product: Dict[str, Any], card: Dict[str, Any]) -> Dict[str, Any]:
    """Build the deterministic selected-product card body for insertion."""

    details = _compact_product_details(product, card=card)
    sku_model = card.get("sku_model") or product_model_label(product)
    price_line = details.get("customer_price_line")
    promo_line = details.get("promo_line")
    warranty_parts = [
        str(details.get("warranty") or "").strip(),
        str(details.get("tire_protection_plan") or "").strip(),
    ]
    warranty_line = " + ".join(part for part in warranty_parts if part)
    lines = [
        "[PRODUCT DETAILS]",
        str(sku_model or "").strip(),
    ]
    if price_line:
        lines.append(f"Price: {price_line}")
    if promo_line:
        lines.append(f"Promo: {promo_line}")
    if details.get("stock_status"):
        lines.append(f"Availability: {details.get('stock_status')}")
    if details.get("installment_text"):
        lines.append(f"Installment: {details.get('installment_text')}")
    if details.get("origin"):
        lines.append(f"Origin: {details.get('origin')}")
    if details.get("dot"):
        lines.append(f"DOT: {details.get('dot')}")
    if warranty_line:
        lines.append(f"Warranty/TPP: {warranty_line}")
    if details.get("url"):
        lines.append(f"Link: {details.get('url')}")
    return {
        "card_ref": card.get("card_ref"),
        "item_ref": details.get("item_ref"),
        "product_id": details.get("product_id"),
        "slug": details.get("slug"),
        "brand": details.get("brand"),
        "category": details.get("category"),
        "sku_model": sku_model,
        "customer_price_line": details.get("customer_price_line"),
        "promo_line": details.get("promo_line"),
        "pricing_facts": details.get("pricing_facts"),
        "image_url": details.get("image_url"),
        "stock_status": details.get("stock_status"),
        "installment_text": details.get("installment_text"),
        "warranty": details.get("warranty"),
        "tire_protection_plan": details.get("tire_protection_plan"),
        "dot": details.get("dot"),
        "origin": details.get("origin"),
        "url": details.get("url"),
        "card_text": "\n".join(line for line in lines if str(line or "").strip()),
    }


def _card_like_from_product(product: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "item_ref": product.get("item_ref"),
        "product_id": product.get("product_id"),
        "slug": product.get("slug"),
        "brand": product.get("brand"),
        "category": product.get("category"),
        "sku_model": product.get("model"),
        "deal_price_line": product.get("total_price_text") or product.get("price_text"),
        "promo_savings_line": product.get("promo_label") or product.get("product_discount_text"),
        "pricing_facts": product.get("pricing_facts"),
        "image_url": product.get("image_url"),
        "url": product.get("url"),
    }
