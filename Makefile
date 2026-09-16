.PHONY: help install dev agents test lint format check

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

check: lint test  ## Everything that must pass before opening a PR
