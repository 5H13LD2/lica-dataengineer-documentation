"""Channel rendering helpers for Runtime V7.

The model and harness produce structured response units plus trusted runtime
surfaces. This module converts that output into channel-safe text/image content
without asking the model to rewrite exact product, order, or payment details.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Sequence, Tuple
from urllib.parse import urlparse

from runtime_v7.choice_actions import (
    build_location_choice_token,
    build_payment_method_choice_token,
    build_payment_option_choice_token,
    build_price_category_token,
    build_product_choice_token,
    build_schedule_choice_token,
)
from runtime_v7.promo_catalog import build_promo_click_token, parse_promo_click_token
from runtime_v7.runtime_harness import (
    FIRST_TURN_INTRO_MODE_FULL,
    FIRST_TURN_INTRO_MODE_WELCOME_ONLY,
    MODEL_COMPOSED_FIRST_TURN_OPENING_EVENT_TYPE,
    RUNTIME_V7_FIRST_TURN_INTRO_MESSAGES,
    RUNTIME_V7_FIRST_TURN_INTRO_TEXT,
    RUNTIME_V7_WELCOME_SPIEL_TEXT,
    WELCOME_SPIEL_GUARD_EVENT_TYPE,
    _collect_runtime_presentation_surfaces,
    final_composer_surface_plan_authoritative,
    _normalize_first_turn_intro_mode,
    _parse_structured_response_units,
    _provider_owned_product_match_scope_notice,
    _recover_response_units_from_plain_model_text,
    _product_inclusions_spiel,
    _response_has_welcome_spiel,
    _render_runtime_surface_body,
    _sanitize_structured_text_unit,
    _surface_service_type,
    _surfaces_include_warranty_promo,
)
from runtime_v7.transaction_choices import (
    build_schedule_choice_surface,
)


DEFAULT_MAX_BUBBLE_CHARS = 1900


@dataclass
class RuntimeV7ChannelRender:
    """Rendered channel output for a Runtime V7 turn."""

    response: Dict[str, str]
    content_messages: List[Dict[str, Any]]
    images: List[Dict[str, str]] = field(default_factory=list)
    payment: Dict[str, Any] = field(default_factory=dict)
    contact_actions: List[Dict[str, Any]] = field(default_factory=list)
    promo_presentation: Dict[str, Any] = field(default_factory=dict)
    choice_presentations: List[Dict[str, Any]] = field(default_factory=list)
    product_presentations: List[Dict[str, Any]] = field(default_factory=list)
    service_policy_note_ids: List[str] = field(default_factory=list)
    text: str = ""


def render_turn_for_channel(
    turn_record: Dict[str, Any],
    *,
    max_bubble_chars: int = DEFAULT_MAX_BUBBLE_CHARS,
    profile_fields: Dict[str, Any] | None = None,
    service_environment: str | None = None,
) -> RuntimeV7ChannelRender:
    """Render a harness turn into bubbles plus ManyChat-style content items."""

    suppressed_surface_tools = {
        str(value or "").strip()
        for value in turn_record.get("suppressed_channel_surface_tools") or []
        if str(value or "").strip()
    }
    tool_results = [
        item
        for item in turn_record.get("tool_results") or []
        if isinstance(item, dict)
        and str(item.get("name") or "").strip() not in suppressed_surface_tools
    ]
    surfaces = _collect_runtime_presentation_surfaces(tool_results)
    surfaces = _prepare_product_selection_surfaces(
        surfaces,
        delivered_price_lists=(
            turn_record.get("product_price_list_delivery_fingerprints") or []
        ),
    )
    previously_sent_policy_notes = {
        str(value or "").strip()
        for value in turn_record.get("service_policy_note_ids_previously_sent") or []
        if str(value or "").strip()
    }
    surfaces = _filter_seen_service_policy_notes(
        surfaces,
        previously_sent=previously_sent_policy_notes,
    )
    location_surface = (
        turn_record.get("location_choice_surface")
        if isinstance(turn_record.get("location_choice_surface"), dict)
        else {}
    )
    checkout_surface = (
        turn_record.get("checkout_choice_surface")
        if isinstance(turn_record.get("checkout_choice_surface"), dict)
        else {}
    )
    if location_surface:
        surfaces.append(
            (
                "location_choice",
                _composer_owned_choice_surface(location_surface),
            )
        )
    if checkout_surface:
        surfaces.append(
            (
                "checkout_choice",
                _composer_owned_choice_surface(checkout_surface),
            )
        )
    units = _response_units_from_turn(turn_record)
    include_product_inclusions = bool(
        not turn_record.get("product_inclusions_previously_sent")
        and not _surfaces_include_warranty_promo(surfaces)
    )
    content_messages = _render_units_to_content(
        units,
        surfaces,
        include_product_inclusions=include_product_inclusions,
        service_environment=service_environment,
        append_unrendered=not final_composer_surface_plan_authoritative(
            turn_record
        ),
    )
    if not content_messages:
        fallback_text = str(turn_record.get("runtime_final_response") or "").strip()
        content_messages = _text_messages_from_text(fallback_text) if fallback_text else []
    if _turn_has_welcome_spiel_marker(turn_record):
        content_messages = _split_prefixed_welcome_spiel(content_messages)
    if _should_prepend_welcome_spiel(turn_record, content_messages):
        intro_messages = [{"type": "text", "text": text} for text in _first_turn_intro_messages_for_turn(turn_record)]
        content_messages = [*intro_messages, *content_messages]
    content_messages = _merge_fallback_welcome_only_with_first_text(
        turn_record,
        content_messages,
    )
    content_messages = _split_text_messages(content_messages, max_chars=max_bubble_chars)
    response = _messages_to_bubbles(content_messages)
    images = [_image_meta(message) for message in content_messages if str(message.get("type") or "") == "image"]
    images = [item for item in images if item.get("url")]
    payment = _payment_metadata(surfaces)
    promo_presentation = (
        _promo_presentation_metadata(surfaces)
        if _content_has_tracked_choice_token(content_messages, prefix="pc1|")
        else {}
    )
    category_presentations = (
        _choice_presentation_metadata(surfaces)
        if _content_has_tracked_choice_token(content_messages, prefix="bc1|")
        else []
    )
    location_presentations = (
        [_location_choice_presentation_metadata(location_surface)]
        if location_surface
        and _content_has_tracked_choice_token(content_messages, prefix="lc1|")
        else []
    )
    location_presentations = [item for item in location_presentations if item]
    product_choice_presentations = (
        _product_choice_presentation_metadata(surfaces)
        if _content_has_tracked_choice_token(content_messages, prefix="ps1|")
        else []
    )
    schedule_presentations = (
        _schedule_choice_presentation_metadata(surfaces)
        if _content_has_tracked_choice_token(content_messages, prefix="ss1|")
        else []
    )
    checkout_presentations = (
        [_checkout_choice_presentation_metadata(checkout_surface)]
        if checkout_surface
        and (
            _content_has_tracked_choice_token(content_messages, prefix="po1|")
            or _content_has_tracked_choice_token(content_messages, prefix="pm1|")
        )
        else []
    )
    checkout_presentations = [item for item in checkout_presentations if item]
    choice_presentations = [
        *category_presentations,
        *location_presentations,
        *product_choice_presentations,
        *schedule_presentations,
        *checkout_presentations,
    ]
    product_presentations = [
        presentation
        for presentation in _product_presentation_metadata(
            surfaces,
            include_product_inclusions=include_product_inclusions,
        )
        if _product_presentation_visible_in_messages(
            content_messages,
            presentation,
        )
    ]
    service_policy_note_ids = _rendered_service_policy_note_ids(surfaces)
    contact_actions = _promo_contact_actions(promo_presentation, profile_fields or {})
    if not contact_actions:
        contact_actions = _choice_contact_actions(choice_presentations, profile_fields or {})
    text = "\n\n".join(str(message.get("text") or "").strip() for message in content_messages if message.get("type") == "text")
    return RuntimeV7ChannelRender(
        response=response,
        content_messages=content_messages,
        images=images,
        payment=payment,
        contact_actions=contact_actions,
        promo_presentation=promo_presentation,
        choice_presentations=choice_presentations,
        product_presentations=product_presentations,
        service_policy_note_ids=service_policy_note_ids,
        text=text,
    )


def _product_presentation_visible_in_messages(
    messages: Sequence[Dict[str, Any]],
    presentation: Mapping[str, Any],
) -> bool:
    """Keep presentation metadata aligned with the actual channel payload."""

    presentation_ref = str(
        presentation.get("presentation_ref") or ""
    ).strip()
    if presentation_ref and any(
        str(action.get("value") or "").startswith(
            f"ps1|{presentation_ref}|"
        )
        for message in messages or []
        if isinstance(message, Mapping)
        for element in message.get("elements") or []
        if isinstance(element, Mapping)
        for button in element.get("buttons") or []
        if isinstance(button, Mapping)
        for action in button.get("actions") or []
        if isinstance(action, Mapping)
    ):
        return True

    visible_parts: List[str] = []
    for message in messages or []:
        if not isinstance(message, Mapping):
            continue
        visible_parts.append(str(message.get("text") or ""))
        for element in message.get("elements") or []:
            if isinstance(element, Mapping):
                visible_parts.extend(
                    [
                        str(element.get("title") or ""),
                        str(element.get("subtitle") or ""),
                    ]
                )
    visible_text = re.sub(
        r"[^a-z0-9]+",
        " ",
        " ".join(visible_parts).casefold(),
    ).strip()
    for card in presentation.get("cards") or []:
        if not isinstance(card, Mapping):
            continue
        for key in ("sku_model", "model", "title", "slug"):
            candidate = re.sub(
                r"[^a-z0-9]+",
                " ",
                str(card.get(key) or "").casefold(),
            ).strip()
            if len(candidate) >= 5 and candidate in visible_text:
                return True
    return False


def _prepare_product_selection_surfaces(
    surfaces: Sequence[Tuple[str, Dict[str, Any]]],
    *,
    delivered_price_lists: Sequence[Dict[str, Any]],
) -> List[Tuple[str, Dict[str, Any]]]:
    """Align product text, gallery buttons, and repeat-suppression identity.

    A multi-product gallery may contain only cards with a trusted catalog image,
    a stable card reference, and a visible title. Source-backed cards without a
    trusted image remain in the long-form price list, but they do not enter the
    tracked visual-choice allowlist. Price text is suppressed only for the exact
    same presentation previously delivered by the price-list-plus-gallery
    renderer.
    """

    prepared: List[Tuple[str, Dict[str, Any]]] = []
    prior = [item for item in delivered_price_lists or [] if isinstance(item, dict)]
    for surface_type, original in surfaces or []:
        if surface_type != "product" or str(original.get("tool") or "") not in {
            "product_search",
            "get_product_details",
        }:
            prepared.append((surface_type, original))
            continue
        surface = dict(original)
        cards = [card for card in surface.get("cards") or [] if isinstance(card, dict)]
        surface["cards"] = cards
        full = surface.get("full_result") if isinstance(surface.get("full_result"), dict) else {}
        presentation_ref = str(
            full.get("presentation_ref") or surface.get("presentation_ref") or ""
        ).strip()
        identities = [_product_card_identity(card) for card in cards]
        commercial_fingerprints = [
            _product_card_commercial_fingerprint(card) for card in cards
        ]
        surface["_suppress_repeated_price_list"] = bool(
            presentation_ref
            and identities
            and commercial_fingerprints
            and any(
                str(item.get("presentation_ref") or "").strip()
                == presentation_ref
                and list(item.get("card_identities") or []) == identities
                and list(item.get("commercial_fingerprints") or [])
                == commercial_fingerprints
                for item in prior
            )
        )
        prepared.append((surface_type, surface))
    return prepared


def _product_card_identity(card: Dict[str, Any]) -> str:
    """Return the first stable provider-backed identity available for a card."""

    for key in ("item_ref", "product_id", "slug", "card_ref"):
        value = str(card.get(key) or "").strip()
        if value:
            return f"{key}:{value}"
    return ""


def _product_card_commercial_fingerprint(card: Mapping[str, Any]) -> str:
    """Hash the canonical customer-visible deterministic product details."""

    payload = {
        "rendered_card": _approved_product_price_list_card(dict(card)),
    }
    digest = hashlib.sha1(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"pcf1:{digest}"


def _filter_seen_service_policy_notes(
    surfaces: Sequence[Tuple[str, Dict[str, Any]]],
    *,
    previously_sent: set[str],
) -> List[Tuple[str, Dict[str, Any]]]:
    """Suppress already delivered policy notes while retaining sanitizer ownership."""

    output: List[Tuple[str, Dict[str, Any]]] = []
    for surface_type, surface in surfaces or []:
        if surface_type != "service" or not previously_sent:
            output.append((surface_type, surface))
            continue
        copied = deepcopy(surface)
        full = copied.get("full_result") if isinstance(copied.get("full_result"), dict) else {}
        notes = [item for item in full.get("service_policy_notes") or [] if isinstance(item, dict)]
        kept = [
            item
            for item in notes
            if str(item.get("id") or "").strip() not in previously_sent
        ]
        suppressed = [
            item
            for item in notes
            if str(item.get("id") or "").strip() in previously_sent
        ]
        full["service_policy_notes"] = kept
        if suppressed:
            full["suppressed_service_policy_notes"] = suppressed
        copied["full_result"] = full
        output.append((surface_type, copied))
    return output


def _rendered_service_policy_note_ids(
    surfaces: Sequence[Tuple[str, Dict[str, Any]]],
) -> List[str]:
    """Return stable IDs for policy notes included in the rendered surfaces."""

    return list(
        dict.fromkeys(
            str(note.get("id") or "").strip()
            for surface_type, surface in surfaces or []
            if surface_type == "service"
            for note in (
                (surface.get("full_result") or {}).get("service_policy_notes") or []
                if isinstance(surface.get("full_result"), dict)
                else []
            )
            if isinstance(note, dict) and str(note.get("id") or "").strip()
        )
    )


def _content_has_tracked_choice_token(
    messages: Sequence[Dict[str, Any]],
    *,
    prefix: str,
) -> bool:
    """Return whether delivered card content contains one tracked choice token."""

    for message in messages or []:
        if str(message.get("type") or "").strip().casefold() != "cards":
            continue
        for element in message.get("elements") or []:
            if not isinstance(element, dict):
                continue
            for button in element.get("buttons") or []:
                if not isinstance(button, dict):
                    continue
                for action in button.get("actions") or []:
                    if not isinstance(action, dict):
                        continue
                    value = str(action.get("value") or "")
                    if action.get("field_name") == "promo_selected_id" and value.startswith(prefix):
                        return True
    return False


def _should_prepend_welcome_spiel(
    turn_record: Dict[str, Any],
    content_messages: Sequence[Dict[str, Any]],
) -> bool:
    if not _turn_has_welcome_spiel_marker(turn_record):
        return False
    rendered_text = "\n\n".join(
        str(message.get("text") or "").strip()
        for message in content_messages or []
        if message.get("type") == "text"
    )
    return not _response_has_welcome_spiel(rendered_text)


def _turn_has_welcome_spiel_marker(turn_record: Dict[str, Any]) -> bool:
    if bool(turn_record.get("welcome_spiel_inserted")):
        return True
    return any(
        isinstance(event, dict) and event.get("type") == WELCOME_SPIEL_GUARD_EVENT_TYPE
        for event in turn_record.get("response_guard_events") or []
    )


def _first_turn_intro_messages_for_turn(turn_record: Dict[str, Any]) -> List[str]:
    mode = _first_turn_intro_mode_for_turn(turn_record)
    if mode == FIRST_TURN_INTRO_MODE_WELCOME_ONLY:
        return [RUNTIME_V7_WELCOME_SPIEL_TEXT]
    return list(RUNTIME_V7_FIRST_TURN_INTRO_MESSAGES)


def _first_turn_intro_mode_for_turn(turn_record: Dict[str, Any]) -> str:
    direct = _normalize_first_turn_intro_mode(turn_record.get("first_turn_intro_mode"))
    if direct:
        return direct
    for event in turn_record.get("response_guard_events") or []:
        if not isinstance(event, dict) or event.get("type") not in {
            WELCOME_SPIEL_GUARD_EVENT_TYPE,
            MODEL_COMPOSED_FIRST_TURN_OPENING_EVENT_TYPE,
        }:
            continue
        return _normalize_first_turn_intro_mode(event.get("intro_mode")) or FIRST_TURN_INTRO_MODE_FULL
    if bool(turn_record.get("welcome_spiel_inserted")):
        return FIRST_TURN_INTRO_MODE_FULL
    return ""


def _split_prefixed_welcome_spiel(content_messages: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    welcome = RUNTIME_V7_WELCOME_SPIEL_TEXT.strip()
    intro = RUNTIME_V7_FIRST_TURN_INTRO_TEXT.strip()
    for message in content_messages or []:
        if str(message.get("type") or "") != "text":
            output.append(dict(message))
            continue
        text = str(message.get("text") or "").strip()
        if text == intro:
            output.extend({"type": "text", "text": part} for part in RUNTIME_V7_FIRST_TURN_INTRO_MESSAGES)
            continue
        if text.startswith(f"{intro}\n\n"):
            remainder = text[len(intro) :].strip()
            output.extend({"type": "text", "text": part} for part in RUNTIME_V7_FIRST_TURN_INTRO_MESSAGES)
            if remainder:
                output.append({"type": "text", "text": remainder})
            continue
        if text == welcome:
            output.append({"type": "text", "text": welcome})
            continue
        if text.startswith(f"{welcome}\n\n"):
            remainder = text[len(welcome) :].strip()
            output.append({"type": "text", "text": welcome})
            if remainder:
                output.append({"type": "text", "text": remainder})
            continue
        output.append(dict(message))
    return output


def _merge_fallback_welcome_only_with_first_text(
    turn_record: Dict[str, Any],
    content_messages: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Join a fixed fallback welcome to its continuation when safe.

    Normal welcome-only turns already contain one complete model-authored opening
    and never enter this branch. Full intake stays separate, and a surface-first
    fallback is left untouched because text must not move across a surface.
    """

    messages = [dict(message) for message in content_messages or []]
    if _first_turn_intro_mode_for_turn(turn_record) != FIRST_TURN_INTRO_MODE_WELCOME_ONLY:
        return messages
    if len(messages) < 2:
        return messages
    response_units = _response_units_from_turn(turn_record)
    first_unit = next(
        (unit for unit in response_units if isinstance(unit, dict)),
        {},
    )
    if first_unit and str(first_unit.get("type") or "") != "text":
        return messages
    first, second = messages[0], messages[1]
    if (
        str(first.get("type") or "") != "text"
        or str(first.get("text") or "").strip() != RUNTIME_V7_WELCOME_SPIEL_TEXT
        or str(second.get("type") or "") != "text"
        or not str(second.get("text") or "").strip()
    ):
        return messages
    merged = dict(first)
    merged["text"] = (
        f"{RUNTIME_V7_WELCOME_SPIEL_TEXT}\n\n"
        f"{str(second.get('text') or '').strip()}"
    )
    return [merged, *messages[2:]]


def _response_units_from_turn(turn_record: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("assistant_text", "draft_assistant_text", "runtime_final_response"):
        raw = str(turn_record.get(key) or "")
        units = _parse_structured_response_units(raw)
        if units is not None:
            return units
        if key != "runtime_final_response":
            recovered = _recover_response_units_from_plain_model_text(raw)
            if recovered:
                return recovered
    final = turn_record.get("final_composer_response")
    if isinstance(final, dict):
        units = _parse_structured_response_units(str(final.get("content") or ""))
        if units is not None:
            return units
    return []


def _render_units_to_content(
    response_units: Sequence[Dict[str, Any]],
    surfaces: Sequence[Tuple[str, Dict[str, Any]]],
    *,
    include_product_inclusions: bool = True,
    service_environment: str | None = None,
    append_unrendered: bool = True,
) -> List[Dict[str, Any]]:
    content: List[Dict[str, Any]] = []
    surface_by_ref = _surface_index(surfaces)
    rendered_refs: set[str] = set()
    pending_text: List[str] = []

    def flush_text() -> None:
        if not pending_text:
            return
        joined = "\n\n".join(part for part in pending_text if part).strip()
        pending_text.clear()
        if joined:
            content.extend(_text_messages_from_text(joined))

    for unit in response_units or []:
        unit_type = str(unit.get("type") or "").strip().lower()
        unit_content = unit.get("content") if isinstance(unit.get("content"), dict) else {}
        if unit_type == "text":
            text = _sanitize_structured_text_unit(str(unit_content.get("text") or ""), surfaces).strip()
            if text:
                pending_text.append(text)
            continue
        if unit_type == "image":
            flush_text()
            image = _image_message_from_content(unit_content)
            if image:
                content.append(image)
            continue
        if unit_type != "render_surface":
            continue
        surface_ref = str(unit_content.get("surface_ref") or "").strip()
        surface_entry = surface_by_ref.get(surface_ref)
        if (
            surface_entry
            and surface_entry[0] == "product"
            and str(surface_entry[1].get("tool") or "") == "product_search"
            and _provider_owned_product_match_scope_notice(
                surface_entry[1].get("full_result")
                if isinstance(surface_entry[1].get("full_result"), dict)
                else {}
            )
        ):
            # The deterministic partial-match notice owns product scope. Drop
            # adjacent model prose so it cannot call relaxed cards exact
            # matches before the authoritative disclosure.
            pending_text.clear()
        flush_text()
        if not surface_entry:
            continue
        canonical_ref = str(surface_entry[1].get("surface_ref") or surface_ref).strip()
        if canonical_ref and canonical_ref in rendered_refs:
            continue
        content.extend(
            _surface_to_content(
                surface_entry[0],
                surface_entry[1],
                include_product_inclusions=include_product_inclusions,
                service_environment=service_environment,
            )
        )
        if canonical_ref:
            rendered_refs.add(canonical_ref)

    flush_text()
    if not append_unrendered:
        return _dedupe_adjacent_messages(content)
    for surface_type, surface in sorted(surfaces, key=lambda item: int(item[1].get("order") or 0)):
        surface_ref = str(surface.get("surface_ref") or "").strip()
        if surface_ref and surface_ref in rendered_refs:
            continue
        content.extend(
            _surface_to_content(
                surface_type,
                surface,
                include_product_inclusions=include_product_inclusions,
                service_environment=service_environment,
            )
        )
        if surface_ref:
            rendered_refs.add(surface_ref)
    return _dedupe_adjacent_messages(content)


def _surface_index(
    surfaces: Sequence[Tuple[str, Dict[str, Any]]],
) -> Dict[str, Tuple[str, Dict[str, Any]]]:
    index: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for surface_type, surface in surfaces or []:
        refs = [surface.get("surface_ref")]
        full = surface.get("full_result") if isinstance(surface.get("full_result"), dict) else {}
        refs.extend([full.get("presentation_ref"), full.get("order_summary_ref"), full.get("payment_request_ref")])
        for ref in refs:
            key = str(ref or "").strip()
            if key:
                index[key] = (surface_type, surface)
    return index


def _composer_owned_choice_surface(
    surface: Dict[str, Any],
) -> Dict[str, Any]:
    """Expose an auxiliary choice surface through its presentation ref."""

    output = deepcopy(surface)
    output["surface_ref"] = str(
        output.get("surface_ref")
        or output.get("presentation_ref")
        or ""
    ).strip()
    return output


def _surface_to_content(
    surface_type: str,
    surface: Dict[str, Any],
    *,
    include_product_inclusions: bool = True,
    service_environment: str | None = None,
) -> List[Dict[str, Any]]:
    if surface_type == "location_choice":
        return _location_choice_messages(
            surface,
            service_environment=service_environment,
        )
    if surface_type == "checkout_choice":
        return _checkout_choice_messages(
            surface,
            service_environment=service_environment,
        )
    if (
        surface_type == "service"
        and surface.get("qualification_notice_only")
    ):
        return _text_messages_from_text(
            "Wala pa akong confirmed installation option for the requested "
            "area and order. Pili muna tayo ng tire, then I can recheck the "
            "service options that apply."
        )
    if surface_type == "payment":
        return _payment_surface_to_content(surface)
    if surface_type == "promo":
        return _promo_surface_to_content(surface, service_environment=service_environment)
    if surface_type == "product":
        return _product_surface_to_content(
            surface,
            include_inclusions=include_product_inclusions,
            service_environment=service_environment,
        )
    if (
        surface_type == "service"
        and str(surface.get("tool") or "") == "find_installation_slots"
    ):
        schedule_surface = build_schedule_choice_surface(
            surface.get("full_result")
            if isinstance(surface.get("full_result"), dict)
            else {}
        )
        if schedule_surface:
            return _schedule_choice_messages(
                schedule_surface,
                service_environment=service_environment,
            )
    body = _render_runtime_surface_body(surface_type, surface).strip()
    if surface_type == "order":
        return _order_surface_to_content(body)
    return _text_messages_from_text(body) if body else []


def _promo_surface_to_content(
    surface: Dict[str, Any],
    *,
    service_environment: str | None = None,
) -> List[Dict[str, Any]]:
    """Render only immutable reviewed promo card definitions."""

    elements: List[Dict[str, Any]] = []
    for stored in surface.get("cards") or []:
        if not isinstance(stored, dict):
            continue
        image_url = str(stored.get("image_url") or "").strip()
        title = str(stored.get("title") or "").strip()
        if not title or not image_url.startswith("https://storage.googleapis.com/") or "?" in image_url:
            continue
        buttons = []
        for stored_button in stored.get("buttons") or []:
            if not isinstance(stored_button, dict):
                continue
            caption = str(stored_button.get("caption") or "").strip()
            target = _promo_button_target(
                stored_button,
                service_environment=service_environment,
            )
            if not caption or len(caption) > 20 or not target:
                continue
            button = {
                "type": "flow",
                "caption": caption,
                "target": target,
            }
            click_action = _promo_button_click_action(stored_button)
            if not click_action:
                continue
            button["actions"] = [click_action]
            buttons.append(button)
        if not buttons:
            continue
        elements.append(
            {
                "title": title[:80],
                "subtitle": str(stored.get("subtitle") or "").strip()[:80],
                "image_url": image_url,
                "buttons": buttons[:3],
            }
        )
        if len(elements) >= 8:
            break
    if not elements:
        return []
    return [{"type": "cards", "elements": elements, "image_aspect_ratio": "square"}]


def _promo_button_click_action(stored_button: Dict[str, Any]) -> Dict[str, Any]:
    """Collapse legacy multi-field buttons into one catalog click token."""

    actions = [action for action in stored_button.get("actions") or [] if isinstance(action, dict)]
    fields = {
        str(action.get("field_name") or "").strip(): action.get("value")
        for action in actions
        if str(action.get("action") or "").strip() == "set_field_value"
    }
    selected_value = str(fields.get("promo_selected_id") or "").strip()
    try:
        parsed = parse_promo_click_token(selected_value)
        if parsed:
            token = build_promo_click_token(**parsed)
        else:
            token = build_promo_click_token(
                catalog_version_id=str(fields.get("promo_catalog_version") or ""),
                promo_id=selected_value,
                card_id=str(fields.get("promo_selected_card_id") or ""),
                action=str(stored_button.get("action") or fields.get("promo_selected_action") or ""),
                selected_brand=str(stored_button.get("selected_brand") or fields.get("promo_selected_brand") or ""),
            )
    except ValueError:
        return {}
    return {
        "action": "set_field_value",
        "field_name": "promo_selected_id",
        "value": token,
    }


def _promo_button_target(
    stored_button: Dict[str, Any],
    *,
    service_environment: str | None = None,
) -> str:
    """Resolve a prepublished router target for the current deployment only."""

    environment = str(service_environment or os.getenv("SERVICE_ENVIRONMENT") or "").strip().casefold()
    if environment in {"staging", "stage", "test", "development", "dev"}:
        target_environment = "staging"
    elif environment in {"live", "prod", "production", "shadow", "vm"}:
        target_environment = "live"
    else:
        target_environment = ""
    targets = stored_button.get("targets") if isinstance(stored_button.get("targets"), dict) else {}
    if target_environment:
        return str(targets.get(target_environment) or stored_button.get("target") or "").strip()
    return str(stored_button.get("target") or "").strip()


def _promo_presentation_metadata(
    surfaces: Sequence[Tuple[str, Dict[str, Any]]],
) -> Dict[str, Any]:
    for surface_type, surface in reversed(list(surfaces or [])):
        if surface_type != "promo":
            continue
        full = surface.get("full_result") if isinstance(surface.get("full_result"), dict) else {}
        return {
            "catalog_version_id": str(full.get("catalog_version_id") or ""),
            "presentation_ref": str(full.get("presentation_ref") or ""),
            "promo_refs": list(full.get("promo_refs") or [])[:8],
            "promo_ids": list(full.get("promo_ids") or [])[:8],
            "card_refs": list(full.get("card_refs") or [])[:8],
            "trigger_mode": str(full.get("trigger_mode") or ""),
            "explicit_redisplay": full.get("explicit_redisplay") is True,
            "selection_fingerprint": str(full.get("selection_fingerprint") or ""),
            "show_count": max(1, int(full.get("show_count") or 1)),
        }
    return {}


def _product_presentation_metadata(
    surfaces: Sequence[Tuple[str, Dict[str, Any]]],
    *,
    include_product_inclusions: bool = True,
) -> List[Dict[str, Any]]:
    """Return exact structured product cards rendered in this channel turn."""

    presentations: List[Dict[str, Any]] = []
    seen = set()
    card_keys = (
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
        "promo_label",
        "pricing_facts",
        "quantity",
        "pricing_basis",
        "installment_text",
        "origin",
        "dot",
        "warranty",
        "tire_protection_plan",
        "inclusions",
        "url",
        "image_url",
    )
    for surface_type, surface in surfaces or []:
        if surface_type != "product":
            continue
        full = surface.get("full_result") if isinstance(surface.get("full_result"), dict) else {}
        cards = []
        commercial_fingerprints = []
        for card in surface.get("cards") or []:
            if not isinstance(card, dict):
                continue
            compact = {key: card.get(key) for key in card_keys if card.get(key) not in (None, "", [], {})}
            if compact:
                cards.append(compact)
                commercial_fingerprints.append(
                    _product_card_commercial_fingerprint(card)
                )
        if not cards:
            continue
        presentation_ref = str(
            full.get("presentation_ref")
            or surface.get("presentation_ref")
            or "product_presentation_" + str(cards[0].get("card_ref") or cards[0].get("item_ref") or "unknown")
        )
        fingerprint = (presentation_ref, tuple(str(card.get("card_ref") or card.get("item_ref") or "") for card in cards))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        presentation = {
            "presentation_ref": presentation_ref,
            "observation_ref": str(full.get("observation_ref") or surface.get("observation_ref") or ""),
            "tool": str(surface.get("tool") or ""),
            "cards": cards[:8],
            "commercial_fingerprints": commercial_fingerprints[:8],
            "renderer_variant": (
                "manychat_product_price_list_gallery_v2"
                if surface.get("_gallery_included")
                else "manychat_product_text_only_v1"
            ),
            "price_list_included": bool(surface.get("_price_list_included")),
            "gallery_included": bool(surface.get("_gallery_included")),
        }
        if include_product_inclusions:
            inclusions_text = _product_inclusions_spiel(
                [card for card in surface.get("cards") or [] if isinstance(card, dict)],
                service_type=_surface_service_type(surface, full),
            )
            if inclusions_text:
                presentation["inclusions_text"] = inclusions_text
        presentations.append(presentation)
    return presentations[-3:]


def _choice_presentation_metadata(
    surfaces: Sequence[Tuple[str, Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Return deterministic category-choice impressions for session tracking."""

    output: List[Dict[str, Any]] = []
    for surface_type, surface in surfaces or []:
        if surface_type != "product" or str(surface.get("tool") or "") != "discover_brand_buckets":
            continue
        full = surface.get("full_result") if isinstance(surface.get("full_result"), dict) else {}
        query_basis = full.get("query_basis") if isinstance(full.get("query_basis"), dict) else {}
        filters = query_basis.get("normalized_filters") if isinstance(query_basis.get("normalized_filters"), dict) else {}
        choices = []
        for card in surface.get("cards") or []:
            if not isinstance(card, dict):
                continue
            choices.append(
                {
                    "choice_ref": str(card.get("choice_ref") or ""),
                    "category": str(card.get("bucket") or ""),
                    "label": str(card.get("label") or ""),
                    "position": int(card.get("position") or len(choices) + 1),
                    "brand_count": int(card.get("brand_count") or 0),
                    "product_count": int(card.get("product_count") or 0),
                }
            )
        if choices:
            output.append(
                {
                    "presentation_ref": str(full.get("presentation_ref") or ""),
                    "surface_type": "price_category_choices",
                    "choice_type": "price_category",
                    "choices": choices,
                    "tire_size": _tire_size_from_filters(filters),
                    "renderer_variant": "manychat_category_cards_v1",
                }
            )
    return output[-3:]


def _product_choice_presentation_metadata(
    surfaces: Sequence[Tuple[str, Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Return the trusted product-card allowlist shown as explicit buttons."""

    output: List[Dict[str, Any]] = []
    for surface_type, surface in surfaces or []:
        if surface_type != "product" or str(surface.get("tool") or "") not in {
            "product_search",
            "get_product_details",
        }:
            continue
        full = surface.get("full_result") if isinstance(surface.get("full_result"), dict) else {}
        presentation_ref = str(
            full.get("presentation_ref") or surface.get("presentation_ref") or ""
        ).strip()
        observation_ref = str(
            full.get("observation_ref") or surface.get("observation_ref") or ""
        ).strip()
        choices = []
        for position, card in enumerate(surface.get("cards") or [], start=1):
            if not isinstance(card, dict):
                continue
            card_ref = str(card.get("card_ref") or "").strip()
            if not card_ref or not _trusted_product_image_url(card.get("image_url")):
                continue
            choices.append(
                {
                    "choice_ref": f"product:{card_ref}",
                    "card_ref": card_ref,
                    "item_ref": str(card.get("item_ref") or ""),
                    "product_id": str(card.get("product_id") or ""),
                    "slug": str(card.get("slug") or ""),
                    "label": str(card.get("sku_model") or card.get("brand") or ""),
                    "brand": str(card.get("brand") or ""),
                    "tire_size": str(card.get("tire_size") or ""),
                    "deal_price_line": str(card.get("deal_price_line") or ""),
                    "position": position,
                }
            )
        if presentation_ref and choices:
            output.append(
                {
                    "presentation_ref": presentation_ref,
                    "observation_ref": observation_ref,
                    "surface_type": "product_choices",
                    "choice_type": "product_selection",
                    "choices": choices,
                    "renderer_variant": "manychat_product_choice_cards_v1",
                }
            )
    return output[-3:]


def _location_choice_presentation_metadata(surface: Dict[str, Any]) -> Dict[str, Any]:
    """Return the exact source-backed location options shown to the customer."""

    choices = []
    for position, item in enumerate(surface.get("choices") or [], start=1):
        if not isinstance(item, dict):
            continue
        choices.append(
            {
                "choice_ref": str(item.get("choice_ref") or ""),
                "code": str(item.get("code") or ""),
                "label": str(item.get("label") or ""),
                "position": position,
                "partner_count": int(item.get("partner_count") or 0),
                "province_code": str(item.get("province_code") or ""),
                "province_label": str(item.get("province_label") or ""),
                "serviceability_status": str(item.get("serviceability_status") or ""),
                "earliest_slot_preview": deepcopy(
                    item.get("earliest_slot_preview") or {}
                ),
            }
        )
    if not choices:
        return {}
    return {
        "presentation_ref": str(surface.get("presentation_ref") or ""),
        "surface_type": str(surface.get("surface_type") or ""),
        "choice_type": str(surface.get("choice_type") or ""),
        "level": str(surface.get("level") or ""),
        "parent_code": str(surface.get("parent_code") or ""),
        "parent_label": str(surface.get("parent_label") or ""),
        "choices": choices,
        "source": str(surface.get("source") or ""),
        "source_paths": list(surface.get("source_paths") or []),
        "source_version": str(surface.get("source_version") or ""),
        "freshness_ttl_seconds": int(surface.get("freshness_ttl_seconds") or 0),
        "renderer_variant": str(surface.get("renderer_variant") or ""),
    }


def _schedule_choice_presentation_metadata(
    surfaces: Sequence[Tuple[str, Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Return exact schedule controls shown from one trusted observation."""

    output: List[Dict[str, Any]] = []
    for surface_type, surface in surfaces or []:
        if (
            surface_type != "service"
            or str(surface.get("tool") or "") != "find_installation_slots"
        ):
            continue
        full = (
            surface.get("full_result")
            if isinstance(surface.get("full_result"), dict)
            else {}
        )
        schedule = build_schedule_choice_surface(full)
        if schedule:
            output.append(schedule)
    return output[-3:]


def _checkout_choice_presentation_metadata(
    surface: Dict[str, Any],
) -> Dict[str, Any]:
    """Return the API-backed checkout choices delivered to the customer."""

    choices = [
        deepcopy(item)
        for item in surface.get("choices") or []
        if isinstance(item, dict) and str(item.get("choice_ref") or "").strip()
    ]
    if not choices:
        return {}
    return {
        "presentation_ref": str(surface.get("presentation_ref") or ""),
        "surface_type": str(surface.get("surface_type") or ""),
        "choice_type": str(surface.get("choice_type") or ""),
        "choices": choices[:20],
        "source": str(surface.get("source") or ""),
        "quote_ref": str(surface.get("quote_ref") or ""),
        "payment_option": str(surface.get("payment_option") or ""),
        "payment_option_id": str(surface.get("payment_option_id") or ""),
        "service_path": str(surface.get("service_path") or ""),
        "product_brand": str(surface.get("product_brand") or ""),
        "renderer_variant": str(surface.get("renderer_variant") or ""),
    }


def _promo_contact_actions(
    presentation: Dict[str, Any],
    profile_fields: Dict[str, Any],
) -> List[Dict[str, Any]]:
    action_mirror = profile_fields.get("_promo_action_mirror")
    if isinstance(action_mirror, dict):
        return _promo_action_contact_actions(action_mirror)
    if not presentation:
        return []
    try:
        show_count = int(presentation.get("show_count") or 0)
    except (TypeError, ValueError):
        show_count = 0
    if show_count <= 0:
        try:
            show_count = int(profile_fields.get("promo_gallery_show_count") or 0) + 1
        except (TypeError, ValueError):
            show_count = 1
    promo_ids = ",".join(str(value) for value in presentation.get("promo_ids") or [])[:255]
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    values = [
        ("promo_catalog_version", presentation.get("catalog_version_id") or ""),
        ("promo_gallery_shown", True),
        ("promo_gallery_last_shown_at", timestamp),
        ("promo_gallery_show_count", show_count),
        ("promo_gallery_promo_ids", promo_ids),
    ]
    return [
        {"action": "set_field_value", "field_name": field_name, "value": value}
        for field_name, value in values
    ]


def _promo_action_contact_actions(action_mirror: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Mirror normalized click identity after the router submits one token."""

    values = [
        ("promo_selected_id", action_mirror.get("promo_id")),
        ("promo_selected_card_id", action_mirror.get("card_id")),
        ("promo_selected_action", action_mirror.get("action")),
    ]
    selected_brand = str(action_mirror.get("selected_brand") or "").strip()
    if selected_brand:
        values.append(("promo_selected_brand", selected_brand))
    values.append(("promo_source", "manychat_router_flow"))
    if len(values) < 5:
        values.append(("chatbot_state", "promo_action"))
    return [
        {"action": "set_field_value", "field_name": field_name, "value": value}
        for field_name, value in values[:5]
        if value not in (None, "")
    ]


def _choice_contact_actions(
    presentations: Sequence[Dict[str, Any]],
    profile_fields: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Mirror only the latest category impression or selection to ManyChat."""

    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    selected_type = str(profile_fields.get("discovery_choice_type") or "").strip()
    selected_value = str(profile_fields.get("discovery_choice_value") or "").strip()
    if selected_type and selected_value:
        values = [
            ("discovery_surface_type", profile_fields.get("discovery_surface_type") or "price_category_choices"),
            ("discovery_surface_ref", profile_fields.get("discovery_surface_ref") or ""),
            ("discovery_choice_type", selected_type),
            ("discovery_choice_value", selected_value),
            ("discovery_choice_selected_at", profile_fields.get("discovery_choice_selected_at") or timestamp),
        ]
    elif presentations:
        latest = presentations[-1]
        values = [
            ("discovery_surface_type", latest.get("surface_type") or "price_category_choices"),
            ("discovery_surface_ref", latest.get("presentation_ref") or ""),
            ("discovery_surface_shown_at", timestamp),
        ]
    else:
        return []
    return [
        {"action": "set_field_value", "field_name": name, "value": value}
        for name, value in values
        if value not in (None, "")
    ][:5]
def _product_surface_to_content(
    surface: Dict[str, Any],
    *,
    include_inclusions: bool = True,
    service_environment: str | None = None,
) -> List[Dict[str, Any]]:
    tool = str(surface.get("tool") or "")
    full_result = surface.get("full_result") if isinstance(surface.get("full_result"), dict) else {}
    cards = [card for card in surface.get("cards") or [] if isinstance(card, dict)]
    messages: List[Dict[str, Any]] = []
    if tool == "discover_brand_buckets":
        category_message = _price_category_cards_message(
            surface,
            service_environment=service_environment,
        )
        return [category_message] if category_message else []
    if tool in {"product_search", "get_product_details"}:
        surface["_product_surface_rendered"] = True
        match_scope_notice = (
            _provider_owned_product_match_scope_notice(full_result)
            if tool == "product_search"
            else ""
        )
        choice_message = _product_selection_cards_message(
            surface,
            service_environment=service_environment,
        )
        card_texts = [
            _approved_product_price_list_card(card)
            for card in cards
            if _approved_product_price_list_card(card)
        ]
        card_block = "\n\n".join(card_texts).strip()
        suppress_repeated_price_list = bool(
            surface.get("_suppress_repeated_price_list")
        )
        surface["_price_list_included"] = bool(
            card_block and not suppress_repeated_price_list
        )
        surface["_gallery_included"] = bool(choice_message)
        if match_scope_notice:
            messages.append({"type": "text", "text": match_scope_notice})
        if surface["_price_list_included"]:
            messages.append({"type": "text", "text": card_block})
        if choice_message:
            messages.append(choice_message)
        if include_inclusions:
            inclusions = _product_inclusions_spiel(cards, service_type=_surface_service_type(surface, full_result))
            if inclusions:
                messages.append({"type": "text", "text": inclusions})
        return messages
    body = _render_runtime_surface_body("product", surface).strip()
    return _grouped_text_messages(body)


def _product_selection_cards_message(
    surface: Dict[str, Any],
    *,
    service_environment: str | None,
) -> Dict[str, Any]:
    """Render exact product refs as compact, source-backed selection buttons."""

    full = surface.get("full_result") if isinstance(surface.get("full_result"), dict) else {}
    presentation_ref = str(
        full.get("presentation_ref") or surface.get("presentation_ref") or ""
    ).strip()
    target = _choice_router_target(service_environment)
    if not presentation_ref or not target:
        return {}
    selectable_cards = [
        card
        for card in surface.get("cards") or []
        if isinstance(card, dict)
        and str(card.get("card_ref") or "").strip()
        and _trusted_product_image_url(card.get("image_url"))
    ]
    elements: List[Dict[str, Any]] = []
    for card in selectable_cards:
        card_ref = str(card.get("card_ref") or "").strip()
        title = str(card.get("sku_model") or card.get("brand") or "").strip()
        if not card_ref or not title:
            continue
        try:
            token = build_product_choice_token(
                presentation_ref=presentation_ref,
                card_ref=card_ref,
            )
        except ValueError:
            continue
        subtitle = _product_gallery_subtitle(card)
        element = {
            "title": title[:80],
            "subtitle": subtitle[:80],
            "buttons": [
                {
                    "type": "flow",
                    "caption": _product_choice_caption(title),
                    "target": target,
                    "actions": [
                        {
                            "action": "set_field_value",
                            "field_name": "promo_selected_id",
                            "value": token,
                        }
                    ],
                }
            ],
        }
        element["image_url"] = _trusted_product_image_url(card.get("image_url"))
        elements.append(element)
    if not elements:
        return {}
    return {"type": "cards", "elements": elements[:8], "image_aspect_ratio": "square"}


def _approved_product_price_list_card(card: Dict[str, Any]) -> str:
    """Render the provider-owned detailed pricelist beside its visual card.

    Rebuild the approved detailed template from the structured commercial
    facts used for presentation metadata. ``card_text`` is only a non-authority
    fallback for category or price when structured fields are unavailable.
    """

    title = str(card.get("sku_model") or card.get("brand") or "").strip()
    if not title:
        return ""
    source_lines = [
        line.strip()
        for line in str(card.get("card_text") or "").splitlines()
        if line.strip()
    ]
    category = str(card.get("category") or "").strip().upper()
    if not category and source_lines:
        match = re.match(r"^\[([^\]]+)\]$", source_lines[0])
        category = match.group(1).strip().upper() if match else ""
    pricing_facts = (
        card.get("pricing_facts")
        if isinstance(card.get("pricing_facts"), dict)
        else {}
    )
    has_structured_price = any(
        _float_or_none(pricing_facts.get(key)) is not None
        for key in ("unit_price", "payable_total")
    )
    deal = (
        _product_gallery_subtitle(card).splitlines()[0].strip()
        if has_structured_price
        else ""
    )
    if not deal:
        deal = str(card.get("deal_price_line") or "").strip()
    if not deal:
        deal = next(
            (
                line
                for line in source_lines
                if ("PHP " in line or "₱" in line)
                and not re.search(r"https?://", line, flags=re.IGNORECASE)
            ),
            "",
        )
    deal = re.sub(r"^\s*💰\s*", "", deal)
    promo = str(card.get("promo_savings_line") or "").strip()
    installment = str(card.get("installment_text") or "").strip()
    origin = str(card.get("origin") or "").strip()
    dot = str(card.get("dot") or "").strip()
    warranty_parts = [
        str(card.get(key) or "").strip()
        for key in ("warranty", "tire_protection_plan")
        if str(card.get(key) or "").strip()
    ]
    url = str(card.get("url") or "").strip()
    lines = [
        f"[{category}]" if category else "",
        f"🛞 {title}",
        f"💰 {deal}" if deal else "",
        f"🎁 {promo}" if promo else "",
        f"💳 {installment}" if installment else "",
        f"Origin: {origin}" if origin else "",
        f"🗓️ DOT: {dot}" if dot else "",
        f"Warranty: {' + '.join(warranty_parts)}" if warranty_parts else "",
        f"🔗 {url}" if url else "",
    ]
    return "\n".join(line for line in lines if line).strip()


def _product_gallery_subtitle(card: Dict[str, Any]) -> str:
    """Return complete compact pricing facts without cutting a claim mid-phrase."""

    facts = card.get("pricing_facts") if isinstance(card.get("pricing_facts"), dict) else {}
    quantity = max(1, _int_or_default(facts.get("quantity") or card.get("quantity"), 1))
    unit_price = _float_or_none(facts.get("unit_price"))
    payable_total = _float_or_none(facts.get("payable_total"))
    parts: List[str] = []
    if unit_price is not None:
        parts.append(f"PHP {unit_price:,.2f}/tire")
    if payable_total is not None:
        noun = "tire" if quantity == 1 else "tires"
        parts.append(f"{quantity} {noun}: PHP {payable_total:,.2f}")
    if not parts:
        price = str(card.get("deal_price_line") or "").strip()
        if price:
            parts.append(price)
    subtitle = " | ".join(parts) or "Current product option"
    promo = _compact_product_promo_label(card.get("promo_savings_line"))
    if promo and len(subtitle) + len(promo) + 1 <= 80:
        subtitle = f"{subtitle}\n{promo}"
    return subtitle[:80]


def _compact_product_promo_label(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    if re.search(r"\bbuy\s*3\s*(?:get|\+)\s*1\s*free\b", text, flags=re.IGNORECASE):
        return "Buy 3 Get 1 FREE"
    bundle = re.search(r"\bbundle:\s*save\s+PHP\s*[\d,]+(?:\.\d{1,2})?", text, flags=re.IGNORECASE)
    if bundle:
        return bundle.group(0)
    savings = re.search(r"\bsave\s+PHP\s*[\d,]+(?:\.\d{1,2})?", text, flags=re.IGNORECASE)
    if savings:
        return savings.group(0)
    discount = re.search(r"PHP\s*[\d,]+(?:\.\d{1,2})?\s*off/tire", text, flags=re.IGNORECASE)
    return discount.group(0) if discount else ""


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _trusted_product_image_url(value: Any) -> str:
    """Return only stable product-image hosts already authorized by the catalog."""

    url = str(value or "").strip()
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme.casefold() != "https" or parsed.username or parsed.password:
        return ""
    host = str(parsed.hostname or "").strip().casefold()
    if host not in {
        "gulong-ph.sgp1.digitaloceanspaces.com",
        "gulongph.sgp1.digitaloceanspaces.com",
        "storage.googleapis.com",
    }:
        return ""
    return url


def _schedule_choice_messages(
    surface: Dict[str, Any],
    *,
    service_environment: str | None,
) -> List[Dict[str, Any]]:
    """Render one schedule card per day with bounded, validated actions."""

    target = _choice_router_target(service_environment)
    presentation_ref = str(surface.get("presentation_ref") or "").strip()
    if not target or not presentation_ref:
        return []
    elements: List[Dict[str, Any]] = []
    for day in surface.get("days") or []:
        if not isinstance(day, dict):
            continue
        buttons: List[Dict[str, Any]] = []
        for choice in day.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            choice_ref = str(choice.get("choice_ref") or "").strip()
            label = str(choice.get("label") or "").strip()
            if not choice_ref or not label:
                continue
            try:
                token = build_schedule_choice_token(
                    presentation_ref=presentation_ref,
                    choice_ref=choice_ref,
                )
            except ValueError:
                continue
            caption = (
                "Anytime in afternoon"
                if choice.get("selection_kind") == "afternoon_preference"
                else label
            )
            buttons.append(
                {
                    "type": "flow",
                    "caption": caption[:20],
                    "target": target,
                    "actions": [
                        {
                            "action": "set_field_value",
                            "field_name": "promo_selected_id",
                            "value": token,
                        }
                    ],
                }
            )
        if not buttons:
            continue
        elements.append(
            {
                "title": str(day.get("title") or day.get("date") or "Schedule")[:80],
                "subtitle": str(day.get("subtitle") or "Current schedule options")[:80],
                "buttons": buttons[:3],
            }
        )
    if not elements:
        return []
    messages: List[Dict[str, Any]] = [
        {
            "type": "cards",
            "elements": elements[:10],
            "image_aspect_ratio": "horizontal",
        }
    ]
    policy_notes = [
        str(note.get("text") or "").strip()
        for note in (
            (surface.get("service_policy_notes") or [])
            if isinstance(surface.get("service_policy_notes"), list)
            else []
        )
        if isinstance(note, dict) and str(note.get("text") or "").strip()
    ]
    if policy_notes:
        messages.extend(_text_messages_from_text("\n\n".join(policy_notes)))
    return messages


def _checkout_choice_messages(
    surface: Dict[str, Any],
    *,
    service_environment: str | None,
) -> List[Dict[str, Any]]:
    """Render exact validated payment controls without connective prose."""

    if not surface:
        return []
    target = _choice_router_target(service_environment)
    presentation_ref = str(surface.get("presentation_ref") or "").strip()
    surface_type = str(surface.get("surface_type") or "").strip()
    if not target or not presentation_ref:
        return []
    if surface_type == "payment_option_choices":
        token_builder = build_payment_option_choice_token
    elif surface_type == "payment_method_choices":
        token_builder = build_payment_method_choice_token
    else:
        return []

    elements: List[Dict[str, Any]] = []
    for choice in surface.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        choice_ref = str(choice.get("choice_ref") or "").strip()
        label = str(choice.get("label") or "").strip()
        if not choice_ref or not label:
            continue
        try:
            token = token_builder(
                presentation_ref=presentation_ref,
                choice_ref=choice_ref,
            )
        except ValueError:
            continue
        subtitle = str(
            choice.get("subtitle")
            or choice.get("description")
            or "Available for the current checkout"
        ).strip()
        elements.append(
            {
                "title": label[:80],
                "subtitle": subtitle[:80],
                "buttons": [
                    {
                        "type": "flow",
                        "caption": _compact_choice_caption(label),
                        "target": target,
                        "actions": [
                            {
                                "action": "set_field_value",
                                "field_name": "promo_selected_id",
                                "value": token,
                            }
                        ],
                    }
                ],
            }
        )
    card_messages = [
        {
            "type": "cards",
            "elements": elements[index : index + 10],
            "image_aspect_ratio": "horizontal",
        }
        for index in range(0, len(elements), 10)
        if elements[index : index + 10]
    ]
    return card_messages


def _product_choice_caption(title: str) -> str:
    """Keep the clicked product identifiable in the visible transcript."""

    without_size = re.sub(
        r"\b\d{3}\s*/\s*\d{2}\s*/?\s*(?:Z?R)?\s*\d{2}\b",
        "",
        str(title or ""),
        flags=re.IGNORECASE,
    )
    return _compact_choice_caption(without_size or title, fallback="Select tire")


def _compact_choice_caption(label: str, *, fallback: str = "Select") -> str:
    """Build an audit-readable ManyChat caption within its 20-char limit."""

    compact = " ".join(str(label or "").split())
    compact = re.sub(r"\bPayMaya\b", "Maya", compact, flags=re.IGNORECASE)
    compact = re.sub(
        r"\s*\(\s*0%\s*interest\s*\)",
        " 0%",
        compact,
        flags=re.IGNORECASE,
    )
    compact = re.sub(r"\bInstallment\b", "", compact, flags=re.IGNORECASE)
    compact = " ".join(compact.split()).strip(" -/") or fallback
    if len(compact) <= 20:
        return compact
    if compact[20:21].isspace():
        return compact[:20].strip(" -/")
    shortened = compact[:20].rsplit(" ", 1)[0].strip(" -/")
    return shortened or compact[:20]


def _price_category_cards_message(
    surface: Dict[str, Any],
    *,
    service_environment: str | None,
) -> Dict[str, Any]:
    """Render four low-effort, tracked category choices as one gallery."""

    full = surface.get("full_result") if isinstance(surface.get("full_result"), dict) else {}
    query_basis = full.get("query_basis") if isinstance(full.get("query_basis"), dict) else {}
    filters = query_basis.get("normalized_filters") if isinstance(query_basis.get("normalized_filters"), dict) else {}
    presentation_ref = str(full.get("presentation_ref") or "").strip()
    target = _choice_router_target(service_environment)
    if not presentation_ref or not target:
        return {}
    width = str(filters.get("section_width") or "").strip()
    aspect = str(filters.get("aspect_ratio") or "").strip()
    rim = str(filters.get("rim_size") or "").strip()
    elements = []
    for card in surface.get("cards") or []:
        if not isinstance(card, dict):
            continue
        label = str(card.get("label") or "").strip()
        category = str(card.get("bucket") or "").strip()
        if not label or not category:
            continue
        try:
            token = build_price_category_token(
                presentation_ref=presentation_ref,
                category=category,
                section_width=width,
                aspect_ratio=aspect,
                rim_size=rim,
            )
        except ValueError:
            continue
        min_price = str(card.get("min_price_text") or "").strip()
        max_price = str(card.get("max_price_text") or "").strip()
        price_text = f"{min_price} - {max_price} per tire" if min_price and max_price else "Current exact-size options"
        brand_count = int(card.get("brand_count") or len(card.get("brands") or []))
        product_count = int(card.get("product_count") or 0)
        subtitle_parts = [price_text, f"{brand_count} brands | {product_count} options"]
        subtitle = _fit_category_subtitle(
            subtitle_parts,
            [str(value).strip() for value in (card.get("brands") or [])[:3] if str(value).strip()],
        )
        elements.append(
            {
                "title": label[:80],
                "subtitle": subtitle,
                "buttons": [
                    {
                        "type": "flow",
                        "caption": f"Choose {label}"[:20],
                        "target": target,
                        "actions": [
                            {
                                "action": "set_field_value",
                                "field_name": "promo_selected_id",
                                "value": token,
                            }
                        ],
                    }
                ],
            }
        )
    if not elements:
        return {}
    return {"type": "cards", "elements": elements[:4], "image_aspect_ratio": "horizontal"}


def _location_choice_messages(
    surface: Dict[str, Any],
    *,
    service_environment: str | None,
) -> List[Dict[str, Any]]:
    """Render serviceable locations, splitting galleries at Messenger's limit."""

    if not surface:
        return []
    target = _choice_router_target(service_environment)
    presentation_ref = str(surface.get("presentation_ref") or "").strip()
    level = str(surface.get("level") or "").strip().casefold()
    parent_code = str(surface.get("parent_code") or "").strip()
    if not target or not presentation_ref or not level or not parent_code:
        return []
    elements: List[Dict[str, Any]] = []
    for item in surface.get("choices") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        label = str(item.get("label") or "").strip()
        if not code or not label:
            continue
        try:
            token = build_location_choice_token(
                presentation_ref=presentation_ref,
                level=level,
                parent_code=parent_code,
                choice_code=code,
            )
        except ValueError:
            continue
        partner_count = int(item.get("partner_count") or 0)
        status = str(item.get("serviceability_status") or "")
        if status == "typed_location_required":
            subtitle = "Outside these areas? Check delivery options"
        else:
            suffix = "partner" if partner_count == 1 else "partners"
            preview = (
                item.get("earliest_slot_preview")
                if isinstance(item.get("earliest_slot_preview"), dict)
                else {}
            )
            preview_label = _city_slot_preview_label(preview)
            subtitle = (
                f"Earliest preview: {preview_label}"
                if preview_label
                else f"{partner_count} current installation {suffix}"
            )
        elements.append(
            {
                "title": label[:80],
                "subtitle": subtitle[:80],
                "buttons": [
                    {
                        "type": "flow",
                        "caption": f"Choose {label}"[:20],
                        "target": target,
                        "actions": [
                            {
                                "action": "set_field_value",
                                "field_name": "promo_selected_id",
                                "value": token,
                            }
                        ],
                    }
                ],
            }
        )
    return [
        {"type": "cards", "elements": elements[index : index + 10], "image_aspect_ratio": "horizontal"}
        for index in range(0, len(elements), 10)
        if elements[index : index + 10]
    ]


def _city_slot_preview_label(preview: Dict[str, Any]) -> str:
    """Format one city availability preview for a compact card subtitle."""

    date_text = str(preview.get("date") or "").strip()
    time_text = str(preview.get("time_text") or "").strip()
    friendly_date = date_text
    try:
        parsed = datetime.strptime(date_text, "%Y-%m-%d")
        friendly_date = (
            f"{parsed.strftime('%a, %b')} {parsed.day}"
        )
    except (TypeError, ValueError):
        pass
    return " - ".join(
        part for part in (friendly_date, time_text) if part
    )


def _fit_category_subtitle(lines: Sequence[str], brands: Sequence[str], *, limit: int = 80) -> str:
    """Add only complete representative brand names within ManyChat's limit."""

    base = "\n".join(str(line).strip() for line in lines if str(line).strip())
    selected: List[str] = []
    for brand in brands:
        candidate_brands = ", ".join([*selected, brand])
        candidate = f"{base}\n{candidate_brands}" if base else candidate_brands
        if len(candidate) > limit:
            break
        selected.append(brand)
    return f"{base}\n{', '.join(selected)}" if selected else base[:limit].rstrip(" ,")


def _choice_router_target(service_environment: str | None) -> str:
    environment = str(service_environment or os.getenv("SERVICE_ENVIRONMENT") or "").strip().casefold()
    if environment in {"staging", "stage", "test", "development", "dev"}:
        return str(
            os.getenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE")
            or os.getenv("PROMO_STAGING_ROUTER_FLOW_NAMESPACE")
            or ""
        ).strip()
    return str(
        os.getenv("PRICE_CATEGORY_LIVE_ROUTER_FLOW_NAMESPACE")
        or os.getenv("PROMO_LIVE_ROUTER_FLOW_NAMESPACE")
        or ""
    ).strip()


def _tire_size_from_filters(filters: Dict[str, Any]) -> str:
    width = str(filters.get("section_width") or "").strip()
    aspect = str(filters.get("aspect_ratio") or "").strip()
    rim = str(filters.get("rim_size") or "").strip().upper()
    return f"{width}/{aspect}{rim}" if width and aspect and rim else ""


def _payment_surface_to_content(surface: Dict[str, Any]) -> List[Dict[str, Any]]:
    full = surface.get("full_result") if isinstance(surface.get("full_result"), dict) else {}
    qr = full.get("qr_image") if isinstance(full.get("qr_image"), dict) else {}
    link = full.get("payment_link") if isinstance(full.get("payment_link"), dict) else {}
    qr_url = str(qr.get("url") or "").strip()
    messages: List[Dict[str, Any]] = []
    structured = _structured_payment_messages(full)
    if structured:
        messages.extend(structured)
        if qr_url:
            image_message = {
                "type": "image",
                "url": qr_url,
                "alt": str(qr.get("alt") or "Gulong.PH payment QR").strip(),
                "image_ref": str(qr.get("image_ref") or "img_payment_qr_gulong").strip(),
            }
            messages.insert(1 if len(messages) > 1 else len(messages), image_message)
        return messages
    else:
        body = str(full.get("payment_instruction_block") or _render_runtime_surface_body("payment", surface)).strip()
        if body:
            messages.extend(_grouped_text_messages(_remove_duplicate_qr_url(body, qr_url)))
    if qr_url:
        messages.append(
            {
                "type": "image",
                "url": qr_url,
                "alt": str(qr.get("alt") or "Gulong.PH payment QR").strip(),
                "image_ref": str(qr.get("image_ref") or "img_payment_qr_gulong").strip(),
            }
        )
    if link.get("url"):
        # The exact link stays in the runtime-rendered text body; metadata lets
        # the API response expose it for flow mapping without text scraping.
        pass
    return messages


def _structured_payment_messages(full: Dict[str, Any]) -> List[Dict[str, Any]]:
    order_id = str(full.get("order_id") or "").strip()
    amount_text = str(full.get("expected_amount_text") or "").strip()
    amount_breakdown = full.get("amount_breakdown") if isinstance(full.get("amount_breakdown"), dict) else {}
    subtotal_text = str(amount_breakdown.get("subtotal_before_pay_now_discount_text") or "").strip()
    discount_text = str(amount_breakdown.get("pay_now_discount_text") or "").strip()
    payment_stage = _payment_stage_label(full.get("payment_stage"))
    payment_link = full.get("payment_link") if isinstance(full.get("payment_link"), dict) else {}
    qr = full.get("qr_image") if isinstance(full.get("qr_image"), dict) else {}
    manual_details = [row for row in full.get("manual_details") or [] if isinstance(row, dict)]
    if not (order_id or amount_text or payment_link.get("url") or qr.get("url") or manual_details):
        return []

    messages: List[Dict[str, Any]] = []
    header = ["💳 Payment Request"]
    if order_id:
        header.append(f"Order: {order_id}")
    if amount_text:
        header.extend(["", f"Amount Due: {amount_text}"])
    if payment_stage:
        header.append(f"Payment: {payment_stage}")
    if subtotal_text or discount_text:
        header.append("")
        if subtotal_text:
            header.append(f"Product/Order Total: {subtotal_text}")
        if discount_text:
            header.append(f"Pay Now Discount: {discount_text}")
    if payment_link.get("url"):
        header.extend(["", "🔗 Primary Payment Link", str(payment_link.get("url")).strip()])
    if qr.get("url"):
        header.extend(["", "📷 Primary Payment QR", "Please scan the QR image below."])
    messages.append({"type": "text", "text": "\n".join(header).strip()})

    account_blocks: List[str] = []
    for row in manual_details:
        method = str(row.get("method") or "").strip()
        account_name = str(row.get("account_name") or "").strip()
        account_number = str(row.get("account_number") or "").strip()
        lines = [method]
        if account_name:
            lines.append(f"Account Name: {account_name}")
        if account_number:
            lines.append(f"Account Number: {account_number}")
        text = "\n".join(line for line in lines if line).strip()
        if text:
            account_blocks.append(text)
    if account_blocks:
        messages.append(
            {
                "type": "text",
                "text": "\n\n".join(
                    [
                        "🏦 Alternative Account Details",
                        "Use these if QR payment is not convenient.",
                        *account_blocks,
                    ]
                ).strip(),
            }
        )
    return messages


def _payment_stage_label(value: Any) -> str:
    return {
        "reservation_fee": "reservation fee",
        "balance_payment": "balance payment",
        "full_payment": "full payment",
    }.get(str(value or "").strip(), str(value or "").strip())


def _grouped_text_messages(text: str) -> List[Dict[str, Any]]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return []
    groups = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    if len(groups) <= 1:
        return _text_messages_from_text(cleaned)
    if len(groups[0].splitlines()) == 1 and len(groups) > 1:
        groups = [f"{groups[0]}\n\n{groups[1]}", *groups[2:]]
    return [{"type": "text", "text": group} for group in groups]


def _order_surface_to_content(text: str) -> List[Dict[str, Any]]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return []
    groups = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    if len(groups) <= 2:
        return _grouped_text_messages(cleaned)
    first = "\n\n".join(groups[:3]).strip()
    second = "\n\n".join(groups[3:]).strip()
    return [{"type": "text", "text": part} for part in [first, second] if part]


def _remove_duplicate_qr_url(text: str, qr_url: str) -> str:
    if not qr_url:
        return text
    kept: List[str] = []
    skip_next_url = False
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if skip_next_url and _same_url(stripped, qr_url):
            skip_next_url = False
            continue
        skip_next_url = False
        kept.append(line.rstrip())
        if "primary payment qr" in stripped.lower():
            skip_next_url = True
    return "\n".join(kept).strip()


def _same_url(value: str, expected: str) -> bool:
    return value.strip().rstrip("/") == expected.strip().rstrip("/")


def _image_message_from_content(content: Dict[str, Any]) -> Dict[str, Any]:
    url = str(content.get("url") or "").strip()
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        return {}
    return {
        "type": "image",
        "url": url,
        "alt": str(content.get("alt") or "Image").strip(),
        "image_ref": str(content.get("image_ref") or "").strip(),
    }


def _text_messages_from_text(text: str) -> List[Dict[str, Any]]:
    cleaned = _manychat_safe_plain_text(str(text or "")).strip()
    if not cleaned:
        return []
    return [{"type": "text", "text": cleaned}]


def _manychat_safe_plain_text(text: str) -> str:
    """Convert model-authored lightweight markup into ManyChat-safe text."""

    cleaned = str(text or "")
    if not cleaned.strip():
        return ""
    cleaned = re.sub(r"<\s*br\s*/?\s*>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<\s*li[^>]*>", "\n- ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<\s*/\s*li\s*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<\s*/\s*(?:p|div|ul|ol)\s*>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = re.sub(r"\*\*([^*\n][^*]*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_\n][^_]*?)__", r"\1", cleaned)
    lines: List[str] = []
    previous_blank = False
    for raw_line in cleaned.splitlines():
        line = raw_line.rstrip()
        line = re.sub(r"^\s*[*]\s+", "- ", line)
        line = re.sub(r"^\s*[-]\s{2,}", "- ", line)
        line = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"\1", line)
        if not line.strip():
            if not previous_blank:
                lines.append("")
            previous_blank = True
            continue
        lines.append(line.strip())
        previous_blank = False
    return "\n".join(lines).strip()


def _split_text_messages(messages: Sequence[Dict[str, Any]], *, max_chars: int) -> List[Dict[str, Any]]:
    limit = max(300, int(max_chars or DEFAULT_MAX_BUBBLE_CHARS))
    split: List[Dict[str, Any]] = []
    for message in messages or []:
        if str(message.get("type") or "") != "text":
            split.append(dict(message))
            continue
        for chunk in _split_text(str(message.get("text") or ""), limit):
            if chunk:
                split.append({"type": "text", "text": chunk})
    return split


def _split_text(text: str, max_chars: int) -> List[str]:
    text = str(text or "").strip()
    if len(text) <= max_chars:
        return [text] if text else []
    chunks: List[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(paragraph) <= max_chars:
            current = paragraph
            continue
        chunks.extend(_split_long_block(paragraph, max_chars))
    if current:
        chunks.append(current)
    return chunks


def _split_long_block(text: str, max_chars: int) -> List[str]:
    lines = [line.rstrip() for line in str(text or "").splitlines() if line.strip()]
    chunks: List[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}".strip() if current else line
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = line[:max_chars]
    if current:
        chunks.append(current)
    return chunks


def _messages_to_bubbles(messages: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    bubbles: Dict[str, str] = {}
    index = 1
    for message in messages or []:
        if str(message.get("type") or "") != "text":
            continue
        text = str(message.get("text") or "").strip()
        if not text:
            continue
        bubbles[f"bubble{index}"] = text
        index += 1
    return bubbles or {"bubble1": ""}


def _image_meta(message: Dict[str, Any]) -> Dict[str, str]:
    return {
        "url": str(message.get("url") or "").strip(),
        "alt": str(message.get("alt") or "").strip(),
        "image_ref": str(message.get("image_ref") or "").strip(),
    }


def _payment_metadata(surfaces: Sequence[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
    for surface_type, surface in surfaces or []:
        if surface_type != "payment":
            continue
        full = surface.get("full_result") if isinstance(surface.get("full_result"), dict) else {}
        qr = full.get("qr_image") if isinstance(full.get("qr_image"), dict) else {}
        link = full.get("payment_link") if isinstance(full.get("payment_link"), dict) else {}
        return {
            "payment_request_ref": full.get("payment_request_ref"),
            "order_id": full.get("order_id"),
            "payment_stage": full.get("payment_stage"),
            "expected_amount": full.get("expected_amount"),
            "expected_amount_text": full.get("expected_amount_text"),
            "primary_method": full.get("primary_method"),
            "payment_instruction_type": full.get("payment_instruction_type"),
            "qr_image_url": qr.get("url"),
            "payment_link_url": link.get("url"),
            "can_accept_payment_proof": full.get("can_accept_payment_proof"),
        }
    return {}


def _dedupe_adjacent_messages(messages: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    for message in messages or []:
        if not message:
            continue
        if deduped and _message_key(deduped[-1]) == _message_key(message):
            continue
        deduped.append(dict(message))
    return deduped


def _message_key(message: Dict[str, Any]) -> Tuple[str, str]:
    message_type = str(message.get("type") or "")
    if message_type == "image":
        return (message_type, str(message.get("url") or ""))
    if message_type == "cards":
        return (message_type, repr(message.get("elements") or []))
    return (message_type, re.sub(r"\s+", " ", str(message.get("text") or "")).strip())
