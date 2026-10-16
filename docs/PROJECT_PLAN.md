# Real-Time Ride Dispatch Platform on AWS - Geospatial Matching, Streaming and Dynamic Pricing

---

## Project Description

Matching a rider to the nearest available driver among many moving vehicles, in a fraction of a second, while adjusting price to local supply and demand, is a classic system design problem. This project builds the matching engine itself and tests it under a live, moving simulation instead of a static map.

The platform is provisioned entirely with **Terraform** and combines **H3 geospatial indexing** (the open-source hexagonal grid library created at Uber), a **Redis proximity cache**, **Kafka (Amazon MSK)** for continuous driver position ingestion, and an **event-driven ride lifecycle** (requested, searching, matched, driver en route, driver arrived, in trip, completed) pushed to the client in real time over WebSocket. Driver movement is simulated along real Nairobi road geometry computed by a **self-hosted OSRM instance on Kubernetes**, not straight lines through buildings. Prices react live to simulated supply shortages in specific zones. Every completed ride is archived to a small analytics layer, so the system can answer business questions about demand, not only serve real-time requests.

Every technology choice, including the ones left out, was tested against one question: does it solve a problem this scenario actually has? See Considered and Rejected.

---

## Technologies and Services Used

| Layer | Technology | Purpose |
| --- | --- | --- |
| IaC | **Terraform** | VPC, IAM and all managed services, single source of truth |
| Routing engine | **OSRM**, self-hosted on **Amazon EKS** | Real road-network routes for simulated driver movement and trip distance and price; long-lived service that loads the road graph into memory at startup (measured size recorded in an ADR) |
| Geospatial indexing | **H3** | Hexagonal grid for proximity search and per-zone surge calculation |
| Geospatial cache | **Amazon ElastiCache (Redis)** | Low-latency "nearest available drivers" queries with GEOADD and GEOSEARCH |
| Ingestion | **Amazon MSK (Kafka)** | Continuous stream of simulated driver GPS positions, read independently by the matching path and by the analytics archival path |
| Matching and pricing compute | **AWS Lambda (arm64, Graviton)** | Matching logic and surge calculation per H3 cell, on Graviton for cost and performance |
| Persistent data | **Amazon DynamoDB** | Rides, drivers, clients, ride history |
| Analytics layer | **Amazon S3 and Amazon Athena** | Completed rides archived and queried with SQL; sized for the real data volume |
| Ride lifecycle events | **Amazon EventBridge** | Decouples state transitions from notification delivery |
| Real-time push | **API Gateway WebSocket API** | Live updates to the UI without polling |
| Security | **IAM**, least privilege per function | One role per function, no wildcard admin |
| Frontend | **React and Leaflet** (OpenStreetMap tiles, attribution shown) | Two full-screen views: Client Panel and Live Ops Map |
| Simulation | **Python** (OSRM-interpolated movement, Faker) | 20 drivers moving on real roads; 5 clickable client cards for on-demand ride requests |

---

## Architecture Patterns Demonstrated

- **Geospatial indexing** - H3 cells instead of comparing the rider position with every driver position.
- **Low-latency proximity lookup** - Redis geospatial commands instead of querying a general-purpose database for the nearest driver. The latency is measured and reported, not assumed.
- **Independent stream consumers** - the same Kafka topic of driver positions is read by two unrelated consumers (real-time matching and analytics archival) without either affecting the other.
- **Stateful workload placement** - OSRM holds a road graph in memory, so it runs as a long-lived service on Kubernetes instead of Lambda.
- **Ride lifecycle as an explicit state machine** - each transition is an event, not hidden state in application logic.
- **Event-driven decoupling** - notification delivery reacts to EventBridge events, so a slow notification never blocks dispatch.
- **Dynamic pricing from live local supply** - surge computed per H3 cell from real-time driver availability, not a hardcoded multiplier.
- **Compute architecture as a cost lever** - matching and pricing Lambdas on arm64.
- **Realistic simulated movement** - driver positions interpolated along OSRM routes on real Nairobi roads.

---

## Demo Scenarios

| Scenario | What Happens | What It Proves |
| --- | --- | --- |
| **Live matching** | A client card requests a ride; the nearest of 20 moving drivers is found and assigned, with the measured matching latency shown | Geospatial matching under a moving simulation |
| **Surge in action** | Driver availability in one H3 zone is reduced; the price for that zone rises in near real time | Pricing driven by local supply data |
| **Full lifecycle trace** | One ride followed end to end: searching, matched with ETA, driver arrived, in trip, completed, each step notified live | The event-driven state machine and the real-time notification path |
| **Demand query** | An Athena query on a synthetic ride history (seeded script, labeled synthetic) answers "which H3 zone had the highest demand, and at what time?" | The analytics layer turns event history into a business answer |

---

## UI Details

One application, two full-screen views switched by two top-level buttons:

- **Client Panel** - 5 client cards with live status (Waiting, Searching, Driver found with ETA, Driver arrived, In trip, Completed); clicking a card opens a pickup and dropoff form with a "Send request" button.
- **Live Ops Map** - the 20 simulated drivers moving along real roads, color-coded by status (available, en route to pickup, in trip); active rides drawn as a line from driver to client, updating live.
- A non-technical viewer can watch a request appear, a driver get matched and a price get calculated.

---

## Use Case Simulation

| Role | What They Would See or Do |
| --- | --- |
| **Rider (client card)** | Requests a ride and watches the status change from search to completion |
| **Driver (simulated)** | Receives a match and moves along the real route to pickup then dropoff |
| **Platform engineer** | Watches matching latency and the event stream behind each state transition |
| **Pricing analyst** | Runs Athena queries on ride history to understand demand by zone and time |

---

## Deployment Strategy

Billable resources (EKS, MSK, ElastiCache) are kept alive for the shortest possible time. Everything is written and tested offline first, then applied once.

1. **Terraform backend and budget**
2. **Local build and validation, no AWS cost** - Redis, Kafka and OSRM in Docker; H3 matching and pricing logic with tests; simulator; UI built against recorded messages
3. **Infrastructure code** - network, EKS, MSK, ElastiCache, DynamoDB, S3, Athena, EventBridge, WebSocket API, Lambdas; validated and planned, with an hourly cost estimate
4. **One billable session** - apply, deploy OSRM and the simulator to EKS, ingest to MSK, run the Lambdas, connect the UI, validate all four scenarios, capture proof
5. **Clean-up** - everything torn down and verified before the documentation work
6. **Documentation** - architecture diagram and README, written offline

---

## Considered and Rejected

- **Multi-region deployment** - the scenario simulates one city; a second region would add infrastructure with no latency problem to solve.
- **Multi-cloud** - no functional need at this scope.
- **Amazon EMR or Spark for analytics** - built for far larger data. The real volume here is a few thousand rows; S3 and Athena is the right size.
- **Amazon Keyspaces** - DynamoDB covers the actual data needs; adding a second store would be technology for its own sake.
- **Mapbox** - needs an account token; Leaflet with OpenStreetMap tiles does the job without one.
- **Real driver hardware or apps** - the system under test is the AWS side; simulated publishers exercise the same architecture.

---

## Architecture Decisions Worth Documenting

- **OSRM on Kubernetes instead of Lambda**: it holds the road graph in memory, a poor fit for Lambda cold starts. The measured memory footprint goes in the ADR.
- **Kafka (MSK) instead of Kinesis**: two independent consumers read the same position stream through separate consumer groups. Verified in the documentation before building.
- **S3 and Athena instead of EMR**: right-sized for a few thousand rows.
- **Graviton (arm64) Lambdas**: lower cost per invocation; requires arm64 builds of native dependencies such as H3.
- **H3 instead of raw latitude and longitude comparison**: constant-time cell lookup and per-zone aggregation for surge.
- **Redis geospatial cache instead of DynamoDB for proximity**: DynamoDB is not built for this query shape.
- **OSRM-routed simulated movement instead of a random walk**: the matching engine works on coordinates that behave like real traffic.
- **One app with two full-screen views instead of a split dashboard**: cause (client action) and effect (map reaction) are shown as two clear steps.
- **No multi-region and no multi-cloud**: neither solves a problem this scope has.
