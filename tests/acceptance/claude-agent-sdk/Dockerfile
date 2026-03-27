FROM openflux-base
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm && rm -rf /var/lib/apt/lists/*
RUN npm install -g @anthropic-ai/claude-code
RUN uv pip install "claude-agent-sdk" "pytest-asyncio" --system
COPY tests/acceptance/test_claude_agent_sdk.py ./tests/acceptance/test_claude_agent_sdk.py
CMD ["python", "-m", "pytest", "tests/acceptance/test_claude_agent_sdk.py", "-xvs", "--tb=short"]
