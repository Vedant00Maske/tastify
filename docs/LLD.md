# TASTIFY — Low-Level Design

> Derived from the approved specification [TASTIFY_v0.1.md](../TASTIFY_v0.1.md) (§6.1, §6.6, §13).
> This file is the maintained version: update it in the same pull request as the code it describes.

## 6. Low-Level Design (LLD)

### 6.1 Design Principles

We will follow:

- SOLID principles.
- Dependency inversion.
- Repository pattern.
- Strategy pattern.
- Factory pattern where appropriate.
- Dependency injection.
- Domain-driven module boundaries.

---

### 6.6 Main Application Classes

#### UserProfileService

- get_profile()
- update_preferences()
- update_taste_profile()
- get_user_history()

#### MusicCatalogService

- get_track()
- search_tracks()
- get_artist()
- resolve_external_track()

#### InteractionService

- record_event()
- validate_event()
- get_interaction_history()
- aggregate_interactions()

#### CandidateGenerator

- generate_content_candidates()
- generate_collaborative_candidates()
- generate_popularity_candidates()
- merge_candidates()

#### RecommendationRanker

- calculate_content_score()
- calculate_collaborative_score()
- calculate_novelty_score()
- calculate_mood_score()
- calculate_final_score()

#### DiversityReranker

- remove_duplicates()
- apply_artist_constraints()
- calculate_mmr()
- generate_diverse_results()

#### RecommendationService

- recommend()
- recommend_by_mood()
- recommend_by_artist()
- recommend_by_genre()
- recommend_hidden_gems()

#### PlaylistService

- create_playlist()
- update_playlist()
- add_track()
- remove_track()
- reorder_tracks()
- export_playlist()

#### ProviderIntegrationService

- authenticate_provider()
- import_user_data()
- search_provider_catalogue()
- export_playlist()
- refresh_access_token()

---

## 13. Data Structures and Algorithm Selection

| Data structure | Application | Complexity benefit |
|---|---|---|
| HashMap | Track lookup | O(1) average |
| HashSet | Deduplication | O(1) average |
| Heap | Top-K candidates | O(N log K) |
| Sparse Matrix | User-item interactions | Memory efficient |
| Graph | User-artist-track relationships | Relationship traversal |
| Vector Index | Similarity retrieval | Efficient approximate search |
| Queue | Background jobs | Asynchronous processing |
| LRU Cache | Recommendation caching | Fast repeated reads |

We will select structures based on measured workload rather than introducing them just to demonstrate knowledge of data structures.
