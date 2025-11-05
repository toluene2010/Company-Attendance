# ==========================================================
# Company Attendance System (Full) — Public schema, Hybrid DB,
# auto-init + self-heal, admin seeding, dashboards intact.
# ==========================================================

import streamlit as st
import pandas as pd
import datetime
import time
import os
import json
import bcrypt
import calendar
from io import BytesIO

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

# --------------------- CONFIG -----------------------------

st.set_page_config(page_title="Attendance", page_icon="🗂️", layout="wide")

SQLITE_URL = "sqlite:///attendance_offline.db"

@st.cache_resource
def build_supabase_url_from_secrets():
    try:
        u = st.secrets["database"]["DB_USER"]
        p = st.secrets["database"]["DB_PASSWORD"]
        h = st.secrets["database"]["DB_HOST"]
        po = st.secrets["database"]["DB_PORT"]
        db = st.secrets["database"]["DB_NAME"]
        return f"postgresql+psycopg2://{u}:{p}@{h}:{po}/{db}"
    except Exception:
        return None

SUPABASE_URL = build_supabase_url_from_secrets()

@st.cache_resource
def get_engine(url: str):
    return create_engine(url, poolclass=NullPool)

def _try_ping(engine) -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

def get_online_engine_or_none():
    if not SUPABASE_URL:
        return None
    eng = get_engine(SUPABASE_URL)
    return eng if _try_ping(eng) else None

def get_offline_engine():
    eng = get_engine(SQLITE_URL)
    try:
        with eng.connect() as _:
            pass
    except Exception:
        pass
    return eng

def is_online() -> bool:
    return get_online_engine_or_none() is not None

def current_engine():
    return get_online_engine_or_none() or get_offline_engine()

# ----------------- TABLE DEFINITIONS ----------------------

# Postgres-compatible schema
PG_TABLES = [
    """CREATE TABLE IF NOT EXISTS shifts (
        ID SERIAL PRIMARY KEY,
        Name VARCHAR(255) NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS sections (
        ID SERIAL PRIMARY KEY,
        Name VARCHAR(255) NOT NULL,
        Description VARCHAR(500)
    )""",
    """CREATE TABLE IF NOT EXISTS departments (
        ID SERIAL PRIMARY KEY,
        Name VARCHAR(255) NOT NULL,
        Section_ID INTEGER,
        Description VARCHAR(500)
    )""",
    """CREATE TABLE IF NOT EXISTS users (
        ID SERIAL PRIMARY KEY,
        Name VARCHAR(255) NOT NULL,
        Username VARCHAR(255) UNIQUE NOT NULL,
        Password VARCHAR(255) NOT NULL,
        Role VARCHAR(50) NOT NULL,
        Active BOOLEAN DEFAULT TRUE,
        Assigned_Section VARCHAR(255),
        Assigned_Shift VARCHAR(255)
    )""",
    """CREATE TABLE IF NOT EXISTS workers (
        ID SERIAL PRIMARY KEY,
        Name VARCHAR(255) NOT NULL,
        Section VARCHAR(255),
        Department VARCHAR(255),
        Shift VARCHAR(255),
        Active BOOLEAN DEFAULT TRUE
    )""",
    """CREATE TABLE IF NOT EXISTS attendance (
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

# SQLite-compatible schema
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
    )"""
]

def initialize_databases():
    # Always init SQLite
    off = get_offline_engine()
    with off.begin() as conn:
        for sql in SQLITE_TABLES:
            conn.execute(text(sql))

    # Init Postgres if online
    on = get_online_engine_or_none()
    if on:
        with on.begin() as conn:
            for sql in PG_TABLES:
                conn.execute(text(sql))

def seed_defaults():
    eng = current_engine()
    with eng.begin() as conn:
        # shifts
        c = conn.execute(text("SELECT COUNT(*) FROM shifts")).scalar()
        if c == 0:
            conn.execute(text("INSERT INTO shifts (Name) VALUES ('Morning'), ('Afternoon'), ('General')"))
        # sections
        c = conn.execute(text("SELECT COUNT(*) FROM sections")).scalar()
        if c == 0:
            conn.execute(text("""
                INSERT INTO sections (Name, Description) VALUES
                ('Liquid Section','Liquid manufacturing'),
                ('Solid Section','Solid manufacturing'),
                ('Utility Section','Utility services')
            """))
        # departments
        c = conn.execute(text("SELECT COUNT(*) FROM departments")).scalar()
        if c == 0:
            conn.execute(text("""
                INSERT INTO departments (Name, Section_ID, Description) VALUES
                ('Mixing', 1, 'Mixing department'),
                ('Filling', 1, 'Filling department'),
                ('Packaging', 2, 'Packaging department'),
                ('Maintenance', 3, 'Maintenance department')
            """))
        # users
        c = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
        if c == 0:
            hashed = bcrypt.hashpw("admin123".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            conn.execute(
                text("""INSERT INTO users (Name, Username, Password, Role, Active, Assigned_Section, Assigned_Shift)
                        VALUES (:n, :u, :p, :r, :a, :s, :sh)"""),
                {"n":"Admin User","u":"admin","p":hashed,"r":"Admin","a":True,"s":"","sh":""}
            )

# --------------- SELF-HEAL HELPERS -----------------------

def read_table(table):
    eng = current_engine()
    try:
        return pd.read_sql(f"SELECT * FROM {table}", eng)
    except Exception:
        st.warning(f"⚙️ Rebuilding tables... ({table} missing or invalid)")
        try:
            initialize_databases()
            seed_defaults()
            return pd.read_sql(f"SELECT * FROM {table}", eng)
        except Exception:
            return pd.DataFrame()

def write_table_replace(table, df: pd.DataFrame) -> bool:
    eng = current_engine()
    try:
        df.to_sql(table, eng, if_exists="replace", index=False)
        return True
    except Exception as e:
        st.error(f"Write error ({table}): {e}")
        return False

# ----------------- SYNC (Offline→Online) ------------------

def sync_from_sqlite_to_supabase():
    """Push new workers & attendance from SQLite to Supabase when we come online."""
    on = get_online_engine_or_none()
    if not on:
        return 0, 0

    off = get_offline_engine()
    new_workers = 0
    new_att = 0
    try:
        off_workers = pd.read_sql("SELECT Name,Section,Department,Shift,Active FROM workers", off)
        on_workers = pd.read_sql("SELECT Name,Section,Department,Shift,Active FROM workers", on)
        if not off_workers.empty:
            merged = off_workers.merge(
                on_workers, how="left",
                on=["Name","Section","Department","Shift"],
                indicator=True, suffixes=("","_on")
            )
            to_add = merged[merged["_merge"] == "left_only"][["Name","Section","Department","Shift","Active"]]
            if not to_add.empty:
                to_add["Active"] = to_add["Active"].apply(lambda x: bool(int(x)) if str(x).isdigit() else (str(x).lower() in ["true","1","yes"]))
                with on.begin() as conn:
                    for _, r in to_add.iterrows():
                        conn.execute(text("""INSERT INTO workers (Name,Section,Department,Shift,Active)
                                             VALUES (:n,:s,:d,:sh,:a)"""),
                                     {"n":r["Name"],"s":r["Section"],"d":r["Department"],"sh":r["Shift"],"a":bool(r["Active"])})
                new_workers = len(to_add)

        off_att = pd.read_sql("SELECT Worker_ID,Worker_Name,Date,Section,Department,Shift,Status,Timestamp FROM attendance", off)
        on_att = pd.read_sql("SELECT Worker_Name,Date FROM attendance", on)
        if not off_att.empty:
            off_att["Date"] = pd.to_datetime(off_att["Date"]).dt.date.astype(str)
            on_att["Date"] = pd.to_datetime(on_att["Date"]).dt.date.astype(str)
            merged = off_att.merge(on_att, how="left", on=["Worker_Name","Date"], indicator=True)
            to_add = merged[merged["_merge"] == "left_only"][["Worker_ID","Worker_Name","Date","Section","Department","Shift","Status","Timestamp"]]
            if not to_add.empty:
                with on.begin() as conn:
                    for _, r in to_add.iterrows():
                        conn.execute(text("""INSERT INTO attendance
                            (Worker_ID,Worker_Name,Date,Section,Department,Shift,Status,Timestamp)
                            VALUES (:wid,:wn,:dt,:s,:d,:sh,:st,:ts)"""),
                            {"wid":int(r["Worker_ID"]) if pd.notna(r["Worker_ID"]) else None,
                             "wn":r["Worker_Name"],"dt":r["Date"],"s":r["Section"],
                             "d":r["Department"],"sh":r["Shift"],"st":r["Status"],
                             "ts":r["Timestamp"] if pd.notna(r["Timestamp"]) else datetime.datetime.now()})
                new_att = len(to_add)
    except Exception as e:
        st.warning(f"Sync note: {e}")

    return new_workers, new_att

# ----------------- UTILITIES ------------------------------

def mobile_css():
    return """
    <style>
    @media (max-width: 768px) {
      .main .block-container { padding: 1rem; }
      .stButton > button { width: 100%; }
      .stDataFrame { overflow-x: auto; }
      .stTabs [data-baseweb="tab-list"] { flex-wrap: wrap; }
    }
    .attendance-grid th { position: sticky; top: 0; background: #f6f7fb; }
    .attendance-grid td, .attendance-grid th { text-align: center; }
    </style>
    """

def dataframe_to_excel_bytes(df: pd.DataFrame):
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as w:
        df.to_excel(w, index=False)
    bio.seek(0)
    return bio

def worker_template_bytes():
    cols = ["Name","Section","Department","Shift","Active"]
    return dataframe_to_excel_bytes(pd.DataFrame(columns=cols))

def verify_password(plain, hashed) -> bool:
    try: return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception: return False

def generate_attendance_grid(year, month):
    workers = read_table("workers")
    att = read_table("attendance")
    if workers.empty or att.empty: return pd.DataFrame()
    for c in ["Active","Section","Department","Shift"]:
        if c not in workers.columns: workers[c] = "" if c != "Active" else True
    att["Date"] = pd.to_datetime(att["Date"])
    att_m = att[(att["Date"].dt.year==year)&(att["Date"].dt.month==month)]
    if att_m.empty: return pd.DataFrame()

    days = calendar.monthrange(year, month)[1]
    g = workers[["ID","Name","Section","Department","Shift"]].copy()
    for d in range(1, days+1): g[str(d)] = ""
    for _, r in att_m.iterrows():
        name = r["Worker_Name"]; d = int(r["Date"].day); s = r["Status"]
        idx = g[g["Name"]==name].index
        if not idx.empty:
            g.at[idx[0], str(d)] = "✓" if s=="Present" else ("✗" if s=="Absent" else (s[:1] if isinstance(s,str) and s else ""))
    pres = []; perc=[]
    for _, row in g.iterrows():
        p = sum(1 for d in range(1,days+1) if row[str(d)]=="✓")
        pres.append(p); perc.append(round(p/days*100,1))
    g["Present Days"] = pres; g["Attendance %"] = perc
    return g

# ----------------- AUTH -------------------------------

def login(username, password) -> bool:
    eng = current_engine()
    with eng.connect() as conn:
        try:
            res = conn.execute(text("SELECT ID, Password, Role, Active FROM users WHERE Username = :u"), {"u":username}).fetchone()
        except Exception:
            initialize_databases(); seed_defaults()
            res = conn.execute(text("SELECT ID, Password, Role, Active FROM users WHERE Username = :u"), {"u":username}).fetchone()
    if not res: return False
    uid, phash, role, active = res
    if not active: return False
    if verify_password(password, phash):
        st.session_state["logged_in"]=True
        st.session_state["username"]=username
        st.session_state["role"]=role
        st.session_state["user_id"]=uid
        return True
    return False

def logout():
    st.session_state.clear()

# ----------------- ADMIN DASHBOARD ---------------------

def admin_dashboard():
    st.title("🔧 Admin Dashboard")
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        ["👥 Users", "🏭 Sections", "🏢 Departments", "👷 Workers", "📊 Attendance", "🗑️ Delete Data"]
    )

    # ---- Users ----
    with tab1:
        st.subheader("User Management")
        users_df = read_table("users")
        col_a, col_b = st.columns([2,3])
        with col_a:
            st.markdown("#### ➕ Add New User")
            with st.form("add_user"):
                name = st.text_input("Full Name")
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                role = st.selectbox("Role", ["Admin", "Supervisor", "HR"], key="admin_role")
                assigned_section = st.text_input("Assigned Section (optional)")
                assigned_shift = st.text_input("Assigned Shift (optional)")
                if st.form_submit_button("Add User"):
                    if name and username and password:
                        df = read_table("users")
                        new_id = int(df['ID'].max())+1 if not df.empty and 'ID' in df.columns else 1
                        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                        new_user = pd.DataFrame([{
                            'ID': new_id,
                            'Name': name,
                            'Username': username,
                            'Password': hashed,
                            'Role': role,
                            'Active': True,
                            'Assigned_Section': assigned_section,
                            'Assigned_Shift': assigned_shift
                        }])
                        df = pd.concat([df, new_user], ignore_index=True)
                        if write_table_replace("users", df):
                            st.success("User added")
                            st.rerun()
                    else:
                        st.error("Please fill all fields")

        with col_b:
            st.markdown("#### 📋 All Users")
            df = read_table("users")
            expected_cols = ["ID","Name","Username","Role","Active","Assigned_Section","Assigned_Shift"]
            if df.empty:
                st.info("No users found yet. Default admin = admin / admin123")
            else:
                missing = [c for c in expected_cols if c not in df.columns]
                if missing:
                    st.warning(f"Rebuilding users table (missing columns: {', '.join(missing)})")
                    initialize_databases(); seed_defaults(); df = read_table("users")
                st.dataframe(df[[c for c in expected_cols if c in df.columns]], use_container_width=True)

    # ---- Sections ----
    with tab2:
        st.subheader("Sections Management")
        sections_df = read_table("sections")
        col1, col2 = st.columns([2,3])
        with col1:
            st.markdown("#### ➕ Add Section")
            with st.form("add_section"):
                section_name = st.text_input("Section Name")
                desc = st.text_area("Description")
                if st.form_submit_button("Add Section"):
                    if section_name:
                        df = read_table("sections")
                        new_id = int(df['ID'].max())+1 if not df.empty and 'ID' in df.columns else 1
                        new_section = pd.DataFrame([{'ID':new_id,'Name':section_name,'Description':desc}])
                        df = pd.concat([df, new_section], ignore_index=True)
                        if write_table_replace("sections", df):
                            st.success("Section added")
                            st.rerun()
                    else:
                        st.error("Enter section name")
        with col2:
            if not sections_df.empty:
                st.dataframe(sections_df, use_container_width=True)
            else:
                st.info("No sections found")

    # ---- Departments ----
    with tab3:
        sections_df = read_table("sections")
        departments_df = read_table("departments")

        # ✅ Auto-heal missing columns in sections
        expected_sec_cols = ["ID","Name","Description"]
        missing_sec = [c for c in expected_sec_cols if c not in sections_df.columns]
        if missing_sec or sections_df.empty:
            st.warning("⚙️ Rebuilding sections table (missing columns or empty)")
            initialize_databases()
            seed_defaults()
            sections_df = read_table("sections")

        # ✅ Auto-heal missing columns in departments
        expected_dept_cols = ["ID","Name","Section_ID","Description"]
        missing_dept = [c for c in expected_dept_cols if c not in departments_df.columns]
        if missing_dept:
            st.warning("⚙️ Rebuilding departments table (missing columns)")
            initialize_databases()
            seed_defaults()
            departments_df = read_table("departments")

        col1, col2 = st.columns([2,3])
        with col1:
            st.markdown("#### ➕ Add Department")
            with st.form("add_department"):
                dept_name = st.text_input("Department Name")
                section_id = st.selectbox(
                    "Section",
                    sections_df['ID'].tolist() if "ID" in sections_df.columns and not sections_df.empty else [],
                    key="dept_section"
                )
                desc = st.text_area("Description")
                if st.form_submit_button("Add Department"):
                    if dept_name and section_id:
                        df = read_table("departments")
                        new_id = int(df['ID'].max())+1 if not df.empty and 'ID' in df.columns else 1
                        new_department = pd.DataFrame([{
                            'ID': new_id,
                            'Name': dept_name,
                            'Section_ID': section_id,
                            'Description': desc
                        }])
                        df = pd.concat([df, new_department], ignore_index=True)
                        if write_table_replace("departments", df):
                            st.success("Department added")
                            st.rerun()
                    else:
                        st.error("Enter department name and select section")
        
        with col2:
            if not departments_df.empty:
                merged = departments_df.merge(
                    sections_df[['ID','Name']], left_on='Section_ID', right_on='ID', how='left', suffixes=('', '_section')
                )
                merged = merged.rename(columns={'Name':'Department','Name_section':'Section'})
                merged = merged.drop(columns=['ID_section'])
                st.dataframe(merged[['ID','Department','Section','Description']], use_container_width=True)
            else:
                st.info("No departments found")

    # ---- Workers ----
    with tab4:
        st.subheader("Worker Management")
        sections_df = read_table("sections")
        departments_df = read_table("departments")
        shifts_df = read_table("shifts")
        workers_df = read_table("workers")

        for c, default in [("Active", True), ("Section",""), ("Department",""), ("Shift","")]:
            if c not in workers_df.columns:
                workers_df[c] = default

        col1, col2 = st.columns([2,3])

        with col1:
            st.markdown("#### 📤 Upload Workers from Excel/CSV")
            st.download_button(
                "⬇️ Download Workers Template",
                data=worker_template_bytes(),
                file_name="workers_template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

            uploaded_file = st.file_uploader("Upload File", type=["xlsx","csv"], key="admin_upload_workers")
            if uploaded_file is not None:
                try:
                    if uploaded_file.name.endswith(".xlsx"):
                        uploaded_df = pd.read_excel(uploaded_file)
                    else:
                        uploaded_df = pd.read_csv(uploaded_file)
                    required_cols = {"Name","Section","Department","Shift"}
                    if not required_cols.issubset(uploaded_df.columns):
                        st.error("File must contain columns: Name, Section, Department, Shift")
                    else:
                        wdf = read_table("workers")
                        if wdf.empty:
                            wdf = pd.DataFrame(columns=['ID','Name','Section','Department','Shift','Active'])
                        for c, default in [("Active", True), ("Section",""), ("Department",""), ("Shift","")]:
                            if c not in wdf.columns:
                                wdf[c] = default

                        def is_dup(row):
                            return ((wdf['Name'] == row['Name']) &
                                    (wdf['Section'] == row['Section']) &
                                    (wdf['Department'] == row['Department']) &
                                    (wdf['Shift'] == row['Shift'])).any()

                        new_rows = []
                        next_id = int(wdf['ID'].max())+1 if not wdf.empty and 'ID' in wdf.columns else 1
                        for _, r in uploaded_df.iterrows():
                            if not is_dup(r):
                                new_rows.append({
                                    'ID': next_id, 'Name': str(r['Name']).strip(), 'Section': str(r['Section']).strip(),
                                    'Department': str(r['Department']).strip(), 'Shift': str(r['Shift']).strip(), 'Active': True
                                })
                                next_id += 1

                        if not new_rows:
                            st.warning("All uploaded workers already exist. No new workers added.")
                        else:
                            add_df = pd.DataFrame(new_rows)
                            wdf = pd.concat([wdf, add_df], ignore_index=True)
                            if write_table_replace("workers", wdf):
                                st.success(f"Added {len(add_df)} new workers")
                                st.rerun()
                except Exception as e:
                    st.error(f"Error reading file: {e}")

            st.markdown("#### ➕ Add Single Worker (Admin)")
            with st.form("add_worker_admin"):
                w_name = st.text_input("Name")
                w_section = st.selectbox("Section", sections_df['Name'].tolist() if not sections_df.empty else [], key="admin_add_section")

                if w_section and not sections_df.empty:
                    section_id = sections_df[sections_df['Name'] == w_section]['ID'].values[0]
                    dept_options = departments_df[departments_df['Section_ID'] == section_id]['Name'].tolist() if not departments_df.empty else []
                else:
                    dept_options = []

                w_department = st.selectbox("Department", dept_options, key="admin_add_department")
                w_shift = st.selectbox("Shift", shifts_df['Name'].tolist() if not shifts_df.empty else [], key="admin_add_shift")

                if st.form_submit_button("Add Worker"):
                    if w_name and w_section and w_department and w_shift:
                        wdf = read_table("workers")
                        for c, default in [("Active", True), ("Section",""), ("Department",""), ("Shift","")]:
                            if c not in wdf.columns:
                                wdf[c] = default
                        new_id = int(wdf['ID'].max())+1 if not wdf.empty and 'ID' in wdf.columns else 1
                        new_worker = pd.DataFrame([{
                            'ID': new_id, 'Name': w_name, 'Section': w_section,
                            'Department': w_department, 'Shift': w_shift, 'Active': True
                        }])
                        wdf = pd.concat([wdf, new_worker], ignore_index=True)
                        if write_table_replace("workers", wdf):
                            st.success("Worker added")
                            st.rerun()
                    else:
                        st.error("Fill all fields")

        with col2:
            st.markdown("#### 📋 All Workers")
            wdf = read_table("workers")
            for c, default in [("Active", True), ("Section",""), ("Department",""), ("Shift","")]:
                if c not in wdf.columns:
                    wdf[c] = default
            wdf['Active'] = wdf['Active'].astype(str)
            st.write(f"**Total: {len(wdf)} workers**")
            st.download_button(
                "📥 Download Workers Excel",
                data=dataframe_to_excel_bytes(wdf),
                file_name="workers.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            st.markdown("---")
            for _, w in wdf.iterrows():
                tag = '✅' if w['Active'].lower() in ['true','1','yes'] else '❌'
                with st.expander(f"{tag} {w['Name']} - {w['Section']} / {w['Department']} ({w['Shift']})"):
                    st.write(f"ID: {w['ID']}")
                    colA, colB, colC = st.columns([2,1,1])
                    with colA:
                        if w['Active'].lower() in ['true','1','yes']:
                            if st.button("Deactivate", key=f"deact_{w['ID']}"):
                                df = read_table("workers")
                                for c2, default2 in [("Active", True), ("Section",""), ("Department",""), ("Shift","")]:
                                    if c2 not in df.columns: df[c2] = default2
                                df.loc[df['ID']==w['ID'],'Active'] = False
                                write_table_replace("workers", df); st.rerun()
                        else:
                            if st.button("Activate", key=f"act_{w['ID']}"):
                                df = read_table("workers")
                                for c2, default2 in [("Active", True), ("Section",""), ("Department",""), ("Shift","")]:
                                    if c2 not in df.columns: df[c2] = default2
                                df.loc[df['ID']==w['ID'],'Active'] = True
                                write_table_replace("workers", df); st.rerun()
                    with colC:
                        if st.button("🗑️ Delete", key=f"del_worker_{w['ID']}"):
                            df = read_table("workers")
                            df = df[df['ID'] != w['ID']]
                            write_table_replace("workers", df); st.rerun()

    # ---- Attendance (Admin view) ----
    with tab5:
        st.subheader("📊 Attendance Records")
        att = read_table("attendance")
        if not att.empty and 'Date' in att.columns:
            att['Date'] = pd.to_datetime(att['Date']).dt.date
            view_date = st.date_input("Select Date", datetime.date.today(), key="admin_view_date")
            filtered = att[att['Date'] == view_date]
            if not filtered.empty:
                st.write(f"Attendance for {view_date.strftime('%B %d, %Y')}")
                st.dataframe(filtered[['Worker_Name','Section','Department','Shift','Status','Timestamp']], use_container_width=True)
                total = len(filtered)
                present = (filtered['Status'] == 'Present').sum()
                absent = (filtered['Status'] == 'Absent').sum()
                late = (filtered['Status'] == 'Late').sum()
                leave = (filtered['Status'] == 'Leave').sum()
                c1,c2,c3,c4 = st.columns(4)
                with c1: st.metric("Present", present, f"{present/total*100:.1f}%")
                with c2: st.metric("Absent", absent, f"{absent/total*100:.1f}%")
                with c3: st.metric("Late", late, f"{late/total*100:.1f}%")
                with c4: st.metric("Leave", leave, f"{leave/total*100:.1f}%")
                st.download_button(
                    "📥 Download Attendance CSV",
                    filtered.to_csv(index=False).encode("utf-8"),
                    file_name=f"attendance_{view_date}.csv",
                    mime="text/csv"
                )
            else:
                st.info("No attendance records for selected date.")
        else:
            st.info("No attendance data yet.")

    # ---- Delete Data ----
    with tab6:
        st.subheader("Danger Zone - Delete Data")
        if st.button("Clear All Attendance", key="clear_attendance"):
            write_table_replace("attendance", pd.DataFrame(columns=['ID','Worker_ID','Worker_Name','Date','Section','Department','Shift','Status','Timestamp']))
            st.success("Attendance cleared")
        if st.button("Clear All Workers", key="clear_workers"):
            write_table_replace("workers", pd.DataFrame(columns=['ID','Name','Section','Department','Shift','Active']))
            st.success("Workers cleared")
        if st.button("Clear All Departments", key="clear_departments"):
            write_table_replace("departments", pd.DataFrame(columns=['ID','Name','Section_ID','Description']))
            st.success("Departments cleared")
        if st.button("Clear All Sections", key="clear_sections"):
            write_table_replace("sections", pd.DataFrame(columns=['ID','Name','Description']))
            st.success("Sections cleared")

# ----------------- SUPERVISOR DASHBOARD ------------------

def supervisor_dashboard():
    st.title("👷 Supervisor Dashboard")
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        ["✅ Mark Attendance", "📊 Attendance Register", "🔄 Transfer Workers",
         "👥 Manage Workers", "📅 View Attendance", "📊 Attendance Grid"]
    )

    sections_df = read_table("sections")
    departments_df = read_table("departments")
    shifts_df = read_table("shifts")
    workers_df = read_table("workers")
    for c, default in [("Active", True), ("Section",""), ("Department",""), ("Shift","")]:
        if c not in workers_df.columns:
            workers_df[c] = default

    # TAB 1: Mark Attendance
    with tab1:
        st.subheader("✅ Mark Attendance")
        mark_date = st.date_input("Select Date for Attendance", datetime.date.today(), key="mark_date")

        col1, col2 = st.columns(2)
        with col1:
            selected_section = st.selectbox("Select Section", ["All"] + (sections_df['Name'].tolist() if not sections_df.empty else []), key="mark_section")
            if selected_section != "All" and not sections_df.empty:
                section_id = sections_df[sections_df['Name'] == selected_section]['ID'].values[0]
                dept_options = departments_df[departments_df['Section_ID'] == section_id]['Name'].tolist() if not departments_df.empty else []
            else:
                dept_options = ["All"]
            selected_department = st.selectbox("Select Department", dept_options, key="mark_department")
        with col2:
            selected_shift = st.selectbox("Select Shift", ["All"] + (shifts_df['Name'].tolist() if not shifts_df.empty else []), key="mark_shift")

        wdf = read_table("workers")
        for c, default in [("Active", True), ("Section",""), ("Department",""), ("Shift","")]:
            if c not in wdf.columns:
                wdf[c] = default
        wdf["Active"] = wdf["Active"].astype(str)
        filtered = wdf.copy()

        if selected_section != "All": filtered = filtered[filtered["Section"] == selected_section]
        if selected_department != "All": filtered = filtered[filtered["Department"] == selected_department]
        if selected_shift != "All": filtered = filtered[filtered["Shift"] == selected_shift]
        filtered = filtered[filtered["Active"].str.lower().isin(["true","1","yes"])]

        if filtered.empty:
            st.info("No active workers for selected filters.")
        else:
            st.write(f"### 📋 Mark Attendance for {mark_date.strftime('%B %d, %Y')} ({len(filtered)} workers)")
            att_df = read_table("attendance")
            if not att_df.empty and "Date" in att_df.columns:
                att_df["Date"] = pd.to_datetime(att_df["Date"]).dt.date
                existing_att = att_df[(att_df["Date"] == mark_date) & (att_df["Worker_ID"].astype(str).isin(filtered["ID"].astype(str)))]
            else:
                existing_att = pd.DataFrame()

            with st.form("mark_attendance_form"):
                statuses = {}
                for _, worker in filtered.iterrows():
                    worker_id_str = str(worker["ID"])
                    worker_name = worker["Name"]
                    worker_section = worker.get("Section","")
                    worker_department = worker.get("Department","")
                    worker_shift = worker.get("Shift","")
                    if not existing_att.empty and "Worker_ID" in existing_att.columns:
                        worker_att = existing_att[existing_att["Worker_ID"].astype(str) == worker_id_str]
                        if not worker_att.empty and "Status" in worker_att.columns:
                            current_status = worker_att.iloc[0]["Status"]
                            default_idx = ["Present","Absent","Late","Leave"].index(current_status) if current_status in ["Present","Absent","Late","Leave"] else 0
                        else:
                            default_idx = 0
                    else:
                        default_idx = 0

                    st.write(f"**{worker_name}** - {worker_section} / {worker_department} / {worker_shift}")
                    status = st.radio("Status", ["Present","Absent","Late","Leave"], index=default_idx,
                                      key=f"stat_{worker['ID']}", horizontal=True, label_visibility="collapsed")
                    statuses[int(worker["ID"])] = {
                        'name': worker_name, 'status': status,
                        'section': worker_section, 'department': worker_department, 'shift': worker_shift
                    }

                if st.form_submit_button("Submit Attendance"):
                    if att_df.empty:
                        att_df = pd.DataFrame(columns=['ID','Worker_ID','Worker_Name','Date','Section','Department','Shift','Status','Timestamp'])
                    next_id = int(att_df['ID'].max())+1 if not att_df.empty and 'ID' in att_df.columns else 1
                    date_str = mark_date.strftime('%Y-%m-%d')
                    new_records = []

                    for wid, info in statuses.items():
                        if not existing_att.empty and "Worker_ID" in existing_att.columns:
                            existing_record = existing_att[existing_att["Worker_ID"].astype(str) == str(wid)]
                            if not existing_record.empty:
                                record_id = existing_record.iloc[0]["ID"]
                                att_df.loc[att_df["ID"] == record_id, "Status"] = info["status"]
                                att_df.loc[att_df["ID"] == record_id, "Timestamp"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            else:
                                new_records.append({
                                    'ID': next_id,
                                    'Worker_ID': wid,
                                    'Worker_Name': info['name'],
                                    'Date': date_str,
                                    'Section': info['section'],
                                    'Department': info['department'],
                                    'Shift': info['shift'],
                                    'Status': info['status'],
                                    'Timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                })
                                next_id += 1
                        else:
                            new_records.append({
                                'ID': next_id,
                                'Worker_ID': wid,
                                'Worker_Name': info['name'],
                                'Date': date_str,
                                'Section': info['section'],
                                'Department': info['department'],
                                'Shift': info['shift'],
                                'Status': info['status'],
                                'Timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            })
                            next_id += 1

                    if new_records:
                        new_att = pd.DataFrame(new_records)
                        att_df = pd.concat([att_df, new_att], ignore_index=True)

                    if write_table_replace("attendance", att_df):
                        st.success(f"Updated attendance for {len(filtered)} workers")
                        st.rerun()

    # TAB 2: Attendance Register (inline edit)
    with tab2:
        st.subheader("📊 Attendance Register")
        reg_date = st.date_input("Select Date for Register", datetime.date.today(), key="reg_date")

        col1, col2 = st.columns(2)
        with col1:
            reg_section = st.selectbox("Select Section", ["All"] + (sections_df['Name'].tolist() if not sections_df.empty else []), key="reg_section")
            if reg_section != "All" and not sections_df.empty:
                section_id = sections_df[sections_df['Name'] == reg_section]['ID'].values[0]
                dept_options = departments_df[departments_df['Section_ID'] == section_id]['Name'].tolist() if not departments_df.empty else []
            else:
                dept_options = ["All"]
            reg_department = st.selectbox("Select Department", dept_options, key="reg_department")
        with col2:
            reg_shift = st.selectbox("Select Shift", ["All"] + (shifts_df['Name'].tolist() if not shifts_df.empty else []), key="reg_shift")

        att = read_table("attendance")
        if not att.empty and "Date" in att.columns:
            att["Date"] = pd.to_datetime(att["Date"]).dt.date
            filtered = att[att["Date"] == reg_date]
            if reg_section != "All": filtered = filtered[filtered["Section"] == reg_section]
            if reg_department != "All": filtered = filtered[filtered["Department"] == reg_department]
            if reg_shift != "All": filtered = filtered[filtered["Shift"] == reg_shift]

            if not filtered.empty:
                st.write(f"### Attendance Register for {reg_date.strftime('%B %d, %Y')}")
                editable_df = filtered.copy()
                editable_df["Edit"] = False
                edited_df = st.data_editor(
                    editable_df[['Worker_Name','Section','Department','Shift','Status','Timestamp','Edit']],
                    use_container_width=True,
                    column_config={
                        "Worker_Name": st.column_config.TextColumn("Worker Name", disabled=True),
                        "Section": st.column_config.TextColumn("Section", disabled=True),
                        "Department": st.column_config.TextColumn("Department", disabled=True),
                        "Shift": st.column_config.TextColumn("Shift", disabled=True),
                        "Status": st.column_config.TextColumn("Status", disabled=True),
                        "Timestamp": st.column_config.TextColumn("Timestamp", disabled=True),
                        "Edit": st.column_config.CheckboxColumn("Edit for Changes")
                    },
                    hide_index=True
                )
                records_to_edit = edited_df[edited_df["Edit"] == True]
                if not records_to_edit.empty:
                    st.subheader("Edit Selected Records")
                    with st.form("edit_attendance_form"):
                        for idx, record in records_to_edit.iterrows():
                            worker_name = record["Worker_Name"]
                            current_status = record["Status"]
                            original_record = filtered[filtered["Worker_Name"] == worker_name]
                            if not original_record.empty:
                                record_id = original_record.iloc[0]["ID"]
                                new_status = st.radio(
                                    f"{worker_name} — New Status",
                                    ["Present","Absent","Late","Leave"],
                                    index=["Present","Absent","Late","Leave"].index(current_status) if current_status in ["Present","Absent","Late","Leave"] else 0,
                                    key=f"edit_status_{record_id}"
                                )
                                st.session_state[f"edit_status_{record_id}"] = new_status
                            st.divider()
                        if st.form_submit_button("Save Changes"):
                            att_df = read_table("attendance")
                            for idx, record in records_to_edit.iterrows():
                                worker_name = record["Worker_Name"]
                                original_record = filtered[filtered["Worker_Name"] == worker_name]
                                if not original_record.empty:
                                    record_id = original_record.iloc[0]["ID"]
                                    new_status = st.session_state[f"edit_status_{record_id}"]
                                    att_df.loc[att_df["ID"] == record_id, "Status"] = new_status
                                    att_df.loc[att_df["ID"] == record_id, "Timestamp"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            if write_table_replace("attendance", att_df):
                                st.success("Attendance records updated successfully!")
                                st.rerun()

                total = len(filtered)
                present = (filtered['Status'] == 'Present').sum()
                absent = (filtered['Status'] == 'Absent').sum()
                late = (filtered['Status'] == 'Late').sum()
                leave = (filtered['Status'] == 'Leave').sum()
                c1,c2,c3,c4 = st.columns(4)
                with c1: st.metric("Present", present, f"{present/total*100:.1f}%")
                with c2: st.metric("Absent", absent, f"{absent/total*100:.1f}%")
                with c3: st.metric("Late", late, f"{late/total*100:.1f}%")
                with c4: st.metric("Leave", leave, f"{leave/total*100:.1f}%")

                st.download_button(
                    "📥 Download Attendance CSV",
                    filtered.to_csv(index=False).encode("utf-8"),
                    file_name=f"attendance_{reg_date}.csv",
                    mime="text/csv"
                )
            else:
                st.info("No attendance records for selected filters.")
        else:
            st.info("No attendance data")

    # TAB 3: Transfer Workers
    with tab3:
        st.subheader("🔄 Transfer Workers")
        wdf = read_table("workers")
        for c, default in [("Active", True), ("Section",""), ("Department",""), ("Shift","")]:
            if c not in wdf.columns:
                wdf[c] = default
        if not wdf.empty:
            active = wdf[wdf["Active"].astype(str).str.lower().isin(["true","1","yes"])]
            if not active.empty:
                sel = st.selectbox("Select Worker", active["Name"].tolist(), key="transfer_worker")
                row = active[active["Name"] == sel].iloc[0]
                st.write(f"Current: {row.get('Section','')} / {row.get('Department','')} - {row.get('Shift','')}")
                col1, col2, _ = st.columns(3)
                with col1:
                    new_section = st.selectbox("New Section", sections_df['Name'].tolist(), key="new_section")
                    if new_section and not sections_df.empty:
                        section_id = sections_df[sections_df['Name'] == new_section]['ID'].values[0]
                        dept_options = departments_df[departments_df['Section_ID'] == section_id]['Name'].tolist() if not departments_df.empty else []
                    else:
                        dept_options = []
                    new_department = st.selectbox("New Department", dept_options, key="new_department")
                with col2:
                    new_shift = st.selectbox("New Shift", shifts_df['Name'].tolist() if not shifts_df.empty else [], key="new_shift")
                if st.button("Transfer Worker", key="transfer_btn"):
                    wdf.loc[wdf['ID']==row['ID'],'Section'] = new_section
                    wdf.loc[wdf['ID']==row['ID'],'Department'] = new_department
                    wdf.loc[wdf['ID']==row['ID'],'Shift'] = new_shift
                    write_table_replace("workers", wdf)
                    st.success("Transferred")
            else:
                st.info("No active workers")
        else:
            st.info("No workers found")

    # TAB 4: Manage Workers
    with tab4:
        st.subheader("👥 Manage Workers")
        wdf = read_table("workers")
        for c, default in [("Active", True), ("Section",""), ("Department",""), ("Shift","")]:
            if c not in wdf.columns:
                wdf[c] = default
        if not wdf.empty:
            for _, w in wdf.iterrows():
                tag = '✅' if str(w['Active']).lower() in ['true','1','yes'] else '❌'
                with st.expander(f"{tag} {w['Name']} - {w.get('Section','')} / {w.get('Department','')} ({w.get('Shift','')})"):
                    st.write(f"ID: {w['ID']}")
                    st.write(f"Section: {w.get('Section','')} | Department: {w.get('Department','')} | Shift: {w.get('Shift','')}")
                    col1, col2 = st.columns([3,1])
                    with col1:
                        if str(w['Active']).lower() in ['true','1','yes']:
                            if st.button("Deactivate", key=f"sup_deact_{w['ID']}"):
                                df = read_table("workers")
                                for c2, default2 in [("Active", True), ("Section",""), ("Department",""), ("Shift","")]:
                                    if c2 not in df.columns: df[c2] = default2
                                df.loc[df['ID']==w['ID'],'Active'] = False
                                write_table_replace("workers", df)
                                st.rerun()
                        else:
                            if st.button("Activate", key=f"sup_act_{w['ID']}"):
                                df = read_table("workers")
                                for c2, default2 in [("Active", True), ("Section",""), ("Department",""), ("Shift","")]:
                                    if c2 not in df.columns: df[c2] = default2
                                df.loc[df['ID']==w['ID'],'Active'] = True
                                write_table_replace("workers", df)
                                st.rerun()
                    with col2:
                        if st.button("🗑️ Delete", key=f"sup_del_{w['ID']}"):
                            df = read_table("workers")
                            df = df[df['ID'] != w['ID']]
                            write_table_replace("workers", df)
                            st.rerun()
        else:
            st.info("No workers found")

    # TAB 5: View Attendance quick
    with tab5:
        st.subheader("📅 View Attendance")
        att = read_table("attendance")
        if not att.empty and "Date" in att.columns:
            att["Date"] = pd.to_datetime(att["Date"]).dt.date
            view_date = st.date_input("Date", datetime.date.today(), key="sup_view_date")
            view_section = st.selectbox("Section", ["All"] + (sections_df['Name'].tolist() if not sections_df.empty else []), key="sup_view_section")
            if view_section != "All" and not sections_df.empty:
                section_id = sections_df[sections_df['Name'] == view_section]['ID'].values[0]
                dept_options = departments_df[departments_df['Section_ID'] == section_id]['Name'].tolist() if not departments_df.empty else []
            else:
                dept_options = ["All"]
            view_department = st.selectbox("Department", dept_options, key="sup_view_department")
            view_shift = st.selectbox("Shift", ["All"] + (shifts_df['Name'].tolist() if not shifts_df.empty else []), key="sup_view_shift")

            filtered = att[att["Date"] == view_date]
            if view_section != "All": filtered = filtered[filtered["Section"] == view_section]
            if view_department != "All": filtered = filtered[filtered["Department"] == view_department]
            if view_shift != "All": filtered = filtered[filtered["Shift"] == view_shift]

            if not filtered.empty:
                st.write(f"### Attendance Register - {view_date.strftime('%B %d, %Y')}")
                st.dataframe(filtered[['Worker_Name','Section','Department','Shift','Status','Timestamp']], use_container_width=True)
                total = len(filtered)
                present = (filtered['Status']=='Present').sum()
                absent = (filtered['Status']=='Absent').sum()
                late = (filtered['Status']=='Late').sum()
                leave = (filtered['Status']=='Leave').sum()
                c1,c2,c3,c4 = st.columns(4)
                with c1: st.metric("Present", present, f"{present/total*100:.1f}%")
                with c2: st.metric("Absent", absent, f"{absent/total*100:.1f}%")
                with c3: st.metric("Late", late, f"{late/total*100:.1f}%")
                with c4: st.metric("Leave", leave, f"{leave/total*100:.1f}%")
            else:
                st.info("No records found")
        else:
            st.info("No attendance data or 'Date' column missing.")

    # TAB 6: Attendance Grid
    with tab6:
        st.subheader("📊 Attendance Grid")
        col1, col2 = st.columns(2)
        with col1:
            year = st.selectbox("Year", list(range(2020, datetime.date.today().year + 2)),
                                index=list(range(2020, datetime.date.today().year + 2)).index(datetime.date.today().year),
                                key="sup_grid_year")
        with col2:
            month = st.selectbox("Month", list(range(1, 13)),
                                 index=datetime.date.today().month - 1,
                                 key="sup_grid_month")
        grid_df = generate_attendance_grid(year, month)
        if not grid_df.empty:
            st.markdown('<div class="attendance-grid">', unsafe_allow_html=True)
            st.dataframe(grid_df, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            st.download_button(
                "📥 Download Attendance Grid",
                data=dataframe_to_excel_bytes(grid_df),
                file_name=f"attendance_grid_{year}_{month}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("No attendance data available for the selected period.")

# ----------------- HR DASHBOARD ---------------------------

def hr_dashboard():
    st.title("📊 HR Dashboard")
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Daily","📅 Monthly","👥 Directory", "📊 Attendance Grid"])
    workers_df = read_table("workers")
    attendance_df = read_table("attendance")

    for c, default in [("Active", True), ("Section",""), ("Department",""), ("Shift","")]:
        if c not in workers_df.columns:
            workers_df[c] = default

    with tab1:
        st.subheader("📊 Daily Attendance")
        view_date = st.date_input("Date", datetime.date.today(), key="hr_daily_date")
        if not attendance_df.empty and "Date" in attendance_df.columns:
            attendance_df["Date"] = pd.to_datetime(attendance_df["Date"]).dt.date
            filtered = attendance_df[attendance_df["Date"] == view_date]
            if not filtered.empty:
                st.dataframe(filtered[['Worker_Name','Section','Department','Shift','Status','Timestamp']], use_container_width=True)
                total = len(filtered)
                present = (filtered['Status']=='Present').sum()
                absent = (filtered['Status']=='Absent').sum()
                late = (filtered['Status']=='Late').sum()
                leave = (filtered['Status']=='Leave').sum()
                c1,c2,c3,c4 = st.columns(4)
                with c1: st.metric("Present", present, f"{present/total*100:.1f}%")
                with c2: st.metric("Absent", absent, f"{absent/total*100:.1f}%")
                with c3: st.metric("Late", late, f"{late/total*100:.1f}%")
                with c4: st.metric("Leave", leave, f"{leave/total*100:.1f}%")
            else:
                st.info("No attendance records for date")
        else:
            st.info("No attendance data")

    with tab2:
        st.subheader("📅 Monthly Analysis")
        year = st.selectbox("Year", list(range(2020, datetime.date.today().year+2)),
                            index=list(range(2020, datetime.date.today().year+2)).index(datetime.date.today().year),
                            key="hr_monthly_year")
        month = st.selectbox("Month", list(range(1,13)),
                             index=datetime.date.today().month-1,
                             key="hr_monthly_month")
        if not attendance_df.empty and "Date" in attendance_df.columns:
            attendance_df["Date"] = pd.to_datetime(attendance_df["Date"])
            monthly = attendance_df[
                (attendance_df["Date"].dt.year == year) &
                (attendance_df["Date"].dt.month == month)
            ]
            if not monthly.empty:
                worker_stats = monthly.groupby('Worker_Name').agg(
                    Present=('Status', lambda x: (x=='Present').sum()),
                    Absent=('Status', lambda x: (x=='Absent').sum()),
                    Late=('Status', lambda x: (x=='Late').sum()),
                    Leave=('Status', lambda x: (x=='Leave').sum()),
                    Total=('Status', 'count')
                ).reset_index()
                worker_stats['Attendance %'] = (worker_stats['Present'] / worker_stats['Total'] * 100).round(1)

                worker_details = workers_df[['Name','Section','Department','Shift']].copy()
                worker_stats = worker_stats.merge(
                    worker_details, left_on='Worker_Name', right_on='Name', how='left'
                ).drop('Name', axis=1)

                st.dataframe(worker_stats, use_container_width=True)

                total_records = len(monthly)
                total_present = (monthly['Status']=='Present').sum()
                total_absent = (monthly['Status']=='Absent').sum()
                total_late = (monthly['Status']=='Late').sum()
                total_leave = (monthly['Status']=='Leave').sum()
                c1,c2,c3,c4 = st.columns(4)
                with c1: st.metric("Total Records", total_records)
                with c2: st.metric("Present", total_present, f"{total_present/total_records*100:.1f}%")
                with c3: st.metric("Absent", total_absent, f"{total_absent/total_records*100:.1f}%")
                with c4: st.metric("Late", total_late, f"{total_late/total_records*100:.1f}%")

                st.download_button(
                    "📥 Download Monthly Report",
                    worker_stats.to_csv(index=False).encode("utf-8"),
                    file_name=f"monthly_attendance_{year}_{month}.csv",
                    mime="text/csv"
                )
            else:
                st.info("No attendance records for selected month")
        else:
            st.info("No attendance data")

    with tab3:
        st.subheader("👥 Worker Directory")
        if not workers_df.empty:
            workers_df['Active'] = workers_df['Active'].astype(str)
            active_workers = workers_df[workers_df['Active'].str.lower().isin(['true','1','yes'])]
            if not active_workers.empty:
                st.dataframe(
                    active_workers[['Name','Section','Department','Shift']],
                    use_container_width=True,
                    hide_index=True
                )
                st.download_button(
                    "📥 Download Worker Directory",
                    dataframe_to_excel_bytes(active_workers[['Name','Section','Department','Shift']]),
                    file_name="worker_directory.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.info("No active workers found")
        else:
            st.info("No workers found")

    with tab4:
        st.subheader("📊 Attendance Grid")
        col1, col2 = st.columns(2)
        with col1:
            year = st.selectbox("Year", list(range(2020, datetime.date.today().year + 2)),
                                index=list(range(2020, datetime.date.today().year + 2)).index(datetime.date.today().year),
                                key="hr_grid_year")
        with col2:
            month = st.selectbox("Month", list(range(1, 13)),
                                 index=datetime.date.today().month - 1,
                                 key="hr_grid_month")
        grid_df = generate_attendance_grid(year, month)
        if not grid_df.empty:
            st.markdown('<div class="attendance-grid">', unsafe_allow_html=True)
            st.dataframe(grid_df, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            st.download_button(
                "📥 Download Attendance Grid",
                dataframe_to_excel_bytes(grid_df),
                file_name=f"attendance_grid_{year}_{month}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("No attendance data available for the selected period.")

# ----------------- LOGIN PAGE ----------------------------

def login_page():
    st.title("🔐 Company Attendance System")
    st.markdown("---")
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.subheader("Login")
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        if st.button("Login", type="primary", use_container_width=True):
            if login(username, password):
                st.success(f"Welcome, {username}!")
                time.sleep(0.7)
                st.rerun()
            else:
                st.error("Invalid credentials or account inactive")

# ----------------- MAIN ---------------------------------

def main():
    st.markdown(mobile_css(), unsafe_allow_html=True)

    # Ensure DB & seed BEFORE any UI
    initialize_databases()
    seed_defaults()

    # Sidebar status + sync
    with st.sidebar:
        if is_online():
            nw, na = sync_from_sqlite_to_supabase()
            eng = get_online_engine_or_none()
            with eng.connect() as conn:
                now = conn.execute(text("SELECT NOW()")).scalar()
            st.success(f"🟢 Online (Supabase Pooler)\n{now}")
            if nw or na:
                st.info(f"Synced: {nw} worker(s), {na} attendance record(s)")
        else:
            eng = get_offline_engine()
            with eng.connect() as conn:
                now = conn.execute(text("SELECT datetime('now')")).scalar()
            st.warning(f"🔵 Offline (SQLite)\n{now}")

        if st.button("🔄 Sync Now"):
            if is_online():
                nw, na = sync_from_sqlite_to_supabase()
                st.success(f"Synced {nw} worker(s), {na} attendance record(s)")
            else:
                st.info("Still offline — will sync when online.")

        st.markdown("---")
        if st.session_state.get("logged_in"):
            st.write(f"👤 {st.session_state['username']} ({st.session_state['role']})")
            if st.button("Logout"):
                logout()
                st.rerun()

    if not st.session_state.get("logged_in"):
        login_page()
        return

    role = st.session_state.get("role","Admin")
    if role == "Admin":
        admin_dashboard()
    elif role == "Supervisor":
        supervisor_dashboard()
    elif role == "HR":
        hr_dashboard()
    else:
        st.error("Invalid role")

if __name__ == "__main__":
    main()
