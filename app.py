from __future__ import annotations

import argparse
from collections import defaultdict

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from radar.classifier import load_topics
from radar.config import (
    DB_PATH,
    DEBUG,
    DEFAULT_VIEW_DAYS,
    ENRICHMENT_ENABLED,
    HOST,
    LOOKBACK_DAYS,
    PORT,
    PUBLISHER_HTML_ENABLED,
    SECRET_KEY,
    TOPICS_PATH,
)
from radar.db import Repository
from radar.pipeline import enrich_one_article, import_doi, update_literature

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
repo = Repository(DB_PATH)

PERIOD_OPTIONS = [
    (1, "Hoje"),
    (3, "Últimos 3 dias"),
    (5, "Últimos 5 dias"),
    (7, "Últimos 7 dias"),
    (15, "Últimos 15 dias"),
    (30, "Últimos 30 dias"),
    (60, "Últimos 60 dias"),
    (90, "Últimos 90 dias"),
    (None, "Todo o período"),
]

SOURCE_OPTIONS = [
    ("", "Todas as fontes"),
    ("PubMed", "PubMed"),
    ("Crossref", "Crossref"),
    ("Europe PMC", "Europe PMC"),
]

MS_SCOPE_OPTIONS = [
    ("eligible", "EM: alta + moderada"),
    ("high", "EM: alta especificidade"),
    ("moderate", "EM: moderada"),
    ("pending", "Pendentes de evidência"),
    ("manual", "Importados manualmente"),
    ("audit", "Auditoria: todos no banco"),
]
MS_SCOPE_VALUES = {value for value, _ in MS_SCOPE_OPTIONS}


def _parse_days(value: str | None) -> tuple[int | None, str]:
    raw = (value or str(DEFAULT_VIEW_DAYS)).strip().lower()
    if raw == "all":
        return None, "all"
    try:
        days = int(raw)
    except (TypeError, ValueError):
        days = DEFAULT_VIEW_DAYS
    days = max(1, min(days, 3650))
    return days, str(days)


def _period_label(selected_days: int | None) -> str:
    if selected_days is None:
        return "Todo o período"
    for value, label in PERIOD_OPTIONS:
        if value == selected_days:
            return label
    return f"Últimos {selected_days} dias"


def _sources_from_payload(value) -> set[str] | None:
    if not value:
        return None
    if isinstance(value, str):
        raw = [x.strip().lower() for x in value.split(",")]
    else:
        raw = [str(x).strip().lower() for x in value]
    aliases = {
        "pubmed": "pubmed",
        "crossref": "crossref",
        "europepmc": "europe_pmc",
        "europe_pmc": "europe_pmc",
        "europe pmc": "europe_pmc",
    }
    selected = {aliases[x] for x in raw if x in aliases}
    return selected or None


@app.get("/")
def index():
    topic = request.args.get("topic", "").strip()
    search = request.args.get("q", "").strip()
    source = request.args.get("source", "").strip()
    ms_scope = request.args.get("ms", "eligible").strip().lower()
    favorites_only = request.args.get("favorites") == "1"
    unread_only = request.args.get("unread") == "1"
    open_access_only = request.args.get("open_access") == "1"
    enriched_only = request.args.get("enriched") == "1"
    selected_days, days_arg = _parse_days(request.args.get("days"))

    topics = load_topics(TOPICS_PATH)
    topic_by_id = {item["id"]: item for item in topics}
    if topic and topic not in topic_by_id and topic != "general":
        topic = ""
    if source not in {"", "PubMed", "Crossref", "Europe PMC"}:
        source = ""
    if ms_scope not in MS_SCOPE_VALUES:
        ms_scope = "eligible"

    articles = repo.list_articles(
        topic=topic,
        search=search,
        source=source,
        favorites_only=favorites_only,
        unread_only=unread_only,
        open_access_only=open_access_only,
        enriched_only=enriched_only,
        ms_scope=ms_scope,
        days=selected_days,
    )
    stats = repo.stats(days=selected_days, ms_scope=ms_scope)

    grouped = defaultdict(list)
    for article in articles:
        grouped[article["primary_topic"]].append(article)

    ordered_groups = []
    for topic_item in topics:
        topic_id = topic_item["id"]
        if grouped.get(topic_id):
            ordered_groups.append((topic_item, grouped[topic_id]))
    if grouped.get("general"):
        ordered_groups.append(
            ({"id": "general", "label": "Geral / multidisciplinar", "icon": "📚"}, grouped["general"])
        )

    update_days = selected_days if selected_days is not None else LOOKBACK_DAYS

    return render_template(
        "index.html",
        topics=topics,
        topic_by_id=topic_by_id,
        groups=ordered_groups,
        stats=stats,
        visible_count=len(articles),
        selected_topic=topic,
        selected_source=source,
        source_options=SOURCE_OPTIONS,
        selected_ms_scope=ms_scope,
        ms_scope_options=MS_SCOPE_OPTIONS,
        search=search,
        favorites_only=favorites_only,
        unread_only=unread_only,
        open_access_only=open_access_only,
        enriched_only=enriched_only,
        selected_days=selected_days,
        selected_days_arg=days_arg,
        period_label=_period_label(selected_days),
        period_options=PERIOD_OPTIONS,
        update_days=update_days,
        lookback_days=LOOKBACK_DAYS,
        enrichment_enabled=ENRICHMENT_ENABLED,
        publisher_html_enabled=PUBLISHER_HTML_ENABLED,
    )


@app.get("/article/<article_id>")
def article_detail(article_id: str):
    article = repo.get_article(article_id)
    if not article:
        abort(404)

    topics = load_topics(TOPICS_PATH)
    topic_by_id = {item["id"]: item for item in topics}
    topic = topic_by_id.get(
        article["primary_topic"],
        {"id": "general", "label": "Geral / multidisciplinar", "icon": "📚"},
    )
    return render_template(
        "article.html",
        article=article,
        topic=topic,
        publisher_html_enabled=PUBLISHER_HTML_ENABLED,
    )


@app.post("/api/update")
def api_update():
    payload = request.get_json(silent=True) or {}
    try:
        days = int(payload.get("days", LOOKBACK_DAYS))
    except (TypeError, ValueError):
        days = LOOKBACK_DAYS
    days = max(1, min(days, 365))

    enrich = payload.get("enrich")
    publisher_html = payload.get("publisher_html")
    sources = _sources_from_payload(payload.get("sources"))

    try:
        result = update_literature(
            days,
            enrich=ENRICHMENT_ENABLED if enrich is None else bool(enrich),
            publisher_html=PUBLISHER_HTML_ENABLED if publisher_html is None else bool(publisher_html),
            sources=sources,
        )
        return jsonify(result)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/import-doi")
def import_doi_api():
    payload = request.get_json(silent=True) or {}
    doi = str(payload.get("doi", "")).strip()
    publisher_html = bool(payload.get("publisher_html", False))
    if not doi:
        return jsonify({"ok": False, "error": "Informe um DOI"}), 400
    try:
        return jsonify(import_doi(doi, publisher_html=publisher_html))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/articles/<article_id>/enrich")
def enrich_article_api(article_id: str):
    payload = request.get_json(silent=True) or {}
    publisher_html = bool(payload.get("publisher_html", False))
    try:
        result = enrich_one_article(article_id, publisher_html=publisher_html)
    except KeyError:
        return jsonify({"ok": False, "error": "Artigo não encontrado"}), 404
    return jsonify(result)


@app.post("/api/articles/<article_id>/favorite")
def favorite(article_id: str):
    try:
        value = repo.toggle_flag(article_id, "is_favorite")
    except KeyError:
        return jsonify({"ok": False, "error": "Artigo não encontrado"}), 404
    return jsonify({"ok": True, "value": value})


@app.post("/api/articles/<article_id>/read")
def read(article_id: str):
    try:
        value = repo.toggle_flag(article_id, "is_read")
    except KeyError:
        return jsonify({"ok": False, "error": "Artigo não encontrado"}), 404
    return jsonify({"ok": True, "value": value})


@app.get("/reset-filters")
def reset_filters():
    return redirect(url_for("index", days=DEFAULT_VIEW_DAYS, ms="eligible"))


def main():
    parser = argparse.ArgumentParser(description="Radar de literatura científica em esclerose múltipla")
    parser.add_argument("--update", action="store_true", help="Atualiza a base e encerra.")
    parser.add_argument("--days", type=int, default=LOOKBACK_DAYS, help="Janela em dias usada na atualização.")
    parser.add_argument(
        "--sources",
        default="pubmed,crossref,europe_pmc",
        help="Fontes de descoberta separadas por vírgula: pubmed,crossref,europe_pmc",
    )
    parser.add_argument(
        "--add-doi",
        default="",
        help="Importa diretamente um DOI via Crossref/Europe PMC e encerra.",
    )
    parser.add_argument(
        "--reassess-ms",
        action="store_true",
        help="Reavalia a especificidade para esclerose múltipla de todos os registros do banco.",
    )

    enrichment_group = parser.add_mutually_exclusive_group()
    enrichment_group.add_argument("--enrich", dest="enrich", action="store_true", help="Ativa enriquecimento estruturado.")
    enrichment_group.add_argument("--no-enrich", dest="enrich", action="store_false", help="Desativa enriquecimento.")
    parser.set_defaults(enrich=None)

    parser.add_argument(
        "--publisher-html",
        action="store_true",
        help="Ativa HTML público via BeautifulSoup; respeita robots.txt e não contorna paywalls.",
    )
    args = parser.parse_args()

    if args.reassess_ms:
        print(repo.reassess_ms_eligibility())
        return

    if args.add_doi:
        print(import_doi(args.add_doi, publisher_html=args.publisher_html))
        return

    if args.update:
        days = max(1, min(args.days, 365))
        result = update_literature(
            days,
            enrich=ENRICHMENT_ENABLED if args.enrich is None else args.enrich,
            publisher_html=args.publisher_html or PUBLISHER_HTML_ENABLED,
            sources=_sources_from_payload(args.sources),
        )
        print(result)
        return

    app.run(host=HOST, port=PORT, debug=DEBUG)


if __name__ == "__main__":
    main()
