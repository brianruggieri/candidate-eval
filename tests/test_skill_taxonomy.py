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
    assert taxonomy.canonicalize("web-architecture") == "frontend-development"


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
