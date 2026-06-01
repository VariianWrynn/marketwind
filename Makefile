# Host-facing defaults for commands run outside containers (override via env).
DATABASE_URL ?= postgresql://marketwind:marketwind@localhost:5432/marketwind
REDIS_URL ?= redis://localhost:6379/0
export DATABASE_URL
export REDIS_URL

.PHONY: dev test migrate lint-sql test-gt eval-prompt

dev:
	docker compose up --build

test:
	pytest

migrate:
	python -m marketwind.storage.migrate

lint-sql:
	sqlfluff lint migrations

test-gt:
	@echo "test-gt: not implemented until P2" && exit 1

eval-prompt:
	@echo "eval-prompt: not implemented until P2" && exit 1
