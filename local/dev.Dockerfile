# Python toolbox for tests, the local harness, the simulator and the history
# generator. Python 3.13 matches the Lambda runtime used in AWS.
FROM python:3.13-slim
COPY local/requirements-dev.txt /tmp/requirements-dev.txt
RUN pip install --no-cache-dir -r /tmp/requirements-dev.txt
ENV PYTHONPATH=/w/services/shared:/w/services/matching:/w/services/lifecycle:/w/services/archiver:/w/services/simulator \
    PYTHONUNBUFFERED=1
WORKDIR /w
