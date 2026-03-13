from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from .queries import *

app = FastAPI()

templates = Jinja2Templates(directory="api/templates")

app.mount("/static", StaticFiles(directory="api/static"), name="static")


@app.get("/")
def home(request: Request):

    sermons = get_recent_sermons()
    stats = get_home_stats()

    return templates.TemplateResponse(
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

    return templates.TemplateResponse(
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

    return templates.TemplateResponse(
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

    return templates.TemplateResponse(
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

    return templates.TemplateResponse(
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

    return templates.TemplateResponse(
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

    return templates.TemplateResponse(
        "preachers.html",
        {
            "request": request,
            "preachers": rows,
            "last_update": get_last_update()
        }
    )


@app.get("/preachers/{preacher}")
def preacher(request: Request, preacher: str):

    sermons = sermons_by_preacher(preacher)

    return templates.TemplateResponse(
        "sermons.html",
        {
            "request": request,
            "sermons": sermons,
            "title": preacher,
            "last_update": get_last_update()
        }
    )


@app.get("/stats")
def stats(request: Request):

    s = get_stats()

    return templates.TemplateResponse(
        "stats.html",
        {
            "request": request,
            "stats": s,
            "last_update": get_last_update()
        }
    )


@app.get("/timeline")
def tl(request: Request):

    rows = timeline()

    return templates.TemplateResponse(
        "timeline.html",
        {
            "request": request,
            "timeline": rows,
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