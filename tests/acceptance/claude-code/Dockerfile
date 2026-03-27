FROM openflux-base
COPY tests/acceptance/test_claude_code.py ./tests/acceptance/test_claude_code.py
CMD ["python", "-m", "pytest", "tests/acceptance/test_claude_code.py", "-xvs", "--tb=short"]
