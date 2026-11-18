"""Which escalations a set of filters selects. The Escalations page and the Overall quality figures both use this,
so the two can never disagree: an escalation counts when it was raised in the period and matches the
client / project / editor / QC member / editor-type filters."""
from __future__ import annotations

from ..models import Escalation
from .scope import Scope


def where(scope: Scope) -> list:
    c = [Escalation.deleted_at.is_(None), Escalation.raised_date >= scope.date_from,
         Escalation.raised_date <= scope.date_to]
    if scope.client_ids:
        c.append(Escalation.client_id.in_(scope.client_ids))
    if scope.project_ids:
        c.append(Escalation.project_id.in_(scope.project_ids))
    if scope.editor_id is not None:
        c.append(Escalation.editor_id == scope.editor_id)
    if scope.qc_member_id is not None:
        c.append(Escalation.qc_member_id == scope.qc_member_id)
    if scope.editor_type:
        c.append(Escalation.editor_type == scope.editor_type)
    return c
