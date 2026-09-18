from __future__ import annotations

import argparse
from collections import defaultdict

from flask import Flask, jsonify, redirect, render_template, request, url_for

from radar.classifier import load_topics
from radar.config import (
    DB_PATH,
    DEBUG,
    DEFAULT_VIEW_DAYS,
    HOST,
    LOOKBACK_DAYS,
    PORT,
    SECRET_KEY,
    TOPICS_PATH,
)
from radar.db import Repository
from radar.pipeline import update_literature


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


def _parse_days(value: str | None) -> tuple[int | None, str]:
    """Converte o parâmetro ?days= em um período seguro para o painel."""
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


@app.get("/")
def index():
    topic = request.args.get("topic", "").strip()
    search = request.args.get("q", "").strip()
    favorites_only = request.args.get("favorites") == "1"
    unread_only = request.args.get("unread") == "1"
    selected_days, days_arg = _parse_days(request.args.get("days"))

    topics = load_topics(TOPICS_PATH)
    topic_by_id = {item["id"]: item for item in topics}

    # Ignora IDs de tópico inválidos em vez de gerar uma tela vazia confusa.
    if topic and topic not in topic_by_id and topic != "general":
        topic = ""

    articles = repo.list_articles(
        topic=topic,
        search=search,
        favorites_only=favorites_only,
        unread_only=unread_only,
        days=selected_days,
    )

    # Estatísticas e contagens de tópicos acompanham o período escolhido,
    # mas não os demais filtros. Assim a navegação continua informativa.
    stats = repo.stats(days=selected_days)

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
            (
                {
                    "id": "general",
                    "label": "Geral / multidisciplinar",
                    "icon": "📚",
                },
                grouped["general"],
            )
        )

    # Ao clicar em Atualizar, a coleta usa o mesmo período exibido.
    # Em "Todo o período", usa a janela padrão de coleta configurada no .env.
    update_days = selected_days if selected_days is not None else LOOKBACK_DAYS

    return render_template(
        "index.html",
        topics=topics,
        topic_by_id=topic_by_id,
        groups=ordered_groups,
        stats=stats,
        visible_count=len(articles),
        selected_topic=topic,
        search=search,
        favorites_only=favorites_only,
        unread_only=unread_only,
        selected_days=selected_days,
        selected_days_arg=days_arg,
        period_label=_period_label(selected_days),
        period_options=PERIOD_OPTIONS,
        update_days=update_days,
        lookback_days=LOOKBACK_DAYS,
    )


@app.post("/api/update")
def api_update():
    payload = request.get_json(silent=True) or {}

    try:
        days = int(payload.get("days", LOOKBACK_DAYS))
    except (TypeError, ValueError):
        days = LOOKBACK_DAYS

    days = max(1, min(days, 365))
    result = update_literature(days)
    return jsonify(result)


@app.post("/api/articles/<pmid>/favorite")
def favorite(pmid: str):
    return jsonify({"ok": True, "value": repo.toggle_flag(pmid, "is_favorite")})


@app.post("/api/articles/<pmid>/read")
def read(pmid: str):
    return jsonify({"ok": True, "value": repo.toggle_flag(pmid, "is_read")})


@app.get("/reset-filters")
def reset_filters():
    return redirect(url_for("index", days=DEFAULT_VIEW_DAYS))


def main():
    parser = argparse.ArgumentParser(
        description="Radar de literatura científica em esclerose múltipla"
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Atualiza a base e encerra, sem abrir o servidor web.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=LOOKBACK_DAYS,
        help="Janela em dias usada com --update.",
    )
    args = parser.parse_args()

    if args.update:
        result = update_literature(max(1, min(args.days, 365)))
        print(result)
        return

    app.run(host=HOST, port=PORT, debug=DEBUG)


if __name__ == "__main__":
    main()
