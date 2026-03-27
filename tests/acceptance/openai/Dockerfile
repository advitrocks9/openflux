FROM openflux-base
RUN uv pip install "openai-agents" --system
COPY tests/acceptance/test_openai_agents.py ./tests/acceptance/test_openai_agents.py
CMD ["python", "-m", "pytest", "tests/acceptance/test_openai_agents.py", "-xvs", "--tb=short"]
