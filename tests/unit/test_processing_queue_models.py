"""Unit checks for processing queue model contracts."""
from app.storage.models import Base


def test_processing_run_has_durable_queue_and_lease_fields():
    table = Base.metadata.tables["processing_runs"]
    assert {
        "idempotency_key", "attempt_count", "max_attempts", "available_at",
        "lease_owner", "lease_expires_at", "heartbeat_at",
    } <= set(table.columns.keys())
    constraints = {item.name for item in table.constraints}
    assert "uq_processing_runs_idempotency" in constraints
    assert "ck_processing_runs_running_lease" in constraints
    assert "ck_processing_runs_nonrunning_without_lease" in constraints
    assert "ck_processing_runs_attempts" in constraints


def test_processing_run_queue_has_tenant_scoped_claim_index():
    table = Base.metadata.tables["processing_runs"]
    assert "ix_processing_runs_queue" in {item.name for item in table.indexes}
