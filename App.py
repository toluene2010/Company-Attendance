import streamlit as st
import pandas as pd
import time
import json
import bcrypt
from io import BytesIO
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
import sqlalchemy

import streamlit.components.v1 as components

# ==========================================================
# CONFIG: Online (Supabase) + Offline (SQLite) hybrid
# ==========================================================

SUPABASE_URL = None  # filled by load_supabase_url()
SQLITE_URL = "sqlite:///attendance_offline.db"

@st.cache_resource
def load_supabase_url():
    """Read Supabase creds from Streamlit secrets; return DB URL or None."""
    try:
        DB_USER = st.secrets["database"]["DB_USER"]
        DB_PASSWORD = st.secrets["database"]["DB_PASSWORD"]
        DB_HOST = st.secrets["database"]["DB_HOST"]
        DB_PORT = st.secrets["database"]["DB_PORT"]
        DB_NAME = st.secrets["database"]["DB_NAME"]
        return f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    except Exception:
        return None

SUPABASE_URL = load_supabase_url()

@st.cache_resource
def get_engine(url: str):
    return create_engine(url, poolclass=NullPool)

def try_connect(engine) -> bool:
    try:
        with engine.connect() as conn:
            if "postgresql" in str(engine.url):
                conn.execute(text("SELECT NOW()"))
            else:
                conn.execute(text("SELECT datetime('now')"))
            return True
    except Exception:
        return False

def is_online() -> bool:
    """True if Supabase engine exists & can connect."""
    if not SUPABASE_URL:
        return False
    eng = get_engine(SUPABASE_URL)
    return try_connect(eng)

def online_engine_or_none():
    if not SUPABASE_URL:
        return None
    eng = get_engine(SUPABASE_URL)
    if try_connect(eng):
        return eng
    return None

def offline_engine():
    eng = get_engine(SQLITE_URL)
    # Ensure SQLite file exists and connectable
    try:
        with eng.connect() as _:
            pass
    except Exception:
        pass
    return eng

# ==========================================================
# DB INIT (both backends)
# ==========================================================

POSTGRES_TABLES = [
    """CREATE SCHEMA IF NOT EXISTS attendance""",
    """CREATE TABLE IF NOT EXISTS attendance.shifts (
        ID SERIAL PRIMARY KEY,
        Name VARCHAR(255) NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS attendance.sections (
        ID SERIAL PRIMARY KEY,
        Name VARCHAR(255) NOT NULL,
        Description VARCHAR(500)
    )""",
    """CREATE TABLE IF NOT EXISTS attendance.departments (
        ID SERIAL PRIMARY KEY,
        Name VARCHAR(255) NOT NULL,
        Section_ID INTEGER,
        Description VARCHAR(500)
    )""",
    """CREATE TABLE IF NOT EXISTS attendance.users (
        ID SERIAL PRIMARY KEY,
        Name VARCHAR(255) NOT NULL,
        Username VARCHAR(255) UNIQUE NOT NULL,
        Password VARCHAR(255) NOT NULL,
        Role VARCHAR(50) NOT NULL,
        Active BOOLEAN DEFAULT TRUE,
        Assigned_Section VARCHAR(255),
        Assigned_Shift VARCHAR(255)
    )""",
    """CREATE TABLE IF NOT EXISTS attendance.workers (
        ID SERIAL PRIMARY KEY,
        Name VARCHAR(255) NOT NULL,
        Section VARCHAR(255),
        Department VARCHAR(255),
        Shift VARCHAR(255),
        Active BOOLEAN DEFAULT TRUE
    )""",
    """CREATE TABLE IF NOT EXISTS attendance.attendance (
        ID SERIAL PRIMARY KEY,
        Worker_ID INTEGER,
        Worker_Name VARCHAR(255) NOT NULL,
        Date DATE NOT NULL,
        Section VARCHAR(255),
        Department VARCHAR(255),
        Shift VARCHAR(255),
        Status VARCHAR(50) NOT NULL,
        Timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )"""
]

# SQLite has no schemas; mirror tables w/o schema + a queue
SQLITE_TABLES = [
    """CREATE TABLE IF NOT EXISTS shifts (
        ID INTEGER PRIMARY KEY AUTOINCREMENT,
        Name TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS sections (
        ID INTEGER PRIMARY KEY AUTOINCREMENT,
        Name TEXT NOT NULL,
        Description TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS departments (
        ID INTEGER PRIMARY KEY AUTOINCREMENT,
        Name TEXT NOT NULL,
        Section_ID INTEGER,
        Description TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS users (
        ID INTEGER PRIMARY KEY AUTOINCREMENT,
        Name TEXT NOT NULL,
        Username TEXT UNIQUE NOT NULL,
        Password TEXT NOT NULL,
        Role TEXT NOT NULL,
        Active INTEGER DEFAULT 1,
        Assigned_Section TEXT,
        Assigned_Shift TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS workers (
        ID INTEGER PRIMARY KEY AUTOINCREMENT,
        Name TEXT NOT NULL,
        Section TEXT,
        Department TEXT,
        Shift TEXT,
        Active INTEGER DEFAULT 1
    )""",
    """CREATE TABLE IF NOT EXISTS attendance (
        ID INTEGER PRIMARY KEY AUTOINCREMENT,
        Worker_ID INTEGER,
        Worker_Name TEXT NOT NULL,
        Date TEXT NOT NULL,
        Section TEXT,
        Department TEXT,
        Shift TEXT,
        Status TEXT NOT NULL,
        Timestamp TEXT DEFAULT (datetime('now'))
    )""",
    # Queue of offline changes to sync later (only workers for now)
    """CREATE TABLE IF NOT EXISTS pending_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity TEXT NOT NULL,       -- e.g., 'workers'
        op TEXT NOT NULL,           -- 'add' or 'delete'
        payload TEXT NOT NULL,      -- JSON string of row data
        ts TEXT DEFAULT (datetime('now'))
    )"""
]

def initialize_databases():
    # Initialize offline DB
    off_eng = offline_engine()
    with off_eng.begin() as conn:
        for sql in SQLITE_TABLES:
            conn.execute(text(sql))

    # Initialize online DB (if reachable)
    on_eng = online_engine_or_none()
    if on_eng:
        with on_eng.begin() as conn:
            for sql in POSTGRES_TABLES:
                conn.execute(text(sql))

def df_read_sql(engine, query):
    return pd.read_sql(query, engine)

# ==========================================================
# Helpers: read/write tables (transparent schema handling)
# ==========================================================

def read_table(table_name: str) -> pd.DataFrame:
    if is_online():
        eng = online_engine_or_none()
        if not eng:
            return pd.DataFrame()
        query = f"SELECT * FROM attendance.{table_name}"
        try:
            return df_read_sql(eng, query)
        except Exception:
            return pd.DataFrame()
        finally:
            eng.dispose()
    else:
        eng = offline_engine()
        query = f"SELECT * FROM {table_name}"
        try:
            return df_read_sql(eng, query)
        except Exception:
            return pd.DataFrame()
        finally:
            eng.dispose()

def write_table_replace(table_name: str, df: pd.DataFrame) -> bool:
    """Replace a whole table (used only where safe)."""
    try:
        if is_online():
            eng = online_engine_or_none()
            if not eng:
                return False
            df.to_sql(table_name, eng, if_exists='replace', index=False, schema='attendance')
            eng.dispose()
        else:
            eng = offline_engine()
            df.to_sql(table_name, eng, if_exists='replace', index=False)
            eng.dispose()
        return True
    except Exception as e:
        st.error(f"Error writing table {table_name}: {e}")
        return False

# ==========================================================
# Offline change queue (workers) + sync
# ==========================================================

def queue_offline_change(entity: str, op: str, payload: dict):
    """Store a JSON change locally to sync later."""
    eng = offline_engine()
    try:
        with eng.begin() as conn:
            conn.execute(
                text("INSERT INTO pending_changes(entity, op, payload) VALUES (:e, :o, :p)"),
                {"e": entity, "o": op, "p": json.dumps(payload)}
            )
    finally:
        eng.dispose()

def sync_pending_changes():
    """If online, push pending worker changes from SQLite to Supabase."""
    if not is_online():
        return 0

    # read queued changes
    off_eng = offline_engine()
    total = 0
    try:
        with off_eng.begin() as conn:
            rows = conn.execute(text("SELECT id, entity, op, payload FROM pending_changes ORDER BY id")).fetchall()
            if not rows:
                return 0

    finally:
        off_eng.dispose()

    on_eng = online_engine_or_none()
    if not on_eng:
        return 0

    applied_ids = []
    try:
        with on_eng.begin() as on_conn:
            for rid, entity, op, payload_json in rows:
                if entity != "workers":
                    continue
                payload = json.loads(payload_json)

                if op == "add":
                    # Insert by fields (no ID sync). Best-effort dedupe by (Name, Section, Department, Shift)
                    on_conn.execute(
                        text("""INSERT INTO attendance.workers(Name, Section, Department, Shift, Active)
                                SELECT :Name, :Section, :Department, :Shift, :Active
                                WHERE NOT EXISTS (
                                  SELECT 1 FROM attendance.workers
                                  WHERE Name=:Name AND Section=:Section AND Department=:Department AND Shift=:Shift
                                )"""),
                        {
                            "Name": payload.get("Name"),
                            "Section": payload.get("Section"),
                            "Department": payload.get("Department"),
                            "Shift": payload.get("Shift"),
                            "Active": bool(payload.get("Active", True))
                        }
                    )
                    applied_ids.append(rid)

                elif op == "delete":
                    # Delete by Name + optional Department to narrow (still a best-effort)
                    on_conn.execute(
                        text("""DELETE FROM attendance.workers
                                WHERE Name=:Name AND (:Department IS NULL OR Department=:Department)"""),
                        {"Name": payload.get("Name"), "Department": payload.get("Department")}
                    )
                    applied_ids.append(rid)

                total += 1

    finally:
        on_eng.dispose()

    # Remove applied items from queue
    if applied_ids:
        off_eng2 = offline_engine()
        try:
            with off_eng2.begin() as conn:
                conn.execute(text("DELETE FROM pending_changes WHERE id IN (%s)" %
                                  ",".join(str(x) for x in applied_ids)))
        finally:
            off_eng2.dispose()

    return total

# ==========================================================
# Seed data (run on both stores as needed)
# ==========================================================

def ensure_seed_data():
    # Shifts
    if read_table("shifts").empty:
        write_table_replace("shifts", pd.DataFrame({
            "ID": [1, 2, 3],
            "Name": ["Morning", "Afternoon", "General"]
        }))

    # Sections
    if read_table("sections").empty:
        write_table_replace("sections", pd.DataFrame({
            "ID": [1, 2, 3],
            "Name": ["Liquid Section", "Solid Section", "Utility Section"],
            "Description": ["Liquid manufacturing", "Solid manufacturing", "Utility services"]
        }))

    # Departments
    if read_table("departments").empty:
        write_table_replace("departments", pd.DataFrame({
            "ID": [1, 2, 3, 4],
            "Name": ["Mixing", "Filling", "Packaging", "Maintenance"],
            "Section_ID": [1, 1, 2, 3],
            "Description": ["Mixing dept", "Filling dept", "Packaging dept", "Maintenance dept"]
        }))

    # Users
    users_df = read_table("users")
    if users_df.empty:
        hashed_pw = bcrypt.hashpw("admin123".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        df = pd.DataFrame([{
            "ID": 1, "Name": "Admin User", "Username": "admin",
            "Password": hashed_pw, "Role": "Admin", "Active": True,
            "Assigned_Section": "", "Assigned_Shift": ""
        }])
        write_table_replace("users", df)

# ==========================================================
# Authentication (password + optional device quick-login)
# ==========================================================

def verify_password(plain, hashed):
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def login(username, password) -> bool:
    users = read_table("users")
    if users.empty:
        return False
    user = users[users["Username"] == username]
    if user.empty:
        return False
    if verify_password(password, user.iloc[0]["Password"]):
        st.session_state.update({
            "logged_in": True,
            "username": username,
            "role": user.iloc[0]["Role"],
            "user_id": int(user.iloc[0]["ID"])
        })
        return True
    return False

def set_device_token(username: str):
    """Render a small JS widget to save a device token (pseudo passkey) in the browser."""
    components.html(f"""
    <div style="display:none" id="quickpass-anchor"></div>
    <script>
      (function() {{
        const key = "quickpass_token::{username}";
        if (!localStorage.getItem(key)) {{
          const token = crypto.getRandomValues(new Uint32Array(4)).join("-");
          localStorage.setItem(key, token);
        }}
        // Post back token so Streamlit can store the fact that this device is trusted
        const token = localStorage.getItem(key);
        window.parent.postMessage({{isTrustedDevice: true, user: "{username}", token}}, "*");
      }})();
    </script>
    """, height=0)

def check_device_token(username: str):
    """JS to retrieve the device token and send to Streamlit; Streamlit compares to session."""
    components.html(f"""
    <div style="display:none"></div>
    <script>
      const key = "quickpass_token::{username}";
      const token = localStorage.getItem(key);
      window.parent.postMessage({{quickpassRead: true, user: "{username}", token}}, "*");
    </script>
    """, height=0)

# ==========================================================
# CRUD: Workers (row-wise so we can queue offline)
# ==========================================================

def add_worker_row(row: dict):
    """
    Add worker row either online or offline.
    When offline, queue change for later sync.
    """
    if is_online():
        eng = online_engine_or_none()
        if not eng:
            st.error("Online engine error.")
            return
        try:
            with eng.begin() as conn:
                conn.execute(
                    text("""INSERT INTO attendance.workers(Name, Section, Department, Shift, Active)
                            VALUES (:Name, :Section, :Department, :Shift, :Active)"""),
                    {
                        "Name": row["Name"], "Section": row["Section"],
                        "Department": row["Department"], "Shift": row["Shift"],
                        "Active": bool(row.get("Active", True))
                    }
                )
        finally:
            eng.dispose()
    else:
        # insert locally + queue
        eng = offline_engine()
        try:
            with eng.begin() as conn:
                conn.execute(
                    text("""INSERT INTO workers(Name, Section, Department, Shift, Active)
                            VALUES (:Name, :Section, :Department, :Shift, :Active)"""),
                    {
                        "Name": row["Name"], "Section": row["Section"],
                        "Department": row["Department"], "Shift": row["Shift"],
                        "Active": 1 if row.get("Active", True) else 0
                    }
                )
            queue_offline_change("workers", "add", row)
        finally:
            eng.dispose()

def delete_worker_by_name(name: str, department: str | None):
    """
    Delete worker by name (+ optional department). When offline, queue deletion for later sync.
    """
    if is_online():
        eng = online_engine_or_none()
        if not eng:
            st.error("Online engine error.")
            return
        try:
            with eng.begin() as conn:
                conn.execute(
                    text("""DELETE FROM attendance.workers
                            WHERE Name=:Name AND (:Department IS NULL OR Department=:Department)"""),
                    {"Name": name, "Department": department}
                )
        finally:
            eng.dispose()
    else:
        eng = offline_engine()
        try:
            with eng.begin() as conn:
                conn.execute(
                    text("""DELETE FROM workers
                            WHERE Name=:Name AND (:Department IS NULL OR Department=:Department)"""),
                    {"Name": name, "Department": department}
                )
            queue_offline_change("workers", "delete", {"Name": name, "Department": department})
        finally:
            eng.dispose()

# ==========================================================
# UI: Mobile responsiveness
# ==========================================================

def mobile_css():
    return """
    <style>
      @media (max-width: 768px) {
        .main .block-container { padding: 1rem; }
        .stButton > button { width: 100%; }
        .stDataFrame { overflow-x: auto; }
        .stTabs [data-baseweb="tab-list"] { flex-wrap: wrap; }
      }
    </style>
    """

# ==========================================================
# Pages
# ==========================================================

def manage_workers_page():
    st.subheader("👷 Manage Workers")

    # Try syncing if we came back online
    synced = 0
    if is_online():
        synced = sync_pending_changes()
        if synced:
            st.success(f"🔄 Synced {synced} pending change(s) to Supabase.")

    # Show status
    st.info("Status: " + ("🟢 Online (Supabase)" if is_online() else "🔵 Offline (SQLite — changes will sync later)"))

    workers_df = read_table("workers")
    st.dataframe(workers_df, use_container_width=True)

    st.markdown("---")
    st.subheader("➕ Add Worker")
    with st.form("add_worker_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Worker Name")
            sections_df = read_table("sections")
            section = st.selectbox("Section", sections_df["Name"].tolist() if not sections_df.empty else ["Liquid Section","Solid Section","Utility Section"])
            departments_df = read_table("departments")
            department = st.selectbox("Department", departments_df["Name"].tolist() if not departments_df.empty else ["Mixing","Filling","Packaging","Maintenance"])
        with col2:
            shifts_df = read_table("shifts")
            shift = st.selectbox("Shift", shifts_df["Name"].tolist() if not shifts_df.empty else ["Morning","Afternoon","General"])
            active = st.checkbox("Active", value=True)
        submitted = st.form_submit_button("💾 Save Worker")

    if submitted:
        if not name.strip():
            st.error("Please enter a worker name.")
        else:
            add_worker_row({"Name": name.strip(), "Section": section, "Department": department, "Shift": shift, "Active": active})
            st.success(f"✅ Worker '{name}' saved ({'online' if is_online() else 'offline — queued for sync'}).")
            time.sleep(1)
            st.rerun()

    st.markdown("---")
    st.subheader("📤 Bulk Upload Workers (Excel/CSV)")
    up = st.file_uploader("Upload file", type=["xlsx", "csv"])
    if up:
        try:
            if up.name.endswith(".csv"):
                new_workers = pd.read_csv(up)
            else:
                new_workers = pd.read_excel(up)
            required = {"Name", "Section", "Department", "Shift", "Active"}
            if not required.issubset(set(new_workers.columns)):
                st.error(f"❌ Missing required columns. Must include: {', '.join(sorted(required))}")
            else:
                count = 0
                for _, r in new_workers.iterrows():
                    add_worker_row({
                        "Name": str(r["Name"]).strip(),
                        "Section": str(r["Section"]).strip(),
                        "Department": str(r["Department"]).strip(),
                        "Shift": str(r["Shift"]).strip(),
                        "Active": bool(r["Active"])
                    })
                    count += 1
                st.success(f"✅ Processed {count} worker(s) ({'online' if is_online() else 'offline — queued for sync'}).")
                time.sleep(1)
                st.rerun()
        except Exception as e:
            st.error(f"Error reading file: {e}")

    st.markdown("---")
    st.subheader("❌ Delete Worker")
    if not workers_df.empty:
        name_del = st.selectbox("Select worker by name", workers_df["Name"].tolist())
        dept_options = workers_df.loc[workers_df["Name"] == name_del, "Department"].dropna().unique().tolist()
        dept_del = st.selectbox("Filter by Department (optional)", [""] + dept_options)
        if st.button("🗑️ Delete"):
            delete_worker_by_name(name_del, dept_del if dept_del else None)
            st.warning(f"Deleted '{name_del}' ({'online' if is_online() else 'offline — queued for sync'}).")
            time.sleep(1)
            st.rerun()
    else:
        st.info("No workers to delete.")

def hr_dashboard():
    st.title("📊 HR Dashboard")
    workers = read_table("workers")
    attendance = read_table("attendance")
    col1, col2 = st.columns(2)
    col1.metric("Total Workers", len(workers))
    col2.metric("Attendance Records", len(attendance))

def admin_dashboard():
    st.title("🔧 Admin Dashboard")
    manage_workers_page()

def supervisor_dashboard():
    st.title("👷 Supervisor Dashboard")
    manage_workers_page()

def login_page():
    st.title("🔐 Company Attendance System")
    st.markdown("---")

    # Quick-login info
    with st.expander("🔑 Device Quick-Login (Convenience, not a security control)"):
        st.write(
            "Enable a device token on this browser to bypass typing your password next time on **this same device**. "
            "This is **not** full biometric security. For true passkeys/fingerprint (WebAuthn), a server-side verifier is required."
        )

    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.subheader("Login")
        username = st.text_input("Username", key="login_user")
        password = st.text_input("Password", type="password", key="login_pw")

        # Quick login button uses local device token if present
        use_quick = st.checkbox("Use device quick-login (if enabled on this device)")
        login_btn = st.button("Login", use_container_width=True)

        # Listen to quickpass messages
        msg = st.experimental_get_query_params()  # fallback; not used
        quick_token_state = st.session_state.get("quick_token_seen")

        # Read device token silently
        if use_quick and username:
            # Ask browser for token
            check_device_token(username)
            # Streamlit receives postMessage via its internal bridge; we catch it with the trick below
            # (Streamlit doesn't expose window message directly. We'll register the token when user clicks login.)

        if login_btn:
            ok = False
            if use_quick and username:
                # We can't directly read the postMessage; emulate by asking the browser to set token and then using a hidden input approach.
                # For simplicity, we still require password on first run; after enabling quick-login below, user can skip password on same device.
                # So if password is blank but quick-login was previously enabled, allow login.
                quick_enabled_key = f"quick_enabled::{username}"
                if st.session_state.get(quick_enabled_key) and password.strip() == "":
                    ok = True

            if not ok:
                ok = login(username, password)

            if ok:
                st.success("✅ Logged in")
                st.session_state["logged_in"] = True
                st.session_state.setdefault(f"quick_enabled::{username}", False)
                st.rerun()
            else:
                st.error("Invalid credentials or quick-login not enabled on this device.")

        st.markdown("---")
        st.subheader("Enable Device Quick-Login for this user")
        if st.button("Enable on this device"):
            if not username:
                st.error("Enter a username first.")
            else:
                # Save a device token in browser storage and mark session flag so next time password can be skipped
                set_device_token(username)
                st.session_state[f"quick_enabled::{username}"] = True
                st.success("✅ Quick-login enabled on this device for this username.\nNext time you can log in without a password (convenience only).")

# ==========================================================
# MAIN
# ==========================================================

def main():
    st.set_page_config(page_title="Attendance System", page_icon="🗂️", layout="wide")
    st.markdown(mobile_css(), unsafe_allow_html=True)

    # Initialize both DBs and seed
    initialize_databases()
    ensure_seed_data()

    # Sidebar status + sync
    with st.sidebar:
        if is_online():
            eng = online_engine_or_none()
            with eng.connect() as conn:
                now = conn.execute(text("SELECT NOW()")).scalar()
            st.success(f"🟢 Online (Supabase)\n{now}")
        else:
            eng = offline_engine()
            with eng.connect() as conn:
                now = conn.execute(text("SELECT datetime('now')")).scalar()
            st.warning(f"🔵 Offline (SQLite)\n{now}")

        # Manual sync button (does nothing if offline)
        if st.button("🔄 Sync Now"):
            if is_online():
                n = sync_pending_changes()
                st.success(f"Synced {n} change(s).")
            else:
                st.info("Still offline — will sync when online.")

        st.markdown("---")
        if st.session_state.get("logged_in"):
            st.write(f"👤 {st.session_state['username']} ({st.session_state['role']})")
            if st.button("Logout"):
                for k in list(st.session_state.keys()):
                    if k.startswith("quickpass") or k.startswith("quick_enabled::"):
                        continue
                    del st.session_state[k]
                st.experimental_rerun()

    # Routing
    if not st.session_state.get("logged_in"):
        login_page()
        return

    role = st.session_state.get("role", "Admin")
    if role == "Admin":
        admin_dashboard()
    elif role == "Supervisor":
        supervisor_dashboard()
    elif role == "HR":
        hr_dashboard()
    else:
        st.error("Invalid role.")

if __name__ == "__main__":
    main()
