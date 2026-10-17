# OSRM with the Nairobi graph baked in (built by services/osrm/prepare.sh).
# Build context: local/data. The base image is multi-arch; built for arm64.
FROM ghcr.io/project-osrm/osrm-backend:v6.0.0
COPY --chmod=0444 nairobi.osrm.* /data/
EXPOSE 5000
USER 65534
CMD ["osrm-routed", "--algorithm", "mld", "/data/nairobi.osrm"]
