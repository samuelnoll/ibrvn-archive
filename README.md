# IBRVN Sermon Platform

Searchable sermon archive for Igreja Batista Reformada Vida Nova.

The project ingests historical WordPress data and modern YouTube data, processes
them through a medallion-style pipeline, stores a curated gold dataset in
PostgreSQL, and serves the final archive through a FastAPI web app.

## Current Architecture

The homelab runtime is intentionally split:

- `api/` serves the web interface and reads gold data only
- `pipe/` owns ingestion, transformation, enrichment, and operational jobs
- `shared/` contains the common database and settings modules

`preaching_date` remains the canonical business key for a sermon. If a
technical `sermon_id` is introduced later, it should stay in a 1:1
relationship with `preaching_date`.

## Repository Layout

```text
ibrvn-archive/
  api/
    Dockerfile
    main.py
    db.py
    queries.py
    requirements.txt
    templates/
    static/
  pipe/
    Dockerfile
    requirements.txt
    jobs/
    pipelines/
      bronze/
      silver/
      gold/
    config/
    scripts/
  shared/
    db.py
    settings.py
  docs/
  compose.yaml
  Makefile
```

## Data Flow

```mermaid
flowchart TD
  A["External Sources"] --> B["source to bronze"]
  B --> C["bronze to silver"]
  C --> D["silver to gold"]
  D --> E["FastAPI reads gold"]
```

Current sources:

- WordPress XML export for the historical archive
- YouTube Data API v3 for ongoing sermon ingestion

Current orchestration shape in `homelab-airflow`:

- `ibrvn_sermon_youtube_bronze`
- `ibrvn_sermon_youtube_weekly`
- `ibrvn_sermon_wordpress_historic`
- `ibrvn_sermon_metadata_silver`
- `ibrvn_sermon_audio_enrichment`
- `ibrvn_sermon_gold_refresh`
- `ibrvn_sermon_critique`

## Data Model

The curated gold layer contains one unified sermon row per `preaching_date`.
That row can merge multiple source references at the same time, such as
YouTube, WordPress, and audio links.

Silver is stored in PostgreSQL tables, not CSV files. The current silver model
is centered on:

- `silver_source_items`
- `silver_sermon_metadata`
- `silver_media_assets`
- `silver_transcripts`
- `silver_critique`
- `silver_processing_runs`

Audio enrichment now calls the separate `homelab-ai` runtime for:

- local transcription with `faster-whisper`

The sermon critique flow is separate from that stack and calls the
OpenAI API directly from `ibrvn-archive`, then reports through email and the
WhatsApp scheduler.

Current core fields:

- `preaching_date`
- `preacher_name`
- `title`
- `text_reference`
- `serie`
- `youtube_link`
- `wordpress_link`
- `media_link`
- `download_link`

### Study Archive

Studies use a separate data model and do not write to sermon tables. WordPress
and YouTube remain separate through silver and are merged only in gold.

Study tables:

- `silver_study_wordpress`
- `silver_study_wordpress_resources`
- `silver_study_youtube`
- `silver_study_youtube_resources`
- `silver_study_resource_assets`
- `silver_study_resource_transcripts`
- `silver_study_processing_runs`
- `gold_studies`
- `gold_study_resources`

Like `gold_sermons`, `gold_study_resources` carries the API-facing enrichment
fields directly: local filename/path, download link, local MIME type, duration,
and transcript availability. Detailed assets and transcript text remain in the
separate study silver tables.

WordPress ingestion uses only published pages directly reachable from the
`ctb`, `palestras-conferencias`, and `materiais-de-estudo` public roots. The
pipeline resolves linked YouTube video and playlist titles in batches using
`YOUTUBE_API_KEY`; unavailable or private items retain their identifier. The
YouTube extractor uses only playlists whose normalized title begins with
`Estudo `, `CTB `, `Conferencia `, or `Retiro `. Each qualifying playlist is
one study and its videos are the study resources.

Manual pipeline commands:

```bash
python -m pipe.pipelines.studies.wordpress_bronze_to_silver
python -m pipe.pipelines.studies.youtube_source_to_bronze
python -m pipe.pipelines.studies.youtube_source_to_bronze --loopback-days 30
python -m pipe.pipelines.studies.youtube_bronze_to_silver
python -m pipe.pipelines.studies.silver_to_gold
python -m pipe.pipelines.studies.resource_enrichment.download_resources
python -m pipe.pipelines.studies.resource_enrichment.measure_audio_duration
python -m pipe.pipelines.studies.resource_enrichment.transcribe_audio
python -m pipe.pipelines.studies.resource_enrichment.data_quality
python -m pipe.pipelines.studies.resource_enrichment.silver_to_gold
```

Study orchestration is isolated in these DAGs:

- `ibrvn_study_wordpress_historic`
- `ibrvn_study_youtube_bronze`
- `ibrvn_study_metadata_silver`
- `ibrvn_study_gold_refresh`
- `ibrvn_study_resource_enrichment`

`ibrvn_study_resource_enrichment` accepts optional `loopback_days` and
`skip_transcription` DAG configuration parameters. Files are stored separately
from sermon audio under `ARCHIVE_STUDY_RESOURCE_RAW_DIR`, which defaults to
`/app/data/resource/raw` in the container. Direct audio and documents preserve
their original filename. YouTube videos are converted to MP3 only for studies
that do not already contain a direct audio resource.

## Running

Start the homelab stack:

```bash
docker compose up -d --build
```

For local transcription, start `homelab-ai` separately before
running the audio enrichment pipeline.

Run the API locally:

```bash
make api
```

Run pipeline jobs manually:

```bash
make job-youtube-weekly
make job-youtube-historic
make job-wordpress-historic
```

Utility commands:

```bash
make quality
make export
make migrate-gold-postgres
```

## Airflow

`homelab-airflow` orchestrates the existing pipeline runtime by executing
commands inside the dedicated `ibrvn-archive-pipelines` container.

This is the current transitional model before moving to container-per-task
execution.

## Notes

- The API container does not need `YOUTUBE_API_KEY`.
- The pipeline container owns ingestion credentials and heavier dependencies.
- Bronze stays on disk for source snapshots and raw files.
- Silver and gold are stored in PostgreSQL in the homelab deployment.
- Audio enrichment writes duration and transcript outputs into silver tables.
- Local AI inference for audio enrichment is expected to run in the separate `homelab-ai` stack.
- Sermon critique generation uses the OpenAI API directly.

## Docs

- [docs/homelab-migration.md](/D:/Desenvolvimento/homelab/ibrvn-archive/docs/homelab-migration.md)
- [docs/api-pipelines-split-plan.md](/D:/Desenvolvimento/homelab/ibrvn-archive/docs/api-pipelines-split-plan.md)
