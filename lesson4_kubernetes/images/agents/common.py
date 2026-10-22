"""Small helpers shared by our three services."""

import logging
import os
import socket

POD = os.getenv("POD_NAME", socket.gethostname())       # which replica this is (set by Kubernetes)


def make_logger(name: str) -> logging.Logger:
    """Our own short log lines only — the libraries stay quiet. Every line starts with the pod name."""
    log = logging.getLogger(name)
    log.setLevel(logging.INFO)
    log.propagate = False                                # the SDKs put their own handler on the root logger
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(f"%(asctime)s  [{POD}]  %(message)s", datefmt="%H:%M:%S"))
    log.addHandler(handler)
    return log


def make_llm():
    """The chat model via OpenRouter; the key comes from a Kubernetes Secret, the model from a ConfigMap."""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=os.getenv("MODEL", "openai/gpt-4o-mini"), base_url="https://openrouter.ai/api/v1",
                      api_key=os.environ["OPENROUTER_API_KEY"])
