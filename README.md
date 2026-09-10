# AI-Interview-Coach

An AI-powered technical interview coach built with FastAPI and a static frontend. It simulates an interview loop, records candidate answers, evaluates them with Claude, and produces a final report.

## Run modes

This project supports two runtime modes:

### 1) Docker mode: safe demo mode

This is the default behavior in Docker.

```bash
cd /Users/shreyaravibabu/Projects/AI-Interview-Coach
docker compose up --build
```

What happens in Docker mode:
- `USE_DEMO_MODE=true` is enforced by the Docker setup
- the app does not require live Anthropic or ElevenLabs credentials
- it uses deterministic canned questions and canned evaluation responses
- the UI still works end-to-end for demos and walkthroughs
- it prevents accidental API usage and cost leakage during presentations

This is the recommended mode for:
- demos
- interviews
- public walkthroughs
- local testing without billing risk

### How demo mode works

In demo mode, the app intentionally avoids live external model calls. Instead it:
- returns fixed sample interview questions
- returns deterministic evaluation scores and feedback
- generates silent audio placeholders so the frontend can still play the interview flow
- keeps the app fully functional without requiring secrets

This is important because it lets the app behave like a polished product even when no API keys are configured.

### 2) Local live mode: real AI-powered interview

If you want the full version with real model calls, run the app locally without Docker and add the required keys in [backend/.env](backend/.env).

Example:

```bash
cd backend
cp .env.example .env
# edit .env and add your real keys
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Then serve the frontend:

```bash
cd ../frontend
python3 -m http.server 8080
```

Open http://localhost:8080 in the browser.

In live mode:
- Anthropic generates interview questions and evaluates answers
- ElevenLabs converts the interviewer question to speech and transcribes the candidate answer
- the app uses real model behavior and real audio processing
- you get the production-like AI interview loop instead of the demo fallback

### Demo vs live mode

| Mode | API keys required | Model calls | Cost risk | Best for |
| --- | --- | --- | --- | --- |
| Docker demo mode | No | No | None | Demos, interviews, safe walkthroughs |
| Local live mode | Yes | Yes | Yes | Real functionality and full experience |

The app automatically chooses safe behavior by default so users are not forced into paying for AI usage during demos.

## Local development

1. Create a virtual environment in the backend folder.
2. Install dependencies:
   ```bash
   cd backend
   python -m pip install -r requirements.txt
   python -m pip install -r requirements-dev.txt
   ```
3. Copy the example env file and configure your keys:
   ```bash
   cp .env.example .env
   ```
4. Start the API:
   ```bash
   uvicorn main:app --host 127.0.0.1 --port 8000 --reload
   ```
5. Serve the frontend from the frontend folder:
   ```bash
   cd ../frontend
   python -m http.server 8080
   ```
6. Open http://localhost:8080 in the browser.

## Deployment options

### Recommended free option: Render

This is the best free option for a portfolio-grade deployment because it gives you:
- a real public HTTPS URL
- easy Docker-based app hosting
- separate frontend and backend deployment flow
- a production-like deployment story you can discuss in interviews

#### Deploying the API

1. Push this repository to GitHub.
2. Create a new Render Web Service.
3. Connect it to the repo.
4. Set the root directory to `backend` and use the included Dockerfile.
5. Add environment variables from `.env.example`.
6. Keep the Web Service port at 8000.

#### Deploying the frontend

1. Create a static site on Render.
2. Set the root directory to `frontend`.
3. Publish the folder as-is.
4. Update the deployed backend URL if needed in `frontend/index.html`.

### Alternative free option: Railway or Fly.io

These also work well for Python apps, but Render is simpler and historically easier for a free-tier deployment story.

## Why this deployment path is FAANG-worthy

This demonstrates real-world engineering judgment:
- production API deployment
- environment-driven configuration
- separate frontend/backend concerns
- WebSocket-based interaction over a public endpoint
- cloud deployment readiness and operational awareness

That is much stronger than a purely local demo and maps well to the kind of systems thinking interviewers look for.

## Project structure

- `backend/` — FastAPI API, interview logic, SQLite persistence
- `frontend/` — static HTML/JS interview UI
- `render.yaml` — free deployment manifest for Render
- `backend/Dockerfile` — container definition for the API
