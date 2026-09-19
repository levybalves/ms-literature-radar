from __future__ import annotations

import unittest

from radar import enrichment


SAMPLE_HTML = """
<!doctype html>
<html>
<head>
  <meta name="citation_publisher" content="Example Scientific Press">
  <meta name="citation_online_date" content="2026/09/18">
  <meta name="citation_article_type" content="Research Article">
  <meta name="citation_abstract" content="Multiple sclerosis is the central disease studied in this article.">
  <meta name="citation_keywords" content="multiple sclerosis; EBNA1; HLA-DRB1">
  <meta name="citation_author_institution" content="Example University">
  <meta name="citation_pdf_url" content="/article.pdf">
  <meta name="citation_graphical_abstract" content="/graphical-abstract.png">
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "ScholarlyArticle",
    "isAccessibleForFree": true,
    "keywords": ["molecular mimicry", "T cell"]
  }
  </script>
</head>
<body>
  <a href="/supplementary/s1.pdf">Supplementary material</a>
</body>
</html>
"""


@unittest.skipIf(enrichment.BeautifulSoup is None, "beautifulsoup4 não instalado")
class PublisherHtmlParserTests(unittest.TestCase):
    def test_generic_metadata_extraction(self) -> None:
        data = enrichment.parse_publisher_html(
            SAMPLE_HTML,
            "https://example.org/articles/123",
        )

        self.assertEqual(data["publisher"], "Example Scientific Press")
        self.assertEqual(data["online_date"], "2026-09-18")
        self.assertEqual(data["article_type"], "Research Article")
        self.assertIn("Multiple sclerosis", data["abstract"])
        self.assertEqual(data["open_access_status"], "yes")
        self.assertIn("EBNA1", data["author_keywords"])
        self.assertIn("molecular mimicry", data["author_keywords"])
        self.assertIn("Example University", data["affiliations"])
        self.assertEqual(
            data["graphical_abstract_url"],
            "https://example.org/graphical-abstract.png",
        )
        self.assertIn("https://example.org/article.pdf", data["fulltext_urls"])
        self.assertIn(
            "https://example.org/supplementary/s1.pdf",
            data["supplementary_urls"],
        )


if __name__ == "__main__":
    unittest.main()
