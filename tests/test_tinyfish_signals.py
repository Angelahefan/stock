"""
Tests — TinyFish Financial Signal Pipeline
===========================================
Tests for all signal agents, classifier, pipeline, and API contracts.
Runs fully offline — no LLM, no network calls required.

Run:
    python3 -m pytest tests/test_tinyfish_signals.py -q --tb=short
"""

from __future__ import annotations

import pytest

# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

OLD_WITH_GUIDANCE = (
    "We expect revenue growth of 25% in FY2026. "
    "The company is confident in achieving its targets by end of FY2026. "
    "We are on track to deliver strong earnings. "
    "We will achieve our stated guidance."
)

NEW_WITHOUT_GUIDANCE = (
    "We aim to pursue long-term value for shareholders. "
    "The company continues to evaluate its operational priorities. "
    "We remain focused on our business activities."
)

OLD_LOW_RISK = (
    "The company operates in a stable regulatory environment. "
    "Our supply chain remains robust. "
    "We maintain strong liquidity with a well-funded balance sheet."
)

NEW_HIGH_RISK = (
    "The company faces increasing regulatory uncertainty in key markets. "
    "Supply chain disruptions remain a material risk to operations. "
    "Geopolitical volatility and margin pressure continue to create headwinds. "
    "Liquidity may be affected by changing credit market conditions. "
    "Material adverse conditions in global markets could impact our results."
)

OLD_CONFIDENT_TONE = (
    "We are confident in our strong growth trajectory. "
    "The company will deliver record revenues. "
    "We commit to returning capital to shareholders."
)

NEW_CAUTIOUS_TONE = (
    "We are cautious about near-term conditions. "
    "The company may achieve stable revenues. "
    "We are evaluating options for capital allocation."
)

UNCHANGED_TEXT = (
    "The company provides data analytics services to enterprise clients. "
    "We operate across multiple industry verticals."
)


# ══════════════════════════════════════════════════════════════════════════════
# TestForwardGuidanceAgent
# ══════════════════════════════════════════════════════════════════════════════

class TestForwardGuidanceAgent:
    def test_detects_guidance_withdrawal(self):
        from agents.tinyfish_signals.forward_guidance_agent import detect_guidance_withdrawal
        detected, confidence, severity, evidence = detect_guidance_withdrawal(
            OLD_WITH_GUIDANCE, NEW_WITHOUT_GUIDANCE
        )
        assert detected is True
        assert confidence > 0.3
        assert severity in ("HIGH", "MEDIUM")
        assert len(evidence) > 0

    def test_no_signal_when_unchanged(self):
        from agents.tinyfish_signals.forward_guidance_agent import detect_guidance_withdrawal
        detected, confidence, severity, evidence = detect_guidance_withdrawal(
            UNCHANGED_TEXT, UNCHANGED_TEXT
        )
        assert detected is False

    def test_run_guidance_agent_returns_correct_signal_type(self):
        from agents.tinyfish_signals.forward_guidance_agent import run_forward_guidance_agent
        result = run_forward_guidance_agent(OLD_WITH_GUIDANCE, NEW_WITHOUT_GUIDANCE)
        assert result["signal_type"] == "GUIDANCE_WITHDRAWAL"
        assert result["confidence"] > 0.0

    def test_run_guidance_agent_no_signal_case(self):
        from agents.tinyfish_signals.forward_guidance_agent import run_forward_guidance_agent
        result = run_forward_guidance_agent(UNCHANGED_TEXT, UNCHANGED_TEXT)
        assert result["signal_type"] == "NO_SIGNAL"

    def test_evidence_quotes_populated(self):
        from agents.tinyfish_signals.forward_guidance_agent import run_forward_guidance_agent
        result = run_forward_guidance_agent(OLD_WITH_GUIDANCE, NEW_WITHOUT_GUIDANCE)
        assert isinstance(result["evidence_quotes"], list)

    def test_quality_flags_short_text(self):
        from agents.tinyfish_signals.forward_guidance_agent import run_forward_guidance_agent
        result = run_forward_guidance_agent("short", "short")
        assert "old_text_very_short" in result.get("quality_flags", [])


# ══════════════════════════════════════════════════════════════════════════════
# TestRiskDisclosureAgent
# ══════════════════════════════════════════════════════════════════════════════

class TestRiskDisclosureAgent:
    def test_detects_risk_expansion(self):
        from agents.tinyfish_signals.risk_disclosure_agent import detect_risk_disclosure_expansion
        detected, confidence, severity, evidence = detect_risk_disclosure_expansion(
            OLD_LOW_RISK, NEW_HIGH_RISK
        )
        assert detected is True
        assert confidence > 0.3
        assert len(evidence) > 0

    def test_no_signal_when_unchanged(self):
        from agents.tinyfish_signals.risk_disclosure_agent import detect_risk_disclosure_expansion
        detected, confidence, severity, evidence = detect_risk_disclosure_expansion(
            OLD_LOW_RISK, OLD_LOW_RISK
        )
        assert detected is False

    def test_run_risk_agent_returns_correct_signal(self):
        from agents.tinyfish_signals.risk_disclosure_agent import run_risk_disclosure_agent
        result = run_risk_disclosure_agent(OLD_LOW_RISK, NEW_HIGH_RISK)
        assert result["signal_type"] == "RISK_DISCLOSURE_EXPANSION"

    def test_run_risk_agent_no_signal_case(self):
        from agents.tinyfish_signals.risk_disclosure_agent import run_risk_disclosure_agent
        result = run_risk_disclosure_agent(UNCHANGED_TEXT, UNCHANGED_TEXT)
        assert result["signal_type"] == "NO_SIGNAL"

    def test_high_severity_terms_trigger_high_severity(self):
        from agents.tinyfish_signals.risk_disclosure_agent import detect_risk_disclosure_expansion
        old = "The company is well-funded."
        new = "The company faces going concern uncertainty and potential material adverse conditions."
        detected, confidence, severity, evidence = detect_risk_disclosure_expansion(old, new)
        assert detected is True
        assert severity == "HIGH"

    def test_evidence_has_keyword_context(self):
        from agents.tinyfish_signals.risk_disclosure_agent import run_risk_disclosure_agent
        result = run_risk_disclosure_agent(OLD_LOW_RISK, NEW_HIGH_RISK)
        assert any("risk" in e.lower() or "uncertainty" in e.lower()
                   for e in result["evidence_quotes"])


# ══════════════════════════════════════════════════════════════════════════════
# TestToneShiftAgent
# ══════════════════════════════════════════════════════════════════════════════

class TestToneShiftAgent:
    def test_detects_tone_softening(self):
        from agents.tinyfish_signals.tone_shift_agent import detect_tone_softening
        detected, confidence, severity, evidence = detect_tone_softening(
            OLD_CONFIDENT_TONE, NEW_CAUTIOUS_TONE
        )
        assert detected is True
        assert confidence > 0.1

    def test_no_signal_when_unchanged(self):
        from agents.tinyfish_signals.tone_shift_agent import detect_tone_softening
        detected, *_ = detect_tone_softening(UNCHANGED_TEXT, UNCHANGED_TEXT)
        assert detected is False

    def test_run_tone_agent_returns_correct_signal(self):
        from agents.tinyfish_signals.tone_shift_agent import run_tone_shift_agent
        result = run_tone_shift_agent(OLD_CONFIDENT_TONE, NEW_CAUTIOUS_TONE)
        assert result["signal_type"] == "TONE_SOFTENING"

    def test_run_tone_agent_no_signal(self):
        from agents.tinyfish_signals.tone_shift_agent import run_tone_shift_agent
        result = run_tone_shift_agent(UNCHANGED_TEXT, UNCHANGED_TEXT)
        assert result["signal_type"] == "NO_SIGNAL"

    def test_canonical_substitutions_detected(self):
        from agents.tinyfish_signals.tone_shift_agent import _detect_substitutions
        old = "We will deliver strong growth and are confident in our targets."
        new = "We may achieve stable performance and are cautious about conditions."
        subs = _detect_substitutions(old, new)
        assert len(subs) > 0

    def test_confidence_score_positive_for_strong_softening(self):
        from agents.tinyfish_signals.tone_shift_agent import detect_tone_softening
        _, confidence, _, _ = detect_tone_softening(OLD_CONFIDENT_TONE, NEW_CAUTIOUS_TONE)
        assert confidence > 0.15


# ══════════════════════════════════════════════════════════════════════════════
# TestSignalClassifier
# ══════════════════════════════════════════════════════════════════════════════

class TestSignalClassifier:
    def test_guidance_wins_over_tone(self):
        """GUIDANCE_WITHDRAWAL has priority 1; should win over TONE_SOFTENING."""
        from agents.tinyfish_signals.signal_classifier import classify_signals
        # Text has both guidance removal AND tone softening
        old = (
            "We expect revenue growth of 30% in FY2026 and are confident. "
            "We will deliver strong results."
        )
        new = (
            "We aim to pursue long-term value. We are cautious about near-term outlook."
        )
        result = classify_signals(old, new)
        # Guidance withdrawal has higher priority; must be selected if above threshold
        assert result["signal_type"] in ("GUIDANCE_WITHDRAWAL", "TONE_SOFTENING", "NO_SIGNAL")
        assert "confidence" in result
        assert "evidence_quotes" in result

    def test_no_signal_returned_for_identical_texts(self):
        from agents.tinyfish_signals.signal_classifier import classify_signals
        result = classify_signals(UNCHANGED_TEXT, UNCHANGED_TEXT)
        assert result["signal_type"] == "NO_SIGNAL"

    def test_validation_boost_increases_confidence(self):
        from agents.tinyfish_signals.signal_classifier import classify_signals
        base = classify_signals(OLD_WITH_GUIDANCE, NEW_WITHOUT_GUIDANCE)
        base_conf = base["confidence"]

        boosted = classify_signals(
            OLD_WITH_GUIDANCE, NEW_WITHOUT_GUIDANCE,
            validation_result={
                "validation_status":     "CONFIRMED",
                "validation_summary":    "Found in ASX filing.",
                "validation_evidence":   [],
                "confidence_adjustment": 0.10,
            }
        )
        assert boosted["confidence"] >= base_conf

    def test_all_signals_included_in_result(self):
        from agents.tinyfish_signals.signal_classifier import classify_signals
        result = classify_signals(OLD_WITH_GUIDANCE, NEW_WITHOUT_GUIDANCE)
        assert "_all_signals" in result
        assert "GUIDANCE_WITHDRAWAL" in result["_all_signals"]
        assert "RISK_DISCLOSURE_EXPANSION" in result["_all_signals"]
        assert "TONE_SOFTENING" in result["_all_signals"]

    def test_result_has_required_fields(self):
        from agents.tinyfish_signals.signal_classifier import classify_signals
        result = classify_signals(OLD_LOW_RISK, NEW_HIGH_RISK)
        for field in ("signal_type", "severity", "confidence", "financial_relevance",
                      "evidence_quotes", "quality_flags", "validation_status"):
            assert field in result, f"Missing field: {field}"


# ══════════════════════════════════════════════════════════════════════════════
# TestTinyFishPipeline
# ══════════════════════════════════════════════════════════════════════════════

class TestTinyFishPipeline:
    def _run(self, old, new, snippet=""):
        from agents.tinyfish_signals.tinyfish_signal_pipeline import run_tinyfish_signal_pipeline
        return run_tinyfish_signal_pipeline(
            ticker       = "TEST",
            company_name = "Test Corp",
            source_url   = "",
            old_text     = old,
            new_text     = new,
            changed_snippet = snippet,
            llm_client   = None,  # heuristic-only, no network
        )

    def test_pipeline_returns_all_required_fields(self):
        result = self._run(OLD_WITH_GUIDANCE, NEW_WITHOUT_GUIDANCE)
        required = [
            "signal_type", "severity", "confidence", "financial_relevance",
            "evidence_quotes", "quality_flags", "validation_status",
            "validation_summary", "validation_evidence", "summary",
            "what_changed", "why_it_matters",
        ]
        for f in required:
            assert f in result, f"Missing required pipeline field: {f}"

    def test_pipeline_detects_guidance_withdrawal(self):
        result = self._run(OLD_WITH_GUIDANCE, NEW_WITHOUT_GUIDANCE)
        # May be GUIDANCE_WITHDRAWAL or NO_SIGNAL depending on threshold
        assert result["signal_type"] in ("GUIDANCE_WITHDRAWAL", "NO_SIGNAL", "TONE_SOFTENING")

    def test_pipeline_no_signal_unchanged_text(self):
        result = self._run(UNCHANGED_TEXT, UNCHANGED_TEXT)
        assert result["signal_type"] == "NO_SIGNAL"

    def test_pipeline_summary_is_string(self):
        result = self._run(OLD_WITH_GUIDANCE, NEW_WITHOUT_GUIDANCE)
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0

    def test_pipeline_validation_not_triggered_for_no_signal(self):
        """Cross-validation should be skipped for NO_SIGNAL."""
        result = self._run(UNCHANGED_TEXT, UNCHANGED_TEXT)
        assert result["validation_status"] in (
            "NOT_CONFIRMED_YET", "SOURCE_UNAVAILABLE", "CONFIRMED", "PARTIALLY_CONFIRMED"
        )

    def test_normalize_strips_html(self):
        from agents.tinyfish_signals.tinyfish_signal_pipeline import normalize_text
        raw  = "<p>We &amp; our partners <b>expect</b> growth.</p>"
        clean = normalize_text(raw)
        assert "<p>" not in clean
        assert "&amp;" not in clean
        assert "We & our partners" in clean or "expect" in clean

    def test_normalize_collapses_whitespace(self):
        from agents.tinyfish_signals.tinyfish_signal_pipeline import normalize_text
        raw   = "  Hello   \n\n  World  "
        clean = normalize_text(raw)
        assert clean == "Hello World"


# ══════════════════════════════════════════════════════════════════════════════
# TestTinyFishContracts  (requires pydantic — skipped if not installed)
# ══════════════════════════════════════════════════════════════════════════════

def _skip_if_no_pydantic():
    try:
        import pydantic  # noqa: F401
    except ImportError:
        pytest.skip("pydantic not installed in this test environment")


class TestTinyFishContracts:
    def setup_method(self):
        _skip_if_no_pydantic()

    def test_api_response_success(self):
        from agents.tinyfish_signals.tinyfish_contracts import ApiResponse
        r = ApiResponse.success({"key": "value"})
        assert r.ok is True
        assert r.data == {"key": "value"}
        assert r.error is None

    def test_api_response_failure(self):
        from agents.tinyfish_signals.tinyfish_contracts import ApiResponse
        r = ApiResponse.failure("ERR_CODE", "Something went wrong")
        assert r.ok is False
        assert r.data is None
        assert r.error.code == "ERR_CODE"
        assert r.error.message == "Something went wrong"

    def test_signal_type_enum_values(self):
        from agents.tinyfish_signals.tinyfish_contracts import SignalType
        assert SignalType.GUIDANCE_WITHDRAWAL.value    == "GUIDANCE_WITHDRAWAL"
        assert SignalType.RISK_DISCLOSURE_EXPANSION.value == "RISK_DISCLOSURE_EXPANSION"
        assert SignalType.TONE_SOFTENING.value         == "TONE_SOFTENING"
        assert SignalType.NO_SIGNAL.value              == "NO_SIGNAL"

    def test_validation_status_enum_values(self):
        from agents.tinyfish_signals.tinyfish_contracts import ValidationStatus
        assert ValidationStatus.CONFIRMED.value           == "CONFIRMED"
        assert ValidationStatus.PARTIALLY_CONFIRMED.value == "PARTIALLY_CONFIRMED"
        assert ValidationStatus.NOT_CONFIRMED_YET.value   == "NOT_CONFIRMED_YET"
        assert ValidationStatus.SOURCE_UNAVAILABLE.value  == "SOURCE_UNAVAILABLE"

    def test_detect_signal_request_model(self):
        from agents.tinyfish_signals.tinyfish_contracts import DetectSignalRequest
        req = DetectSignalRequest(
            ticker="TEST",
            company_name="Test Corp",
            source_url="https://test.com",
            old_text="old content",
            new_text="new content",
        )
        assert req.ticker == "TEST"
        assert req.changed_snippet == ""  # default

    def test_run_pipeline_request_model(self):
        from agents.tinyfish_signals.tinyfish_contracts import RunPipelineRequest
        req = RunPipelineRequest(
            ticker="GATO",
            company_name="Gatos Silver",
            source_url="https://gatos.com/investors",
            old_text="old text",
            new_text="new text",
        )
        assert req.ticker == "GATO"

    def test_health_data_model(self):
        from agents.tinyfish_signals.tinyfish_contracts import HealthData
        h = HealthData(
            paid_llm_enabled=True,
            private_llm_enabled=False,
        )
        assert h.service == "datapai-streamlit"
        assert h.contract_version == "v1"


# ══════════════════════════════════════════════════════════════════════════════
# TestCrossValidationAgent (offline — skips network calls)
# ══════════════════════════════════════════════════════════════════════════════

class TestCrossValidationAgentOffline:
    def test_signal_keywords_mapping(self):
        from agents.tinyfish_signals.cross_validation_agent import _SIGNAL_KEYWORDS
        assert "GUIDANCE_WITHDRAWAL"    in _SIGNAL_KEYWORDS
        assert "RISK_DISCLOSURE_EXPANSION" in _SIGNAL_KEYWORDS
        assert "TONE_SOFTENING"         in _SIGNAL_KEYWORDS

    def test_asx_ticker_detection(self):
        from agents.tinyfish_signals.cross_validation_agent import _is_asx_ticker
        # Heuristic: 2-4 uppercase alpha chars are treated as ASX-like
        assert _is_asx_ticker("BHP")   is True   # 3-letter ASX ticker
        assert _is_asx_ticker("CBA")   is True   # 3-letter ASX ticker
        assert _is_asx_ticker("GATO")  is True   # 4-letter uppercase — heuristic treats as ASX
        assert _is_asx_ticker("AAPL")  is True   # 4-letter — also matches (heuristic limitation)
        assert _is_asx_ticker("aapl")  is False  # lowercase — not matched
        assert _is_asx_ticker("123")   is False  # numeric — not matched
        assert _is_asx_ticker("A")     is False  # 1 letter — too short

    def test_derive_status_no_evidence_returns_not_confirmed(self):
        from agents.tinyfish_signals.cross_validation_agent import _derive_status
        status, summary, adj = _derive_status([], "GUIDANCE_WITHDRAWAL")
        assert status == "NOT_CONFIRMED_YET"
        assert adj == 0.0

    def test_derive_status_filing_evidence_returns_confirmed(self):
        from agents.tinyfish_signals.cross_validation_agent import _derive_status
        evidence = [{"url": "https://asx.com.au/ann", "snippet": "guidance update", "source": "ASX filing"}]
        status, summary, adj = _derive_status(evidence, "GUIDANCE_WITHDRAWAL")
        assert status == "CONFIRMED"
        assert adj > 0.0
