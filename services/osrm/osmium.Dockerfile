# Small image with osmium-tool, used once to clip the Nairobi area out of the
# Geofabrik Kenya extract.
FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends osmium-tool \
    && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["osmium"]
