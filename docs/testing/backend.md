# Backend testing strategy

## Layer boundaries and commands

From `backend/`, run the pure unit layer with:

```powershell
python -m pytest tests/unit
```

The root validation gate uses the same selector and removes `DATABASE*`,
`TEST_DATABASE*`, `AUTH_*`, and `REDIS*` variables before starting pytest:

```powershell
python scripts/validate.py --gate backend-unit --no-install
```

Run the full repository, API, and characterization suites through the disposable
service gate from the repository root:

```powershell
python scripts/validate.py --gate backend-integration --no-install
```

That gate starts an isolated PostgreSQL/Redis Compose project, creates a unique
disposable PostgreSQL database from the test template, applies Alembic head,
runs the complete backend suite, checks model drift, and drops the database and
services on exit. `--external-services` is reserved for CI and requires an
explicit `TEST_DATABASE_URL`. Never point the suite at the application database.

`tests/unit/` contains domain policies, calculations, configuration validation,
and service orchestration with fakes. `tests/integration/` contains both direct
PostgreSQL repository/model checks and HTTP workflows through FastAPI with real
authentication and tenant scoping. `tests/characterization/` protects HTTP
contracts and also uses the disposable database because the application and the
shared cleanup fixture are configured during collection. The two historical
top-level tests are service-backed: `test_health.py` imports the configured
application and `test_order_flow_integration.py` exercises a full authenticated
business journey.

## Fixture lifecycle and isolation

The root `tests/conftest.py` recognizes an explicitly selected `tests/unit`
path before test-module collection. In this mode it does not read `.env`, require
or inject service variables, create a SQLAlchemy engine, or connect to services.
The unit fixture replaces database cleanup with a no-op and blocks socket
`connect`/`connect_ex` calls. The isolation test also verifies that the app's
database engine module is not imported. Tests that need valid application
settings construct them with `_env_file=None` and throwaway local-only values.

Every other pytest selection is service-backed. Before importing application
modules, pytest requires `TEST_DATABASE_URL`, accepts only the
`postgresql+asyncpg` driver and a database name ending in `_test`, points the app
to that URL, generates process-local auth test secrets, and creates the fixture
engine. A missing URL or unsafe target fails before collection can reach the
truncate fixture. The root autouse fixture truncates application tables before
and after each non-unit test; the unit conftest shadows it with a no-op. The
sync fixture engine is disposed when pytest exits. HTTP authentication fixtures
log in through the real routes rather than overriding authorization.
`integration/test_database_isolation.py` places a provisioned-user case directly
before a case that asserts its rows have been removed, so the cleanup lifecycle
is also executable evidence rather than only fixture setup.

## Requirement-to-test map

| Critical behavior | Existing executable coverage |
|---|---|
| Order transitions, permission rules, totals, inventory math | `unit/test_order_domain.py::test_valid_order_transitions_are_returned_in_canonical_form`; `unit/test_tenancy_policies.py::test_all_roles_have_operational_reads`, `test_employee_cannot_manage_or_read_financial_analytics`, and `test_manager_cannot_administer_ownership_or_delete`; `unit/test_order_service.py::test_create_builds_price_snapshots_inside_one_transaction`; `unit/test_inventory_quantities.py` |
| Cross-tenant reads/writes and tenant-scoped lists | `integration/test_tenant_access.py::test_cross_tenant_direct_nested_reads_and_writes`, `test_lists_counts_and_payload_references_are_scoped`, and `test_single_org_membership_and_cross_org_assignment_admin` |
| Role restrictions and immediate revocation | `integration/test_tenant_access.py::test_employee_preparation_only_and_forbidden_fields_roll_back`, `test_owner_admin_last_owner_and_immediate_revocation`, and `test_membership_creation_assignment_validation_and_live_role_change`; `integration/test_inventory_management.py::test_role_and_tenant_scope` and `test_role_and_assignment_revocation_are_immediate` |
| Refresh replay revokes the family and account disable revokes issued credentials | `integration/auth/test_auth_http.py::test_replay_commits_revocation_and_rejects_successor`, `test_concurrent_disable_prevents_usable_credentials`, and `test_rotation_and_logout_serialize` |
| Same-key order replay returns the original immutable snapshot; changed payload is rejected | `integration/test_order_inventory.py::test_order_idempotency_replays_original_snapshot_after_updates` |
| Same-key inventory create/movement replay and payload mismatch | `integration/test_inventory_management.py::test_lifecycle_retries_ledger_and_deletion` |
| Fixture cleanup prevents test data leaking into the next case | `integration/test_database_isolation.py::test_fixture_data_is_present_only_during_its_test` followed by `test_previous_test_rows_are_cleared_before_the_next_case` |
| Failed writes roll back related state | `integration/test_order_transactions.py::test_failed_status_and_item_update_rolls_back_all_order_changes`; `integration/test_order_inventory.py::test_insufficient_later_ingredient_rolls_back_prior_consumption_and_order_update` and `test_acceptance_flush_failures_roll_back_balance_movement_order_and_audit`; `integration/test_inventory_management.py::test_audit_failure_rolls_back_balance_and_movement` |
| Concurrent stock acceptance cannot overdraw | `integration/test_order_inventory.py::test_two_distinct_managers_accepting_competing_orders_cannot_overdraw` uses events around the shared restaurant lock to prove the second request reached the lock while the first held it |
| Cancellation never restores consumed stock | `integration/test_order_inventory.py::test_cancellation_never_returns_stock_after_recipe_edit_and_history_is_retained` |

Authentication race tests synchronize at the conflicting repository operation,
after both requests reach the user or session-family lock. Inventory races use
events to hold and observe the first transaction's lock, then assert that the
second request is blocked at that same lock before release. These tests use
bounded timeouts only as deadlock guards, not as evidence that overlap occurred.

Workers and events do not exist in this milestone. Milestone 8 owns future tests
for delivery, retry, duplicate handling, and failure recovery; no worker/event
coverage is claimed here.
