# RadMapping+

**RadMapping+** is a centralized platform for managing radiologist schedules, specialties, facility assignments, licensing, and workload analytics, along with other provider-related information. It integrates real-time data sync from Google Sheets with a secure Supabase backend and a Flask-based web dashboard.

---

## Table of Contents

* [Visual Demo](#visual-demo)

  * [Landing Page](#landing-page)
  * [Daily Schedule](#daily-schedule)
  * [Monthly Schedule](#monthly-schedule)
  * [Capacity](#capacity)
  * [Doctor Directory](#doctor-directory)
  * [Doctor Profile](#doctor-profile)
  * [Facilities Directory](#facilities-directory)
  * [Facility Profile](#facility-profile)
  * [Specialties](#specialties)
  * [Licenses](#licenses)
  * [Vacations](#vacations)
  * [Information](#information)
  * [Contacts](#contacts)
  * [Audit Log](#audit-log)
  * [RAG AI Assistant](#rag-ai-assistant)
* [Authentication & Roles](#authentication--roles)
* [Tech Stack](#tech-stack)
* [Setup](#setup)

  * [Clone the repo](#1-clone-the-repo)
  * [Create .env file](#2-create-env-file)
  * [Install dependencies](#3-install-dependencies)
  * [Run the app](#4-run-the-app)
  * [Re-Deploy to Google Cloud](#5-re-deploy-to-google-cloud)
* [Security](#security)

  * [Roles](#roles)
  * [Promote a User to Admin](#promote-a-user-to-admin)
  * [Demote a User](#demote-a-user)

---

# Visual Demo

## Landing Page

![Landing Page](https://github.com/user-attachments/assets/a08ab8a3-8ee0-4088-a62e-b030cd204845)

* Navigate to any page here upon landing on the site after authentication

## Daily Schedule

![Daily Schedule](https://github.com/user-attachments/assets/4c0e0aa9-6531-42fa-9f4e-0eb58d4d1e63)

* Navigate day-by-day by hour with color-coded availability and RVU
* Tooltips and modals for more details
* Special tags for PRN and other shift types

## Monthly Schedule

![Monthly Schedule](https://github.com/user-attachments/assets/e72f0517-6357-4bdc-bbda-008bcbd47f4c)

* View entries at a glance
* Pinned and sorted doctors
* Color coded by shift type

## Capacity

![Capacity](https://github.com/user-attachments/assets/290968d6-287b-4a4c-8bfe-fcee1716197f)

* View gaps based on expected vs actual RVU/hour
* Search by facility, state, and hour block

## Doctor Directory

![Doctor Directory](https://github.com/user-attachments/assets/25900834-b253-44f4-bb9d-71c7d545e473)

* Search doctors, filter by active status
* Pinned doctors prioritized

## Doctor Profile

![Doctor Profile](https://github.com/user-attachments/assets/046cc3ec-5420-4a00-b747-e5dbd66f5142)

* View/edit doctor info, facility assignments, and licenses
* Changes are audit-logged

## Facilities Directory

![Facilities Directory](https://github.com/user-attachments/assets/efee3eaa-b7d8-4a1a-b7c2-881abbf13ab8)

* Search facilities, filter by status or state
* Prioritized facilities feature

## Facility Profile

![Facility Profile](https://github.com/user-attachments/assets/b21411ae-b0fc-4e90-8e87-2aa1a6cbc0a7)

* View facility info and assigned doctors
* Facility-specific contact info

## Specialties

![Specialties](https://github.com/user-attachments/assets/ae1bb453-2c97-4d8e-9405-374c434f5222)

* See specialty-to-doctor assignments

## Licenses

![Licenses](https://github.com/user-attachments/assets/aca28cb1-b237-4d8e-82fe-bfc8eca35db3)

* View/edit licenses
* Expired licenses are auto-detected

## Vacations

![Vacations](https://github.com/user-attachments/assets/36259702-cff6-4950-9693-7d27ee850b27)

* View current and upcoming vacations

## Information

![Information](https://github.com/user-attachments/assets/e11770a4-24de-44c4-8a0d-b6d2eec0bd87)

* Provider-related policies and notes

## Contacts

![Contacts](https://github.com/user-attachments/assets/5d1e8e40-57b7-438a-90e3-27f92e115b00)

* Contact management with roles

## Audit Log

![Audit Log](https://github.com/user-attachments/assets/4707ede0-8b3f-44e1-ae8a-3f817ec3da01)

* View all changes from admins or sync
* Searchable by field

## RAG AI Assistant

![RAG AI Assistant](https://github.com/user-attachments/assets/f3c74155-f98a-415f-b01b-ace630108023)

* Converts user questions into SQL using OpenAI + LlamaIndex

---

### Authentication & Roles

* Google OAuth via Supabase
* Role-based access (Admin vs User)

---

## Tech Stack

* **Backend:** Python + Flask
* **Frontend:** HTML, Jinja2, TailwindCSS
* **Database:** Supabase (PostgreSQL + Auth + Storage)
* **AI Integration:** OpenAI, LlamaIndex
* **Scheduling APIs:** Google Sheets API
* **Data Processing:** Pandas, openpyxl
* **Deployment:** Docker-compatible, uses environment variables

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/acozy03/RadmappingPlus.git
cd RadMapping+
```

### 2. Create .env file

```
SUPABASE_URL=
SUPABASE_KEY=
SECRET_KEY=
SUPABASE_SUPER_KEY=
OPENAI_API_KEY=
OPENAI_ORG_ID=
SUPABASE_DB_URL=
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the app

```
python -m flask run
```

### 5. Re-Deploy to Google Cloud

```bash
gcloud builds submit --tag gcr.io/project-id/project-name
gcloud run deploy flask-app \
  --image gcr.io/project-id/project-name \
  --platform managed \
  --region region \
  --allow-unauthenticated \
  --env-vars-file .env.yaml
```

---

## Security

* Supabase Auth controls user access
* All writes are logged with user IDs via audit logging
* Editable sections are role-locked

### Roles

| Role  | Capabilities                                          |
| ----- | ----------------------------------------------------- |
| Admin | Full edit access to all modules and fields (CRUD ops) |
| User  | View-only access to the platform                      |

### Promote a User to Admin

1. In Supabase, go to **Authentication** and copy the UID.
2. Navigate to the `users` table.
3. Click **Insert Row**:

   * Paste UID into `id`
   * Set `role` to `admin`

### Demote a User

1. Find user in `users` table
2. Either:

   * Delete the row
   * Or change `role` to `user`
