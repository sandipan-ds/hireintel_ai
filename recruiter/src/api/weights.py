"""API routes for weight configuration management."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from recruiter.src.models.database import (
    Requirement,
    Role,
    WeightConfiguration,
    WeightItem,
    get_db,
)
from recruiter.src.schemas.weight_config import (
    CategoryValidation,
    CategorySummary,
    RequirementResponse,
    ValidationResponse,
    WeightConfigurationCreate,
    WeightConfigurationListResponse,
    WeightConfigurationResponse,
    WeightConfigurationUpdate,
    WeightItemCreate,
    WeightItemResponse,
    WeightSummary,
)
from recruiter.src.services.json_export import export_config_to_json, delete_json_config

router = APIRouter(prefix="/api/weights", tags=["weights"])


def _validate_weight_configuration(
    requirements: List[Requirement],
    weight_items: List[WeightItemCreate],
) -> ValidationResponse:
    """Validate weight configuration."""
    # Create a mapping of requirement_id to weight
    weight_map = {item.requirement_id: item.weight_percentage for item in weight_items}

    # Calculate totals
    total_allocated = sum(x.weight_percentage for x in weight_items)
    remaining = 100.0 - total_allocated

    # Group by category
    by_category: Dict[str, CategoryValidation] = {}
    errors = []
    warnings = []

    for req in requirements:
        category = req.category
        weight = weight_map.get(req.id, 0)

        if category not in by_category:
            by_category[category] = CategoryValidation(
                category=category,
                total=0.0,
                count=0,
                remaining=0.0,
                items=[],
            )

        by_category[category].total += weight
        by_category[category].count += 1
        by_category[category].items.append({
            "requirement_id": req.id,
            "req_id": req.req_id,
            "name": req.name,
            "weight": weight,
        })

    # Calculate remaining for each category
    for cat in by_category.values():
        cat.remaining = 100.0 - cat.total

    # Validation checks
    is_valid = True

    if abs(total_allocated - 100.0) > 0.01:
        is_valid = False
        errors.append(f"Total allocated must be 100%, currently {total_allocated:.1f}%")

    # Check for negative weights
    for item in weight_items:
        if item.weight_percentage < 0:
            is_valid = False
            errors.append(f"Weight cannot be negative for requirement {item.requirement_id}")

    # Check for weights > 100%
    for item in weight_items:
        if item.weight_percentage > 100:
            is_valid = False
            errors.append(f"Weight cannot exceed 100% for requirement {item.requirement_id}")

    return ValidationResponse(
        is_valid=is_valid,
        total_allocated=total_allocated,
        remaining=remaining,
        by_category=by_category,
        errors=errors,
        warnings=warnings,
    )


@router.get("/configurations", response_model=WeightConfigurationListResponse)
def list_configurations(
    role_id: Optional[int] = None,
    recruiter_id: Optional[int] = None,
    db: Session = Depends(get_db),
) -> WeightConfigurationListResponse:
    """List weight configurations, optionally filtered by role or recruiter."""
    query = db.query(WeightConfiguration)

    if role_id:
        query = query.filter(WeightConfiguration.role_id == role_id)
    if recruiter_id:
        query = query.filter(WeightConfiguration.recruiter_id == recruiter_id)

    configurations = query.all()

    config_responses = []
    for config in configurations:
        # Get role name
        role = db.query(Role).filter(Role.id == config.role_id).first()
        role_name = role.name if role else "Unknown"

        # Get weight items
        weight_items = db.query(WeightItem).filter(WeightItem.configuration_id == config.id).all()
        weight_item_responses = []

        for wi in weight_items:
            req = db.query(Requirement).filter(Requirement.id == wi.requirement_id).first()
            weight_item_responses.append(
                WeightItemResponse(
                    id=wi.id,
                    requirement_id=wi.requirement_id,
                    requirement_name=req.name if req else "Unknown",
                    requirement_req_id=req.req_id if req else "Unknown",
                    category=req.category if req else "Unknown",
                    weight_percentage=wi.weight_percentage,
                    expected_years=wi.expected_years,
                    notes=wi.notes,
                )
            )

        # Validate configuration
        validation = _validate_weight_configuration(
            db.query(Requirement).filter(Requirement.role_id == config.role_id).all(),
            [WeightItemCreate(
                requirement_id=wi.requirement_id,
                weight_percentage=wi.weight_percentage,
                expected_years=wi.expected_years,
                notes=wi.notes,
            ) for wi in weight_items],
        )

        config_responses.append(
            WeightConfigurationResponse(
                id=config.id,
                role_id=config.role_id,
                role_name=role_name,
                recruiter_id=config.recruiter_id,
                name=config.name,
                description=config.description,
                total_allocated=config.total_allocated,
                scale_factor=config.scale_factor,
                is_active=bool(config.is_active),
                created_at=config.created_at,
                updated_at=config.updated_at,
                weight_items=weight_item_responses,
                validation=validation,
            )
        )

    return WeightConfigurationListResponse(
        configurations=config_responses,
        total=len(config_responses),
    )


@router.get("/configurations/{config_id}", response_model=WeightConfigurationResponse)
def get_configuration(config_id: int, db: Session = Depends(get_db)) -> WeightConfigurationResponse:
    """Get a specific weight configuration."""
    config = db.query(WeightConfiguration).filter(WeightConfiguration.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")

    # Get role name
    role = db.query(Role).filter(Role.id == config.role_id).first()
    role_name = role.name if role else "Unknown"

    # Get weight items
    weight_items = db.query(WeightItem).filter(WeightItem.configuration_id == config.id).all()
    weight_item_responses = []

    for wi in weight_items:
        req = db.query(Requirement).filter(Requirement.id == wi.requirement_id).first()
        weight_item_responses.append(
            WeightItemResponse(
                id=wi.id,
                requirement_id=wi.requirement_id,
                requirement_name=req.name if req else "Unknown",
                requirement_req_id=req.req_id if req else "Unknown",
                category=req.category if req else "Unknown",
                weight_percentage=wi.weight_percentage,
                expected_years=wi.expected_years,
                notes=wi.notes,
            )
        )

    # Validate configuration
    validation = _validate_weight_configuration(
        db.query(Requirement).filter(Requirement.role_id == config.role_id).all(),
        [WeightItemCreate(
            requirement_id=wi.requirement_id,
            weight_percentage=wi.weight_percentage,
            expected_years=wi.expected_years,
            notes=wi.notes,
        ) for wi in weight_items],
    )

    return WeightConfigurationResponse(
        id=config.id,
        role_id=config.role_id,
        role_name=role_name,
        recruiter_id=config.recruiter_id,
        name=config.name,
        description=config.description,
        total_allocated=config.total_allocated,
        scale_factor=config.scale_factor,
        is_active=bool(config.is_active),
        created_at=config.created_at,
        updated_at=config.updated_at,
        weight_items=weight_item_responses,
        validation=validation,
    )


@router.post("/configurations", response_model=WeightConfigurationResponse)
def create_configuration(
    config_data: WeightConfigurationCreate,
    role_id: int,
    db: Session = Depends(get_db),
) -> WeightConfigurationResponse:
    """Create a new weight configuration."""
    # Check if role exists
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # Get all requirements for the role
    requirements = db.query(Requirement).filter(Requirement.role_id == role_id).all()

    # Validate weight configuration
    validation = _validate_weight_configuration(requirements, config_data.weight_items)
    if not validation.is_valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid weight configuration: {'; '.join(validation.errors)}",
        )

    # Create configuration
    config = WeightConfiguration(
        role_id=role_id,
        recruiter_id=config_data.recruiter_id,
        name=config_data.name,
        description=config_data.description,
        total_allocated=validation.total_allocated,
        scale_factor=100.0 / validation.total_allocated if validation.total_allocated > 0 else 1.0,
    )
    db.add(config)
    db.commit()
    db.refresh(config)

    # Create weight items
    for item in config_data.weight_items:
        weight_item = WeightItem(
            configuration_id=config.id,
            requirement_id=item.requirement_id,
            weight_percentage=item.weight_percentage,
            expected_years=item.expected_years,
            notes=item.notes,
        )
        db.add(weight_item)

    db.commit()

    # Return created configuration
    return get_configuration(config.id, db)


@router.put("/configurations/{config_id}", response_model=WeightConfigurationResponse)
def update_configuration(
    config_id: int,
    config_data: WeightConfigurationUpdate,
    db: Session = Depends(get_db),
) -> WeightConfigurationResponse:
    """Update an existing weight configuration."""
    config = db.query(WeightConfiguration).filter(WeightConfiguration.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")

    # Update fields if provided
    if config_data.name is not None:
        config.name = config_data.name
    if config_data.description is not None:
        config.description = config_data.description

    # Update weight items if provided
    if config_data.weight_items is not None:
        # Delete existing weight items
        db.query(WeightItem).filter(WeightItem.configuration_id == config_id).delete()

        # Create new weight items
        for item in config_data.weight_items:
            weight_item = WeightItem(
                configuration_id=config.id,
                requirement_id=item.requirement_id,
                weight_percentage=item.weight_percentage,
                expected_years=item.expected_years,
                notes=item.notes,
            )
            db.add(weight_item)

        # Get all requirements for validation
        requirements = db.query(Requirement).filter(Requirement.role_id == config.role_id).all()
        validation = _validate_weight_configuration(requirements, config_data.weight_items)

        # Update totals
        config.total_allocated = validation.total_allocated
        config.scale_factor = 100.0 / validation.total_allocated if validation.total_allocated > 0 else 1.0

    db.commit()

    # Return updated configuration
    return get_configuration(config.id, db)


@router.delete("/configurations/{config_id}")
def delete_configuration(config_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Delete a weight configuration from DB and JSON file."""
    config = db.query(WeightConfiguration).filter(WeightConfiguration.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")

    # Get role name for JSON deletion
    role = db.query(Role).filter(Role.id == config.role_id).first()
    role_name = role.name if role else None

    # Delete weight items
    db.query(WeightItem).filter(WeightItem.configuration_id == config_id).delete()

    # Delete configuration
    db.delete(config)
    db.commit()

    # Delete JSON file
    json_deleted = False
    if role_name:
        json_deleted = delete_json_config(role_name, config.name)

    return {
        "message": "Configuration deleted successfully",
        "id": config_id,
        "json_deleted": json_deleted,
    }


@router.post("/validate", response_model=ValidationResponse)
def validate_configuration(
    role_id: int,
    weight_items: List[WeightItemCreate],
    db: Session = Depends(get_db),
) -> ValidationResponse:
    """Validate a weight configuration without saving."""
    # Get requirements for the role
    requirements = db.query(Requirement).filter(Requirement.role_id == role_id).all()

    if not requirements:
        raise HTTPException(status_code=404, detail="No requirements found for this role")

    return _validate_weight_configuration(requirements, weight_items)


@router.get("/summary/{role_id}", response_model=WeightSummary)
def get_weight_summary(
    role_id: int,
    config_id: Optional[int] = None,
    db: Session = Depends(get_db),
) -> WeightSummary:
    """Get weight summary for a role, optionally with a specific configuration."""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    requirements = db.query(Requirement).filter(Requirement.role_id == role_id).all()

    # Get weight items from configuration or empty
    weight_items_dict: Dict[int, float] = {}
    weight_item_responses: List[WeightItemResponse] = []

    if config_id:
        config = db.query(WeightConfiguration).filter(WeightConfiguration.id == config_id).first()
        if config:
            weight_items = db.query(WeightItem).filter(WeightItem.configuration_id == config_id).all()
            for wi in weight_items:
                weight_items_dict[wi.requirement_id] = wi.weight_percentage
                req = db.query(Requirement).filter(Requirement.id == wi.requirement_id).first()
                weight_item_responses.append(
                    WeightItemResponse(
                        id=wi.id,
                        requirement_id=wi.requirement_id,
                        requirement_name=req.name if req else "Unknown",
                        requirement_req_id=req.req_id if req else "Unknown",
                        category=req.category if req else "Unknown",
                        weight_percentage=wi.weight_percentage,
                        expected_years=wi.expected_years,
                        notes=wi.notes,
                    )
                )

    # Group requirements by category
    categorized: Dict[str, List[Requirement]] = {}
    for req in requirements:
        if req.category not in categorized:
            categorized[req.category] = []
        categorized[req.category].append(req)

    # Calculate category summaries
    by_category: Dict[str, CategorySummary] = {}
    total_allocated = 0.0

    for category, reqs in categorized.items():
        cat_total = sum(weight_items_dict.get(req.id, 0) for req in reqs)
        rated_count = sum(1 for req in reqs if req.id in weight_items_dict)
        unrated_count = len(reqs) - rated_count

        by_category[category] = CategorySummary(
            category=category,
            total=cat_total,
            count=len(reqs),
            rated_count=rated_count,
            unrated_count=unrated_count,
            remaining=100.0 - cat_total,  # This will be adjusted at global level
        )

        total_allocated += cat_total

    # Calculate items without weight
    items_without_weight = [
        RequirementResponse(
            id=req.id,
            role_id=req.role_id,
            req_id=req.req_id,
            name=req.name,
            category=req.category,
            requirement_type=req.requirement_type,
            description=req.description,
            subquery_count=req.subquery_count,
            scoring_formula=req.scoring_formula,
            created_at=req.created_at,
        )
        for req in requirements
        if req.id not in weight_items_dict
    ]

    return WeightSummary(
        role_name=role.name,
        total_allocated=total_allocated,
        remaining=100.0 - total_allocated,
        is_valid=abs(total_allocated - 100.0) < 0.01,
        by_category=by_category,
        items_without_weight=items_without_weight,
        items_with_weight=weight_item_responses,
    )
