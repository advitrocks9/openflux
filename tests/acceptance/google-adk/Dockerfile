FROM openflux-base
RUN uv pip install "google-adk" --system
COPY tests/acceptance/test_google_adk.py ./tests/acceptance/test_google_adk.py
CMD ["python", "-m", "pytest", "tests/acceptance/test_google_adk.py", "-xvs", "--tb=short"]
