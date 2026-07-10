FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN if grep -vE '^\s*(#|$)' /tmp/requirements.txt >/dev/null; then pip install --no-cache-dir -r /tmp/requirements.txt; fi

COPY assistant_bot /app/assistant_bot

CMD ["python", "-m", "assistant_bot"]
