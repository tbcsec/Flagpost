"""SQLAlchemy models.

Importing this package imports every model module so ``Base.metadata`` is
fully populated — Alembic autogenerate and metadata-create both rely on that.
Add new model modules to the imports below as domains are built.
"""

from models.ai import (
    AiCompetitionSettings,
    AiConversation,
    AiDisclosureAcceptance,
    AiMessage,
    AiSettings,
)
from models.announcement import Announcement
from models.api_token import ApiToken
from models.attachment import Attachment
from models.audit_log import AuditLogEntry
from models.automation import Achievement, AutomationRule
from models.bracket import BracketMembership
from models.certificate import CertificateExportJob, CertificateFont, CertificateTemplate
from models.challenge import Category, Challenge
from models.collab import CollabDocument
from models.competition import Competition
from models.competition_module import CompetitionModule
from models.dashboard_layout import DashboardLayout
from models.email_verification import EmailVerificationToken
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
from models.identity_provider import (
    AuthLoginState,
    IdentityProvider,
    UserExternalIdentity,
)
from models.page import Page
from models.password_reset import PasswordResetToken
from models.report import CompetitionReport
from models.role import Role, RoleAssignment
from models.rules_acceptance import RulesAcceptance
from models.score_adjustment import ScoreAdjustment
from models.site_settings import SiteSettings
from models.submission import Submission
from models.team import Team, TeamApplication, TeamMembership
from models.ticket import Ticket, TicketMessage
from models.ticket_attachment import TicketAttachment
from models.user import RefreshSession, User

__all__ = [
    "Achievement",
    "AiCompetitionSettings",
    "AiConversation",
    "AiDisclosureAcceptance",
    "AiMessage",
    "AiSettings",
    "Announcement",
    "ApiToken",
    "Attachment",
    "AuditLogEntry",
    "AutomationRule",
    "BracketMembership",
    "Category",
    "CertificateExportJob",
    "CertificateFont",
    "CertificateTemplate",
    "Challenge",
    "ChallengeRating",
    "CollabDocument",
    "Competition",
    "CompetitionModule",
    "CompetitionReport",
    "DashboardLayout",
    "EmailVerificationToken",
    "Hint",
    "HintReveal",
    "MCGuessReset",
    "Notification",
    "AuthLoginState",
    "IdentityProvider",
    "Page",
    "PasswordResetToken",
    "Role",
    "RoleAssignment",
    "RulesAcceptance",
    "ScoreAdjustment",
    "Survey",
    "SurveyAnswer",
    "SurveyQuestion",
    "SurveyResponse",
    "SiteSettings",
    "Submission",
    "RefreshSession",
    "Team",
    "TeamApplication",
    "TeamMembership",
    "Ticket",
    "TicketAttachment",
    "TicketMessage",
    "User",
    "UserExternalIdentity",
]
