"""Contract tests for source-backed Runtime V7 brand knowledge."""

from __future__ import annotations

import json

from runtime_v7.brand_knowledge import (
    BrandKnowledgeRepository,
    BrandKnowledgeService,
    brand_knowledge_enabled,
    compact_brand_profile,
)
from runtime_v7.api_runtime import _response_seed_overrides_for_flow
from apps.api.routers.gulong import _promo_action_user_text
from runtime_v7.capability_profile import CapabilityProfile, build_capability_profile
from runtime_v7.model_contract import (
    CORE_SYSTEM_PROMPT,
    PROMO_TOOL_SCHEMAS,
    build_runtime_v7_system_prompt,
)
from runtime_v7.promo_catalog import PromoCatalogService
from runtime_v7.runtime_harness import (
    _prune_redundant_product_faq_for_brand_knowledge,
)
from scripts.brand_knowledge_sync import (
    build_profiles,
    extract_brand_directory,
    extract_warranty_policy,
)


def _directory_html(rows: list[dict]) -> str:
    escaped = json.dumps(rows).replace('"', '\\"')
    return f'<script>\\\"brands\\\":{escaped},\\\"brandsToday\\\":[]</script>'


def _apollo_row() -> dict:
    return {
        "id": 57,
        "brand": "APOLLO",
        "slug": "apollo",
        "about_brand": (
            "Established in 1972 in India, Apollo offers durable and "
            "fuel-saving tires for daily commuters."
        ),
        "warranty": "5 years",
        "warranty_year": 5,
        "origin_country": "India",
        "name": "Mid Range",
        "active": 1,
        "updated_at": "2025-11-06 19:02:17",
    }


def _apollo_detail_html() -> str:
    return """
    <html><body>
      <section id="warranty_policy">
        <h2>Warranty Coverage</h2>
        <p>Gulong.ph offers an unconditional warranty for normal driving
        conditions when installed by an authorized partner.</p>
        <h2>Warranty Period</h2>
        <p>This warranty is valid one (1) year from purchase.</p>
        <h2>Conditions for Warranty Claims</h2>
        <ul><li>Original purchaser only.</li><li>Proof of purchase is required.</li></ul>
        <h2>Claim Process</h2>
        <ol><li>Notify Gulong.ph.</li><li>Submit the claim form.</li></ol>
        <h2>Limitations</h2>
        <p>Replacement only; no cash conversion.</p>
      </section>
      <p>Unrelated footer content.</p>
    </body></html>
    """


def test_brand_knowledge_flag_is_explicit() -> None:
    assert brand_knowledge_enabled(value="1") is True
    assert brand_knowledge_enabled(value="true") is True
    assert brand_knowledge_enabled(value="0") is False
    assert brand_knowledge_enabled(value="") is False


def test_extract_brand_directory_reads_active_structured_profiles() -> None:
    rows = [
        _apollo_row(),
        {
            **_apollo_row(),
            "id": 99,
            "brand": "INACTIVE",
            "slug": "inactive",
            "active": 0,
        },
    ]

    result = extract_brand_directory(_directory_html(rows))

    assert [row["brand"] for row in result] == ["APOLLO"]
    assert result[0]["about_brand"].startswith("Established in 1972")


def test_extract_warranty_policy_keeps_structured_sections() -> None:
    policy = extract_warranty_policy(_apollo_detail_html())

    assert "unconditional warranty" in policy["coverage"][0]
    assert policy["period"] == [
        "This warranty is valid one (1) year from purchase."
    ]
    assert policy["conditions"] == [
        "Original purchaser only.",
        "Proof of purchase is required.",
    ]
    assert "Unrelated footer" not in json.dumps(policy)


def test_build_profiles_separates_product_and_gulong_warranties() -> None:
    profile = build_profiles(
        [_apollo_row()],
        {"apollo": _apollo_detail_html()},
    )[0]

    assert profile["manufacturer_warranty"]["duration_years"] == 5
    assert profile["manufacturer_warranty"]["display"] == "5 years"
    assert profile["manufacturer_warranty"]["scope"] == (
        "brand_product_warranty"
    )
    assert "start_date" in profile["manufacturer_warranty"][
        "unpublished_fields"
    ]
    assert profile["gulong_guarantee"]["duration_years"] == 1
    assert "from purchase" in profile["gulong_guarantee"][
        "period_text"
    ]
    assert profile["gulong_guarantee"]["conditions"] == [
        "Original purchaser only.",
        "Proof of purchase is required.",
    ]
    assert (
        profile["gulong_guarantee"]["scope"]
        == "gulong_unconditional_damage_warranty"
    )


def test_compact_profile_preserves_sources_and_bounds_policy() -> None:
    profile = build_profiles(
        [_apollo_row()],
        {"apollo": _apollo_detail_html()},
    )[0]
    profile.update(
        {
            "version_id": "brand-v1",
            "evidence_refs": ["brand_source:abc:apollo"],
        }
    )

    compact = compact_brand_profile(profile)

    assert compact["profile_ref"] == "brand_profile:brand-v1:apollo"
    assert compact["origin_country"] == "India"
    assert compact["manufacturer_warranty"]["duration_years"] == 5
    assert compact["gulong_guarantee"]["duration_years"] == 1
    assert compact["gulong_guarantee"]["conditions"] == [
        "Original purchaser only.",
        "Proof of purchase is required.",
    ]
    assert "brand_source:abc:apollo" in compact["evidence_refs"]


def test_typed_named_brand_exposes_published_brand_authority() -> None:
    profile = build_capability_profile(
        current_user_message=(
            "Covered ba Apollo manufacturer warranty kapag may factory defect?"
        ),
        background_signals=[
            {
                "key": "required_brands",
                "value": "APOLLO",
                "source": "latest_user_message",
            }
        ],
        default_domains=(),
    )
    _prune_redundant_product_faq_for_brand_knowledge(profile)

    assert "get_brand_knowledge" in profile.candidate_tools
    assert "get_brand_knowledge" in profile.exposed_tools
    assert "answer_product_faq" not in profile.exposed_tools
    assert profile.matched_signal_keys["get_brand_knowledge"] == ["required_brands"]


def test_named_brand_phrase_does_not_change_capability_without_typed_state() -> None:
    warranty_profile = build_capability_profile(
        current_user_message="Apollo warranty?",
        background_signals=[],
        default_domains=(),
    )
    runflat_profile = build_capability_profile(
        current_user_message="May Apollo run-flat tire ba?",
        background_signals=[],
        default_domains=(),
    )

    assert warranty_profile.candidate_tools == runflat_profile.candidate_tools
    assert warranty_profile.selected_domains == runflat_profile.selected_domains
    assert warranty_profile.exposed_tools == runflat_profile.exposed_tools


class _FakeBrandRepository:
    def __init__(self) -> None:
        self.profile_payload = {
            **build_profiles(
                [_apollo_row()],
                {"apollo": _apollo_detail_html()},
            )[0],
            "version_id": "brand-v1",
            "status": "published",
            "enabled": True,
            "evidence_refs": ["brand_source:abc:apollo"],
        }

    def active_config(self) -> dict:
        return {"brand_knowledge_version_id": "brand-v1"}

    def profile(self, *, version_id: str, brand: str) -> dict:
        assert version_id == "brand-v1"
        return (
            dict(self.profile_payload)
            if brand.casefold() == "apollo"
            else {}
        )

    def semantic_profiles(
        self,
        *,
        version_id: str,
        query_text: str,
        limit: int,
    ) -> list[dict]:
        assert version_id == "brand-v1"
        assert query_text
        assert limit == 4
        return [dict(self.profile_payload)]


def test_service_uses_exact_profile_and_reports_missing_brand() -> None:
    service = BrandKnowledgeService(_FakeBrandRepository())  # type: ignore[arg-type]

    result = service.get_brand_knowledge(
        {
            "query": "Compare Apollo and Unknown",
            "brands": ["Apollo", "Unknown"],
            "_customer_query_text": "Compare Apollo and Unknown",
        }
    )

    assert result["status"] == "ok"
    assert [profile["brand"] for profile in result["profiles"]] == [
        "APOLLO"
    ]
    assert result["missing_brands"] == ["Unknown"]
    assert result["rejected_proposed_brands"] == []
    assert (
        result["profiles"][0]["manufacturer_warranty"]["duration_years"]
        == 5
    )


def test_about_brand_profile_is_informational_source_evidence() -> None:
    service = BrandKnowledgeService(_FakeBrandRepository())  # type: ignore[arg-type]

    profile = service.profile_for_brand("Apollo")

    assert profile["about_brand"].startswith("Established in 1972")
    assert profile["profile_ref"] == "brand_profile:brand-v1:apollo"
    assert "promo" not in profile["about_brand"].casefold()


def test_model_added_brand_is_not_treated_as_customer_scope() -> None:
    service = BrandKnowledgeService(_FakeBrandRepository())  # type: ignore[arg-type]

    result = service.get_brand_knowledge(
        {
            "query": "Tell me about this tire brand",
            "brands": ["Apollo"],
            "_customer_query_text": "Tell me about this tire brand",
        }
    )

    assert result["rejected_proposed_brands"] == ["Apollo"]


def test_semantic_provider_failure_uses_bounded_lexical_fallback(
    monkeypatch,
) -> None:
    class _FailingEmbedder:
        def embed(self, text: str, *, task_type: str) -> list[float]:
            raise RuntimeError("temporary_embedding_failure")

    repository = BrandKnowledgeRepository(
        firestore_client=object(),
        embedder=_FailingEmbedder(),
    )
    fallback = [{"brand": "APOLLO", "retrieval_method": "lexical_fallback"}]
    monkeypatch.setattr(
        repository,
        "_lexical_profiles",
        lambda **kwargs: fallback,
    )

    result = repository.semantic_profiles(
        version_id="brand-v1",
        query_text="value daily commuter",
        limit=4,
    )

    assert result == fallback


class _FakePromoRepository:
    def active_config(self) -> dict:
        return {"catalog_version_id": "catalog-v1"}

    def list_cards(self, catalog_version_id: str) -> list[dict]:
        assert catalog_version_id == "catalog-v1"
        return [
            {
                "catalog_version_id": "catalog-v1",
                "promo_id": "apollo-promo",
                "title": "Apollo Promo",
                "brands": ["Apollo"],
                "offer_summary": "Reviewed offer.",
                "status": "published",
                "enabled": True,
                "display_cards": [
                    {
                        "card_id": "apollo-card",
                        "buttons": [
                            {
                                "action": "about_brand",
                                "selected_brand": "Apollo",
                            }
                        ],
                    }
                ],
            }
        ]

    def mechanics_for_promos(
        self,
        *,
        catalog_version_id: str,
        promo_ids: list[str],
    ) -> dict:
        assert catalog_version_id == "catalog-v1"
        return {promo_id: [] for promo_id in promo_ids}

    def brand_profile(self, *, catalog_version_id: str, brand: str) -> dict:
        raise AssertionError("promo-derived profile must not be consulted")


def test_about_brand_action_uses_published_brand_knowledge() -> None:
    knowledge = BrandKnowledgeService(_FakeBrandRepository())  # type: ignore[arg-type]
    service = PromoCatalogService(
        _FakePromoRepository(),  # type: ignore[arg-type]
        brand_knowledge=knowledge,
    )

    result = service.validate_action(
        {
            "catalog_version_id": "catalog-v1",
            "promo_id": "apollo-promo",
            "card_id": "apollo-card",
            "action": "about_brand",
            "selected_brand": "Apollo",
        }
    )

    assert result["status"] == "valid"
    assert result["brand_profile"]["about_brand"].startswith(
        "Established in 1972"
    )
    assert (
        result["brand_profile"]["profile_ref"]
        == "brand_profile:brand-v1:apollo"
    )


def test_about_brand_seed_exposes_source_background_to_composer() -> None:
    profile = BrandKnowledgeService(
        _FakeBrandRepository()  # type: ignore[arg-type]
    ).profile_for_brand("Apollo")

    seed = _response_seed_overrides_for_flow(
        {
            "promo_action_context": {
                "status": "valid",
                "action": "about_brand",
                "selected_brand": "Apollo",
                "brand_profile": profile,
            }
        }
    )[0]

    assert "gulong_brand_knowledge" in seed["guidance"]
    assert "Established in 1972" in seed["guidance"]
    assert "background is not available" not in seed["guidance"]
    assert "not a brand, product, quantity" in seed["guidance"]
    assert "This general About Brand action is not a warranty question" in (
        seed["guidance"]
    )
    assert "mention only the published" in seed["guidance"]
    assert "unless the customer explicitly asks" in seed["guidance"]


def test_about_brand_synthetic_text_cannot_mean_customer_review() -> None:
    text = _promo_action_user_text(
        {
            "status": "valid",
            "action": "about_brand",
            "selected_brand": "Apollo",
            "promo": {"title": "Apollo Promo"},
        }
    )

    assert "About Brand" in text
    assert "Apollo" not in text
    assert "not submitting a customer review or feedback" in text


def test_general_brand_comparison_is_not_gated_on_tire_size() -> None:
    brand_tool = next(
        item["function"]
        for item in PROMO_TOOL_SCHEMAS
        if item["function"]["name"] == "get_brand_knowledge"
    )

    prompt = " ".join(build_runtime_v7_system_prompt(["product"]).split())
    assert "does not require a tire size" in prompt
    assert "answer the information request first" in prompt
    assert "fit, current stock, exact price" in prompt
    assert "does not require a tire size" in brand_tool["description"]


def test_qualitative_tire_advice_uses_expertise_without_weak_refusal() -> None:
    prompt = " ".join(build_runtime_v7_system_prompt(["product"]).split())

    assert "Ordinary tire expertise is part of your role" in prompt
    assert "road noise, comfort, wet-road use, long drives" in prompt
    assert "reason practically instead of refusing" in prompt
    assert "published brand knowledge and trusted product details" in prompt
    assert "do not invent a measured test result" in prompt


def test_tire_quantity_voice_prefers_pcs_or_tires_over_formal_piraso() -> None:
    prompt = " ".join(CORE_SYSTEM_PROMPT.split())

    assert '"4 pcs" or "4 tires"' in prompt
    assert 'Avoid the more formal-sounding "piraso"' in prompt


def test_brand_authority_prunes_unrelated_generic_product_faq() -> None:
    profile = CapabilityProfile(
        candidate_tools=["get_brand_knowledge", "product_search"],
        exposed_tools=[
            "get_brand_knowledge",
            "product_search",
            "answer_product_faq",
        ],
        available_context_refs={
            "product_observation": False,
            "product_presentation": False,
        },
        faq_hints=[
            {"suggested_tool": "answer_service_faq"},
        ],
    )

    _prune_redundant_product_faq_for_brand_knowledge(profile)

    assert "get_brand_knowledge" in profile.exposed_tools
    assert "answer_product_faq" not in profile.exposed_tools
    assert (
        "brand_knowledge:generic_product_faq_redundant"
        in profile.selection_reasons
    )


def test_named_brand_authority_prunes_generic_product_faq_hint() -> None:
    profile = CapabilityProfile(
        candidate_tools=["get_brand_knowledge", "answer_product_faq"],
        exposed_tools=["get_brand_knowledge", "answer_product_faq"],
        available_context_refs={},
        faq_hints=[
            {"suggested_tool": "answer_product_faq"},
        ],
    )

    _prune_redundant_product_faq_for_brand_knowledge(profile)

    assert "answer_product_faq" not in profile.exposed_tools


def test_selected_product_keeps_product_faq_available() -> None:
    profile = CapabilityProfile(
        candidate_tools=["get_brand_knowledge", "answer_product_faq"],
        exposed_tools=["get_brand_knowledge", "answer_product_faq"],
        available_context_refs={},
        faq_hints=[],
    )

    _prune_redundant_product_faq_for_brand_knowledge(
        profile,
        selected_product_context={"item_ref": "item_apollo_1"},
    )

    assert "answer_product_faq" in profile.exposed_tools


def test_brand_composer_guidance_requires_complete_gulong_conditions() -> None:
    prompt = " ".join(build_runtime_v7_system_prompt(["product"]).split())

    assert "preserve all published eligibility conditions" in prompt
    assert "state only the policy duration" in prompt
