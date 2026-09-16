# ADR 0001: Evolve RestaurantOS as a modular monolith

- Status: Accepted
- Date: 2026-09-16

## Context

RestaurantOS currently consists of a Next.js application, one FastAPI API, and
one PostgreSQL database. Core restaurant, catalog, order, and analytics behavior
is still incomplete, and the backend currently places persistence and business
orchestration directly in routers.

Splitting the system into independently deployed services now would add network,
deployment, consistency, and observability costs before stable domain boundaries
or measured scaling needs exist.

## Decision

RestaurantOS will evolve as a modular monolith. The FastAPI API and any future
worker may run as separate processes while sharing versioned domain and
application code. New code should move gradually toward this dependency
direction when a milestone requires it:

```text
API router -> application service/use case -> domain/repository -> adapter
```

Existing files will not be reorganized solely to match an ideal directory tree.
Characterization tests and vertical behavior take priority over broad rewrites.

A separately deployed service requires evidence of at least one of:

- an independent scaling profile;
- a materially different availability or security boundary;
- repeated deployment interference with unrelated modules;
- a stable boundary supported by measured operational need.

## Consequences

Positive consequences:

- transactions and schema evolution remain straightforward;
- local development and CI use fewer moving parts;
- business boundaries can be discovered through working vertical slices;
- later extraction remains possible behind explicit module contracts.

Trade-offs:

- process-level isolation is not available between modules;
- disciplined imports and ownership will become important as the codebase grows;
- the current router-heavy implementation still needs incremental boundaries in
  later milestones.

## Not decided here

This ADR does not select authentication, tenant, queue, cache, deployment, ML,
or AI-provider technologies. It also does not authorize a Milestone 0
application refactor.
