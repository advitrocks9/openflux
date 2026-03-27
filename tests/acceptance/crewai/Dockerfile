FROM openflux-base
RUN uv pip install "crewai>=0.80" --system
COPY tests/acceptance/test_crewai.py ./tests/acceptance/test_crewai.py
CMD ["python", "-m", "pytest", "tests/acceptance/test_crewai.py", "-xvs", "--tb=short"]
