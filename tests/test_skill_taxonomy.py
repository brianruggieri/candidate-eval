"""Tests for SkillTaxonomy: alias resolution, fuzzy matching, and skill relationships."""

from __future__ import annotations

import pytest

from claude_candidate.skill_taxonomy import SkillTaxonomy


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def taxonomy() -> SkillTaxonomy:
    """Load the default bundled taxonomy once for the module."""
    return SkillTaxonomy.load_default()


# ---------------------------------------------------------------------------
# Exact canonical lookup
# ---------------------------------------------------------------------------

def test_canonical_exact_self(taxonomy: SkillTaxonomy) -> None:
    """A canonical name resolves to itself."""
    assert taxonomy.canonicalize("python") == "python"


def test_canonical_exact_several(taxonomy: SkillTaxonomy) -> None:
    """Multiple canonical names resolve to themselves."""
    for name in ("typescript", "rust", "go", "redis", "sql"):
        assert taxonomy.canonicalize(name) == name


# ---------------------------------------------------------------------------
# Alias resolution
# ---------------------------------------------------------------------------

def test_alias_py_to_python(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("py") == "python"


def test_alias_k8s_to_kubernetes(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("k8s") == "kubernetes"


def test_alias_reactjs_to_react(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("react.js") == "react"


def test_alias_ts_to_typescript(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("ts") == "typescript"


def test_alias_node_to_nodejs(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("node") == "node.js"


def test_alias_postgres_to_postgresql(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("postgres") == "postgresql"


def test_alias_golang_to_go(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("golang") == "go"


def test_alias_ml_to_machine_learning(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("ml") == "machine-learning"


def test_alias_tf_to_terraform(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("tf") == "terraform"


def test_alias_github_actions_to_ci_cd(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("github-actions") == "ci-cd"


# ---------------------------------------------------------------------------
# Case insensitivity
# ---------------------------------------------------------------------------

def test_case_python_upper(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("Python") == "python"


def test_case_typescript_all_caps(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("TYPESCRIPT") == "typescript"


def test_case_k8s_mixed(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("K8S") == "kubernetes"


def test_case_react_title(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("React") == "react"


# ---------------------------------------------------------------------------
# Unknown skill returns lowered input
# ---------------------------------------------------------------------------

def test_unknown_skill_passthrough(taxonomy: SkillTaxonomy) -> None:
    """canonicalize() returns the lowercased input for unknown skills."""
    assert taxonomy.canonicalize("banana") == "banana"


def test_unknown_skill_mixed_case_passthrough(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("FooBarBaz") == "foobarbaz"


# ---------------------------------------------------------------------------
# Fuzzy matching via match()
# ---------------------------------------------------------------------------

def test_fuzzy_javascript_typo(taxonomy: SkillTaxonomy) -> None:
    """Typo in javascript should still resolve."""
    result = taxonomy.match("javascrpt")
    assert result == "javascript"


def test_fuzzy_kubernetes_typo(taxonomy: SkillTaxonomy) -> None:
    """Typo in kubernetes should still resolve."""
    result = taxonomy.match("kuberntes")
    assert result == "kubernetes"


def test_fuzzy_python_typo(taxonomy: SkillTaxonomy) -> None:
    # "pyhton" scores ~83 on token_set_ratio, below threshold 90
    result = taxonomy.match("pyhton")
    assert result is None


def test_fuzzy_returns_none_for_unrelated(taxonomy: SkillTaxonomy) -> None:
    """Totally unrelated term returns None."""
    assert taxonomy.match("banana") is None


def test_fuzzy_returns_none_for_gibberish(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.match("xyzqwerty123") is None


def test_match_prefers_exact_over_fuzzy(taxonomy: SkillTaxonomy) -> None:
    """Exact alias should win over any fuzzy candidate."""
    # "py" is an exact alias for python; must not fuzzy-resolve to something else
    assert taxonomy.match("py") == "python"


def test_match_exact_canonical(taxonomy: SkillTaxonomy) -> None:
    """match() on an exact canonical name returns that canonical name."""
    assert taxonomy.match("python") == "python"
    assert taxonomy.match("rust") == "rust"


# ---------------------------------------------------------------------------
# get_related
# ---------------------------------------------------------------------------

def test_get_related_python(taxonomy: SkillTaxonomy) -> None:
    related = taxonomy.get_related("python")
    assert "fastapi" in related
    assert "pytest" in related


def test_get_related_via_alias(taxonomy: SkillTaxonomy) -> None:
    """get_related resolves aliases before lookup."""
    related_via_alias = taxonomy.get_related("py")
    related_canonical = taxonomy.get_related("python")
    assert related_via_alias == related_canonical


def test_get_related_unknown_returns_empty(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_related("banana") == []


def test_get_related_react(taxonomy: SkillTaxonomy) -> None:
    related = taxonomy.get_related("react")
    assert "javascript" in related
    assert "typescript" in related


# ---------------------------------------------------------------------------
# get_category
# ---------------------------------------------------------------------------

def test_get_category_python_is_language(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("python") == "language"


def test_get_category_react_is_framework(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("react") == "framework"


def test_get_category_kubernetes_is_platform(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("kubernetes") == "platform"


def test_get_category_via_alias(taxonomy: SkillTaxonomy) -> None:
    """Alias resolves before category lookup."""
    assert taxonomy.get_category("k8s") == "platform"


def test_get_category_unknown_returns_none(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("banana") is None


# ---------------------------------------------------------------------------
# are_related
# ---------------------------------------------------------------------------

def test_are_related_python_fastapi(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.are_related("python", "fastapi") is True


def test_are_related_is_symmetric(taxonomy: SkillTaxonomy) -> None:
    """are_related must be symmetric."""
    assert taxonomy.are_related("fastapi", "python") is True


def test_are_related_parent_child(taxonomy: SkillTaxonomy) -> None:
    """Parent/child relationships count as related."""
    # nextjs has parent: react
    assert taxonomy.are_related("nextjs", "react") is True
    assert taxonomy.are_related("react", "nextjs") is True


def test_are_related_via_aliases(taxonomy: SkillTaxonomy) -> None:
    """Aliases are resolved before checking relatedness."""
    assert taxonomy.are_related("py", "fastapi") is True
    assert taxonomy.are_related("k8s", "docker") is True


def test_are_related_unrelated_skills(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.are_related("rust", "react") is False


def test_are_related_self(taxonomy: SkillTaxonomy) -> None:
    """A skill is not explicitly related to itself (no self-loop in data)."""
    # This just checks it doesn't crash; result depends on taxonomy data
    result = taxonomy.are_related("python", "python")
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Soft skill category
# ---------------------------------------------------------------------------

def test_soft_skill_category(taxonomy: SkillTaxonomy) -> None:
    """Soft skill entries should have category 'soft_skill'."""
    assert taxonomy.get_category("communication") == "soft_skill"
    assert taxonomy.get_category("collaboration") == "soft_skill"
    assert taxonomy.get_category("leadership") == "soft_skill"
    # Aliases should resolve
    assert taxonomy.match("excellent communication") == "communication"
    assert taxonomy.match("team player") == "collaboration"


# ---------------------------------------------------------------------------
# Promoted entries — canonical resolution
# ---------------------------------------------------------------------------

def test_canonical_ai_research(taxonomy: SkillTaxonomy) -> None:
    """ai-research is now its own entry, not an alias of adaptability."""
    assert taxonomy.canonicalize("ai-research") == "ai-research"
    assert taxonomy.canonicalize("ai_research") == "ai-research"
    assert taxonomy.get_category("ai-research") == "domain"


def test_canonical_ai_safety(taxonomy: SkillTaxonomy) -> None:
    """ai-safety is now its own entry, not an alias of security."""
    assert taxonomy.canonicalize("ai-safety") == "ai-safety"
    assert taxonomy.canonicalize("responsible-ai") == "ai-safety"
    assert taxonomy.canonicalize("responsible_ai") == "ai-safety"
    assert taxonomy.get_category("ai-safety") == "practice"


def test_canonical_computer_vision(taxonomy: SkillTaxonomy) -> None:
    """computer-vision is now its own entry, not an alias of machine-learning."""
    assert taxonomy.canonicalize("computer-vision") == "computer-vision"
    assert taxonomy.get_category("computer-vision") == "domain"
    assert taxonomy.are_related("computer-vision", "machine-learning")


def test_canonical_multimodal_ai(taxonomy: SkillTaxonomy) -> None:
    """multimodal-ai is now its own entry, not an alias of machine-learning."""
    assert taxonomy.canonicalize("multimodal-ai") == "multimodal-ai"
    assert taxonomy.canonicalize("multimodal_ai") == "multimodal-ai"
    assert taxonomy.get_category("multimodal-ai") == "domain"


def test_canonical_voice_ai(taxonomy: SkillTaxonomy) -> None:
    """voice-ai is now its own entry, not an alias of machine-learning."""
    assert taxonomy.canonicalize("voice-ai") == "voice-ai"
    assert taxonomy.canonicalize("conversational-ai") == "voice-ai"
    assert taxonomy.get_category("voice-ai") == "domain"


def test_canonical_graphql(taxonomy: SkillTaxonomy) -> None:
    """graphql is now its own entry, not an alias of api-design."""
    assert taxonomy.canonicalize("graphql") == "graphql"
    assert taxonomy.get_category("graphql") == "framework"
    assert taxonomy.are_related("graphql", "api-design")


def test_canonical_langgraph(taxonomy: SkillTaxonomy) -> None:
    """langgraph is now its own entry, not an alias of langchain."""
    assert taxonomy.canonicalize("langgraph") == "langgraph"
    assert taxonomy.get_category("langgraph") == "framework"
    assert taxonomy.are_related("langgraph", "langchain")


def test_canonical_langsmith(taxonomy: SkillTaxonomy) -> None:
    """langsmith is now its own entry, not an alias of langchain."""
    assert taxonomy.canonicalize("langsmith") == "langsmith"
    assert taxonomy.get_category("langsmith") == "tool"
    assert taxonomy.are_related("langsmith", "langchain")


def test_canonical_code_review(taxonomy: SkillTaxonomy) -> None:
    """code-review is now its own entry, not an alias of testing."""
    assert taxonomy.canonicalize("code-review") == "code-review"
    assert taxonomy.canonicalize("code_review") == "code-review"
    assert taxonomy.canonicalize("code review") == "code-review"
    assert taxonomy.get_category("code-review") == "practice"


def test_canonical_ai_evaluation(taxonomy: SkillTaxonomy) -> None:
    """ai-evaluation is now its own entry, not an alias of metrics."""
    assert taxonomy.canonicalize("ai-evaluation") == "ai-evaluation"
    assert taxonomy.canonicalize("ai_evaluation") == "ai-evaluation"
    assert taxonomy.canonicalize("llm-evaluation") == "ai-evaluation"
    assert taxonomy.get_category("ai-evaluation") == "practice"


def test_canonical_data_engineering(taxonomy: SkillTaxonomy) -> None:
    """data-engineering is a new entry."""
    assert taxonomy.canonicalize("data-engineering") == "data-engineering"
    assert taxonomy.canonicalize("data engineering") == "data-engineering"
    assert taxonomy.get_category("data-engineering") == "domain"


# ---------------------------------------------------------------------------
# Alias removals — ensure old bad mappings are gone
# ---------------------------------------------------------------------------

def test_curiosity_not_adaptability(taxonomy: SkillTaxonomy) -> None:
    """curiosity should no longer resolve to adaptability."""
    assert taxonomy.canonicalize("curiosity") != "adaptability"


def test_ai_research_not_adaptability(taxonomy: SkillTaxonomy) -> None:
    """ai-research should no longer resolve to adaptability."""
    assert taxonomy.canonicalize("ai-research") != "adaptability"


def test_ai_safety_not_security(taxonomy: SkillTaxonomy) -> None:
    """ai-safety should no longer resolve to security."""
    assert taxonomy.canonicalize("ai-safety") != "security"


def test_graphql_not_api_design(taxonomy: SkillTaxonomy) -> None:
    """graphql should no longer resolve to api-design."""
    assert taxonomy.canonicalize("graphql") != "api-design"


def test_code_review_not_testing(taxonomy: SkillTaxonomy) -> None:
    """code-review should no longer resolve to testing."""
    assert taxonomy.canonicalize("code-review") != "testing"


# ---------------------------------------------------------------------------
# Explicit aliases — formerly fuzzy, now exact
# ---------------------------------------------------------------------------

def test_alias_developer_tooling(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("developer_tooling") == "developer-tools"


def test_alias_rest_api(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("rest_api") == "api-design"


def test_alias_multi_agent_orchestration(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("multi-agent-orchestration") == "agentic-workflows"


def test_alias_ai_assisted_development(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("ai-assisted-development") == "agentic-workflows"
    assert taxonomy.canonicalize("ai_assisted_development") == "agentic-workflows"


def test_alias_ai_tools(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("ai-tools") == "developer-tools"
    assert taxonomy.canonicalize("ai_tools") == "developer-tools"


def test_alias_large_scale_systems(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("large-scale-systems") == "performance-optimization"


def test_alias_cloud_ai_platforms(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("cloud-ai-platforms") == "cloud-infrastructure"


def test_alias_production_deployment(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("production-deployment") == "production-systems"


def test_alias_web_architecture(taxonomy: SkillTaxonomy) -> None:
    # web-architecture moved from frontend-development to system-design (plan-10 misroute fix)
    assert taxonomy.canonicalize("web-architecture") == "system-design"
    assert taxonomy.canonicalize("web architecture") == "system-design"


def test_alias_cross_browser_development(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("cross-browser-development") == "frontend-development"


def test_alias_llm_integration(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("llm-integration") == "llm"


# ---------------------------------------------------------------------------
# Fuzzy threshold — verify threshold is at 90
# ---------------------------------------------------------------------------

def test_fuzzy_threshold_is_90() -> None:
    """Verify FUZZY_THRESHOLD has been raised to 90."""
    from claude_candidate.skill_taxonomy import FUZZY_THRESHOLD
    assert FUZZY_THRESHOLD == 90


def test_fuzzy_still_catches_typos(taxonomy: SkillTaxonomy) -> None:
    """Typos with score >= 90 should still resolve."""
    assert taxonomy.match("javascrpt") == "javascript"
    assert taxonomy.match("kuberntes") == "kubernetes"
    # "pyhton" scores ~83 (below 90), so it no longer resolves via fuzzy
    assert taxonomy.match("pyhton") is None


def test_fuzzy_rejects_false_positives(taxonomy: SkillTaxonomy) -> None:
    """Terms that previously fuzzy-matched at 80-89 should no longer resolve."""
    # production-deployment should NOT fuzzy-match to product-development
    # (it should exact-match to production-systems via new alias)
    result = taxonomy.match("production-deployment")
    assert result == "production-systems"


# ---------------------------------------------------------------------------
# Plan-10 new entries — alias resolution
# ---------------------------------------------------------------------------

def test_alias_rtk_query_to_redux(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("rtk_query") == "redux"
    assert taxonomy.canonicalize("rtk-query") == "redux"
    assert taxonomy.canonicalize("redux-toolkit") == "redux"


def test_alias_webassembly_to_wasm(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("webassembly") == "wasm"
    assert taxonomy.canonicalize("web-assembly") == "wasm"


def test_alias_react_query_to_tanstack(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("react-query") == "tanstack"
    assert taxonomy.canonicalize("tanstack-query") == "tanstack"


def test_alias_mobile_development_to_react_native(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("react native") == "react-native"
    assert taxonomy.canonicalize("mobile-development") == "react-native"
    assert taxonomy.canonicalize("mobile web") == "react-native"


def test_alias_genai_to_generative_ai(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("generative_ai") == "generative-ai"
    assert taxonomy.canonicalize("genai") == "generative-ai"
    assert taxonomy.canonicalize("applied_ai") == "generative-ai"
    assert taxonomy.canonicalize("artificial-intelligence") == "generative-ai"
    assert taxonomy.canonicalize("ai") == "generative-ai"


def test_alias_user_research_variants(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("user research") == "user-research"
    assert taxonomy.canonicalize("user_research") == "user-research"
    assert taxonomy.canonicalize("ux-research") == "user-research"
    assert taxonomy.canonicalize("user-empathy") == "user-research"
    assert taxonomy.canonicalize("user_centered_design") == "user-research"


def test_alias_concurrent_programming_variants(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("concurrency") == "concurrent-programming"
    assert taxonomy.canonicalize("multithreading") == "concurrent-programming"
    assert taxonomy.canonicalize("parallelism") == "concurrent-programming"
    assert taxonomy.canonicalize("async-programming") == "concurrent-programming"


def test_alias_real_time_graphics_variants(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("real_time_graphics") == "real-time-graphics"
    assert taxonomy.canonicalize("real-time-rendering") == "real-time-graphics"
    assert taxonomy.canonicalize("graphics_programming") == "real-time-graphics"
    assert taxonomy.canonicalize("computer_graphics") == "real-time-graphics"
    assert taxonomy.canonicalize("shader_programming") == "real-time-graphics"
    assert taxonomy.canonicalize("gpu_programming") == "real-time-graphics"
    assert taxonomy.canonicalize("rendering") == "real-time-graphics"


def test_alias_virtual_production_variants(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("virtual_production") == "virtual-production"
    assert taxonomy.canonicalize("vr") == "virtual-production"
    assert taxonomy.canonicalize("xr") == "virtual-production"
    assert taxonomy.canonicalize("webxr") == "virtual-production"
    assert taxonomy.canonicalize("virtual_reality") == "virtual-production"


def test_alias_ux_design_variants(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("ux_design") == "ux-design"
    assert taxonomy.canonicalize("user experience") == "ux-design"
    assert taxonomy.canonicalize("user_experience") == "ux-design"
    assert taxonomy.canonicalize("ux_understanding") == "ux-design"
    assert taxonomy.canonicalize("user_facing_software") == "ux-design"


def test_alias_state_management_variants(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("state management") == "state-management"
    assert taxonomy.canonicalize("state_management") == "state-management"
    assert taxonomy.canonicalize("global state") == "state-management"


def test_alias_functional_programming_variants(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("functional programming") == "functional-programming"
    assert taxonomy.canonicalize("functional_programming") == "functional-programming"
    assert taxonomy.canonicalize("immutability") == "functional-programming"
    assert taxonomy.canonicalize("fp") == "functional-programming"


def test_alias_ecommerce_variants(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("ecommerce") == "e-commerce"
    assert taxonomy.canonicalize("commerce") == "e-commerce"
    assert taxonomy.canonicalize("digital-commerce") == "e-commerce"


def test_alias_sandboxing_variants(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("sandbox") == "sandboxing"
    assert taxonomy.canonicalize("isolation") == "sandboxing"
    assert taxonomy.canonicalize("process-isolation") == "sandboxing"


def test_alias_accessibility_variants(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("a11y") == "accessibility"
    assert taxonomy.canonicalize("wcag") == "accessibility"
    assert taxonomy.canonicalize("aria") == "accessibility"
    assert taxonomy.canonicalize("web-accessibility") == "accessibility"


def test_alias_animation_variants(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("web-animation") == "animation"
    assert taxonomy.canonicalize("motion-design") == "animation"
    assert taxonomy.canonicalize("motion-graphics") == "animation"
    assert taxonomy.canonicalize("canvas") == "animation"


# ---------------------------------------------------------------------------
# Plan-10 new entries — categories
# ---------------------------------------------------------------------------

def test_category_e_commerce(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("e-commerce") == "domain"


def test_category_state_management(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("state-management") == "practice"


def test_category_redux(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("redux") == "framework"


def test_category_tanstack(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("tanstack") == "framework"


def test_category_wasm(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("wasm") == "domain"


def test_category_functional_programming(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("functional-programming") == "practice"


def test_category_user_research(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("user-research") == "practice"


def test_category_sandboxing(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("sandboxing") == "practice"


def test_category_concurrent_programming(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("concurrent-programming") == "practice"


def test_category_real_time_graphics(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("real-time-graphics") == "domain"


def test_category_virtual_production(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("virtual-production") == "domain"


def test_category_ux_design(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("ux-design") == "practice"


def test_category_react_native(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("react-native") == "framework"


def test_category_generative_ai(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("generative-ai") == "domain"


def test_category_accessibility(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("accessibility") == "practice"


def test_category_animation(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.get_category("animation") == "domain"


# ---------------------------------------------------------------------------
# Plan-10 new entries — relationships
# ---------------------------------------------------------------------------

def test_redux_related_to_react(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.are_related("redux", "react")


def test_tanstack_related_to_react(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.are_related("tanstack", "react")


def test_react_native_related_to_react(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.are_related("react-native", "react")


def test_wasm_related_to_rust(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.are_related("wasm", "rust")


def test_wasm_related_to_webgl(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.are_related("wasm", "webgl")


def test_real_time_graphics_related_to_unity(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.are_related("real-time-graphics", "unity")


def test_real_time_graphics_related_to_webgl(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.are_related("real-time-graphics", "webgl")


def test_virtual_production_related_to_unity(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.are_related("virtual-production", "unity")


def test_generative_ai_parent_is_machine_learning(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.are_related("generative-ai", "machine-learning")


def test_generative_ai_related_to_llm(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.are_related("generative-ai", "llm")


def test_ux_design_related_to_user_research(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.are_related("ux-design", "user-research")


def test_state_management_related_to_react(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.are_related("state-management", "react")


def test_concurrent_programming_related_to_distributed_systems(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.are_related("concurrent-programming", "distributed-systems")


def test_data_engineering_related_to_data_science(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.are_related("data-engineering", "data-science")


# ---------------------------------------------------------------------------
# Plan-10 misroute regression tests
# ---------------------------------------------------------------------------

def test_ux_engineering_resolves_correctly(taxonomy: SkillTaxonomy) -> None:
    """ux engineering was previously fuzzy-matching to prompt-engineering."""
    assert taxonomy.match("ux engineering") == "ux-design"


def test_ui_design_resolves_correctly(taxonomy: SkillTaxonomy) -> None:
    """ui design was previously fuzzy-matching to api-design."""
    assert taxonomy.match("ui design") == "ux-design"


def test_product_design_resolves_correctly(taxonomy: SkillTaxonomy) -> None:
    """product design now has explicit alias in product-development."""
    assert taxonomy.match("product design") == "product-development"
    assert taxonomy.canonicalize("product-design") == "product-development"


def test_data_engineering_not_mlops(taxonomy: SkillTaxonomy) -> None:
    """data engineering was previously fuzzy-matching to mlops."""
    assert taxonomy.match("data engineering") == "data-engineering"
    assert taxonomy.canonicalize("data engineering") == "data-engineering"


def test_sdk_development_resolves_to_developer_tools(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("sdk-development") == "developer-tools"


def test_ui_frameworks_resolves_to_frontend_development(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("ui-frameworks") == "frontend-development"
    assert taxonomy.canonicalize("ui frameworks") == "frontend-development"


def test_web_architecture_resolves_to_system_design(taxonomy: SkillTaxonomy) -> None:
    """web architecture was previously aliased to frontend-development; now moved to system-design."""
    assert taxonomy.canonicalize("web-architecture") == "system-design"
    assert taxonomy.canonicalize("web architecture") == "system-design"


# ---------------------------------------------------------------------------
# Plan-10 existing entry alias additions
# ---------------------------------------------------------------------------

def test_alias_rtk_query_collaboration(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("pair-programming") == "collaboration"
    assert taxonomy.canonicalize("pair programming") == "collaboration"
    assert taxonomy.canonicalize("customer_success") == "collaboration"


def test_alias_technical_consulting_communication(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("technical-consulting") == "communication"
    assert taxonomy.canonicalize("solutions-engineering") == "communication"
    assert taxonomy.canonicalize("technical_communication") == "communication"


def test_alias_product_strategy_product_development(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("product-strategy") == "product-development"
    assert taxonomy.canonicalize("product_roadmap") == "product-development"


def test_alias_entrepreneurship_startup_experience(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("entrepreneurship") == "startup-experience"
    assert taxonomy.canonicalize("founder-mentality") == "startup-experience"
    assert taxonomy.canonicalize("zero_to_one") == "startup-experience"


def test_alias_learning_science_edtech(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("learning-science") == "edtech"
    assert taxonomy.canonicalize("instructional-design") == "edtech"
    assert taxonomy.canonicalize("adaptive_learning") == "edtech"


def test_alias_embeddings_rag(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("embeddings") == "rag"
    assert taxonomy.canonicalize("semantic_search") == "rag"
    assert taxonomy.canonicalize("recommendation_systems") == "rag"


def test_alias_solution_architecture_system_design(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("solution-architecture") == "system-design"
    assert taxonomy.canonicalize("cloud-architecture") == "system-design"
    assert taxonomy.canonicalize("scalable_systems") == "system-design"


def test_alias_engineering_leadership_leadership(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("engineering-leadership") == "leadership"
    assert taxonomy.canonicalize("cross_functional_leadership") == "leadership"
    assert taxonomy.canonicalize("onboarding") == "leadership"


def test_alias_shipping_ownership(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("feature-ownership") == "ownership"
    assert taxonomy.canonicalize("shipping") == "ownership"
    assert taxonomy.canonicalize("accountability") == "ownership"


def test_alias_mission_driven_adaptability(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("self_motivation") == "adaptability"
    assert taxonomy.canonicalize("mission_driven") == "adaptability"
    assert taxonomy.canonicalize("mission_alignment") == "adaptability"


def test_alias_agentic_systems(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("agentic-systems") == "agentic-workflows"
    assert taxonomy.canonicalize("agentic_systems") == "agentic-workflows"
    assert taxonomy.canonicalize("agent-architecture") == "agentic-workflows"
    assert taxonomy.canonicalize("function-calling") == "agentic-workflows"
    assert taxonomy.canonicalize("mcp_servers") == "agentic-workflows"


def test_alias_claude_to_llm(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("claude") == "llm"
    assert taxonomy.canonicalize("gemini") == "llm"
    assert taxonomy.canonicalize("claude-code") == "llm"


def test_alias_diffusion_models_machine_learning(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("diffusion-models") == "machine-learning"
    assert taxonomy.canonicalize("fine_tuning") == "machine-learning"
    assert taxonomy.canonicalize("rlhf") == "machine-learning"
    assert taxonomy.canonicalize("lora") == "machine-learning"


def test_alias_inference_optimization_performance(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("inference-optimization") == "performance-optimization"
    assert taxonomy.canonicalize("inference_optimization") == "performance-optimization"
    assert taxonomy.canonicalize("high-traffic-systems") == "performance-optimization"


def test_alias_rate_limiting_security(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("rate-limiting") == "security"
    assert taxonomy.canonicalize("fault-tolerance") == "security"


def test_alias_e2e_testing_testing(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("e2e_testing") == "testing"
    assert taxonomy.canonicalize("testing_frameworks") == "testing"
    assert taxonomy.canonicalize("quality-assurance") == "testing"


def test_alias_opentelemetry_metrics(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("opentelemetry") == "metrics"
    assert taxonomy.canonicalize("datadog") == "metrics"
    assert taxonomy.canonicalize("grafana") == "metrics"
    assert taxonomy.canonicalize("prometheus") == "metrics"
    assert taxonomy.canonicalize("okrs") == "metrics"
    assert taxonomy.canonicalize("product_metrics") == "metrics"


def test_alias_hybrid_cloud_infrastructure(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("hybrid-cloud") == "cloud-infrastructure"
    assert taxonomy.canonicalize("edge-computing") == "cloud-infrastructure"
    assert taxonomy.canonicalize("infrastructure_as_code") == "cloud-infrastructure"


def test_alias_mlops_additions(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("ml-pipelines") == "mlops"
    assert taxonomy.canonicalize("ml_pipelines") == "mlops"
    assert taxonomy.canonicalize("weights-and-biases") == "mlops"
    assert taxonomy.canonicalize("mlflow") == "mlops"
    assert taxonomy.canonicalize("vertex_ai") == "mlops"


def test_alias_reliability_engineering_production_systems(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("reliability-engineering") == "production-systems"
    assert taxonomy.canonicalize("reliability_engineering") == "production-systems"
    assert taxonomy.canonicalize("feature_flags") == "production-systems"


def test_alias_game_development_additions(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("houdini") == "game-development"
    assert taxonomy.canonicalize("maya") == "game-development"
    assert taxonomy.canonicalize("unreal_engine") == "game-development"
    assert taxonomy.canonicalize("dcc_tools") == "game-development"


def test_alias_creative_tools_additions(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("film_production") == "creative-tools"
    assert taxonomy.canonicalize("media_industry") == "creative-tools"
    assert taxonomy.canonicalize("usd") == "creative-tools"
    assert taxonomy.canonicalize("artist_collaboration") == "creative-tools"


def test_alias_pandas_data_science(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("pandas") == "data-science"
    assert taxonomy.canonicalize("jupyter") == "data-science"
    assert taxonomy.canonicalize("jupyter_notebooks") == "data-science"
    assert taxonomy.canonicalize("scikit_learn") == "data-science"
    assert taxonomy.canonicalize("xgboost") == "data-science"


def test_alias_data_modeling_data_engineering(taxonomy: SkillTaxonomy) -> None:
    assert taxonomy.canonicalize("data-modeling") == "data-engineering"
    assert taxonomy.canonicalize("data-warehousing") == "data-engineering"
    assert taxonomy.canonicalize("pipeline-design") == "data-engineering"
    assert taxonomy.canonicalize("data_extraction") == "data-engineering"
