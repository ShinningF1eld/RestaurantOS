# Reproducible dependencies and formatting

The supported toolchain is Python 3.12 and Node.js 24. The Python runtime lock is
`backend/requirements.txt`; `backend/requirements-dev.txt` is the complete development
and test lock, including runtime dependencies. Both are generated from the adjacent
`.in` source files, include exact transitive versions and artifact hashes, and are
installed without resolving newer versions during validation. The frontend uses
`frontend/package-lock.json`; clean frontend installs use `npm ci`.

## Update Python locks

Use uv 0.11.31 to compile a universal lock targeting Python 3.12. To bootstrap that
exact compiler version into an existing Python installation:

```powershell
py -3.12 -m pip install uv==0.11.31
```

On macOS or Linux, use the supported Python 3.12 interpreter instead:

```sh
python3.12 -m pip install uv==0.11.31
```

From the `backend` directory, update the runtime lock first, then the full development
lock. Existing output pins are retained unless `--upgrade` is supplied; change the
desired direct pin in the corresponding `.in` file before upgrading that dependency.

```sh
uv pip compile --universal --python-version 3.12 --generate-hashes --no-header \
  --output-file requirements.txt requirements.in
uv pip compile --universal --python-version 3.12 --generate-hashes --no-header \
  --constraint requirements.txt --output-file requirements-dev.txt requirements-dev.in
```

For a deliberate complete refresh, add `--upgrade` to both compile commands. To
upgrade selected dependencies, add `--upgrade-package package-name` to each relevant
command and update its direct requirement in the input file first. Review both lockfile
diffs together. The universal resolver keeps platform- and interpreter-specific
dependencies conditional, allowing the same locks to serve Windows and Linux while
targeting Python 3.12.

## Install and verify

Use an empty virtual environment for a development/test install. Hash enforcement
rejects an artifact whose bytes do not match the committed lock:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.txt
```

On macOS or Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
```

Use `requirements.txt` instead of `requirements-dev.txt` to install only runtime
dependencies. `uv pip sync requirements.txt` and `uv pip sync requirements-dev.txt`
are also available when using uv; sync removes packages outside the selected lock.
CI should install the full development lock with
`python -m pip install --require-hashes -r backend/requirements-dev.txt`.

## Lint, format, and type checks

From `backend`, run the lint and formatter checks independently; the formatter check
does not modify files, while `ruff format` applies the mechanical formatting:

```sh
python -m ruff check app tests
python -m ruff format --check app tests
python -m ruff format app tests
python -m mypy app
```

From `frontend`, lint, formatting, and TypeScript remain separate checks:

```sh
npm ci
npm run lint
npm run format:check
npm run format
npm run typecheck
```

The checked-in formatter settings preserve the existing lint and type rules. The
format commands only rewrite layout and whitespace; review their diff for semantic
changes before committing.

Pre-commit hooks remain optional. They are not required to install dependencies or
reproduce these checks.
