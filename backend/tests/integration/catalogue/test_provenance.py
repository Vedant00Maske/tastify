import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.models import IngestionJob
from app.domains.catalogue.provenance import JobRecorder
from tests.integration.catalogue.conftest import register_source

pytestmark = pytest.mark.integration


async def test_a_crashing_stage_marks_its_job_failed(session: AsyncSession) -> None:
    source_id = await register_source(session, "musicbrainz")
    job = await JobRecorder.start(session, source_id, "catalogue", {"size": 10})

    async def crashing_stage() -> None:
        async with job:
            job.stats["fetched"] += 3
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await crashing_stage()

    row = await session.get(IngestionJob, job.job_id, populate_existing=True)
    assert row is not None
    assert row.status == "failed"
    assert row.error_message == "RuntimeError: boom"
    assert row.finished_at is not None
    assert row.stats["fetched"] == 3


async def test_errors_are_sampled_per_code(session: AsyncSession) -> None:
    source_id = await register_source(session, "fma")
    async with await JobRecorder.start(session, source_id, "fma", {}) as job:
        for index in range(250):
            job.error("validation", "invalid_fma_track", str(index), "bad row")
        await job.finish()

    row = await session.get(IngestionJob, job.job_id, populate_existing=True)
    assert row is not None
    assert row.status == "succeeded"
    assert row.stats["errors"] == {"invalid_fma_track": 250}
