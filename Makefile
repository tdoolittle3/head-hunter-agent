.PHONY: help install dev serve agents test lint format check eval \
        enable-apis deploy-test deploy-prod

# --- Deploy settings. Override on the command line, e.g.
# ---   make deploy-test TEST_PROJECT=my-test-project
REGION      ?= us-central1
TEST_PROJECT ?=
PROD_PROJECT ?=
TEST_SERVICE ?= head-hunter-test
PROD_SERVICE ?= head-hunter

# Only set this if your project does not serve the default model.
MODEL ?=

# Cloud Run runs the signed-in server in the Dockerfile, not `adk web`.
#
# --set-env-vars REPLACES the service's whole environment; --update-env-vars
# would merge into it. That is deliberate: the old `adk web` deployment carried
# HH_SINGLE_USER, which pins everybody to one profile, and the server refuses to
# start if it is still there. Replacing the set guarantees it is gone.
#
# The service is public (--allow-unauthenticated) because the app, not Cloud Run
# IAM, decides who is in: every API route needs a verified Firebase token. That is
# only safe with the signed-in server, which is why it is never combined with
# `adk web`. The deploy workflow smoke-tests that anonymous chat is refused.
#
# --max-instances bounds the worst-case Gemini bill and multiplies the per-user
# limits in head_hunter/ratelimit.py; raise it deliberately, not casually.
MAX_INSTANCES ?= 3
RUN_FLAGS = --allow-unauthenticated             --max-instances=$(MAX_INSTANCES)             --concurrency=20             --memory=1Gi

# $(1) is the project. HH_DATA_DIR still points somewhere writable in case
# anything ever falls back to the JSON store: the container runs as a non-root
# user, and /app is root-owned.
run_env = GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=$(1),GOOGLE_CLOUD_LOCATION=$(REGION),HH_STORAGE=firestore,HH_DATA_DIR=/tmp/head-hunter-data$(if $(MODEL),$(comma)HH_MODEL=$(MODEL),)
comma := ,

help:  ## Show this help
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  make %-13s %s\n", $$1, $$2}'

install:  ## Install dependencies
	pip install -r requirements.txt

dev:  ## Start the web chat UI on port 8000
	adk web head_hunter

serve:  ## Start the signed-in API server on port 8080 (needs HH_SINGLE_USER unset)
	python -m uvicorn head_hunter.server:create_app --factory --port 8080

agents:  ## Start the web UI with every agent listed separately (for testing one alone)
	adk web head_hunter/agents

test:  ## Run the tests
	pytest

lint:  ## Check formatting and lint
	ruff check .
	ruff format --check .

format:  ## Reformat the code
	ruff format .
	ruff check --fix .

eval:  ## Run the ADK eval sets against the fixture profile (needs a GCP project)
	@echo "Requires: pip install 'google-adk[eval]'"
	@# Cleared before EACH set, not once: the blocker run leaves a fit report
	@# behind, and the resume run would then read it. Each set must stand alone.
	@rm -rf head_hunter/evals/fixture_data/fit_reports head_hunter/evals/fixture_data/resumes
	PYTHONPATH=. HH_SINGLE_USER=local HH_DATA_DIR=head_hunter/evals/fixture_data adk eval head_hunter head_hunter/evals/blocker_detection.evalset.json --config_file_path head_hunter/evals/test_config.json
	@rm -rf head_hunter/evals/fixture_data/fit_reports head_hunter/evals/fixture_data/resumes
	PYTHONPATH=. HH_SINGLE_USER=local HH_DATA_DIR=head_hunter/evals/fixture_data adk eval head_hunter head_hunter/evals/no_invented_experience.evalset.json --config_file_path head_hunter/evals/test_config.json

check: lint test  ## Everything that must pass before opening a PR

enable-apis:  ## Turn on the Google Cloud APIs a deploy needs (once per project)
	@test -n "$(PROJECT)" || { echo "Usage: make enable-apis PROJECT=your-project-id"; exit 1; }
	gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
	  aiplatform.googleapis.com artifactregistry.googleapis.com --project=$(PROJECT)

deploy-test:  ## Deploy the signed-in server to the test Cloud Run service (public; app-level login)
	@test -n "$(TEST_PROJECT)" || { echo "Usage: make deploy-test TEST_PROJECT=your-test-project-id"; exit 1; }
	gcloud run deploy $(TEST_SERVICE) --source . 	  --project=$(TEST_PROJECT) --region=$(REGION) 	  --set-env-vars="$(call run_env,$(TEST_PROJECT))" 	  $(RUN_FLAGS)

deploy-prod:  ## Deploy the signed-in server to the production Cloud Run service. See README first.
	@test -n "$(PROD_PROJECT)" || { echo "Usage: make deploy-prod PROD_PROJECT=your-prod-project-id"; exit 1; }
	gcloud run deploy $(PROD_SERVICE) --source . 	  --project=$(PROD_PROJECT) --region=$(REGION) 	  --set-env-vars="$(call run_env,$(PROD_PROJECT))" 	  $(RUN_FLAGS) --min-instances=1
