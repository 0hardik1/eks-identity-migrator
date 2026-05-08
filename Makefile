.PHONY: help install ci-bootstrap fmt fmt-check lint typecheck test coverage-gate verify integration bootstrap-integration clean

PY := uv run
COVERAGE_OVERALL_MIN := 60
COVERAGE_CORE_MIN := 80
COVERAGE_CORE_INCLUDE := src/eks_identity_migrator/policy/*,src/eks_identity_migrator/risk/*,src/eks_identity_migrator/plan/*

help:
	@echo "make install            - install dev dependencies via uv sync"
	@echo "make ci-bootstrap       - install with frozen lockfile (CI)"
	@echo "make verify             - fmt-check + lint + typecheck + test + coverage gates"
	@echo "make fmt                - auto-format with ruff"
	@echo "make fmt-check          - check formatting"
	@echo "make lint               - ruff check"
	@echo "make typecheck          - mypy --strict"
	@echo "make test               - pytest (excludes integration)"
	@echo "make coverage-gate      - enforce coverage thresholds"
	@echo "make integration        - run integration tests (requires kind+localstack)"
	@echo "make bootstrap-integration - install kind, kubectl, pull localstack image"
	@echo "make clean              - remove caches and build artifacts"

install:
	uv sync --all-extras --dev

ci-bootstrap:
	uv sync --frozen --all-extras --dev

fmt:
	$(PY) ruff format .

fmt-check:
	$(PY) ruff format --check .

lint:
	$(PY) ruff check .

typecheck:
	$(PY) mypy

test:
	$(PY) pytest

coverage-gate:
	$(PY) coverage report --fail-under=$(COVERAGE_OVERALL_MIN)
	$(PY) coverage report --include='$(COVERAGE_CORE_INCLUDE)' --fail-under=$(COVERAGE_CORE_MIN)

verify: fmt-check lint typecheck test coverage-gate
	@echo "verify: all checks passed"

integration:
	$(PY) pytest test/integration -v -m integration --no-cov

bootstrap-integration:
	@echo "Installing kind..."
	@command -v kind >/dev/null 2>&1 || ( \
		curl -fsSL -o /tmp/kind https://kind.sigs.k8s.io/dl/v0.24.0/kind-linux-amd64 && \
		chmod +x /tmp/kind && \
		sudo mv /tmp/kind /usr/local/bin/kind \
	)
	@echo "Installing kubectl..."
	@command -v kubectl >/dev/null 2>&1 || ( \
		curl -fsSL -o /tmp/kubectl https://dl.k8s.io/release/v1.31.0/bin/linux/amd64/kubectl && \
		chmod +x /tmp/kubectl && \
		sudo mv /tmp/kubectl /usr/local/bin/kubectl \
	)
	@echo "Pulling localstack..."
	docker pull localstack/localstack:3.8
	@echo "Bootstrap complete. Run 'make integration'."

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
