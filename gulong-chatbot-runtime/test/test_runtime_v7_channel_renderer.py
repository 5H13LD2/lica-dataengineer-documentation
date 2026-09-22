import json
import asyncio

import pytest

from runtime_v7.api_runtime import (
    RuntimeV7APIRequest,
    RuntimeV7APIService,
    _build_manychat_handoff_note,
    _extract_image_urls_from_text,
)
from runtime_v7.channel_renderer import RuntimeV7ChannelRender, render_turn_for_channel
from runtime_v7.runtime_harness import (
    FIRST_TURN_INTRO_MODE_WELCOME_ONLY,
    MODEL_COMPOSED_FIRST_TURN_OPENING_EVENT_TYPE,
    RUNTIME_V7_FIRST_TURN_INFO_REQUEST_TEXT,
    RUNTIME_V7_FIRST_TURN_INTRO_TEXT,
    RUNTIME_V7_FIRST_TURN_SIZE_GUIDE_TEXT,
    RUNTIME_V7_WELCOME_SPIEL_TEXT,
    WELCOME_SPIEL_GUARD_EVENT_TYPE,
)
from runtime_v7.transaction_choices import (
    build_payment_method_surface,
    build_payment_option_surface,
)
from runtime.gateways.analytics_gateway import MemoryAnalyticsGateway


def _payment_turn_record() -> dict:
    payment_result = {
        "status": "ok",
        "payment_request_ref": "payment_request_abc",
        "presentation_ref": "pres_payment_request_abc",
        "order_id": "35593",
        "payment_stage": "full_payment",
        "expected_amount": 5035.0,
        "expected_amount_text": "PHP 5,035.00",
        "primary_method": "qr",
        "payment_instruction_type": "qr_primary",
        "can_accept_payment_proof": True,
        "qr_image": {
            "image_ref": "img_payment_qr_gulong",
            "url": "https://storage.googleapis.com/gulong_chatbot_files/images/gulong_qr.png",
            "alt": "Gulong.PH payment QR",
        },
        "payment_link": {
            "url": "https://payments.example.test/request/35593",
        },
        "manual_details": [
            {
                "method": "BPI Bank Transfer",
                "account_name": "LICA AUTO GROUP",
                "account_number": "9671002072",
            }
        ],
        "payment_instruction_block": (
            "Payment details:\n"
            "Product/Order Total: PHP 5,035.00\n"
            "Primary Payment QR:\n"
            "https://storage.googleapis.com/gulong_chatbot_files/images/gulong_qr.png\n"
            "Account Name: LICA AUTO GROUP\n"
            "Account Number: 9671002072"
        ),
    }
    return {
        "assistant_text": json.dumps(
            {
                "response_units": [
                    {"type": "text", "content": {"text": "Placed na po yung order."}},
                    {"type": "render_surface", "content": {"surface_ref": "pres_payment_request_abc"}},
                    {
                        "type": "text",
                        "content": {"text": "Pakisend na lang po yung proof/reference after payment."},
                    },
                ]
            }
        ),
        "tool_results": [
            {
                "name": "prepare_payment_request",
                "round": 1,
                "result": {
                    "status": "ok",
                    "payment_request_ref": "payment_request_abc",
                    "presentation_ref": "pres_payment_request_abc",
                },
                "full_result": payment_result,
            }
        ],
    }


def test_channel_renderer_outputs_payment_qr_as_image_message():
    rendered = render_turn_for_channel(_payment_turn_record())

    image_messages = [message for message in rendered.content_messages if message.get("type") == "image"]
    text_messages = [message for message in rendered.content_messages if message.get("type") == "text"]

    assert image_messages == [
        {
            "type": "image",
            "url": "https://storage.googleapis.com/gulong_chatbot_files/images/gulong_qr.png",
            "alt": "Gulong.PH payment QR",
            "image_ref": "img_payment_qr_gulong",
        }
    ]
    assert rendered.images == [
        {
            "url": "https://storage.googleapis.com/gulong_chatbot_files/images/gulong_qr.png",
            "alt": "Gulong.PH payment QR",
            "image_ref": "img_payment_qr_gulong",
        }
    ]
    assert rendered.payment["payment_request_ref"] == "payment_request_abc"
    assert rendered.payment["qr_image_url"] == "https://storage.googleapis.com/gulong_chatbot_files/images/gulong_qr.png"
    assert all("storage.googleapis.com/gulong_chatbot_files/images/gulong_qr.png" not in message["text"] for message in text_messages)
    assert rendered.response["bubble1"] == "Placed na po yung order."
    assert any("Account Number: 9671002072" in message["text"] for message in text_messages)


def test_channel_renderer_splits_long_text_bubbles_without_moving_images():
    turn = _payment_turn_record()
    turn["assistant_text"] = json.dumps(
        {
            "response_units": [
                {"type": "text", "content": {"text": "A" * 650}},
                {"type": "render_surface", "content": {"surface_ref": "pres_payment_request_abc"}},
            ]
        }
    )

    rendered = render_turn_for_channel(turn, max_bubble_chars=300)

    assert any(message.get("type") == "image" for message in rendered.content_messages)
    assert all(
        len(message.get("text", "")) <= 300
        for message in rendered.content_messages
        if message.get("type") == "text"
    )
    assert len(rendered.response) >= 2


def test_channel_renderer_converts_model_markdown_to_plain_manychat_text():
    turn = {
        "assistant_text": json.dumps(
            {
                "response_units": [
                    {
                        "type": "text",
                        "content": {
                            "text": (
                                "May options po:\n\n"
                                "*   **APOLLO 175/65/R14 AMAZER XP 82T**\n"
                                "*   **BFGOODRICH 175/65/R14 ADVANTAGE TOURING 82H**\n"
                                "<ul><li>Promo option</li><li>Budget option</li></ul>"
                            )
                        },
                    }
                ]
            }
        ),
        "tool_results": [],
    }

    rendered = render_turn_for_channel(turn)
    text = rendered.response["bubble1"]

    assert "**" not in text
    assert "<li>" not in text
    assert "- APOLLO 175/65/R14 AMAZER XP 82T" in text
    assert "- Promo option" in text


def test_channel_renderer_prepends_first_turn_welcome_marker_before_structured_units():
    turn = {
        "assistant_text": json.dumps(
            {
                "response_units": [
                    {"type": "text", "content": {"text": "May available options po tayo for that size."}},
                ]
            }
        ),
        "welcome_spiel_inserted": True,
    }

    rendered = render_turn_for_channel(turn)

    assert rendered.response["bubble1"] == RUNTIME_V7_WELCOME_SPIEL_TEXT
    assert rendered.response["bubble2"] == RUNTIME_V7_FIRST_TURN_INFO_REQUEST_TEXT
    assert rendered.response["bubble3"] == RUNTIME_V7_FIRST_TURN_SIZE_GUIDE_TEXT
    assert rendered.response["bubble4"] == "May available options po tayo for that size."


def test_channel_renderer_uses_guard_event_to_prepend_first_turn_welcome():
    turn = {
        "assistant_text": json.dumps(
            {
                "response_units": [
                    {"type": "text", "content": {"text": "May available options po tayo for that size."}},
                ]
            }
        ),
        "response_guard_events": [
            {
                "type": WELCOME_SPIEL_GUARD_EVENT_TYPE,
                "reason": "no_prior_agent_chatbot_or_manychat_automation",
            }
        ],
    }

    rendered = render_turn_for_channel(turn)

    assert rendered.response["bubble1"] == RUNTIME_V7_WELCOME_SPIEL_TEXT
    assert rendered.response["bubble2"] == RUNTIME_V7_FIRST_TURN_INFO_REQUEST_TEXT
    assert rendered.response["bubble3"] == RUNTIME_V7_FIRST_TURN_SIZE_GUIDE_TEXT
    assert rendered.response["bubble4"] == "May available options po tayo for that size."


def test_channel_renderer_uses_fixed_fallback_when_model_opening_is_missing():
    turn = {
        "assistant_text": json.dumps(
            {
                "response_units": [
                    {"type": "text", "content": {"text": "May available options po tayo for that size."}},
                ]
            }
        ),
        "response_guard_events": [
            {
                "type": WELCOME_SPIEL_GUARD_EVENT_TYPE,
                "reason": "first_turn_intro_applicable_no_prior_outbound",
                "intro_mode": FIRST_TURN_INTRO_MODE_WELCOME_ONLY,
            }
        ],
    }

    rendered = render_turn_for_channel(turn)

    assert rendered.response == {
        "bubble1": (
            f"{RUNTIME_V7_WELCOME_SPIEL_TEXT}\n\n"
            "May available options po tayo for that size."
        )
    }
    assert RUNTIME_V7_FIRST_TURN_INFO_REQUEST_TEXT not in rendered.response.values()


def test_channel_renderer_keeps_welcome_separate_when_required_surface_is_first():
    turn = _product_turn_record()
    turn["response_guard_events"] = [
        {
            "type": WELCOME_SPIEL_GUARD_EVENT_TYPE,
            "reason": "first_turn_intro_applicable_no_prior_outbound",
            "intro_mode": FIRST_TURN_INTRO_MODE_WELCOME_ONLY,
        }
    ]

    rendered = render_turn_for_channel(turn)

    assert rendered.response["bubble1"] == RUNTIME_V7_WELCOME_SPIEL_TEXT
    assert rendered.content_messages[0] == {
        "type": "text",
        "text": RUNTIME_V7_WELCOME_SPIEL_TEXT,
    }
    assert rendered.content_messages[1]["type"] in {"text", "cards"}


def test_channel_renderer_merges_existing_welcome_prefix_in_welcome_only_mode():
    continuation = "Yes po—may current options tayo for your requested size 😊"
    turn = {
        "runtime_final_response": f"{RUNTIME_V7_WELCOME_SPIEL_TEXT}\n\n{continuation}",
        "first_turn_intro_mode": FIRST_TURN_INTRO_MODE_WELCOME_ONLY,
        "welcome_spiel_inserted": True,
    }

    rendered = render_turn_for_channel(turn)

    assert rendered.response == {
        "bubble1": f"{RUNTIME_V7_WELCOME_SPIEL_TEXT}\n\n{continuation}"
    }


def test_fallback_welcome_merge_preserves_lead_surface_and_cta_sequence():
    turn = _product_turn_record()
    lead = "Yes po—may current options tayo for your requested size and quantity 😊"
    cta = "Aling exact model po ang gusto niyong unahin natin?"
    turn["assistant_text"] = json.dumps(
        {
            "response_units": [
                {"type": "text", "content": {"text": lead}},
                {"type": "render_surface", "content": {"surface_ref": "pres_product_abc"}},
                {"type": "text", "content": {"text": cta}},
            ]
        }
    )
    turn["response_guard_events"] = [
        {
            "type": WELCOME_SPIEL_GUARD_EVENT_TYPE,
            "reason": "first_turn_intro_applicable_no_prior_outbound",
            "intro_mode": FIRST_TURN_INTRO_MODE_WELCOME_ONLY,
        }
    ]

    rendered = render_turn_for_channel(turn)
    texts = [
        message["text"]
        for message in rendered.content_messages
        if message.get("type") == "text"
    ]

    assert texts[0] == f"{RUNTIME_V7_WELCOME_SPIEL_TEXT}\n\n{lead}"
    assert "MICHELIN PILOT SPORT 5" in texts[1]
    assert texts[-1] == cta
    assert sum("Welcome to Gulong.ph" in text for text in texts) == 1


def test_channel_renderer_preserves_model_composed_opening_without_fixed_welcome():
    turn = _product_turn_record()
    opening = (
        "Good morning po! Gulong.ph here 😊 May options tayo for the size "
        "and quantity you sent—ito po yung current choices:"
    )
    cta = "Aling model po ang gusto ninyong unahin natin?"
    turn["assistant_text"] = json.dumps(
        {
            "response_units": [
                {"type": "text", "content": {"text": opening}},
                {"type": "render_surface", "content": {"surface_ref": "pres_product_abc"}},
                {"type": "text", "content": {"text": cta}},
            ]
        }
    )
    turn["first_turn_intro_mode"] = FIRST_TURN_INTRO_MODE_WELCOME_ONLY
    turn["response_guard_events"] = [
        {
            "type": MODEL_COMPOSED_FIRST_TURN_OPENING_EVENT_TYPE,
            "reason": "model_owned_first_turn_text_preserved",
            "intro_mode": FIRST_TURN_INTRO_MODE_WELCOME_ONLY,
        }
    ]

    rendered = render_turn_for_channel(turn)
    texts = [
        message["text"]
        for message in rendered.content_messages
        if message.get("type") == "text"
    ]

    assert texts[0] == opening
    assert RUNTIME_V7_WELCOME_SPIEL_TEXT not in texts[0]
    assert "MICHELIN PILOT SPORT 5" in texts[1]
    assert texts[-1] == cta


def test_channel_renderer_does_not_duplicate_welcome_when_fallback_text_already_has_it():
    turn = {
        "runtime_final_response": (
            f"{RUNTIME_V7_FIRST_TURN_INTRO_TEXT}\n\n"
            "May available options po tayo for that size."
        ),
        "welcome_spiel_inserted": True,
    }

    rendered = render_turn_for_channel(turn)

    assert list(rendered.response.values()).count(RUNTIME_V7_WELCOME_SPIEL_TEXT) == 1
    assert rendered.response["bubble1"] == RUNTIME_V7_WELCOME_SPIEL_TEXT
    assert rendered.response["bubble2"] == RUNTIME_V7_FIRST_TURN_INFO_REQUEST_TEXT
    assert rendered.response["bubble3"] == RUNTIME_V7_FIRST_TURN_SIZE_GUIDE_TEXT
    assert rendered.response["bubble4"] == "May available options po tayo for that size."


def test_channel_renderer_coalesces_adjacent_model_text_units():
    turn = {
        "assistant_text": json.dumps(
            {
                "response_units": [
                    {"type": "text", "content": {"text": "Ang NANKANG po ay PHP 4,355 for one tire."}},
                    {"type": "text", "content": {"text": "Pay Now: PHP 4,255 with PHP 100 discount."}},
                    {
                        "type": "text",
                        "content": {"text": "Pay Later: PHP 500 reservation, balance PHP 3,855."},
                    },
                ]
            }
        ),
        "tool_results": [],
    }

    rendered = render_turn_for_channel(turn)

    assert len(rendered.content_messages) == 1
    assert rendered.response == {
        "bubble1": (
            "Ang NANKANG po ay PHP 4,355 for one tire.\n\n"
            "Pay Now: PHP 4,255 with PHP 100 discount.\n\n"
            "Pay Later: PHP 500 reservation, balance PHP 3,855."
        )
    }


def _product_turn_record(*, service_type: str = "installation") -> dict:
    return {
        "assistant_text": json.dumps(
            {
                "response_units": [
                    {"type": "render_surface", "content": {"surface_ref": "pres_product_abc"}},
                    {"type": "text", "content": {"text": "Alin po ang gusto niyong i-check next?"}},
                ]
            }
        ),
        "tool_results": [
            {
                "name": "product_search",
                "round": 1,
                "args": {"service_type": service_type} if service_type else {},
                "result": {"status": "ok", "presentation_ref": "pres_product_abc"},
                "full_result": {
                    "status": "ok",
                    "presentation_ref": "pres_product_abc",
                    "product_cards": [
                        {
                            "card_ref": "card_1",
                            "item_ref": "prod_michelin",
                            "brand": "MICHELIN",
                            "sku_model": "MICHELIN PILOT SPORT 5 215/50/R17",
                            "warranty": "6 years",
                            "tire_protection_plan": "Tire Protection Plan (1 Year)",
                            "image_url": (
                                "https://gulongph.sgp1.digitaloceanspaces.com/"
                                "product_images/michelin-pilot-sport-5.webp"
                            ),
                            "card_text": "[PREMIUM]\nMICHELIN PILOT SPORT 5\nPHP 42,420.00 for 4 tires",
                        },
                        {
                            "card_ref": "card_2",
                            "item_ref": "prod_apollo",
                            "brand": "APOLLO",
                            "sku_model": "APOLLO ALNAC 4G 215/50/R17",
                            "warranty": "5 years",
                            "image_url": (
                                "https://gulong-ph.sgp1.digitaloceanspaces.com/"
                                "product_images/apollo-alnac-4g.webp"
                            ),
                            "card_text": "[MID RANGE]\nAPOLLO ALNAC 4G\nPHP 28,000.00 for 4 tires",
                        },
                    ],
                    "card_runtime_insert": True,
                },
            }
        ],
    }


def test_channel_renderer_adds_product_inclusions_bubble_before_cta():
    rendered = render_turn_for_channel(_product_turn_record())
    texts = [message["text"] for message in rendered.content_messages if message.get("type") == "text"]

    inclusion_index = next(index for index, text in enumerate(texts) if "Warranty and inclusions:" in text)
    cta_index = next(index for index, text in enumerate(texts) if "Alin po ang gusto" in text)

    assert "[PREMIUM]\n🛞 MICHELIN PILOT SPORT 5" in texts[0]
    assert "[MID RANGE]\n🛞 APOLLO ALNAC 4G" in texts[0]
    assert texts[0].count("PHP ") == 2
    assert "https://gulong.ph/product/" not in texts[0]
    assert inclusion_index < cta_index
    assert texts[inclusion_index].startswith("Warranty and inclusions:")
    assert "Manufacturer's warranty:" not in texts[inclusion_index]
    assert "MICHELIN - 6 years against manufacturer defect" not in texts[inclusion_index]
    assert "Tire Protection Plan: The Gulong" not in texts[inclusion_index]
    assert "The Gulong Tire Protection Plan is an unconditional warranty" in texts[inclusion_index]
    assert "Kapag nabutas, napako, or nasira ang sidewall, papalitan agad" in texts[inclusion_index]
    assert "Install with our authorized Installation Partners and get:" in texts[inclusion_index]
    assert "• FREE mounting & balancing" in texts[inclusion_index]
    assert "• FREE weights & tire valves" in texts[inclusion_index]
    assert "100% brand new with Manufacturer's Warranty & Tire Protection Plan 💯" in texts[inclusion_index]
    assert rendered.response[f"bubble{inclusion_index + 1}"] == texts[inclusion_index]


def test_channel_renderer_discloses_same_brand_terrain_relaxation_before_products(
    monkeypatch,
):
    monkeypatch.setenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE", "staging_router")
    turn = _product_turn_record()
    full_result = turn["tool_results"][0]["full_result"]
    turn["assistant_text"] = json.dumps(
        {
            "response_units": [
                {
                    "type": "text",
                    "content": {
                        "text": "Meron kaming 3 exact Nitto A/T options para sa inyo."
                    },
                },
                {
                    "type": "render_surface",
                    "content": {"surface_ref": "pres_product_abc"},
                },
                {
                    "type": "text",
                    "content": {"text": "Alin po ang gusto niyong i-check next?"},
                },
            ]
        }
    )
    full_result.update(
        {
            "status": "partial_match",
            "result_level": "near_exact",
            "query_basis": {
                "normalized_filters": {
                    "section_width": "265",
                    "aspect_ratio": "50",
                    "rim_size": "R20",
                    "brands": ["NITTO"],
                    "terrain_types": ["ALL_TERRAIN"],
                }
            },
            "presentation_strategy": {
                "relaxation": {
                    "applied": True,
                    "shown_cards_missing_filters": ["terrain_type"],
                }
            },
        }
    )
    full_result["product_cards"] = [
        {
            "card_ref": "card_nitto_420sd",
            "item_ref": "prod_nitto_420sd",
            "brand": "NITTO",
            "tire_size": "265/50R20",
            "sku_model": "NITTO 265/50/R20 420SD HP 111V",
            "image_url": (
                "https://gulongph.sgp1.digitaloceanspaces.com/"
                "product_images/nitto-420sd.webp"
            ),
            "card_text": "[PREMIUM]\nNITTO 265/50/R20 420SD HP 111V",
        },
        {
            "card_ref": "card_nitto_421q",
            "item_ref": "prod_nitto_421q",
            "brand": "NITTO",
            "tire_size": "265/50R20",
            "sku_model": "NITTO 265/50/R20 421Q HP 111V",
            "image_url": (
                "https://gulongph.sgp1.digitaloceanspaces.com/"
                "product_images/nitto-421q.webp"
            ),
            "card_text": "[PREMIUM]\nNITTO 265/50/R20 421Q HP 111V",
        },
        {
            "card_ref": "card_nitto_terra",
            "item_ref": "prod_nitto_terra",
            "brand": "NITTO",
            "tire_size": "265/50R20",
            "sku_model": "NITTO 265/50/R20 TERRA GRAPPLER NTGA2 111S",
            "card_text": (
                "[PREMIUM]\nNITTO 265/50/R20 TERRA GRAPPLER NTGA2 111S"
            ),
        },
    ]

    rendered = render_turn_for_channel(turn, service_environment="staging")

    messages = rendered.content_messages
    notice_index = next(
        index
        for index, message in enumerate(messages)
        if message.get("type") == "text"
        and "Walang NITTO option na verified as A/T sa 265/50R20" in message.get(
            "text", ""
        )
    )
    price_index = next(
        index
        for index, message in enumerate(messages)
        if message.get("type") == "text"
        and "420SD HP" in message.get("text", "")
    )
    gallery_index = next(
        index for index, message in enumerate(messages) if message.get("type") == "cards"
    )
    cta_index = next(
        index
        for index, message in enumerate(messages)
        if message.get("type") == "text"
        and "Alin po ang gusto" in message.get("text", "")
    )

    assert notice_index < price_index < gallery_index < cta_index
    assert not any(
        "exact Nitto A/T" in message.get("text", "") for message in messages
    )
    price_text = messages[price_index]["text"]
    assert "420SD HP" in price_text
    assert "421Q HP" in price_text
    assert "TERRA GRAPPLER" in price_text
    assert len(messages[gallery_index]["elements"]) == 2
    assert all(
        element["buttons"][0]["actions"][0]["value"].startswith("ps1|")
        for element in messages[gallery_index]["elements"]
    )


def test_channel_renderer_suppresses_product_inclusions_after_session_seen():
    turn = _product_turn_record()
    turn["product_inclusions_previously_sent"] = True

    rendered = render_turn_for_channel(turn)
    texts = [message["text"] for message in rendered.content_messages if message.get("type") == "text"]

    assert "[PREMIUM]\n🛞 MICHELIN PILOT SPORT 5" in texts[0]
    assert "[MID RANGE]\n🛞 APOLLO ALNAC 4G" in texts[0]
    assert not any("Warranty and inclusions:" in text for text in texts)
    assert any("Alin po ang gusto" in text for text in texts)


def test_channel_renderer_keeps_single_product_visual_and_selection_button(monkeypatch):
    monkeypatch.setenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE", "staging_router")
    turn = _product_turn_record()
    turn["tool_results"][0]["full_result"]["product_cards"] = [
        turn["tool_results"][0]["full_result"]["product_cards"][0]
    ]

    rendered = render_turn_for_channel(turn, service_environment="staging")
    galleries = [
        message
        for message in rendered.content_messages
        if message.get("type") == "cards"
    ]

    assert len(galleries) == 1
    assert len(galleries[0]["elements"]) == 1
    assert galleries[0]["elements"][0]["image_url"].startswith("https://")
    assert galleries[0]["elements"][0]["buttons"][0]["actions"][0][
        "value"
    ].startswith("ps1|")


def test_channel_renderer_treats_repaired_composer_surface_plan_as_authoritative():
    turn = _product_turn_record()
    turn["final_composer"] = {"status": "repaired"}
    turn["assistant_text"] = json.dumps(
        {
            "response_units": [
                {
                    "type": "text",
                    "content": {"text": "Noted po. Saang area kayo para ma-check ang next option?"},
                }
            ]
        }
    )

    rendered = render_turn_for_channel(turn)

    assert rendered.text == "Noted po. Saang area kayo para ma-check ang next option?"
    assert "MICHELIN PILOT SPORT" not in rendered.text
    assert not any(message.get("type") == "cards" for message in rendered.content_messages)


def test_channel_renderer_treats_contract_fallback_surface_plan_as_authoritative():
    turn = _product_turn_record()
    turn["final_composer"] = {"status": "renderer_contract_fallback"}
    turn["assistant_text"] = json.dumps(
        {
            "response_units": [
                {
                    "type": "text",
                    "content": {
                        "text": "Noted po ang area. Pili muna tayo ng tire option."
                    },
                }
            ]
        }
    )

    rendered = render_turn_for_channel(turn)

    assert rendered.text == "Noted po ang area. Pili muna tayo ng tire option."
    assert "MICHELIN PILOT SPORT" not in rendered.text
    assert not any(
        message.get("type") == "cards"
        for message in rendered.content_messages
    )


def test_channel_renderer_keeps_product_card_selected_by_contract_fallback(
    monkeypatch,
):
    monkeypatch.setenv(
        "PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE",
        "staging_router",
    )
    turn = _product_turn_record()
    turn["final_composer"] = {"status": "renderer_contract_fallback"}
    turn["assistant_text"] = json.dumps(
        {
            "response_units": [
                {
                    "type": "text",
                    "content": {"text": "Validated fallback po."},
                },
                {
                    "type": "render_surface",
                    "content": {"surface_ref": "pres_product_abc"},
                },
            ]
        }
    )

    rendered = render_turn_for_channel(
        turn,
        service_environment="staging",
    )

    assert rendered.text.startswith("Validated fallback po.")
    cards = [
        message
        for message in rendered.content_messages
        if message.get("type") == "cards"
    ]
    assert len(cards) == 1
    assert cards[0]["elements"][0]["buttons"][0]["actions"][0][
        "value"
    ].startswith("ps1|")


def test_channel_renderer_uses_warranty_gallery_instead_of_long_inclusions(monkeypatch):
    monkeypatch.setenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE", "staging_router")
    turn = _product_turn_record()
    turn["assistant_text"] = json.dumps(
        {
            "response_units": [
                {
                    "type": "render_surface",
                    "content": {"surface_ref": "pres_product_abc"},
                },
                {
                    "type": "render_surface",
                    "content": {"surface_ref": "promo_gallery_warranty"},
                },
                {
                    "type": "text",
                    "content": {"text": "Alin po ang gusto niyong i-check next?"},
                },
            ]
        }
    )
    turn["tool_results"].append(
        {
            "name": "present_promo_gallery",
            "round": 2,
            "result": {"status": "ok", "presentation_ref": "promo_gallery_warranty"},
            "full_result": {
                "status": "ok",
                "presentation_ref": "promo_gallery_warranty",
                "promo_refs": ["promo:double-warranty"],
                "promo_ids": ["double-warranty"],
                "promo_types": ["warranty"],
                "promo_titles": ["The Gulong Double Warranty"],
                "card_refs": ["double-warranty-card"],
                "cards": [
                    {
                        "card_id": "double-warranty-card",
                        "title": "The Gulong Double Warranty",
                        "subtitle": "Manufacturer warranty plus Gulong tire protection warranty.",
                        "image_url": (
                            "https://storage.googleapis.com/gulong-chatbot-459723-"
                            "promo-media/catalog/catalog-v1/cards/double-warranty.png"
                        ),
                        "buttons": [
                            {
                                "type": "flow",
                                "caption": "Promo Details",
                                "targets": {
                                    "staging": "content-staging-promo-router",
                                    "live": "content-live-promo-router",
                                },
                                "action": "promo_details",
                                "selected_brand": "",
                                "actions": [
                                    {
                                        "action": "set_field_value",
                                        "field_name": "promo_catalog_version",
                                        "value": "catalog-v1",
                                    },
                                    {
                                        "action": "set_field_value",
                                        "field_name": "promo_selected_id",
                                        "value": "double-warranty",
                                    },
                                    {
                                        "action": "set_field_value",
                                        "field_name": "promo_selected_card_id",
                                        "value": "double-warranty-card",
                                    },
                                    {
                                        "action": "set_field_value",
                                        "field_name": "promo_selected_action",
                                        "value": "promo_details",
                                    },
                                ],
                            }
                        ],
                    }
                ],
                "card_runtime_insert": True,
            },
        }
    )

    rendered = render_turn_for_channel(turn, service_environment="staging")
    texts = [
        message["text"]
        for message in rendered.content_messages
        if message.get("type") == "text"
    ]

    assert not any("Warranty and inclusions:" in text for text in texts)
    galleries = [
        message
        for message in rendered.content_messages
        if message.get("type") == "cards"
    ]
    warranty_gallery = next(
        message
        for message in galleries
        if message["elements"][0].get("title") == "The Gulong Double Warranty"
    )
    assert warranty_gallery["elements"][0]["image_url"] == (
        "https://storage.googleapis.com/gulong-chatbot-459723-promo-media/"
        "catalog/catalog-v1/cards/double-warranty.png"
    )
    product_gallery = next(
        message
        for message in galleries
        if "MICHELIN PILOT SPORT 5" in message["elements"][0].get("title", "")
    )
    assert product_gallery["elements"][0]["buttons"]
    assert all(
        button.get("type") == "flow"
        for button in product_gallery["elements"][0]["buttons"]
    )
    # Both surfaces were explicitly selected by the composer. The warranty
    # card replaces only the verbose inclusions spiel; it must not erase a
    # product gallery when the configured channel router can render one.
    assert sum(
        message["elements"][0].get("title") == "The Gulong Double Warranty"
        for message in galleries
    ) == 1
    assert any("MICHELIN PILOT SPORT 5" in text for text in texts)
    assert len(rendered.product_presentations) == 1
    assert rendered.product_presentations[0]["presentation_ref"] == "pres_product_abc"


def test_channel_renderer_adds_exact_product_choice_buttons(monkeypatch):
    monkeypatch.setenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE", "staging_router")

    rendered = render_turn_for_channel(
        _product_turn_record(),
        service_environment="staging",
    )

    galleries = [
        message
        for message in rendered.content_messages
        if message.get("type") == "cards"
    ]
    assert len(galleries) == 1
    assert [element["title"] for element in galleries[0]["elements"]] == [
        "MICHELIN PILOT SPORT 5 215/50/R17",
        "APOLLO ALNAC 4G 215/50/R17",
    ]
    assert [
        element["buttons"][0]["caption"]
        for element in galleries[0]["elements"]
    ] == [
        "MICHELIN PILOT SPORT",
        "APOLLO ALNAC 4G",
    ]
    assert all(
        element["buttons"][0]["target"] == "staging_router"
        and element["buttons"][0]["actions"][0]["value"].startswith("ps1|")
        for element in galleries[0]["elements"]
    )
    product_choices = [
        item
        for item in rendered.choice_presentations
        if item.get("choice_type") == "product_selection"
    ]
    assert len(product_choices) == 1
    assert len(product_choices[0]["choices"]) == 2


def test_channel_renderer_uses_catalog_images_for_product_selection_gallery(monkeypatch):
    monkeypatch.setenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE", "staging_router")
    turn = _product_turn_record()
    cards = turn["tool_results"][0]["full_result"]["product_cards"]
    cards[0]["image_url"] = (
        "https://gulongph.sgp1.digitaloceanspaces.com/"
        "product_images/New_Main_Product_Image/MICHELIN/MICHELIN.webp"
    )
    cards[1]["image_url"] = (
        "https://gulong-ph.sgp1.digitaloceanspaces.com/"
        "product_images/New_Main_Product_Image/APOLLO/APOLLO.webp"
    )
    cards[0]["pricing_facts"] = {
        "quantity": 4,
        "unit_price": 8085,
        "payable_total": 24255,
    }
    cards[0]["card_text"] = (
        "[PREMIUM]\nMICHELIN PILOT SPORT 5\n"
        "PHP 8,085.00/tire | 4 tires: PHP 24,255.00"
    )
    cards[0]["promo_savings_line"] = (
        "PHP 1,000.00 off/tire already reflected in unit price | "
        "Buy 3 Get 1 FREE | Save PHP 8,085.00"
    )
    cards[0]["installment_text"] = "BPI 6mo 0% interest"
    cards[0]["origin"] = "Thailand"
    cards[0]["dot"] = "2026"
    cards[0]["url"] = "https://gulong.ph/product/michelin-pilot-sport-5"

    rendered = render_turn_for_channel(turn, service_environment="staging")

    gallery = next(
        message
        for message in rendered.content_messages
        if message.get("type") == "cards"
    )
    assert gallery["image_aspect_ratio"] == "square"
    assert [element["image_url"] for element in gallery["elements"]] == [
        cards[0]["image_url"],
        cards[1]["image_url"],
    ]
    assert gallery["elements"][0]["subtitle"] == (
        "PHP 8,085.00/tire | 4 tires: PHP 24,255.00\nBuy 3 Get 1 FREE"
    )
    assert "already" not in gallery["elements"][0]["subtitle"]
    assert all(element["buttons"][0]["caption"] for element in gallery["elements"])
    text_messages = [
        message["text"]
        for message in rendered.content_messages
        if message.get("type") == "text"
    ]
    assert any("[PREMIUM]\n🛞 MICHELIN PILOT SPORT 5" in text for text in text_messages)
    assert any("[MID RANGE]\n🛞 APOLLO ALNAC 4G" in text for text in text_messages)
    rich_price_list = next(
        text for text in text_messages if "MICHELIN PILOT SPORT 5" in text
    )
    assert "💰 PHP 8,085.00/tire | 4 tires: PHP 24,255.00" in rich_price_list
    assert (
        "🎁 PHP 1,000.00 off/tire already reflected in unit price | "
        "Buy 3 Get 1 FREE | Save PHP 8,085.00"
    ) in rich_price_list
    assert "💳 BPI 6mo 0% interest" in rich_price_list
    assert "Origin: Thailand" in rich_price_list
    assert "🗓️ DOT: 2026" in rich_price_list
    assert "Warranty: 6 years + Tire Protection Plan (1 Year)" in rich_price_list
    assert "🔗 https://gulong.ph/product/michelin-pilot-sport-5" in rich_price_list
    assert any("Warranty and inclusions:" in text for text in text_messages)
    assert any("Alin po ang gusto" in text for text in text_messages)


def test_channel_renderer_prefers_structured_pricing_over_stale_card_text(monkeypatch):
    monkeypatch.setenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE", "staging_router")
    turn = _product_turn_record()
    card = turn["tool_results"][0]["full_result"]["product_cards"][0]
    card["pricing_facts"] = {
        "quantity": 4,
        "unit_price": 8085,
        "payable_total": 24255,
    }
    assert "PHP 42,420.00" in card["card_text"]

    rendered = render_turn_for_channel(turn, service_environment="staging")
    visible_text = "\n".join(
        message.get("text", "")
        for message in rendered.content_messages
        if message.get("type") == "text"
    )

    assert "PHP 8,085.00/tire | 4 tires: PHP 24,255.00" in visible_text
    assert "PHP 42,420.00" not in visible_text


def test_channel_renderer_rejects_untrusted_product_image_host(monkeypatch):
    monkeypatch.setenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE", "staging_router")
    turn = _product_turn_record()
    cards = turn["tool_results"][0]["full_result"]["product_cards"]
    cards[0]["image_url"] = "https://example.com/not-catalog.jpg"
    cards.append(
        {
            "card_ref": "card_3",
            "item_ref": "prod_yokohama",
            "brand": "YOKOHAMA",
            "sku_model": "YOKOHAMA BLUEARTH GT AE51 215/50/R17",
            "image_url": (
                "https://storage.googleapis.com/gulong-catalog/"
                "yokohama-bluearth-gt-ae51.webp"
            ),
            "card_text": (
                "[PREMIUM]\nYOKOHAMA BLUEARTH GT AE51\n"
                "PHP 36,000.00 for 4 tires"
            ),
        }
    )

    rendered = render_turn_for_channel(turn, service_environment="staging")

    gallery = next(
        message
        for message in rendered.content_messages
        if message.get("type") == "cards"
    )
    assert [element["title"] for element in gallery["elements"]] == [
        "APOLLO ALNAC 4G 215/50/R17",
        "YOKOHAMA BLUEARTH GT AE51 215/50/R17",
    ]
    price_list = next(
        message["text"]
        for message in rendered.content_messages
        if message.get("type") == "text" and "APOLLO ALNAC 4G" in message.get("text", "")
    )
    assert "YOKOHAMA BLUEARTH GT AE51" in price_list
    assert "MICHELIN PILOT SPORT 5" in price_list
    choices = next(
        item
        for item in rendered.choice_presentations
        if item.get("choice_type") == "product_selection"
    )
    assert [item["card_ref"] for item in choices["choices"]] == ["card_2", "card_3"]


def test_channel_renderer_repeats_gallery_without_duplicate_delivered_price_list(monkeypatch):
    monkeypatch.setenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE", "staging_router")
    first_turn = _product_turn_record()
    first = render_turn_for_channel(first_turn, service_environment="staging")
    presentation = first.product_presentations[0]
    assert presentation["price_list_included"] is True
    assert presentation["gallery_included"] is True
    assert all(
        fingerprint.startswith("pcf1:")
        for fingerprint in presentation["commercial_fingerprints"]
    )

    repeated_turn = _product_turn_record()
    repeated_turn["product_price_list_delivery_fingerprints"] = [
        {
            "presentation_ref": presentation["presentation_ref"],
            "card_identities": [
                f"item_ref:{card['item_ref']}" for card in presentation["cards"]
            ],
            "commercial_fingerprints": presentation["commercial_fingerprints"],
        }
    ]
    repeated = render_turn_for_channel(repeated_turn, service_environment="staging")

    assert any(message.get("type") == "cards" for message in repeated.content_messages)
    assert not any(
        "MICHELIN PILOT SPORT 5" in message.get("text", "")
        for message in repeated.content_messages
    )
    assert repeated.product_presentations[0]["price_list_included"] is False


def test_channel_renderer_repeats_price_list_when_commercial_facts_change(monkeypatch):
    monkeypatch.setenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE", "staging_router")
    first_turn = _product_turn_record()
    first_card = first_turn["tool_results"][0]["full_result"]["product_cards"][0]
    first_card["pricing_facts"] = {
        "quantity": 4,
        "unit_price": 10605,
        "payable_total": 42420,
    }
    first = render_turn_for_channel(first_turn, service_environment="staging")
    prior = first.product_presentations[0]

    changed_turn = _product_turn_record()
    changed_card = changed_turn["tool_results"][0]["full_result"]["product_cards"][0]
    changed_card["pricing_facts"] = {
        "quantity": 4,
        "unit_price": 8085,
        "payable_total": 24255,
    }
    changed_turn["product_price_list_delivery_fingerprints"] = [
        {
            "presentation_ref": prior["presentation_ref"],
            "card_identities": [
                f"item_ref:{card['item_ref']}" for card in prior["cards"]
            ],
            "commercial_fingerprints": prior["commercial_fingerprints"],
        }
    ]

    changed = render_turn_for_channel(changed_turn, service_environment="staging")

    assert changed.product_presentations[0]["price_list_included"] is True
    assert "PHP 8,085.00/tire | 4 tires: PHP 24,255.00" in changed.text
    assert changed.product_presentations[0]["commercial_fingerprints"] != (
        prior["commercial_fingerprints"]
    )


@pytest.mark.parametrize(
    ("field", "before", "after", "visible_after"),
    [
        ("origin", "Thailand", "Japan", "Origin: Japan"),
        ("dot", "2025", "2026", "🗓️ DOT: 2026"),
        (
            "url",
            "https://gulong.ph/product/old-product-ref",
            "https://gulong.ph/product/current-product-ref",
            "🔗 https://gulong.ph/product/current-product-ref",
        ),
    ],
)
def test_channel_renderer_repeats_rich_price_list_when_visible_detail_changes(
    monkeypatch,
    field,
    before,
    after,
    visible_after,
):
    monkeypatch.setenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE", "staging_router")
    first_turn = _product_turn_record()
    first_turn["tool_results"][0]["full_result"]["product_cards"][0][field] = before
    first = render_turn_for_channel(first_turn, service_environment="staging")
    prior = first.product_presentations[0]

    changed_turn = _product_turn_record()
    changed_turn["tool_results"][0]["full_result"]["product_cards"][0][field] = after
    changed_turn["product_price_list_delivery_fingerprints"] = [
        {
            "presentation_ref": prior["presentation_ref"],
            "card_identities": [
                f"item_ref:{card['item_ref']}" for card in prior["cards"]
            ],
            "commercial_fingerprints": prior["commercial_fingerprints"],
        }
    ]

    changed = render_turn_for_channel(changed_turn, service_environment="staging")

    assert changed.product_presentations[0]["price_list_included"] is True
    assert visible_after in changed.text
    assert changed.product_presentations[0]["commercial_fingerprints"] != (
        prior["commercial_fingerprints"]
    )


def test_legacy_identity_only_delivery_record_does_not_suppress_price_list(monkeypatch):
    monkeypatch.setenv("PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE", "staging_router")
    turn = _product_turn_record()
    cards = turn["tool_results"][0]["full_result"]["product_cards"]
    turn["product_price_list_delivery_fingerprints"] = [
        {
            "presentation_ref": "pres_product_abc",
            "card_identities": [f"item_ref:{card['item_ref']}" for card in cards],
        }
    ]

    rendered = render_turn_for_channel(turn, service_environment="staging")

    assert rendered.product_presentations[0]["price_list_included"] is True
    assert "MICHELIN PILOT SPORT 5" in rendered.text


def test_service_no_match_does_not_inject_scripted_delivery_copy(monkeypatch):
    monkeypatch.setenv(
        "PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE",
        "staging_router",
    )
    turn = _product_turn_record()
    turn["tool_results"].append(
        {
            "name": "find_installation_partners",
            "result": {"status": "no_match"},
            "full_result": {
                "status": "no_match",
                "observation_ref": "svc_no_match_1",
                "presentation_ref": "pres_no_match_1",
                "availability": {
                    "availability_status": "verified_no_match"
                },
                "message": "No current installation coverage was found.",
            },
        }
    )

    rendered = render_turn_for_channel(turn, service_environment="staging")

    assert "delivery na lang" not in rendered.text.casefold()
    assert "delivery area/address" not in rendered.text.casefold()
    assert "Alin po ang gusto" in rendered.text
    assert any(
        item.get("choice_type") == "product_selection"
        for item in rendered.choice_presentations
    )


def test_checkout_cards_receive_intro_when_model_did_not_provide_one(
    monkeypatch,
):
    monkeypatch.setenv(
        "PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE",
        "staging_router",
    )
    surface = build_payment_option_surface(
        quote={
            "quote_ref": "quote_1",
            "quote_breakdown": {
                "payment_options_preview": {
                    "pay_now": {
                        "discount_text": "PHP 100.00",
                        "amount_due_now_text": "PHP 18,380.00",
                    },
                    "pay_later": {
                        "reservation_fee_text": "PHP 500.00",
                        "balance_due_text": "PHP 17,980.00",
                    },
                }
            },
        },
        metadata={
            "source": "gulong_api_checkout_metadata",
            "payment_options": [
                {"id": 1, "name": "Pay Later"},
                {"id": 2, "name": "Pay Now"},
            ],
        },
        turn_id="turn_checkout_intro",
    )
    rendered = render_turn_for_channel(
        {
            "assistant_text": "Your selected tire and schedule are noted.",
            "tool_results": [],
            "checkout_choice_surface": surface,
        },
        service_environment="staging",
    )

    assert "Choose how you want to pay" not in rendered.text
    assert "Your selected tire and schedule are noted." in rendered.text
    assert any(
        message.get("type") == "cards"
        for message in rendered.content_messages
    )
    card = next(
        message
        for message in rendered.content_messages
        if message.get("type") == "cards"
    )
    assert [
        element["buttons"][0]["caption"]
        for element in card["elements"]
    ] == ["Pay Later", "Pay Now"]


def test_checkout_method_buttons_show_the_selected_method_in_transcript(
    monkeypatch,
):
    monkeypatch.setenv(
        "PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE",
        "staging_router",
    )
    surface = build_payment_method_surface(
        metadata={
            "source": "gulong_api_checkout_metadata",
            "payment_options": [{"id": 1, "name": "Pay Later"}],
            "transaction_types": [{"id": 1, "trans_type": "Install"}],
            "payment_types": [
                {
                    "id": 10,
                    "main_payment_type_id": 1,
                    "name": "BPI 6-mos Installment (0% interest)",
                    "value": "BPI-INSTALLMENT",
                    "is_installment": True,
                }
            ],
        },
        payment_option="Pay Later",
        product_brand="MICHELIN",
        service_path="installation",
        turn_id="turn_checkout_method_caption",
    )

    rendered = render_turn_for_channel(
        {
            "assistant_text": "Choose the payment method.",
            "tool_results": [],
            "checkout_choice_surface": surface,
        },
        service_environment="staging",
    )

    card = next(
        message
        for message in rendered.content_messages
        if message.get("type") == "cards"
    )
    assert card["elements"][0]["buttons"][0]["caption"] == "BPI 6-mos 0%"


def test_checkout_intro_is_not_duplicated_when_model_already_asks_payment(
    monkeypatch,
):
    monkeypatch.setenv(
        "PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE",
        "staging_router",
    )
    surface = build_payment_option_surface(
        quote={
            "quote_ref": "quote_2",
            "quote_breakdown": {
                "payment_options_preview": {
                    "pay_now": {"discount_text": "PHP 100.00"},
                    "pay_later": {"reservation_fee_text": "PHP 500.00"},
                }
            },
        },
        metadata={
            "payment_options": [
                {"id": 1, "name": "Pay Later"},
                {"id": 2, "name": "Pay Now"},
            ]
        },
        turn_id="turn_checkout_no_duplicate",
    )
    rendered = render_turn_for_channel(
        {
            "assistant_text": "Would you prefer Pay Now or Pay Later?",
            "tool_results": [],
            "checkout_choice_surface": surface,
        },
        service_environment="staging",
    )

    assert rendered.text.count("Pay Now") == 1


def test_payment_option_controls_do_not_rewrite_model_owned_question(
    monkeypatch,
):
    monkeypatch.setenv(
        "PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE",
        "staging_router",
    )
    surface = build_payment_option_surface(
        quote={
            "quote_ref": "quote_payment_before_review",
            "quote_breakdown": {
                "payment_options_preview": {
                    "pay_now": {"discount_text": "PHP 100.00"},
                    "pay_later": {"reservation_fee_text": "PHP 500.00"},
                }
            },
        },
        metadata={
            "payment_options": [
                {"id": 1, "name": "Pay Later"},
                {"id": 2, "name": "Pay Now"},
            ]
        },
        turn_id="turn_payment_before_review",
    )
    rendered = render_turn_for_channel(
        {
            "assistant_text": json.dumps(
                {
                    "response_units": [
                        {
                            "type": "text",
                            "content": {
                                "text": "Noted po ang schedule ninyo.",
                            },
                        },
                        {
                            "type": "text",
                            "content": {
                                "text": (
                                    "Gusto niyo na po bang i-review ang order "
                                    "summary?"
                                ),
                            },
                        },
                    ]
                }
            ),
            "tool_results": [],
            "checkout_choice_surface": surface,
        },
        service_environment="staging",
    )

    assert "Noted po ang schedule ninyo." in rendered.text
    assert "review ang order summary" in rendered.text
    assert "Choose how you want to pay" not in rendered.text
    assert any(
        message.get("type") == "cards"
        for message in rendered.content_messages
    )


def test_channel_renderer_suppresses_already_delivered_service_policy_note():
    result = {
        "status": "ok",
        "presentation_ref": "pres_slots_1",
        "installation_partner_cards": [
            {
                "card_ref": "partner_card_1",
                "card_text": "Installation slots near San Pedro\nJul 29: 9:30 AM",
            }
        ],
        "service_policy_notes": [
            {
                "id": "no_walkin_setup",
                "text": "No walk-in setup. Reserve before going to the partner.",
            }
        ],
        "card_runtime_insert": True,
    }
    turn = {
        "assistant_text": json.dumps(
            {
                "response_units": [
                    {
                        "type": "render_surface",
                        "content": {"surface_ref": "pres_slots_1"},
                    }
                ]
            }
        ),
        "tool_results": [
            {
                "name": "find_installation_slots",
                "result": {"status": "ok", "presentation_ref": "pres_slots_1"},
                "full_result": result,
            }
        ],
    }

    first = render_turn_for_channel(turn)
    turn["service_policy_note_ids_previously_sent"] = ["no_walkin_setup"]
    second = render_turn_for_channel(turn)

    assert "No walk-in setup" in first.text
    assert first.service_policy_note_ids == ["no_walkin_setup"]
    assert "No walk-in setup" not in second.text
    assert second.service_policy_note_ids == []


def test_channel_renderer_omits_installation_inclusions_for_delivery_product_context():
    rendered = render_turn_for_channel(_product_turn_record(service_type="delivery"))
    inclusion = next(
        message["text"]
        for message in rendered.content_messages
        if message.get("type") == "text" and "Warranty and inclusions:" in message.get("text", "")
    )

    assert "Manufacturer's warranty:" not in inclusion
    assert "Tire Protection Plan: The Gulong" not in inclusion
    assert "The Gulong Tire Protection Plan is an unconditional warranty" in inclusion
    assert "eligible when plan requirements are met" not in inclusion
    assert "Install with our authorized Installation Partners" not in inclusion


def test_api_runtime_extracts_image_urls_embedded_in_user_text():
    urls = _extract_image_urls_from_text(
        "ito yung pic https://cdn.manychat.com/incoming/sidewall.jpg "
        "and product link https://gulong.ph/product/apollo-175-65-r14 "
        "plus receipt https://storage.googleapis.com/bucket/payment-proof.png."
    )

    assert urls == [
        "https://cdn.manychat.com/incoming/sidewall.jpg",
        "https://storage.googleapis.com/bucket/payment-proof.png",
    ]


def test_api_runtime_does_not_apply_manychat_tags_in_return_only_mode():
    service = RuntimeV7APIService(sessions_gateway=object(), delivery_mode="return_only")

    result = asyncio.run(
        service._apply_tags(
            RuntimeV7APIRequest(user_id="user_1", channel="manychat", user_text="hm po"),
            {"tags_to_add": [{"tag": "Moderate Intent"}]},
            delivery_mode="return_only",
        )
    )

    assert result["tag_apply_skipped"] is True
    assert result["tag_apply_skip_reason"] == "return_only"


def test_manychat_handoff_note_formats_human_context():
    note = _build_manychat_handoff_note(
        "High Intent",
        request=RuntimeV7APIRequest(
            user_id="user_1",
            channel="manychat",
            user_text="Sige po, meron installation sa Baguio?",
            request_time="2026-06-14 10:31:00",
            channel_event_ts="2026-06-14 10:31:00",
        ),
        turn={
            "user_message": "Sige po, meron installation sa Baguio?",
            "lead_qualification": {
                "present": {"tire_size": "225/55R19", "tire_brand": "MICHELIN", "location": "Baguio"},
                "optional_missing": ["contact_number"],
            },
            "order_readiness_after_tools": {
                "collected": {
                    "Product": "MICHELIN 225/55R19 PRIMACY SUV+ 99V",
                    "Quantity": "4 tires (assumed default)",
                    "Trusted total": "PHP 31,800.00",
                    "Fulfillment": "installation",
                    "Installation area": "Baguio",
                    "Installation partner": "Sample Tire Center",
                    "Preferred installation schedule": (
                        "Jul 29, 2026 - 12:00 PM (flexible preference)"
                    ),
                    "Payment option": "Pay Later / Pay After Service",
                    "Balance payment method": "BPI 6-mos Installment (0% interest)",
                    "First name": "Juan",
                    "Last name": "Dela Cruz",
                    "Contact number": "09171234567",
                    "Email address": "juan@example.com",
                },
                "missing": [],
            },
            "tool_results": [
                {
                    "name": "product_search",
                    "full_result": {"product_cards": [{"brand": "MICHELIN", "tire_size": "225/55R19"}]},
                }
            ],
        },
        tagging_result={"synthetic_signals": {"has_location_or_partner": True, "has_schedule_or_payment": False}},
    )

    assert note == "\n".join(
        [
            "Gulong.ph CS Handoff | High Intent",
            "Tire: 225/55R19 | MICHELIN",
            "Product: MICHELIN 225/55R19 PRIMACY SUV+ 99V",
            "Qty / total: 4 tires | PHP 31,800.00",
            "Service: Installation | Baguio",
            "Partner: Sample Tire Center",
            "Schedule: Jul 29 - 12:00 PM (preferred)",
            "Payment: Pay Later | Balance: BPI 6-mos Installment (0% interest)",
            "Customer: Juan Dela Cruz | 09171234567 | juan@example.com",
            "Pending: None",
        ]
    )
    assert "Latest customer message" not in note
    assert "Suggested next reply" not in note
    assert "Why High Intent" not in note
    assert "2026" not in note


def test_manychat_handoff_note_does_not_render_service_phrase_as_location():
    note = _build_manychat_handoff_note(
        "Moderate Intent",
        request=RuntimeV7APIRequest(
            user_id="user_1",
            channel="manychat",
            user_text="Saan po ako makakatanggap ng libreng pag-installation?",
            request_time="2026-06-14 10:31:00",
            channel_event_ts="2026-06-14 10:31:00",
        ),
        turn={
            "user_message": "Saan po ako makakatanggap ng libreng pag-installation?",
            "lead_qualification": {
                "present": {"tire_size": "225/55R19", "tire_brand": "MICHELIN", "location": "Free Installation"},
                "missing": [],
            },
            "tool_results": [
                {
                    "name": "product_search",
                    "full_result": {"product_cards": [{"brand": "MICHELIN", "tire_size": "225/55R19"}]},
                }
            ],
        },
        tagging_result={"synthetic_signals": {"has_location_or_partner": False, "has_schedule_or_payment": False}},
    )

    assert "Free Installation" not in note
    assert "Service:" not in note
    assert "Pending: location" in note
    assert "Suggested next reply" not in note


def test_manychat_handoff_note_never_exposes_internal_pending_field_names():
    note = _build_manychat_handoff_note(
        "Moderate Intent",
        request=RuntimeV7APIRequest(user_id="trial", user_text="continue"),
        turn={
            "order_readiness_after_tools": {
                "missing": ["selected_product", "email_address"],
                "collected": {},
            },
            "lead_qualification": {"present": {}, "missing": []},
        },
        tagging_result={"synthetic_signals": {}},
    )

    assert "Pending: product choice, email" in note
    assert "selected_product" not in note
    assert "email_address" not in note


def test_api_runtime_creates_handoff_note_for_new_moderate_tag(monkeypatch):
    created = {"notes": []}

    class FakeManyChatAPI:
        def __init__(self, psid):
            self.psid = psid

        async def add_tag_by_name(self, tag_name):
            return {"status": "success", "tag": tag_name}

        async def create_note(self, note_content):
            created["notes"].append(note_content)
            return {"status": "success", "note_id": "note_1"}

    monkeypatch.setattr("runtime_v7.api_runtime.ManyChatAPI", FakeManyChatAPI)
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        delivery_mode="send_content",
        apply_manychat_tags=True,
    )

    result = asyncio.run(
        service._apply_tags(
            RuntimeV7APIRequest(
                user_id="user_1",
                channel="manychat",
                user_text="Baguio po",
                request_time="2026-06-14 10:31:00",
            ),
            {
                "tags_to_add": [{"tag": "Moderate Intent"}],
                "synthetic_signals": {"has_location_or_partner": True, "has_schedule_or_payment": False},
            },
            delivery_mode="send_content",
            turn={
                "user_message": "Baguio po",
                "lead_qualification": {
                    "present": {"tire_size": "225/55R19", "tire_brand": "MICHELIN", "location": "Baguio"},
                    "optional_missing": ["contact_number"],
                },
                "tool_results": [
                    {"name": "product_search", "full_result": {"product_cards": [{"brand": "MICHELIN", "tire_size": "225/55R19"}]}}
                ],
            },
        )
    )

    assert result["tags_applied"] == ["Moderate Intent"]
    assert result["handoff_note"]["status"] == "success"
    assert len(created["notes"]) == 1
    assert created["notes"][0].startswith("Gulong.ph CS Handoff | Moderate Intent")


def test_api_runtime_creates_handoff_note_for_stop_chatbot(monkeypatch):
    created = {"notes": []}

    class FakeManyChatAPI:
        def __init__(self, psid):
            self.psid = psid

        async def add_tag_by_name(self, tag_name):
            return {"status": "success", "tag": tag_name}

        async def create_note(self, note_content):
            created["notes"].append(note_content)
            return {"status": "success", "note_id": "note_handoff"}

    monkeypatch.setattr("runtime_v7.api_runtime.ManyChatAPI", FakeManyChatAPI)
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        delivery_mode="send_content",
        apply_manychat_tags=True,
    )

    result = asyncio.run(
        service._apply_tags(
            RuntimeV7APIRequest(
                user_id="user_handoff",
                channel="manychat",
                user_text="Stop the bot. Human agent please.",
            ),
            {
                "tags_to_add": [{"tag": "Stop Chatbot"}],
                "synthetic_signals": {"human_handoff_requested": True},
            },
            delivery_mode="send_content",
            turn={
                "user_message": "Stop the bot. Human agent please.",
                "human_handoff_state_after_turn": {
                    "status": "requested",
                    "human_assignment_confirmed": False,
                },
                "tool_results": [
                    {
                        "name": "request_human_handoff",
                        "full_result": {"status": "requested"},
                    }
                ],
            },
        )
    )

    assert result["tags_applied"] == ["Stop Chatbot"]
    assert result["handoff_note"]["status"] == "success"
    assert created["notes"][0].startswith(
        "Gulong.ph CS Handoff | Human Handoff Requested"
    )


class _FakeManyChatDeliveryClient:
    def __init__(self, statuses=None):
        self.statuses = list(statuses or [])
        self.calls = []

    async def send_content(self, messages, channel_subtype=None):
        self.calls.append({"messages": list(messages), "channel_subtype": channel_subtype})
        if self.statuses:
            return self.statuses.pop(0)
        return {"status": "success", "status_code": 200, "data": {"ok": True}}


def test_api_runtime_delivers_manychat_text_bubbles_with_default_delay(monkeypatch):
    monkeypatch.delenv("RUNTIME_V7_MANYCHAT_BUBBLE_DELAY_MS", raising=False)
    monkeypatch.delenv("RUNTIME_V7_MANYCHAT_BUBBLE_DELAY_MAX_MESSAGES", raising=False)
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("runtime_v7.api_runtime.asyncio.sleep", fake_sleep)
    client = _FakeManyChatDeliveryClient()
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        delivery_mode="send_content",
        delivery_client_factory=lambda _request: client,
    )
    messages = [
        {"type": "text", "text": "Bubble 1"},
        {"type": "text", "text": "Bubble 2"},
        {"type": "text", "text": "Bubble 3"},
    ]

    result = asyncio.run(
        service._deliver(
            RuntimeV7APIRequest(
                user_id="user_1",
                channel="manychat",
                channel_subtype="instagram",
                user_text="hm po",
            ),
            RuntimeV7ChannelRender(response={}, content_messages=messages),
            delivery_mode="send_content",
        )
    )

    assert [call["messages"] for call in client.calls] == [[messages[0]], [messages[1]], [messages[2]]]
    assert {call["channel_subtype"] for call in client.calls} == {"instagram"}
    assert sleeps == [1.2, 1.2]
    assert result["status"] == "success"
    assert result["delivery_mode"] == "send_content"
    assert result["sequential_delivery"] is True
    assert result["message_count"] == 3
    assert result["delayed_gap_count"] == 2
    assert "data" not in result["delivery_results"][0]


def test_api_runtime_manychat_bubble_delay_can_be_disabled(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_MANYCHAT_BUBBLE_DELAY_MS", "0")
    client = _FakeManyChatDeliveryClient()
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        delivery_mode="send_content",
        delivery_client_factory=lambda _request: client,
    )
    messages = [
        {"type": "text", "text": "Bubble 1"},
        {"type": "text", "text": "Bubble 2"},
    ]

    result = asyncio.run(
        service._deliver(
            RuntimeV7APIRequest(user_id="user_1", channel="manychat", user_text="hm po"),
            RuntimeV7ChannelRender(response={}, content_messages=messages),
            delivery_mode="send_content",
        )
    )

    assert [call["messages"] for call in client.calls] == [messages]
    assert result["status"] == "success"
    assert result["delivery_mode"] == "send_content"
    assert "sequential_delivery" not in result


def test_api_runtime_uses_channel_user_id_for_manychat_delivery(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_MANYCHAT_BUBBLE_DELAY_MS", "0")
    recipients = []

    class CapturingManyChatClient(_FakeManyChatDeliveryClient):
        def __init__(self, *, psid):
            super().__init__()
            recipients.append(psid)

    monkeypatch.setattr(
        "runtime_v7.api_runtime.ManyChatAPI",
        CapturingManyChatClient,
    )
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        delivery_mode="send_content",
    )

    result = asyncio.run(
        service._deliver(
            RuntimeV7APIRequest(
                user_id="synthetic-runtime-session",
                channel_user_id="4843256405786522",
                channel="manychat",
                user_text="show the warranty promo",
            ),
            RuntimeV7ChannelRender(
                response={},
                content_messages=[{"type": "text", "text": "Warranty details"}],
            ),
            delivery_mode="send_content",
        )
    )

    assert recipients == ["4843256405786522"]
    assert result["status"] == "success"


def test_api_runtime_manychat_bubble_delay_keeps_image_payloads_batched(monkeypatch):
    monkeypatch.delenv("RUNTIME_V7_MANYCHAT_BUBBLE_DELAY_MS", raising=False)
    client = _FakeManyChatDeliveryClient()
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        delivery_mode="send_content",
        delivery_client_factory=lambda _request: client,
    )
    messages = [
        {"type": "text", "text": "Payment details po."},
        {"type": "image", "url": "https://example.test/qr.png"},
        {"type": "text", "text": "Send proof after payment."},
    ]

    result = asyncio.run(
        service._deliver(
            RuntimeV7APIRequest(user_id="user_1", channel="manychat", user_text="gcash"),
            RuntimeV7ChannelRender(response={}, content_messages=messages),
            delivery_mode="send_content",
        )
    )

    assert [call["messages"] for call in client.calls] == [messages]
    assert result["status"] == "success"
    assert "sequential_delivery" not in result


def test_api_runtime_manychat_bubble_delay_stops_on_first_error(monkeypatch):
    monkeypatch.setenv("RUNTIME_V7_MANYCHAT_BUBBLE_DELAY_MS", "100")
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("runtime_v7.api_runtime.asyncio.sleep", fake_sleep)
    client = _FakeManyChatDeliveryClient(
        statuses=[
            {"status": "success", "status_code": 200, "data": {"ok": True}},
            {"status": "error", "status_code": 500, "error": "ManyChat unavailable"},
            {"status": "success", "status_code": 200},
        ]
    )
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        delivery_mode="send_content",
        delivery_client_factory=lambda _request: client,
    )
    messages = [
        {"type": "text", "text": "Bubble 1"},
        {"type": "text", "text": "Bubble 2"},
        {"type": "text", "text": "Bubble 3"},
    ]

    result = asyncio.run(
        service._deliver(
            RuntimeV7APIRequest(user_id="user_1", channel="manychat", user_text="hm po"),
            RuntimeV7ChannelRender(response={}, content_messages=messages),
            delivery_mode="send_content",
        )
    )

    assert [call["messages"] for call in client.calls] == [[messages[0]], [messages[1]]]
    assert sleeps == [0.1]
    assert result["status"] == "error"
    assert result["partial_delivery"] is True
    assert result["delivered_message_count"] == 1
    assert result["failed_message_index"] == 1
    assert result["delivery_mode"] == "send_content"


def test_api_runtime_persists_turn_trace_to_analytics_gateway():
    analytics = MemoryAnalyticsGateway()
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        delivery_mode="return_only",
        analytics_gateway=analytics,
    )
    request = RuntimeV7APIRequest(user_id="user_1", channel="manychat", user_text="hm po")
    rendered = render_turn_for_channel(
        {
            "assistant_text": json.dumps(
                {"response_units": [{"type": "text", "content": {"text": "Meron po."}}]}
            ),
            "tool_results": [],
        }
    )

    service._persist_turn_trace(
        request=request,
        turn={
            "turn_id": "turn_1",
            "tool_results": [],
            "llm_calls": [],
            "llm_usage_summary": {"total_tokens": 123},
        },
        rendered=rendered,
        turn_trace={"trace_id": "trace_1", "turn_id": "turn_1", "status": "completed"},
        delivery_result={"status": "skipped", "reason": "return_only"},
        tagging_result={"tags_to_add": []},
        session_id="sess_1",
        request_id="req_1",
        trace_id="trace_1",
        user_id="user_1",
    )

    log = analytics.last_debug_log() or {}

    assert log["request_id"] == "req_1"
    assert log["trace_id"] == "trace_1"
    assert log["debug_payload"]["kind"] == "runtime_v7_turn_trace"
    assert log["debug_payload"]["turn_record"]["llm_usage_summary"]["total_tokens"] == 123


def test_api_runtime_emits_price_category_impression_event():
    analytics = MemoryAnalyticsGateway()
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        delivery_mode="send_content",
        analytics_gateway=analytics,
    )
    request = RuntimeV7APIRequest(
        user_id="user_1",
        channel="manychat",
        user_text="Hi hm po 195 60 15",
        idempotency_key="message-1",
    )
    rendered = RuntimeV7ChannelRender(
        response={},
        content_messages=[
            {
                "type": "cards",
                "elements": [
                    {
                        "title": "Premium",
                        "buttons": [
                            {
                                "type": "flow",
                                "caption": "Choose Premium",
                                "target": "content-live-router",
                                "actions": [
                                    {
                                        "action": "set_field_value",
                                        "field_name": "promo_selected_id",
                                        "value": "bc1|price_categories_abc123|premium|195|60|R15",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        choice_presentations=[
            {
                "presentation_ref": "price_categories_abc123",
                "surface_type": "price_category_choices",
                "choice_type": "price_category",
                "tire_size": "195/60R15",
                "choices": [{"choice_ref": "price_category:premium"}],
            }
        ],
    )

    service._persist_turn_trace(
        request=request,
        turn={"turn_id": "turn_1", "tool_results": [], "llm_calls": []},
        rendered=rendered,
        turn_trace={"trace_id": "trace_1", "turn_id": "turn_1", "status": "completed"},
        delivery_result={"status": "success"},
        tagging_result={"tags_to_add": []},
        session_id="sess_1",
        request_id="req_1",
        trace_id="trace_1",
        user_id="user_1",
    )

    event = analytics.interaction_event_logs[-1]
    assert event["event_type"] == "surface_delivery_succeeded"
    assert event["surface_ref"] == "price_categories_abc123"
    assert event["tire_size"] == "195/60R15"


def test_api_runtime_does_not_emit_category_impression_without_cards():
    analytics = MemoryAnalyticsGateway()
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        delivery_mode="send_content",
        analytics_gateway=analytics,
    )
    rendered = RuntimeV7ChannelRender(
        response={"bubble1": "Pili po kayo ng category."},
        content_messages=[{"type": "text", "text": "Pili po kayo ng category."}],
        choice_presentations=[
            {
                "presentation_ref": "price_categories_abc123",
                "surface_type": "price_category_choices",
                "choice_type": "price_category",
                "tire_size": "195/60R15",
                "choices": [{"choice_ref": "price_category:premium"}],
            }
        ],
    )

    service._persist_turn_trace(
        request=RuntimeV7APIRequest(
            user_id="user_1",
            channel="manychat",
            user_text="Hi hm po 195 60 15",
            idempotency_key="message-1",
        ),
        turn={"turn_id": "turn_1", "tool_results": [], "llm_calls": []},
        rendered=rendered,
        turn_trace={"trace_id": "trace_1", "turn_id": "turn_1", "status": "completed"},
        delivery_result={"status": "success"},
        tagging_result={"tags_to_add": []},
        session_id="sess_1",
        request_id="req_1",
        trace_id="trace_1",
        user_id="user_1",
    )

    assert list(analytics.interaction_event_logs) == []


def test_api_runtime_emits_promo_product_progression_event():
    analytics = MemoryAnalyticsGateway()
    service = RuntimeV7APIService(
        sessions_gateway=object(),
        delivery_mode="send_content",
        analytics_gateway=analytics,
    )
    rendered = RuntimeV7ChannelRender(
        response={"bubble1": "Ito po ang Michelin options."},
        content_messages=[{"type": "text", "text": "Ito po ang Michelin options."}],
        product_presentations=[
            {
                "presentation_ref": "product_presentation_1",
                "cards": [
                    {
                        "card_ref": "product:7420",
                        "product_id": "7420",
                        "brand": "MICHELIN",
                        "tire_size": "175/65R14",
                    }
                ],
            }
        ],
    )

    service._persist_turn_trace(
        request=RuntimeV7APIRequest(
            user_id="user_1",
            channel="manychat",
            user_text="I selected Michelin.",
            idempotency_key="promo-click-1",
            flow_context={
                "promo_action_context": {
                    "status": "valid",
                    "catalog_version_id": "catalog-v1",
                    "card_id": "michelin-card-1",
                    "action": "check_price",
                    "selected_brand": "Michelin",
                    "promo": {"promo_id": "michelin-3-1"},
                },
                "promo_action_runtime_context": {
                    "trusted_tire_size": "175/65R14",
                },
            },
        ),
        turn={"turn_id": "turn_1", "tool_results": [], "llm_calls": []},
        rendered=rendered,
        turn_trace={"trace_id": "trace_1", "turn_id": "turn_1", "status": "completed"},
        delivery_result={"status": "success"},
        tagging_result={"tags_to_add": []},
        session_id="sess_1",
        request_id="req_1",
        trace_id="trace_1",
        user_id="user_1",
    )

    event = next(
        item
        for item in analytics.interaction_event_logs
        if item["event_type"] == "products_presented_from_choice"
    )
    assert event["surface_type"] == "promo_gallery"
    assert event["choice_ref"] == "check_price"
    assert event["promo_id"] == "michelin-3-1"
    assert event["tire_size"] == "175/65R14"
    assert event["details"] == {
        "product_presentation_refs": ["product_presentation_1"],
        "product_card_count": 1,
        "product_refs": ["product:7420"],
        "product_ids": ["7420"],
        "brands": ["MICHELIN"],
    }
