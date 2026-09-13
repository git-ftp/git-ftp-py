.PHONY: setup lint fmt typecheck test test-fast test-docker docker-up docker-down build man completions clean
UV ?= uv

setup:
	$(UV) sync --all-groups

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

fmt:
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

typecheck:
	$(UV) run mypy

test:
	$(UV) run pytest -m "not docker" --cov --cov-report=term-missing

test-fast:
	$(UV) run pytest tests/unit -q

docker-up:
	docker compose -f docker-compose.test.yml up -d --wait

docker-down:
	docker compose -f docker-compose.test.yml down -v

test-docker: docker-up
	GIT_FTP_TEST_FTP_ADDR=127.0.0.1:21 GIT_FTP_TEST_FTP_BADPASV_ADDR=127.0.0.1:2121 \
	GIT_FTP_TEST_FTP_USER=gitftp GIT_FTP_TEST_FTP_PASS=s3cret \
	$(UV) run pytest tests/docker -m docker -v; status=$$?; $(MAKE) docker-down; exit $$status

build:
	$(UV) build
	$(UV)x twine check dist/*

man:
	mkdir -p out && pandoc -s -t man docs/git-ftp.1.md -o out/git-ftp.1

completions:
	mkdir -p out/completions
	_GIT_FTP_COMPLETE=bash_source $(UV) run git-ftp > out/completions/git-ftp.bash
	_GIT_FTP_COMPLETE=zsh_source $(UV) run git-ftp > out/completions/_git-ftp
	_GIT_FTP_COMPLETE=fish_source $(UV) run git-ftp > out/completions/git-ftp.fish

clean:
	rm -rf dist build out .coverage coverage.xml htmlcov .pytest_cache .mypy_cache .ruff_cache
