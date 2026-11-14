.DEFAULT_GOAL := help

PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python

.PHONY: all build check clean freeze help lint python-lint sync test venv workflow-lint

all: build ## Собрать каталог.

$(VENV)/.ready: requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install -r requirements.txt
	@touch $@

venv: $(VENV)/.ready ## Создать .venv и поставить зависимости.

build: $(VENV)/.ready ## Собрать сайт и каталог Homebrew Channel в _site/.
	$(VENV_PYTHON) scripts/build.py

sync: $(VENV)/.ready ## Скачать свежие сторонние IPK из remote-packages.json.
	$(VENV_PYTHON) scripts/sync_remote.py

test: $(VENV)/.ready ## Запустить тесты генератора.
	$(VENV_PYTHON) -m unittest discover -s tests

lint: ## Проверить Makefile с помощью checkmake.
	checkmake --config checkmake.ini Makefile

python-lint: $(VENV)/.ready ## Проверить Python-код с помощью Ruff.
	$(VENV)/bin/ruff check scripts tests

workflow-lint: $(VENV)/.ready ## Проверить безопасность GitHub Actions.
	$(VENV)/bin/zizmor $(ZIZMOR_FLAGS) .github/workflows

check: test lint python-lint ## Запустить тесты и проверки кода.

freeze: ## Зафиксировать версии прямых зависимостей из .venv.
	@if [ ! -x $(VENV_PYTHON) ]; then $(MAKE) $(VENV)/.ready; fi
	$(VENV_PYTHON) scripts/freeze.py $(PACKAGES)

clean: ## Удалить результат сборки.
	rm -rf -- _site

help: ## Показать доступные команды.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-12s %s\n", $$1, $$2}' $(firstword $(MAKEFILE_LIST))
