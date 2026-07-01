# IBRVN Sermon Platform

A data engineering project that builds a searchable sermon archive from
multiple sources (WordPress site and YouTube), processes the data through a
**Medallion Data Architecture**, and serves it through a **FastAPI web
application**.

The system powers the **IBRVN Archive**, a minimal and searchable sermon
repository for the Igreja Batista Reformada Vida Nova.

This project demonstrates how a **small-scale data platform can be
implemented locally**, using modern data engineering patterns typically
seen in cloud environments such as **Databricks, Azure Data Lake and
Lakehouse architectures**.

Since it is developed to run in a **Raspberry Pi 3 B+ (1GB RAM)**, all Data Lake and API components 
have to be **high performance**.

The Web Interface is running for testing here (HTTP only): [raspi.servehttp.com:8000](http://raspi.servehttp.com:8000)

------------------------------------------------------------------------

# Table of Contents

- [Project Goals](#project-goals)
- [High Level Architecture](#high-level-architecture)
- [Data Lake Structure](#data-lake-structure)
- [Pipeline Architecture](#pipeline-architecture)
- [Data Sources](#data-sources)
- [Data Modeling](#data-modeling)
- [API Architecture](#api-architecture)
- [Web Interface](#web-interface)
- [Job Orchestration](#job-orchestration)
- [Scheduling](#scheduling)
- [Technology Decisions](#technology-decisions)
- [Project Structure](#project-structure)
- [Running the Platform](#running-the-platform)
- [Future Improvements](#future-improvements)

------------------------------------------------------------------------

# Project Goals

This project was built to demonstrate practical knowledge of:

-   Data ingestion pipelines
-   Medallion Data Architecture
-   Data normalization and modeling
-   API-driven data serving
-   Job orchestration
-   Local infrastructure management
-   End-to-end data platform design

All implemented with **open-source tools running on a Raspberry Pi Linux
server**.

------------------------------------------------------------------------

# High Level Architecture

The platform ingests sermon data from two independent sources:

-   WordPress (static historical archive with MP3 files)
-   YouTube (modern livestream sermons)

These sources are processed through a **multi-layer data pipeline** using **Medallion Data Architecture** and
exposed through an API.

``` mermaid
flowchart LR

A[WordPress XML Export] --> B(Bronze - XML)
C[YouTube Data API] --> B(Bronze - JSON)

B --> D(Silver - CSV)

E --> W[(Gold - PostgreSQL Database)]

W --> F[FastAPI Backend]

F --> G[IBRVN Archive Web Interface]
```

------------------------------------------------------------------------

# Data Lake Structure

The project uses a **local data lake structure** similar to what would
exist in a cloud lakehouse.

    data
    │
    ├─ bronze
    │  ├─ youtube_videos.json
    │  └─ wordpress_export.xml
    │
    ├─ silver
    │  ├─ youtube_sermons.csv
    │  └─ wordpress_sermons.csv
    │
    └─ gold
       └─ archive.db

## Why this structure?

Separating raw, cleaned, and curated data makes pipelines:

-   deterministic
-   auditable
-   easy to rebuild

The raw source data is preserved in the Bronze layer so the pipeline can
be replayed if needed.

In the homelab deployment, the curated Gold layer now lives in PostgreSQL.
The legacy `archive.db` file may still be kept on disk for backfill and
rollback safety.

------------------------------------------------------------------------

# Pipeline Architecture

Each pipeline stage is implemented as modular Python scripts.

    pipelines
    │
    ├─ bronze
    │   ├─ youtube_source_to_bronze.py
    │   └─ wordpress_historic_source_to_bronze.py
    │
    ├─ silver
    │   ├─ youtube_bronze_to_silver.py
    │   └─ wordpress_historic_bronze_to_silver.py
    │
    └─ gold
        ├─ youtube_silver_to_gold.py
        ├─ wordpress_historic_silver_to_gold.py
        └─ optimize_gold.py

## Pipeline Execution Flow

``` mermaid
flowchart TD

A[External Sources]

A --> B[source_to_bronze]

B --> C[bronze_to_silver]

C --> D[silver_to_gold]

D --> E[(optimize_gold)]
```

------------------------------------------------------------------------

# Data Sources

## WordPress

Historical sermons were originally published on the church website until 2021.

This source is treated in this project as a **static historical archive**.
It is not expected to receive ongoing updates, so the WordPress pipeline is
kept mainly for occasional historical reprocessing rather than continuous
ingestion.

Almost all posts contain:

-   sermon title
-   preacher
-   Bible reference
-   sermon series
-   MP3 audio file

These posts are extracted from a **WordPress XML export** manually and put into the bronze folder.

## YouTube

Since 2020 sermons are livestreamed and stored on YouTube.

The pipeline retrieves:

-   video metadata
-   livestream start times
-   sermon descriptions
-   playlist membership
-   view statistics

using the **YouTube Data API v3**.

------------------------------------------------------------------------

# Data Modeling

The **Gold layer** contains a single unified sermon table.

This table merges information from both sources.

  Field            Description
  ---------------- --------------------------
  preaching_date   canonical sermon date
  preacher_name    normalized preacher name
  title            sermon title
  text_reference   Bible passage
  serie            sermon series
  youtube_link     YouTube video
  wordpress_link   WordPress page
  media_link       MP3 audio file

This model allows a sermon to contain **multiple source references
simultaneously**.

------------------------------------------------------------------------

# API Architecture

The platform exposes the Gold dataset through a **FastAPI backend**.

Reasons for choosing FastAPI:

-   high performance
-   asynchronous support
-   minimal boilerplate
-   easy integration with Python pipelines

## API Structure

    api
    │
    ├─ main.py
    ├─ queries.py
    │
    ├─ templates
    │   ├─ base.html
    │   ├─ ...
    │   └─ sermons.html
    │
    └─ static
       └─ style.css


## API Flow

``` mermaid
flowchart LR

User --> Browser

Browser --> FastAPI

FastAPI --> PostgreSQL

PostgreSQL --> FastAPI

FastAPI --> HTML Templates

HTML Templates --> Browser
```

------------------------------------------------------------------------

# Web Interface

The **IBRVN Archive** provides a minimal searchable interface.

Users can search sermons by:

-   Bible text
-   preacher
-   series
-   sermon title
-   keywords

Search results update **in real time without page reloads**.

------------------------------------------------------------------------

# Job Orchestration

Pipeline execution is handled through **job scripts**.

    jobs
    │
    ├─ youtube_job.py
    └─ wordpress_job.py

Jobs execute pipeline stages sequentially.

------------------------------------------------------------------------

# Scheduling

Jobs are scheduled using **cron**.

In practice, continuous scheduled ingestion is focused on the YouTube
pipeline. The WordPress source is historical and can be reprocessed on demand
when needed.

Example schedule:

  Job                        Schedule
  -------------------------- -----------------
  YouTube weekly ingestion   Monday 22:00
  API restart                daily
  database optimization      after pipelines

Cron was chosen instead of heavier orchestrators such as Airflow
because:

-   infrastructure is minimal
-   pipeline complexity is low
-   operational overhead is near zero

------------------------------------------------------------------------

# Technology Decisions

## Python

Chosen due to its strong ecosystem for:

-   data processing
-   scripting
-   API integration

## PostgreSQL in Homelab

In the homelab deployment, PostgreSQL powers the Gold layer.

Reasons for this choice:

-   central shared database for multiple services
-   better fit for containerized infrastructure
-   easier future integration with Airflow and other apps
-   safer growth path than keeping the production gold layer in a local file

## FastAPI

FastAPI was selected because:

-   it provides high performance
-   supports async operations
-   integrates naturally with Python pipelines

## Raspberry Pi Infrastructure

The platform runs on a **self-hosted Raspberry Pi Linux server**.

This demonstrates that a **complete data platform can run on minimal
hardware**.

Advantages:

-   low cost
-   low power consumption
-   full infrastructure control

------------------------------------------------------------------------

# Running the Platform

Start the API:

    make api

Run pipelines manually:

    make job-youtube-weekly
    make job-youtube-historic
    make job-wordpress-historic

Backfill the legacy SQLite gold into PostgreSQL:

    make migrate-gold-postgres

------------------------------------------------------------------------

# Future Improvements

Potential future extensions include:

-   full-text search indexing
-   sermon transcription search
-   topic classification
-   analytics dashboards
-   recommendation systems

------------------------------------------------------------------------

# Author

Samuel Noll\
Data Engineer \| Software Developer

------------------------------------------------------------------------

# Homelab Migration

For the move from the Raspberry-style setup to the Ubuntu mini PC, use the
Docker-based intermediate step documented here:

- `docs/homelab-migration.md`

The homelab version now supports PostgreSQL as the gold storage backend while
keeping the legacy SQLite file available for one-time backfill and fast
rollback.
