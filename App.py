import streamlit as st
import pandas as pd
import datetime
import os
import bcrypt
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

# ==================== DATABASE CONNECTION ====================
@st.cache_resource
def get_db_connection():
    try:
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            # Simpler: don’t force AUTHORIZATION
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS attendance"))
            conn.commit()
        return engine
    except Exception as e:
        st.error(f"Error connecting to database: {e}")
        return None

def execute_query(query, params=None):
    engine = get_db_connection()
    if engine is None:
        return None
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            if query.strip().upper().startswith("SELECT"):
                return result.fetchall()
            else:
                conn.commit()
                return True
    except Exception as e:
        st.error(f"Database error: {e}")
        return None

def read_table(table_name):
    engine = get_db_connection()
    if engine is None:
        return pd.DataFrame()
    try:
        query = f"SELECT * FROM attendance.{table_name}"   # 👈 fixed schema
        df = pd.read_sql(query, engine)
        return df
    except Exception as e:
        st.warning(f"Error reading from table {table_name}: {e}")
        return pd.DataFrame()

def write_table(table_name, df):
    engine = get_db_connection()
    if engine is None:
        return False
    try:
        df.to_sql(table_name, engine, if_exists='replace', index=False, schema='attendance')
        return True
    except Exception as e:
        st.error(f"Error writing to table {table_name}: {e}")
        return False

def table_exists(table_name):
    engine = get_db_connection()
    if engine is None:
        return False
    try:
        with engine.connect() as conn:
            query = text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'attendance' 
                    AND table_name = :table_name
                )
            """)
            result = conn.execute(query, {"table_name": table_name})
            return result.scalar()
    except Exception as e:
        st.error(f"Error checking if table {table_name} exists: {e}")
        return False

# ==================== INITIALIZATION ====================
def initialize_system():
    engine = get_db_connection()
    if engine is None:
        st.error("Cannot connect to database. System initialization failed.")
        return
    
    metadata = MetaData()

    # Define tables in attendance schema
    shifts = Table(
        'shifts', metadata,
        Column('ID', Integer, primary_key=True),
        Column('Name', String(255), nullable=False),
        schema='attendance'
    )
    sections = Table(
        'sections', metadata,
        Column('ID', Integer, primary_key=True),
        Column('Name', String(255), nullable=False),
        Column('Description', String(500)),
        schema='attendance'
    )
    departments = Table(
        'departments', metadata,
        Column('ID', Integer, primary_key=True),
        Column('Name', String(255), nullable=False),
        Column('Section_ID', Integer),
        Column('Description', String(500)),
        schema='attendance'
    )
    users = Table(
        'users', metadata,
        Column('ID', Integer, primary_key=True),
        Column('Name', String(255), nullable=False),
        Column('Username', String(255), nullable=False, unique=True),
        Column('Password', String(255), nullable=False),
        Column('Role', String(50), nullable=False),
        Column('Active', Boolean, default=True),
        Column('Assigned_Section', String(255)),
        Column('Assigned_Shift', String(255)),
        schema='attendance'
    )
    workers = Table(
        'workers', metadata,
        Column('ID', Integer, primary_key=True),
        Column('Name', String(255), nullable=False),
        Column('Section', String(255)),
        Column('Department', String(255)),
        Column('Shift', String(255)),
        Column('Active', Boolean, default=True),
        schema='attendance'
    )
    attendance = Table(
        'attendance', metadata,
        Column('ID', Integer, primary_key=True),
        Column('Worker_ID', Integer),
        Column('Worker_Name', String(255), nullable=False),
        Column('Date', Date, nullable=False),
        Column('Section', String(255)),
        Column('Department', String(255)),
        Column('Shift', String(255)),
        Column('Status', String(50), nullable=False),
        Column('Timestamp', DateTime, default=datetime.datetime.now),
        schema='attendance'
    )

    try:
        metadata.create_all(engine)
        st.success("Database tables created successfully!")
    except Exception as e:
        st.error(f"Error creating database tables: {e}")
        return

    # Insert default data if empty
    if read_table("shifts").empty:
        write_table("shifts", pd.DataFrame({'ID':[1,2,3],'Name':['Morning','Afternoon','General']}))
    if read_table("sections").empty:
        write_table("sections", pd.DataFrame({
            'ID': [1, 2, 3],
            'Name': ['Liquid Section', 'Solid Section', 'Utility Section'],
            'Description': ['Liquid manufacturing', 'Solid manufacturing', 'Utility services']
        }))
    if read_table("departments").empty:
        write_table("departments", pd.DataFrame({
            'ID': [1, 2, 3, 4],
            'Name': ['Mixing', 'Filling', 'Packaging', 'Maintenance'],
            'Section_ID': [1, 1, 2, 3],
            'Description': ['Mixing department', 'Filling department', 'Packaging department', 'Maintenance department']
        }))
    if read_table("users").empty:
        # Hash the admin password
        hashed_password = bcrypt.hashpw("admin123".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        users_df = pd.DataFrame([{
            'ID': 1,
            'Name': 'Admin User',
            'Username': 'admin',
            'Password': hashed_password,
            'Role': 'Admin',
            'Active': True,
            'Assigned_Section': '',
            'Assigned_Shift': ''
        }])
        write_table("users", users_df)
    if read_table("workers").empty:
        write_table("workers", pd.DataFrame(columns=['ID','Name','Section','Department','Shift','Active']))
    if read_table("attendance").empty:
        write_table("attendance", pd.DataFrame(columns=['ID','Worker_ID','Worker_Name','Date','Section','Department','Shift','Status','Timestamp']))

# ==================== AUTHENTICATION ====================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plain password against the stored bcrypt hash"""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

def login(username: str, password: str) -> bool:
    """Verify user login credentials against the database"""
    engine = get_db_connection()
    if engine is None:
        return False
    
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT Password, Role, Active FROM attendance.users WHERE Username = :u"),
            {"u": username}
        ).fetchone()
        
        if result:
            stored_hash, role, active = result
            if active and verify_password(password, stored_hash):
                st.session_state["logged_in"] = True
                st.session_state["username"] = username
                st.session_state["role"] = role
                return True
    return False

def logout():
    """Clear session state on logout"""
    st.session_state.clear()


# ==================== MOBILE RESPONSIVENESS ====================
def mobile_responsive_css():
    return """
    <style>
    /* Mobile responsiveness */
    @media (max-width: 768px) {
        .main .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
            max-width: 100%;
        }
        
        /* Adjust columns for mobile */
        div[data-testid="stHorizontalBlock"] > div {
            width: 100% !important;
            margin-bottom: 1rem;
        }
        
        /* Make tables scrollable horizontally */
        .stDataFrame {
            overflow-x: auto;
            display: block;
            white-space: nowrap;
        }
        
        /* Adjust form elements */
        .stTextInput, .stSelectbox, .stDateInput, .stTimeInput, .stNumberInput {
            margin-bottom: 1rem;
        }
        
        /* Adjust buttons */
        .stButton > button {
            width: 100%;
            margin-bottom: 0.5rem;
        }
        
        /* Adjust radio buttons */
        .stRadio > div {
            flex-direction: column;
        }
        
        .stRadio > div > label {
            margin-bottom: 0.5rem;
        }
        
        /* Adjust expanders */
        .streamlit-expanderHeader {
            font-size: 1rem;
            padding: 0.5rem 0;
        }
        
        /* Adjust metrics */
        div[data-testid="stMetric"] {
            margin-bottom: 1rem;
        }
        
        /* Adjust tabs */
        .stTabs > div > div > div > button {
            font-size: 0.8rem;
            padding: 0.5rem;
        }
    }
    
    /* Make sidebar more mobile-friendly */
    @media (max-width: 768px) {
        .css-1d391kg {
            padding-top: 1rem;
        }
        
        .css-1lcbmhc {
            padding: 1rem;
        }
    }
    
    /* Custom styles for attendance grid */
    .attendance-grid {
        font-size: 0.9rem;
    }
    
    .attendance-grid th {
        text-align: center;
        background-color: #f0f2f6;
        position: sticky;
        top: 0;
    }
    
    .attendance-grid td {
        text-align: center;
    }
    
    .present {
        color: green;
        font-weight: bold;
    }
    
    .absent {
        color: red;
        font-weight: bold;
    }
    
    .other-status {
        color: orange;
    }
    </style>
    """

# ==================== SESSION ====================
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.role = None
    st.session_state.user_id = None

# ==================== UTILITIES ====================
def normalize_active_column(df, col='Active'):
    if col not in df.columns:
        df[col] = True
    df[col] = df[col].astype(str).str.strip().str.upper()
    return df

def dataframe_to_excel_bytes(df: pd.DataFrame):
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    bio.seek(0)
    return bio

def generate_attendance_grid(year, month):
    """Generate attendance grid for the selected month and year"""
    # Get all workers
    workers_df = read_table("workers")
    
    # Ensure required columns exist
    if 'Active' not in workers_df.columns:
        workers_df['Active'] = True
    if 'Section' not in workers_df.columns:
        workers_df['Section'] = ''
    if 'Department' not in workers_df.columns:
        workers_df['Department'] = ''
    if 'Shift' not in workers_df.columns:
        workers_df['Shift'] = ''
    
    # Filter active workers
    workers_df['Active'] = workers_df['Active'].astype(str)
    active_workers = workers_df[workers_df['Active'].str.lower().isin(['true','1','yes'])]
    
    if active_workers.empty:
        return pd.DataFrame()
    
    # Get attendance data for the selected month and year
    attendance_df = read_table("attendance")
    
    if attendance_df.empty or 'Date' not in attendance_df.columns:
        return pd.DataFrame()
    
    # Convert Date to datetime
    attendance_df['Date'] = pd.to_datetime(attendance_df['Date'])
    
    # Filter for the selected month and year
    monthly_attendance = attendance_df[
        (attendance_df['Date'].dt.year == year) & 
        (attendance_df['Date'].dt.month == month)
    ]
    
    # Get number of days in the month
    days_in_month = calendar.monthrange(year, month)[1]
    
    # Create a base DataFrame with all workers
    grid_df = active_workers[['Name', 'Section', 'Department', 'Shift']].copy()
    
    # Add columns for each day of the month
    for day in range(1, days_in_month + 1):
        grid_df[str(day)] = ''  # Initialize with empty string
    
    # Fill in attendance data
    for _, att in monthly_attendance.iterrows():
        worker_name = att['Worker_Name']
        day = att['Date'].day
        status = att['Status']
        
        # Find the worker in the grid
        worker_idx = grid_df[grid_df['Name'] == worker_name].index
        
        if not worker_idx.empty:
            if status == 'Present':
                grid_df.at[worker_idx[0], str(day)] = '✓'
            elif status == 'Absent':
                grid_df.at[worker_idx[0], str(day)] = '✗'
            else:
                grid_df.at[worker_idx[0], str(day)] = status[0]  # First letter of other statuses
    
    # Calculate present days and percentage
    present_counts = []
    percentages = []
    
    for _, worker in grid_df.iterrows():
        present_count = 0
        for day in range(1, days_in_month + 1):
            if worker[str(day)] == '✓':
                present_count += 1
        
        present_counts.append(present_count)
        # Calculate percentage (present days / total days in month * 100)
        percentage = (present_count / days_in_month) * 100
        percentages.append(round(percentage, 1))
    
    grid_df['Present Days'] = present_counts
    grid_df['Attendance %'] = percentages
    
    return grid_df

# ==================== AUTHENTICATION ====================
def login_page():
    st.title("🔐 Company Attendance System")
    st.markdown("---")
    
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.subheader("Login")
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        if st.button("Login", type="primary", use_container_width=True):
            users_df = read_table("users")
            if users_df.empty:
                st.error("No users found. System needs initialization.")
                return
            # Normalize Active column
            users_df = normalize_active_column(users_df, 'Active')
            # Match
            user = users_df[
                (users_df['Username'] == username) &
                (users_df['Password'] == password) &
                (users_df['Active'].isin(["TRUE","YES","1"]))
            ]
            if not user.empty:
                st.session_state.logged_in = True
                st.session_state.username = username
                st.session_state.role = user.iloc[0]['Role']
                st.session_state.user_id = user.iloc[0]['ID']
                st.success(f"Welcome, {username}!")
                time.sleep(0.8)
                st.rerun()
            else:
                st.error("Invalid credentials or account inactive")

# ==================== ADMIN DASHBOARD ====================
def admin_dashboard():
    st.title("🔧 Admin Dashboard")
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["👥 Users","🏭 Sections","🏢 Departments","👷 Workers","📊 Attendance","🗑️ Delete Data"])

    # ---- Users Tab ----
    with tab1:
        st.subheader("User Management")
        users_df = read_table("users")
        col_a, col_b = st.columns([2,3])
        with col_a:
            st.markdown("#### ➕ Add New User")
            with st.form("add_user"):
                name = st.text_input("Full Name")
                username = st.text_input("Username")
                password = st.text_input("Password")
                role = st.selectbox("Role", ["Admin","Supervisor","HR"], key="admin_role")
                assigned_section = st.text_input("Assigned Section (optional)")
                assigned_shift = st.text_input("Assigned Shift (optional)")
                if st.form_submit_button("Add User"):
                    if name and username and password:
                        users_df = read_table("users")
                        new_id = int(users_df['ID'].max())+1 if not users_df.empty and 'ID' in users_df.columns else 1
                        new_user = pd.DataFrame([{
                            'ID': new_id,
                            'Name': name,
                            'Username': username,
                            'Password': password,
                            'Role': role,
                            'Active': True,
                            'Assigned_Section': assigned_section,
                            'Assigned_Shift': assigned_shift
                        }])
                        users_df = pd.concat([users_df, new_user], ignore_index=True)
                        if write_table("users", users_df):
                            st.success("User added")
                            st.rerun()
                    else:
                        st.error("Please fill all fields")
        with col_b:
            st.markdown("#### 📋 All Users")
            users_df = read_table("users")
            if not users_df.empty:
                users_df = normalize_active_column(users_df,'Active')
                for _, u in users_df.iterrows():
                    label = f"{'✅' if u['Active']=='TRUE' else '❌'} {u['Name']} (@{u['Username']})"
                    with st.expander(label):
                        st.write(f"Role: {u['Role']}")
                        st.write(f"ID: {u['ID']}")
                        st.write(f"Assigned Section: {u.get('Assigned_Section','')}")
                        st.write(f"Assigned Shift: {u.get('Assigned_Shift','')}")
                        col1, col2 = st.columns(2)
                        with col1:
                            if u['Active']=='TRUE':
                                if st.button("Deactivate", key=f"deact_{u['ID']}"):
                                    users_df.loc[users_df['ID']==u['ID'],'Active'] = False
                                    write_table("users", users_df)
                                    st.rerun()
                            else:
                                if st.button("Activate", key=f"act_{u['ID']}"):
                                    users_df.loc[users_df['ID']==u['ID'],'Active'] = True
                                    write_table("users", users_df)
                                    st.rerun()
                        with col2:
                            if u['ID'] != st.session_state.user_id:
                                if st.button("🗑️ Delete", key=f"del_{u['ID']}"):
                                    users_df = users_df[users_df['ID'] != u['ID']]
                                    write_table("users", users_df)
                                    st.rerun()
            else:
                st.info("No users found")

    # ---- Sections Tab ----
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
                        sections_df = read_table("sections")
                        new_id = int(sections_df['ID'].max())+1 if not sections_df.empty and 'ID' in sections_df.columns else 1
                        new_section = pd.DataFrame([{'ID':new_id,'Name':section_name,'Description':desc}])
                        sections_df = pd.concat([sections_df, new_section], ignore_index=True)
                        if write_table("sections", sections_df):
                            st.success("Section added")
                            st.rerun()
                    else:
                        st.error("Enter section name")
        with col2:
            st.markdown("#### 📋 All Sections")
            if not sections_df.empty:
                st.dataframe(sections_df, use_container_width=True)
            else:
                st.info("No sections found")

    # ---- Departments Tab ----
    with tab3:
        st.subheader("Departments Management")
        sections_df = read_table("sections")
        departments_df = read_table("departments")
        col1, col2 = st.columns([2,3])
        with col1:
            st.markdown("#### ➕ Add Department")
            with st.form("add_department"):
                dept_name = st.text_input("Department Name")
                section_id = st.selectbox("Section", sections_df['ID'].tolist() if not sections_df.empty else [], key="dept_section")
                desc = st.text_area("Description")
                if st.form_submit_button("Add Department"):
                    if dept_name and section_id:
                        departments_df = read_table("departments")
                        new_id = int(departments_df['ID'].max())+1 if not departments_df.empty and 'ID' in departments_df.columns else 1
                        new_department = pd.DataFrame([{'ID':new_id,'Name':dept_name,'Section_ID':section_id,'Description':desc}])
                        departments_df = pd.concat([departments_df, new_department], ignore_index=True)
                        if write_table("departments", departments_df):
                            st.success("Department added")
                            st.rerun()
                    else:
                        st.error("Enter department name and select section")
        with col2:
            st.markdown("#### 📋 All Departments")
            if not departments_df.empty:
                # Merge with sections to show section names
                merged_df = departments_df.merge(
                    sections_df[['ID', 'Name']], 
                    left_on='Section_ID', 
                    right_on='ID', 
                    how='left',
                    suffixes=('', '_section')
                )
                # Rename columns appropriately
                merged_df = merged_df.rename(columns={'Name': 'Department', 'Name_section': 'Section'})
                # Drop the duplicate ID from sections
                merged_df = merged_df.drop(columns=['ID_section'])
                # Display the dataframe
                st.dataframe(merged_df[['ID', 'Department', 'Section', 'Description']], use_container_width=True)
            else:
                st.info("No departments found")

    # ---- Workers Tab ----
    with tab4:
        st.subheader("Worker Management")
        sections_df = read_table("sections")
        departments_df = read_table("departments")
        shifts_df = read_table("shifts")
        workers_df = read_table("workers")
        
        # Ensure required columns exist
        if 'Active' not in workers_df.columns:
            workers_df['Active'] = True
        if 'Section' not in workers_df.columns:
            workers_df['Section'] = ''
        if 'Department' not in workers_df.columns:
            workers_df['Department'] = ''
        if 'Shift' not in workers_df.columns:
            workers_df['Shift'] = ''

        col1, col2 = st.columns([2,3])

        # Upload Workers from Excel
        with col1:
            st.markdown("#### 📤 Upload Workers from Excel (.xlsx)")
            uploaded_file = st.file_uploader("Upload Excel File", type=["xlsx"], key="admin_upload_workers")
            if uploaded_file is not None:
                try:
                    uploaded_df = pd.read_excel(uploaded_file)
                    required_cols = {"Name","Section","Department","Shift"}
                    if not required_cols.issubset(uploaded_df.columns):
                        st.error("Excel must contain columns: Name, Section, Department, Shift")
                    else:
                        # load current workers
                        workers_df = read_table("workers")
                        if workers_df.empty:
                            workers_df = pd.DataFrame(columns=['ID','Name','Section','Department','Shift','Active'])
                        # Ensure required columns exist
                        if 'Active' not in workers_df.columns:
                            workers_df['Active'] = True
                        if 'Section' not in workers_df.columns:
                            workers_df['Section'] = ''
                        if 'Department' not in workers_df.columns:
                            workers_df['Department'] = ''
                        if 'Shift' not in workers_df.columns:
                            workers_df['Shift'] = ''
                        # Prevent duplicates (Name+Section+Department+Shift)
                        def is_duplicate(row):
                            return ((workers_df['Name'] == row['Name']) & 
                                    (workers_df['Section'] == row['Section']) &
                                    (workers_df['Department'] == row['Department']) &
                                    (workers_df['Shift'] == row['Shift'])).any()
                        new_rows = []
                        next_id = int(workers_df['ID'].max())+1 if not workers_df.empty and 'ID' in workers_df.columns else 1
                        for idx, r in uploaded_df.iterrows():
                            if not is_duplicate(r):
                                new_rows.append({'ID': next_id, 'Name': r['Name'], 'Section': r['Section'], 'Department': r['Department'], 'Shift': r['Shift'], 'Active': True})
                                next_id += 1
                        if not new_rows:
                            st.warning("All uploaded workers already exist. No new workers added.")
                        else:
                            add_df = pd.DataFrame(new_rows)
                            workers_df = pd.concat([workers_df, add_df], ignore_index=True)
                            if write_table("workers", workers_df):
                                st.success(f"Added {len(add_df)} new workers")
                                st.rerun()
                except Exception as e:
                    st.error(f"Error reading Excel file: {e}")

            st.markdown("#### ➕ Add Single Worker (Admin)")
            with st.form("add_worker_admin"):
                w_name = st.text_input("Name")
                w_section = st.selectbox("Section", sections_df['Name'].tolist() if not sections_df.empty else [], key="admin_add_section")
                
                # Filter departments based on selected section
                if w_section and not sections_df.empty:
                    section_id = sections_df[sections_df['Name'] == w_section]['ID'].values[0]
                    dept_options = departments_df[departments_df['Section_ID'] == section_id]['Name'].tolist() if not departments_df.empty else []
                else:
                    dept_options = []
                
                w_department = st.selectbox("Department", dept_options, key="admin_add_department")
                w_shift = st.selectbox("Shift", shifts_df['Name'].tolist() if not shifts_df.empty else [], key="admin_add_shift")
                
                if st.form_submit_button("Add Worker"):
                    if w_name and w_section and w_department and w_shift:
                        workers_df = read_table("workers")
                        # Ensure required columns exist
                        if 'Active' not in workers_df.columns:
                            workers_df['Active'] = True
                        if 'Section' not in workers_df.columns:
                            workers_df['Section'] = ''
                        if 'Department' not in workers_df.columns:
                            workers_df['Department'] = ''
                        if 'Shift' not in workers_df.columns:
                            workers_df['Shift'] = ''
                        new_id = int(workers_df['ID'].max())+1 if not workers_df.empty and 'ID' in workers_df.columns else 1
                        new_worker = pd.DataFrame([{'ID':new_id,'Name':w_name,'Section':w_section,'Department':w_department,'Shift':w_shift,'Active':True}])
                        workers_df = pd.concat([workers_df,new_worker], ignore_index=True)
                        if write_table("workers", workers_df):
                            st.success("Worker added")
                            st.rerun()
                    else:
                        st.error("Fill all fields")

        # Worker list + export
        with col2:
            st.markdown("#### 📋 All Workers")
            workers_df = read_table("workers")
            # Ensure required columns exist
            if 'Active' not in workers_df.columns:
                workers_df['Active'] = True
            if 'Section' not in workers_df.columns:
                workers_df['Section'] = ''
            if 'Department' not in workers_df.columns:
                workers_df['Department'] = ''
            if 'Shift' not in workers_df.columns:
                workers_df['Shift'] = ''
            workers_df['Active'] = workers_df['Active'].astype(str)
            st.write(f"**Total: {len(workers_df)} workers**")
            # Export button (Excel in-memory)
            excel_bytes = dataframe_to_excel_bytes(workers_df)
            st.download_button("📥 Download Workers Excel", data=excel_bytes, file_name="workers.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            st.markdown("---")
            for _, w in workers_df.iterrows():
                with st.expander(f"{'✅' if str(w['Active']).lower() in ['true','1','yes'] else '❌'} {w['Name']} - {w['Section']} / {w['Department']} ({w['Shift']})"):
                    st.write(f"ID: {w['ID']}")
                    colA, colB = st.columns([3,1])
                    with colA:
                        if st.button("Deactivate" if str(w['Active']).lower() in ['true','1','yes'] else "Activate", key=f"toggle_worker_{w['ID']}"):
                            df = read_table("workers")
                            # Ensure required columns exist
                            if 'Active' not in df.columns:
                                df['Active'] = True
                            if 'Section' not in df.columns:
                                df['Section'] = ''
                            if 'Department' not in df.columns:
                                df['Department'] = ''
                            if 'Shift' not in df.columns:
                                df['Shift'] = ''
                            df.loc[df['ID'] == w['ID'], 'Active'] = not (str(w['Active']).lower() in ['true','1','yes'])
                            write_table("workers", df)
                            st.rerun()
                    with colB:
                        # Worker ID display
                        st.write(f"ID: {w['ID']}")
            else:
                st.info("No workers found")

    # ---- Attendance Tab (Admin view) ----
    with tab5:
        st.subheader("📊 Attendance Records")
        att = read_table("attendance")
        if not att.empty:
            # Check if 'Date' column exists
            if 'Date' in att.columns:
                att['Date'] = pd.to_datetime(att['Date']).dt.date
                view_date = st.date_input("Select Date", datetime.date.today(), key="admin_view_date")
                filtered = att[att['Date'] == view_date]
                if not filtered.empty:
                    st.write(f"Attendance for {view_date.strftime('%B %d, %Y')}")
                    # show register table
                    st.dataframe(filtered[['Worker_Name','Section','Department','Shift','Status','Timestamp']], use_container_width=True)
                    # stats
                    total = len(filtered)
                    present = len(filtered[filtered['Status']=='Present'])
                    absent = len(filtered[filtered['Status']=='Absent'])
                    late = len(filtered[filtered['Status']=='Late'])
                    leave = len(filtered[filtered['Status']=='Leave'])
                    col1,col2,col3,col4 = st.columns(4)
                    with col1: st.metric("Present", present, f"{present/total*100:.1f}%")
                    with col2: st.metric("Absent", absent, f"{absent/total*100:.1f}%")
                    with col3: st.metric("Late", late, f"{late/total*100:.1f}%")
                    with col4: st.metric("Leave", leave, f"{leave/total*100:.1f}%")
                    # Download CSV
                    csv = filtered.to_csv(index=False).encode('utf-8')
                    st.download_button("📥 Download Attendance CSV", csv, file_name=f"attendance_{view_date}.csv")
                else:
                    st.info("No attendance records for selected date.")
            else:
                st.error("Attendance data is missing the 'Date' column. Please check your data structure.")
        else:
            st.info("No attendance data yet.")

    # ---- Delete Data Tab ----
    with tab6:
        st.subheader("Danger Zone - Delete Data")
        if st.button("Clear All Attendance", key="clear_attendance"):
            write_table("attendance", pd.DataFrame(columns=['ID','Worker_ID','Worker_Name','Date','Section','Department','Shift','Status','Timestamp']))
            st.success("Attendance cleared")
        if st.button("Clear All Workers", key="clear_workers"):
            write_table("workers", pd.DataFrame(columns=['ID','Name','Section','Department','Shift','Active']))
            st.success("Workers cleared")
        if st.button("Clear All Departments", key="clear_departments"):
            write_table("departments", pd.DataFrame(columns=['ID','Name','Section_ID','Description']))
            st.success("Departments cleared")
        if st.button("Clear All Sections", key="clear_sections"):
            write_table("sections", pd.DataFrame(columns=['ID','Name','Description']))
            st.success("Sections cleared")

# ==================== SUPERVISOR DASHBOARD ====================
def supervisor_dashboard():
    st.title("👷 Supervisor Dashboard")
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["✅ Mark Attendance", "📊 Attendance Register", "🔄 Transfer Workers", "👥 Manage Workers", "📅 View Attendance", "📊 Attendance Grid"])

    sections_df = read_table("sections")
    departments_df = read_table("departments")
    shifts_df = read_table("shifts")
    workers_df = read_table("workers")
    
    # Ensure required columns exist in Workers DataFrame
    if 'Active' not in workers_df.columns:
        workers_df['Active'] = True
    if 'Section' not in workers_df.columns:
        workers_df['Section'] = ''
    if 'Department' not in workers_df.columns:
        workers_df['Department'] = ''
    if 'Shift' not in workers_df.columns:
        workers_df['Shift'] = ''

    # ---------- TAB 1: Mark Attendance ----------
    with tab1:
        st.subheader("✅ Mark Attendance")
        
        # Date selector for marking attendance (past or future)
        mark_date = st.date_input("Select Date for Attendance", datetime.date.today(), key="mark_date")
        
        col1, col2 = st.columns(2)
        with col1:
            selected_section = st.selectbox("Select Section", ["All"] + (sections_df['Name'].tolist() if not sections_df.empty else []), key="mark_section")
            
            # Filter departments based on selected section
            if selected_section != "All" and not sections_df.empty:
                section_id = sections_df[sections_df['Name'] == selected_section]['ID'].values[0]
                dept_options = departments_df[departments_df['Section_ID'] == section_id]['Name'].tolist() if not departments_df.empty else []
            else:
                dept_options = ["All"]
            
            selected_department = st.selectbox("Select Department", dept_options, key="mark_department")
            
        with col2:
            selected_shift = st.selectbox("Select Shift", ["All"] + (shifts_df['Name'].tolist() if not shifts_df.empty else []), key="mark_shift")

        # Filter workers based on selection
        wdf = read_table("workers")
        # Ensure required columns exist
        if 'Active' not in wdf.columns:
            wdf['Active'] = True
        if 'Section' not in wdf.columns:
            wdf['Section'] = ''
        if 'Department' not in wdf.columns:
            wdf['Department'] = ''
        if 'Shift' not in wdf.columns:
            wdf['Shift'] = ''
        wdf['Active'] = wdf['Active'].astype(str)
        filtered = wdf.copy()
        
        # Apply filters only if columns exist
        if selected_section != "All" and 'Section' in filtered.columns:
            filtered = filtered[filtered['Section'] == selected_section]
        if selected_department != "All" and 'Department' in filtered.columns:
            filtered = filtered[filtered['Department'] == selected_department]
        if selected_shift != "All" and 'Shift' in filtered.columns:
            filtered = filtered[filtered['Shift'] == selected_shift]
        filtered = filtered[filtered['Active'].str.lower().isin(['true','1','yes'])]

        if filtered.empty:
            st.info("No active workers for selected filters.")
        else:
            st.write(f"### 📋 Mark Attendance for {mark_date.strftime('%B %d, %Y')} ({len(filtered)} workers)")
            
            # Check if attendance already exists for this date and workers
            att_df = read_table("attendance")
            
            # Only process if 'Date' column exists
            if not att_df.empty and 'Date' in att_df.columns:
                att_df['Date'] = pd.to_datetime(att_df['Date']).dt.date
                
                # Get existing attendance for the selected date and workers
                existing_att = att_df[
                    (att_df['Date'] == mark_date) &
                    (att_df['Worker_ID'].isin(filtered['ID'].astype(str)))
                ]
            else:
                existing_att = pd.DataFrame()
            
            # For marking attendance, render radio widgets
            with st.form("mark_attendance_form"):
                statuses = {}
                for _, worker in filtered.iterrows():
                    worker_id_str = str(worker['ID'])
                    worker_name = worker['Name']
                    worker_section = worker.get('Section', '')
                    worker_department = worker.get('Department', '')
                    worker_shift = worker.get('Shift', '')
                    
                    # Check if attendance already exists for this worker
                    if not existing_att.empty and 'Worker_ID' in existing_att.columns:
                        worker_att = existing_att[existing_att['Worker_ID'] == worker_id_str]
                        if not worker_att.empty and 'Status' in worker_att.columns:
                            current_status = worker_att.iloc[0]['Status']
                            default_idx = ["Present", "Absent", "Late", "Leave"].index(current_status) if current_status in ["Present", "Absent", "Late", "Leave"] else 0
                        else:
                            default_idx = 0
                    else:
                        default_idx = 0
                    
                    st.write(f"**{worker_name}** - {worker_section} / {worker_department} / {worker_shift}")
                    status = st.radio("Status", ["Present","Absent","Late","Leave"], index=default_idx, key=f"stat_{worker['ID']}", horizontal=True, label_visibility="collapsed")
                    statuses[int(worker['ID'])] = {'name': worker_name, 'status': status, 'section': worker_section, 'department': worker_department, 'shift': worker_shift}
                
                if st.form_submit_button("Submit Attendance"):
                    # Initialize att_df if it's empty
                    if att_df.empty:
                        att_df = pd.DataFrame(columns=['ID','Worker_ID','Worker_Name','Date','Section','Department','Shift','Status','Timestamp'])
                    
                    next_id = int(att_df['ID'].max())+1 if not att_df.empty and 'ID' in att_df.columns else 1
                    date_str = mark_date.strftime('%Y-%m-%d')
                    new_records = []
                    
                    for wid, info in statuses.items():
                        worker_id_str = str(wid)
                        # Check if this record already exists
                        if not existing_att.empty and 'Worker_ID' in existing_att.columns:
                            existing_record = existing_att[existing_att['Worker_ID'] == worker_id_str]
                            
                            if not existing_record.empty:
                                # Update existing record
                                record_id = existing_record.iloc[0]['ID']
                                att_df.loc[att_df['ID'] == record_id, 'Status'] = info['status']
                                att_df.loc[att_df['ID'] == record_id, 'Timestamp'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            else:
                                # Add new record
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
                            # Add new record
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
                    
                    if write_table("attendance", att_df):
                        st.success(f"Updated attendance for {len(filtered)} workers")
                        st.rerun()

    # ---------- TAB 2: Attendance Register ----------
    with tab2:
        st.subheader("📊 Attendance Register")
        
        # Date selector for viewing attendance register
        reg_date = st.date_input("Select Date for Register", datetime.date.today(), key="reg_date")
        
        col1, col2 = st.columns(2)
        with col1:
            reg_section = st.selectbox("Select Section", ["All"] + (sections_df['Name'].tolist() if not sections_df.empty else []), key="reg_section")
            
            # Filter departments based on selected section
            if reg_section != "All" and not sections_df.empty:
                section_id = sections_df[sections_df['Name'] == reg_section]['ID'].values[0]
                dept_options = departments_df[departments_df['Section_ID'] == section_id]['Name'].tolist() if not departments_df.empty else []
            else:
                dept_options = ["All"]
            
            reg_department = st.selectbox("Select Department", dept_options, key="reg_department")
            
        with col2:
            reg_shift = st.selectbox("Select Shift", ["All"] + (shifts_df['Name'].tolist() if not shifts_df.empty else []), key="reg_shift")
        
        # Get attendance data
        att = read_table("attendance")
        if not att.empty:
            # Check if 'Date' column exists
            if 'Date' in att.columns:
                att['Date'] = pd.to_datetime(att['Date']).dt.date
                filtered = att[att['Date'] == reg_date]
                
                if reg_section != "All" and 'Section' in filtered.columns:
                    filtered = filtered[filtered['Section'] == reg_section]
                if reg_department != "All" and 'Department' in filtered.columns:
                    filtered = filtered[filtered['Department'] == reg_department]
                if reg_shift != "All" and 'Shift' in filtered.columns:
                    filtered = filtered[filtered['Shift'] == reg_shift]
                
                if not filtered.empty:
                    st.write(f"### Attendance Register for {reg_date.strftime('%B %d, %Y')}")
                    
                    # Create a copy for editing
                    editable_df = filtered.copy()
                    
                    # Add an edit column
                    editable_df['Edit'] = False
                    
                    # Display the dataframe with an edit checkbox
                    edited_df = st.data_editor(
                        editable_df[['Worker_Name', 'Section', 'Department', 'Shift', 'Status', 'Timestamp', 'Edit']],
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
                    
                    # Get records marked for editing
                    records_to_edit = edited_df[edited_df['Edit'] == True]
                    
                    if not records_to_edit.empty:
                        st.subheader("Edit Selected Records")
                        
                        # Create a form for editing
                        with st.form("edit_attendance_form"):
                            for idx, record in records_to_edit.iterrows():
                                worker_id = record['Worker_ID'] if 'Worker_ID' in record else ""
                                worker_name = record['Worker_Name']
                                current_status = record['Status']
                                
                                st.write(f"**{worker_name}** (ID: {worker_id})")
                                
                                # Get the original record to find its index in the dataframe
                                original_record = filtered[filtered['Worker_Name'] == worker_name]
                                if not original_record.empty:
                                    record_id = original_record.iloc[0]['ID']
                                    
                                    # Create a radio button for status selection
                                    new_status = st.radio(
                                        "Select New Status",
                                        ["Present", "Absent", "Late", "Leave"],
                                        index=["Present", "Absent", "Late", "Leave"].index(current_status) if current_status in ["Present", "Absent", "Late", "Leave"] else 0,
                                        key=f"edit_status_{record_id}"
                                    )
                                    
                                    # Store the new status in session state
                                    if f"edit_status_{record_id}" not in st.session_state:
                                        st.session_state[f"edit_status_{record_id}"] = current_status
                                    else:
                                        st.session_state[f"edit_status_{record_id}"] = new_status
                                
                                st.divider()
                            
                            if st.form_submit_button("Save Changes"):
                                # Update the attendance records
                                att_df = read_table("attendance")
                                
                                for idx, record in records_to_edit.iterrows():
                                    worker_name = record['Worker_Name']
                                    original_record = filtered[filtered['Worker_Name'] == worker_name]
                                    
                                    if not original_record.empty:
                                        record_id = original_record.iloc[0]['ID']
                                        new_status = st.session_state[f"edit_status_{record_id}"]
                                        
                                        # Update the status and timestamp
                                        att_df.loc[att_df['ID'] == record_id, 'Status'] = new_status
                                        att_df.loc[att_df['ID'] == record_id, 'Timestamp'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                
                                # Save the updated dataframe
                                if write_table("attendance", att_df):
                                    st.success("Attendance records updated successfully!")
                                    st.rerun()
                    
                    # stats
                    total = len(filtered)
                    present = len(filtered[filtered['Status']=='Present'])
                    absent = len(filtered[filtered['Status']=='Absent'])
                    late = len(filtered[filtered['Status']=='Late'])
                    leave = len(filtered[filtered['Status']=='Leave'])
                    col1,col2,col3,col4 = st.columns(4)
                    with col1: st.metric("Present", present, f"{present/total*100:.1f}%")
                    with col2: st.metric("Absent", absent, f"{absent/total*100:.1f}%")
                    with col3: st.metric("Late", late, f"{late/total*100:.1f}%")
                    with col4: st.metric("Leave", leave, f"{leave/total*100:.1f}%")
                    
                    # Download CSV
                    csv = filtered.to_csv(index=False).encode('utf-8')
                    st.download_button("📥 Download Attendance CSV", csv, file_name=f"attendance_{reg_date}.csv")
                else:
                    st.info("No attendance records for selected filters.")
            else:
                st.error("Attendance data is missing the 'Date' column. Please check your data structure.")
        else:
            st.info("No attendance data")

    # ---------- TAB 3: Transfer Workers ----------
    with tab3:
        st.subheader("🔄 Transfer Workers")
        wdf = read_table("workers")
        # Ensure required columns exist
        if 'Active' not in wdf.columns:
            wdf['Active'] = True
        if 'Section' not in wdf.columns:
            wdf['Section'] = ''
        if 'Department' not in wdf.columns:
            wdf['Department'] = ''
        if 'Shift' not in wdf.columns:
            wdf['Shift'] = ''
        if not wdf.empty:
            active = wdf[wdf['Active'].astype(str).str.lower().isin(['true','1','yes'])]
            if not active.empty:
                sel = st.selectbox("Select Worker", active['Name'].tolist(), key="transfer_worker")
                row = active[active['Name']==sel].iloc[0]
                st.write(f"Current: {row.get('Section', '')} / {row.get('Department', '')} - {row.get('Shift', '')}")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    new_section = st.selectbox("New Section", sections_df['Name'].tolist(), key="new_section")
                    
                    # Filter departments based on selected section
                    if new_section and not sections_df.empty:
                        section_id = sections_df[sections_df['Name'] == new_section]['ID'].values[0]
                        dept_options = departments_df[departments_df['Section_ID'] == section_id]['Name'].tolist() if not departments_df.empty else []
                    else:
                        dept_options = []
                    
                    new_department = st.selectbox("New Department", dept_options, key="new_department")
                    
                with col2:
                    new_shift = st.selectbox("New Shift", shifts_df['Name'].tolist(), key="new_shift")
                    
                with col3:
                    st.write("")  # Spacer for alignment
                
                if st.button("Transfer Worker", key="transfer_btn"):
                    wdf.loc[wdf['ID']==row['ID'],'Section'] = new_section
                    wdf.loc[wdf['ID']==row['ID'],'Department'] = new_department
                    wdf.loc[wdf['ID']==row['ID'],'Shift'] = new_shift
                    write_table("workers", wdf)
                    st.success("Transferred")
            else:
                st.info("No active workers")
        else:
            st.info("No workers found")

    # ---------- TAB 4: Manage Workers ----------
    with tab4:
        st.subheader("👥 Manage Workers")
        wdf = read_table("workers")
        # Ensure required columns exist
        if 'Active' not in wdf.columns:
            wdf['Active'] = True
        if 'Section' not in wdf.columns:
            wdf['Section'] = ''
        if 'Department' not in wdf.columns:
            wdf['Department'] = ''
        if 'Shift' not in wdf.columns:
            wdf['Shift'] = ''
        if not wdf.empty:
            for _, w in wdf.iterrows():
                with st.expander(f"{'✅' if str(w['Active']).lower() in ['true','1','yes'] else '❌'} {w['Name']} - {w.get('Section', '')} / {w.get('Department', '')} ({w.get('Shift', '')})"):
                    st.write(f"ID: {w['ID']}")
                    st.write(f"Section: {w.get('Section', '')} | Department: {w.get('Department', '')} | Shift: {w.get('Shift', '')}")
                    col1,col2 = st.columns([3,1])
                    with col1:
                        if str(w['Active']).lower() in ['true','1','yes']:
                            if st.button("Deactivate", key=f"sup_deact_{w['ID']}"):
                                df = read_table("workers")
                                # Ensure required columns exist
                                if 'Active' not in df.columns:
                                    df['Active'] = True
                                if 'Section' not in df.columns:
                                    df['Section'] = ''
                                if 'Department' not in df.columns:
                                    df['Department'] = ''
                                if 'Shift' not in df.columns:
                                    df['Shift'] = ''
                                df.loc[df['ID']==w['ID'],'Active'] = False
                                write_table("workers", df)
                                st.rerun()
                        else:
                            if st.button("Activate", key=f"sup_act_{w['ID']}"):
                                df = read_table("workers")
                                # Ensure required columns exist
                                if 'Active' not in df.columns:
                                    df['Active'] = True
                                if 'Section' not in df.columns:
                                    df['Section'] = ''
                                if 'Department' not in df.columns:
                                    df['Department'] = ''
                                if 'Shift' not in df.columns:
                                    df['Shift'] = ''
                                df.loc[df['ID']==w['ID'],'Active'] = True
                                write_table("workers", df)
                                st.rerun()
                    with col2:
                        if st.button("🗑️ Delete", key=f"sup_del_{w['ID']}"):
                            df = read_table("workers")
                            df = df[df['ID'] != w['ID']]
                            write_table("workers", df)
                            st.rerun()
        else:
            st.info("No workers found")

    # ---------- TAB 5: View Attendance ----------
    with tab5:
        st.subheader("📅 View Attendance")
        att = read_table("attendance")
        if not att.empty:
            # Check if 'Date' column exists
            if 'Date' in att.columns:
                att['Date'] = pd.to_datetime(att['Date']).dt.date
                view_date = st.date_input("Date", datetime.date.today(), key="sup_view_date")
                view_section = st.selectbox("Section", ["All"] + (sections_df['Name'].tolist() if not sections_df.empty else []), key="sup_view_section")
                
                # Filter departments based on selected section
                if view_section != "All" and not sections_df.empty:
                    section_id = sections_df[sections_df['Name'] == view_section]['ID'].values[0]
                    dept_options = departments_df[departments_df['Section_ID'] == section_id]['Name'].tolist() if not departments_df.empty else []
                else:
                    dept_options = ["All"]
                
                view_department = st.selectbox("Department", dept_options, key="sup_view_department")
                view_shift = st.selectbox("Shift", ["All"] + (shifts_df['Name'].tolist() if not shifts_df.empty else []), key="sup_view_shift")
                
                filtered = att[att['Date'] == view_date]
                if view_section != "All" and 'Section' in filtered.columns:
                    filtered = filtered[filtered['Section'] == view_section]
                if view_department != "All" and 'Department' in filtered.columns:
                    filtered = filtered[filtered['Department'] == view_department]
                if view_shift != "All" and 'Shift' in filtered.columns:
                    filtered = filtered[filtered['Shift'] == view_shift]
                if not filtered.empty:
                    st.write(f"### Attendance Register - {view_date.strftime('%B %d, %Y')}")
                    st.dataframe(filtered[['Worker_Name','Section','Department','Shift','Status','Timestamp']], use_container_width=True)
                    # stats
                    total = len(filtered)
                    present = len(filtered[filtered['Status']=='Present'])
                    absent = len(filtered[filtered['Status']=='Absent'])
                    late = len(filtered[filtered['Status']=='Late'])
                    leave = len(filtered[filtered['Status']=='Leave'])
                    col1,col2,col3,col4 = st.columns(4)
                    with col1: st.metric("Present", present, f"{present/total*100:.1f}%")
                    with col2: st.metric("Absent", absent, f"{absent/total*100:.1f}%")
                    with col3: st.metric("Late", late, f"{late/total*100:.1f}%")
                    with col4: st.metric("Leave", leave, f"{leave/total*100:.1f}%")
                else:
                    st.info("No records found")
            else:
                st.error("Attendance data is missing the 'Date' column. Please check your data structure.")
        else:
            st.info("No attendance data")

    # ---------- TAB 6: Attendance Grid ----------
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
        
        # Generate attendance grid
        grid_df = generate_attendance_grid(year, month)
        
        if not grid_df.empty:
            # Apply custom CSS for the grid
            st.markdown('<div class="attendance-grid">', unsafe_allow_html=True)
            
            # Display the grid
            st.dataframe(
                grid_df,
                use_container_width=True,
                column_config={
                    "Name": st.column_config.TextColumn("Name", width="medium"),
                    "Section": st.column_config.TextColumn("Section", width="small"),
                    "Department": st.column_config.TextColumn("Department", width="small"),
                    "Shift": st.column_config.TextColumn("Shift", width="small"),
                    "Present Days": st.column_config.NumberColumn("Present Days", format="%d"),
                    "Attendance %": st.column_config.NumberColumn("Attendance %", format="%.1f%%")
                }
            )
            
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Export button
            excel_bytes = dataframe_to_excel_bytes(grid_df)
            st.download_button(
                "📥 Download Attendance Grid", 
                data=excel_bytes, 
                file_name=f"attendance_grid_{year}_{month}.xlsx", 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("No attendance data available for the selected period.")

# ==================== HR DASHBOARD ====================
def hr_dashboard():
    st.title("📊 HR Dashboard")
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Daily","📅 Monthly","👥 Directory", "📊 Attendance Grid"])
    sections_df = read_table("sections")
    departments_df = read_table("departments")
    workers_df = read_table("workers")
    attendance_df = read_table("attendance")
    
    # Ensure required columns exist in Workers DataFrame
    if 'Active' not in workers_df.columns:
        workers_df['Active'] = True
    if 'Section' not in workers_df.columns:
        workers_df['Section'] = ''
    if 'Department' not in workers_df.columns:
        workers_df['Department'] = ''
    if 'Shift' not in workers_df.columns:
        workers_df['Shift'] = ''

    with tab1:
        st.subheader("📊 Daily Attendance")
        view_date = st.date_input("Date", datetime.date.today(), key="hr_daily_date")
        if not attendance_df.empty:
            # Check if 'Date' column exists
            if 'Date' in attendance_df.columns:
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
                st.error("Attendance data is missing the 'Date' column. Please check your data structure.")
        else:
            st.info("No attendance data")

    with tab2:
        st.subheader("📅 Monthly Analysis")
        year = st.selectbox("Year", list(range(2023, datetime.date.today().year+2)), 
                             index=list(range(2023, datetime.date.today().year+2)).index(datetime.date.today().year),
                             key="hr_monthly_year")
        month = st.selectbox("Month", list(range(1,13)), 
                             index=datetime.date.today().month-1,
                             key="hr_monthly_month")
        if not attendance_df.empty:
            # Check if 'Date' column exists
            if 'Date' in attendance_df.columns:
                attendance_df['Date'] = pd.to_datetime(attendance_df['Date'])
                monthly = attendance_df[
                    (attendance_df['Date'].dt.year == year) & 
                    (attendance_df['Date'].dt.month == month)
                ]
                if not monthly.empty:
                    # Group by worker and calculate attendance
                    worker_stats = monthly.groupby('Worker_Name').agg(
                        Present=('Status', lambda x: (x=='Present').sum()),
                        Absent=('Status', lambda x: (x=='Absent').sum()),
                        Late=('Status', lambda x: (x=='Late').sum()),
                        Leave=('Status', lambda x: (x=='Leave').sum()),
                        Total=('Status', 'count')
                    ).reset_index()
                    
                    # Calculate attendance percentage
                    worker_stats['Attendance %'] = (worker_stats['Present'] / worker_stats['Total'] * 100).round(1)
                    
                    # Merge with worker details
                    worker_details = workers_df[['Name', 'Section', 'Department', 'Shift']].copy()
                    worker_stats = worker_stats.merge(
                        worker_details, 
                        left_on='Worker_Name', 
                        right_on='Name', 
                        how='left'
                    ).drop('Name', axis=1)
                    
                    st.dataframe(worker_stats, use_container_width=True)
                    
                    # Overall stats
                    total_records = len(monthly)
                    total_present = len(monthly[monthly['Status']=='Present'])
                    total_absent = len(monthly[monthly['Status']=='Absent'])
                    total_late = len(monthly[monthly['Status']=='Late'])
                    total_leave = len(monthly[monthly['Status']=='Leave'])
                    
                    col1,col2,col3,col4 = st.columns(4)
                    with col1: st.metric("Total Records", total_records)
                    with col2: st.metric("Present", total_present, f"{total_present/total_records*100:.1f}%")
                    with col3: st.metric("Absent", total_absent, f"{total_absent/total_records*100:.1f}%")
                    with col4: st.metric("Late", total_late, f"{total_late/total_records*100:.1f}%")
                    
                    # Download CSV
                    csv = worker_stats.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        "📥 Download Monthly Report", 
                        csv, 
                        file_name=f"monthly_attendance_{year}_{month}.csv"
                    )
                else:
                    st.info("No attendance records for selected month")
            else:
                st.error("Attendance data is missing the 'Date' column. Please check your data structure.")
        else:
            st.info("No attendance data")

    with tab3:
        st.subheader("👥 Worker Directory")
        if not workers_df.empty:
            # Filter active workers
            workers_df['Active'] = workers_df['Active'].astype(str)
            active_workers = workers_df[workers_df['Active'].str.lower().isin(['true','1','yes'])]
            
            if not active_workers.empty:
                st.dataframe(
                    active_workers[['Name', 'Section', 'Department', 'Shift']], 
                    use_container_width=True,
                    column_config={
                        "Name": st.column_config.TextColumn("Name"),
                        "Section": st.column_config.TextColumn("Section"),
                        "Department": st.column_config.TextColumn("Department"),
                        "Shift": st.column_config.TextColumn("Shift")
                    },
                    hide_index=True
                )
                
                # Export button
                excel_bytes = dataframe_to_excel_bytes(active_workers[['Name', 'Section', 'Department', 'Shift']])
                st.download_button(
                    "📥 Download Worker Directory", 
                    data=excel_bytes, 
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
        
        # Generate attendance grid
        grid_df = generate_attendance_grid(year, month)
        
        if not grid_df.empty:
            # Apply custom CSS for the grid
            st.markdown('<div class="attendance-grid">', unsafe_allow_html=True)
            
            # Display the grid
            st.dataframe(
                grid_df,
                use_container_width=True,
                column_config={
                    "Name": st.column_config.TextColumn("Name", width="medium"),
                    "Section": st.column_config.TextColumn("Section", width="small"),
                    "Department": st.column_config.TextColumn("Department", width="small"),
                    "Shift": st.column_config.TextColumn("Shift", width="small"),
                    "Present Days": st.column_config.NumberColumn("Present Days", format="%d"),
                    "Attendance %": st.column_config.NumberColumn("Attendance %", format="%.1f%%")
                }
            )
            
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Export button
            excel_bytes = dataframe_to_excel_bytes(grid_df)
            st.download_button(
                "📥 Download Attendance Grid", 
                data=excel_bytes, 
                file_name=f"attendance_grid_{year}_{month}.xlsx", 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("No attendance data available for the selected period.")

# ==================== MAIN APP ====================
def main():
    # Apply mobile responsive CSS
    st.markdown(mobile_responsive_css(), unsafe_allow_html=True)
    
    # Initialize system if needed
    initialize_system()
    
    # Check login status
    if not st.session_state.logged_in:
        login_page()
    else:
        # Sidebar with logout
        with st.sidebar:
            st.write(f"Logged in as: **{st.session_state.username}** ({st.session_state.role})")
            if st.button("Logout"):
                st.session_state.logged_in = False
                st.session_state.username = None
                st.session_state.role = None
                st.session_state.user_id = None
                st.rerun()
        
        # Role-based dashboard
        if st.session_state.role == "Admin":
            admin_dashboard()
        elif st.session_state.role == "Supervisor":
            supervisor_dashboard()
        elif st.session_state.role == "HR":
            hr_dashboard()
        else:
            st.error("Invalid role. Please contact administrator.")

if __name__ == "__main__":
    main()