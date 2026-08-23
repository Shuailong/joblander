"""Domain models.

Status / Priority / Source mirror the real Notion tracker schema verbatim
(fetched 2026-08-06), so proposals can round-trip without mapping tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class Status(str, Enum):
    ADDED = "Added"
    DREAM = "Dream"
    IN_CONSIDERATION = "In Consideration"
    TO_APPLY = "To Apply"
    SCREENING_CALLED = "Screening Called"
    APPLIED = "Applied"
    INTERVIEW_SCHEDULED = "Interview Scheduled"
    INTERVIEW_COMPLETED = "Interview Completed"
    TERMINATED = "Terminated"
    NOT_APPLY = "Not Apply"
    OFFER_RECEIVED = "Offer Received"
    REJECTED = "Rejected"
    WITHDRAWN = "Withdrawn"


class Priority(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Source(str, Enum):
    LINKEDIN = "LinkedIn"
    COMPANY_WEBSITE = "Company Website"
    REFERRAL = "Referral"
    JOB_BOARD = "Job Board"
    RECRUITER = "Recruiter"
    CAREER_FAIR = "Career Fair"
    SOCIAL_MEDIA = "Social Media"
    COLD_APPLICATION = "Cold Application"
    HEADHUNTER = "Headhunter"
    EMAIL = "Email"


@dataclass
class Opportunity:
    """One tracker row. `notion_page_id` is the join key back to the SoT."""

    company: str
    position: str | None = None
    status: Status = Status.ADDED
    priority: Priority | None = None
    source: Source | None = None
    contact_person: str | None = None
    contact_info: str | None = None
    job_url: str | None = None
    highlight: str | None = None       # 约定：一句短语，表格扫读用
    next_steps: str | None = None      # 约定：一句话动作
    feedback: str | None = None
    date_applied: date | None = None
    follow_up: date | None = None
    added_date: date | None = None
    notion_page_id: str | None = None


@dataclass
class Event:
    """Append-only log entry. Everything the system perceives or does is an Event."""

    ts: datetime
    kind: str                          # e.g. "email.received", "transcript.dropped", "proposal.approved"
    source: str                        # e.g. "gmail", "doubao", "human"
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextPack:
    """Explicitly assembled context for one agent run, with a token budget.

    装配器本身可测：该进包的关键事实是否进了包（见 DESIGN.md §9.6）。
    """

    task: str                          # 本次运行的任务定义
    sections: dict[str, str] = field(default_factory=dict)  # 命名分区 -> 内容（档案/Playbook/近期事件…）
    token_budget: int = 32_000
    sources: list[str] = field(default_factory=list)        # 溯源：内容来自哪些 store/事件


@dataclass
class WorkflowRun:
    """One workflow instance. Every step emits Events tagged with run_id."""

    run_id: str
    workflow: str                      # e.g. "W8.interview-logging"
    trigger_event_ts: datetime
    status: str = "running"            # running | done | failed | budget_exceeded
    token_spent: int = 0


@dataclass
class ChangeProposal:
    """A write the system WANTS to make to the SoT. Never applied without approval.

    体现 HITL 闸门：agent 产出提案，人批准，工具层执行。
    """

    agent: str                         # 提案来源 agent
    rationale: str                     # 一句话：为什么要改
    notion_page_id: str | None         # None = 提案新建行
    field_diffs: dict[str, Any] = field(default_factory=dict)   # 属性名 -> 新值
    body_entry: str | None = None      # 追加到页面正文的 `### YYYY-MM-DD 事件` 条目（倒序插入）
    approved: bool | None = None       # None=待审 True=批准 False=否决
