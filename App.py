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

# ==========================================================
# CONFIG — Hybrid DB: Supabase (Pooler) when online, SQLite when offline
# ==========================================================

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
            if "postgresql" in str(engine.url):
                conn.execute(text("SELECT NOW()"))
            else:
                conn.execute(text("SELECT datetime('now')"))
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
    # touch/connect
    try:
        with eng.connect() as _:
            pass
    except Exception:
        pass
    return eng

def is_online() -> bool:
    e = get_online_engine_or_none()
    return e is not None

# ==========================================================
# DB INIT (public schema for both stores)
# ==========================================================

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

def seed_defaults(engine):
    # shifts
    rows = engine.execute(text("SELECT COUNT(*) FROM shifts")).scalar()
    if rows == 0:
        engine.execute(text("INSERT INTO shifts (Name) VALUES ('Morning'), ('Afternoon'), ('General')"))
    # sections
    rows = engine.execute(text("SELECT COUNT(*) FROM sections")).scalar()
    if rows == 0:
        engine.execute(text("""
            INSERT INTO sections (Name, Description) VALUES
            ('Liquid Section','Liquid manufacturing'),
            ('Solid Section','Solid manufacturing'),
            ('Utility Section','Utility services')
        """))
    # departments
    rows = engine.execute(text("SELECT COUNT(*) FROM departments")).scalar()
    if rows == 0:
        engine.execute(text("""
            INSERT INTO departments (Name, Section_ID, Description) VALUES
            ('Mixing', 1, 'Mixing dept'),
            ('Filling', 1, 'Filling dept'),
            ('Packaging', 2, 'Packaging dept'),
            ('Maintenance', 3, 'Maintenance dept')
        """))
    # users (default admin)
    rows = engine.execute(text("SELECT COUNT(*) FROM users")).scalar()
    if rows == 0:
        hashed = bcrypt.hashpw("admin123".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        engine.execute(
            text("""INSERT INTO users (Name, Username, Password, Role, Active, Assigned_Section, Assigned_Shift)
                    VALUES (:n, :u, :p, :r, :a, :s, :sh)"""),
            {"n":"Admin User","u":"admin","p":hashed,"r":"Admin","a":True,"s":"","sh":""}
        )

def ensure_seed_data():
    # seed offline DB
    off = get_offline_engine()
    with off.begin() as conn:
        seed_defaults(conn)
    # seed online if possible
    on = get_online_engine_or_none()
    if on:
        with on.begin() as conn:
            seed_defaults(conn)

# ==========================================================
# READ/WRITE helpers (auto select engine)
# ==========================================================

def current_engine():
    return get_online_engine_or_none() or get_offline_engine()

def read_table(table):
    eng = current_engine()
    try:
        df = pd.read_sql(f"SELECT * FROM {table}", eng)
        return df
    except Exception as e:
        # Table missing or schema mismatch → rebuild everything
        st.warning(f"⚙️ Rebuilding tables... ({table} missing or invalid)")
        try:
            initialize_databases()
            ensure_seed_data()
            df = pd.read_sql(f"SELECT * FROM {table}", eng)
            return df
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

# ==========================================================
# OFFLINE → ONLINE SYNC (simple, best-effort)
# ==========================================================

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
        # dedupe key: Name+Section+Department+Shift
        if not off_workers.empty:
            merged = off_workers.merge(
                on_workers, how="left",
                on=["Name","Section","Department","Shift"],
                indicator=True, suffixes=("","_on")
            )
            to_add = merged[merged["_merge"] == "left_only"][["Name","Section","Department","Shift","Active"]]
            if not to_add.empty:
                # normalize Active to bool for PG
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
            # normalize date to yyyy-mm-dd
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

# ==========================================================
# UTILITIES
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
            g.at[idx[0], str(d)] = "✓" if s=="Present" else ("✗" if s=="Absent" else s[:1])
    pres = []; perc=[]
    for _, row in g.iterrows():
        p = sum(1 for d in range(1,days+1) if row[str(d)]=="✓")
        pres.append(p); perc.append(round(p/days*100,1))
    g["Present Days"] = pres; g["Attendance %"] = perc
    return g

# ==========================================================
# AUTH
# ==========================================================

def login(username, password) -> bool:
    eng = current_engine()
    with eng.connect() as conn:
        res = conn.execute(text("SELECT ID, Password, Role, Active FROM users WHERE Username=:u"), {"u":username}).fetchone()
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

# ==========================================================
# PAGES — Admin / Supervisor / HR
# ==========================================================

def admin_dashboard():
    st.title("🔧 Admin Dashboard")
    tabs = st.tabs(["👥 Users","🏭 Sections","🏢 Departments","👷 Workers","📊 Attendance","🗑️ Delete Data"])

    # USERS
    with tabs[0]:
        st.subheader("User Management")
        df = read_table("users")
        colA, colB = st.columns([1.2,2])
        with colA:
            st.markdown("#### ➕ Add User")
            with st.form("add_user"):
                name = st.text_input("Full Name")
                uname = st.text_input("Username")
                pwd = st.text_input("Password", type="password")
                role = st.selectbox("Role", ["Admin","Supervisor","HR"])
                asec = st.text_input("Assigned Section (optional)")
                ashi = st.text_input("Assigned Shift (optional)")
                if st.form_submit_button("Add"):
                    if name and uname and pwd:
                        hashed = bcrypt.hashpw(pwd.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                        next_id = int(df["ID"].max())+1 if (not df.empty and "ID" in df.columns) else 1
                        row = pd.DataFrame([{"ID":next_id,"Name":name,"Username":uname,"Password":hashed,
                                            "Role":role,"Active":True,"Assigned_Section":asec,"Assigned_Shift":ashi}])
                        df = pd.concat([df, row], ignore_index=True)
                        if write_table_replace("users", df): st.success("User added"); st.rerun()
                    else:
                        st.error("Fill all fields")
        with colB:
            st.markdown("#### 📋 Users")
            if df.empty: st.info("No users"); 
            else:
                expected_cols = ["ID","Name","Username","Role","Active","Assigned_Section","Assigned_Shift"]
missing = [c for c in expected_cols if c not in df.columns]
if missing:
    st.warning(f"Rebuilding users table (missing columns: {', '.join(missing)})")
    initialize_databases()
    ensure_seed_data()
    df = read_table("users")
if not df.empty:
    st.dataframe(df[[c for c in expected_cols if c in df.columns]], use_container_width=True)
else:
    st.info("No users found yet. Default admin = admin / admin123")

    # SECTIONS
    with tabs[1]:
        st.subheader("Sections")
        df = read_table("sections")
        colA, colB = st.columns([1.2,2])
        with colA:
            with st.form("add_section"):
                n = st.text_input("Section Name")
                d = st.text_area("Description")
                if st.form_submit_button("Add Section"):
                    if n:
                        next_id = int(df["ID"].max())+1 if (not df.empty and "ID" in df.columns) else 1
                        row = pd.DataFrame([{"ID":next_id,"Name":n,"Description":d}])
                        out = pd.concat([df, row], ignore_index=True)
                        if write_table_replace("sections", out): st.success("Added"); st.rerun()
                    else: st.error("Enter name")
        with colB:
            st.dataframe(df, use_container_width=True)

    # DEPARTMENTS
    with tabs[2]:
        st.subheader("Departments")
        secs = read_table("sections")
        df = read_table("departments")
        colA, colB = st.columns([1.2,2])
        with colA:
            with st.form("add_dept"):
                n = st.text_input("Department Name")
                sec_id = st.selectbox("Section", secs["ID"].tolist() if not secs.empty else [])
                d = st.text_area("Description")
                if st.form_submit_button("Add Department"):
                    if n and sec_id:
                        next_id = int(df["ID"].max())+1 if (not df.empty and "ID" in df.columns) else 1
                        row = pd.DataFrame([{"ID":next_id,"Name":n,"Section_ID":sec_id,"Description":d}])
                        out = pd.concat([df,row], ignore_index=True)
                        if write_table_replace("departments", out): st.success("Added"); st.rerun()
                    else: st.error("Enter name & section")
        with colB:
            if df.empty: st.info("No departments")
            else:
                merged = df.merge(secs[["ID","Name"]], left_on="Section_ID", right_on="ID", how="left", suffixes=("","_sec"))
                merged = merged.rename(columns={"Name":"Department","Name_sec":"Section"}).drop(columns=["ID_sec"])
                st.dataframe(merged[["ID","Department","Section","Description"]], use_container_width=True)

    # WORKERS
    with tabs[3]:
        st.subheader("Workers")
        secs = read_table("sections"); depts = read_table("departments"); shf = read_table("shifts")
        wdf = read_table("workers")
        for c, default in [("Active",True),("Section",""),("Department",""),("Shift","")]:
            if c not in wdf.columns: wdf[c]=default

        colL, colR = st.columns([1.2,2])
        with colL:
            st.download_button("⬇️ Workers Template", data=worker_template_bytes(),
                               file_name="workers_template.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            up = st.file_uploader("Upload Workers (Excel/CSV)", type=["xlsx","csv"])
            if up:
                try:
                    newdf = pd.read_excel(up) if up.name.endswith(".xlsx") else pd.read_csv(up)
                    need = {"Name","Section","Department","Shift"}
                    if not need.issubset(set(newdf.columns)): st.error(f"Missing columns. Need: {', '.join(sorted(need))}")
                    else:
                        def dup(r):
                            return ((wdf["Name"]==r["Name"])&(wdf["Section"]==r["Section"])&
                                    (wdf["Department"]==r["Department"])&(wdf["Shift"]==r["Shift"])).any()
                        nxt = int(wdf["ID"].max())+1 if (not wdf.empty and "ID" in wdf.columns) else 1
                        adds=[]
                        for _, r in newdf.iterrows():
                            if not dup(r):
                                adds.append({"ID":nxt,"Name":str(r["Name"]).strip(),"Section":str(r["Section"]).strip(),
                                             "Department":str(r["Department"]).strip(),"Shift":str(r["Shift"]).strip(),
                                             "Active":True})
                                nxt+=1
                        if adds:
                            out = pd.concat([wdf, pd.DataFrame(adds)], ignore_index=True)
                            if write_table_replace("workers", out): st.success(f"Added {len(adds)}"); st.rerun()
                        else:
                            st.info("No new workers to add.")
                except Exception as e:
                    st.error(f"Read error: {e}")

            st.markdown("#### ➕ Add Single Worker")
            with st.form("add_single_worker"):
                nm = st.text_input("Name")
                sec = st.selectbox("Section", secs["Name"].tolist() if not secs.empty else [])
                if sec and not secs.empty:
                    sec_id = secs[secs["Name"]==sec]["ID"].values[0]
                    dept_opts = depts[depts["Section_ID"]==sec_id]["Name"].tolist() if not depts.empty else []
                else:
                    dept_opts=[]
                dep = st.selectbox("Department", dept_opts)
                shi = st.selectbox("Shift", shf["Name"].tolist() if not shf.empty else [])
                if st.form_submit_button("Add"):
                    if nm and sec and dep and shi:
                        nxt = int(wdf["ID"].max())+1 if (not wdf.empty and "ID" in wdf.columns) else 1
                        row = pd.DataFrame([{"ID":nxt,"Name":nm,"Section":sec,"Department":dep,"Shift":shi,"Active":True}])
                        out = pd.concat([wdf,row], ignore_index=True)
                        if write_table_replace("workers", out): st.success("Added"); st.rerun()
                    else: st.error("Fill all fields")

        with colR:
            st.write(f"**Total workers:** {len(wdf)}")
            st.download_button("📥 Download Workers", data=dataframe_to_excel_bytes(wdf),
                               file_name="workers.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            st.dataframe(wdf, use_container_width=True)

    # ATTENDANCE (view)
    with tabs[4]:
        st.subheader("Attendance Records")
        att = read_table("attendance")
        if not att.empty and "Date" in att.columns:
            att["Date"] = pd.to_datetime(att["Date"]).dt.date
            d = st.date_input("Date", datetime.date.today())
            f = att[att["Date"]==d]
            if not f.empty:
                st.dataframe(f[["Worker_Name","Section","Department","Shift","Status","Timestamp"]], use_container_width=True)
                tot=len(f); p=(f["Status"]=="Present").sum(); a=(f["Status"]=="Absent").sum()
                l=(f["Status"]=="Late").sum(); le=(f["Status"]=="Leave").sum()
                c1,c2,c3,c4=st.columns(4)
                with c1: st.metric("Present", p, f"{p/tot*100:.1f}%")
                with c2: st.metric("Absent", a, f"{a/tot*100:.1f}%")
                with c3: st.metric("Late", l, f"{l/tot*100:.1f}%")
                with c4: st.metric("Leave", le, f"{le/tot*100:.1f}%")
            else: st.info("No records for that date.")
        else: st.info("No attendance yet.")

    # DELETE DATA
    with tabs[5]:
        st.warning("Danger Zone")
        if st.button("Clear Attendance"):
            write_table_replace("attendance", pd.DataFrame(columns=["ID","Worker_ID","Worker_Name","Date","Section","Department","Shift","Status","Timestamp"]))
            st.success("Cleared")
        if st.button("Clear Workers"):
            write_table_replace("workers", pd.DataFrame(columns=["ID","Name","Section","Department","Shift","Active"]))
            st.success("Cleared")

def supervisor_dashboard():
    st.title("👷 Supervisor Dashboard")
    tabs = st.tabs(["✅ Mark Attendance","📊 Register","🔄 Transfer Workers","👥 Manage Workers","📅 View Attendance","📊 Monthly Grid"])
    secs = read_table("sections"); depts = read_table("departments"); shf = read_table("shifts")
    wdf = read_table("workers")
    for c, d in [("Active",True),("Section",""),("Department",""),("Shift","")]:
        if c not in wdf.columns: wdf[c]=d

    # MARK
    with tabs[0]:
        st.subheader("Mark Attendance")
        mark_date = st.date_input("Date", datetime.date.today())
        col1, col2 = st.columns(2)
        with col1:
            sec = st.selectbox("Section", ["All"]+(secs["Name"].tolist() if not secs.empty else []))
            if sec!="All" and not secs.empty:
                sid = secs[secs["Name"]==sec]["ID"].values[0]
                dept_opts = depts[depts["Section_ID"]==sid]["Name"].tolist() if not depts.empty else []
            else:
                dept_opts=["All"]
            dep = st.selectbox("Department", dept_opts)
        with col2:
            shi = st.selectbox("Shift", ["All"]+(shf["Name"].tolist() if not shf.empty else []))

        active = wdf[wdf["Active"].astype(str).str.lower().isin(["true","1","yes"])]
        if sec!="All": active=active[active["Section"]==sec]
        if dep!="All": active=active[active["Department"]==dep]
        if shi!="All": active=active[active["Shift"]==shi]

        if active.empty:
            st.info("No active workers for selected filters.")
        else:
            att = read_table("attendance")
            if not att.empty and "Date" in att.columns:
                att["Date"]=pd.to_datetime(att["Date"]).dt.date
                existing = att[(att["Date"]==mark_date)&(att["Worker_ID"].astype(str).isin(active["ID"].astype(str)))]
            else:
                existing = pd.DataFrame()
            statuses={}
            with st.form("mark_form"):
                for _, r in active.iterrows():
                    default = 0
                    if not existing.empty:
                        row = existing[existing["Worker_ID"].astype(str)==str(r["ID"])]
                        if not row.empty and "Status" in row.columns:
                            s=row.iloc[0]["Status"]
                            default = ["Present","Absent","Late","Leave"].index(s) if s in ["Present","Absent","Late","Leave"] else 0
                    st.write(f"**{r['Name']}** — {r['Section']}/{r['Department']}/{r['Shift']}")
                    s = st.radio("Status", ["Present","Absent","Late","Leave"], index=default, horizontal=True, label_visibility="collapsed", key=f"stat_{r['ID']}")
                    statuses[int(r["ID"])]={
                        "name":r["Name"],"section":r["Section"],"department":r["Department"],"shift":r["Shift"],"status":s
                    }
                if st.form_submit_button("Save"):
                    att_df = read_table("attendance")
                    if att_df.empty:
                        att_df = pd.DataFrame(columns=["ID","Worker_ID","Worker_Name","Date","Section","Department","Shift","Status","Timestamp"])
                    next_id = int(att_df["ID"].max())+1 if (not att_df.empty and "ID" in att_df.columns) else 1
                    dstr = mark_date.strftime("%Y-%m-%d")
                    new_rows=[]
                    for wid, info in statuses.items():
                        if not existing.empty:
                            ex = existing[existing["Worker_ID"].astype(str)==str(wid)]
                            if not ex.empty:
                                rid = ex.iloc[0]["ID"]
                                att_df.loc[att_df["ID"]==rid, "Status"]=info["status"]
                                att_df.loc[att_df["ID"]==rid, "Timestamp"]=datetime.datetime.now()
                            else:
                                new_rows.append({"ID":next_id,"Worker_ID":wid,"Worker_Name":info["name"],"Date":dstr,
                                                 "Section":info["section"],"Department":info["department"],"Shift":info["shift"],
                                                 "Status":info["status"],"Timestamp":datetime.datetime.now()})
                                next_id+=1
                        else:
                            new_rows.append({"ID":next_id,"Worker_ID":wid,"Worker_Name":info["name"],"Date":dstr,
                                             "Section":info["section"],"Department":info["department"],"Shift":info["shift"],
                                             "Status":info["status"],"Timestamp":datetime.datetime.now()})
                            next_id+=1
                    if new_rows:
                        att_df = pd.concat([att_df, pd.DataFrame(new_rows)], ignore_index=True)
                    if write_table_replace("attendance", att_df):
                        st.success("Attendance saved"); st.rerun()

    # REGISTER
    with tabs[1]:
        st.subheader("Attendance Register")
        d = st.date_input("Date", datetime.date.today())
        sec = st.selectbox("Section", ["All"]+(secs["Name"].tolist() if not secs.empty else []), key="reg_sec")
        if sec!="All" and not secs.empty:
            sid = secs[secs["Name"]==sec]["ID"].values[0]
            dept_opts = depts[depts["Section_ID"]==sid]["Name"].tolist() if not depts.empty else []
        else:
            dept_opts=["All"]
        dep = st.selectbox("Department", dept_opts, key="reg_dep")
        shi = st.selectbox("Shift", ["All"]+(shf["Name"].tolist() if not shf.empty else []), key="reg_shi")
        att = read_table("attendance")
        if not att.empty and "Date" in att.columns:
            att["Date"]=pd.to_datetime(att["Date"]).dt.date
            f = att[att["Date"]==d]
            if sec!="All": f=f[f["Section"]==sec]
            if dep!="All": f=f[f["Department"]==dep]
            if shi!="All": f=f[f["Shift"]==shi]
            if not f.empty:
                st.dataframe(f[["Worker_Name","Section","Department","Shift","Status","Timestamp"]], use_container_width=True)
                tot=len(f); p=(f["Status"]=="Present").sum(); a=(f["Status"]=="Absent").sum()
                l=(f["Status"]=="Late").sum(); le=(f["Status"]=="Leave").sum()
                c1,c2,c3,c4=st.columns(4)
                with c1: st.metric("Present", p, f"{p/tot*100:.1f}%")
                with c2: st.metric("Absent", a, f"{a/tot*100:.1f}%")
                with c3: st.metric("Late", l, f"{l/tot*100:.1f}%")
                with c4: st.metric("Leave", le, f"{le/tot*100:.1f}%")
                st.download_button("📥 Download CSV", data=f.to_csv(index=False).encode("utf-8"),
                                   file_name=f"attendance_{d}.csv", mime="text/csv")
            else: st.info("No records for filters.")
        else: st.info("No attendance yet.")

    # TRANSFER
    with tabs[2]:
        st.subheader("Transfer Workers")
        w = read_table("workers")
        if w.empty: st.info("No workers"); 
        else:
            act = w[w["Active"].astype(str).str.lower().isin(["true","1","yes"])]
            if act.empty: st.info("No active workers")
            else:
                name = st.selectbox("Worker", act["Name"].tolist())
                row = act[act["Name"]==name].iloc[0]
                st.write(f"Current: {row['Section']} / {row['Department']} — {row['Shift']}")
                ns = st.selectbox("New Section", secs["Name"].tolist() if not secs.empty else [])
                if ns and not secs.empty:
                    sid = secs[secs["Name"]==ns]["ID"].values[0]
                    nd = depts[depts["Section_ID"]==sid]["Name"].tolist() if not depts.empty else []
                else:
                    nd=[]
                ndp = st.selectbox("New Department", nd)
                nsh = st.selectbox("New Shift", shf["Name"].tolist() if not shf.empty else [])
                if st.button("Transfer"):
                    w.loc[w["ID"]==row["ID"], ["Section","Department","Shift"]] = [ns, ndp, nsh]
                    if write_table_replace("workers", w): st.success("Transferred"); st.rerun()

    # Manage workers (quick activate/deactivate/delete)
    with tabs[3]:
        st.subheader("Manage Workers")
        w = read_table("workers")
        if w.empty: st.info("No workers")
        else:
            for _, r in w.iterrows():
                tag = "✅" if str(r["Active"]).lower() in ["true","1","yes"] else "❌"
                with st.expander(f"{tag} {r['Name']} — {r['Section']}/{r['Department']} ({r['Shift']})"):
                    col1, col2 = st.columns(2)
                    with col1:
                        togg = st.button("Deactivate" if tag=="✅" else "Activate", key=f"toggle_{r['ID']}")
                        if togg:
                            w.loc[w["ID"]==r["ID"], "Active"] = not (tag=="✅")
                            if write_table_replace("workers", w): st.rerun()
                    with col2:
                        if st.button("🗑️ Delete", key=f"del_{r['ID']}"):
                            w2 = w[w["ID"]!=r["ID"]]
                            if write_table_replace("workers", w2): st.rerun()

    # View attendance
    with tabs[4]:
        st.subheader("View Attendance")
        att = read_table("attendance")
        if not att.empty and "Date" in att.columns:
            att["Date"]=pd.to_datetime(att["Date"]).dt.date
            d = st.date_input("Date", datetime.date.today(), key="sv_view_d")
            sec = st.selectbox("Section", ["All"]+(secs["Name"].tolist() if not secs.empty else []), key="sv_view_s")
            if sec!="All" and not secs.empty:
                sid = secs[secs["Name"]==sec]["ID"].values[0]
                dept_opts = depts[depts["Section_ID"]==sid]["Name"].tolist() if not depts.empty else []
            else:
                dept_opts=["All"]
            dep = st.selectbox("Department", dept_opts, key="sv_view_dp")
            shi = st.selectbox("Shift", ["All"]+(shf["Name"].tolist() if not shf.empty else []), key="sv_view_sh")
            f = att[att["Date"]==d]
            if sec!="All": f=f[f["Section"]==sec]
            if dep!="All": f=f[f["Department"]==dep]
            if shi!="All": f=f[f["Shift"]==shi]
            if not f.empty:
                st.dataframe(f[["Worker_Name","Section","Department","Shift","Status","Timestamp"]], use_container_width=True)
            else: st.info("No records for filters.")
        else: st.info("No attendance yet.")

    # Grid
    with tabs[5]:
        st.subheader("Monthly Attendance Grid")
        col1, col2 = st.columns(2)
        with col1:
            year = st.selectbox("Year", list(range(2020, datetime.date.today().year+2)),
                                index=list(range(2020, datetime.date.today().year+2)).index(datetime.date.today().year))
        with col2:
            month = st.selectbox("Month", list(range(1,13)), index=datetime.date.today().month-1)
        g = generate_attendance_grid(year, month)
        if g.empty: st.info("No data for period.")
        else:
            st.markdown('<div class="attendance-grid">', unsafe_allow_html=True)
            st.dataframe(g, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            st.download_button("📥 Download Grid", data=dataframe_to_excel_bytes(g),
                               file_name=f"attendance_grid_{year}_{month}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

def hr_dashboard():
    st.title("📊 HR Dashboard")
    tabs = st.tabs(["📊 Daily","📅 Monthly","👥 Directory","📊 Monthly Grid"])
    workers = read_table("workers")
    att = read_table("attendance")

    # Daily
    with tabs[0]:
        st.subheader("Daily")
        if not att.empty and "Date" in att.columns:
            att["Date"]=pd.to_datetime(att["Date"]).dt.date
            d = st.date_input("Date", datetime.date.today(), key="hr_d")
            f = att[att["Date"]==d]
            if not f.empty:
                st.dataframe(f[["Worker_Name","Section","Department","Shift","Status","Timestamp"]], use_container_width=True)
                tot=len(f); p=(f["Status"]=="Present").sum(); a=(f["Status"]=="Absent").sum()
                l=(f["Status"]=="Late").sum(); le=(f["Status"]=="Leave").sum()
                c1,c2,c3,c4=st.columns(4)
                with c1: st.metric("Present", p, f"{p/tot*100:.1f}%")
                with c2: st.metric("Absent", a, f"{a/tot*100:.1f}%")
                with c3: st.metric("Late", l, f"{l/tot*100:.1f}%")
                with c4: st.metric("Leave", le, f"{le/tot*100:.1f}%")
            else: st.info("No records for date.")
        else: st.info("No attendance yet.")

    # Monthly
    with tabs[1]:
        st.subheader("Monthly")
        if not att.empty and "Date" in att.columns:
            att["Date"]=pd.to_datetime(att["Date"])
            year = st.selectbox("Year", list(range(2020, datetime.date.today().year+2)),
                                index=list(range(2020, datetime.date.today().year+2)).index(datetime.date.today().year),
                                key="hr_y")
            month = st.selectbox("Month", list(range(1,13)), index=datetime.date.today().month-1, key="hr_m")
            m = att[(att["Date"].dt.year==year)&(att["Date"].dt.month==month)]
            if not m.empty:
                stats = m.groupby("Worker_Name").agg(
                    Present=("Status", lambda x: (x=="Present").sum()),
                    Absent=("Status", lambda x: (x=="Absent").sum()),
                    Late=("Status", lambda x: (x=="Late").sum()),
                    Leave=("Status", lambda x: (x=="Leave").sum()),
                    Total=("Status","count")
                ).reset_index()
                stats["Attendance %"] = (stats["Present"]/stats["Total"]*100).round(1)
                details = workers[["Name","Section","Department","Shift"]] if not workers.empty else pd.DataFrame()
                if not details.empty:
                    stats = stats.merge(details, left_on="Worker_Name", right_on="Name", how="left").drop(columns=["Name"])
                st.dataframe(stats, use_container_width=True)
                st.download_button("📥 Download Monthly CSV", data=stats.to_csv(index=False).encode("utf-8"),
                                   file_name=f"monthly_{year}_{month}.csv", mime="text/csv")
            else: st.info("No records for month.")
        else: st.info("No attendance yet.")

    # Directory
    with tabs[2]:
        st.subheader("Directory")
        if workers.empty: st.info("No workers")
        else:
            workers["Active"]=workers["Active"].astype(str)
            act = workers[workers["Active"].str.lower().isin(["true","1","yes"])]
            st.dataframe(act[["Name","Section","Department","Shift"]], use_container_width=True)
            st.download_button("📥 Download Directory", data=dataframe_to_excel_bytes(act[["Name","Section","Department","Shift"]]),
                               file_name="worker_directory.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # Grid
    with tabs[3]:
        st.subheader("Monthly Grid")
        year = st.selectbox("Year", list(range(2020, datetime.date.today().year+2)),
                            index=list(range(2020, datetime.date.today().year+2)).index(datetime.date.today().year),
                            key="hrg_y")
        month = st.selectbox("Month", list(range(1,13)), index=datetime.date.today().month-1, key="hrg_m")
        g = generate_attendance_grid(year, month)
        if g.empty: st.info("No data")
        else:
            st.markdown('<div class="attendance-grid">', unsafe_allow_html=True)
            st.dataframe(g, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            st.download_button("📥 Download Grid", data=dataframe_to_excel_bytes(g),
                               file_name=f"attendance_grid_{year}_{month}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ==========================================================
# LOGIN PAGE
# ==========================================================

def login_page():
    st.title("🔐 Company Attendance System")
    st.markdown("---")
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.subheader("Login")
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Login", use_container_width=True):
            if login(u, p): st.success("Welcome!"); time.sleep(0.7); st.rerun()
            else: st.error("Invalid credentials or inactive user")

# ==========================================================
# MAIN
# ==========================================================

def main():
    st.set_page_config(page_title="Attendance", page_icon="🗂️", layout="wide")
    st.markdown(mobile_css(), unsafe_allow_html=True)

    # Initialize databases and seed defaults
    initialize_databases()
    ensure_seed_data()

    # Sidebar status + manual sync
    with st.sidebar:
        if is_online():
            # perform a quick sync from offline → online
            nw, na = sync_from_sqlite_to_supabase()
            # status
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
