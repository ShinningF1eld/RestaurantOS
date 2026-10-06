# Backend coverage reports

Backend coverage is a review aid for choosing regressions around meaningful
behavior. Branch coverage is enabled for the full `backend/app` package, with no
percentage gate. The unit and service-backed suites write separate reports so
their coverage contribution stays visible instead of one suite replacing or
blending with the other.

Run from `backend/` with the committed development lock installed. The unit
suite uses only pure tests and needs no service URL:

```powershell
python -m pytest tests/unit --cov=app `
  --cov-report=term-missing `
  --cov-report=xml:coverage/backend-unit/coverage.xml `
  --cov-report=json:coverage/backend-unit/coverage.json `
  --cov-report=html:coverage/backend-unit/html
```

The integration report covers every service-backed backend test: repository/API
integration tests, HTTP contract characterization, and top-level service tests.
The `--ignore` selector keeps the unit report and service-backed report
disjoint while including future backend test paths. Run only with a migrated
disposable database provided through `TEST_DATABASE_URL`:

```powershell
python -m pytest tests --ignore=tests/unit --cov=app `
  --cov-report=term-missing `
  --cov-report=xml:coverage/backend-integration/coverage.xml `
  --cov-report=json:coverage/backend-integration/coverage.json `
  --cov-report=html:coverage/backend-integration/html
```

Reports are written beneath `backend/coverage/backend-unit/` and
`backend/coverage/backend-integration/`. Both suites emit a terminal table with
missing line numbers plus XML, JSON, and browsable HTML. Pytest-cov writes these
reports when tests fail as well, while preserving pytest's nonzero exit status.
The shared validator must keep those output directories under the existing
`backend/coverage/**` CI artifact path.

Coverage's `source = ["app"]` boundary includes application modules and excludes
the test suite, vendored or installed dependencies, Alembic revisions, and
generated build/test output. The application package contains handwritten
modules; Python bytecode caches are not measured as source. Empty modules are
omitted from tables, and no lines or branches are hidden with broad exclusions.
Review missed branches in policy, authorization, transaction, and error-handling
paths first, then add a regression test only when it protects an observable
behavior.

The suite selectors deliberately avoid overlap: `tests/unit` is the isolated
pure layer; the integration command includes all remaining backend test paths
that require the migrated database. Browser coverage instrumentation is not
required for this milestone.
