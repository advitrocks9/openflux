FROM openflux-base
COPY tests/acceptance/test_bedrock.py ./tests/acceptance/test_bedrock.py
CMD ["python", "-m", "pytest", "tests/acceptance/test_bedrock.py", "-xvs", "--tb=short"]
