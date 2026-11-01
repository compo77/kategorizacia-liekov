UV ?= uv
UV_PROJECT_ENVIRONMENT ?= .venv-dev
export UV_PROJECT_ENVIRONMENT
PYTHON := $(UV_PROJECT_ENVIRONMENT)/bin/python
PORT ?= 8080
DOCKER ?= docker
IMAGE ?= kategorizacia-liekov:local
DOCKER_PORT ?= 8082
CONTAINER_NAME ?= kategorizacia-liekov-local
CLOUD_PROJECT ?= $(shell gcloud config get-value project 2>/dev/null)
CLOUD_REGION ?= europe-west1
ARTIFACT_REPOSITORY ?= lieky
CLOUD_IMAGE_NAME ?= kategorizacia-liekov
CLOUD_IMAGE_TAG ?= latest
CLOUD_RUN_SERVICE ?= b01ab05
CLOUD_IMAGE := $(CLOUD_REGION)-docker.pkg.dev/$(CLOUD_PROJECT)/$(ARTIFACT_REPOSITORY)/$(CLOUD_IMAGE_NAME):$(CLOUD_IMAGE_TAG)

.PHONY: help setup dev production lint format typecheck test run docker-build docker-run docker-check cloud-build cloud-deploy cloud-check export-requirements

help:
	@printf '%s\n' \
	  'setup                Create the uv environment and install local dev dependencies' \
	  'dev                  Alias for setup with the development toolchain' \
	  'production           Create an isolated runtime-only environment' \
	  'lint                 Run ruff checks' \
	  'format               Format code with ruff and black' \
	  'typecheck            Run mypy' \
	  'test                 Run the test suite in the uv environment' \
	  'run                  Start Flask on 127.0.0.1 (PORT=8080 by default)' \
	  'docker-build         Build the production Docker image' \
	  'docker-run           Run the image on localhost:8082' \
	  'docker-check         Check the running image health endpoint' \
	  'cloud-build          Build linux/amd64 locally and push to Artifact Registry' \
	  'cloud-deploy         Deploy the image to the configured Cloud Run service' \
	  'cloud-check          Check the deployed Cloud Run health endpoint' \
	  'export-requirements  Generate a minimal production requirements.txt for deployment'

setup:
	$(UV) venv $(UV_PROJECT_ENVIRONMENT) --python 3.13
	$(UV) sync --group dev

dev: setup

production:
	$(UV) venv .venv-prod --python 3.13
	$(UV) pip install --python .venv-prod/bin/python -r requirements.txt

lint:
	$(UV) run ruff check .

format:
	$(UV) run ruff format .
	$(UV) run black .

typecheck:
	$(UV) run mypy .

test:
	$(UV) run pytest

run:
	PORT=$(PORT) $(PYTHON) -m flask --app app run --host 127.0.0.1 --port $(PORT)

docker-build:
	$(DOCKER) build -t $(IMAGE) .

docker-run:
	$(DOCKER) run --rm --name $(CONTAINER_NAME) -p 127.0.0.1:$(DOCKER_PORT):8080 $(IMAGE)

docker-check:
	curl --fail --show-error http://127.0.0.1:$(DOCKER_PORT)/status

cloud-build:
	$(DOCKER) buildx build --platform linux/amd64 --tag $(CLOUD_IMAGE) --push .

cloud-deploy:
	gcloud run deploy $(CLOUD_RUN_SERVICE) --image=$(CLOUD_IMAGE) --region=$(CLOUD_REGION) --platform=managed

cloud-check:
	@service_url="$$(gcloud run services describe $(CLOUD_RUN_SERVICE) --region=$(CLOUD_REGION) --format='value(status.url)')" && \
	  curl --fail --show-error "$$service_url/status"

export-requirements:
	$(UV) export --no-dev --format requirements-txt > requirements.txt