"""Template and Variant CRUD API endpoints."""

import json
import logging
from datetime import datetime
from typing import Optional, List
from fastapi import Form
from fastapi.responses import HTMLResponse, JSONResponse

from src.models import PostTemplate, PostVariant, Schedule
from src.database import get_db
from src.audit import log_info, log_error
from src.services.variant_service import VariantSelector

logger = logging.getLogger(__name__)


# ============================================================================
# Template CRUD Endpoints
# ============================================================================

async def create_template(
    name: str = Form(...),
    description: str = Form(None),
    created_by: str = Form(None)
):
    """Create a new post template."""
    try:
        logger.debug(f"create_template called with name: {name}")
        
        # Validate name
        if not name or len(name.strip()) == 0:
            log_error(
                action="template_create_empty_name",
                message="Attempted to create template with empty name",
                component="api",
                extra_data=json.dumps({"name_length": len(name) if name else 0})
            )
            return JSONResponse(
                status_code=400,
                content={"error": "Template name cannot be empty"}
            )
        
        with get_db() as db:
            template = PostTemplate(
                name=name.strip(),
                description=description.strip() if description else None,
                created_by=created_by.strip() if created_by else None,
                active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(template)
            db.commit()
            db.refresh(template)
            
            logger.info(f"Created new template with id: {template.id}")
            log_info(
                action="template_created",
                message=f"Created new template with id {template.id}",
                component="api",
                extra_data=json.dumps({
                    "template_id": template.id,
                    "name": name
                })
            )
            
            return {
                "id": template.id,
                "name": template.name,
                "description": template.description,
                "active": template.active,
                "created_at": template.created_at.isoformat(),
                "updated_at": template.updated_at.isoformat(),
                "created_by": template.created_by
            }
    
    except Exception as e:
        logger.error(f"Unexpected error in create_template: {str(e)}", exc_info=True)
        log_error(
            action="template_create_exception",
            message=f"Exception while creating template",
            component="api",
            extra_data=json.dumps({"error": str(e), "error_type": type(e).__name__})
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


async def get_template(template_id: int):
    """Get a single template with all its variants."""
    try:
        logger.debug(f"get_template called with template_id: {template_id}")
        
        with get_db() as db:
            template = db.query(PostTemplate).filter(PostTemplate.id == template_id).first()
            
            if not template:
                logger.warning(f"Template not found: {template_id}")
                return JSONResponse(
                    status_code=404,
                    content={"error": "Template not found"}
                )
            
            # Get all variants for this template
            variants = db.query(PostVariant).filter(
                PostVariant.template_id == template_id
            ).order_by(PostVariant.created_at.asc()).all()
            
            # Get schedules using this template
            schedules = db.query(Schedule).filter(
                Schedule.template_id == template_id
            ).all()
            
            result = {
                "id": template.id,
                "name": template.name,
                "description": template.description,
                "active": template.active,
                "created_at": template.created_at.isoformat(),
                "updated_at": template.updated_at.isoformat(),
                "created_by": template.created_by,
                "variants": [
                    {
                        "id": v.id,
                        "text": v.text,
                        "weight": v.weight,
                        "active": v.active,
                        "media_refs": v.media_refs,
                        "locale": v.locale,
                        "tags": v.tags,
                        "created_at": v.created_at.isoformat(),
                        "updated_at": v.updated_at.isoformat(),
                        "created_by": v.created_by
                    }
                    for v in variants
                ],
                "schedules": [
                    {
                        "id": s.id,
                        "kind": s.kind,
                        "selection_policy": s.selection_policy,
                        "no_repeat_window": s.no_repeat_window,
                        "no_repeat_scope": s.no_repeat_scope,
                        "enabled": s.enabled,
                        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None
                    }
                    for s in schedules
                ]
            }
            
            logger.info(f"Retrieved template {template_id} with {len(variants)} variants, {len(schedules)} schedules")
            return result
    
    except Exception as e:
        logger.error(f"Unexpected error in get_template: {str(e)}", exc_info=True)
        log_error(
            action="template_get_exception",
            message=f"Exception while getting template",
            component="api",
            extra_data=json.dumps({"template_id": template_id, "error": str(e), "error_type": type(e).__name__})
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


async def list_templates(active_only: bool = True):
    """Get all templates. Optionally include inactive templates."""
    try:
        logger.debug(f"list_templates called, active_only={active_only}")
        
        with get_db() as db:
            query = db.query(PostTemplate)
            
            if active_only:
                query = query.filter(PostTemplate.active == True)
            
            templates = query.order_by(PostTemplate.created_at.desc()).all()
            
            result = [
                {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "active": t.active,
                    "created_at": t.created_at.isoformat(),
                    "updated_at": t.updated_at.isoformat(),
                    "created_by": t.created_by
                }
                for t in templates
            ]
            
            logger.info(f"Retrieved {len(result)} templates (active_only={active_only})")
            return result
    
    except Exception as e:
        logger.error(f"Unexpected error in list_templates: {str(e)}", exc_info=True)
        log_error(
            action="templates_list_exception",
            message=f"Exception while listing templates",
            component="api",
            extra_data=json.dumps({"error": str(e), "error_type": type(e).__name__})
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


async def update_template(
    template_id: int,
    name: str = Form(None),
    description: str = Form(None),
    active: bool = Form(None)
):
    """Update an existing template."""
    try:
        logger.debug(f"update_template called with template_id: {template_id}")
        
        with get_db() as db:
            template = db.query(PostTemplate).filter(PostTemplate.id == template_id).first()
            
            if not template:
                log_error(
                    action="template_update_not_found",
                    message=f"Attempted to update non-existent template {template_id}",
                    component="api",
                    extra_data=json.dumps({"template_id": template_id})
                )
                return JSONResponse(
                    status_code=404,
                    content={"error": "Template not found"}
                )
            
            # Update fields if provided
            if name is not None:
                if len(name.strip()) == 0:
                    return JSONResponse(
                        status_code=400,
                        content={"error": "Template name cannot be empty"}
                    )
                template.name = name.strip()
            
            if description is not None:
                template.description = description.strip() if description else None
            
            if active is not None:
                template.active = active
            
            template.updated_at = datetime.utcnow()
            db.commit()
            
            logger.info(f"Updated template with id: {template_id}")
            log_info(
                action="template_updated",
                message=f"Updated template with id {template_id}",
                component="api",
                extra_data=json.dumps({"template_id": template_id})
            )
            
            return {
                "id": template.id,
                "name": template.name,
                "description": template.description,
                "active": template.active,
                "updated_at": template.updated_at.isoformat()
            }
    
    except Exception as e:
        logger.error(f"Unexpected error in update_template: {str(e)}", exc_info=True)
        log_error(
            action="template_update_exception",
            message=f"Exception while updating template",
            component="api",
            extra_data=json.dumps({"template_id": template_id, "error": str(e), "error_type": type(e).__name__})
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


async def delete_template(template_id: int):
    """Delete a template and all its variants (cascade)."""
    try:
        logger.debug(f"delete_template called with template_id: {template_id}")
        
        with get_db() as db:
            template = db.query(PostTemplate).filter(PostTemplate.id == template_id).first()
            
            if not template:
                logger.warning(f"Template not found: {template_id}")
                log_error(
                    action="template_delete_not_found",
                    message=f"Attempted to delete non-existent template {template_id}",
                    component="api",
                    extra_data=json.dumps({"template_id": template_id})
                )
                return JSONResponse(
                    status_code=404,
                    content={"error": "Template not found"}
                )
            
            # Check if template has schedules
            schedules_count = db.query(Schedule).filter(
                Schedule.template_id == template_id
            ).count()
            
            if schedules_count > 0:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": f"Cannot delete template: {schedules_count} schedule(s) are using it",
                        "schedules_count": schedules_count
                    }
                )
            
            # Delete template (variants will be cascade deleted)
            db.delete(template)
            db.commit()
            
            logger.info(f"Deleted template with id: {template_id}")
            log_info(
                action="template_deleted",
                message=f"Deleted template with id {template_id}",
                component="api",
                extra_data=json.dumps({"template_id": template_id})
            )
            
            return {
                "id": template_id,
                "message": "Template deleted successfully"
            }
    
    except Exception as e:
        logger.error(f"Unexpected error in delete_template: {str(e)}", exc_info=True)
        log_error(
            action="template_delete_exception",
            message=f"Exception while deleting template",
            component="api",
            extra_data=json.dumps({"template_id": template_id, "error": str(e), "error_type": type(e).__name__})
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


# ============================================================================
# Variant CRUD Endpoints
# ============================================================================

async def create_variant(
    template_id: int,
    text: str = Form(...),
    weight: int = Form(1),
    media_refs: str = Form(None),
    locale: str = Form(None),
    tags: str = Form(None),
    created_by: str = Form(None)
):
    """Create a new variant for a template."""
    try:
        logger.debug(f"create_variant called with template_id: {template_id}, text length: {len(text)}")
        
        # Validate text
        if not text or len(text.strip()) == 0:
            log_error(
                action="variant_create_empty",
                message="Attempted to create variant with empty text",
                component="api",
                extra_data=json.dumps({"template_id": template_id, "text_length": len(text) if text else 0})
            )
            return JSONResponse(
                status_code=400,
                content={"error": "Variant text cannot be empty"}
            )
        
        # Validate weight
        if weight < 1:
            return JSONResponse(
                status_code=400,
                content={"error": "Variant weight must be >= 1"}
            )
        
        # Validate X character limit
        if len(text) > 280:
            return JSONResponse(
                status_code=400,
                content={"error": f"Variant text exceeds 280 characters: {len(text)}"}
            )
        
        # Parse media_refs if provided
        media_data = None
        if media_refs:
            try:
                media_data = json.loads(media_refs)
                if not isinstance(media_data, list):
                    raise ValueError("media_refs must be a JSON array")
            except json.JSONDecodeError as e:
                log_error(
                    action="variant_create_invalid_media",
                    message="Failed to parse media_refs JSON",
                    component="api",
                    extra_data=json.dumps({"template_id": template_id, "error": str(e)})
                )
                return JSONResponse(
                    status_code=400,
                    content={"error": "media_refs must be a valid JSON array"}
                )
        
        with get_db() as db:
            # Verify template exists
            template = db.query(PostTemplate).filter(PostTemplate.id == template_id).first()
            if not template:
                return JSONResponse(
                    status_code=404,
                    content={"error": "Template not found"}
                )
            
            variant = PostVariant(
                template_id=template_id,
                text=text.strip(),
                weight=weight,
                active=True,
                media_refs=json.dumps(media_data) if media_data else None,
                locale=locale.strip() if locale else None,
                tags=tags.strip() if tags else None,
                created_by=created_by.strip() if created_by else None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(variant)
            db.commit()
            db.refresh(variant)
            
            logger.info(f"Created new variant with id: {variant.id} for template {template_id}")
            log_info(
                action="variant_created",
                message=f"Created new variant with id {variant.id} for template {template_id}",
                component="api",
                extra_data=json.dumps({
                    "variant_id": variant.id,
                    "template_id": template_id,
                    "text_length": len(text),
                    "weight": weight
                })
            )
            
            return {
                "id": variant.id,
                "template_id": variant.template_id,
                "text": variant.text,
                "weight": variant.weight,
                "active": variant.active,
                "media_refs": variant.media_refs,
                "locale": variant.locale,
                "tags": variant.tags,
                "created_at": variant.created_at.isoformat(),
                "updated_at": variant.updated_at.isoformat(),
                "created_by": variant.created_by
            }
    
    except Exception as e:
        logger.error(f"Unexpected error in create_variant: {str(e)}", exc_info=True)
        log_error(
            action="variant_create_exception",
            message=f"Exception while creating variant",
            component="api",
            extra_data=json.dumps({"template_id": template_id, "error": str(e), "error_type": type(e).__name__})
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


async def list_variants(template_id: int, active_only: bool = True):
    """Get all variants for a template. Optionally include inactive variants."""
    try:
        logger.debug(f"list_variants called with template_id: {template_id}, active_only={active_only}")
        
        with get_db() as db:
            query = db.query(PostVariant).filter(PostVariant.template_id == template_id)
            
            if active_only:
                query = query.filter(PostVariant.active == True)
            
            variants = query.order_by(PostVariant.created_at.asc()).all()
            
            result = [
                {
                    "id": v.id,
                    "template_id": v.template_id,
                    "text": v.text,
                    "weight": v.weight,
                    "active": v.active,
                    "media_refs": v.media_refs,
                    "locale": v.locale,
                    "tags": v.tags,
                    "created_at": v.created_at.isoformat(),
                    "updated_at": v.updated_at.isoformat(),
                    "created_by": v.created_by
                }
                for v in variants
            ]
            
            logger.info(f"Retrieved {len(result)} variants for template {template_id} (active_only={active_only})")
            return result
    
    except Exception as e:
        logger.error(f"Unexpected error in list_variants: {str(e)}", exc_info=True)
        log_error(
            action="variants_list_exception",
            message=f"Exception while listing variants",
            component="api",
            extra_data=json.dumps({"template_id": template_id, "error": str(e), "error_type": type(e).__name__})
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


async def update_variant(
    variant_id: int,
    text: str = Form(None),
    weight: int = Form(None),
    active: bool = Form(None),
    media_refs: str = Form(None),
    locale: str = Form(None),
    tags: str = Form(None)
):
    """Update an existing variant."""
    try:
        logger.debug(f"update_variant called with variant_id: {variant_id}")
        
        with get_db() as db:
            variant = db.query(PostVariant).filter(PostVariant.id == variant_id).first()
            
            if not variant:
                log_error(
                    action="variant_update_not_found",
                    message=f"Attempted to update non-existent variant {variant_id}",
                    component="api",
                    extra_data=json.dumps({"variant_id": variant_id})
                )
                return JSONResponse(
                    status_code=404,
                    content={"error": "Variant not found"}
                )
            
            # Update fields if provided
            if text is not None:
                if len(text.strip()) == 0:
                    return JSONResponse(
                        status_code=400,
                        content={"error": "Variant text cannot be empty"}
                    )
                if len(text) > 280:
                    return JSONResponse(
                        status_code=400,
                        content={"error": f"Variant text exceeds 280 characters: {len(text)}"}
                    )
                variant.text = text.strip()
            
            if weight is not None:
                if weight < 1:
                    return JSONResponse(
                        status_code=400,
                        content={"error": "Variant weight must be >= 1"}
                    )
                variant.weight = weight
            
            if active is not None:
                variant.active = active
            
            if media_refs is not None:
                if media_refs:
                    try:
                        media_data = json.loads(media_refs)
                        if not isinstance(media_data, list):
                            raise ValueError("media_refs must be a JSON array")
                        variant.media_refs = json.dumps(media_data)
                    except json.JSONDecodeError as e:
                        return JSONResponse(
                            status_code=400,
                            content={"error": "media_refs must be a valid JSON array"}
                        )
                else:
                    variant.media_refs = None
            
            if locale is not None:
                variant.locale = locale.strip() if locale else None
            
            if tags is not None:
                variant.tags = tags.strip() if tags else None
            
            variant.updated_at = datetime.utcnow()
            db.commit()
            
            logger.info(f"Updated variant with id: {variant_id}")
            log_info(
                action="variant_updated",
                message=f"Updated variant with id {variant_id}",
                component="api",
                extra_data=json.dumps({"variant_id": variant_id})
            )
            
            return {
                "id": variant.id,
                "template_id": variant.template_id,
                "text": variant.text,
                "weight": variant.weight,
                "active": variant.active,
                "media_refs": variant.media_refs,
                "locale": variant.locale,
                "tags": variant.tags,
                "updated_at": variant.updated_at.isoformat()
            }
    
    except Exception as e:
        logger.error(f"Unexpected error in update_variant: {str(e)}", exc_info=True)
        log_error(
            action="variant_update_exception",
            message=f"Exception while updating variant",
            component="api",
            extra_data=json.dumps({"variant_id": variant_id, "error": str(e), "error_type": type(e).__name__})
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


async def delete_variant(variant_id: int):
    """Delete a variant."""
    try:
        logger.debug(f"delete_variant called with variant_id: {variant_id}")
        
        with get_db() as db:
            variant = db.query(PostVariant).filter(PostVariant.id == variant_id).first()
            
            if not variant:
                logger.warning(f"Variant not found: {variant_id}")
                log_error(
                    action="variant_delete_not_found",
                    message=f"Attempted to delete non-existent variant {variant_id}",
                    component="api",
                    extra_data=json.dumps({"variant_id": variant_id})
                )
                return JSONResponse(
                    status_code=404,
                    content={"error": "Variant not found"}
                )
            
            # Delete variant
            db.delete(variant)
            db.commit()
            
            logger.info(f"Deleted variant with id: {variant_id}")
            log_info(
                action="variant_deleted",
                message=f"Deleted variant with id {variant_id}",
                component="api",
                extra_data=json.dumps({"variant_id": variant_id})
            )
            
            return {
                "id": variant_id,
                "message": "Variant deleted successfully"
            }
    
    except Exception as e:
        logger.error(f"Unexpected error in delete_variant: {str(e)}", exc_info=True)
        log_error(
            action="variant_delete_exception",
            message=f"Exception while deleting variant",
            component="api",
            extra_data=json.dumps({"variant_id": variant_id, "error": str(e), "error_type": type(e).__name__})
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


# ============================================================================
# Variant Selection Preview Endpoint
# ============================================================================

async def preview_variant_selection(
    schedule_id: int,
    planned_at: Optional[str] = None  # ISO datetime string
):
    """Preview which variant would be selected for a given planned_at time.
    
    Uses the same seed generation and selection logic as scheduler_tick().
    Returns: {
        "variant_id": int,
        "variant_text": str,
        "selection_seed": int,
        "planned_at": str
    }
    """
    try:
        logger.debug(f"preview_variant_selection called with schedule_id: {schedule_id}, planned_at: {planned_at}")
        
        from datetime import datetime
        import pytz
        
        with get_db() as db:
            schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
            
            if not schedule:
                return JSONResponse(
                    status_code=404,
                    content={"error": "Schedule not found"}
                )
            
            if not schedule.template_id:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Schedule does not use a template (no template_id)"}
                )
            
            # Parse planned_at or use schedule's next_run_at
            if planned_at:
                try:
                    planned_dt = datetime.fromisoformat(planned_at.replace('Z', '+00:00'))
                    if planned_dt.tzinfo is None:
                        planned_dt = pytz.UTC.localize(planned_dt)
                except ValueError as e:
                    return JSONResponse(
                        status_code=400,
                        content={"error": f"Invalid planned_at format: {e}. Expected ISO datetime string."}
                    )
            else:
                if not schedule.next_run_at:
                    return JSONResponse(
                        status_code=400,
                        content={"error": "No next_run_at set for schedule and no planned_at provided"}
                    )
                planned_dt = schedule.next_run_at
                if planned_dt.tzinfo is None:
                    planned_dt = pytz.UTC.localize(planned_dt)
            
            # Use VariantSelector to get the selection
            variant_selector = VariantSelector(db)
            selected_variant, selection_seed = variant_selector.select_variant(
                schedule,
                planned_dt
            )
            
            if not selected_variant:
                return JSONResponse(
                    status_code=404,
                    content={"error": "No active variants found for template"}
                )
            
            logger.info(f"Preview variant selection for schedule {schedule_id}: variant {selected_variant.id}")
            
            return {
                "variant_id": selected_variant.id,
                "variant_text": selected_variant.text,
                "selection_seed": selection_seed,
                "planned_at": planned_dt.isoformat(),
                "selection_policy": schedule.selection_policy
            }
    
    except Exception as e:
        logger.error(f"Unexpected error in preview_variant_selection: {str(e)}", exc_info=True)
        log_error(
            action="variant_preview_exception",
            message=f"Exception while previewing variant selection",
            component="api",
            extra_data=json.dumps({"schedule_id": schedule_id, "error": str(e), "error_type": type(e).__name__})
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


# ============================================================================
# Schedule Update Endpoint (for template_id and selection policies)
# ============================================================================

async def update_schedule(
    schedule_id: int,
    template_id: Optional[int] = Form(None),
    selection_policy: Optional[str] = Form(None),
    no_repeat_window: Optional[int] = Form(None),
    no_repeat_scope: Optional[str] = Form(None)
):
    """Update a schedule's template_id and selection policy settings.
    
    This endpoint allows updating a schedule to use a template instead of a post,
    or updating the selection policy for an existing template-based schedule.
    """
    try:
        logger.debug(f"update_schedule called with schedule_id: {schedule_id}")
        
        from src.services.scheduler_service import ScheduleResolver
        
        # Validate selection policy if provided
        valid_policies = ["RANDOM_UNIFORM", "RANDOM_WEIGHTED", "ROUND_ROBIN", "NO_REPEAT_WINDOW"]
        if selection_policy and selection_policy not in valid_policies:
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid selection_policy. Must be one of: {', '.join(valid_policies)}"}
            )
        
        # Validate no_repeat_scope if provided
        if no_repeat_scope and no_repeat_scope not in ["template", "schedule"]:
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid no_repeat_scope. Must be 'template' or 'schedule'"}
            )
        
        # Validate no_repeat_window if provided
        if no_repeat_window is not None and no_repeat_window < 0:
            return JSONResponse(
                status_code=400,
                content={"error": "no_repeat_window must be >= 0"}
            )
        
        with get_db() as db:
            schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
            
            if not schedule:
                log_error(
                    action="schedule_update_not_found",
                    message=f"Attempted to update non-existent schedule {schedule_id}",
                    component="api",
                    extra_data=json.dumps({"schedule_id": schedule_id})
                )
                return JSONResponse(
                    status_code=404,
                    content={"error": "Schedule not found"}
                )
            
            # Update template_id if provided
            if template_id is not None:
                # Verify template exists if setting template_id
                if template_id > 0:
                    template = db.query(PostTemplate).filter(PostTemplate.id == template_id).first()
                    if not template:
                        return JSONResponse(
                            status_code=404,
                            content={"error": "Template not found"}
                        )
                    schedule.template_id = template_id
                    # Clear post_id when switching to template-based
                    schedule.post_id = None
                else:
                    # template_id = 0 or None means clear it
                    schedule.template_id = None
            
            # Update selection policy if provided
            if selection_policy is not None:
                schedule.selection_policy = selection_policy
            
            # Update no_repeat_window if provided
            if no_repeat_window is not None:
                schedule.no_repeat_window = no_repeat_window
            
            # Update no_repeat_scope if provided
            if no_repeat_scope is not None:
                schedule.no_repeat_scope = no_repeat_scope
            
            # If we changed template_id or need to recalculate, update next_run_at
            if template_id is not None or selection_policy is not None:
                resolver = ScheduleResolver()
                next_run_at = resolver.resolve_schedule(schedule)
                
                if next_run_at:
                    schedule.next_run_at = next_run_at
                    schedule.enabled = True
                else:
                    schedule.next_run_at = None
                    schedule.enabled = False
                    logger.warning(f"Could not resolve schedule {schedule_id} after update")
            
            schedule.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(schedule)
            
            logger.info(f"Updated schedule {schedule_id}: template_id={schedule.template_id}, policy={schedule.selection_policy}")
            log_info(
                action="schedule_updated",
                message=f"Updated schedule {schedule_id} with template and selection policy",
                component="api",
                extra_data=json.dumps({
                    "schedule_id": schedule_id,
                    "template_id": schedule.template_id,
                    "selection_policy": schedule.selection_policy,
                    "no_repeat_window": schedule.no_repeat_window,
                    "no_repeat_scope": schedule.no_repeat_scope
                })
            )
            
            return {
                "id": schedule.id,
                "template_id": schedule.template_id,
                "post_id": schedule.post_id,
                "selection_policy": schedule.selection_policy,
                "no_repeat_window": schedule.no_repeat_window,
                "no_repeat_scope": schedule.no_repeat_scope,
                "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
                "enabled": schedule.enabled,
                "updated_at": schedule.updated_at.isoformat()
            }
    
    except Exception as e:
        logger.error(f"Unexpected error in update_schedule: {str(e)}", exc_info=True)
        log_error(
            action="schedule_update_exception",
            message=f"Exception while updating schedule",
            component="api",
            extra_data=json.dumps({"schedule_id": schedule_id, "error": str(e), "error_type": type(e).__name__})
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

