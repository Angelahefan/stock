"""
TinyFish Financial Signal Contracts
====================================
Pydantic models for all request/response types in the TinyFish financial
signal pipeline.  These mirror the shared-api-contract.md schema exactly.

No business logic here — pure data contracts.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════════════════════
# Enumerations (from shared-api-contract.md)
# ══════════════════════════════════════════════════════════════════════════════

class SignalType(str, Enum):
    GUIDANCE_WITHDRAWAL       = "GUIDANCE_WITHDRAWAL"
    RISK_DISCLOSURE_EXPANSION = "RISK_DISCLOSURE_EXPANSION"
    TONE_SOFTENING            = "TONE_SOFTENING"
    NO_SIGNAL                 = "NO_SIGNAL"


class ChangeType(str, Enum):
    """
    v1.5 Signal Quality Filter — classifies the nature of a detected text change.
    Only CONTENT_CHANGE should generate high-confidence financial signals.
    """
    CONTENT_CHANGE = "CONTENT_CHANGE"
    ARCHIVE_CHANGE = "ARCHIVE_CHANGE"
    LAYOUT_CHANGE  = "LAYOUT_CHANGE"


class Severity(str, Enum):
    HIGH   = "HIGH"
    MEDIUM = "MEDIUM"
    LOW    = "LOW"
    NONE   = "NONE"


class ValidationStatus(str, Enum):
    CONFIRMED            = "CONFIRMED"
    PARTIALLY_CONFIRMED  = "PARTIALLY_CONFIRMED"
    NOT_CONFIRMED_YET    = "NOT_CONFIRMED_YET"
    SOURCE_UNAVAILABLE   = "SOURCE_UNAVAILABLE"


# ══════════════════════════════════════════════════════════════════════════════
# Shared API envelope (shared-api-contract.md §API Contract)
# ══════════════════════════════════════════════════════════════════════════════

class ApiError(BaseModel):
    code:    str
    message: str


class ApiResponse(BaseModel):
    """Generic envelope — success OR error, never both."""
    ok:    bool
    data:  Optional[Dict[str, Any]] = None
    error: Optional[ApiError]       = None

    @classmethod
    def success(cls, data: Dict[str, Any]) -> "ApiResponse":
        return cls(ok=True, data=data, error=None)

    @classmethod
    def failure(cls, code: str, message: str) -> "ApiResponse":
        return cls(ok=False, data=None, error=ApiError(code=code, message=message))


# ══════════════════════════════════════════════════════════════════════════════
# POST /agent/detect-financial-signal
# ══════════════════════════════════════════════════════════════════════════════

class DetectSignalRequest(BaseModel):
    ticker:          str = Field(..., description="Company ticker symbol, e.g. GATO")
    company_name:    str = Field(..., description="Full company name")
    source_url:      str = Field(..., description="URL where the text was scraped from")
    old_text:        str = Field(..., description="Previous cleaned text snapshot")
    new_text:        str = Field(..., description="Current cleaned text snapshot")
    changed_snippet: str = Field("", description="Optional diff snippet highlighting the change")


class DetectSignalData(BaseModel):
    signal_type:         SignalType
    severity:            Severity
    confidence:          float = Field(ge=0.0, le=1.0)
    financial_relevance: str   = Field(description="Plain-English explanation of financial impact")
    evidence_quotes:     List[str] = Field(default_factory=list)
    quality_flags:       List[str] = Field(default_factory=list,
                                           description="Any caveats or quality warnings")


# ══════════════════════════════════════════════════════════════════════════════
# POST /agent/cross-validate-signal
# ══════════════════════════════════════════════════════════════════════════════

class CrossValidateRequest(BaseModel):
    ticker:          str
    company_name:    str
    signal_type:     SignalType
    changed_snippet: str = ""
    source_url:      str = ""


class ValidationEvidence(BaseModel):
    url:     str
    snippet: str
    source:  str   # e.g. "ASX filing", "SEC 8-K", "press release"


class CrossValidateData(BaseModel):
    validation_status:       ValidationStatus
    validation_summary:      str
    validation_evidence:     List[ValidationEvidence] = Field(default_factory=list)
    confidence_adjustment:   float = Field(0.0, description="Positive = boosts confidence, negative = reduces")


# ══════════════════════════════════════════════════════════════════════════════
# POST /agent/generate-signal-summary
# ══════════════════════════════════════════════════════════════════════════════

class GenerateSummaryRequest(BaseModel):
    ticker:          str
    company_name:    str
    signal_type:     SignalType
    severity:        Severity
    evidence_quotes: List[str]
    old_text:        str = ""
    new_text:        str = ""
    validation_status:   ValidationStatus = ValidationStatus.NOT_CONFIRMED_YET
    validation_summary:  str = ""


class GenerateSummaryData(BaseModel):
    what_changed:   str
    why_it_matters: str
    evidence:       List[str]
    validation_result: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# v1.5 Investigation Agent result
# ══════════════════════════════════════════════════════════════════════════════

class InvestigationFinding(BaseModel):
    url:          str
    snippet:      str
    source:       str   # e.g. "company press releases", "ASX announcement", "company IR page"
    keywords:     List[str] = Field(default_factory=list)
    corroborates: bool = True


class InvestigationResult(BaseModel):
    investigation_results:  List[InvestigationFinding] = Field(default_factory=list)
    sources_checked:        List[str] = Field(default_factory=list)
    investigation_summary:  str = ""
    corroborating_count:    int = 0
    contradicting_count:    int = 0
    found_evidence:         bool = False


# ══════════════════════════════════════════════════════════════════════════════
# POST /agent/run-financial-signal-pipeline (full pipeline)
# ══════════════════════════════════════════════════════════════════════════════

class RunPipelineRequest(BaseModel):
    ticker:          str
    company_name:    str
    source_url:      str
    old_text:        str
    new_text:        str
    changed_snippet: str = ""


class RunPipelineData(BaseModel):
    signal_type:         SignalType
    severity:            Severity
    confidence:          float
    financial_relevance: str
    evidence_quotes:     List[str]
    quality_flags:       List[str]
    # v1.5: change type classification
    change_type:         ChangeType = ChangeType.CONTENT_CHANGE
    change_quality_score: float = Field(1.0, ge=0.0, le=1.0)
    financial_relevance_score: float = Field(0.0, ge=0.0, le=1.0)
    # Validation
    validation_status:   ValidationStatus
    validation_summary:  str
    validation_evidence: List[ValidationEvidence] = Field(default_factory=list)
    # v1.5: investigation fields
    investigation_summary:  str = ""
    investigation_sources:  List[str] = Field(default_factory=list)
    corroborating_count:    int = 0
    # Narrative
    summary:             str   = Field(description="Full investor-friendly narrative")
    what_changed:        str
    why_it_matters:      str


# ══════════════════════════════════════════════════════════════════════════════
# GET /agent/health
# ══════════════════════════════════════════════════════════════════════════════

class HealthData(BaseModel):
    service:             str  = "datapai-streamlit"
    ag2_enabled:         bool = True
    paid_llm_enabled:    bool
    private_llm_enabled: bool
    rag_enabled:         bool = False
    version:             str  = "v1"
    contract_version:    str  = "v1"
