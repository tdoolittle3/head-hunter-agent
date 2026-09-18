.PHONY: help install dev agents test lint format check eval \
        enable-apis deploy-test deploy-prod proxy-test proxy-prod

# --- Deploy settings. Override on the command line, e.g.
# ---   make deploy-test TEST_PROJECT=my-test-project
REGION      ?= us-central1
TEST_PROJECT ?=
PROD_PROJECT ?=
TEST_SERVICE ?= head-hunter-test
PROD_SERVICE ?= head-hunter

# Only set this if your project does not serve the default model.
MODEL ?=

# Which browser origins may load the dev UI.
#
# Two landmines in `adk deploy cloud_run`, both of which produce a container
# that refuses every origin, so read before editing:
#
#  1. It joins repeated --allow_origins with a comma into ONE flag, and the
#     server never splits it back apart. Passing the flag twice allows a single
#     nonsense origin instead of two real ones. Hence one value, not a list --
#     a `regex:` pattern with alternation is the only way to allow two places.
#  2. It interpolates the value verbatim and UNQUOTED into a shell-form CMD in
#     the generated Dockerfile. A pattern containing ( ) or | is then read as
#     shell syntax and the container dies with a syntax error before it starts.
#
# The doubled quoting below is deliberate, not a typo: the outer "..." is eaten
# by this recipe's shell, so adk receives a value that still carries the single
# quotes, and the Dockerfile ends up with --allow_origins='regex:...' -- quoted,
# and safe for the CMD shell to hand to ADK intact.
#
# The default covers both ways in: `gcloud run services proxy` on a laptop
# (localhost:8080) and Cloud Shell Web Preview, whose host carries a per-session
# id and so can only be matched by pattern. The pattern is full-matched against
# the whole origin, so it does not match lookalikes like cloudshell.dev.evil.com.
#
# The dev UI is an Angular app loaded as ES modules, and module scripts are
# always fetched in CORS mode -- they carry an Origin header even same-origin.
# Miss an origin here and ADK answers every script with "403 Forbidden: origin
# not allowed", so the page renders as a blank shell. Stylesheets are not
# fetched in CORS mode and load fine, which makes it look stranger than it is.
#
# This is not the access control. The service is private and IAM decides who
# gets in; this list only decides whose browser can render the UI.
ALLOWED_ORIGINS ?= regex:(?:http://localhost:8080|https://.*\.cloudshell\.dev)

# The container runs as a non-root user in a root-owned /app, so the JSON store
# cannot live at the default ./data. /tmp is writable -- and wiped on every
# restart, which is exactly why this is a smoke test and not somewhere to keep
# a real career profile. Firestore (Phase 3) is what fixes that.
DEPLOY_ENV = --env GOOGLE_GENAI_USE_VERTEXAI=TRUE \
             --env HH_USER_ID=local \
             --env HH_DATA_DIR=/tmp/head-hunter-data \
             $(if $(MODEL),--env HH_MODEL=$(MODEL),)

help:  ## Show this help
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  make %-13s %s\n", $$1, $$2}'

install:  ## Install dependencies
	pip install -r requirements.txt

dev:  ## Start the web chat UI on port 8000
	adk web head_hunter

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
	PYTHONPATH=. HH_DATA_DIR=head_hunter/evals/fixture_data adk eval head_hunter head_hunter/evals/blocker_detection.evalset.json --config_file_path head_hunter/evals/test_config.json
	@rm -rf head_hunter/evals/fixture_data/fit_reports head_hunter/evals/fixture_data/resumes
	PYTHONPATH=. HH_DATA_DIR=head_hunter/evals/fixture_data adk eval head_hunter head_hunter/evals/no_invented_experience.evalset.json --config_file_path head_hunter/evals/test_config.json

check: lint test  ## Everything that must pass before opening a PR

enable-apis:  ## Turn on the Google Cloud APIs a deploy needs (once per project)
	@test -n "$(PROJECT)" || { echo "Usage: make enable-apis PROJECT=your-project-id"; exit 1; }
	gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
	  aiplatform.googleapis.com artifactregistry.googleapis.com --project=$(PROJECT)

deploy-test:  ## Deploy to the test Cloud Run service (private)
	@test -n "$(TEST_PROJECT)" || { echo "Usage: make deploy-test TEST_PROJECT=your-test-project-id"; exit 1; }
	adk deploy cloud_run \
	  --project=$(TEST_PROJECT) --region=$(REGION) \
	  --service_name=$(TEST_SERVICE) --with_ui \
	  --allow_origins="'$(ALLOWED_ORIGINS)'" \
	  $(DEPLOY_ENV) \
	  head_hunter -- --no-allow-unauthenticated

deploy-prod:  ## Deploy to the production Cloud Run service (private). See README first.
	@test -n "$(PROD_PROJECT)" || { echo "Usage: make deploy-prod PROD_PROJECT=your-prod-project-id"; exit 1; }
	adk deploy cloud_run \
	  --project=$(PROD_PROJECT) --region=$(REGION) \
	  --service_name=$(PROD_SERVICE) --with_ui \
	  --allow_origins="'$(ALLOWED_ORIGINS)'" \
	  $(DEPLOY_ENV) \
	  head_hunter -- --no-allow-unauthenticated --min-instances=1

proxy-test:  ## Open an authenticated tunnel to the test service on localhost:8080
	@test -n "$(TEST_PROJECT)" || { echo "Usage: make proxy-test TEST_PROJECT=your-test-project-id"; exit 1; }
	gcloud run services proxy $(TEST_SERVICE) --project=$(TEST_PROJECT) --region=$(REGION)

proxy-prod:  ## Open an authenticated tunnel to the production service on localhost:8080
	@test -n "$(PROD_PROJECT)" || { echo "Usage: make proxy-prod PROD_PROJECT=your-prod-project-id"; exit 1; }
	gcloud run services proxy $(PROD_SERVICE) --project=$(PROD_PROJECT) --region=$(REGION)
