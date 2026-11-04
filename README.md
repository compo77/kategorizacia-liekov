# Medicine Price Comparison for ATC B01AB05

A simple web application with no database. It finds the two most recent lists of categorized medicines in the archive of the Slovak Ministry of Health, downloads their Excel files, and compares medicine prices and patient co-payments for the selected ATC group. Available groups and the default selection are defined in `config/atc_groups.yaml`; adding a group to this file automatically makes it available in the selector. Data is kept only in process memory for four hours. If the source is temporarily unavailable, the running process retains the last successful result.

For example, a direct link to nadroparin is `/?atc=B01AB06`.

Add another group under `groups` in `config/atc_groups.yaml`:

```yaml
groups:
  B01AB99:
    name: Medicine name
```

Keep the other groups in the existing file and set `default` to one of the configured codes. After editing the YAML file, restart the local application. For Cloud Run, build and deploy a new image.

## Project Structure

```text
.
├── .dockerignore
├── .github/
│   └── agents/
│       └── lieky-local-runner.agent.md
├── .gitignore
├── .pre-commit-config.yaml
├── Dockerfile
├── Makefile
├── README.md
├── app.py
├── config/
│   └── atc_groups.yaml
├── medicine_comparison/
│   ├── __init__.py
│   ├── config.py
│   ├── service.py
│   └── source.py
├── pyproject.toml
├── requirements.txt
├── static/
│   ├── app.js
│   └── style.css
├── templates/
│   └── index.html
└── tests/
    └── test_comparison.py
```

- `app.py` creates the Flask application, handles web requests, and formats displayed prices.
- `config/atc_groups.yaml` defines the available ATC groups and default selection; `medicine_comparison/config.py` loads and validates it.
- `medicine_comparison/source.py` finds Ministry of Health lists, downloads their Excel files, and extracts medicine data.
- `medicine_comparison/service.py` matches medicines between lists, calculates price and co-payment changes, and caches results for four hours.
- `templates/index.html`, `static/app.js`, and `static/style.css` provide the comparison page, in-table search, and styling.
- `tests/test_comparison.py` covers configuration, spreadsheet parsing, comparisons, page rendering, and the health endpoint.
- `pyproject.toml` defines the runtime dependency set and the local development dependency group used for linting, type checking, formatting, and tests.
- `.pre-commit-config.yaml` runs the local code-quality checks before commit/push.
- `Dockerfile` builds and runs the app on Cloud Run; `requirements.txt` is a generated minimal runtime dependency file for deployment.

## Local development with uv

Python 3.13+ and [uv](https://docs.astral.sh/uv/) are required.

```sh
make dev
```

This installs the project’s runtime dependencies plus local developer tooling such as `ruff`, `black`, `mypy`, and `pytest` without polluting the production image.

Run the app locally:

```sh
make run
```

The application will be available at `http://localhost:8080`. The first page load downloads spreadsheets from the Ministry's website.
The listings page defaults to `https://www.health.gov.sk/odbornik/kategorizacia-a-cenotvorba/kategorizacia-liekov/zoznam-kategorizovanych-liekov/`.
To use a different page, set `MINISTRY_LISTINGS_URL` in the app's environment before starting it.

## Build and run the production Docker image locally

Docker is required. On macOS with Colima, start the Docker daemon first:

```sh
colima start
```

Build and run the production image:

```sh
make docker-build
make docker-run
```

The container is bound to `127.0.0.1:8082`; check it from another terminal with:

```sh
make docker-check
```

`docker-run` runs in the foreground and removes the container when stopped. Override the image tag or host port as needed, for example `make docker-build IMAGE=my-app:local` or `make docker-run DOCKER_PORT=8083`.

## Quality checks

```sh
make lint
make typecheck
make test
.venv-dev/bin/ruff format --check .
.venv-dev/bin/black --check .
```

Optional local hook setup:

```sh
.venv-dev/bin/pre-commit install
```

## Minimal deployment dependencies

The project keeps a minimal runtime dependency file for deployment. Regenerate it as needed with:

```sh
uv export --no-dev --format requirements-txt > requirements.txt
```

This file is intended for Cloud Run or other production deployments. It does not include local-only quality tools, which stay in the `dev` dependency group defined in `pyproject.toml`.

## Google Cloud Run

Create a Docker repository in Artifact Registry and set the required variables:

```sh
gcloud artifacts repositories create lieky \
  --repository-format=docker --location=REGION
make cloud-build CLOUD_REGION=REGION CLOUD_PROJECT=PROJECT_ID
make cloud-deploy CLOUD_REGION=REGION CLOUD_PROJECT=PROJECT_ID
make cloud-check CLOUD_REGION=REGION
```

Create the Artifact Registry repository only once. Authenticate with `gcloud auth login` and set the active project with `gcloud config set project PROJECT_ID`; Docker must also be configured to authenticate to Artifact Registry. The Make targets default to that active project, region `europe-west1`, repository `lieky`, image `kategorizacia-liekov:latest`, and the existing Cloud Run service `b01ab05`. Override these values as needed. `make cloud-build` uses local Docker Buildx to build a Cloud Run-compatible `linux/amd64` image and push it to Artifact Registry; the account needs Artifact Registry write permission. The service name remains `b01ab05` to update the existing service; the Artifact Registry image uses the project name. The deploy account needs permission to deploy Cloud Run services. The container listens on the `PORT` set automatically by Cloud Run; `make cloud-check` checks the `/status` endpoint. Adding a group to the YAML file does not require changing the Python code; include the updated configuration in a new image.

## Data Notes

The table shows the final price, the official reimbursement price (ÚZP), and the patient co-payment (DOP) from the Ministry of Health's Excel list. The displayed co-payment is the value listed for the entire package. The latest list may be marked as informational; the periods and original files are linked in the application header.