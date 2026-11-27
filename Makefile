.PHONY: install test migrate run status

export PYTHONPATH := src
JOBSERVICE_DB ?= var/jobservice.db
export JOBSERVICE_DB

install:
	python -m pip install -r requirements-dev.txt

test:
	python -m pytest

migrate:
	python -m jobservice migrate

status:
	python -m jobservice status

run: migrate
	python -m jobservice serve
