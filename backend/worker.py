"""Background job worker for analysis jobs.

Design (see docs/ARCHITECTURE.md §3):

  * Jobs are the `uploads` rows themselves. POST /analyze inserts the row in
    `pending` state and pushes its id onto an in-process asyncio queue.
  * A single consumer task runs jobs sequentially. Each job advances through
    explicit stages (queued → loading → profiling → planning → computing →
    findings → narrating → persisting → done/failed) that the frontend polls.
  * Blocking pandas work runs via `asyncio.to_thread` so the event loop (and
    thus the HTTP API) is never blocked.
  * Transient failures retry up to JOB_MAX_ATTEMPTS with exponential backoff;
    permanent failures (FriendlyError) fail immediately with a user-friendly
    message. A job-level timeout cancels hung jobs.
  * On startup the worker recovers interrupted work: `pending` jobs are
    requeued, `processing` jobs older than JOB_STALE_SECONDS are failed.

Swapping to Celery/BullMQ later only requires re-implementing `submit` /
`recover` on this class — everything else stays.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

import agent
import db as db_ops
from storage_utils import SourceFile, download_source
from config import settings
from eda.errors import FriendlyError, TransientError

logger = logging.getLogger("datascope.worker")

# Process-wide cap on concurrent heavy loads (plan preview + worker). Both the
# HTTP plan preview and the job worker load full frames into the same single
# process; this semaphore keeps at most one heavy frame alive at a time so two
# large loads never overlap inside the same memory budget.
heavy_load_semaphore = asyncio.Semaphore(settings.heavy_load_concurrency)


def _memory_mib() -> tuple[int, int]:
    """Return (RSS, HWM) in MiB for the current process."""
    rss = hwm = 0
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) // 1024
                elif line.startswith("VmHWM:"):
                    hwm = int(line.split()[1]) // 1024
    except OSError:
        pass
    return rss, hwm


class StageClock:
    """Per-stage instrumentation: structured log lines with duration + RSS.

    Each transition emits ``stage, upload, dt, elapsed, rss_mib, hwm_mib`` so
    per-stage regressions are answerable from log aggregation alone (no DB
    schema change).
    """

    def __init__(self, upload_id: str) -> None:
        self.upload_id = upload_id
        self._t0 = time.monotonic()
        self._prev = self._t0
        rss, hwm = _memory_mib()
        self._rss0, self._hwm0 = rss, hwm
        logger.info("stage=start upload=%s rss_mib=%d hwm_mib=%d",
                    upload_id, rss, hwm)

    def mark(self, stage: str, extra: str = "") -> None:
        now = time.monotonic()
        rss, hwm = _memory_mib()
        logger.info(
            "stage=%s upload=%s dt=%.2fs elapsed=%.2fs rss_mib=%d "
            "hwm_mib=%d%s",
            stage, self.upload_id, now - self._prev, now - self._t0,
            rss, hwm, extra,
        )
        self._prev = now


class Worker:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._consumer: asyncio.Task | None = None
        self._running: set[str] = set()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._consumer = asyncio.create_task(self._consume(), name="eda-worker")

    async def stop(self) -> None:
        if self._consumer:
            self._consumer.cancel()
            try:
                await self._consumer
            except asyncio.CancelledError:
                pass

    async def submit(self, upload_id: str) -> None:
        await self._queue.put(upload_id)

    @property
    def running_jobs(self) -> list[str]:
        return sorted(self._running)

    async def recover(self) -> None:
        """Requeue pending jobs and fail stale 'processing' ones."""
        try:
            client = db_ops.get_client()
            pending = (
                client.table("uploads")
                .select("id")
                .eq("status", "pending")
                .execute()
            )
            for row in pending.data:
                await self.submit(row["id"])
            for row in db_ops.get_stale_processing(
                client, settings.job_stale_seconds
            ):
                db_ops.set_upload_failed(
                    client,
                    row["id"],
                    "The service restarted while this analysis was running. "
                    "Please upload the file again.",
                )
            if pending.data:
                logger.info("recovered %d pending job(s)", len(pending.data))
        except Exception:  # noqa: BLE001
            logger.exception("worker recovery failed")

    # -- consumption -------------------------------------------------------

    async def _consume(self) -> None:
        while True:
            upload_id = await self._queue.get()
            self._running.add(upload_id)
            try:
                await self._run_job(upload_id)
            except Exception:  # noqa: BLE001
                logger.exception("unexpected worker failure for %s", upload_id)
            finally:
                self._running.discard(upload_id)
                self._queue.task_done()

    async def _run_job(self, upload_id: str) -> None:
        client = db_ops.get_client()
        upload = db_ops.get_upload(client, upload_id)
        if upload is None:
            logger.warning("job %s vanished from uploads table", upload_id)
            return
        if upload["status"] == "done":
            return

        db_ops.set_upload_status(client, upload_id, "processing")
        db_ops.set_upload_stage(client, upload_id, "loading",
                                "Downloading and reading your file…", 15)

        for attempt in range(1, settings.job_max_attempts + 1):
            try:
                await asyncio.wait_for(
                    self._process(upload),
                    timeout=settings.job_timeout_seconds,
                )
                return
            except asyncio.TimeoutError:
                logger.warning("job %s timed out after %ss", upload_id,
                               settings.job_timeout_seconds)
                db_ops.set_upload_failed(
                    client, upload_id,
                    "The analysis took too long and was cancelled. Try a "
                    "smaller file, or fewer columns.",
                )
                return
            except TransientError as exc:
                if attempt < settings.job_max_attempts:
                    backoff = min(2 ** attempt, 30)
                    logger.warning("job %s transient failure (attempt %d): %s",
                                   upload_id, attempt, exc)
                    db_ops.set_upload_meta(client, upload_id, attempts=attempt)
                    await asyncio.sleep(backoff)
                    continue
                db_ops.set_upload_failed(
                    client, upload_id,
                    "A temporary service issue interrupted the analysis. "
                    "Please try again in a minute.",
                )
                return
            except FriendlyError as exc:
                logger.warning("job %s permanent failure: %s", upload_id,
                               exc.user_message)
                db_ops.set_upload_failed(client, upload_id, exc.user_message)
                return
            except Exception:  # noqa: BLE001
                logger.exception("job %s failed unexpectedly", upload_id)
                db_ops.set_upload_failed(
                    client, upload_id,
                    "Something went wrong while analyzing your file. Please "
                    "try again.",
                )
                return

    # -- the pipeline ------------------------------------------------------

    async def _process(self, upload: dict[str, Any]) -> None:
        client = db_ops.get_client()
        upload_id: str = upload["id"]
        storage_path: str = upload["storage_path"]
        filename: str = upload["filename"]
        overrides: dict[str, Any] = upload.get("overrides_json") or {}

        clock = StageClock(upload_id)

        db_ops.set_upload_stage(client, upload_id, "loading",
                                "Downloading your file…", 15)
        source = await asyncio.to_thread(
            self._download, client, storage_path, filename
        )
        if source is None:
            raise FriendlyError(
                "The file could not be found in secure storage. Please "
                "upload it again.",
                kind="storage",
            )
        clock.mark("downloaded", f" size_mib={source.size / 1048576:.1f}")

        try:
            # The heavy section (load + compute) runs under the shared
            # semaphore so at most one large frame is alive in the process
            # memory budget at a time (plan previews queue behind jobs).
            async with heavy_load_semaphore:
                db_ops.set_upload_stage(client, upload_id, "profiling",
                                        "Reading columns and profiling…", 30)
                prepared = await asyncio.to_thread(
                    agent.prepare, source, filename, storage_path
                )
                try:
                    db_ops.set_upload_meta(
                        client, upload_id,
                        file_size_bytes=source.size,
                        source_format=prepared.loaded.fmt,
                        detected_encoding=prepared.loaded.encoding,
                        row_estimate=prepared.loaded.total_rows,
                        column_count=int(prepared.loaded.df.shape[1]),
                        analysis_mode=prepared.mode,
                    )
                    clock.mark("prepared")

                    db_ops.set_upload_stage(client, upload_id, "planning",
                                            "Designing the analysis plan…", 40)
                    # Prior-report context must be attached before planning so
                    # the plan cache key matches the plan preview (same
                    # injection).
                    prior_report = await asyncio.to_thread(
                        db_ops.get_most_recent_report,
                        client, upload["user_id"], exclude_upload_id=upload_id,
                    )
                    await asyncio.to_thread(
                        agent.attach_prior_context, prepared, prior_report
                    )
                    await agent.plan_file(prepared, overrides)
                    db_ops.set_upload_meta(
                        client, upload_id,
                        analysis_plan_json={
                            "tasks": prepared.plan_tasks,
                            "source": prepared.plan_source,
                            "cache_key": prepared.plan_cache_key,
                        },
                    )
                    clock.mark("planned")

                    db_ops.set_upload_stage(client, upload_id, "computing",
                                            "Computing statistics and running tests…", 70)
                    # Server-side tier gating for the heavy adaptive tasks:
                    # the plan is fetched from the owner's profile, never
                    # trusted from the UI.
                    profile = await asyncio.to_thread(
                        db_ops.get_profile, client, upload["user_id"]
                    )
                    user_plan = (profile or {}).get("plan") if profile else None
                    result = await agent.execute(
                        prepared, storage_path, overrides, prior_report,
                        user_plan,
                    )
                    clock.mark("computed")
                finally:
                    await asyncio.to_thread(agent.dispose, prepared)

            db_ops.set_upload_stage(client, upload_id, "narrating",
                                    "Writing the plain-English report…", 90)
            narration = await agent.narrate_result(prepared, result)
            clock.mark("narrated")

            db_ops.set_upload_stage(client, upload_id, "persisting",
                                    "Saving your report…", 98)
            report = db_ops.insert_report(
                client,
                upload_id,
                result["summary"],
                narration["narrative"],
                analysis_plan_json={
                    "tasks": result["plan_tasks"],
                    "source": result["plan_source"],
                },
                overrides_json=overrides or None,
                sample_info_json=result["sample_info"],
                analysis_mode=result["mode"],
                source_format=result["format"],
                column_glossary=narration["column_glossary"],
            )
            db_ops.set_report_export_urls(
                client,
                report["id"],
                export_html_url=f"/api/reports/{report['id']}/export/html",
                export_pdf_url=f"/api/reports/{report['id']}/export/pdf",
                cleaned_data_url=f"/api/reports/{report['id']}/download/clean",
            )
            db_ops.mark_upload_done(client, upload_id)

            try:
                db_ops.decrement_credit(client, upload["user_id"])
            except Exception:  # noqa: BLE001
                logger.warning("failed to decrement credit for user=%s",
                               upload["user_id"])

            clock.mark("persisted")
            logger.info("analysis done upload=%s report=%s", upload_id,
                        report["id"])
        finally:
            source.cleanup()

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _download(client: Any, storage_path: str, filename: str) -> SourceFile | None:
        try:
            return download_source(client, storage_path)
        except FriendlyError:
            raise
        except httpx.HTTPError as exc:
            raise TransientError(f"storage download failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise TransientError(f"storage download failed: {exc}") from exc


worker = Worker()
