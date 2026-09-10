# Technical Architecture README

## 1. System overview

This project is an AI-powered interview coaching application with three major layers:

1. Frontend UI
   - A static JavaScript app served from the frontend folder.
   - It collects candidate metadata, starts interviews, and handles the live interview loop over WebSockets.

2. Backend API
   - Built with FastAPI.
   - Manages interview sessions, stores configuration, and orchestrates the AI flow.
   - Validates request payloads and handles WebSocket state transitions.

3. Persistence and AI services
   - SQLite stores interview sessions and answer records.
   - Anthropic handles question generation and answer evaluation.
   - ElevenLabs provides TTS and speech-to-text capability when live mode is enabled.

The architecture is intentionally simple and intentionally product-shaped: small enough to explain in a portfolio, but strong enough to show engineering discipline around reliability, validation, and fallback behavior.

---

## 2. Architecture decisions

### Frontend

The frontend is intentionally static and lightweight:
- no framework lock-in
- easy to host on a CDN or static hosting service
- simple browser-based interactions
- WebSocket communication to the API for the interview loop

Trade-off:
- this is easy to deploy and demo, but it is not as extensible as a React/Next app for large-scale product complexity.
- for a portfolio project, the simpler frontend is an advantage because it keeps the system easier to reason about.

### Backend

The backend is the orchestration layer. It performs three key jobs:
- validates interview configuration
- manages interview lifecycle and state transitions
- calls AI providers and stores results

The FastAPI app exposes:
- a health endpoint
- a WebSocket route for the live interview
- a session retrieval API for persisted sessions

Trade-off:
- a monolithic backend is simpler and easier to explain in interviews
- it does not scale as a multi-service platform, but it is appropriate for a portfolio-grade demo app

### Persistence

The persistence layer is SQLite. This is a deliberate trade-off:
- low operational overhead
- no external database required for local or demo use
- enough structure to demonstrate real session tracking and stateful behavior

Trade-off:
- SQLite is not the best choice for a multi-tenant production system at very large scale
- however, for a portfolio app, it shows correct engineering patterns around transactions, sessions, and stored evaluation history

---

## 3. Interview flow

The core flow is:

1. User enters candidate metadata and interview config.
2. Frontend connects to the WebSocket route.
3. Backend validates role, topic, difficulty, and persona.
4. Backend creates a new session record.
5. Backend generates the first question.
6. Backend converts the question to audio and sends it to the frontend.
7. User records a spoken answer.
8. Backend transcribes the answer, evaluates it, and stores the result.
9. It repeats through the configured question count.
10. Final report is generated and persisted.
11. Session can be retrieved later through the session endpoint.

This is a realistic end-to-end application workflow, not just a prompt wrapper.

---

## 4. Prompt versioning and eval strategy

The app includes a small prompt-versioning layer so prompt changes are not left implicit.

Each prompt is treated as a versioned artifact with:
- a name
- a version tag
- a template
- a runtime context for rendering

This matters because in real AI products, prompt quality is not “one-off text” — it is a versioned artifact that needs regression checks and comparison.

The accompanying eval harness allows you to:
- define benchmark cases
- check whether outputs contain expected themes and structure
- compare prompt quality across versions
- measure changes with a repeatable score

This is a strong FAANG-style signal because it demonstrates awareness of AI reliability engineering, not just prompting.

---

## 5. Failure modes and resilience

### Missing or invalid API keys

The app is designed to avoid hard crashes when credentials are absent or placeholder values remain in the environment.

If keys are missing, the app gracefully falls back to demo mode.

Why this matters:
- public demos should not fail because of missing secrets
- developers can still build and test without paying for live model calls
- deployment is safer and more interview-friendly

### Docker vs local execution

The app is configured so that Docker defaults to demo mode, while local execution can use live AI mode when valid keys are set.

This prevents the common failure mode of a containerized demo unexpectedly trying to call paid external services during a presentation.

### WebSocket mismatch and port collisions

A major runtime issue in local development is when the frontend and backend are served on the same port or when the frontend resolves the wrong host.

The app handles this by making host selection explicit and by assuming the standard backend path is localhost:8000 when running locally.

This is important for debugging because network issues are often mistaken for app-level logic issues.

### Invalid user input

Interview config is validated before session creation. This prevents invalid states like:
- missing topic
- unsupported difficulty
- unsupported persona
- empty candidate name

The app raises structured errors rather than allowing broken state into the database.

### AI provider failure

If model calls fail or return malformed output, the app has fallbacks:
- demo data generation
- normalized evaluation parsing
- generic safe feedback

This makes the app more robust in real deployments and reduces the impact of model instability.

---

## 6. Why this is FAANG-worthy

This project demonstrates the kind of thinking that strong engineering teams value:

- service-oriented backend design
- state management across a multi-step workflow
- persistence and retrieval of user data
- validation and error handling
- clear deployment strategy
- AI safety through demo mode and fallbacks
- prompt versioning and evaluation discipline
- operational awareness around failure modes

This is significantly stronger than a basic demo because it shows product thinking, engineering judgment, and software reliability discipline.

---

## 7. Suggested interview talking points

A strong interview explanation could be:

> I built a production-style AI interview coach where the backend validates inputs, persists interview sessions in SQLite, records all candidate answers and evaluations, and exposes a retrieval API for later review. I also added prompt versioning and a lightweight eval harness so prompt changes are tracked and measured instead of being ad hoc. The app is designed to fail gracefully: it supports demo mode for safe public demos, live mode when credentials are present, and explicit fallback paths when providers are unavailable.

That communicates both product understanding and engineering maturity.

---

## 8. System design write-up

### Goals

The product goal is to let a user practice technical interviews in a realistic multi-step flow while preserving operational safety and interview-grade engineering quality.

The system is designed around a few practical constraints:
- it must be easy to run locally
- it must be safe for demos without exposing real secrets
- it must support a live AI interview loop without creating a brittle backend
- it must persist the entire interview lifecycle for review and debugging

### High-level design

The system is a small client-server application with the following components:

1. Browser client
   - form-driven setup
   - WebSocket-based interview loop
   - audio recording and playback
   - evaluation rendering

2. FastAPI service
   - handles interview orchestration
   - validates runtime inputs
   - calls external AI APIs
   - persists session state and evaluation artifacts

3. SQLite database
   - stores sessions and answer records
   - enables session retrieval and auditing

4. External AI providers
   - Anthropic for reasoning and evaluation
   - ElevenLabs for voice synthesis and STT when live features are enabled

### Data model

The data model is intentionally simple but realistic:

- Session record:
  - id
  - role
  - difficulty
  - topic
  - persona_type
  - candidate_name
  - status
  - created_at
  - updated_at
  - final_report

- Answer record:
  - id
  - session_id
  - question_number
  - question
  - answer
  - evaluation
  - created_at

This allows the system to answer questions like:
- what was the candidate’s interview history?
- what questions were asked?
- what was the score per question?
- what was the final recommendation?

### Scaling and trade-offs

This is not designed as a distributed ML system. It is deliberately built as a vertical slice of a real product:

- one API service
- one database
- direct calls to model providers
- short-lived in-browser UI state

This is a strong trade-off for a portfolio project because it keeps the system explainable while still demonstrating real product engineering decisions.

If the project were to scale later, the natural next steps would be:
- move to PostgreSQL
- introduce authenticated user sessions
- add queue-based async processing for slow model calls
- separate analytics and model orchestration into different services

### Reliability design

The core reliability principles are:
- validate before processing
- persist state early and often
- avoid hard dependency on external credentials in demo mode
- fail with safe defaults rather than crashing the entire interview

These are classic system-design concerns and they map directly to what senior engineers talk about in interviews: correctness, resilience, and graceful degradation.

### Failure analysis

The most likely failure points are:
- invalid or missing API keys
- WebSocket disconnects
- model provider latency or errors
- voice transcription failures
- port conflicts in local development

The app handles these by:
- using demo mode as a safe fallback
- preserving session records even when an interview partially fails
- returning structured error messages
- validating configuration before state becomes inconsistent

### Interviewer framing

A clear system-design answer for this project is:

> This is a small but realistic AI product architecture: a browser client communicates with a FastAPI backend over WebSockets, the backend orchestrates AI-driven question generation and evaluation, and SQLite persists interview sessions and answer records for retrieval and debugging. The design emphasizes safety, resilience, and traceability over raw complexity, which is a good production-minded trade-off for a portfolio project.

---

## 9. Future improvements

If this project were extended further, the next realistic steps would be:

- move from SQLite to PostgreSQL for production scale
- add authentication and user accounts
- add analytics dashboards for interview outcomes
- add model A/B comparisons using prompt versioning
- add CI gates around eval results and regression tests
- add deployment health checks and observability

Those are all natural next steps in a FAANG-style AI product roadmap.
