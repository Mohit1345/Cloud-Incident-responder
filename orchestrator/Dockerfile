FROM python:3.12-slim

WORKDIR /srv

COPY orchestrator/requirements.txt orchestrator/requirements.txt
RUN pip install --no-cache-dir -r orchestrator/requirements.txt

COPY orchestrator/ orchestrator/
COPY mcp-server/SKILL.md mcp-server/SKILL.md

ENV PYTHONPATH=/srv

EXPOSE 8080

CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8080"]
