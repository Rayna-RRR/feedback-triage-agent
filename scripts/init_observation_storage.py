"""Initialize only the observation-task table in an existing PostgreSQL database."""
from feedback_triage_agent.task_storage import (
    configured_storage, PostgresTaskStore, StorageError,
)


def main():
    try:
        store = configured_storage("data/observation_tasks")
        if not isinstance(store, PostgresTaskStore):
            raise SystemExit("Select FEEDBACK_RISK_STORAGE_BACKEND=postgresql before initialization.")
        store.initialize_schema()
        store.available()
    except StorageError:
        raise SystemExit("Observation storage initialization failed; check the database configuration and access.")
    print("PostgreSQL observation-task schema initialized. No task records were deleted or rewritten.")


if __name__ == "__main__":
    main()
