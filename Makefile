.DEFAULT_GOAL := help

PYTHON ?= python3

.PHONY: all build check clean help lint test

all: build ## Собрать каталог.

build: ## Собрать сайт и каталог Homebrew Channel в _site/.
	$(PYTHON) scripts/build.py

test: ## Запустить тесты генератора.
	$(PYTHON) -m unittest discover -s tests

lint: ## Проверить Makefile с помощью checkmake.
	checkmake Makefile

check: test lint ## Запустить тесты и проверить Makefile.

clean: ## Удалить результат сборки.
	rm -rf -- _site

help: ## Показать доступные команды.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-12s %s\n", $$1, $$2}' $(firstword $(MAKEFILE_LIST))
