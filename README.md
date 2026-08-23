# JobLander

**English | [中文](README.zh-CN.md)**

> Multi-agent engine for running a job search.
> Collapses the job-search information flow scattered across nine tools into one agent workflow with guardrails and evals.

**Status:** v0, running in a real job search — the web war room and every agent below are live, backed by an eval harness (full unit tests + blind-review scripts). Architecture and decision records: [`docs/DESIGN.md`](docs/DESIGN.md) (Chinese).

**Boundary:** This repo holds only the engine and docs. Personal data (resumes, compensation, pipeline, talking points) lives in a private workspace pointed to by `config.yaml` (gitignored) and never enters the repo. See DESIGN.md §6.

**Origin:** Built during a 2026 post-layoff job hunt — built while fighting, open-sourced after the war.

---

## Agent Teams

All agents are stateless: context pack in, artifact or proposal out. Features are composed as workflows, not one agent per feature (ADR-9). **The human is part of the topology**: every outward action (sending a message, writing to the calendar, writing to the source of truth) goes through a proposal queue — the user is the last hop.

### 🕵️ Intelligence — see the other side before the fight

| Agent | Role | Architecture |
|---|---|---|
| **Diligence** | Zero-input company due diligence: highlight card + four-section profile (every claim carries a numbered source) + per-round trail | **Multi-turn ReAct**: after planning its searches, loops "read body excerpts → judge five-way coverage (hiring motive / interview process / tech stack / compensation / stability) → issue new queries for the gaps"; filters repeated queries, marks dead corners after consecutive misses, stops when no new pages turn up. Quality gate: zero-LLM hard checks + five-dimension blind review |
| **Researcher** | Fed-material research: URLs / pasted material → dossier entries, each with source and date | Single-shot extraction; discipline: every piece of evidence must trace back to the input, unsourced inference is marked low-confidence |
| **Analyst** | JD + achievement bank + dossier + salary signals → two-score match snapshot + a radar whose axes are derived from that specific JD | LLM judgment + **policy-as-code**: walk-away lines, discount tiers, etc. are pure-function parameters in private config — judgments stay explainable and regression-testable |
| **Compensation** | A dated market-band report the moment a company enters the pool — numbers before conversations | Researcher evidence side + Analyst statistics side |

### 📝 Resume — single-shot generation, two-tier review, one coach

| Agent | Role | Architecture |
|---|---|---|
| **Customiser** | Achievement bank + JD + accumulated feedback → company-tailored resume | **Single-shot, layout-as-code**: the customiser only outputs structured content JSON; layout and identity (name / contact) are rendered by fixed code — style drift and identity fabrication are impossible by construction. The automatic multi-round revision loop was removed after experiments: no external information enters the loop, so extra rounds never converged and only multiplied latency and cost. Improvement comes from persistently accumulated feedback — every version is regenerated whole from bank + JD + the full feedback history |
| **Evaluator duo** | Quality gate: separates "agent can fix it" from "needs material only the user has" | ① **Recruiter blind review** — its information set is deliberately just resume + JD, simulating the HR reader across the table; ② **Coach triage** — checks findings against the achievement bank to split agent-fixable vs. needs-user-input, discipline: "search the bank before asking the user". Triggered manually on demand, so it never taxes generation; judges run on a dedicated eval tier; zero-LLM hard checks up front (sensitive phrasing, PDF page count — layout is code-fixed, so no master-template diffing needed anymore) |
| **Resume coach (quartermaster)** | Conversational intake: catches, classifies, and archives whatever the user throws in | Three-way classification (fact / opinion / reply): facts are archived to specific bank entries (proposal-confirmed, append-only); opinions join the persistent feedback set and apply to every subsequent version |

### ⚙️ Operations — turn chores into drafts and proposals

| Agent | Role | Architecture |
|---|---|---|
| **Scout / Sourcing** | Email, pasted text, multi-source signals → standardized opportunity proposals into the pool | flash-tier extraction; discipline: null when unknown, never guess |
| **Scribe** | Interview transcripts / PDFs → fields + body + battle-status proposals | Proposal-based: nothing is written back until approved in the review queue |
| **Prep** | Pre-interview brief built around situation assessment + what to do next, readable in 10 minutes | LLM judgment over the full battle state (timeline / JD / due diligence / assessment / achievement bank / playbook), prioritizing recent timeline retros and the other side's feedback as evidence; **user gold standards frozen into an eval** (brief_eval: length budget / no list-dumping / Q&A quota / hallucinated ammo IDs), with quotas hard-enforced in code; red-line content is pointed to, never copied; degrades to a template skeleton if the LLM is down |
| **Coordinator** | Pasted interview invitation → candidate slots → recommendation + reply draft (the user sends it) | Slot extraction uses an LLM; scheduling judgment is **pure rules** (constraints checked against the calendar) |
| **Referral matcher** | Contact map → referrer recommendations + outreach draft (the user sends it) | Text retrieval + flash-tier selection |

### 🛡️ Guard (cross-cutting) — every outbound artifact is inspected

| Agent | Role | Architecture |
|---|---|---|
| **Sentinel** | Uniform inspection of everything that leaves the system, no bypass | Two layers: a **rule layer** catches phrasing red lines and format violations; a **judgment layer** (LLM) handles what rules can't — narrative timing, cross-material consistency, semantic drift |

### Design notes

- **Loop patterns are chosen by evidence**: Diligence runs multi-turn ReAct — every search round brings in external information; resume customisation is single-shot — its information set is closed, and automatic multi-round revision never converged in practice. It was demoted from ReAct to self-refine to single-shot, each step backed by A/B experiments (see `evals/`).
- **Generation / evaluation separation**: each production line has its own Evaluator; judges run on a dedicated `model_eval` tier + blind review with randomized mapping + zero-LLM hard checks — three defenses against same-family favoritism.
- **Three model tiers**: pro for judgment, flash for extraction/matching (~1/25 the price), eval for judges — the judge is never weaker than the tier that produced the artifact.
- **Spend nothing where judgment isn't needed**: scheduling rules, hard checks, red-line card assembly, and resume layout rendering are zero-LLM.

## License

[Apache-2.0](LICENSE)
