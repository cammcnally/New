from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Literal, Optional

from lineage.backend import FileTransport as JsonFileTransport

_OPENLINEAGE_IMPORT_ERROR: ImportError | None = None

try:
    from openlineage.client import OpenLineageClient
    from openlineage.client.constants import DEFAULT_PRODUCER
    from openlineage.client.run import InputDataset, Job, OutputDataset, Run, RunEvent, RunState
    from openlineage.client.serde import Serde
    from openlineage.client.transport.transport import Config, Transport
    from openlineage.client.facet_v2 import (
        documentation_job as documentation_job_facet,
        error_message_run,
        schema_dataset as schema_dataset_facet,  # noqa: F401
        sql_job as sql_job_facet,  # noqa: F401
    )
except ImportError as exc:
    OpenLineageClient = None  # type: ignore[misc, assignment]
    _OPENLINEAGE_IMPORT_ERROR = exc


if OpenLineageClient is not None:

    class _DictFileTransport(Transport):
        """Adapts :class:`lineage.backend.FileTransport` to OpenLineage's transport interface."""

        kind = "swing_pipeline_file"
        config_class = Config

        def __init__(self, backend: JsonFileTransport) -> None:
            self._backend = backend

        def emit(self, event: Any) -> None:
            self._backend.emit(Serde.to_dict(event))

    def _event_time() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    class PipelineLineageEmitter:
        """Emit OpenLineage RunEvents for the swing-trading pipeline."""

        def __init__(
            self,
            namespace: str = "swing-pipeline",
            job_name: str = "pipeline-run",
            transport: str = "file",
            output_dir: str = "lineage_events",
        ) -> None:
            self._namespace = namespace
            self._job_name = job_name
            self._transport_name = transport
            self._output_dir = output_dir
            self._file_backend: JsonFileTransport | None = None
            if transport == "file":
                self._file_backend = JsonFileTransport(output_dir)
            self._client_instance: OpenLineageClient | None = None

        @property
        def _client(self) -> OpenLineageClient:
            if self._client_instance is None:
                if self._transport_name == "file":
                    assert self._file_backend is not None
                    self._client_instance = OpenLineageClient(
                        transport=_DictFileTransport(self._file_backend),
                    )
                else:
                    raise ValueError(
                        f"Unsupported transport {self._transport_name!r}; supported values: 'file'."
                    )
            return self._client_instance

        def _base_job(self) -> Job:
            doc = documentation_job_facet.DocumentationJobFacet(
                description="Swing-trading research pipeline run.",
            )
            return Job(
                namespace=self._namespace,
                name=self._job_name,
                facets={documentation_job_facet.DocumentationJobFacet._get_schema(): doc},
            )

        def _build_dataset_facets(
            self,
            datasets: List[dict[str, Any]],
            kind: Literal["input", "output"] = "input",
        ) -> list[InputDataset] | list[OutputDataset]:
            if kind == "input":
                result: list[InputDataset] = []
                for spec in datasets:
                    facets = dict(spec.get("facets") or {})
                    result.append(
                        InputDataset(
                            namespace=spec["namespace"],
                            name=spec["name"],
                            facets=facets,
                            inputFacets=dict(spec.get("inputFacets") or {}),
                        ),
                    )
                return result
            result_o: list[OutputDataset] = []
            for spec in datasets:
                facets = dict(spec.get("facets") or {})
                result_o.append(
                    OutputDataset(
                        namespace=spec["namespace"],
                        name=spec["name"],
                        facets=facets,
                        outputFacets=dict(spec.get("outputFacets") or {}),
                    ),
                )
            return result_o

        def emit_start(
            self,
            run_id: str,
            input_datasets: List[dict[str, Any]],
            config_facet: Optional[dict[str, Any]] = None,
        ) -> None:
            run_facets: dict[Any, Any] = {}
            if config_facet:
                run_facets.update(config_facet)
            run = Run(runId=run_id, facets=run_facets)
            event = RunEvent(
                eventType=RunState.START,
                eventTime=_event_time(),
                run=run,
                job=self._base_job(),
                producer=DEFAULT_PRODUCER,
                inputs=self._build_dataset_facets(input_datasets, kind="input"),
            )
            self._client.emit(event)

        def emit_complete(self, run_id: str, output_datasets: List[dict[str, Any]]) -> None:
            event = RunEvent(
                eventType=RunState.COMPLETE,
                eventTime=_event_time(),
                run=Run(runId=run_id),
                job=self._base_job(),
                producer=DEFAULT_PRODUCER,
                outputs=self._build_dataset_facets(output_datasets, kind="output"),
            )
            self._client.emit(event)

        def emit_fail(self, run_id: str, error_message: str) -> None:
            err = error_message_run.ErrorMessageRunFacet(
                message=error_message,
                programmingLanguage="Python",
            )
            event = RunEvent(
                eventType=RunState.FAIL,
                eventTime=_event_time(),
                run=Run(
                    runId=run_id,
                    facets={error_message_run.ErrorMessageRunFacet._get_schema(): err},
                ),
                job=self._base_job(),
                producer=DEFAULT_PRODUCER,
            )
            self._client.emit(event)

else:

    class PipelineLineageEmitter:  # type: ignore[no-redef]
        """Stub when ``openlineage-python`` is not installed."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError(
                "openlineage-python is required for lineage emission. "
                "Install with: pip install 'openlineage-python>=1.28' "
                "or sync the project's `lineage` dependency group."
            ) from _OPENLINEAGE_IMPORT_ERROR

        def emit_start(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError(
                "openlineage-python is required for lineage emission. "
                "Install with: pip install 'openlineage-python>=1.28' "
                "or sync the project's `lineage` dependency group."
            ) from _OPENLINEAGE_IMPORT_ERROR

        def emit_complete(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError(
                "openlineage-python is required for lineage emission. "
                "Install with: pip install 'openlineage-python>=1.28' "
                "or sync the project's `lineage` dependency group."
            ) from _OPENLINEAGE_IMPORT_ERROR

        def emit_fail(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError(
                "openlineage-python is required for lineage emission. "
                "Install with: pip install 'openlineage-python>=1.28' "
                "or sync the project's `lineage` dependency group."
            ) from _OPENLINEAGE_IMPORT_ERROR
