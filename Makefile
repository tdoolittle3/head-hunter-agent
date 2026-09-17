.PHONY: help install dev agents test lint format check eval

help:  ## Show this help
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  make %-10s %s\n", $$1, $$2}'

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

eval:  ## Run the ADK eval set against the fixture profile (needs a GCP project)
	@echo "Requires: pip install 'google-adk[eval]'"
	@rm -rf head_hunter/evals/fixture_data/fit_reports
	PYTHONPATH=. HH_DATA_DIR=head_hunter/evals/fixture_data adk eval head_hunter head_hunter/evals/blocker_detection.evalset.json --config_file_path head_hunter/evals/test_config.json

check: lint test  ## Everything that must pass before opening a PR
