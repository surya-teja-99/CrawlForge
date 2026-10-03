.PHONY: setup test demo clean

setup:
	pip3 install --break-system-packages -r requirements.txt

test:
	python3 -m pytest tests/ -q

demo:
	python3 scripts/demo.py

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -name "*.pyc" -delete
	rm -rf .pytest_cache
