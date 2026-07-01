# IBRVN Archive API and Pipelines Split Plan

## Goal

Separate the web API runtime from the data pipeline runtime while preserving the
current business model:

- the API reads only curated gold data
- pipeline jobs own external ingestion and enrichment
- `preaching_date` remains the canonical business key for a sermon

This migration starts with runtime and orchestration boundaries first. It does
not change the current gold table semantics in phase 1.

## Business Key Decision

For this project, there is only one sermon per Sunday, so `preaching_date`
remains the canonical identifier of a sermon.

If a surrogate `sermon_id` is introduced later, it must stay in a 1:1
relationship with `preaching_date`. In other words:

- `preaching_date` remains the business key
- `sermon_id` would only be a technical key for joins, lineage, or future
  schema evolution

Phase 1 does not introduce `sermon_id`.

## Target Runtime Architecture

```text
ibrvn-archive/
  api/
  pipe/
  shared/
  docs/
```

Runtime responsibilities:

- `ibrvn-archive-api`
  - serves FastAPI pages and JSON
  - reads only gold data
  - does not need `YOUTUBE_API_KEY`

- `ibrvn-archive-pipelines`
  - runs ingestion and transformation jobs
  - owns `YOUTUBE_API_KEY`
  - writes bronze, silver, and gold outputs

## Airflow Direction

### Transitional phase

Keep the current orchestration style, but switch Airflow from executing inside
the API container to executing inside the dedicated pipeline container.

This is the lowest-risk split because it avoids rewriting the DAG logic and
keeps the existing job modules unchanged.

### Target phase

Move from `docker exec` in a long-lived container to container-per-task
execution. That can be implemented later with a Docker-based operator or an
equivalent helper so each task:

1. starts an isolated container
2. runs one pipeline command
3. writes logs and artifacts
4. exits

## Pipeline Layering Direction

The intended flow remains medallion-based:

1. `raw/source -> bronze`
2. `bronze -> silver`
3. `silver -> gold`

The main change is that silver will become the integration layer for multiple
kinds of processing, not only source normalization.

Examples of future silver outputs:

- source metadata normalized from YouTube
- WordPress historical metadata normalized
- audio duration measurements
- transcript artifacts
- AI-generated summaries
- processing lineage and quality metrics

The gold layer should stay small and API-oriented: one curated read model for
search and browsing.

## Phased Rollout

### Phase 1: runtime split

- create separate API and pipeline images
- remove `YOUTUBE_API_KEY` from the API container
- add a dedicated `ibrvn-archive-pipelines` container
- point Airflow to the pipeline container

### Phase 2: orchestration cleanup

- move from long-lived pipeline container to ephemeral task containers
- split larger jobs into smaller DAG tasks
- trigger `silver -> gold` after any silver-producing flow

### Phase 3: silver expansion

- add silver datasets/tables for audio, transcripts, summaries, and metrics
- keep `preaching_date` as the sermon business key across all silver outputs

### Phase 4: optional technical key

If needed, introduce a surrogate `sermon_id` with a strict 1:1 mapping to
`preaching_date`, without changing the business definition of a sermon.

## Initial File Changes in This Migration

This first migration step should include:

- separate Dockerfiles inside `api/` and `pipe/`
- separate dependency files inside `api/` and `pipe/`
- compose changes to run both containers
- Airflow environment and helper changes to target pipelines
- documentation updates
