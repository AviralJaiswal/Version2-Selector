# 🚀 Qcom Signal Selector — Project Presentation & Technical Guide

---

## 📌 Executive Summary & Project Pitch

**Qcom Signal Selector** is an enterprise-grade Broadband Selection & Serviceability Qualification Engine built for modern telecommunications providers (powered by **Prodapt**). 

It bridges conversational AI with real-time address geocoding, RAG-driven knowledge lookup, dynamic plan selection, appointment scheduling, and automated payment workflows.

---

## 🛠️ Complete Tech Stack Breakdown

### 1. Frontend Technologies (User Interface & Experience)
* **Framework**: `React 19` + `Vite 6` (Lightning-fast dev setup and optimized ES-module bundling).
* **Styling & Design System**:
  * **Vanilla CSS + Custom Design System**: Custom theme variables, dark mode styling (`styles.css`, `wizard.css`, `wizard-overrides.css`).
  * **Visual Design Aesthetic**: High-contrast glassmorphism, ambient gradient backgrounds, Prodapt Crimson (`#9E1B32`) brand palette, slate accents.
  * **Micro-Animations & Motion**: CSS height collapse and opacity fade transitions for action chips (`.vanished` state), hover glitter effects on title headers.
* **Component Libraries & Icons**:
  * `lucide-react`: Modern vector icon library (Network icons, Signal indicators, Calendar icons).
  * `react-day-picker`: Customized date & appointment slot picker for technician dispatch.

### 2. Backend Architecture (API & Orchestration)
* **Framework**: `FastAPI 0.110+` + `Uvicorn 0.28+` (Asynchronous Python backend with automatic OpenAPI/Swagger documentation).
* **Data Validation & Serialization**: `Pydantic v2` (Strict schemas for requests, address normalization, session states, and API responses).
* **ORM & Database**: `SQLAlchemy v2` with `SQLite` (`qcom.db`) for lightweight, robust local persistence of orders, plans, and sessions.

### 3. AI, RAG & Geocoding Engine
* **Vector Store / Retrieval Augmented Generation**: `ChromaDB` (`chromadb`) for semantic similarity search across catalog data and past user queries (`faq_knowledge_base.md`, `plans_catalog.json`).
* **AI Framework**: `LangChain Core` for modular prompt templates and structured retrieval chains.
* **Geocoding & Telecom Circle Mapping**: **OpenStreetMap (Nominatim API)** integration.
  * Geocodes 6-digit Indian PIN codes and street addresses into telecom circles (e.g., Delhi NCR, Mumbai, Bengaluru, Hyderabad, Chennai, Kolkata, AP & Telangana).
  * Custom `User-Agent` (`SignalSelectorTelecomApp/1.0`) compliant with OSM usage guidelines.

### 4. Logging & Payments Integration
* **Activity & Audit Trail**: `activity.jsonl` (Line-delimited JSON log) capturing session events, pincode lookups, address submissions, and booking events.
* **Payment Processing**: `Razorpay Python SDK` integration for simulating secure subscription checkout.

---

## 🎨 UI/UX Features & Design Highlights (What to highlight about the UI)

1. **Dual Chat Experience**:
   * **Guided Order Wizard**: A structured step-by-step state machine (PIN Code verification → Customer Address Form → Interactive Fiber Plan Cards → Installation Appointment Picker → Payment).
   * **General Assistant Chat**: Handles out-of-band broadband questions, troubleshooting, and speed recommendations powered by RAG retrieval.

2. **Responsive Interactive Components**:
   * **Customer Details Card (`CustomerCard.jsx`)**: Enforces fixed width (540px) across all states (edit, input, saved) to prevent Cumulative Layout Shift (CLS).
   * **Dynamic Action Chips (`SuggestedResponses.jsx`)**: Contextual quick action buttons that animate and vanish smoothly when transitioning into order creation.
   * **Visual Plan Grid (`PlanCardGrid.jsx`)**: Interactive telecom plan cards showing OTT bundles, download/upload speeds, pricing, and "Select Plan" triggers.
   * **Technician Appointment Scheduler (`AppointmentPicker.jsx`)**: Dynamic calendar date selector paired with time slot chips (`10:00 AM - 12:00 PM`, `03:00 PM - 04:00 PM`).

---

## 🎤 Speaker Script & Presentation Notes

### **1. Introduction & Title Slide**
> "Good morning/afternoon. Today I'm presenting **Signal Selector**, a Broadband Connected Intelligence Platform that simplifies how customers discover broadband serviceability, select fiber plans, and schedule installation."

### **2. Tech Stack & Engineering Highlights**
> "For the **UI**, we built a responsive SPA using **React 19, Vite, and Lucide React** with custom CSS featuring glassmorphism and Prodapt brand aesthetics. 
> 
> On the **Backend**, we engineered an asynchronous **FastAPI** service backed by **SQLite** and **SQLAlchemy**. 
> 
> For **AI & Geocoding**, we integrated **ChromaDB** for vector-based Retrieval-Augmented Generation (RAG) and **OpenStreetMap Nominatim** to dynamically resolve Indian PIN codes into telecom serviceability circles."

### **3. Live Demo Flow**
> "During the demo, we will demonstrate:
> 1. Entering a PIN code (`560001` or `110001`) to trigger Nominatim geocoding.
> 2. Structured address confirmation without layout flicker.
> 3. Dynamic fiber plan cards with OTT inclusions.
> 4. Interactive calendar appointment picking and Razorpay checkout simulation."
