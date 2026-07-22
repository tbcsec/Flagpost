"""Automation rules API (ARCHITECTURE.md §5, ROADMAP #25).

Two tiers of rule, mirroring §5.1 ownership:

- **Org rules** (``owner_user_id = None``) — gated on the automation
  permissions. The competition context rides ``?competition_id=…`` (the same
  place ``require_permission`` resolves it, §7.6): with it, you're managing
  that competition's rules; without it, you're managing **global** rules,
  which only a *globally*-assigned holder (Administrator) passes for — a
  judge's per-competition grant doesn't reach `competition_id=None`.
  Mutations on an existing rule re-check the permission against **the rule's
  own** competition, so a judge of A can't edit B's rule by lying in the
  query string.
- **Personal rules** (``/personal``) — any authenticated user, no automation
  permission needed (§5.1), schema-restricted to notify-self.

Org endpoints 404 when the automations module is disabled for the competition
(§11.1 step 3 — the enabled flag is checked per request, not at mount). Every
mutation emits its §3.2 event (``automation.rule_created/updated/deleted``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user, require_permission, user_has_permission
from db import get_db
from models.automation import AutomationRule
from models.competition import Competition
from models.user import User
from plugins.loader import is_module_enabled
from schemas.automation import (
    AutomationCatalog,
    PersonalRuleCreate,
    RuleCreate,
    RuleOut,
    RuleUpdate,
)
from utils.automation_catalog import build_catalog
from utils.event_bus import event_bus

router = APIRouter(prefix="/api/automations", tags=["automations"])


def _to_out(rule: AutomationRule) -> RuleOut:
    return RuleOut(
        id=rule.id,
        name=rule.name,
        trigger_type=rule.trigger_type,
        conditions=rule.conditions or [],
        actions=rule.actions or [],
        is_enabled=rule.is_enabled,
        competition_id=rule.competition_id,
        owner_user_id=rule.owner_user_id,
        trigger_count=rule.trigger_count,
        last_triggered_at=rule.last_triggered_at,
        created_at=rule.created_at,
    )


async def _require_module_enabled(db: AsyncSession, competition_id: str) -> None:
    if await db.get(Competition, competition_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    if not await is_module_enabled(db, "automations", competition_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The automations module is disabled for this competition",
        )


def _dump_rule_fields(body: RuleCreate | RuleUpdate | PersonalRuleCreate) -> dict:
    return {
        "name": body.name,
        "trigger_type": body.trigger_type,
        "conditions": [c.model_dump(exclude_none=True) for c in body.conditions],
        "actions": [a.model_dump(exclude_none=True) for a in body.actions],
        "is_enabled": body.is_enabled,
    }


async def _emit_rule_event(verb: str, rule: AutomationRule, actor: User) -> None:
    await event_bus.emit(
        f"automation.rule_{verb}",
        {
            "rule_id": rule.id,
            "name": rule.name,
            "competition_id": rule.competition_id,
            "owner_user_id": rule.owner_user_id,
            "user_id": actor.id,
        },
    )


# --- catalog (registered before /{rule_id} so the literal path wins) ---------


@router.get("/catalog", response_model=AutomationCatalog)
async def automation_catalog(
    current_user: User = Depends(get_current_user),
) -> AutomationCatalog:
    """Everything the visual builder is generated from — triggers + their
    payload fields, operators, and action config fields (§5.5). Authenticated-
    only (personal-rule authors need it too, §5.1)."""
    return AutomationCatalog(**build_catalog())


# --- personal rules (§5.1) ---------------------------------------------------


@router.get("/personal", response_model=list[RuleOut])
async def list_personal_rules(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RuleOut]:
    rules = (
        (
            await db.execute(
                select(AutomationRule)
                .where(AutomationRule.owner_user_id == current_user.id)
                .order_by(AutomationRule.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_to_out(r) for r in rules]


@router.post(
    "/personal", response_model=RuleOut, status_code=status.HTTP_201_CREATED
)
async def create_personal_rule(
    body: PersonalRuleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RuleOut:
    if body.competition_id is not None:
        if await db.get(Competition, body.competition_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
            )
    rule = AutomationRule(
        owner_user_id=current_user.id,
        competition_id=body.competition_id,
        **_dump_rule_fields(body),
    )
    db.add(rule)
    await db.commit()
    await _emit_rule_event("created", rule, current_user)
    return _to_out(rule)


async def _own_personal_rule(
    db: AsyncSession, rule_id: str, user: User
) -> AutomationRule:
    rule = await db.get(AutomationRule, rule_id)
    # 404 (not 403) for someone else's rule — existence isn't disclosed.
    if rule is None or rule.owner_user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found"
        )
    return rule


@router.put("/personal/{rule_id}", response_model=RuleOut)
async def update_personal_rule(
    rule_id: str,
    body: PersonalRuleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RuleOut:
    rule = await _own_personal_rule(db, rule_id, current_user)
    for key, value in _dump_rule_fields(body).items():
        setattr(rule, key, value)
    rule.competition_id = body.competition_id
    await db.commit()
    await _emit_rule_event("updated", rule, current_user)
    return _to_out(rule)


@router.delete("/personal/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_personal_rule(
    rule_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    rule = await _own_personal_rule(db, rule_id, current_user)
    await _emit_rule_event("deleted", rule, current_user)
    await db.delete(rule)
    await db.commit()


# --- org rules (§5.1) --------------------------------------------------------


@router.get("", response_model=list[RuleOut])
async def list_rules(
    competition_id: str | None = None,
    current_user: User = Depends(require_permission("automation_view")),
    db: AsyncSession = Depends(get_db),
) -> list[RuleOut]:
    """With ``competition_id``: that competition's rules plus the global rules
    that also fire there. Without: global rules only (global grant required —
    the permission dependency already enforced that)."""
    stmt = select(AutomationRule).where(AutomationRule.owner_user_id.is_(None))
    if competition_id is not None:
        await _require_module_enabled(db, competition_id)
        stmt = stmt.where(
            (AutomationRule.competition_id == competition_id)
            | (AutomationRule.competition_id.is_(None))
        )
    else:
        stmt = stmt.where(AutomationRule.competition_id.is_(None))
    rules = (
        (await db.execute(stmt.order_by(AutomationRule.created_at.desc())))
        .scalars()
        .all()
    )
    return [_to_out(r) for r in rules]


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    body: RuleCreate,
    competition_id: str | None = None,
    current_user: User = Depends(require_permission("automation_create")),
    db: AsyncSession = Depends(get_db),
) -> RuleOut:
    if competition_id is not None:
        await _require_module_enabled(db, competition_id)
    rule = AutomationRule(
        competition_id=competition_id,
        owner_user_id=None,
        **_dump_rule_fields(body),
    )
    db.add(rule)
    await db.commit()
    await _emit_rule_event("created", rule, current_user)
    return _to_out(rule)


async def _editable_org_rule(
    db: AsyncSession, rule_id: str, user: User
) -> AutomationRule:
    """Load an org rule, enforcing ``automation_edit`` against the **rule's
    own** competition (global rule → global grant) — never the caller-supplied
    query context."""
    rule = await db.get(AutomationRule, rule_id)
    if rule is None or rule.owner_user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found"
        )
    if not await user_has_permission(
        db, user.id, "automation_edit", rule.competition_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing permission: automation_edit",
        )
    return rule


@router.get("/{rule_id}", response_model=RuleOut)
async def get_rule(
    rule_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RuleOut:
    rule = await db.get(AutomationRule, rule_id)
    if rule is None or rule.owner_user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found"
        )
    if not await user_has_permission(
        db, current_user.id, "automation_view", rule.competition_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found"
        )
    return _to_out(rule)


@router.put("/{rule_id}", response_model=RuleOut)
async def update_rule(
    rule_id: str,
    body: RuleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RuleOut:
    rule = await _editable_org_rule(db, rule_id, current_user)
    for key, value in _dump_rule_fields(body).items():
        setattr(rule, key, value)
    await db.commit()
    await _emit_rule_event("updated", rule, current_user)
    return _to_out(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    rule = await _editable_org_rule(db, rule_id, current_user)
    await _emit_rule_event("deleted", rule, current_user)
    await db.delete(rule)
    await db.commit()
