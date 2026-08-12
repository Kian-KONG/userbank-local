.PHONY: install serve check web

install:
	@PY=$$(command -v python3.12 || command -v python3.11 || command -v python3); \
	$$PY -m venv .venv
	.venv/bin/pip install -U pip -i https://pypi.tuna.tsinghua.edu.cn/simple
	.venv/bin/pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
	cd web && npm install

serve:
	@test -d .venv || $(MAKE) install
	.venv/bin/python -m src.main serve

check:
	@test -d .venv || $(MAKE) install
	.venv/bin/python -c "from src.api import create_app; create_app(); print('ok')"

web:
	cd web && npm run dev

up: serve

down:
	@echo "Stop ub-local with Ctrl-C"
