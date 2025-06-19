# RadMapping+

**RadMapping+** is a centralized platform for managing radiologist schedules, specialties, facility assignments, licensing, and workload analytics, along with other Vesta-related information. It integrates real-time data sync from Google Sheets with a secure Supabase backend and a Flask-based web dashboard.

---

## ✨ Features

### 👨‍⚕️ Doctor Management

* Profile pages with full information and an editable admin section
* Specialty tracking, license status, and shift analytics
* Monthly & daily schedule views (including PRN logic)

### 🏥 Facility Management

* Assign radiologists with read permissions and stipulations
* Contact tracking, sortable facility list, and state filtering

### ⏰ Scheduling

* Interactive calendar views (monthly & daily by hour)
* Google Sheets integration for schedule sync
* Real-time updates with schedule refresh triggers

### 📓 Specialties & Licensing

* Bulk upload from Excel files with color-coded logic
* Status filters and audit logs for every change

### 🌄 Other Modules

* Rad Vacations
* Vesta Contacts
* RVU tracking per radiologist
* Capacity hour-by-hour planning

### 🔐 Authentication & Roles

* Google OAuth via Supabase
* Role-based access: Admins can perform CRUD, Users have restricted views

---

## 🚀 Tech Stack

* **Backend:** Python + Flask
* **Frontend:** HTML, Jinja2, TailwindCSS
* **Database:** Supabase (PostgreSQL + Auth + Storage)
* **AI Integration:** OpenAI, LlamaIndex
* **Scheduling APIs:** Google Sheets API
* **Data Processing:** Pandas, openpyxl
* **Deployment:** Docker-compatible, uses environment variables

---

## ⚙️ Setup

### 1. Clone the repo

```bash
git clone https://github.com/your-org/radmapping-plus.git
cd radmapping-plus
```

### 2. Create `.env` file

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

```bash
python -m flask run
```

### 5. Deploy to Google Cloud

Run these commands from the directory: `PS C:\Users\Adrian Cosentino\Documents\radmapping+>`

```bash
gcloud builds submit --tag gcr.io/radmapping-458916/flask-app
gcloud run deploy flask-app \
  --image gcr.io/radmapping-458916/flask-app \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --env-vars-file .env.yaml
```

---

## 📊 Google Sheets Sync

* Set up a Google Apps Script webhook to hit `/sync-endpoint` whenever a specific cell is edited
* Provide `sheet_name` in the payload to selectively update data
* Schedule logic auto-parses PRN times, shifts over midnight, and date boundaries

---

## 🔒 Security

* Supabase Auth controls user access
* All writes are logged with user IDs via audit logging
* Editable sections are role-locked in the frontend and backend

### 📄 Roles

| Role  | Capabilities                                          |
| ----- | ----------------------------------------------------- |
| Admin | Full edit access to all modules and fields (CRUD ops) |
| User  | View-only access to the platform                      |

#### Promote a User to Admin

1. In Supabase, go to **Authentication** and copy the UID of the user.
2. Navigate to the `users` table in the **Table Editor**.
3. Click **Insert Row** and:

   * Paste the UID into the `id` field
   * Set `role` to `admin`
   * Fill in the remaining fields as necessary

#### Demote a User

1. In the `users` table, locate the user.
2. You can either:

   * Right-click and select **Delete Row**, or
   * Double-click the `role` cell and change `admin` to `user`

---

## 👥 Contributors

Built by **Adrian Cosentino** with aid from **John Boxma**

---
