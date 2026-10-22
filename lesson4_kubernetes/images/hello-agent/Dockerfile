# The smallest agent image: python + one file, no dependencies.
FROM python:3.12-alpine

# the version is baked into the image: hello-agent:1 and hello-agent:2 differ only by it
ARG VERSION=1
ENV AGENT_VERSION=${VERSION} PYTHONUNBUFFERED=1

COPY agent.py /app/agent.py
EXPOSE 8080
CMD ["python", "/app/agent.py"]
