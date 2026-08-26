from app.models.enriched_profile import EnrichedProfile
from app.models.enrichment_job import EnrichmentJob, EnrichmentSource, JobStatus
from app.models.event import Event, EventStatus
from app.models.match import Match, MatchStatus
from app.models.matching_admin import EmailLog, EventParticipantMapping, MatchProfile, SmtpMaster
from app.models.participant import (
    EnrichmentStatus,
    MembershipTier,
    Participant,
    ParticipantStatus,
)
from app.models.participant_embedding import ParticipantEmbedding
from app.models.rbac import (
    CompanyMaster,
    PermissionMaster,
    RoleMaster,
    RolePermissionMapping,
    TagMaster,
    UserTagMapping,
)
from app.models.upload_batch import ParticipantUploadBatch
from app.models.user import UserMaster

# UserMaster/RoleMaster/etc. (Phase 8 merge, Task 51 onward) must be
# importable from here too, not just from their own submodules: several
# QBCals-native models (Match.reviewed_by_user_id, Event.owner_user_id) FK
# to user_master by string table name, and SQLAlchemy only resolves a
# string-based FK target against tables whose model has actually been
# imported into the current process. The FastAPI app process always ends up
# importing every model anyway (main.py's router chain touches all of
# them), which is why this gap went unnoticed until Task 65's Celery worker
# process - which imports only app.workers.* - hit
# NoReferencedTableError resolving matches.reviewed_by_user_id at commit
# time. Importing app.models (this package) anywhere now pulls in the full
# set, in either process.

__all__ = [
    "Event",
    "EventStatus",
    "Participant",
    "MembershipTier",
    "EnrichmentStatus",
    "ParticipantStatus",
    "Match",
    "MatchStatus",
    "EnrichmentJob",
    "EnrichmentSource",
    "JobStatus",
    "ParticipantEmbedding",
    "EnrichedProfile",
    "UserMaster",
    "RoleMaster",
    "PermissionMaster",
    "RolePermissionMapping",
    "CompanyMaster",
    "TagMaster",
    "UserTagMapping",
    "EventParticipantMapping",
    "SmtpMaster",
    "MatchProfile",
    "EmailLog",
    "ParticipantUploadBatch",
]
