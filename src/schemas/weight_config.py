"""Pydantic schemas for weight configuration API."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


# ---------------------------------------------------------------------------
# Role schemas
# ---------------------------------------------------------------------------

class RoleBase(BaseModel):
    """Base role schema."""
    name: str
    display_name: str
    description: Optional[str] = None


class RoleResponse(RoleBase):
    """Role response schema."""
    id: int
    jd_file_path: Optional[str] = None
    subquery_file_path: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    requirements_count: int = 0
    configurations_count: int = 0

    class Config:
        from_attributes = True


class RoleListResponse(BaseModel):
    """Role list response schema."""
    roles: List[RoleResponse]
    total: int


# ---------------------------------------------------------------------------
# Requirement schemas
# ---------------------------------------------------------------------------

class RequirementBase(BaseModel):
    """Base requirement schema."""
    req_id: str
    name: str
    category: str
    requirement_type: str
    description: Optional[str] = None
    subquery_count: int = 1
    scoring_formula: Optional[str] = None


class RequirementResponse(RequirementBase):
    """Requirement response schema."""
    id: int
    role_id: int
    created_at: datetime.datetime

    class Config:
        from_attributes = True


class RequirementListResponse(BaseModel):
    """Requirement list response schema."""
    requirements: List[RequirementResponse]
    total: int
    by_category: Dict[str, List[RequirementResponse]]


# ---------------------------------------------------------------------------
# Weight configuration schemas
# ---------------------------------------------------------------------------

class WeightItemCreate(BaseModel):
    """Weight item creation schema."""
    requirement_id: int
    weight_percentage: float = Field(..., ge=0, le=100, description="Weight percentage (0-100)")
    expected_years: Optional[float] = Field(None, ge=0, description="Expected years of experience")
    notes: Optional[str] = None


class WeightItemResponse(BaseModel):
    """Weight item response schema."""
    id: int
    requirement_id: int
    requirement_name: str
    requirement_req_id: str
    category: str
    weight_percentage: float
    expected_years: Optional[float] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class WeightConfigurationCreate(BaseModel):
    """Weight configuration creation schema."""
    name: str = Field(..., min_length=1, max_length=255, description="Configuration name")
    description: Optional[str] = None
    recruiter_id: Optional[int] = None
    weight_items: List[WeightItemCreate] = Field(..., min_length=1, description="Weight items")

    @validator("weight_items")
    def validate_weight_items(cls, v: List[WeightItemCreate]) -> List[WeightItemCreate]:
        """Validate that weight items are provided."""
        if not v:
            raise ValueError("At least one weight item is required")
        return v


class WeightConfigurationUpdate(BaseModel):
    """Weight configuration update schema."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    weight_items: Optional[List[WeightItemCreate]] = None


class WeightConfigurationResponse(BaseModel):
    """Weight configuration response schema."""
    id: int
    role_id: int
    role_name: str
    recruiter_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    total_allocated: float
    scale_factor: float
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    weight_items: List[WeightItemResponse]
    validation: ValidationResponse

    class Config:
        from_attributes = True


class WeightConfigurationListResponse(BaseModel):
    """Weight configuration list response schema."""
    configurations: List[WeightConfigurationResponse]
    total: int


# ---------------------------------------------------------------------------
# Validation schemas
# ---------------------------------------------------------------------------

class ValidationResponse(BaseModel):
    """Validation response schema."""
    is_valid: bool
    total_allocated: float
    remaining: float
    by_category: Dict[str, CategoryValidation]
    errors: List[str] = []
    warnings: List[str] = []


class CategoryValidation(BaseModel):
    """Category validation schema."""
    category: str
    total: float
    count: int
    remaining: float
    items: List[Dict[str, Any]]


class ValidationRequest(BaseModel):
    """Validation request schema."""
    role_id: int
    weight_items: List[WeightItemCreate]


# ---------------------------------------------------------------------------
# Summary schemas
# ---------------------------------------------------------------------------

class WeightSummary(BaseModel):
    """Weight summary schema for display."""
    role_name: str
    total_allocated: float
    remaining: float
    is_valid: bool
    by_category: Dict[str, CategorySummary]
    items_without_weight: List[RequirementResponse]
    items_with_weight: List[WeightItemResponse]


class CategorySummary(BaseModel):
    """Category summary schema."""
    category: str
    total: float
    count: int
    rated_count: int
    unrated_count: int
    remaining: float


# ---------------------------------------------------------------------------
# Dashboard schemas
# ---------------------------------------------------------------------------

class DashboardResponse(BaseModel):
    """Dashboard response schema."""
    total_roles: int
    total_configurations: int
    total_recruiters: int
    recent_configurations: List[WeightConfigurationResponse]
    roles_with_configs: List[Dict[str, Any]]
