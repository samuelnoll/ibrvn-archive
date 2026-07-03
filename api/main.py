from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from .db import initialize_database
from .queries import *
from shared.settings import AUDIO_RAW_DIR

app = FastAPI()

templates = Jinja2Templates(directory="api/templates")

AUDIO_RAW_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory="api/static"), name="static")
app.mount("/media", StaticFiles(directory=str(AUDIO_RAW_DIR)), name="media")


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

    sermons = get_recent_sermons()
    stats = get_home_stats()

    return render_template(
        request,
        "home.html",
        {
            "request": request,
            "sermons": sermons,
            "stats": stats,
            "last_update": get_last_update()
        }
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



@app.get("/api/search")
def api_search(q: str):

    sermons = search_sermons(q)

    return [
        dict(s)
        for s in sermons[:20]
    ]
