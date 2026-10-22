import csv
import io
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from .db import initialize_database
from .queries import *
from .study_queries import (
    get_study_catalog,
    get_study_detail,
    get_study_home_stats,
    get_study_resource_transcript,
    get_study_type_composition,
)
from .quality_queries import get_quality_dashboard, get_quality_issues, get_quality_run
from shared.settings import AUDIO_RAW_DIR, STUDY_RESOURCE_RAW_DIR

app = FastAPI()

templates = Jinja2Templates(directory="api/templates")

AUDIO_RAW_DIR.mkdir(parents=True, exist_ok=True)
STUDY_RESOURCE_RAW_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory="api/static"), name="static")
app.mount("/media", StaticFiles(directory=str(AUDIO_RAW_DIR)), name="media")
app.mount(
    "/study-media",
    StaticFiles(directory=str(STUDY_RESOURCE_RAW_DIR)),
    name="study-media",
)


@app.on_event("startup")
def startup():

    initialize_database()


def render_template(request: Request, template_name: str, context: dict):

    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=context
    )


@app.get("/")
def home(request: Request):

    stats = get_home_stats()
    study_stats = get_study_home_stats()
    sermon_composition = get_sermon_testament_composition()
    study_composition = get_study_type_composition()

    return render_template(
        request,
        "home.html",
        {
            "request": request,
            "stats": stats,
            "study_stats": study_stats,
            "sermon_composition": sermon_composition,
            "study_composition": study_composition,
            "last_update": get_last_update()
        }
    )


@app.get("/sermons")
def sermons(request: Request):

    return render_template(
        request,
        "sermon_index.html",
        {
            "request": request,
            "sermons": get_recent_sermons(),
            "last_update": get_last_update(),
        },
    )


@app.get("/search")
def search(request: Request, q: str):

    sermons = search_sermons(q)

    return render_template(
        request,
        "sermons.html",
        {
            "request": request,
            "sermons": sermons,
            "title": f"Busca: {q}",
            "last_update": get_last_update()
        }
    )


@app.get("/books")
def books(request: Request):

    rows = get_books()

    return render_template(
        request,
        "books.html",
        {
            "request": request,
            "books": rows,
            "last_update": get_last_update()
        }
    )


@app.get("/books/{book}")
def book(request: Request, book: str):

    sermons = sermons_by_book(book)

    return render_template(
        request,
        "sermons.html",
        {
            "request": request,
            "sermons": sermons,
            "title": book,
            "last_update": get_last_update()
        }
    )


@app.get("/series")
def series(request: Request):

    rows = get_series()

    return render_template(
        request,
        "series.html",
        {
            "request": request,
            "series": rows,
            "last_update": get_last_update()
        }
    )


@app.get("/series/{serie}")
def serie(request: Request, serie: str):

    sermons = sermons_by_series(serie)

    return render_template(
        request,
        "sermons.html",
        {
            "request": request,
            "sermons": sermons,
            "title": serie,
            "last_update": get_last_update()
        }
    )


@app.get("/series/{serie}/preachers/{preacher}")
def serie_by_preacher(request: Request, serie: str, preacher: str):

    sermons = sermons_by_series_and_preacher(serie, preacher)

    return render_template(
        request,
        "sermons.html",
        {
            "request": request,
            "sermons": sermons,
            "title": f"{serie} ({preacher})",
            "last_update": get_last_update()
        }
    )


@app.get("/preachers")
def preachers(request: Request):

    rows = get_preachers()

    return render_template(
        request,
        "preachers.html",
        {
            "request": request,
            "preachers": rows,
            "last_update": get_last_update()
        }
    )


@app.get("/years")
def years(request: Request):

    rows = get_years()

    return render_template(
        request,
        "years.html",
        {
            "request": request,
            "years": rows,
            "last_update": get_last_update()
        }
    )


@app.get("/preachers/{preacher}")
def preacher(request: Request, preacher: str):

    sermons = sermons_by_preacher(preacher)

    return render_template(
        request,
        "sermons.html",
        {
            "request": request,
            "sermons": sermons,
            "title": preacher,
            "last_update": get_last_update()
        }
    )


@app.get("/years/{year}")
def year(request: Request, year: str):

    sermons = sermons_by_year(year)

    return render_template(
        request,
        "sermons.html",
        {
            "request": request,
            "sermons": sermons,
            "title": year,
            "last_update": get_last_update()
        }
    )


@app.get("/transcripts/{canonical_sermon_id}")
def transcript(request: Request, canonical_sermon_id: str):

    row = get_transcript(canonical_sermon_id)

    if not row:
        raise HTTPException(status_code=404, detail="Transcript not found")

    return render_template(
        request,
        "transcript.html",
        {
            "request": request,
            "transcript": row,
            "last_update": get_last_update()
        }
    )


@app.get("/studies")
def studies(request: Request):

    return render_template(
        request,
        "studies.html",
        {
            "request": request,
            "catalog": get_study_catalog(),
            "last_update": get_last_update(),
        },
    )


@app.get("/study-transcripts/{resource_id}")
def study_resource_transcript(request: Request, resource_id: str):

    transcript = get_study_resource_transcript(resource_id)

    if not transcript:
        raise HTTPException(status_code=404, detail="Study transcript not found")

    return render_template(
        request,
        "study_resource_transcript.html",
        {
            "request": request,
            "transcript": transcript,
            "last_update": get_last_update(),
        },
    )


@app.get("/studies/{study_id}")
def study_detail(request: Request, study_id: str):

    study = get_study_detail(study_id)

    if not study:
        raise HTTPException(status_code=404, detail="Study not found")

    return render_template(
        request,
        "study_detail.html",
        {
            "request": request,
            "study": study,
            "last_update": get_last_update(),
        },
    )



@app.get("/api/search")
def api_search(q: str):

    sermons = search_sermons(q)

    return [
        dict(s)
        for s in sermons[:20]
    ]


@app.get("/quality")
def quality_dashboard(
    request: Request,
    run_id: str = "",
    metric: str = "",
    year: str = "",
    source: str = "",
    preacher: str = "",
):
    dashboard = get_quality_dashboard(run_id, metric, year, source, preacher)
    return render_template(
        request,
        "quality.html",
        {
            "request": request,
            **dashboard,
            "selected_year": year,
            "selected_source": source,
            "selected_preacher": preacher,
            "last_update": get_last_update(),
        },
    )


@app.get("/quality/export.csv")
def quality_export_csv(
    run_id: str = "",
    metric: str = "",
    year: str = "",
    source: str = "",
    preacher: str = "",
):
    selected_run = get_quality_run(run_id)
    if not selected_run or not metric:
        raise HTTPException(status_code=404, detail="Quality snapshot not found")
    rows = get_quality_issues(
        selected_run["run_id"], metric, year, source, preacher,
    )
    output = io.StringIO()
    writer = csv.writer(output)
    def csv_cell(value):
        value = str(value or "")
        return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value

    writer.writerow([
        "data", "tipo", "id", "titulo", "pregador", "origem", "detalhe", "link",
    ])
    for row in rows:
        writer.writerow([
            csv_cell(row.get("preaching_date")), csv_cell(row.get("entity_type")),
            csv_cell(row.get("entity_id")), csv_cell(row.get("title")),
            csv_cell(row.get("preacher_name")), csv_cell(row.get("source_system")),
            csv_cell(row.get("detail")), csv_cell(row.get("link")),
        ])
    safe_metric = re.sub(r"[^a-z0-9_-]", "_", metric.lower())
    headers = {
        "Content-Disposition": f'attachment; filename="qualidade-{safe_metric}.csv"',
    }
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8", headers=headers,
    )
