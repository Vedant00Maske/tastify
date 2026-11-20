"""Operations commands for deployed instances (Milestone 7; RUNBOOK.md).

    python -m app.cli check-config       # list unsafe settings for staging/production
    python -m app.cli prune              # run the daily retention job now
    python -m app.cli rotate-token-key   # re-encrypt provider tokens with the current key

In containers: `docker compose -f docker-compose.prod.yml run --rm backend python -m app.cli ...`.
"""

import argparse
import asyncio
import sys
from dataclasses import asdict

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionFactory, engine


def check_config() -> int:
    settings = get_settings()
    problems = settings.deployment_problems()
    sys.stdout.write(f"environment: {settings.environment}\n")
    for problem in problems:
        sys.stdout.write(f"  unsafe: {problem}\n")
    if not problems:
        sys.stdout.write("  no problems found\n")
    return 1 if problems and settings.is_deployed else 0


async def prune() -> int:
    from app.domains import maintenance

    async with SessionFactory() as session:
        result = await maintenance.prune(session)
    sys.stdout.write(f"{asdict(result)}\n")
    return 0


async def rotate_token_key() -> int:
    """Re-encrypt every stored provider token with INTEGRATIONS_TOKEN_KEY. Values that only an
    old key (INTEGRATIONS_TOKEN_PREVIOUS_KEYS) can read are rewritten; afterwards the previous
    keys can be removed. Safe to interrupt and run again."""
    from app.domains.integrations.models import ProviderConnection
    from app.domains.integrations.tokens import TokenCipher, TokenDecryptionError

    cipher = TokenCipher.from_settings()
    rotated = unreadable = 0
    async with SessionFactory() as session:
        connections = (await session.scalars(select(ProviderConnection))).all()
        for connection in connections:
            user, provider = connection.user_id, connection.provider
            try:
                for field in ("access_token", "refresh_token"):
                    value = getattr(connection, field)
                    if value is None or cipher.is_current(value, user, provider):
                        continue
                    plain = cipher.decrypt(value, user, provider)
                    setattr(connection, field, cipher.encrypt(plain, user, provider))
                    rotated += 1
            except TokenDecryptionError:
                unreadable += 1  # no configured key reads it: the user must reconnect
        await session.commit()
    sys.stdout.write(
        f"connections: {len(connections)}, values re-encrypted: {rotated}, "
        f"unreadable connections: {unreadable}\n"
    )
    return 1 if unreadable else 0


async def _run(command: str) -> int:
    try:
        if command == "prune":
            return await prune()
        return await rotate_token_key()
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    parser.add_argument("command", choices=("check-config", "prune", "rotate-token-key"))
    args = parser.parse_args(argv)
    if args.command == "check-config":
        return check_config()
    return asyncio.run(_run(args.command))


if __name__ == "__main__":
    raise SystemExit(main())
