from radar.crossref import article_from_crossref_item
from radar.europe_pmc import article_from_epmc_result
from radar.merge import deduplicate_articles
from radar.models import Article


def test_crossref_parser():
    item = {
        "DOI": "10.1021/TEST.123",
        "title": ["HLA biology in multiple sclerosis"],
        "abstract": "<jats:p>Multiple sclerosis abstract.</jats:p>",
        "container-title": ["ACS Omega"],
        "published-online": {"date-parts": [[2026, 9, 18]]},
        "publisher": "American Chemical Society (ACS)",
        "type": "journal-article",
        "author": [{"given": "Levy", "family": "Alves", "affiliation": [{"name": "USP"}]}],
        "subject": ["Chemistry"],
        "URL": "https://doi.org/10.1021/test.123",
    }
    article = article_from_crossref_item(item)
    assert article is not None
    assert article.doi == "10.1021/test.123"
    assert article.pub_date == "2026-09-18"
    assert article.abstract == "Multiple sclerosis abstract."
    assert "Crossref" in article.discovery_sources


def test_epmc_parser():
    result = {
        "pmid": "12345678",
        "pmcid": "PMC123",
        "doi": "10.1000/example",
        "title": "Multiple sclerosis immunology",
        "abstractText": "An abstract",
        "firstPublicationDate": "2026-09-18",
        "isOpenAccess": "Y",
        "inEPMC": "Y",
        "authorList": {"author": [{"fullName": "A Author"}]},
        "keywordList": {"keyword": ["multiple sclerosis", "HLA"]},
        "pubTypeList": {"pubType": ["research article"]},
        "journalInfo": {"journal": {"title": "Example Journal"}},
    }
    article = article_from_epmc_result(result)
    assert article is not None
    assert article.pmid == "12345678"
    assert article.open_access_status == "yes"
    assert "Europe PMC" in article.discovery_sources
    assert article.fulltext_available is True


def test_deduplicate_by_doi_and_merge_sources():
    pubmed = Article(
        pmid="123",
        doi="10.1000/ABC",
        title="A sufficiently long multiple sclerosis article title",
        abstract="Short abstract",
        pub_date="2026-09-18",
        discovery_sources=["PubMed"],
    )
    crossref = Article(
        doi="10.1000/abc",
        title="A sufficiently long multiple sclerosis article title",
        abstract="A much longer abstract with additional metadata from Crossref.",
        publisher="Publisher",
        pub_date="2026-09-18",
        discovery_sources=["Crossref"],
    )
    merged = deduplicate_articles([pubmed, crossref])
    assert len(merged) == 1
    assert merged[0].pmid == "123"
    assert merged[0].doi == "10.1000/abc"
    assert set(merged[0].discovery_sources) == {"PubMed", "Crossref"}
    assert merged[0].publisher == "Publisher"
    assert merged[0].abstract.startswith("A much longer")


def test_discovery_survives_partial_source_failure(monkeypatch):
    import radar.pipeline as pipeline

    def fail_pubmed(*args, **kwargs):
        raise RuntimeError("temporary failure")

    def crossref_ok(*args, **kwargs):
        return [
            Article(
                doi="10.1000/fallback",
                title="A long multiple sclerosis paper found outside PubMed",
                pub_date="2026-09-18",
                discovery_sources=["Crossref"],
            )
        ]

    monkeypatch.setattr(pipeline.PubMedClient, "search_and_fetch", fail_pubmed)
    monkeypatch.setattr(pipeline.CrossrefClient, "search_recent", crossref_ok)

    result = pipeline.discover_literature(7, sources={"pubmed", "crossref"})
    assert len(result.articles) == 1
    assert result.counts["Crossref"] == 1
    assert any(msg.startswith("PubMed:") for msg in result.errors)
