-- Which H3 zone had the highest demand, and at what time?
-- Runs on the SYNTHETIC ride history (seeded generator, not real rides).
SELECT
  pickup_zone,
  date_trunc('hour', CAST(requested_at AS timestamp)) AS hour_utc,
  count(*) AS rides,
  round(avg(surge), 2) AS avg_surge,
  sum(price_kes) AS revenue_kes
FROM ride_dispatch.synthetic_ride_history
GROUP BY 1, 2
ORDER BY rides DESC, hour_utc
LIMIT 5
