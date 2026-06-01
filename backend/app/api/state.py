from collections import defaultdict

from .schemas import LectureSession, RealtimeEvent


class AppState:
    """Temporary in-memory state used while core managers are not ready.

    This keeps the API routes testable during the first MVP stage. Replace this
    with SessionManager, ContextManager, KnowledgeGraphManager, and LocalStorage
    instead of adding complex behavior here.
    """

    def __init__(self) -> None:
        # Active and ended sessions keyed by session_id. This data is lost when
        # the server restarts; LocalStorage will become the durable source later.
        self.sessions: dict[str, LectureSession] = {}

        # Raw received events per session. ContextManager will later transform
        # these into transcript, timeline, visuals, and graph updates.
        self.events: dict[str, list[RealtimeEvent]] = defaultdict(list)


app_state = AppState()
