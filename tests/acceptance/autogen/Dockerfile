FROM openflux-base
RUN uv pip install "autogen-agentchat>=0.4.2" "autogen-ext[openai]>=0.4.2" "pytest-asyncio" --system
COPY tests/acceptance/test_autogen.py ./tests/acceptance/test_autogen.py
CMD ["python", "-m", "pytest", "tests/acceptance/test_autogen.py", "-xvs", "--tb=short"]
