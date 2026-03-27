FROM openflux-base
RUN uv pip install "langchain-core" "langchain" "langchain-google-genai" "langgraph" --system
COPY tests/acceptance/test_langchain.py ./tests/acceptance/test_langchain.py
CMD ["python", "-m", "pytest", "tests/acceptance/test_langchain.py", "-xvs", "--tb=short"]
