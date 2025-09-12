format:
	poetry run ruff format . 	
	poetry run ruff check --fix ./src ./tests

test:
	poetry run pytest -vv tests/