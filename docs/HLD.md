# SONIQUEO — High-Level Design

> Derived from the approved specification [SONIQUEO_v0.1.md](../SONIQUEO_v0.1.md) (§5, §21).
> This file is the maintained version: update it in the same pull request as the code it describes.

## 5. High-Level Design (HLD)

### 5.1 Architectural Style

SONIQUEO will initially use a modular monolith.

Reasoning:

- Easier initial development.
- Simpler deployment.
- Lower infrastructure costs.
- Clear separation of responsibilities.
- Easier local debugging.
- Ability to extract individual services later.

We will avoid premature microservices.

### 5.2 System Components

#### Presentation Layer
Technology: Next.js, React, TypeScript.

Responsibilities:
- Authentication interfaces.
- Onboarding.
- Recommendation dashboard.
- Playlist management.
- User preferences.
- Interaction collection.

#### API Layer
Technology: FastAPI.

Responsibilities:
- Request validation.
- Authentication and authorization.
- API routing.
- Rate limiting.
- Response serialization.
- Coordination between business services.

#### User Domain

Responsibilities:
- User accounts.
- User preferences.
- Taste profiles.
- External account connections.
- User interaction history.

#### Music Catalogue Domain

Responsibilities:
- Track metadata.
- Artist information.
- Genre classification.
- External provider identifiers.
- Music feature management.
- Catalogue deduplication.

#### Recommendation Domain

Responsibilities:
- Candidate generation.
- Candidate filtering.
- Recommendation ranking.
- Diversity re-ranking.
- Recommendation explanations.

#### Playlist Domain

Responsibilities:
- Playlist creation.
- Playlist editing.
- Track ordering.
- Playlist persistence.
- External playlist export.

#### Integration Domain

Responsibilities:
- Provider authentication.
- Metadata retrieval.
- User-data imports.
- Playlist export.
- Provider-specific rate limits.
- Error handling and retries.

#### ML Domain

Responsibilities:
- Data preprocessing.
- Feature engineering.
- Model training.
- Embedding generation.
- Model evaluation.
- Model versioning.
- Inference.

### 5.3 HLD Data Flow

1. User registers.
2. User connects a supported music provider or selects onboarding preferences.
3. The integration layer retrieves permitted information.
4. Data is normalized into the internal music catalogue.
5. Interaction events are recorded.
6. Feature engineering creates user and track representations.
7. The recommendation engine generates candidates.
8. The ranking engine scores candidates.
9. The diversity layer produces the final recommendation list.
10. The frontend displays recommendations.
11. User feedback is collected.
12. The feedback updates future recommendations.

### 5.4 Proposed Infrastructure

| Component | Technology |
|---|---|
| Frontend | Next.js |
| Backend | FastAPI |
| Primary database | PostgreSQL |
| Vector search | pgvector |
| Cache | Redis |
| Background jobs | Celery |
| Task broker | Redis |
| ML framework | PyTorch |
| Classical ML | scikit-learn |
| Data processing | pandas, NumPy |
| Experiment tracking | MLflow |
| Containerization | Docker |
| CI/CD | GitHub Actions |
| Monitoring | Prometheus and Grafana |
| Error tracking | Sentry |
| Object storage | S3-compatible storage |

---

## 21. Final Engineering Principles

The following principles govern the entire project:

1. Recommendation intelligence belongs to SONIQUEO, not external music platforms.
2. No provider-specific assumptions should leak into the core recommendation domain.
3. Every recommendation model must be evaluated against a baseline.
4. Every user interaction must have a clearly defined meaning.
5. Short-term interests must not automatically overwrite long-term taste.
6. Relevance and diversity must be balanced.
7. User data must be handled with explicit consent.
8. Security and testing are part of development, not final-stage activities.
9. Avoid premature optimization and unnecessary distributed architecture.
10. Prioritize measurable user value over algorithmic complexity.

### Final Product Goal

SONIQUEO should become a working, publicly accessible music discovery product that demonstrates end-to-end Machine Learning Engineering:

**Data Engineering → Feature Engineering → Model Development → Candidate Retrieval → Ranking → Evaluation → Backend Integration → Frontend → Deployment → Real User Feedback.**

The architecture must remain extensible enough to support new recommendation models, additional music platforms and increasing numbers of users without rewriting the core application.

**Document status: Initial engineering specification approved. Implementation begins with Milestone 0.**
