from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import unicodedata

from .models import Article


MS_PHRASES = (
    "multiple sclerosis",
    "esclerose multipla",
    "esclerosis multiple",
    "sclerose en plaques",
)

# Acrônimos suficientemente específicos para EM. "MS" isolado não é usado,
# porque gera muitos falsos positivos em literatura biomédica e analítica.
MS_SPECIFIC_ACRONYMS = ("rrms", "spms", "ppms", "prms")


@dataclass(slots=True)
class MSEligibilityAssessment:
    score: float
    status: str  # high | moderate | pending | excluded | manual
    evidence: list[str] = field(default_factory=list)
    assessed_at: str = ""

    @property
    def eligible(self) -> bool:
        return self.status in {"high", "moderate", "manual"}


def assess_ms_eligibility(
    article: Article,
    *,
    high_threshold: float = 9.0,
    moderate_threshold: float = 6.0,
) -> MSEligibilityAssessment:
    """Avalia se o registro é especificamente relacionado à esclerose múltipla.

    A pontuação é deliberadamente conservadora. O termo curto ``MS`` nunca conta
    como evidência por si só. O filtro privilegia título, MeSH e keywords e usa o
    resumo apenas quando a expressão é explícita, especialmente no início do texto.
    """

    score = 0.0
    evidence: list[str] = []

    title = _normalize(article.title)
    abstract = _normalize(article.abstract)
    mesh = [_normalize(x) for x in article.mesh_terms if x]
    keywords = [_normalize(x) for x in article.keywords if x]
    author_keywords = [_normalize(x) for x in article.author_keywords if x]
    subjects = [_normalize(x) for x in article.subjects if x]

    # Título: evidência muito forte de que EM é o tema central.
    if _contains_ms_phrase(title):
        score += 10.0
        evidence.append("expressão de esclerose múltipla no título (+10)")
    elif _contains_specific_acronym(title):
        score += 7.0
        evidence.append("subtipo específico de EM no título, como RRMS/SPMS/PPMS (+7)")

    # MeSH: evidência controlada e muito forte.
    if any(_contains_ms_phrase(term) for term in mesh):
        score += 10.0
        evidence.append("termo MeSH de esclerose múltipla (+10)")

    # Keywords fornecidas pela base/periódico.
    if any(_contains_ms_phrase(term) for term in keywords):
        score += 9.0
        evidence.append("keyword de esclerose múltipla (+9)")
    if any(_contains_ms_phrase(term) for term in author_keywords):
        score += 9.0
        evidence.append("keyword dos autores sobre esclerose múltipla (+9)")

    # Subjects do Crossref tendem a ser mais amplos; portanto recebem peso menor.
    if any(_contains_ms_phrase(term) for term in subjects):
        score += 4.0
        evidence.append("subject relacionado explicitamente à esclerose múltipla (+4)")

    # Resumo: uma menção isolada e tardia pode ser apenas contextual. Se a doença
    # aparece no início do resumo, isso é uma evidência bem mais forte.
    abstract_phrase_count = _count_ms_phrases(abstract)
    if abstract_phrase_count:
        first_hit = _first_ms_phrase_position(abstract)
        if first_hit is not None and first_hit <= 180:
            score += 9.0
            evidence.append("esclerose múltipla aparece logo no início do resumo (+9)")
        elif first_hit is not None and first_hit <= 500:
            score += 6.0
            evidence.append("esclerose múltipla nos primeiros 500 caracteres do resumo (+6)")
        else:
            score += 3.0
            evidence.append("esclerose múltipla mencionada no resumo (+3)")

        if abstract_phrase_count >= 2:
            score += 2.0
            evidence.append("esclerose múltipla aparece repetidamente no resumo (+2)")
    elif _contains_specific_acronym(abstract):
        score += 4.0
        evidence.append("subtipo específico de EM no resumo, como RRMS/SPMS/PPMS (+4)")

    # Limita a escala para facilitar leitura no painel.
    score = round(min(score, 25.0), 1)

    if score >= high_threshold:
        status = "high"
    elif score >= moderate_threshold:
        status = "moderate"
    else:
        # Registros recém-depositados no Crossref frequentemente ainda não têm
        # abstract/MeSH/keywords. Eles ficam pendentes, em vez de serem descartados,
        # para poderem ser reavaliados quando surgirem metadados novos.
        if _has_limited_evidence(article):
            status = "pending"
        else:
            status = "excluded"

    return MSEligibilityAssessment(
        score=score,
        status=status,
        evidence=evidence,
        assessed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def apply_ms_eligibility(
    article: Article,
    *,
    high_threshold: float = 9.0,
    moderate_threshold: float = 6.0,
    manual_override: bool = False,
) -> Article:
    assessment = assess_ms_eligibility(
        article,
        high_threshold=high_threshold,
        moderate_threshold=moderate_threshold,
    )
    article.ms_score = assessment.score
    article.ms_eligibility = "manual" if manual_override and not assessment.eligible else assessment.status
    article.ms_evidence = list(assessment.evidence)
    if manual_override and not assessment.eligible:
        article.ms_evidence.append("incluído por importação manual de DOI")
    article.ms_assessed_at = assessment.assessed_at
    return article


def _has_limited_evidence(article: Article) -> bool:
    """Indica que ainda há pouca informação para uma exclusão segura."""
    return not bool(
        (article.abstract or "").strip()
        or article.mesh_terms
        or article.keywords
        or article.author_keywords
    )


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("–", "-").replace("—", "-")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _contains_ms_phrase(text: str) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) for phrase in MS_PHRASES)


def _count_ms_phrases(text: str) -> int:
    return sum(
        len(re.findall(rf"(?<!\w){re.escape(phrase)}(?!\w)", text))
        for phrase in MS_PHRASES
    )


def _first_ms_phrase_position(text: str) -> int | None:
    positions: list[int] = []
    for phrase in MS_PHRASES:
        match = re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text)
        if match:
            positions.append(match.start())
    return min(positions) if positions else None


def _contains_specific_acronym(text: str) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(acronym)}(?!\w)", text) for acronym in MS_SPECIFIC_ACRONYMS)
