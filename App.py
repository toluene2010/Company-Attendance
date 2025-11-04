```python
# App.py — Company Attendance System (secure, schema-aware, role-based)

import streamlit as st
import pandas as pd
import datetime, os, time, calendar
import bcrypt
from io import BytesIO
from sqlalchemy import create_engine, text, MetaData, Table, Column, Integer, String, Boolean, Date, DateTime

# ==================== CONFIGURATION ====================
try:
    DB_USER = st.secrets["database"]["DB_USER"]
    DB_PASSWORD = st.secrets["database"]["DB_PASSWORD"]
    DB_HOST = st.secrets["database"]["DB_HOST"]
    DB_PORT = st.secrets["database"]["DB_PORT"]
    DB_NAME = st.secrets["database"]["DB_NAME"]
except Exception:
    DB_USER = os.getenv("DB_USER", "Company_Attendance_subjectlet")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "your_local_password_here")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "Company_Attendance_subjectlet")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# ==================== DATABASE ====================
@st.cache_resource
def get_db_connection():
    try:
        engine = create_engine(DATABASE_URL)
        with engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS attendance"))
        return engine
    except Exception as e:
        st.error(f"Error connecting to database: {e}")
        return None

def read_table(table_name: str) -> pd.DataFrame:
    engine = get_db_connection()
    if engine is None:
        return pd.DataFrame()
    try:
        return pd.read_sql(f"SELECT * FROM attendance.{table_name}", engine)
    except Exception:
        return pd.DataFrame()

def write_table(table_name: str, df: pd.DataFrame) -> bool:
    engine = get_db_connection()
    if engine is None:
        return False
    try:
        df.to_sql(table_name, engine, if_exists='replace', index=False, schema='attendance')
        return True
    except Exception as e:
        st.error(f"Error writing {table_name}: {e}")
        return False

# ==================== INITIALIZATION ====================
def initialize_system():
    engine = get_db_connection()
    if engine is None:
        return
    
    metadata = MetaData()
    # Core tables
    Table('users', metadata,
          Column('ID', Integer, primary_key=True),
          Column('Name', String(255), nullable=False),
          Column('Username', String(255), nullable=False, unique=True),
          Column('Password', String(255), nullable=False),
          Column('Role', String(50), nullable=False),
          Column('Active', Boolean, default=True),
          Column('Assigned_Section', String(255)),
          Column('Assigned_Shift', String(255)),
          schema='attendance')
    Table('sections', metadata,
          Column('ID', Integer, primary_key=True),
          Column('Name', String(255), nullable=False),
          Column('Description', String(500)),
          schema='attendance')
    Table('departments', metadata,
          Column('ID', Integer, primary_key=True),
          Column('Name', String(255), nullable=False),
          Column('Section_ID', Integer),
          Column('Description', String(500)),
          schema='attendance')
    Table('shifts', metadata,
          Column('ID', Integer, primary_key=True),
          Column('Name', String(255), nullable=False),
          schema='attendance')
    Table('workers', metadata,
          Column('ID', Integer, primary_key=True),
          Column('Name', String(255), nullable=False),
          Column('Section', String(255)),
          Column('Department', String(255)),
          Column('Shift', String(255)),
          Column('Active', Boolean, default=True),
          schema='attendance')
    Table('attendance', metadata,
          Column('ID', Integer, primary_key=True),
          Column('Worker_ID', Integer),
          Column('Worker_Name', String(255), nullable=False),
          Column('Date', Date, nullable=False),
          Column('Section', String(255)),
          Column('Department', String(255)),
          Column('Shift', String(255)),
          Column('Status', String(50), nullable=False),
          Column('Timestamp', DateTime, default=datetime.datetime.now),
          schema='attendance')
    
    metadata.create_all(engine)

    # Seed defaults if empty
    if read_table("shifts").empty:
        write_table("shifts", pd.DataFrame({'ID':[1,2,3],'Name':['Morning','Afternoon','General']}))
    if read_table("sections").empty:
        write_table("sections", pd.DataFrame({
            'ID':[1,2,3],
            'Name':['Liquid Section','Solid Section','Utility Section'],
            'Description':['Liquid manufacturing','Solid manufacturing','Utility services']
        }))
    if read_table("departments").empty:
        write_table("departments", pd.DataFrame({
            'ID':[1,2,3,4],
            'Name':['Mixing','Filling','Packaging','Maintenance'],
            'Section_ID':[1,1,2,3],
            'Description':['Mixing department','Filling department','Packaging department','Maintenance department']
        }))
    if read_table("users").empty:
        hashed = bcrypt.hashpw("admin123".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        write_table("users", pd.DataFrame([{
            'ID':1, 'Name':'Admin User', 'Username':'admin', 'Password':hashed,
            'Role':'Admin', 'Active':True, 'Assigned_Section':'', 'Assigned_Shift':''
        }]))
    if read_table("workers").empty:
        write_table("workers", pd.DataFrame(columns=['ID','Name','Section','Department','Shift','Active']))
    if read_table("attendance").empty:
        write_table("attendance", pd.DataFrame(columns=['ID','Worker_ID','Worker_Name','Date','Section','Department','Shift','Status','Timestamp']))

# ==================== UTILITIES ====================
def dataframe_to_excel_bytes(df: pd.DataFrame):
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    bio.seek(0)
    return bio

def normalize_active_column(df: pd.DataFrame, col='Active'):
    if col not in df.columns:
        df[col] = True
    df[col] = df[col].astype(str).str.strip().str.upper()
    return df

def generate_attendance_grid(year: int, month: int) -> pd.DataFrame:
    workers_df = read_table("workers")
    if workers_df.empty:
        return pd.DataFrame()
    for col in ['Active','Section','Department','Shift']:
        if col not in workers_df.columns:
            workers_df[col] = '' if col != 'Active' else True
    workers_df['Active'] = workers_df['Active'].astype(str)
    active_workers = workers_df[workers_df['Active'].str.lower().isin(['true','1','yes'])]
    if active_workers.empty:
        return pd.DataFrame()

    attendance_df = read_table("attendance")
    if attendance_df.empty or 'Date' not in attendance_df.columns:
        return pd.DataFrame()
    attendance_df['Date'] = pd.to_datetime(attendance_df['Date'])
    monthly_attendance = attendance_df[
        (attendance_df['Date'].dt.year == year) &
        (attendance_df['Date'].dt.month == month)
    ]
    days_in_month = calendar.monthrange(year, month)[1]
    grid_df = active_workers[['Name','Section','Department','Shift']].copy()
    for day in range(1, days_in_month + 1):
        grid_df[str(day)] = ''
    for _, att in monthly_attendance.iterrows():
        worker_name = att['Worker_Name']
        day = att['Date'].day
        status = att['Status']
        idx = grid_df[grid_df['Name'] == worker_name].index
        if not idx.empty:
            grid_df.at[idx[0], str(day)] = '✓' if status == 'Present' else ('✗' if status == 'Absent' else status[:1])
    grid_df['Present Days'] = grid_df[[str(d) for d in range(1, days_in_month+1)]].apply(lambda r: sum(v=='✓' for v in r), axis=1)
    grid_df['Attendance %'] = (grid_df['Present Days'] / days_in_month * 100).round(1)
    return grid_df

# ==================== AUTHENTICATION ====================
def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def login(username: str, password: str) -> bool:
    engine = get_db_connection()
    if engine is None:
        return False
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT ID, Password, Role, Active FROM attendance.users WHERE Username=:u"),
            {"u": username}
        ).fetchone()
    if row:
        uid, stored_hash, role, active = row
        if bool(active) and verify_password(password, stored_hash):
            st.session_state.update({"logged_in": True, "username": username, "role": role, "user_id": uid})
            return True
    return False

def logout():
    st.session_state.clear()

# ==================== MOBILE CSS ====================
def mobile_responsive_css():
    return """
    <style>
    @media (max-width: 768px) {
        .main .block-container { padding-left: 1rem; padding-right: 1rem; max-width: 100%; }
        div[data-testid="stHorizontalBlock"] > div { width: 100% !important; margin-bottom: 1rem; }
        .stButton > button { width: 100%; margin-bottom: 0.5rem; }
        .stRadio > div { flex-direction: column; }
    }
    .attendance-grid { font-size: 0.9rem; }
    .attendance-grid th { text-align: center; background-color: #f0f2f6; position: sticky; top: 0; }
    .attendance-grid td { text-align: center; }
    </style>
    """

# ==================== LOGIN PAGE ====================
def login_page():
    st.title("🔐 Company Attendance System")
    st.markdown("---")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login", type="primary"):
        if login(username, password):
            st.success(f"Welcome, {username}!")
            time.sleep(0.7)
            st.rerun()
        else:
            st.error("Invalid credentials or inactive account")

# ==================== ADMIN DASHBOARD ====================
def admin_dashboard():
    st.title("🔧 Admin Dashboard")
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["👥 Users","🏭 Sections","🏢 Departments","👷 Workers","📊 Attendance","🗑️ Delete Data"])

    # Users
    with tab1:
        st.subheader("➕ Add New User")
        with st.form("add_user"):
            name = st.text_input("Full Name")
            username = st.text_input("Username")
            password = st.text_input("Password")
            role = st.selectbox("Role", ["Admin","Supervisor","HR"])
            assigned_section = st.text_input("Assigned Section (optional)")
            assigned_shift = st.text_input("Assigned Shift (optional)")
            if st.form_submit_button("Add User"):
                if name and username and password:
                    users_df = read_table("users")
                    new_id = int(users_df['ID'].max())+1 if not users_df.empty else 1
                    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                    new_user = pd.DataFrame([{
                        'ID': new_id, 'Name': name, 'Username': username,
                        'Password': hashed, 'Role': role, 'Active': True,
                        'Assigned_Section': assigned_section, 'Assigned_Shift': assigned_shift
                    }])
                    users_df = pd.concat([users_df, new_user], ignore_index=True)
                    if write_table("users", users_df):
                        st.success("User added")
                        st.rerun()
                else:
                    st.error("Please fill all fields")
        st.divider()
        st.subheader("📋 All Users")
        users_df = read_table("users")
        if not users_df.empty:
            users_df = normalize_active_column(users_df, 'Active')
            st.dataframe(users_df[['ID','Name','Username','Role','Active']], use_container_width=True)
        else:
            st.info("No users found")

    # Sections
    with tab2:
        st.subheader("➕ Add Section")
        sections_df = read_table("sections")
        with st.form("add_section"):
            section_name = st.text_input("Section Name")
            desc = st.text_area("Description")
            if st.form_submit_button("Add Section"):
                if section_name:
                    new_id = int(sections_df['ID'].max())+1 if not sections_df.empty else 1
                    new_section = pd.DataFrame([{'ID':new_id,'Name':section_name,'Description':desc}])
                    sections_df = pd.concat([sections_df, new_section], ignore_index=True)
                    if write_table("sections", sections_df):
                        st.success("Section added")
                        st.rerun()
                else:
                    st.error("Enter section name")
        st.divider()
        st.subheader("📋 All Sections")
        st.dataframe(read_table("sections"), use_container_width=True)

    # Departments
    with tab3:
        st.subheader("➕ Add Department")
        sections_df = read_table("sections")
        departments_df = read_table("departments")
        with st.form("add_department"):
            dept_name = st.text_input("Department Name")
            section_id = st.selectbox("Section", sections_df['ID'].tolist() if not sections_df.empty else [])
            desc = st.text_area("Description")
            if st.form_submit_button("Add Department"):
                if dept_name and section_id:
                    new_id = int(departments_df['ID'].max())+1 if not departments_df.empty else 1
                    new_department = pd.DataFrame([{'ID':new_id,'Name':dept_name,'Section_ID':section_id,'Description':desc}])
                    departments_df = pd.concat([departments_df, new_department], ignore_index=True)
                    if write_table("departments", departments_df):
                        st.success("Department added")
                        st.rerun()
                else:
                    st.error("Enter department name and select section")
        st.divider()
        st.subheader("📋 All Departments")
        merged = departments_df.merge(sections_df[['ID','Name']], left_on='Section_ID', right_on='ID', how='left', suffixes=('','_section'))
        if not merged.empty:
            merged = merged.rename(columns={'Name':'Department','Name_section':'Section'})
            merged = merged.drop(columns=['ID_section'])
            st.dataframe(merged[['ID','Department','Section','Description']], use_container_width=True)
        else:
            st.info("No departments found")

    # Workers
    with tab4:
        st.subheader("➕ Add Worker")
        sections_df = read_table("sections")
        departments_df = read_table("departments")
        shifts_df = read_table("shifts")
        with st.form("add_worker"):
            w_name = st.text_input("Name")
            w_section = st.selectbox("Section", sections_df['Name'].tolist() if not sections_df.empty else [])
            if w_section and not sections_df.empty:
                section_id = sections_df[sections_df['Name']==w_section]['ID'].values[0]
                dept_options = departments_df[departments_df['Section_ID']==section_id]['Name'].tolist() if not departments_df.empty else []
            else:
                dept_options = []
            w_department = st.selectbox("Department", dept_options)
            w_shift = st.selectbox("Shift", shifts_df['Name'].tolist() if not shifts_df.empty else [])
            if st.form_submit_button("Add Worker"):
                if w_name and w_section and w_department and w_shift:
                    workers_df = read_table("workers")
                    new_id = int(workers_df['ID'].max())+1 if not workers_df.empty else 1
                    new_worker = pd.DataFrame([{'ID':new_id,'Name':w_name,'Section':w_section,'Department':w_department,'Shift':w_shift,'Active':True}])
                    workers_df = pd.concat([workers_df,new_worker], ignore_index=True)
                    if write_table("workers", workers_df):
                        st.success("Worker added")
                        st.rerun()
                else:
                    st.error("Fill all fields")
        st.divider()
        st.subheader("📋 All Workers")
        wd = read_table("workers")
        if not wd.empty:
            wd['Active'] = wd['Active'].astype(str)
            st.dataframe(wd[['ID','Name','Section','Department','Shift','Active']], use_container_width=True)
            excel_bytes = dataframe_to_excel_bytes(wd)
            st.download_button("📥 Download Workers Excel", data=excel_bytes, file_name="workers.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.info("No workers found")

    # Attendance
    with tab5:
        st.subheader("📊 Attendance Records")
        att = read_table("attendance")
        if not att.empty and 'Date' in att.columns:
            att['Date'] = pd.to_datetime(att['Date']).dt.date
            view_date = st.date_input("Select Date", datetime.date.today())
            filtered = att[att['Date'] == view_date]
            if not filtered.empty:
                st.dataframe(filtered[['Worker_Name','Section','Department','Shift','Status','Timestamp']], use_container_width=True)
                total = len(filtered)
                present = len(filtered[filtered['Status']=='Present'])
                absent = len(filtered[filtered['Status']=='Absent'])
                late = len(filtered[filtered['Status']=='Late'])
                leave = len(filtered[filtered['Status']=='Leave'])
                c1,c2,c3,c4 = st.columns(4)
                with c1: st.metric("Present", present, f"{present/total*100:.1f}%")
                with c2: st.metric("Absent", absent, f"{absent/total*100:.1f}%")
                with c3: st.metric("Late", late, f"{late/total*100:.1f}%")
                with c4: st.metric("Leave", leave, f"{leave/total*100:.1f}%")
                st.download_button("📥 Download Attendance CSV", filtered.to_csv(index=False).encode('utf-8'), file_name=f"attendance_{view_date}.csv")
            else:
                st.info("No attendance records for selected date.")
        else:
            st.info("No attendance data yet.")

    # Danger Zone
    with tab6:
        st.subheader("🗑️ Danger Zone")
        if st.button("Clear All Attendance"):
            write_table("attendance", pd.DataFrame(columns=['ID','Worker_ID','Worker_Name','Date','Section','Department','Shift','Status','Timestamp']))
            st.success("Attendance cleared")
        if st.button("Clear All Workers"):
            write_table("workers", pd.DataFrame(columns=['ID','Name','Section','Department','Shift','Active']))
            st.success("Workers cleared")
        if st.button("Clear All Departments"):
            write_table("departments", pd.DataFrame(columns=['ID','Name','Section_ID','Description']))
            st.success("Departments cleared")
        if st.button("Clear All Sections"):
            write_table("sections", pd.DataFrame(columns=['ID','Name','Description']))
            st.success("Sections cleared")

# ==================== SUPERVISOR DASHBOARD ====================
def supervisor_dashboard():
    st.title("👷 Supervisor Dashboard")
    sections_df = read_table("sections")
    departments_df = read_table("departments")
    shifts_df = read_table("shifts")
    workers_df = read_table("workers")
    for col in ['Active','Section','Department','Shift']:
        if col not in workers_df.columns:
            workers_df[col] = '' if col != 'Active' else True
    workers_df['Active'] = workers_df['Active'].astype(str)
    active_workers = workers_df[workers_df['Active'].str.lower().isin(['true','1','yes'])]

    tab1, tab2 = st.tabs(["✅ Mark Attendance","📅 View Attendance"])
    with tab1:
        st.subheader("✅ Mark Attendance")
        mark_date = st.date_input("Select Date", datetime.date.today())
        selected_section = st.selectbox("Section", ["All"] + (sections_df['Name'].tolist() if not sections_df.empty else []))
        if selected_section != "All" and not sections_df.empty:
            section_id = sections_df[sections_df['Name']==selected_section]['ID'].values[0]
            dept_options = departments_df[departments_df['Section_ID']==section_id]['Name'].tolist() if not departments_df.empty else []
        else:
            dept_options = ["All"]
        selected_department = st.selectbox("Department", dept_options)
        selected_shift = st.selectbox("Shift", ["All"] + (shifts_df['Name'].tolist() if not shifts_df.empty else []))

        filtered = active_workers.copy()
        if selected_section != "All": filtered = filtered[filtered['Section'] == selected_section]
        if selected_department != "All": filtered = filtered[filtered['Department'] == selected_department]
        if selected_shift != "All": filtered = filtered[filtered['Shift'] == selected_shift]

        if filtered.empty:
            st.info("No active workers for selected filters.")
        else:
            att_df = read_table("attendance")
            if not att_df.empty and 'Date' in att_df.columns:
                att_df['Date'] = pd.to_datetime(att_df['Date']).dt.date
                existing_att = att_df[(att_df['Date'] == mark_date)]
            else:
                existing_att = pd.DataFrame()

            with st.form("mark_attendance_form"):
                statuses = {}
                for _, w in filtered.iterrows():
                    w_status_default = 0
                    if not existing_att.empty:
                        row = existing_att[existing_att['Worker_ID'] == w['ID']]
                        if not row.empty and 'Status' in row.columns:
                            try:
                                w_status_default = ["Present","Absent","Late","Leave"].index(row.iloc[0]['Status'])
                            except ValueError:
                                w_status_default = 0
                    st.write(f"• {w['Name']} — {w['Section']} / {w['Department']} / {w['Shift']}")
                    statuses[int(w['ID'])] = st.radio("Status", ["Present","Absent","Late","Leave"], index=w_status_default, key=f"stat_{w['ID']}", horizontal=True)
                if st.form_submit_button("Submit Attendance"):
                    if att_df.empty:
                        att_df = pd.DataFrame(columns=['ID','Worker_ID','Worker_Name','Date','Section','Department','Shift','Status','Timestamp'])
                    next_id = int(att_df['ID'].max())+1 if not att_df.empty else 1
                    date_str = mark_date.strftime('%Y-%m-%d')
                    for wid in statuses:
                        row = att_df[(att_df['Date'] == mark_date) & (att_df['Worker_ID'] == wid)]
                        if not row.empty:
                            rid = row.iloc[0]['ID']
                            att_df.loc[att_df['ID'] == rid, ['Status','Timestamp']] = [statuses[wid], datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
                        else:
                            worker = filtered[filtered['ID'] == wid].iloc[0]
                            att_df = pd.concat([att_df, pd.DataFrame([{
                                'ID': next_id,
                                'Worker_ID': wid,
                                'Worker_Name': worker['Name'],
                                'Date': date_str,
                                'Section': worker['Section'],
                                'Department': worker['Department'],
                                'Shift': worker['Shift'],
                                'Status': statuses[wid],
                                'Timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            }])], ignore_index=True)
                            next_id += 1
                    if write_table("attendance", att_df):
                        st.success(f"Attendance updated for {len(filtered)} workers")
                        st.rerun()

    with tab2:
        st.subheader("📅 View Attendance")
        att = read_table("attendance")
        if not att.empty and 'Date' in att.columns:
            att['Date'] = pd.to_datetime(att['Date']).dt.date
            view_date = st.date_input("Date", datetime.date.today(), key="sup_view_date")
            view_section = st.selectbox("Section", ["All"] + (sections_df['Name'].tolist() if not sections_df.empty else []), key="sup_view_section")
            if view_section != "All" and not sections_df.empty:
                section_id = sections_df[sections_df['Name'] == view_section]['ID'].values[0]
                dept_options = departments_df[departments_df['Section_ID'] == section_id]['Name'].tolist() if not departments_df.empty else []
            else:
                dept_options = ["All"]
            view_department = st.selectbox("Department", dept_options, key="sup_view_department")
            view_shift = st.selectbox("Shift", ["All"] + (shifts_df['Name'].tolist() if not shifts_df.empty else []), key="sup_view_shift")
            filtered = att[att['Date'] == view_date]
            if view_section != "All": filtered = filtered[filtered['Section'] == view_section]
            if view_department != "All": filtered = filtered[filtered['Department'] == view_department]
            if view_shift != "All": filtered = filtered[filtered['Shift'] == view_shift]
            if not filtered.empty:
                st.dataframe(filtered[['Worker_Name','Section','Department','Shift','Status','Timestamp']], use_container_width=True)
            else:
                st.info("No records found")
        else:
            st.info("No attendance data")

# ==================== HR DASHBOARD ====================
def hr_dashboard():
    st.title("📊 HR Dashboard")
    workers_df = read_table("workers")
    attendance_df = read_table("attendance")
    for col in ['Active','Section','Department','Shift']:
        if col not in workers_df.columns:
            workers_df[col] = '' if col != 'Active' else True

    tab1, tab2, tab3 = st.tabs(["📊 Daily","📅 Monthly","📈 Attendance Grid"])
    with tab1:
        st.subheader("📊 Daily Attendance")
        view_date = st.date_input("Date", datetime.date.today())
        if not attendance_df.empty and 'Date' in attendance_df.columns:
            attendance_df['Date'] = pd.to_datetime(attendance_df['Date']).dt.date
            filtered = attendance_df[attendance_df['Date'] == view_date]
            if not filtered.empty:
                st.dataframe(filtered[['Worker_Name','Section','Department','Shift','Status','Timestamp']], use_container_width=True)
                total = len(filtered)
                present = len(filtered[filtered['Status']=='Present'])
                absent = len(filtered[filtered['Status']=='Absent'])
                late = len(filtered[filtered['Status']=='Late'])
                leave = len(filtered[filtered['Status']=='Leave'])
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
        year = st.selectbox("Year", list(range(2023, datetime.date.today().year+2)),
                            index=list(range(2023, datetime.date.today().year+2)).index(datetime.date.today().year))
        month = st.selectbox("Month", list(range(1,13)), index=datetime.date.today().month-1)
        if not attendance_df.empty and 'Date' in attendance_df.columns:
            attendance_df['Date'] = pd.to_datetime(attendance_df['Date'])
            monthly = attendance_df[(attendance_df['Date'].dt.year == year) & (attendance_df['Date'].dt.month == month)]
            if not monthly.empty:
                worker_stats = monthly.groupby('Worker_Name').agg(
                    Present=('Status', lambda x: (x=='Present').sum()),
                    Absent=('Status', lambda x: (x=='Absent').sum()),
                    Late=('Status', lambda x: (x=='Late').sum()),
                    Leave=('Status', lambda x: (x=='Leave').sum()),
                    Total=('Status', 'count')
                ).reset_index()
                worker_stats['Attendance %'] = (worker_stats['Present'] / worker_stats['Total'] * 100).round(1)
                details = workers_df[['Name','Section','Department','Shift']]
                worker_stats = worker_stats.merge(details, left_on='Worker_Name', right_on='Name', how='left').drop('Name', axis=1)
                st.dataframe(worker_stats, use_container_width=True)
                csv = worker_stats.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download Monthly Report", csv, file_name=f"monthly_attendance_{year}_{month}.csv")
            else:
                st.info("No attendance records for selected month")
        else:
            st.info("No attendance data")

    with tab3:
        st.subheader("📈 Attendance Grid")
        year = st.selectbox("Grid Year", list(range(2020, datetime.date.today().year + 2)),
                            index=list(range(2020, datetime.date.today().year + 2)).index(datetime.date.today().year))
        month = st.selectbox("Grid Month", list(range(1, 13)), index=datetime.date.today().month - 1)
        grid_df = generate_attendance_grid(year, month)
        if not grid_df.empty:
            st.dataframe(grid_df, use_container_width=True)
            excel_bytes = dataframe_to_excel_bytes(grid_df)
            st.download_button("📥 Download Attendance Grid", data=excel_bytes,
                               file_name=f"attendance_grid_{year}_{month}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.info("No attendance data available for the selected period.")

# ==================== MAIN ====================
def main():
    st.markdown(mobile_responsive_css(), unsafe_allow_html=True)
    initialize_system()

    if not st.session_state.get("logged_in"):
        login_page()
    else:
        with st.sidebar:
            st.write(f"Logged in as: **{st.session_state['username']}** ({st.session_state['role']})")
            if st.button("Logout"):
                logout()
                st.rerun()
        role = st.session_state["role"]
        if role == "Admin":
            admin_dashboard()
        elif role == "Supervisor":
            supervisor_dashboard()
        elif role == "HR":
            hr_dashboard()
        else:
            st.warning("No dashboard available for this role.")

if __name__ == "__main__":
    main()
```