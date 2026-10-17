# Driver simulator image (also carries the demo and measurement scripts, which
# run inside the cluster because MSK and Redis are private). Build context: repo root.
FROM python:3.13-slim
WORKDIR /app
COPY services/simulator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/shared/shared shared/
COPY services/matching/matching matching/
COPY services/simulator/simulator simulator/
COPY scripts/*.py scripts/
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
USER 10001
CMD ["python", "-m", "simulator.main"]
