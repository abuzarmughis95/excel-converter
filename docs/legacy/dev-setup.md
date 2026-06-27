# Development Environment Setup

## Prerequisites

- Node.js 20.x
- npm 10.x
- Python 3.12
- Docker and Docker Compose (optional for containerized development)

## Getting started

1. Install dependencies for all JavaScript packages:

   ```bash
   npm install
   ```

2. Install backend Python dependencies:

   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate  # macOS/Linux
   .\.venv\Scripts\activate # Windows
   pip install -r requirements.txt
   ```

3. Run the backend locally:

   ```bash
   cd backend
   alembic upgrade head
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

4. Run the frontend locally:

   ```bash
   cd frontend
   npm run dev
   ```

5. Run the desktop shell locally:

   ```bash
   cd desktop-app
   npm run dev
   ```

## Docker

Start the primary services with Docker Compose:

```bash
docker compose up --build
```

## Tests

Run all test suites from the repository root:

```bash
npm test
```

Or run tests individually:

- `cd frontend && npm test`
- `cd desktop-app && npm test`
- `cd backend && pytest`
