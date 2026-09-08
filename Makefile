# =============================================================================
# Legafy AI — developer & operations entrypoints
# =============================================================================

.PHONY: help install lint fmt test audit validate validate-live run smoke mcp build up up-host up-full down logs ps tunnel bootstrap clean audit-verify watch taxonomy

VENV        ?= .venv
# Interpreter used to CREATE the venv. Python 3.11-3.14 all work: every pin is
# pure Python except pydantic-core, which ships cp314 wheels. Override only if
# your default python3 is older than 3.11:  make install PY=python3.12
PY          ?= python3
PYTHON      ?= $(VENV)/bin/python
PIP         ?= $(VENV)/bin/pip

help: ## Show this help
	@echo "Legafy AI — available targets:"
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create a venv and install runtime + dev dependencies
	$(PY) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt

lint: ## Run ruff check
	$(VENV)/bin/ruff check .

fmt: ## Run ruff format
	$(VENV)/bin/ruff format .

test: ## Run the pytest suite
	$(VENV)/bin/pytest -q

audit: ## Scan pinned dependencies for published advisories
	$(PIP) install -q pip-audit
	$(VENV)/bin/pip-audit -r requirements.txt

validate: ## Validate plugin manifests, tool schemas and client config examples
	$(PYTHON) scripts/validate_integration.py

validate-live: ## Validate, then run a real MCP initialize / tools/list / tools/call
	$(PYTHON) scripts/validate_integration.py --live

run: ## Run the API locally with autoreload
	$(VENV)/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

smoke: ## End-to-end smoke test against a running instance
	./scripts/smoke_test.sh

mcp: ## Run the MCP stdio server
	$(PYTHON) -m app.mcp.server

build: ## Build the Docker image
	docker compose build

up: ## Bring up the default stack (api + cloudflared, bridge networking)
	docker compose up -d --build

up-host: ## Bring up the stack with cloudflared on host networking (Linux CPU server)
	docker compose -f docker-compose.yml -f docker-compose.host.yml up -d --build

up-full: ## Bring up the full stack including redis (--profile full)
	docker compose --profile full up -d --build

down: ## Stop and remove the stack
	docker compose down

logs: ## Tail logs for all services
	docker compose logs -f --tail=200

ps: ## Show running services
	docker compose ps

tunnel: ## Run the Cloudflare Tunnel setup automation
	./setup_tunnel.sh

bootstrap: ## One-shot host preparation (dirs, .env, secrets, license seed)
	./scripts/bootstrap.sh

clean: ## Remove caches only — NEVER touches generated/ (that's the audit vault + runtime output; it is bind-mounted and must survive `make clean`)
	rm -rf .ruff_cache .pytest_cache .coverage htmlcov dist build *.egg-info
	find . -type d -name '__pycache__' -not -path './generated/*' -exec rm -rf {} +

watch: ## Crawl watched primary sources and refresh the review queue
	$(PYTHON) -m app.sources.watcher

taxonomy: ## What people actually ask (from the opt-in question corpus)
	$(PYTHON) -c "import json; from app.search.corpus import get_corpus; print(json.dumps(get_corpus().taxonomy(), indent=2))"

audit-verify: ## Verify the append-only audit vault's hash chain is intact
	$(PYTHON) -c "from app.security.telemetry import get_audit_vault; result = get_audit_vault().verify_chain(); print(result); raise SystemExit(0 if result else 1)"
