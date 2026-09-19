from __future__ import annotations

from dataclasses import dataclass, field

from .classifier import classify, load_topics
from .config import (
    BASE_QUERY,
    CROSSREF_DISCOVERY_ENABLED,
    CROSSREF_RETMAX,
    DB_PATH,
    ENRICHMENT_ENABLED,
    ENRICHMENT_MAX_ARTICLES,
    EUROPE_PMC_DISCOVERY_ENABLED,
    EUROPE_PMC_RETMAX,
    LOOKBACK_DAYS,
    MS_ELIGIBILITY_ENABLED,
    MS_HIGH_THRESHOLD,
    MS_MODERATE_THRESHOLD,
    MS_STORE_PENDING,
    PUBMED_DISCOVERY_ENABLED,
    PUBMED_RETMAX,
    PUBLISHER_HTML_ENABLED,
    TOPICS_PATH,
)
from .crossref import CrossrefClient
from .db import Repository
from .eligibility import apply_ms_eligibility
from .enrichment import MetadataEnricher
from .europe_pmc import EuropePMCClient
from .merge import deduplicate_articles, merge_articles
from .models import Article, normalize_doi
from .pubmed import PubMedClient


@dataclass(slots=True)
class DiscoveryResult:
    articles: list[Article] = field(default_factory=list)
    counts: dict[str, int] = field(
        default_factory=lambda: {"PubMed": 0, "Crossref": 0, "Europe PMC": 0}
    )
    errors: list[str] = field(default_factory=list)
    successful_sources: list[str] = field(default_factory=list)


def discover_literature(days: int, *, sources: set[str] | None = None) -> DiscoveryResult:
    selected = sources or {"pubmed", "crossref", "europe_pmc"}
    result = DiscoveryResult()

    if PUBMED_DISCOVERY_ENABLED and "pubmed" in selected:
        try:
            items = PubMedClient().search_and_fetch(days=days, retmax=PUBMED_RETMAX)
            for item in items:
                item.ensure_identity()
            result.articles.extend(items)
            result.counts["PubMed"] = len(items)
            result.successful_sources.append("PubMed")
        except Exception as exc:
            result.errors.append(f"PubMed: {exc}")

    if CROSSREF_DISCOVERY_ENABLED and "crossref" in selected:
        try:
            items = CrossrefClient().search_recent(days=days, retmax=CROSSREF_RETMAX)
            result.articles.extend(items)
            result.counts["Crossref"] = len(items)
            result.successful_sources.append("Crossref")
        except Exception as exc:
            result.errors.append(f"Crossref: {exc}")

    if EUROPE_PMC_DISCOVERY_ENABLED and "europe_pmc" in selected:
        try:
            items = EuropePMCClient().search_recent(days=days, retmax=EUROPE_PMC_RETMAX)
            result.articles.extend(items)
            result.counts["Europe PMC"] = len(items)
            result.successful_sources.append("Europe PMC")
        except Exception as exc:
            result.errors.append(f"Europe PMC: {exc}")

    if not result.successful_sources:
        raise RuntimeError(
            "Nenhuma fonte bibliográfica pôde ser consultada. " + " | ".join(result.errors)
        )

    result.articles = deduplicate_articles(result.articles)
    return result


def update_literature(
    days: int = LOOKBACK_DAYS,
    *,
    enrich: bool | None = None,
    publisher_html: bool | None = None,
    sources: set[str] | None = None,
) -> dict:
    repo = Repository(DB_PATH)
    run_id = repo.start_run(BASE_QUERY, days)

    use_enrichment = ENRICHMENT_ENABLED if enrich is None else bool(enrich)
    use_publisher_html = PUBLISHER_HTML_ENABLED if publisher_html is None else bool(publisher_html)
    use_publisher_html = use_publisher_html and use_enrichment

    try:
        discovery = discover_literature(days, sources=sources)
        articles = discovery.articles

        # Avaliação preliminar: serve também para priorizar candidatos com poucos
        # metadados (especialmente Crossref recém-depositado) no enriquecimento.
        if MS_ELIGIBILITY_ENABLED:
            for article in articles:
                apply_ms_eligibility(
                    article,
                    high_threshold=MS_HIGH_THRESHOLD,
                    moderate_threshold=MS_MODERATE_THRESHOLD,
                )

        enriched_count = 0
        enrichment_failures = 0
        publisher_html_count = 0

        if use_enrichment and ENRICHMENT_MAX_ARTICLES > 0:
            enricher = MetadataEnricher(publisher_html=use_publisher_html)

            status_rank = {
                "pending": 0,
                "moderate": 1,
                "high": 2,
                "unknown": 2,
                "excluded": 3,
                "manual": 3,
            }
            candidates = sorted(
                articles,
                key=lambda a: (
                    status_rank.get(a.ms_eligibility, 2),
                    bool(a.abstract),
                    len(set(a.discovery_sources) & {"PubMed", "Crossref", "Europe PMC"}),
                ),
            )[:ENRICHMENT_MAX_ARTICLES]

            for article in candidates:
                outcome = enricher.enrich(article)
                if outcome.enriched:
                    enriched_count += 1
                if outcome.errors:
                    enrichment_failures += 1
                if "Publisher HTML" in (outcome.sources or []):
                    publisher_html_count += 1

        topics = load_topics(TOPICS_PATH)
        status_counts = {"high": 0, "moderate": 0, "pending": 0, "excluded": 0, "manual": 0}

        for article in articles:
            if MS_ELIGIBILITY_ENABLED:
                apply_ms_eligibility(
                    article,
                    high_threshold=MS_HIGH_THRESHOLD,
                    moderate_threshold=MS_MODERATE_THRESHOLD,
                )
            else:
                article.ms_eligibility = "high"
                article.ms_score = 10.0
                article.ms_evidence = ["filtro de elegibilidade desativado"]

            status_counts[article.ms_eligibility] = status_counts.get(article.ms_eligibility, 0) + 1
            classify(article, topics)

        # O feed principal recebe apenas alta/moderada. Pendentes são mantidos no
        # banco (ocultos por padrão) para poderem ganhar abstract/PMID no futuro.
        # Registros excluídos novos não são armazenados; se já existiam, atualizamos
        # o status para que deixem de aparecer no feed padrão.
        to_store: list[Article] = []
        for article in articles:
            if article.ms_eligibility in {"high", "moderate", "manual"}:
                to_store.append(article)
            elif article.ms_eligibility == "pending" and MS_STORE_PENDING:
                to_store.append(article)
            elif article.ms_eligibility == "excluded":
                existing = repo.find_article(pmid=article.pmid, doi=article.doi, pmc_id=article.pmc_id)
                if existing:
                    to_store.append(article)

        inserted, updated = repo.upsert_articles(to_store)
        raw_seen = sum(discovery.counts.values())
        deduplicated_count = max(0, raw_seen - len(articles))

        repo.finish_run(
            run_id,
            status="success",
            articles_seen=len(articles),
            inserted=inserted,
            updated=updated,
            enriched_count=enriched_count,
            enrichment_failures=enrichment_failures,
            publisher_html_count=publisher_html_count,
            pubmed_seen=discovery.counts["PubMed"],
            crossref_seen=discovery.counts["Crossref"],
            europe_pmc_seen=discovery.counts["Europe PMC"],
            deduplicated_count=deduplicated_count,
            ms_high_count=status_counts.get("high", 0),
            ms_moderate_count=status_counts.get("moderate", 0),
            ms_pending_count=status_counts.get("pending", 0),
            ms_excluded_count=status_counts.get("excluded", 0),
            discovery_errors=discovery.errors,
        )

        eligible_count = status_counts.get("high", 0) + status_counts.get("moderate", 0)
        return {
            "ok": True,
            "articles_seen": len(articles),
            "raw_seen": raw_seen,
            "inserted": inserted,
            "updated": updated,
            "deduplicated": deduplicated_count,
            "sources": discovery.counts,
            "source_errors": discovery.errors,
            "enriched": enriched_count,
            "enrichment_failures": enrichment_failures,
            "publisher_html": publisher_html_count,
            "ms_eligible": eligible_count,
            "ms_high": status_counts.get("high", 0),
            "ms_moderate": status_counts.get("moderate", 0),
            "ms_pending": status_counts.get("pending", 0),
            "excluded_not_ms": status_counts.get("excluded", 0),
            "stored": len(to_store),
        }
    except Exception as exc:
        repo.finish_run(run_id, status="error", error=str(exc))
        raise


def enrich_one_article(article_id: str, *, publisher_html: bool = False) -> dict:
    repo = Repository(DB_PATH)
    data = repo.get_article(article_id)
    if not data:
        raise KeyError(article_id)

    article = Article.from_mapping(data)
    previous_status = article.ms_eligibility
    outcome = MetadataEnricher(publisher_html=publisher_html).enrich(article)
    apply_ms_eligibility(
        article,
        high_threshold=MS_HIGH_THRESHOLD,
        moderate_threshold=MS_MODERATE_THRESHOLD,
        manual_override=(previous_status == "manual"),
    )
    classify(article, load_topics(TOPICS_PATH))
    repo.upsert_articles([article])

    refreshed = repo.get_article(article.article_id)
    return {
        "ok": True,
        "enriched": outcome.enriched,
        "sources": outcome.sources,
        "errors": outcome.errors,
        "article": refreshed,
    }


def import_doi(doi: str, *, publisher_html: bool = False) -> dict:
    """Importa um DOI explicitamente solicitado pelo usuário.

    Se os metadados ainda forem insuficientes para provar especificidade para EM,
    o registro é mantido como ``manual``. Isso é intencional: a importação direta
    representa uma decisão explícita do usuário e permite acompanhar um trabalho
    recém-publicado antes de a indexação bibliográfica ficar completa.
    """

    normalized = normalize_doi(doi)
    if not normalized:
        raise ValueError("DOI inválido ou vazio")

    repo = Repository(DB_PATH)
    article = CrossrefClient().lookup_doi(normalized)
    source_errors: list[str] = []

    if article is None:
        try:
            article = EuropePMCClient().lookup_article(doi=normalized)
        except Exception as exc:
            source_errors.append(f"Europe PMC: {exc}")

    if article is None:
        raise ValueError("O DOI não foi localizado no Crossref nem no Europe PMC")

    if "Europe PMC" not in article.discovery_sources:
        try:
            epmc = EuropePMCClient().lookup_article(doi=normalized)
            if epmc:
                merge_articles(article, epmc)
        except Exception as exc:
            source_errors.append(f"Europe PMC: {exc}")

    outcome = MetadataEnricher(publisher_html=publisher_html).enrich(article)
    source_errors.extend(outcome.errors or [])

    apply_ms_eligibility(
        article,
        high_threshold=MS_HIGH_THRESHOLD,
        moderate_threshold=MS_MODERATE_THRESHOLD,
        manual_override=True,
    )
    classify(article, load_topics(TOPICS_PATH))
    inserted, updated = repo.upsert_articles([article])

    saved = repo.find_article(pmid=article.pmid, doi=article.doi, pmc_id=article.pmc_id)
    return {
        "ok": True,
        "inserted": inserted,
        "updated": updated,
        "errors": source_errors,
        "article": saved,
    }
