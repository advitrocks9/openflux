FROM openflux-base
RUN uv pip install "claude-agent-sdk" "pytest-asyncio" --system
COPY tests/acceptance/test_claude_agent_sdk.py ./tests/acceptance/test_claude_agent_sdk.py
CMD ["python", "-m", "pytest", "tests/acceptance/test_claude_agent_sdk.py", "-xvs", "--tb=short"]
