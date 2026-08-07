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
from typing import Any

import httpx

import agent
import db as db_ops
from storage_utils import download_source
from config import settings
from eda.errors import FriendlyError, TransientError

logger = logging.getLogger("datascope.worker")


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

        db_ops.set_upload_stage(client, upload_id, "loading",
                                "Downloading your file…", 15)
        content = await asyncio.to_thread(
            self._download, client, storage_path, filename
        )
        if content is None:
            raise FriendlyError(
                "The file could not be found in secure storage. Please "
                "upload it again.",
                kind="storage",
            )

        db_ops.set_upload_stage(client, upload_id, "profiling",
                                "Reading columns and profiling…", 30)
        prepared = await asyncio.to_thread(
            agent.prepare, content, filename, storage_path
        )
        try:
            db_ops.set_upload_meta(
                client, upload_id,
                file_size_bytes=len(content),
                source_format=prepared.loaded.fmt,
                detected_encoding=prepared.loaded.encoding,
                row_estimate=prepared.loaded.total_rows,
                column_count=int(prepared.loaded.df.shape[1]),
                analysis_mode=prepared.mode,
            )

            db_ops.set_upload_stage(client, upload_id, "planning",
                                    "Designing the analysis plan…", 40)
            await agent.plan_file(prepared, overrides)
            db_ops.set_upload_meta(
                client, upload_id,
                analysis_plan_json={
                    "tasks": prepared.plan_tasks,
                    "source": prepared.plan_source,
                    "cache_key": prepared.plan_cache_key,
                },
            )

            db_ops.set_upload_stage(client, upload_id, "computing",
                                    "Computing statistics and running tests…", 70)
            result = await asyncio.to_thread(
                agent.execute, prepared, storage_path, overrides
            )

            db_ops.set_upload_stage(client, upload_id, "narrating",
                                    "Writing the plain-English report…", 90)
            narrative = await agent.narrate_result(prepared, result)

            db_ops.set_upload_stage(client, upload_id, "persisting",
                                    "Saving your report…", 98)
            report = db_ops.insert_report(
                client,
                upload_id,
                result["summary"],
                narrative,
                analysis_plan_json={
                    "tasks": result["plan_tasks"],
                    "source": result["plan_source"],
                },
                overrides_json=overrides or None,
                sample_info_json=result["sample_info"],
                analysis_mode=result["mode"],
                source_format=result["format"],
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
                db_ops.increment_reports_used(client, upload["user_id"])
            except Exception:  # noqa: BLE001
                logger.warning("failed to increment usage for user=%s",
                               upload["user_id"])

            logger.info("analysis done upload=%s report=%s", upload_id,
                        report["id"])
        finally:
            await asyncio.to_thread(agent.dispose, prepared)

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _download(client: Any, storage_path: str, filename: str) -> bytes | None:
        try:
            return download_source(client, storage_path)
        except FriendlyError:
            raise
        except httpx.HTTPError as exc:
            raise TransientError(f"storage download failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise TransientError(f"storage download failed: {exc}") from exc


worker = Worker()
