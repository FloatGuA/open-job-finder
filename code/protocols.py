from typing import Protocol, runtime_checkable, List
from schemas import Job, ApplicationRecord, StatusUpdate


@runtime_checkable
class LLMProviderProtocol(Protocol):
    name: str

    def is_available(self) -> bool: ...

    def complete(self, prompt: str, system: str = "", output_schema: "dict | None" = None, think: bool = False, images: "list | None" = None) -> str: ...


@runtime_checkable
class TrackerProtocol(Protocol):
    def exists(self, job_id: str) -> bool: ...

    def upsert(self, record: ApplicationRecord) -> None: ...

    def count_today(self) -> int: ...

    def get_all(self) -> List[ApplicationRecord]: ...

    def get_pending_responses(self) -> List[ApplicationRecord]: ...

    def has_action(self, job_id: str, action: str) -> bool: ...

    def mark_action(self, job_id: str, action: str) -> None: ...


@runtime_checkable
class BrowserAgentProtocol(Protocol):
    def search(self, keywords: str, city: str, limit: int) -> List[Job]: ...

    def open_job(self, url: str) -> tuple: ...

    def apply(self, job: Job, resume_path: str) -> bool: ...

    def check_chat_list(self) -> List[StatusUpdate]: ...


@runtime_checkable
class ToolProtocol(Protocol):
    name: str
    description: str
    input_schema: dict
    output_schema: dict

    def execute(self, **kwargs) -> dict: ...
