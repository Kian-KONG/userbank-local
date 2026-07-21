# userbank-local — start FastAPI + Vite (laptop only)
#
#   make up      # api :8780 + web :5174
#   make down
#   make status / make logs
#
# Requires: uv (or python3 -m venv), node/npm for web/

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

ROOT := $(abspath .)
PID_DIR := $(ROOT)/.dev-pids
LOG_DIR := $(ROOT)/.dev-logs

API_HOST ?= 127.0.0.1
API_PORT ?= 8780
WEB_PORT ?= 5174
VITE_LOCAL_API ?= http://127.0.0.1:$(API_PORT)

.PHONY: help up down api web status logs install ensure-dirs kill

help:
	@echo "userbank-local"
	@echo ""
	@echo "  make install   Create .venv + install Python deps; npm install in web/"
	@echo "  make up        Start FastAPI (:$(API_PORT)) + Vite (:$(WEB_PORT))"
	@echo "  make down      Stop both"
	@echo "  make api       Start API only"
	@echo "  make web       Start Vite only"
	@echo "  make status / make logs"
	@echo ""
	@echo "Open http://127.0.0.1:$(WEB_PORT)  API http://$(API_HOST):$(API_PORT)/health"

ensure-dirs:
	@mkdir -p "$(PID_DIR)" "$(LOG_DIR)"

install:
	@cd "$(ROOT)" && \
	  if command -v uv >/dev/null 2>&1; then uv sync; \
	  else \
	    PY=python3.12; command -v $$PY >/dev/null || PY=python3; \
	    $$PY -m venv .venv && .venv/bin/pip install -U pip setuptools wheel && .venv/bin/pip install -e '.[dev]'; \
	  fi
	@cd "$(ROOT)/web" && npm install

api: ensure-dirs
	@if [[ -f "$(PID_DIR)/api.pid" ]] && kill -0 "$$(cat "$(PID_DIR)/api.pid")" 2>/dev/null; then \
		echo "api already running pid=$$(cat "$(PID_DIR)/api.pid")"; \
	else \
		echo "Starting API on $(API_HOST):$(API_PORT)..."; \
		( cd "$(ROOT)" && \
			if [[ -x .venv/bin/ub-local ]]; then BIN=.venv/bin/ub-local; \
			elif command -v uv >/dev/null; then BIN="uv run ub-local"; \
			else echo "run make install first"; exit 1; fi; \
			$$BIN serve --host $(API_HOST) --port $(API_PORT) ) \
			> "$(LOG_DIR)/api.log" 2>&1 & echo $$! > "$(PID_DIR)/api.pid"; \
		echo "  pid=$$(cat "$(PID_DIR)/api.pid") log=$(LOG_DIR)/api.log"; \
	fi

web: ensure-dirs
	@test -d "$(ROOT)/web/node_modules" || { echo "run: make install"; exit 1; }
	@if [[ -f "$(PID_DIR)/web.pid" ]] && kill -0 "$$(cat "$(PID_DIR)/web.pid")" 2>/dev/null; then \
		echo "web already running pid=$$(cat "$(PID_DIR)/web.pid")"; \
	else \
		echo "Starting web on :$(WEB_PORT)..."; \
		( cd "$(ROOT)/web" && \
			VITE_LOCAL_API=$(VITE_LOCAL_API) npm run dev -- --port $(WEB_PORT) --host 127.0.0.1 ) \
			> "$(LOG_DIR)/web.log" 2>&1 & echo $$! > "$(PID_DIR)/web.pid"; \
		echo "  pid=$$(cat "$(PID_DIR)/web.pid") log=$(LOG_DIR)/web.log"; \
	fi

up: api web
	@echo ""
	@echo "userbank-local up:"
	@echo "  web  http://127.0.0.1:$(WEB_PORT)"
	@echo "  api  http://$(API_HOST):$(API_PORT)/health"
	@echo "stop: make down"

dev: up

kill:
	@for name in api web; do \
		if [[ -f "$(PID_DIR)/$$name.pid" ]]; then \
			pid=$$(cat "$(PID_DIR)/$$name.pid"); \
			if kill -0 "$$pid" 2>/dev/null; then \
				echo "Stopping $$name pid=$$pid"; \
				kill "$$pid" 2>/dev/null || true; \
				sleep 0.3; \
				kill -9 "$$pid" 2>/dev/null || true; \
			fi; \
			rm -f "$(PID_DIR)/$$name.pid"; \
		fi; \
	done

down: kill
	@echo "Stopped."

status:
	@for name in api web; do \
		if [[ -f "$(PID_DIR)/$$name.pid" ]] && kill -0 "$$(cat "$(PID_DIR)/$$name.pid")" 2>/dev/null; then \
			echo "$$name: running pid=$$(cat "$(PID_DIR)/$$name.pid")"; \
		else \
			echo "$$name: stopped"; \
		fi; \
	done

logs:
	@mkdir -p "$(LOG_DIR)"
	@touch "$(LOG_DIR)/api.log" "$(LOG_DIR)/web.log"
	@tail -n 40 -F "$(LOG_DIR)/api.log" "$(LOG_DIR)/web.log"
