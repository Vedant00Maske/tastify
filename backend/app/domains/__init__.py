"""Business domains (modular monolith boundaries, see docs/HLD.md and ADR-001).

Each domain owns its models, services and schemas. Domains talk to each other through
service interfaces, never through each other's ORM models or repositories.
"""
