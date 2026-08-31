PIP_INDEX := https://pypi.tuna.tsinghua.edu.cn/simple
NPM_REGISTRY := https://registry.npmmirror.com

.PHONY: install serve check web

install:
	@PY=$$(command -v python3.12 || command -v python3.11 || command -v python3); \
	$$PY -m venv .venv
	@cp pip.conf .venv/pip.conf
	.venv/bin/pip install -U pip -i $(PIP_INDEX)
	.venv/bin/pip install -e ".[dev]" -i $(PIP_INDEX)
	cd web && npm install --registry=$(NPM_REGISTRY)

serve:
	@test -d .venv || $(MAKE) install
	@cp pip.conf .venv/pip.conf
	.venv/bin/python -m src.main serve

check:
	@test -d .venv || $(MAKE) install
	@cp pip.conf .venv/pip.conf
	.venv/bin/python -c "from src.api import create_app; create_app(); print('ok')"
	.venv/bin/python -m pytest tests -q

web:
	cd web && npm run dev

up: serve

down:
	@echo "Stop ub-local with Ctrl-C"
