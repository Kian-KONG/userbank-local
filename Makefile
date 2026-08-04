.PHONY: install up down serve check

install:
	cd web && npm install

check:
	cargo check -p ub-local

serve:
	cargo run -p ub-local -- serve

up: serve

down:
	@echo "Stop ub-local with Ctrl-C"
