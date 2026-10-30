.DEFAULT_GOAL := help

PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python

.PHONY: all build check clean help lint test

all: build ## Собрать каталог.

$(VENV)/.ready: requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install -r requirements.txt
	@touch $@

build: $(VENV)/.ready ## Собрать сайт и каталог Homebrew Channel в _site/.
	$(VENV_PYTHON) scripts/build.py

test: $(VENV)/.ready ## Запустить тесты генератора.
	$(VENV_PYTHON) -m unittest discover -s tests

lint: ## Проверить Makefile с помощью checkmake.
	checkmake --config checkmake.ini Makefile

check: test lint ## Запустить тесты и проверить Makefile.

clean: ## Удалить результат сборки.
	rm -rf -- _site

help: ## Показать доступные команды.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-12s %s\n", $$1, $$2}' $(firstword $(MAKEFILE_LIST))
