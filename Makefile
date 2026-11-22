.PHONY: install test

install:
	python -m pip install -r requirements-dev.txt

test:
	python -m pytest
