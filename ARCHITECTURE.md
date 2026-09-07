# 📐 Qcom Signal Selector — Technical System Architecture

**Signal Selector** is an enterprise-grade broadband connected intelligence platform built with a React (Vite) frontend, FastAPI backend core, LLM tool orchestration, dual-geocoding fallback engine (Mapbox + OpenStreetMap), and vector-based RAG support.

---

## 🎨 System Architecture Diagram

```mermaid
flowchart TD
    %% Node Styling Definitions
    classDef client fill:#E0F2FE,stroke:#0284C7,stroke-width:2px,color:#0F172A;
    classDef api fill:#DCFCE7,stroke:#16A34A,stroke-width:2px,color:#0F172A;
    classDef agent fill:#FEF3C7,stroke:#D97706,stroke-width:2px,color:#0F172A;
    classDef external fill:#FAE8FF,stroke:#C026D3,stroke-width:2px,color:#0F172A;
    classDef storage fill:#FFEDD5,stroke:#EA580C,stroke-width:2px,color:#0F172A;

    subgraph ClientLayer ["1. Frontend Layer (React + Vite)"]
        UI["Conversational UI\n(App.jsx & Chat Components)"]
        Wizard["Step-by-Step Order Flow\n(Address, Plans, Booking)"]
    end

    subgraph BackendLayer ["2. Backend Core (FastAPI)"]
        API["FastAPI Modular Router\n(/api/v1/...)"]
        SessServ["Session & Qualification Service"]
        OrdServ["Order & Appointment Service"]
    end

    subgraph AILayer ["3. AI Agent & RAG Engine"]
        Agent["LLM Agent Orchestrator\n(Intent & Tool Dispatcher)"]
        ToolGeo["Geocoding Tool\n(Pincode to Telecom Circle)"]
        ToolRAG["RAG Search Tool\n(Semantic FAQ Search)"]
    end

    subgraph ExtLayer ["4. Geocoding Services"]
        Mapbox["Mapbox Geocoding API\n(Primary Provider)"]
        OSM["Nominatim OpenStreetMap\n(Secondary Fallback)"]
    end

    subgraph DataLayer ["5. Data & Persistence Layer"]
        DB[("SQLite Database\n(qcom.db - Orders & Customers)")]
        ChromaStore[("ChromaDB Vector Store\n(FAQ & Plan Catalog Vectors)")]
        Logs[("Activity Logger\n(data/activity.jsonl)")]
    end

    %% Interaction Flows
    UI -->|"1. User Input / PIN Code"| API
    Wizard -->|"4. Complete Order & Appointment"| API

    API -->|"Route Session & Qualification"| SessServ
    API -->|"Route Booking Requests"| OrdServ
    API -->|"Process Chat & Intent"| Agent

    Agent -->|"Validate Address / PIN"| ToolGeo
    Agent -->|"Retrieve Telecom QA"| ToolRAG

    ToolGeo -->|"Primary Lookup"| Mapbox
    ToolGeo -->|"Fallback Lookup"| OSM

    ToolRAG -->|"Vector Search"| ChromaStore

    SessServ -->|"Check Circle & Plans"| DB
    OrdServ -->|"Persist Customer & Orders"| DB
    API -->|"Append Action Logs"| Logs

    class UI,Wizard client;
    class API,SessServ,OrdServ api;
    class Agent,ToolGeo,ToolRAG agent;
    class Mapbox,OSM external;
    class DB,ChromaStore,Logs storage;
```

---

## 🔍 Layer Component Breakdown

### 1. Frontend Layer (`/frontend`)
- **Technology**: React 19, Vite, Tailwind CSS, Custom CSS (`wizard.css`, `wizard-overrides.css`).
- **`App.jsx`**: Main state management and conversational interface renderer.
- **Components**: `CustomerCard`, `QuickActions`, `PlanCards`, `AppointmentScheduler`.

### 2. Backend Core (`/app`)
- **Framework**: FastAPI with standard JSON envelopes (`success`, `code`, `message`, `data`).
- **APIRouters**: Modular router registry (`/api/v1/session`, `/qualification`, `/recommendation`, `/customers`, `/appointments`, `/payments`, `/orders`, `/assistant`).

### 3. AI Agent & RAG Engine (`/app/chat`, `/app/rag`)
- **Agent Orchestrator**: Intent handling, out-of-domain query guardrails, and tool dispatching.
- **Geocoding Tool**: Enforces 6-digit Indian pincode validation and resolves regional telecom circles.
- **RAG Retriever**: Queries ChromaDB vector embeddings over FAQ catalogs for grounded answers.

### 4. External Geocoding Services
- **Primary**: Mapbox API.
- **Secondary Fallback**: Nominatim OpenStreetMap with compliant custom user-agent header.

### 5. Persistence Layer (`/data`, `qcom.db`)
- **SQLite (`qcom.db`)**: Persistent tables for customer profiles, plans, appointments, and orders.
- **ChromaDB (`chroma_data/`)**: Vector embeddings store.
- **Activity Log (`data/activity.jsonl`)**: Line-delimited JSON log capturing session activity, query inputs, and order bookings.
