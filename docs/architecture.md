# Architecture of Job Execution Service

## 1. Context diagram (C4 level: Context)

```mermaid
flowchart LR
    researcher["Scientific researcher<br/>[person]<br/>converts temperatures, requests weather"]
    engineer["Civil engineer<br/>[person]<br/>converts lengths"]
    author["Author<br/>[person]<br/>transforms text to Title Case"]
    dev["Developer / student / reviewer<br/>[person]<br/>calls the API from scripts and tests"]

    system["<b>Job Execution Service</b><br/>[our system]<br/>runs small computations as Jobs,<br/>keeps execution history,<br/>allows safe retry"]

    owm["<b>OpenWeatherMap API</b><br/>[external system]<br/>geocoding + current weather"]

    researcher -- "creates jobs, reads results<br/>(HTTPS, JSON)" --> system
    engineer -- "creates jobs, reads results<br/>(HTTPS, JSON)" --> system
    author -- "creates jobs, reads results<br/>(HTTPS, JSON)" --> system
    dev -- "creates jobs, reads results, health<br/>(HTTPS, JSON)" --> system
    system -- "resolves city, requests current weather<br/>(HTTPS, JSON, API key)" --> owm
```

**What the arrows show:** runtime **calls** (who sends a request to whom). The arrow points from the caller to the
callee; the label says what is requested and over which protocol. The database is not shown: at this level it is
part of our system (it appears on the component diagram).

**Intentionally not shown:** internal structure, the database, deployment.


## 2. Component diagram (C4 level: Component)