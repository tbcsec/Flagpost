"""SQLAlchemy models.

Importing this package imports every model module so ``Base.metadata`` is
fully populated — Alembic autogenerate and metadata-create both rely on that.
Add new model modules to the imports below as domains are built.
"""

from models.announcement import Announcement
from models.attachment import Attachment
from models.audit_log import AuditLogEntry
from models.automation import Achievement, AutomationRule
from models.challenge import Category, Challenge
from models.collab import CollabDocument
from models.competition import Competition
from models.competition_module import CompetitionModule
from models.dashboard_layout import DashboardLayout
from models.feedback import (
    ChallengeRating,
    Survey,
    SurveyAnswer,
    SurveyQuestion,
    SurveyResponse,
)
from models.hint import Hint, HintReveal
from models.mc_guess_reset import MCGuessReset
from models.notification import Notification
from models.role import Role, RoleAssignment
from models.score_adjustment import ScoreAdjustment
from models.site_settings import SiteSettings
from models.submission import Submission
from models.team import Team, TeamMembership
from models.ticket import Ticket, TicketMessage
from models.user import RefreshSession, User

__all__ = [
    "Achievement",
    "Announcement",
    "Attachment",
    "AuditLogEntry",
    "AutomationRule",
    "Category",
    "Challenge",
    "ChallengeRating",
    "CollabDocument",
    "Competition",
    "CompetitionModule",
    "DashboardLayout",
    "Hint",
    "HintReveal",
    "MCGuessReset",
    "Notification",
    "Role",
    "RoleAssignment",
    "ScoreAdjustment",
    "Survey",
    "SurveyAnswer",
    "SurveyQuestion",
    "SurveyResponse",
    "SiteSettings",
    "Submission",
    "RefreshSession",
    "Team",
    "TeamMembership",
    "Ticket",
    "TicketMessage",
    "User",
]
