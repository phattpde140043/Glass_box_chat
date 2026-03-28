from ..repositories.contracts import HealthRepository


class HealthService:
    """Responsible for system health checks."""

    def __init__(self, repository: HealthRepository) -> None:
        self._repository = repository

    def get_health(self) -> dict[str, str]:
        return {
            "status": "ok",
            "storage": "sqlite",
            "databasePath": str(self._repository.get_database_path()),
        }
