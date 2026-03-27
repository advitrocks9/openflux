FROM openflux-base
RUN uv pip install "mcp[cli]" "fastmcp" --system
COPY tests/acceptance/test_mcp.py ./tests/acceptance/test_mcp.py
CMD ["python", "-m", "pytest", "tests/acceptance/test_mcp.py", "-xvs", "--tb=short"]
